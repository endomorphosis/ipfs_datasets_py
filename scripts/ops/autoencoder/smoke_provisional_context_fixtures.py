#!/usr/bin/env python3
"""Build all Legal/UI companion projections without claiming source qualification.

The exact underspecified originals remain negative controls. Explicit synthetic
premises make their companion lowerings executable; training reviews/floors are
reported separately and never synthesized by this runner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _lake_counts(executions):
    return {"actual_lake_build_count": sum(row.get("backend_executed") is True for row in executions),
        "successful_lake_build_count": sum(row.get("backend_executed") is True and row.get("status") == "passed"
                                           for row in executions)}


def _tool_pins(lake, java, jar):
    """Pin installed native binaries before Lake can launch a child tool."""
    found = shutil.which(str(lake))
    if not found:
        raise ValueError("installed native Lake executable required")
    native_lake = Path(found).resolve()
    binaries = [native_lake, native_lake.with_name("lean")]
    if java is not None:
        found_java = shutil.which(str(java))
        if not found_java:
            raise ValueError("installed native Java executable required")
        binaries.append(Path(found_java).resolve())
    native_magic = {b"\x7fELF", b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
                    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"}
    for path in binaries:
        if not path.is_file():
            raise ValueError("installed native tool missing: " + str(path))
        with path.open("rb") as stream:
            head = stream.read(4)
        if head not in native_magic and head[:2] != b"MZ":
            raise ValueError("native executable required; scripts and toolchain shims are not accepted")
    paths = binaries + ([Path(jar).resolve()] if jar is not None else [])
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def run(output, lake, *, java_executable=None, tla2tools_jar=None):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import provisional_context_panel as panel
    from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v5 as native
    from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v5 as policy
    from ipfs_datasets_py.logic.formalization.autoencoder import projection_context_audit as audit
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    tool_pins = _tool_pins(lake, java_executable, tla2tools_jar)
    results = {}
    executions = []
    for domain in panel.DOMAINS:
        directory = output / domain
        directory.mkdir()
        try:
            case_started = time.monotonic()
            case = panel.prepare_companion(domain)
            _write(directory / "fixture.json", case["fixture"])
            _write(directory / "original-targets.json", case["original_report"])
            _write(directory / "companion-targets.json", case["report"])
            original = native.prepare_native_family_lean(case["original_report"], source_inputs=case["original_source_inputs"])
            _write(directory / "original-native-preparation.json", original)
            blockers = {p["projection_id"]: p["reason"] for p in original["per_projection"] if not p["semantic_lowering_supported"]}
            if blockers != audit.BLOCKERS[domain]:
                raise ValueError("historical negative control changed")
            execution = native.build_native_family_lake(case["report"], source_inputs=case["source_inputs"],
                lake_executable=lake, output_directory=directory / "companion-native",
                java_executable=java_executable, tla2tools_jar=tla2tools_jar)
            receipt = execution.to_dict()
            executions.append(receipt["execution"])
            rows = receipt["per_projection"]
            observed_tools = {}
            if receipt["execution"].get("backend_executed") is True:
                observed_tools[str(Path(receipt["execution"]["command"][0]).resolve())] = receipt["execution"]["executable_sha256"]
            for projection in rows:
                for check in projection.get("additional_syntax_checks", []):
                    observed_tools.update({str(Path(path).resolve()): digest for path, digest in check.get("tool_sha256", {}).items()})
            if any(tool_pins.get(path) != digest for path, digest in observed_tools.items()):
                raise ValueError("native execution tool hashes differ from pinned binaries")
            observation = policy.validate_projection_report(case["report"], lake_execution=execution)
            validation = observation.to_dict()
            batch = policy.evaluate_projection_training_batch([observation], domain_id=domain, target_reports=[case["report"]])
            _write(directory / "validation.json", validation)
            _write(directory / "batch-validation.json", batch)
            checks = {
                "negative_control_preserved": blockers == audit.BLOCKERS[domain],
                "all_companion_projection_checks_passed": all(p["parser_status"] == p["lake_status"] == "passed" for p in rows),
                "every_projection_retained": {p["projection_id"] for p in rows} == {p["projection_id"] for p in case["report"]["projections"]},
                "same_projection_count": len(rows) == len(case["original_report"]["projections"]),
                "complete_family_inventory": len(case["report"]["family_inventory"]) == len(case["report"]["requested_families"]) == 40,
                "reviews_not_silently_supplied": bool(validation["family_blockers"]),
                "strict_training_still_blocked_without_complete_review": batch["strict_training_allowed"] is False,
            }
            result = {"domain_id": domain, "integration_passed": all(checks.values()), "checks": checks,
                "original_semantic_blockers": blockers, "companion_projection_count": len(rows),
                "passed_companion_projections": sum(p["parser_status"] == p["lake_status"] == "passed" for p in rows),
                "lake_command": receipt.get("execution", {}).get("command"),
                "lake_status": receipt.get("execution", {}).get("status"),
                "actual_lake_build": receipt["execution"].get("backend_executed") is True,
                "successful_lake_build": receipt["execution"].get("backend_executed") is True and receipt["execution"].get("status") == "passed",
                "execution_tool_sha256": observed_tools,
                "additional_syntax_checks": [{"projection_id": p["projection_id"], "checks": p["additional_syntax_checks"]}
                    for p in rows if p.get("additional_syntax_checks")],
                "strict_training_allowed": batch["strict_training_allowed"],
                "modality_floor_satisfied": batch["modality_floor_satisfied"],
                "all_source_projection_gates_passed": batch["all_source_projection_gates_passed"],
                "source_gate_blockers": validation["family_blockers"],
                "wall_seconds": time.monotonic() - case_started,
                "companion_fixture_sha256": case["fixture"]["fixture_sha256"], **panel.FALSE}
            _write(directory / "summary.json", result)
            results[domain] = result
            print(json.dumps({key: result[key] for key in ("domain_id", "integration_passed", "passed_companion_projections",
                "companion_projection_count", "strict_training_allowed", "wall_seconds")}), flush=True)
        except Exception:
            (directory / "failure.txt").write_text(traceback.format_exc())
            raise
    tool_pins_after = _tool_pins(lake, java_executable, tla2tools_jar)
    if tool_pins_after != tool_pins:
        raise ValueError("native tool changed during fixture smoke")
    summary = {"schema": "provisional-context-companion-smoke/v1", "results": results,
        "integration_passed": set(results) == set(panel.DOMAINS) and all(r["integration_passed"] for r in results.values()),
        "scope": "explicitly assumed fixture lowering; original negatives retained; no source fidelity or complete training gate claim",
        "original_source_count": 2, "companion_source_count": 2,
        "original_semantic_blocker_count": sum(len(r["original_semantic_blockers"]) for r in results.values()),
        "companion_projection_count": sum(r["companion_projection_count"] for r in results.values()),
        "passed_companion_projection_count": sum(r["passed_companion_projections"] for r in results.values()),
        **_lake_counts(executions), "tool_sha256": tool_pins, "tool_hashes_unchanged": True,
        "source_tree": str(ROOT), "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fixture_builder_sha256": hashlib.sha256(Path(panel.__file__).read_bytes()).hexdigest(),
        "tools": {"lake": lake, "java_executable": java_executable, "tla2tools_jar": tla2tools_jar},
        "total_wall_seconds": time.monotonic() - started, "download_calls": 0,
        "training_gates_changed": False, "cache_scope": "fresh native workspace for each companion", **panel.FALSE}
    _write(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lake", required=True)
    parser.add_argument("--java-executable")
    parser.add_argument("--tla2tools-jar")
    args = parser.parse_args()
    result = run(args.output, args.lake, java_executable=args.java_executable, tla2tools_jar=args.tla2tools_jar)
    raise SystemExit(0 if result["integration_passed"] else 1)
