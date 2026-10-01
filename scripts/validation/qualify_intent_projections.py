#!/usr/bin/env python3
"""Export Intent family projections and optionally run real Lean/TLA checks."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _read(path, maximum=4 * 1024 * 1024):
    with Path(path).open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("qualification input exceeds its byte bound")
    return json.loads(raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--intent-ir", type=Path)
    source.add_argument("--instruction-file", type=Path)
    parser.add_argument("--checkpoint-descriptor", type=Path)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--family", action="append")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check-lean", action="store_true")
    parser.add_argument("--lake-executable", default="lake")
    parser.add_argument("--lean-toolchain", help="Already-installed toolchain; never downloaded")
    parser.add_argument("--check-tla", action="store_true")
    parser.add_argument("--model-check", action="store_true", help="Also run bounded TLC TypeOK/deadlock checks")
    parser.add_argument("--tla-jar", type=Path)
    parser.add_argument("--java-executable", default="java")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args(argv)
    if not 1 <= args.timeout_seconds <= 60:
        parser.error("each tool invocation must be bounded to 1–60 seconds")
    if args.instruction_file and not args.checkpoint_descriptor:
        parser.error("an instruction requires an explicitly selected checkpoint descriptor")
    if args.intent_ir and args.checkpoint_descriptor:
        parser.error("a typed IntentIR input does not use a neural checkpoint")
    if (args.check_tla or args.model_check) and args.tla_jar is None:
        parser.error("TLA checking requires an explicitly selected local jar")
    from ipfs_datasets_py.logic.intent_ir.formalize.extended_projections import project_intent_families
    from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import validated_document, canonical_bytes
    from ipfs_datasets_py.logic.intent_ir.formalize.lean_projection import validate_lean_projection
    from ipfs_datasets_py.logic.intent_ir.formalize.state_projections import validate_tla_projection
    if args.instruction_file:
        from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import prepare_roundtrip_intent_instruction
        if args.instruction_file.stat().st_size > 65536:
            raise ValueError("bounded original instruction required")
        instruction = args.instruction_file.read_text()
        inference = prepare_roundtrip_intent_instruction(instruction, _read(args.checkpoint_descriptor, 32768))
        if inference["candidate_intent_ir"] is None:
            print(json.dumps({"status": "no_ir_candidate", "inference_status": inference["status"],
                              "continue_planning": True, "proof_authority": False}))
            return 2
        document = validated_document(inference["candidate_intent_ir"])
    else:
        inference = None
        document = validated_document(_read(args.intent_ir))
    context = _read(args.context) if args.context else None
    report = project_intent_families(document, context=context, requested_families=args.family)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    def write(name, value):
        (output / name).write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    write("intent-ir.json", document.to_dict())
    write("projections.json", report)
    if inference is not None:
        write("inference.json", inference)
        from ipfs_datasets_py.logic.intent_ir.formalize.projection_request import make_intent_projection_request
        request = make_intent_projection_request(instruction, document,
            checkpoint_sha256=inference["checkpoint_sha256"], context=context,
            requested_families=args.family)
        (output / "projection-request.json").write_bytes(canonical_bytes(request))
    checks = []
    for row in report["projections"]:
        representation = row["representation"]
        family, profile = row["family_id"], row["profile_id"]
        if family == "higher_order" and row["status"] != "unsupported":
            (output / "IntentProjection.lean").write_text(representation["source"])
        if profile == "tla_plus" and row["status"] != "unsupported":
            artifact = representation["qualification"]
            (output / (artifact["module_name"] + ".tla")).write_text(artifact["model_text"])
            (output / (artifact["module_name"] + ".cfg")).write_text(artifact["tlc_config_text"])
        if args.check_lean and family == "higher_order":
            checks.append(validate_lean_projection(row, document, lake_executable=args.lake_executable,
                toolchain=args.lean_toolchain, timeout_seconds=args.timeout_seconds))
        if (args.check_tla or args.model_check) and profile == "tla_plus":
            if row["status"] == "unsupported":
                checks.append({"schema": "intent-tla-qualification/v1", "status": "unsupported",
                               "reason": "no_supported_state_model", "proof_authority": False})
            else:
                checks.append(validate_tla_projection(row, args.tla_jar, document=document, context=context,
                    java_executable=args.java_executable, run_model_checker=args.model_check,
                    timeout_seconds=args.timeout_seconds))
    selected = {r["family_id"] for r in report["projections"]}
    if args.check_lean and "higher_order" not in selected:
        checks.append({"schema": "intent-lean-syntax-receipt/v1", "status": "not_run", "reason": "family_not_selected"})
    if (args.check_tla or args.model_check) and "transition_system" not in selected:
        checks.append({"schema": "intent-tla-qualification/v1", "status": "not_run", "reason": "family_not_selected"})
    write("syntax-checks.json", checks)
    summary = {"schema": "intent-projection-qualification/v1", "source_ir_sha256": report["source_ir_sha256"],
        "projections": [{"family": r["family_id"], "profile": r["profile_id"], "status": r["status"],
                         "unsupported_count": len(r["unsupported"])} for r in report["projections"]],
        "external_checks": [{"schema": r["schema"], "status": r["status"]} for r in checks],
        "all_requested_checks_passed": bool(checks) and all(r["status"] == "passed" for r in checks),
        "proof_authority": False, "source_semantics_verified": False, "program_correctness_verified": False,
        "files": [{"name": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
                  for p in sorted(output.iterdir()) if p.is_file()]}
    write("qualification.json", summary)
    print(json.dumps(summary, sort_keys=True))
    return 0 if not checks or summary["all_requested_checks_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
