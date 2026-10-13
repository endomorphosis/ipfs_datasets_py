"""Two predeclared temporal-head cells; execute only through the retained guardian.

The child receives training labels and source-only diagnostic rows. Reference
scoring occurs outside this process after both output bundles are frozen.
"""
from contextlib import ExitStack
import argparse
import ctypes.util
import hashlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import struct
import sys
import time
from unittest.mock import patch

F = Path(__file__).resolve().parent
N4 = F.parent / "legal-split-feature-20261013-01"
PRIOR_RUNNER = N4 / "run_split_features.py"
PRIOR_RUNNER_SHA = "abedfe1505c3c554deac3b79d6516062a0d8b4589510522f812ebee07ce2d19a"
RUN_ROOT = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01")
FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
PANELS = ("old_tune", "fresh_tune", "fresh_challenge", "old_authored_eval", "authored_dev", "authored_eval", "law")
COUNTS = dict(zip(PANELS, (96, 36, 36, 72, 72, 72, 8), strict=True))
CELLS = ("temporal-ce-control", "temporal-anchor-margin")
SOURCE_SHA = "95bd50a7cc6e25381ad126e3d955f0816c31470ec469fb22ceca297e35115035"
SOURCE_STATE_SHA = "fb63e61c7e2591259d40492b5ac5c020ae77f64c08e409d16b372ff7229b9aa5"
FALSE = dict(qualified=False, admitted=False, formalized=False, proof_authority=False,
             semantic_correctness_verified=False, promotion_performed=False)
STATE = dict(created_output=None, completed_updates=0, stage="preflight", in_progress_updates_unknown=False)


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink(), "Physical file required")
    before = path.stat()
    hashed = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            hashed.update(block)
            size += len(block)
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), "Input drift")
    return dict(path=str(path), bytes=size, sha256=hashed.hexdigest())


READ_PINS = {}


def read(path):
    path = Path(path)
    before = pin(path)
    require(before["bytes"] <= 32 * 1024 * 1024, "Bounded metadata required")
    raw = path.read_bytes()
    require(len(raw) == before["bytes"] and hashlib.sha256(raw).hexdigest() == before["sha256"] and pin(path) == before, "Consumed input drift")
    require(str(path) not in READ_PINS or READ_PINS[str(path)] == before, "Previous input drift")
    READ_PINS[str(path)] = before

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    def finite(value):
        parsed = float(value)
        require(math.isfinite(parsed), "Nonfinite JSON number")
        return parsed

    def reject(value):
        raise ValueError("Nonfinite JSON: " + value)

    return json.loads(raw, object_pairs_hook=unique, parse_float=finite, parse_constant=reject)


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return pin(Path(path))


