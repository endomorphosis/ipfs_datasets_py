#!/usr/bin/env python3
"""Replay declared UI temporal, normative and cognitive coverage through Lake.

The cases are authored source declarations, never neural predictions. No model,
embedding, training run or checkpoint is opened. Every declared negative case
remains in the denominator. Native execution and strict gates are separate.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ("tests/fixtures/logic/ui_modal_logic_v1/cases.py",)
DECLARED_ROUTES = {
    "temporal": "ui_ux_ir/declared_state_logic/TFOL/v1",
    "tdfol": "ui_ux_ir/declared_state_logic/TDFOL/v1",
    "dcec": "ui_ux_ir/explicit_logic/bounded_dcec/v1",
}
TOOLS = {
    "lake": ("/home/barberb/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lake",
        "8c987aee79f105bc2ff21772b958b219c8921a51b8ca2df8af410a2b17bd8701"),
    "java": ("/home/barberb/.local/share/ipfs_datasets_py/theorem-provers/advisors/temurin-jdk/17.0.20+8/jdk/bin/java",
        "0cd543f9949605b5eccb1d2b98c2b8637bb0953f0b5087208393b4b7ded73c1a"),
    "tla": ("/home/barberb/.local/share/ipfs_datasets_py/theorem-provers/tlc/1.8.0/tla2tools.jar",
        "e22f8ffb4bacdea0a871f444dd94fe5fb0d8013b3388ae39e82e26f852c735d5"),
}
FALSE = dict(admitted=False, qualified=False, formalized=False, roundtrip_ok=False,
    source_semantics_verified=False, neural_inference_executed=False, training_executed=False,
    weights_loaded=False, embeddings_loaded=False, downloads_performed=False,
    checkpoint_promoted=False, fresh_holdout=False, constitution_formalized=False)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def load_fixture(relative):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location("coverage_fixture_" + sha(path)[:16], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    sys.dont_write_bytecode = True
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.logic.formalization.autoencoder import family_training as core
    from ipfs_datasets_py.logic.formalization.autoencoder import family_coverage_frontier_v2 as frontier
    from ipfs_datasets_py.logic.formalization.autoencoder import parallel_projection_checks_v4 as checks
    from ipfs_datasets_py.logic.formalization.autoencoder import resumable_native_validation_v2 as durable
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as token_owner
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources

    started = time.monotonic()
    tree = require_workspace_logic_tree()
    source_files = {str(p.relative_to(ROOT)): sha(p)
                    for p in sorted((ROOT / "ipfs_datasets_py").rglob("*"))
                    if p.is_file() and not p.is_symlink() and "__pycache__" not in p.parts}
    fixture_files = {relative: sha(ROOT / relative) for relative in FIXTURES}
    for key, (path, digest) in TOOLS.items():
        require(sha(path) == digest, "installed tool differs: " + key)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    catalog = list(core._families())
    require(len(catalog) == 40, "reviewed canonical family catalog changed")
    scheduled = [(relative, load_fixture(relative)) for relative in FIXTURES]
    cases = [(relative, module, row) for relative, module in scheduled for row in module.cases()]
    identities = [row["id"] for _, _, row in cases]
    require(len(identities) == len(set(identities)) and cases, "unique complete fixture schedule required")
    require(all(row["expected_disposition"] in {"prepared", "blocked"} for _, _, row in cases),
            "explicit predeclared fixture dispositions required")
    plan = {"schema": "declared-ui-modal-coverage-plan/v1", "scope": "authored_declarations_not_model_outputs",
        "logic_tree": tree, "source_files": source_files, "fixtures": fixture_files,
        "script_sha256": sha(__file__), "tools": TOOLS,
        "cases": [core._json(row) for _, _, row in cases], "requested_families": catalog,
        "native_max_workers": 2, "temperature": 0, "current_decoder_token_ceiling": 64,
        "target_truncation_allowed": False, "bridge_on_evaluation_ran": False,
        "native_artifact_cache": "fresh_job_workspaces_existing_installed_toolchain", **FALSE}
    save(output / "plan.json", plan)
    jobs, prepared, attempts = [], {}, []
    for relative, module, original in cases:
        row = deepcopy(original)
        encoded = raw(core._json(row))
        identity, domain = row["id"], row["domain"]
        # Count the exact current lexical codec; never truncate to make a row fit.
        lexical = token_owner._TOKEN.findall(token_owner._raw(row["candidate"]).decode())
        require("".join(lexical).encode() == token_owner._raw(row["candidate"]), "target codec lost bytes")
        record = {"id": identity, "domain": domain, "fixture": relative,
            "candidate_origin": row["candidate_origin"], "source_text": row["source_text"],
            "candidate": row["candidate"], "expected_disposition": row["expected_disposition"],
            "expected_reason": row.get("expected_reason"),
            "source_bytes": len(row["source_text"].encode()), "semantic_encoder_context_checked": False,
            "decoder_target_tokens_including_bos_eos": len(lexical) + 2,
            "fits_current_64_token_decoder": len(lexical) + 2 <= 64,
            "expected_declared_projection_ids": [projection_id for field, projection_id in DECLARED_ROUTES.items()
                if row["candidate"]["logic"][field] is not None],
            "candidate_rewritten": False, **FALSE}
        tick = time.monotonic()
        try:
            packet = module.prepare_case(row)
        except (ValueError, TypeError, KeyError) as error:
            record.update(status="blocked", error_type=type(error).__name__, reason=str(error))
        else:
            require(set(packet["report"]["requested_families"]) == set(catalog), "family request narrowed")
            require(packet["report"]["domain_id"] == domain, "case domain changed")
            prepared[identity] = packet
            native = checks.native.prepare_native_family_lean(packet["report"], source_inputs=packet["source_inputs"])
            record.update(status="prepared", target_report=packet["report"], source_audit=packet["audit"],
                source_adapter_audits=core._json({key: value for key, value in packet.items()
                    if key not in {"report", "source_inputs"}}),
                source_inputs=core._json(packet["source_inputs"]), native_preparation=native,
                coverage=frontier.diagnose_family_coverage(packet["report"], native_receipt=native))
            jobs.append(checks.NativeProjectionJob(identity, packet["report"], packet["source_inputs"]))
        record["preparation_wall_seconds"] = time.monotonic() - tick
        require(raw(core._json(row)) == encoded, "fixture or candidate mutated during preparation")
        save(output / "cases" / (identity + ".json"), record)
        attempts.append(record)
    save(output / "attempts.json", attempts)
    mismatches = [row["id"] for row in attempts if row["status"] != row["expected_disposition"]
        or row["status"] == "blocked" and row["expected_reason"] is not None
        and row["expected_reason"] not in row.get("reason", "")]
    require(not mismatches, "fixture disposition differs; preserved full attempts: " + repr(mismatches))
    require(jobs, "no prepared native jobs")
    native = durable.run_resumable_native_validation(jobs, owner=durable.NativeValidationOwner.from_module(checks),
        output_directory=output / "native-validation", scheduler=resources.get_global_resource_scheduler(),
        max_admission_seconds=300, max_attempts_per_job=3, retry_backoff_seconds=1,
        max_workers=2, native_memory_mb=1024, native_cpu_slots=2, native_child_process_slots=2,
        lease_wait_timeout_seconds=30, native_step_timeout_seconds=60,
        lake_executable=TOOLS["lake"][0], java_executable=TOOLS["java"][0], tla2tools_jar=TOOLS["tla"][0])
    gates, coverage, executions = {}, {}, {}
    for row in native["live_jobs"]:
        identity, report = row["job_id"], row["report"]
        receipt = checks.native.verify_native_family_lake(row["native_execution"], report)
        executions[identity] = receipt
        coverage[identity] = frontier.diagnose_family_coverage(report, native_receipt=receipt)
        gates[identity] = checks.validation.evaluate_projection_training_batch([row["observation"]],
            domain_id=report["domain_id"], target_reports=[report])
        require(gates[identity]["strict_training_allowed"] is False,
                "authored partial panel must not grant whole modality training")
    save(output / "native-executions.json", executions)
    save(output / "native-strict-gates.json", gates)
    save(output / "coverage.json", coverage)
    expected_new = {row["id"]: row["expected_declared_projection_ids"] for row in attempts if row["status"] == "prepared"}
    declared_checks = {}
    for identity, ids in expected_new.items():
        receipt = executions.get(identity)
        rows = [] if receipt is None else [row for row in receipt["per_projection"] if row["projection_id"] in ids]
        declared_checks[identity] = {
            "expected_projection_ids": ids,
            "exact_projection_inventory": sorted(row["projection_id"] for row in rows) == sorted(ids),
            "all_declared_parser_lowering_Lake_passed": bool(rows) and all(
                row["parser_status"] == row["lake_status"] == "passed" and row["semantic_lowering_supported"]
                and row["lowering"].get("capability_floor_eligible") is True for row in rows),
            **FALSE}
    save(output / "declared-native-checks.json", declared_checks)
    batch_gates = {}
    for domain in ("ui_ux_ir",):
        rows = [row for row in native["live_jobs"] if row["report"]["domain_id"] == domain]
        if rows:
            batch_gates[domain] = checks.validation.evaluate_projection_training_batch(
                [row["observation"] for row in rows], domain_id=domain,
                target_reports=[row["report"] for row in rows])
            require(batch_gates[domain]["strict_training_allowed"] is False,
                    "unreviewed catalog families cannot be silently waived across a batch")
    save(output / "native-batch-gates.json", batch_gates)
    for relative, digest in {**source_files, **fixture_files}.items():
        require(sha(ROOT / relative) == digest, "frozen producer changed: " + relative)
    loaded = {name: {"path": str(Path(module.__file__).resolve()), "sha256": sha(module.__file__)}
              for name, module in tuple(sys.modules.items())
              if name.startswith("ipfs_datasets_py") and getattr(module, "__file__", None)}
    require(all(Path(row["path"]).is_relative_to(ROOT) for row in loaded.values()), "drifted dependency tree")
    save(output / "loaded-modules.json", loaded)
    summary = {"schema": "declared-ui-modal-coverage-smoke/v1", "scope": plan["scope"],
        "attempt_count": len(attempts), "prepared_count": len(jobs), "blocked_count": len(attempts) - len(jobs),
        "live_native_count": len(executions), "native_receipt": native["receipt"],
        "strict_training_allowed_count": sum(row["strict_training_allowed"] for row in gates.values()),
        "elapsed_seconds": time.monotonic() - started, "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "rss_scope": "Python_parent_only_excludes_native_child_RSS", "all_frozen_sources_unchanged": True,
        "actual_Lake_pass_count": sum(row["execution"]["status"] == "passed" for row in executions.values()),
        "declared_projection_occurrences": sum(len(row["expected_projection_ids"]) for row in declared_checks.values()),
        "all_new_declarations_validated": all(row["exact_projection_inventory"] and
            row["all_declared_parser_lowering_Lake_passed"] for row in declared_checks.values()),
        "attempts": [{k: row[k] for k in ("id", "domain", "status", "expected_disposition", "preparation_wall_seconds",
             "decoder_target_tokens_including_bos_eos", "fits_current_64_token_decoder")} for row in attempts], **FALSE}
    save(output / "summary.json", summary)
    require(len(executions) == len(jobs), "native execution incomplete; see preserved receipts")
    require(summary["actual_Lake_pass_count"] == len(jobs), "actual Lake failures remain")
    require(summary["all_new_declarations_validated"], "new declared logic still lacks native parser/lowering/Lake evidence")
    require(batch_gates["ui_ux_ir"]["modality_floor_satisfied"] is True,
            "authored UI panel still lacks the unchanged minimum family floor")
    print(json.dumps({k: summary[k] for k in ("attempt_count", "prepared_count", "blocked_count", "actual_Lake_pass_count", "elapsed_seconds")}))


if __name__ == "__main__":
    main()
