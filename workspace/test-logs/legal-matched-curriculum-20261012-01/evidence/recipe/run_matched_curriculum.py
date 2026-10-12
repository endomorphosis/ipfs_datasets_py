"""One resource-guarded cell of the matched source-only curriculum experiment.

Importing this file does not construct models, read checkpoints or reserve
resources. Numerical execution belongs exclusively to the reviewed guardian.
References are authored diagnostics; they establish no statutory fidelity.
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
import random
import sys
import time
from unittest.mock import patch

F = Path(__file__).resolve().parent
T = F.parent / "legal-temporal-binding-20261012-01"
RUN_ROOT = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01")
HELPER = T / "run_temporal_contrast_pilot.py"
HELPER_SHA = "0ae80b9554c45ec104430b7f1a482ad834a33e5f41f5f031fdd203634374fa05"
RETAINED_FORBIDDEN = (
    "/home/barberb/.cache/huggingface/hub/datasets--justicedao--ipfs_uscode/blobs/4d26df1e3814279e4b4df3af0e454b4f64fc89a81879db926989862b6ad7d8b8",
    "/home/barberb/lift_coding/artifacts/legal-decoder-native-conditioning-20261002/prepared/corpus.json",
    "/home/barberb/lift_coding/artifacts/legal-decoder-native-conditioning-20261002/prepared/sealed-evaluation-targets.json",
    "/home/barberb/lift_coding/artifacts/legal-decoder-native-conditioning-20261002/run-01/contexts-raw384.json",
    "/home/barberb/lift_coding/artifacts/legal-joint-readout-20261011-01/statutory-source-review-packet.json",
    "/home/barberb/lift_coding/artifacts/legal-joint-readout-20261011-01/statutory-source-review-template.json",
    "/home/barberb/lift_coding/artifacts/legal-structured-training-20261011-01/statutory-review-pending-recording.json",
    "/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/uscode-span-continuation-20261011/archived-reconciliation-01/results/reconciliation.duckdb",
)
SCHEMA = "matched-temporal-curriculum-cell-plan/v1"
DATA_SCHEMA = "matched-temporal-curriculum-export/v1"
REFERENCE_SCOPE = "Authored engineering only; eval references excluded until all matrix outputs are frozen"
FALSE = dict(qualified=False, admitted=False, formalized=False, proof_authority=False,
             semantic_correctness_verified=False, promotion_performed=False)
STATE = dict(created_output=None, completed_updates=0, saved_states=[], stage="preflight",
             in_progress_updates_unknown=False)
PLAN_FIELDS = {
    "schema", "package_root", "runner_path", "guardian_path", "helper_pin", "attempt_name",
    "source_owner_pins", "artifacts", "ctypes_dl_resolution", "historical_parent_file_pin",
    "historical_parent_canonical_sha256", "parent_base_canonical_sha256", "parent_model_state_sha256",
    "data_export", "cell", "training_manifest_sha256", "tuning_manifest_sha256", "diagnostic_panels",
    "context_contract", "resource_contract", "forbidden_reference_paths", "training_seconds",
    "seed", "batch_order_seed", "dimension", "latent_enabled", "encoder_execution_planned",
    "semantic_gold", "independent_semantic_holdout", "checkpoint_selection_executed", "default_promotion",
    "Lake_executed", "baseline_results", "baseline_plan",
}


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink(),
            "exact absolute ordinary file required")
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and len(raw) == before.st_size,
            "file changed during read")
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def finite(raw):
        value = float(raw)
        require(math.isfinite(value), "nonfinite JSON number")
        return value
    raw = Path(path).read_bytes()
    require(len(raw) <= 128 * 1024 * 1024, "bounded JSON required")
    return json.loads(raw, object_pairs_hook=unique, parse_float=finite,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return pin(path)


def helpers():
    require(pin(HELPER)["sha256"] == HELPER_SHA, "retained diagnostic helper changed")
    spec = importlib.util.spec_from_file_location("matched_retained_diagnostics", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def schedule(rows, steps=32, seed=1729, batch_size=12):
    epoch = cursor = 0
    indices, ids = [], []
    for _ in range(steps):
        order = list(range(len(rows)))
        random.Random(seed + epoch).shuffle(order)
        chosen = order[cursor:cursor + batch_size]
        indices.append(chosen)
        ids.append([rows[index]["id"] for index in chosen])
        cursor += len(chosen)
        if cursor == len(rows):
            epoch, cursor = epoch + 1, 0
    return dict(batch_indices=indices, batch_ids=ids, batch_indices_sha256=digest(indices),
                final_progress=dict(epochs_completed=epoch, row_cursor=cursor, optimizer_steps=steps))


def validate_plan(plan):
    require(type(plan) is dict and set(plan) == PLAN_FIELDS and plan["schema"] == SCHEMA,
            "closed one-cell plan required")
    require(plan["runner_path"] == str(Path(__file__).resolve()) and plan["package_root"] == str(F / "datasets")
            and plan["guardian_path"] == str(F / "run_scope_guardian.py"), "exact selected producers required")
    require(plan["helper_pin"] == pin(HELPER) and plan["helper_pin"]["sha256"] == HELPER_SHA,
            "exact retained helper binding required")
    require(type(plan["attempt_name"]) is str and plan["attempt_name"].startswith("matched-temporal-20261012-")
            and Path(plan["attempt_name"]).name == plan["attempt_name"]
            and plan["attempt_name"] not in {".", ".."}, "fresh exact attempt component required")
    cell = plan["cell"]
    require(type(cell) is dict and set(cell) == {"id", "actor_curriculum", "scope_curriculum", "modality_loss_weight"},
            "one closed factorial cell required")
    require(all(type(cell[key]) is int and cell[key] in (0, 1) for key in ("actor_curriculum", "scope_curriculum"))
            and type(cell["modality_loss_weight"]) is int and cell["modality_loss_weight"] in (1, 2), "invalid factors")
    require(cell["id"] == f"actor{cell['actor_curriculum']}-scope{cell['scope_curriculum']}-modality{cell['modality_loss_weight']-1}",
            "cell identity/factors differ")
    require(type(plan["seed"]) is int and plan["seed"] == 1729
            and type(plan["batch_order_seed"]) is int and plan["batch_order_seed"] == 1729
            and type(plan["dimension"]) is int and plan["dimension"] == 384 and plan["latent_enabled"] is False,
            "initial single-order-seed source-only configuration required")
    require(all(plan[k] is False for k in ("encoder_execution_planned", "semantic_gold", "independent_semantic_holdout",
            "checkpoint_selection_executed", "default_promotion", "Lake_executed")), "no semantic or promotion authority")
    require(plan["resource_contract"] == dict(cpu_slots=2, rss_mib=1536, child_slots=1,
            storage_bytes=200000000, wall_seconds=300), "unchanged guarded resource envelope required")
    require(type(plan["training_seconds"]) in (int, float) and math.isfinite(plan["training_seconds"])
            and 0 < plan["training_seconds"] <= 32, "bounded numerical training allowance required")
    expected = [("old_tune", 96, True), ("fresh_tune", 36, True), ("fresh_challenge", 36, True),
                ("authored_dev", 72, True), ("authored_eval", 72, False), ("law", 8, False)]
    require(type(plan["diagnostic_panels"]) is list and len(plan["diagnostic_panels"]) == len(expected), "complete diagnostics required")
    for panel, (name, count, reference) in zip(plan["diagnostic_panels"], expected, strict=True):
        require(set(panel) == {"name", "count", "has_authored_reference", "provenance"}
                and panel["name"] == name and type(panel["count"]) is int and panel["count"] == count
                and panel["has_authored_reference"] is reference, "diagnostic population differs")
    require(type(plan["artifacts"]) is dict and plan["artifacts"]
            and not set(plan["artifacts"]) & set(plan["forbidden_reference_paths"]), "finite admitted artifacts required")
    require(plan["forbidden_reference_paths"] == list(RETAINED_FORBIDDEN)
            + [str(F / "authored-reference-packet-v01.json")], "complete original/evaluation reference exclusion required")
    for path in (plan["runner_path"], plan["guardian_path"], str(HELPER), plan["data_export"]["path"],
                 plan["historical_parent_file_pin"]["path"]):
        require(path in plan["artifacts"], "required input absent from artifact closure")
    require((plan["baseline_results"] is None) == (plan["baseline_plan"] is None), "partial baseline reuse forbidden")
    require((plan["baseline_results"] is None) == (cell["id"] == "actor0-scope0-modality0"),
            "only the preregistered first cell may construct baseline diagnostics")


def owner_origins(plan):
    observed = {}
    for name, module in list(sys.modules.items()):
        if not name.startswith("ipfs_datasets_py.") or not getattr(module, "__file__", None):
            continue
        require(name in plan["source_owner_pins"], "unfrozen package producer: " + name)
        actual = pin(Path(module.__file__).resolve())
        require(actual == plan["source_owner_pins"][name], "package source/origin drift: " + name)
        observed[name] = actual
    for name in ("legal_span_formula", "legal_span_continuation", "legal_span_curriculum"):
        require("ipfs_datasets_py.optimizers.logic_theorem_optimizer." + name in observed, "required trainer missing")
    return observed


def validate_data(plan, data, helper):
    require(type(data) is dict and set(data) == {"schema", "training_populations", "training_metadata",
            "diagnostic_populations", "diagnostic_metadata", "semantic_gold", "reference_scope"}
            and data["schema"] == DATA_SCHEMA and data["semantic_gold"] is False,
            "authored diagnostic data only")
    require(data["reference_scope"] == REFERENCE_SCOPE, "unexpected reference payload/scope")
    train_keys = {f"actor{a}-scope{s}" for a in (0, 1) for s in (0, 1)}
    require(set(data["training_populations"]) == set(data["training_metadata"]) == train_keys
            and set(data["diagnostic_populations"]) == {"old_tune", "fresh_tune", "fresh_challenge", "authored_dev", "authored_eval", "law"}
            and set(data["diagnostic_metadata"]) == {"old_tune", "fresh_tune", "fresh_challenge", "authored_dev"},
            "closed matched populations; evaluation references/metadata forbidden")
    training_ids, training_sources, training_groups, training_pairs = set(), set(), set(), set()
    base = data["training_populations"]["actor0-scope0"]
    classes = ("plain_deadline", "condition_duration", "exception_duration", "actor_duration_name",
               "object_duration_title", "condition_exception_duration")
    for name, population in data["training_populations"].items():
        metadata = data["training_metadata"][name]
        require(type(population) is list and len(population) == 168 and len(metadata) == 168
                and metadata == data["training_metadata"]["actor0-scope0"]
                and digest(population[:96]) == "4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995"
                and digest(metadata[:96]) == "ad674072ee5026a0ae5ea0df270265785e00cf20fa4ca58c309d73ebb0d6fa72",
                "exact common rehearsal and metadata required")
        helper.validate_authored_pairs(population[:96], metadata[:96], require_pairs=False)
        helper.validate_authored_pairs(population[96:], metadata[96:])
        for row in population:
            require(set(row) == {"id", "source_text", "latent", "canonical_ir"}
                    and type(row["source_text"]) is str and row["source_text"].strip()
                    and type(row["latent"]) is list and len(row["latent"]) == 384
                    and all(type(v) in (int, float) and math.isfinite(v) for v in row["latent"]), "closed training row")
        for index, (row, reference, meta) in enumerate(zip(population, base, metadata, strict=True)):
            require(row["id"] == reference["id"] and len(row["source_text"]) == len(reference["source_text"])
                    and len(row["source_text"].encode()) == len(reference["source_text"].encode()), "stable slots and source lengths required")
            changed = (name.startswith("actor1") and 132 <= index < 144) or (name.endswith("scope1") and 156 <= index < 168)
            require((row != reference) is changed, "factor changes outside declared actor/scope slots")
            if index >= 96:
                require(meta["class_name"] == classes[(index - 96) // 12], "matched class quotas differ")
                training_groups.add(meta["group_id"]);training_pairs.add(meta["pair_id"])
        training_ids.update(row["id"] for row in population)
        training_sources.update(row["source_text"] for row in population)
    key = f"actor{plan['cell']['actor_curriculum']}-scope{plan['cell']['scope_curriculum']}"
    rows = data["training_populations"][key]
    require(len(rows) == 168 and digest(rows) == plan["training_manifest_sha256"], "exact matched168 rows required")
    require(digest(data["diagnostic_populations"]["old_tune"]) == plan["tuning_manifest_sha256"], "old tuning manifest drift")
    for panel in plan["diagnostic_panels"]:
        incoming = data["diagnostic_populations"][panel["name"]]
        require(type(incoming) is list and len(incoming) == panel["count"], "complete panel data required")
        for row in incoming:
            require(set(row) == {"id", "source_text", "latent"} | ({"canonical_ir"} if panel["has_authored_reference"] else set()),
                    "closed diagnostic row required")
            require(type(row["id"]) is str and 0 < len(row["id"].strip()) <= 512
                    and type(row["source_text"]) is str and 0 < len(row["source_text"].strip()) <= 16384,
                    "bounded diagnostic identity/source required")
            require(type(row["latent"]) is list and len(row["latent"]) == 384
                    and all(type(v) in (int, float) and math.isfinite(v) for v in row["latent"]),
                    "finite dormant384 placeholders required")
            if panel["name"] in ("authored_dev", "authored_eval"):
                require(row["latent"] == [0.0] * 384, "new authored vectors must be zero placeholders")
        require(len({r["id"] for r in incoming}) == len(incoming)
                and len({r["source_text"] for r in incoming}) == len(incoming), "duplicate diagnostic occurrence")
        if panel["has_authored_reference"]:
            helper.validate_authored_pairs(incoming, data["diagnostic_metadata"][panel["name"]],
                                           require_pairs=panel["name"] != "old_tune")
        if panel["name"] in ("authored_dev", "authored_eval"):
            require(not training_ids & {row["id"] for row in incoming}
                    and not training_sources & {row["source_text"] for row in incoming}, "new split overlaps training occurrences")
    dev, evaluation = data["diagnostic_populations"]["authored_dev"], data["diagnostic_populations"]["authored_eval"]
    require(not {r["id"] for r in dev} & {r["id"] for r in evaluation}
            and not {r["source_text"] for r in dev} & {r["source_text"] for r in evaluation}, "new development/evaluation overlap")
    require(not training_groups & {m["group_id"] for m in data["diagnostic_metadata"]["authored_dev"]}
            and not training_pairs & {m["pair_id"] for m in data["diagnostic_metadata"]["authored_dev"]}, "development pair/group overlaps training")
    return rows


def reuse_baseline(plan):
    """Reuse only the complete first cell's identical, source-only diagnostics."""
    prior_path = plan["baseline_plan"]["path"]
    summary_path = plan["baseline_results"]["path"]
    require(pin(prior_path) == plan["baseline_plan"] and pin(summary_path) == plan["baseline_results"],
            "prior baseline plan/results drift")
    prior, result = read(prior_path), read(summary_path)
    validate_plan(prior)
    require(Path(prior_path) == F / "actor0-scope0-modality0-plan-v01.json"
            and Path(summary_path) == RUN_ROOT / prior["attempt_name"] / "results" / "summary.json"
            and result["schema"] == "matched-temporal-curriculum-cell-results/v1"
            and result["cell"] == prior["cell"] and result["attempt_name"] == prior["attempt_name"],
            "baseline must join exact first cell plan/attempt/results")
    require(prior["baseline_results"] is None and result["status"] == "completed"
            and result["actual_new_updates"] == 32 and result["actual_encoder_calls"] == 0
            and result["baseline_reuse"] is None, "only complete initial baseline can be reused")
    for key in ("source_owner_pins", "historical_parent_file_pin", "parent_base_canonical_sha256",
                "parent_model_state_sha256", "seed", "dimension", "latent_enabled", "diagnostic_panels",
                "data_export", "context_contract"):
        require(prior[key] == plan[key], "baseline experiment boundary differs: " + key)
    terminal_path = Path(summary_path).parent.parent / "guardian-exit.json"
    pre_path = Path(summary_path).parent.parent / "pre-admission.json"
    require(str(terminal_path) in plan["artifacts"], "prior successful terminal not bound")
    require(str(pre_path) in plan["artifacts"] and read(pre_path)["plan"] == pin(prior_path), "prior admitted plan identity differs")
    terminal = read(terminal_path)
    require(type(terminal["returncode"]) is int and type(terminal["child_returncode"]) is int
            and terminal["returncode"] == terminal["child_returncode"] == 0
            and terminal["artifacts_durable"] is True and terminal["resource_reservation_released"] is True,
            "baseline source run did not terminate durably and release")
    reports = result["baseline_panels"]
    require(result["baseline_optimizer_steps"] == 0
            and result["baseline_model_state_sha256"] == plan["parent_model_state_sha256"], "baseline was not zero-update parent weights")
    require([row["name"] for row in reports] == [row["name"] for row in plan["diagnostic_panels"]],
            "complete reusable baseline panels required")
    data = read(plan["data_export"]["path"])
    for row, panel in zip(reports, plan["diagnostic_panels"], strict=True):
        require(set(row) == {"name", "row_count", "raw", "joint", "score", "has_authored_reference"}
                and row["row_count"] == panel["count"] and row["has_authored_reference"] is panel["has_authored_reference"]
                and (row["score"] is not None) is panel["has_authored_reference"], "baseline panel envelope differs")
        for key in ("raw", "joint", "score"):
            if row[key] is not None:
                require(str(row[key]["path"]) in plan["artifacts"] and pin(row[key]["path"]) == row[key],
                        "reused baseline diagnostic not bound or drifted")
                require(Path(row[key]["path"]) == Path(summary_path).parent / ("baseline-" + row["name"] + "-" + key + ".json"),
                        "baseline panel file belongs to another state/attempt")
        raw = read(row["raw"]["path"])
        inference = raw["inference"]
        require(inference["checkpoint_sha256"] == result["initial_continuation_checkpoint_sha256"]
                and inference["source_parent_checkpoint_sha256"] == plan["parent_base_canonical_sha256"]
                and inference["source_parent_optimizer_steps"] == 400
                and inference["context_contract_sha256"] == digest(plan["context_contract"])
                and raw["actual_source_forwards"] == panel["count"] and raw["target_access"] is False
                and raw["model_weights_unchanged"] is True, "baseline source/model/context identity differs")
        incoming = data["diagnostic_populations"][row["name"]]
        require(len(raw["occurrences"]) == panel["count"], "baseline occurrence count differs")
        for occurrence, source in zip(raw["occurrences"], incoming, strict=True):
            require(occurrence["id"] == source["id"] and occurrence["source_sha256"] == hashlib.sha256(source["source_text"].encode()).hexdigest(),
                    "baseline input source identity differs")
    return reports