def prior_runner():
    require(pin(PRIOR_RUNNER)["sha256"] == PRIOR_RUNNER_SHA, "Qualified shared runner helper changed")
    spec = importlib.util.spec_from_file_location("retained_split_runner_helpers", PRIOR_RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLAN_FIELDS = {"schema", "package_root", "runner_path", "guardian_path", "attempt_name", "cell",
    "source_owner_pins", "artifacts", "data_export", "source_checkpoint", "source_model_state_sha256",
    "context_contract", "training_manifest_sha256", "legacy_prefix_sha256", "source_reference_panels",
    "ctypes_dl_resolution", "forbidden_reference_paths", "resource_contract", "training_seconds",
    "diagnostic_panels", "reference_source_export", "reference_packet", "evaluation_contract", "proposal",
    "configured_dimension", "latent_enabled", "default_promotion", "Lake_executed"}


def validate_plan(plan):
    require(type(plan) is dict and set(plan) == PLAN_FIELDS and plan["schema"] == "temporal-adapter-cell-plan/v1", "Closed adapter plan required")
    require(plan["package_root"] == str(F / "datasets") and plan["runner_path"] == str(Path(__file__).resolve())
            and plan["guardian_path"] == str(F / "run_scope_guardian.py"), "Selected producer paths differ")
    require(plan["cell"] in CELLS and plan["attempt_name"] == "temporal-adapter-20261013-" + plan["cell"] + "-01", "Fixed cell/attempt required")
    require(plan["source_checkpoint"]["sha256"] == SOURCE_SHA and plan["source_checkpoint"]["bytes"] == 3592389
            and plan["source_model_state_sha256"] == SOURCE_STATE_SHA, "Exact completed N4 source required")
    require(plan["legacy_prefix_sha256"] == "4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995", "Exact historical training prefix required")
    require(plan["resource_contract"] == dict(cpu_slots=2, rss_mib=1536, child_slots=1, storage_bytes=200000000, deadline_seconds=300), "Unchanged resource envelope required")
    require(type(plan["training_seconds"]) is int and plan["training_seconds"] == 32
            and plan["configured_dimension"] == 384 and plan["latent_enabled"] is False
            and plan["default_promotion"] is False and plan["Lake_executed"] is False, "Fixed bounded source-only recipe required")
    require(plan["diagnostic_panels"] == [dict(name=name, count=COUNTS[name]) for name in PANELS], "Complete fixed source panels required")
    require(set(plan["source_reference_panels"]) == set(PANELS), "Exact N4 source reference panels required")
    for reference in plan["source_reference_panels"].values():
        require(type(reference) is dict and set(reference) == {"raw", "joint"}, "Closed source reference pair required")
        for descriptor in reference.values():
            require(set(descriptor) == {"path", "bytes", "sha256"} and
                    plan["artifacts"].get(descriptor["path"]) == {k: descriptor[k] for k in ("bytes", "sha256")},
                    "Source reference pair missing from artifact closure")
    require(plan["reference_source_export"]["path"] in plan["forbidden_reference_paths"]
            and plan["reference_packet"]["path"] in plan["forbidden_reference_paths"], "Diagnostic target containers must be forbidden")
    require(not set(plan["artifacts"]) & set(plan["forbidden_reference_paths"]), "Forbidden references in admitted input closure")
    for key in ("runner_path", "guardian_path"):
        require(plan[key] in plan["artifacts"], "Required producer missing")
    for descriptor in (plan["data_export"], plan["source_checkpoint"], plan["evaluation_contract"], plan["proposal"]):
        require(plan["artifacts"].get(descriptor["path"]) == {k: descriptor[k] for k in ("bytes", "sha256")}, "Required input absent from closure")


def validate_data(plan, data, helper):
    require(type(data) is dict and set(data) == {"schema", "training_rows", "training_metadata", "diagnostic_sources", "semantic_gold"}
            and data["schema"] == "temporal-adapter-source-only-diagnostics-export/v1" and data["semantic_gold"] is False,
            "Closed training/source-only export required")
    rows, metadata = data["training_rows"], data["training_metadata"]
    require(len(rows) == len(metadata) == 168 and digest(rows) == plan["training_manifest_sha256"]
            and digest(rows[:96]) == plan["legacy_prefix_sha256"], "Exact authenticated168 training rows required")
    require(digest(metadata[:96]) == "ad674072ee5026a0ae5ea0df270265785e00cf20fa4ca58c309d73ebb0d6fa72", "Historical training metadata differs")
    helper.validate_authored_pairs(rows[:96], metadata[:96], require_pairs=False)
    helper.validate_authored_pairs(rows[96:], metadata[96:])
    classes = ("plain_deadline", "condition_duration", "exception_duration", "actor_duration_name", "object_duration_title", "condition_exception_duration")
    for index, meta in enumerate(metadata[96:]):
        require(meta["class_name"] == classes[index // 12], "Matched class schedule differs")
    require(sum(bool(row["canonical_ir"]["rules"][0]["temporal"]) for row in rows[:96]) == 48
            and sum(bool(row["canonical_ir"]["rules"][0]["temporal"]) for row in rows[96:]) == 36, "Four temporal training strata differ")
    require(set(data["diagnostic_sources"]) == set(PANELS), "All source panels required")
    train_ids, train_texts = {r["id"] for r in rows}, {r["source_text"] for r in rows}
    require(len(train_ids) == len(train_texts) == 168, "Duplicate training input")
    for name in PANELS:
        incoming = data["diagnostic_sources"][name]
        require(len(incoming) == COUNTS[name] and len({r["id"] for r in incoming}) == COUNTS[name], "Diagnostic source coverage differs")
        for row in incoming:
            require(type(row) is dict and set(row) == {"id", "source_text", "latent"}, "Diagnostic references forbidden")
            require(type(row["id"]) is str and row["id"].strip() and type(row["source_text"]) is str and 0 < len(row["source_text"].strip()) <= 16384,
                    "Bounded exact diagnostic identity required")
            require(type(row["latent"]) is list and len(row["latent"]) == 384 and
                    all(type(v) in (int, float) and math.isfinite(v) for v in row["latent"]), "Finite dormant384 placeholder required")
        require(not train_ids & {r["id"] for r in incoming} and not train_texts & {r["source_text"] for r in incoming}, "Diagnostic input overlaps training")
    return rows


def binary(value):
    if type(value) is list:
        return b"".join(binary(v) for v in value)
    if type(value) is dict:
        return b"".join(binary(value[k]) for k in sorted(value))
    require(type(value) in (int, float) and math.isfinite(value), "Finite binary32 scores required")
    packed = struct.pack("!f", value)
    require(struct.unpack("!f", packed)[0] == value, "Saved score is not exact binary32")
    return packed


def diagnostics(torch, span, warm, adapter, joint, checkpoint, data, out, state):
    reports = []
    for name in PANELS:
        rows = data["diagnostic_sources"][name]
        raw = adapter.captured_inference(torch, span, warm, checkpoint, rows)
        raw_pin = write(out / (state + "-" + name + "-raw.json"), raw)
        selected = [dict(id=row["id"], result=joint.select_joint_spans(row["source_text"], capture["scores"], top_k=8, max_search_nodes=50000))
                    for row, capture in zip(rows, raw["occurrences"], strict=True)]
        joint_pin = write(out / (state + "-" + name + "-joint.json"), dict(schema="temporal-adapter-joint-panel/v1", rows=selected,
            top_k=8, max_search_nodes=50000, reference_scoring_performed=False, **FALSE))
        reports.append(dict(name=name, row_count=len(rows), raw=raw_pin, joint=joint_pin, score=None, has_authored_reference=False))
    return reports


def compare_scores(plan, data, panels, *, initial):
    records = []
    for name, fresh in zip(PANELS, panels, strict=True):
        require(fresh["name"] == name, "Panel order differs")
        descriptor = plan["source_reference_panels"][name]
        old = read(descriptor["raw"]["path"])
        new = read(fresh["raw"]["path"])
        require(READ_PINS[descriptor["raw"]["path"]] == descriptor["raw"] and READ_PINS[fresh["raw"]["path"]] == fresh["raw"], "Capture descriptor drift")
        old_joint = read(descriptor["joint"]["path"])["rows"] if initial else None
        new_joint = read(fresh["joint"]["path"])["rows"] if initial else None
        if initial:
            require(READ_PINS[descriptor["joint"]["path"]] == descriptor["joint"]
                    and READ_PINS[fresh["joint"]["path"]] == fresh["joint"], "Joint descriptor drift")
        require(len(old["occurrences"]) == len(new["occurrences"]) == COUNTS[name], "Complete score coverage required")
        for index, (source, a, b) in enumerate(zip(data["diagnostic_sources"][name], old["occurrences"], new["occurrences"], strict=True)):
            require(source["id"] == a["id"] == b["id"] and a["source_sha256"] == b["source_sha256"]
                    == hashlib.sha256(source["source_text"].encode()).hexdigest(), "Source score join differs")
            require(canonical(a["scores"]["tokens"]) == canonical(b["scores"]["tokens"]), "Token geometry differs")
            unchanged = {key: a["scores"][key] for key in ("modality_logits", "start_logits", "end_logits")}
            observed = {key: b["scores"][key] for key in unchanged}
            unchanged["presence_logits"] = {k: v for k, v in a["scores"]["presence_logits"].items() if initial or k != "temporal"}
            observed["presence_logits"] = {k: v for k, v in b["scores"]["presence_logits"].items() if initial or k != "temporal"}
            require(binary(unchanged) == binary(observed), "Frozen head component changed")
            if initial:
                keys = ("status", "reason", "canonical_ir", "span_diagnostics", "minimum_decision_logit_margin")
                before, after = old["inference"]["rows"][index], new["inference"]["rows"][index]
                require({k: before.get(k) for k in keys} == {k: after.get(k) for k in keys}, "Initial greedy parity differs")
                require(old_joint[index]["id"] == new_joint[index]["id"] == source["id"]
                        and old_joint[index]["result"] == new_joint[index]["result"], "Initial joint parity differs")
            records.append(dict(panel=name, id=source["id"], source_sha256=a["source_sha256"], binary32_sha256=hashlib.sha256(binary(unchanged)).hexdigest(), exact=True))
    require(len(records) == 392, "Complete392 head comparison required")
    return dict(schema="temporal-adapter-initial-parity/v1" if initial else "temporal-adapter-frozen-head-retention/v1",
        initial=initial, source_rows=392, all_compared_components_bit_equal=True, compared_temporal_presence=initial,
        greedy_and_joint_parity_checked=initial, rows=records, actual_extra_model_forwards=0, **FALSE)


def completion(checkpoint, report, schedule, rows, cell):
    require(report["optimizer_steps"] == 32 and report["stopped_reason"] == "step_limit"
            and checkpoint["progress"] == schedule["final_progress"], "Incomplete bounded comparison cell")
    trace = report["batch_trace"]
    require(trace["completed_updates"] == 32 and trace["training_count"] == 168 and trace["training_manifest_sha256"] == digest(rows)
            and [r["indices"] for r in trace["batches"]] == schedule["batch_indices"]
            and [r["ids"] for r in trace["batches"]] == schedule["batch_ids"]
            and [r["loss"] for r in trace["batches"]] == report["batch_losses"], "Actual returned update schedule differs")
    require(report["training_policy"]["objective"] == cell, "Actual objective differs from declared cell")
    partition = report["parameter_partition"]
    require(partition["trainable_parameter_names"] == ["temporal_presence.weight", "temporal_presence.bias"]
            and len(partition["model_parameter_names"]) == 36 and len(partition["frozen_parameter_names"]) == 34,
            "Only two temporal-head tensors may train")


def main(args):
    started = time.monotonic()
    plan = read(Path(args.plan))
    validate_plan(plan)
    out = Path(args.output)
    require(out.is_absolute() and out.resolve() == out and out == RUN_ROOT / plan["attempt_name"] / "results" and not out.exists(), "Fresh guardian output required")
    forbidden = set(plan["forbidden_reference_paths"])

    def audit(event, values):
        if event.startswith(("subprocess.", "os.exec", "os.spawn", "socket.")) or event in ("os.system", "os.fork"):
            raise ValueError("Process/network forbidden in training child: " + event)
        if event == "open" and isinstance(values[0], (str, bytes)):
            require(str(Path(os.fsdecode(values[0])).absolute()) not in forbidden, "Diagnostic reference container access forbidden")

    sys.addaudithook(audit)
    for path, expected in plan["artifacts"].items():
        actual = pin(Path(path))
        require({k: actual[k] for k in ("bytes", "sha256")} == expected, "Opening input drift: " + path)
    out.mkdir(mode=0o700)
    STATE["created_output"] = str(out)
    retained = prior_runner()
    helper = retained.helpers()
    sys.meta_path.insert(0, helper.NoEncoder())
    helper.bootstrap(Path(plan["package_root"]))
    prefix = "ipfs_datasets_py.optimizers.logic_theorem_optimizer."
    span = importlib.import_module(prefix + "legal_span_formula")
    warm = importlib.import_module(prefix + "legal_span_continuation")
    adapter = importlib.import_module(prefix + "legal_span_temporal_adapter")
    joint = importlib.import_module("ipfs_datasets_py.logic.legal_ir.joint_span_selection")
    importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture")
    opening_owners = retained.owner_origins(plan)
    data = read(Path(plan["data_export"]["path"]))
    require(READ_PINS[plan["data_export"]["path"]] == plan["data_export"], "Child data identity differs")
    rows = validate_data(plan, data, helper)
    prepared = retained.schedule(rows)
    schedule_pin = write(out / "data-schedule-before-models.json", dict(schedule=prepared, training_count=168, model_imported=False, **FALSE))
    source = read(Path(plan["source_checkpoint"]["path"]))
    require(READ_PINS[plan["source_checkpoint"]["path"]] == plan["source_checkpoint"] and digest(source) == SOURCE_SHA
            and digest(source["model_state"]) == SOURCE_STATE_SHA and source["progress"]["optimizer_steps"] == 32,
            "Exact completed split checkpoint required")
    fix, queries = plan["ctypes_dl_resolution"], []
    for key in ("library_pin", "ctypes_util_pin", "cuda_pathfinder_pin"):
        require(pin(Path(fix[key]["path"])) == fix[key], "Dynamic library input drift")
    with ExitStack() as stack:
        def find_dl(name):
            require(name == "dl" and pin(Path(fix["library_pin"]["path"])) == fix["library_pin"], "Unlisted dynamic library query")
            queries.append(name)
            return fix["library_pin"]["path"]
        stack.enter_context(patch.object(ctypes.util, "find_library", find_dl))
        import torch
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        require(str(torch.__version__) == "2.13.0+cu130", "Qualified Torch runtime drift")
        require(span.audit_examples(rows)["all_supported"], "Unsupported training row")
        checkpoint = adapter.build_checkpoint(source, rows, (), context_contract=plan["context_contract"], objective=plan["cell"],
            seed=1729, batch_order_seed=1729, batch_size=12, learning_rate=.001, latent_enabled=False)
        initial_sha, initial_state = digest(checkpoint), digest(checkpoint["model_state"])
        baseline = diagnostics(torch, span, warm, adapter, joint, checkpoint, data, out, "baseline")
        initial = write(out / "initial-parent-head-parity.json", compare_scores(plan, data, baseline, initial=True))
        parity = adapter.source_only_parity(torch, span, warm, checkpoint, data["diagnostic_sources"]["fresh_tune"], out, "initial")
        STATE.update(stage="training", in_progress_updates_unknown=True)
        trained = adapter.train_decoder(checkpoint, rows, (), max_steps=32, max_seconds=32)
        STATE["in_progress_updates_unknown"] = False
        checkpoint, report = trained["checkpoint"], trained["report"]
        STATE["completed_updates"] = report["optimizer_steps"]
        adapter.save_checkpoint(checkpoint, out / "cell-checkpoint.json")
        checkpoint_pin = pin(out / "cell-checkpoint.json")
        training_pin = write(out / "cell-training.json", report)
        completion(checkpoint, report, prepared, rows, plan["cell"])
        STATE["stage"] = "diagnostics"
        panels = diagnostics(torch, span, warm, adapter, joint, checkpoint, data, out, "trained")
        final = write(out / "trained-frozen-head-retention.json", compare_scores(plan, data, panels, initial=False))
        trained_parity = adapter.source_only_parity(torch, span, warm, checkpoint, data["diagnostic_sources"]["fresh_tune"], out, "trained")
        training_capture = write(out / "trained-training168-raw.json", adapter.captured_inference(torch, span, warm, checkpoint, rows))
    for path, expected in plan["artifacts"].items():
        actual = pin(Path(path))
        require({k: actual[k] for k in ("bytes", "sha256")} == expected, "Closing input drift: " + path)
    for path, expected in READ_PINS.items():
        require(pin(Path(path)) == expected, "Closing consumed input drift")
    closing_owners = retained.owner_origins(plan)
    require(opening_owners == closing_owners, "Loaded source closure changed")
    write(out / "summary.json", dict(schema="temporal-adapter-cell-results/v1", status="completed", cell=plan["cell"],
        attempt_name=plan["attempt_name"], actual_new_updates=32, actual_external_encoder_calls=0, configured_dimension=384,
        latent_enabled=False, source_checkpoint=plan["source_checkpoint"], source_model_state_sha256=SOURCE_STATE_SHA,
        source_optimizer_steps=32, fresh_Adam=True, inherited_optimizer_moments=False, training_count=168,
        prepared_schedule=prepared, schedule=schedule_pin, checkpoint=checkpoint_pin, training=training_pin,
        initial_checkpoint_sha256=initial_sha, initial_model_state_sha256=initial_state, final_model_state_sha256=digest(checkpoint["model_state"]),
        baseline_panels=baseline, diagnostics=panels, initial_parent_head_parity=initial, frozen_head_retention=final,
        initial_parity=parity, trained_parity=trained_parity, final_training_capture=training_capture,
        diagnostic_source_forwards=784, dormant_control_source_forwards=16, final_training_source_forwards=168,
        training_batch_source_forwards=sum(map(len, prepared["batch_indices"])), feature_paths_per_source_forward=2,
        equal_compute_budget_claimed=False, reference_labels_in_diagnostics=False, reference_scoring_performed=False,
        opening_owners=opening_owners, closing_owners=closing_owners, original_artifacts_byte_exact=True,
        elapsed_seconds=time.monotonic() - started, ctypes_dl_queries=queries, semantic_accuracy=None,
        independent_statutory_gold=False, checkpoint_selection_executed=False, default_promotion=False, Lake_executed=False, **FALSE))
    print(json.dumps(dict(status="completed", cell=plan["cell"], updates=32)), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    try:
        main(parser.parse_args())
    except Exception as error:
        if STATE["created_output"]:
            write(Path(STATE["created_output"]) / "child-failure.json", dict(**STATE, error_type=type(error).__name__, detail=str(error), **FALSE))
        raise
