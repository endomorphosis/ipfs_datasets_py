#!/usr/bin/env python3
"""Replay every selected source-only Intent instruction through learned effects.

A single freshly inferred Security candidate is shared across the instruction
population. Gold targets and stored embeddings are discarded before inference.
Each supported Intent prediction reaches the real supervisor consumer and Lean
checker, retaining satisfaction, counterexamples and disabled-input outcomes.
This is a bounded correctness replay, not a daemon run or throughput benchmark.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wire(value))


def file_record(path):
    path = Path(path).resolve()
    require(path.is_file(), "regular input/checkpoint file required")
    data = path.read_bytes()
    return dict(path=str(path), sha256=sha(data), bytes=len(data))


def source_instructions(path):
    """Project the input artifact to a closed source-only view before inference."""
    records = json.loads(Path(path).read_bytes())
    require(type(records) is list and 1 <= len(records) <= 256, "bounded instruction population required")
    sources = []
    for record in records:
        require(type(record) is dict and type(record.get("id")) is str
            and type(record.get("source_text")) is str and record["source_text"].strip()
            and record.get("split") == "test", "identified held-out source instruction required")
        text = record["source_text"]
        require(len(text.encode()) <= 8192, "bounded instruction text required")
        sources.append(dict(id=record["id"], instruction=text, source_sha256=sha(text.encode()), split="test"))
    require(len({row["id"] for row in sources}) == len(sources), "unique source instruction identities required")
    return sources


def capture_producers(datasets_root, accelerate_root):
    roots = {"datasets": datasets_root.resolve(), "accelerate": accelerate_root.resolve()}
    rows = []
    for name, module in sorted(sys.modules.items()):
        if not (name.startswith("ipfs_datasets_py.logic.")
                or name.startswith("ipfs_datasets_py.optimizers.logic_theorem_optimizer.")
                or name.startswith("ipfs_accelerate_py.agent_supervisor.runtime.")):
            continue
        source = getattr(module, "__file__", None)
        if not source:
            continue
        path = Path(source).resolve()
        require(path.is_file(), "imported producer has no regular source")
        repository = "accelerate" if name.startswith("ipfs_accelerate_py.") else "datasets"
        require(path.is_relative_to(roots[repository]), "imported producer is outside selected repository")
        rows.append(dict(repository=repository, module=name, path=path.relative_to(roots[repository]).as_posix(),
            sha256=sha(path.read_bytes())))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent-config", required=True, type=Path)
    parser.add_argument("--security-config", required=True, type=Path)
    parser.add_argument("--tests-file", required=True, type=Path)
    parser.add_argument("--source-inputs", required=True, type=Path)
    parser.add_argument("--lake", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-instructions", type=int, default=24)
    parser.add_argument("--left-parameter", default="capacity")
    parser.add_argument("--right-parameter", default="threshold")
    args = parser.parse_args(argv)
    require(not args.output.exists(), "fresh evidence output directory required")
    require(args.lake.is_absolute() and args.lake.is_file(), "explicit installed Lake executable required")
    require(1 <= args.expected_instructions <= 256, "bounded expected instruction count required")
    import torch
    from ipfs_accelerate_py.agent_supervisor.runtime import intent_384_advisor as intent_advisor
    from ipfs_accelerate_py.agent_supervisor.runtime import security_source_program_advisor_384 as security_advisor
    from ipfs_accelerate_py.agent_supervisor.runtime import intent_code_effect_advisor as consumer
    from ipfs_datasets_py.logic.formalization.autoencoder import intent_action_association as builder

    datasets_root = Path(__file__).resolve().parents[3]
    accelerate_root = Path(consumer.__file__).resolve().parents[3]
    before_modules = capture_producers(datasets_root, accelerate_root)
    sources = source_instructions(args.tests_file)
    require(len(sources) == args.expected_instructions, "complete expected instruction population required")
    code_sources = json.loads(args.source_inputs.read_bytes())
    require(type(code_sources) is list and len(code_sources) == 1, "exactly one shared original code source required")
    code_source = code_sources[0]
    require(set(code_source) == {"id", "source_text", "source_sha256"}
        and code_source["source_sha256"] == sha(code_source["source_text"].encode()), "exact original code source required")
    intent_config = json.loads(args.intent_config.read_bytes())
    security_config = json.loads(args.security_config.read_bytes())
    require(security_config.get("lake") is None, "Security preplanning must leave kernel checks to contract consumer")
    mapping = {"left": args.left_parameter, "right": args.right_parameter}
    domains = security_config["finite_state_domains"][code_source["id"]]
    require(domains == {name: dict(lower=-1, upper=1) for name in mapping.values()} and len(domains) == 2,
        "explicit two-parameter nine-case domains required")
    paths = [Path(__file__).resolve(), args.intent_config, args.security_config, args.tests_file,
        args.source_inputs, Path(intent_config["checkpoint_path"]), Path(security_config["checkpoint_path"])]
    before_files = [file_record(path) for path in paths]
    require(before_files[-2]["sha256"] == intent_config["checkpoint_sha256"]
        and before_files[-1]["sha256"] == security_config["checkpoint_sha256"], "selected checkpoint bytes differ")
    args.output.mkdir(parents=True)
    save(args.output / "source-only-instructions.json", sources)
    save(args.output / "source-inputs.json", code_sources)
    save(args.output / "intent-config.json", intent_config)
    save(args.output / "security-config.json", security_config)
    save(args.output / "input-references.json", dict(files=before_files,
        stored_targets_passed_to_inference=False, stored_embeddings_passed_to_inference=False,
        source_view_fields=["id", "instruction", "source_sha256", "split"]))
    save(args.output / "execution-environment.json", dict(embedding_device="cuda" if torch.cuda.is_available() else "cpu",
        cuda_visible_devices=os.environ.get("CUDA_VISIBLE_DEVICES"),
        scope="correctness replay with real numerical inference; no throughput claim"))
    security_started = time.monotonic()
    security = security_advisor.prepare_security_source_program_advice(config=security_config, source_rows=code_sources)
    save(args.output / "security-advice.json", security)
    require(security["status"] == "source_candidate_advice" and security["qualified_candidate_count"] == 1,
        "fresh shared Security inference did not produce one source-qualified candidate")
    require(len(security["inference"]["rows"]) == 1 and len(security["input_bindings"]) == 1,
        "shared Security prediction population changed")
    prediction = security["inference"]["rows"][0]
    require(security["input_bindings"] == [dict(source_id=code_source["id"], inference_id=prediction["id"],
        source_sha256=code_source["source_sha256"])] and prediction["source_sha256"] == code_source["source_sha256"],
        "raw Security candidate is not joined to the original code input")
    security_seconds = time.monotonic() - security_started
    results = []
    for index, source in enumerate(sources):
        directory = args.output / ("case-" + str(index).zfill(3))
        save(directory / "instruction.json", source)
        started = time.monotonic()
        result = dict(id=source["id"], source_sha256=source["source_sha256"], status="unsupported",
            intent_status=None, effect_status=None, case_count=0, enabled_case_count=0,
            finite_effects_kernel_checked=False, bounded_effects_satisfied=False, counterexample_kernel_checked=False,
            counterexample_case_indices=[], continue_planning=True, proof_authority=False,
            execution_authority=False, completion_authority=False, source_semantics_verified=False)
        try:
            advice = intent_advisor.prepare_intent_384_advice(instruction=source["instruction"], config=intent_config)
            save(directory / "intent-advice.json", advice)
            result["intent_status"] = advice["status"]
            require(advice["status"] == "semantic_candidate_advice" and advice["numerical_replay_verified"] is True,
                "learned Intent candidate did not pass numerical/source replay")
            bound = advice["report"]["binding"]["bound_candidate"]
            require(bound["document"] == advice["candidate_intent_ir"]
                and advice["raw_candidate_ir"] == advice["report"]["binding"]["candidate"],
                "raw prediction and provenance-bound document differ")
            association = builder.build_intent_action_association(source["instruction"], bound,
                code_source["source_text"], prediction["candidate_ir"], domains,
                action_id="action", input_parameter_mapping=mapping)
            save(directory / "association.json", association)
            selection = dict(schema=consumer.CONFIG_SCHEMA, contracts=[dict(id=source["id"],
                source_id=code_source["id"], input_domains=deepcopy(domains), association=association)],
                lake=dict(executable=str(args.lake), timeout_seconds=60))
            save(directory / "consumer-config.json", selection)
            checked = consumer.prepare_intent_code_effect_advice(instruction=source["instruction"], intent_advice=advice,
                security_advice=security, source_rows=code_sources, config=selection)
            save(directory / "consumer-advice.json", checked)
            require(all(checked[key] is False for key in consumer.FALSE)
                and checked["continue_planning"] is True, "consumer changed authority or fail-open scope")
            native = checked.get("native")
            if native is not None:
                (directory / "IntentCodeEffects.lean").write_bytes(native["lean_source"].encode())
            require(checked.get("live_build_verified") is True and checked.get("all_selected_contracts_checked") is True
                and native is not None and native["backend_executed"] is True and len(native["rows"]) == 1,
                "consumer did not check the complete actual contract: " + str(checked.get("failure_stage")))
            row = native["rows"][0]
            require(row["status"] == row["lake_status"] == "passed" and row["case_count"] == 9,
                "all nine bounded outcomes must be kernel checked")
            result.update(status="checked", consumer_status=checked["status"],
                **{key: row[key] for key in ("effect_status", "case_count", "enabled_case_count",
                    "finite_effects_kernel_checked", "bounded_effects_satisfied", "counterexample_kernel_checked")},
                counterexample_case_indices=row["contract"]["counterexample_case_indices"],
                raw_candidate_sha256=advice["raw_candidate_sha256"],
                bound_candidate_sha256=advice["report"]["binding"]["bound_candidate_sha256"],
                code_candidate_sha256=sha(wire(prediction["candidate_ir"])),
                intent_checkpoint_sha256=advice["checkpoint_sha256"],
                security_checkpoint_sha256=checked["security_checkpoint_sha256"])
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as error:
            result.update(error_type=type(error).__name__, reason=str(error)[:1024])
        result["elapsed_seconds"] = time.monotonic() - started
        save(directory / "result.json", result)
        results.append(result)
        print(json.dumps({key: result.get(key) for key in ("id", "status", "effect_status", "reason")}), flush=True)
    after_files = [file_record(path) for path in paths]
    after_modules = capture_producers(datasets_root, accelerate_root)
    indexed = {row["module"]: row for row in after_modules}
    require(after_files == before_files and all(indexed.get(row["module"]) == row for row in before_modules),
        "inputs, weights or imported producers changed during correctness replay")
    save(args.output / "producer-sources.json", dict(schema="learned-intent-action-producers/v1",
        modules=after_modules, script=file_record(__file__), before_files=before_files, after_files=after_files,
        unchanged=True, scope="listed imported native/runtime modules, script and inputs; excludes external libraries"))
    checked_count = sum(row["status"] == "checked" for row in results)
    summary = dict(schema="learned-intent-action-effect-checks/v1", status="passed" if checked_count == len(sources) else "partial",
        input_instruction_count=len(sources), checked_instruction_count=checked_count,
        unsupported_instruction_count=len(sources) - checked_count,
        distinct_security_sources=1, fresh_security_inference_calls=1, shared_code_source_sha256=code_source["source_sha256"],
        shared_code_candidate_sha256=sha(wire(prediction["candidate_ir"])),
        code_input_cases_per_instruction=9, total_bounded_instruction_cases=sum(row["case_count"] for row in results),
        effect_dispositions=dict(Counter(row["effect_status"] for row in results if row["status"] == "checked")),
        enabled_case_count=sum(row["enabled_case_count"] for row in results),
        counterexample_case_count=sum(len(row["counterexample_case_indices"]) for row in results),
        positive_satisfaction_count=sum(row["bounded_effects_satisfied"] for row in results),
        security_checkpoint_sha256=security_config["checkpoint_sha256"], intent_checkpoint_sha256=intent_config["checkpoint_sha256"],
        parameter_mapping=mapping, all_instructions_retained=len(results) == len(sources),
        inputs_and_weights_unchanged=True, all_supported_contracts_used_supervisor_consumer=True,
        stored_targets_passed_to_inference=False, stored_embeddings_passed_to_inference=False,
        provider_calls=0, training_steps=0, weights_changed=False, source_executed=False,
        terminal_bench_executed=False, full_daemon_executed=False, completion_authority=False, proof_authority=False,
        execution_authority=False, source_semantics_verified=False, whole_instruction_verified=False,
        scope="24 authored held-out source instructions over one shared learned Security candidate; selected finite action contracts only",
        timing_scope="diagnostic wall time only; not a throughput comparison", security_inference_seconds=security_seconds,
        rows=results)
    save(args.output / "summary.json", summary)
    print(json.dumps({key: summary[key] for key in ("status", "checked_instruction_count", "effect_dispositions",
        "total_bounded_instruction_cases", "positive_satisfaction_count")}), flush=True)
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