def validate_completion(checkpoint, report, plan, prepared, rows):
    """Accept only a complete recorded update chain for the selected policy."""
    require(report["checkpoint_sha256"] == digest(checkpoint)
            and report["continuation_checkpoint_sha256"] == digest(checkpoint["continuation_checkpoint"])
            and report["base_checkpoint_sha256"] == digest(checkpoint["continuation_checkpoint"]["base_checkpoint"]),
            "reported/checkpoint digest differs")
    policy, trace = checkpoint["training_policy"], report["batch_trace"]
    require(report["training_policy"] == policy and report["training_policy_sha256"] == digest(policy)
            and policy["modality_loss_weight"] == plan["cell"]["modality_loss_weight"]
            and trace["completed_updates"] == report["optimizer_steps"] == 32 and trace["training_count"] == 168
            and trace["training_manifest_sha256"] == digest(rows)
            and trace["initial_progress"] == dict(epochs_completed=0, row_cursor=0, optimizer_steps=0)
            and trace["final_progress"] == prepared["final_progress"], "completed update/policy boundary differs")
    batches = trace["batches"]
    require(len(batches) == 32 and [b["indices"] for b in batches] == prepared["batch_indices"]
            and [b["ids"] for b in batches] == prepared["batch_ids"]
            and [b["loss"] for b in batches] == report["batch_losses"]
            and trace["indices_sha256"] == digest(prepared["batch_indices"])
            and trace["ids_sha256"] == digest(prepared["batch_ids"])
            and trace["batches_sha256"] == digest(batches), "completed trace digest/index/ID/loss differs")
    progress = dict(trace["initial_progress"])
    for step, batch in enumerate(batches, 1):
        require(batch["pre_progress"] == progress and batch["optimizer_step"] == step,
                "completed trace chain/order differs")
        progress["optimizer_steps"] += 1
        progress["row_cursor"] += len(batch["indices"])
        if progress["row_cursor"] == 168:
            progress["epochs_completed"] += 1;progress["row_cursor"] = 0
        require(batch["post_progress"] == progress, "completed trace transition differs")
    require(progress == prepared["final_progress"] == checkpoint["continuation_checkpoint"]["base_checkpoint"]["progress"],
            "saved/returned final progress differs")


def diagnostics(torch, span, warm, joint, continuation, data, plan, out, name, helper):
    reports = []
    for panel in plan["diagnostic_panels"]:
        rows = data["diagnostic_populations"][panel["name"]]
        raw = helper.captured_inference(torch, span, warm, continuation, rows)
        raw_pin = write(out / (name + "-" + panel["name"] + "-raw.json"), raw)
        selected = [dict(id=row["id"], result=joint.select_joint_spans(row["source_text"], capture["scores"],
                    top_k=8, max_search_nodes=50000)) for row, capture in zip(rows, raw["occurrences"], strict=True)]
        joint_pin = write(out / (name + "-" + panel["name"] + "-joint.json"), dict(schema="matched-curriculum-joint-panel/v1",
            rows=selected, top_k=8, max_search_nodes=50000, learned_presence_and_modality_fixed=True, **FALSE))
        score = None
        if panel["has_authored_reference"]:
            score = write(out / (name + "-" + panel["name"] + "-score.json"),
                helper.score_panel(rows, data["diagnostic_metadata"][panel["name"]], raw, selected))
        reports.append(dict(name=panel["name"], row_count=len(rows), raw=raw_pin, joint=joint_pin,
                            score=score, has_authored_reference=panel["has_authored_reference"]))
    return reports


def main(args):
    started = time.monotonic()
    plan = read(args.plan)
    validate_plan(plan)
    out = Path(args.output)
    require(out.is_absolute() and out.resolve() == out and out == RUN_ROOT / plan["attempt_name"] / "results"
            and not out.exists(), "plan/guardian exact fresh output attempt differs")
    for path, expected in plan["artifacts"].items():
        require({k: pin(path)[k] for k in ("bytes", "sha256")} == expected, "opening artifact drift: " + path)
    out.mkdir(mode=0o700)
    STATE["created_output"] = str(out)
    forbidden = set(plan["forbidden_reference_paths"])
    def audit(event, values):
        if event.startswith(("subprocess.", "os.exec", "os.spawn", "socket.")) or event == "os.system":
            raise ValueError("network/process forbidden: " + event)
        if event == "open" and isinstance(values[0], (str, bytes)):
            require(str(Path(os.fsdecode(values[0])).absolute()) not in forbidden, "forbidden original target container")
    sys.addaudithook(audit)
    helper = helpers()
    sys.meta_path.insert(0, helper.NoEncoder())
    helper.bootstrap(Path(plan["package_root"]))
    span = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_formula")
    warm = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_continuation")
    curriculum = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_curriculum")
    joint = importlib.import_module("ipfs_datasets_py.logic.legal_ir.joint_span_selection")
    importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture")
    opening_owners = owner_origins(plan)
    data = read(plan["data_export"]["path"])
    rows = validate_data(plan, data, helper)
    prepared = schedule(rows, seed=plan["batch_order_seed"])
    write(out / "data-schedule-before-models.json", dict(schedule=prepared, training_count=168, model_imported=False, **FALSE))
    historical = read(plan["historical_parent_file_pin"]["path"])
    require(digest(historical) == plan["historical_parent_canonical_sha256"], "original parent identity drift")
    parent = historical["base_checkpoint"]
    require(digest(parent) == plan["parent_base_canonical_sha256"]
            and digest(parent["model_state"]) == plan["parent_model_state_sha256"], "copied parent/model identity drift")
    require(parent["progress"] == dict(epochs_completed=4, row_cursor=192, optimizer_steps=400)
            and parent["config"]["seed"] == 1729 and parent["config"]["latent_dimension"] == 384
            and parent["config"]["latent_enabled"] is False, "exact source-only400 parent contract required")
    fix = plan["ctypes_dl_resolution"]
    for key in ("library_pin", "ctypes_util_pin", "cuda_pathfinder_pin"):
        require(pin(fix[key]["path"]) == fix[key], "libdl closure drift")
    queries = []
    with ExitStack() as stack:
        def find_dl(name):
            require(name == "dl" and pin(fix["library_pin"]["path"]) == fix["library_pin"], "unlisted dynamic-library query")
            queries.append(name)
            return fix["library_pin"]["path"]
        stack.enter_context(patch.object(ctypes.util, "find_library", find_dl))
        import torch
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        require(torch.__version__ == "2.13.0+cu130", "qualified Torch runtime drift")
        for name, population in data["training_populations"].items():
            require(span.audit_examples(population)["all_supported"], "unsupported matched population: " + name)
        checkpoint = curriculum.build_checkpoint(parent, rows, data["diagnostic_populations"]["old_tune"],
            context_contract=plan["context_contract"], modality_loss_weight=plan["cell"]["modality_loss_weight"],
            batch_order_seed=plan["batch_order_seed"], seed=1729, learning_rate=.001, batch_size=12, latent_enabled=False)
        policy = checkpoint["training_policy"]
        require(policy["modality_loss_weight"] == plan["cell"]["modality_loss_weight"]
                and policy["batch_order_seed"] == plan["batch_order_seed"]
                and policy["initialization_seed"] == 1729 and policy["batch_size"] == 12
                and policy["max_new_optimizer_steps"] == 32
                and checkpoint["training_policy_sha256"] == digest(policy), "constructed objective/sampler policy differs")
        continuation = checkpoint["continuation_checkpoint"]
        initial_continuation_sha = digest(continuation)
        baseline_model_state_sha = digest(continuation["base_checkpoint"]["model_state"])
        require(continuation["initial_model_state_sha256"] == plan["parent_model_state_sha256"]
                and baseline_model_state_sha == plan["parent_model_state_sha256"]
                and continuation["base_checkpoint"]["progress"] == dict(epochs_completed=0, row_cursor=0, optimizer_steps=0)
                and continuation["base_checkpoint"]["optimizer_state"] == dict(schema="adam-default-betas-eps/v1", parameters={}),
                "copied weights and empty new Adam required")
        baseline = None
        if plan["baseline_results"] is None:
            baseline = diagnostics(torch, span, warm, joint, continuation, data, plan, out, "baseline", helper)
        else:
            baseline = reuse_baseline(plan)
        parity = helper.source_only_parity(torch, span, warm, continuation,
            data["diagnostic_populations"]["fresh_tune"], out, "initial")
        STATE.update(stage="training", in_progress_updates_unknown=True)
        trained = curriculum.train_decoder(checkpoint, rows, data["diagnostic_populations"]["old_tune"],
                                           max_steps=32, max_seconds=plan["training_seconds"])
        STATE["in_progress_updates_unknown"] = False
        report = trained["report"]
        STATE["completed_updates"] = report["optimizer_steps"]
        checkpoint_pin = curriculum.save_checkpoint(trained["checkpoint"], out / "cell-checkpoint.json")
        checkpoint_pin = pin(out / "cell-checkpoint.json")
        STATE["saved_states"].append(checkpoint_pin)
        training_pin = write(out / "cell-training.json", report)
        require(report["optimizer_steps"] == 32 and report["stopped_reason"] == "step_limit",
                "incomplete cell: preserve output and refuse equal-budget comparison")
        validate_completion(trained["checkpoint"], report, plan, prepared, rows)
        trace = report["batch_trace"]
        require(report["training_policy"] == policy and report["training_policy_sha256"] == digest(policy)
                and trace["completed_updates"] == 32 and trace["training_count"] == 168
                and trace["initial_progress"] == dict(epochs_completed=0, row_cursor=0, optimizer_steps=0)
                and trace["final_progress"] == prepared["final_progress"]
                and [batch["indices"] for batch in trace["batches"]] == prepared["batch_indices"]
                and [batch["ids"] for batch in trace["batches"]] == prepared["batch_ids"]
                and [batch["loss"] for batch in trace["batches"]] == report["batch_losses"],
                "actual returned completed-batch trace differs from frozen schedule/objective")
        continuation = trained["checkpoint"]["continuation_checkpoint"]
        require(continuation["base_checkpoint"]["progress"] == prepared["final_progress"], "actual final progress differs")
        STATE["stage"] = "diagnostics"
        reports = diagnostics(torch, span, warm, joint, continuation, data, plan, out, "trained", helper)
        trained_parity = helper.source_only_parity(torch, span, warm, continuation,
            data["diagnostic_populations"]["fresh_tune"], out, "trained")
    for path, expected in plan["artifacts"].items():
        require({k: pin(path)[k] for k in ("bytes", "sha256")} == expected, "closing artifact drift: " + path)
    closing_owners = owner_origins(plan)
    write(out / "summary.json", dict(schema="matched-temporal-curriculum-cell-results/v1", status="completed",
        cell=plan["cell"], attempt_name=plan["attempt_name"], actual_new_updates=32, actual_encoder_calls=0,
        same_original_parent_model_sha256=plan["parent_model_state_sha256"], fresh_Adam=True,
        inherited_optimizer_moments=False, parent_optimizer_steps=400, configured_dimension=384, latent_enabled=False,
        training_count=168, prepared_schedule=prepared, checkpoint=checkpoint_pin, training=training_pin,
        initial_continuation_checkpoint_sha256=initial_continuation_sha, baseline_optimizer_steps=0,
        baseline_model_state_sha256=baseline_model_state_sha,
        baseline_panels=baseline, baseline_reuse=plan["baseline_results"], diagnostics=reports,
        initial_parity=parity, trained_parity=trained_parity, opening_owners=opening_owners, closing_owners=closing_owners,
        original_artifacts_byte_exact=True, elapsed_seconds=time.monotonic() - started,
        ctypes_dl_queries=queries, semantic_accuracy=None, independent_statutory_gold=False,
        checkpoint_selection_executed=False, default_promotion=False, Lake_executed=False, **FALSE))
    print(json.dumps(dict(status="completed", cell=plan["cell"]["id"], updates=32)), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    try:
        main(parser.parse_args())
    except Exception as error:
        if STATE["created_output"]:
            write(Path(STATE["created_output"]) / "child-failure.json", dict(**STATE,
                error_type=type(error).__name__, detail=str(error), **FALSE))
        raise
