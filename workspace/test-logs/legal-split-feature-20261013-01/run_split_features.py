"""One guarded split-feature training comparison using exposed authored source data.

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
SCHEMA = "split-feature-cell-plan/v1"
DATA_SCHEMA = "targeted-loss-curriculum-export/v1"
N2 = F.parent / "legal-targeted-loss-20261012-01"
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
    "Lake_executed", "baseline_results", "baseline_plan", "promotion_gate", "parent_capture_reference",
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


READ_PINS = {}


def read(path):
    path = Path(path)
    before = pin(path)
    raw = path.read_bytes()
    require(len(raw) <= 128 * 1024 * 1024 and hashlib.sha256(raw).hexdigest() == before['sha256']
        and pin(path) == before, 'bounded exact consumed metadata bytes required')
    require(str(path) not in READ_PINS or READ_PINS[str(path)] == before,
        'previous metadata identity changed')
    READ_PINS[str(path)] = before
    def unique(pairs):
        result = {}
        for key,value in pairs:
            require(key not in result, 'duplicate JSON key');result[key]=value
        return result
    def finite(raw):
        value=float(raw);require(math.isfinite(value),'nonfinite JSON number');return value
    return json.loads(raw,object_pairs_hook=unique,parse_float=finite,
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
    require(type(plan["attempt_name"]) is str and plan["attempt_name"].startswith("split-feature-20261013-")
            and Path(plan["attempt_name"]).name == plan["attempt_name"]
            and plan["attempt_name"] not in {".", ".."}, "fresh exact attempt component required")
    cell = plan["cell"]
    require(type(cell) is dict and set(cell) == {"id", "trainable_parameter_policy", "actor_ranking_enabled", "presence_ce_weight", "modality_loss_weight"}, "closed parameter-policy cell required")
    require(cell["id"] == "split-features" and cell["trainable_parameter_policy"] == cell["id"]
            and cell["actor_ranking_enabled"] is False and type(cell["presence_ce_weight"]) is int and cell["presence_ce_weight"] == 1
            and type(cell["modality_loss_weight"]) is int and cell["modality_loss_weight"] == 2, "fixed objective and closed optimizer policy required")
    require(plan["promotion_gate"] == dict(schema="legacy-exact-permission-preservation-gate/v1",
            required_old_exact=96, old_count=96, new_permission_to_obligation_allowed=0,
            applies_to="raw_and_joint_IR", automatic_selection=False), "explicit unchanged legacy promotion gate required")
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
                ("old_authored_eval", 72, True), ("authored_dev", 72, True), ("authored_eval", 72, False), ("law", 8, False)]
    require(type(plan["diagnostic_panels"]) is list and len(plan["diagnostic_panels"]) == len(expected), "complete diagnostics required")
    for panel, (name, count, reference) in zip(plan["diagnostic_panels"], expected, strict=True):
        require(set(panel) == {"name", "count", "has_authored_reference", "provenance"}
                and panel["name"] == name and type(panel["count"]) is int and panel["count"] == count
                and panel["has_authored_reference"] is reference, "diagnostic population differs")
    require(type(plan["artifacts"]) is dict and plan["artifacts"]
            and not set(plan["artifacts"]) & set(plan["forbidden_reference_paths"]), "finite admitted artifacts required")
    require(plan["forbidden_reference_paths"] == list(RETAINED_FORBIDDEN)
            + [str(F.parent / "legal-matched-curriculum-20261012-01" / "authored-reference-packet-v01.json"),
               str(N2 / "authored-reference-packet-v01.json")], "complete original/evaluation reference exclusion required")
    for path in (plan["runner_path"], plan["guardian_path"], str(HELPER), plan["data_export"]["path"],
                 plan["historical_parent_file_pin"]["path"]):
        require(path in plan["artifacts"], "required input absent from artifact closure")
    require((plan["baseline_results"] is None) == (plan["baseline_plan"] is None), "partial baseline reuse forbidden")
    require(plan["baseline_results"] is None and plan["baseline_plan"] is None,
            "split model must generate fresh zero-update diagnostics, not reuse prior predictions")
    reference = plan['parent_capture_reference']
    require(type(reference) is dict and set(reference) == {'freeze', 'summary', 'panels'}
            and reference['freeze']['sha256'] == '2a268b4b3f5c03cedb29d8d1df6d5718778fc54da9473fabfb5c2eaefde7d46b'
            and reference['summary']['sha256'] == '6861267ec449f210add8f5526074bec040c690c1bd73652bde5f68e48017b73b'
            and set(reference['panels']) == {panel['name'] for panel in plan['diagnostic_panels']},
            'exact qualified parent capture references required')
    for descriptor in [reference['freeze'], reference['summary'], *reference['panels'].values()]:
        require(set(descriptor) == {'path', 'bytes', 'sha256'} and
                plan['artifacts'].get(descriptor['path']) == {k: descriptor[k] for k in ('bytes', 'sha256')},
                'parent capture reference absent from artifact closure')


def owner_origins(plan):
    observed = {}
    for name, module in list(sys.modules.items()):
        if not name.startswith("ipfs_datasets_py.") or not getattr(module, "__file__", None):
            continue
        require(name in plan["source_owner_pins"], "unfrozen package producer: " + name)
        actual = pin(Path(module.__file__).resolve())
        require(actual == plan["source_owner_pins"][name], "package source/origin drift: " + name)
        observed[name] = actual
    for name in ("legal_span_formula", "legal_span_continuation", "legal_span_targeted_loss", "legal_span_split_features"):
        require("ipfs_datasets_py.optimizers.logic_theorem_optimizer." + name in observed, "required trainer missing")
    return observed


def validate_data(plan, data, helper):
    require(type(data) is dict and set(data) == {"schema", "training_populations", "training_metadata",
            "diagnostic_populations", "diagnostic_metadata", "semantic_gold", "reference_scope"}
            and data["schema"] == DATA_SCHEMA and data["semantic_gold"] is False,
            "authored diagnostic data only")
    require(data["reference_scope"] == REFERENCE_SCOPE, "unexpected reference payload/scope")
    require(set(data["training_populations"]) == set(data["training_metadata"]) == {"mixed"}
            and set(data["diagnostic_populations"]) == {"old_tune", "fresh_tune", "fresh_challenge", "old_authored_eval", "authored_dev", "authored_eval", "law"}
            and set(data["diagnostic_metadata"]) == {"old_tune", "fresh_tune", "fresh_challenge", "old_authored_eval", "authored_dev"},
            "closed common population; new evaluation references/metadata forbidden")
    rows, metadata = data["training_populations"]["mixed"], data["training_metadata"]["mixed"]
    require(type(rows) is list and type(metadata) is list and len(rows) == len(metadata) == 168
            and digest(rows[:96]) == "4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995"
            and digest(metadata[:96]) == "ad674072ee5026a0ae5ea0df270265785e00cf20fa4ca58c309d73ebb0d6fa72",
            "exact common 96-row rehearsal and metadata required")
    helper.validate_authored_pairs(rows[:96], metadata[:96], require_pairs=False)
    helper.validate_authored_pairs(rows[96:], metadata[96:])
    require(digest(rows) == plan["training_manifest_sha256"], "exact common168 training rows required")
    require(digest(data["diagnostic_populations"]["old_tune"]) == plan["tuning_manifest_sha256"], "old tuning manifest drift")
    classes = ("plain_deadline", "condition_duration", "exception_duration", "actor_duration_name",
               "object_duration_title", "condition_exception_duration")
    for index, meta in enumerate(metadata[96:]):
        require(meta["class_name"] == classes[index // 12], "six matched class quotas differ")
    training_ids, training_sources = {r["id"] for r in rows}, {r["source_text"] for r in rows}
    training_groups = {m["group_id"] for m in metadata}
    training_pairs = {m["pair_id"] for m in metadata}
    require(len(training_ids) == len(training_sources) == 168, "duplicate training source/ID")
    for row in rows:
        require(set(row) == {"id", "source_text", "latent", "canonical_ir"}
                and type(row["source_text"]) is str and row["source_text"].strip()
                and type(row["latent"]) is list and len(row["latent"]) == 384
                and all(type(v) in (int, float) and math.isfinite(v) for v in row["latent"]), "closed training row")
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
            require(not training_ids & {r["id"] for r in incoming}
                    and not training_sources & {r["source_text"] for r in incoming}, "new split overlaps training")
            for old_name in ("old_tune", "fresh_tune", "fresh_challenge", "old_authored_eval"):
                old = data["diagnostic_populations"][old_name]
                require(not {r["id"] for r in incoming} & {r["id"] for r in old}
                        and not {r["source_text"] for r in incoming} & {r["source_text"] for r in old}, "new split overlaps exposed source panel")
    dev, evaluation = data["diagnostic_populations"]["authored_dev"], data["diagnostic_populations"]["authored_eval"]
    require(not {r["id"] for r in dev} & {r["id"] for r in evaluation}
            and not {r["source_text"] for r in dev} & {r["source_text"] for r in evaluation}, "new development/evaluation overlap")
    require(not training_groups & {m["group_id"] for m in data["diagnostic_metadata"]["authored_dev"]}
            and not training_pairs & {m["pair_id"] for m in data["diagnostic_metadata"]["authored_dev"]}, "development pair/group overlaps training")
    return rows


def validate_completion(checkpoint, report, plan, prepared, rows):
    require(checkpoint["schema"] == "bounded-split-feature-span-legal-formula-checkpoint/v1"
            and report["checkpoint_sha256"] == digest(checkpoint)
            and checkpoint["progress"] == prepared["final_progress"], "own authoritative trained checkpoint/progress required")
    policy, trace = checkpoint["training_policy"], report["batch_trace"]
    require(report["training_policy"] == policy and report["training_policy_sha256"] == digest(policy)
            and policy["trainable_parameter_policy"] == plan["cell"]["trainable_parameter_policy"]
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
        require(batch["pre_progress"] == progress and batch["optimizer_step"] == step, "completed trace chain/order differs")
        progress["optimizer_steps"] += 1
        progress["row_cursor"] += len(batch["indices"])
        if progress["row_cursor"] == 168:
            progress["epochs_completed"] += 1; progress["row_cursor"] = 0
        require(batch["post_progress"] == progress, "completed trace transition differs")
    require(progress == prepared["final_progress"], "final completed prefix differs")


def modality_comparison(plan, data, baseline, trained, out):
    panels=[]; total_equal=0; total=0
    for panel, before, after in zip(plan["diagnostic_panels"], baseline, trained, strict=True):
        require(before["name"] == after["name"] == panel["name"], "modality comparison panel join differs")
        left=read(before["raw"]["path"])["occurrences"]; right=read(after["raw"]["path"])["occurrences"]
        require(READ_PINS[before['raw']['path']] == before['raw'] and READ_PINS[after['raw']['path']] == after['raw'],
                'parsed modality comparison payload differs from saved capture descriptor')
        require(len(left) == len(right) == panel["count"], "modality comparison row count differs")
        rows=[]
        for source, a, b in zip(data["diagnostic_populations"][panel["name"]], left, right, strict=True):
            require(a["id"] == b["id"] == source["id"] and a["source_sha256"] == b["source_sha256"] == hashlib.sha256(source["source_text"].encode()).hexdigest(), "modality source identity differs")
            x,y=a["scores"]["modality_logits"],b["scores"]["modality_logits"]
            import struct
            require(len(x) == len(y) == 3 and all(type(v) in (int,float) and math.isfinite(v) for v in x+y), "finite three-way modality logits required")
            xb=b"".join(struct.pack("<f",v) for v in x); yb=b"".join(struct.pack("<f",v) for v in y)
            equal=xb==yb
            rows.append(dict(id=source["id"],source_sha256=a["source_sha256"],parent_f32_sha256=hashlib.sha256(xb).hexdigest(),trained_f32_sha256=hashlib.sha256(yb).hexdigest(),bit_equal=equal))
            total+=1; total_equal+=int(equal)
        panels.append(dict(name=panel["name"],rows=rows,equal_count=sum(r["bit_equal"] for r in rows),count=len(rows)))
    require(total == 392, "all seven source panels required")
    frozen=plan["cell"]["trainable_parameter_policy"] == "split-features"
    require(not frozen or total_equal == total, "frozen shared/modality path changed actual source logits")
    return write(out/"trained-modality-retention.json",dict(schema="split-feature-modality-score-comparison/v1",cell=plan["cell"],panels=panels,total_source_rows=total,bit_equal_count=total_equal,exact_modal_score_retention_required=frozen,full_IR_retention_implied=False,semantic_accuracy=None,**FALSE))


def initial_parent_head_parity(plan, data, baseline):
    """Compare fresh captures with qualified prior parent bytes before any update."""
    reference = plan['parent_capture_reference']
    freeze = read(reference['freeze']['path'])
    require(READ_PINS[reference['freeze']['path']] == reference['freeze'], 'parent freeze consumed-byte drift')
    cells = [cell for cell in freeze['cells'] if cell['cell']['id'] == 'all-parameters']
    require(len(cells) == 1 and cells[0]['summary'] == reference['summary'], 'qualified parent summary join differs')
    prior = read(reference['summary']['path'])
    require(READ_PINS[reference['summary']['path']] == reference['summary'] and
            prior['same_original_parent_model_sha256'] == plan['parent_model_state_sha256'] and
            prior['baseline_optimizer_steps'] == 0 and prior['latent_enabled'] is False,
            'qualified original parent capture lineage differs')
    panels = []
    for panel, fresh, old in zip(plan['diagnostic_panels'], baseline, prior['baseline_panels'], strict=True):
        name = panel['name']; expected = reference['panels'][name]
        require(fresh['name'] == old['name'] == name and old['raw'] == expected and
                cells[0]['results'].get(expected['path']) == {k: expected[k] for k in ('bytes', 'sha256')},
                'qualified parent panel freeze join differs')
        before = read(expected['path']); after = read(fresh['raw']['path'])
        require(READ_PINS[expected['path']] == expected and READ_PINS[fresh['raw']['path']] == fresh['raw'],
                'initial parity capture consumed-byte drift')
        left, right = before['occurrences'], after['occurrences']
        require(len(left) == len(right) == panel['count'], 'initial parity count differs')
        for source, a, b in zip(data['diagnostic_populations'][name], left, right, strict=True):
            require(a['id'] == b['id'] == source['id'] and
                    a['source_sha256'] == b['source_sha256'] == hashlib.sha256(source['source_text'].encode()).hexdigest()
                    and canonical(a['scores']) == canonical(b['scores']),
                    'initial parent tokens or complete four-head scores differ')
        panels.append(dict(name=name, count=len(left), parent_capture=expected, fresh_capture=fresh['raw'],
                           complete_score_payloads_sha256=digest([row['scores'] for row in left]),
                           all_four_heads_and_tokens_exact=True))
    require(sum(panel['count'] for panel in panels) == 392, 'complete initial392 parity required')
    return dict(schema='split-feature-initial-parent-head-parity/v1', checked_before_training=True,
                total_source_rows=392, all_four_heads_and_tokens_exact=True, parent_reference=reference,
                panels=panels, model_forward_calls_added=0, **FALSE)


def diagnostics(torch, span, warm, curriculum, joint, checkpoint, data, plan, out, name, helper):
    reports = []
    for panel in plan["diagnostic_panels"]:
        rows = data["diagnostic_populations"][panel["name"]]
        raw = curriculum.captured_inference(torch, span, warm, checkpoint, rows)
        raw_pin = write(out / (name + "-" + panel["name"] + "-raw.json"), raw)
        selected = [dict(id=row["id"], result=joint.select_joint_spans(row["source_text"], capture["scores"],
                    top_k=8, max_search_nodes=50000)) for row, capture in zip(rows, raw["occurrences"], strict=True)]
        joint_pin = write(out / (name + "-" + panel["name"] + "-joint.json"), dict(schema="split-feature-joint-panel/v1",
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
    curriculum = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_split_features")
    joint = importlib.import_module("ipfs_datasets_py.logic.legal_ir.joint_span_selection")
    importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture")
    opening_owners = owner_origins(plan)
    data = read(plan["data_export"]["path"])
    require(READ_PINS[plan['data_export']['path']] == plan['data_export'], 'consumed export descriptor drift')
    rows = validate_data(plan, data, helper)
    prepared = schedule(rows, seed=plan["batch_order_seed"])
    write(out / "data-schedule-before-models.json", dict(schedule=prepared, training_count=168, model_imported=False, **FALSE))
    historical = read(plan["historical_parent_file_pin"]["path"])
    require(READ_PINS[plan['historical_parent_file_pin']['path']] == plan['historical_parent_file_pin'],
            'consumed historical parent descriptor drift')
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
            context_contract=plan["context_contract"], trainable_parameter_policy=plan["cell"]["trainable_parameter_policy"],
            batch_order_seed=plan["batch_order_seed"], seed=1729, learning_rate=.001, batch_size=12, latent_enabled=False)
        policy = checkpoint["training_policy"]
        require(policy["trainable_parameter_policy"] == plan["cell"]["trainable_parameter_policy"]
                and checkpoint["training_policy_sha256"] == digest(policy), "constructed optimizer policy differs")
        initial_checkpoint_sha = digest(checkpoint)
        continuation = checkpoint["initial_continuation_checkpoint"]
        initial_continuation_sha = digest(continuation)
        baseline_model_state_sha = digest(checkpoint["model_state"])
        require(continuation["initial_model_state_sha256"] == plan["parent_model_state_sha256"]
                and checkpoint["progress"] == dict(epochs_completed=0,row_cursor=0,optimizer_steps=0)
                and continuation["base_checkpoint"]["optimizer_state"] == dict(schema="adam-default-betas-eps/v1",parameters={})
                and checkpoint["optimizer_state"]["parameters"] == {}, "copied weights and true empty new Adam required")
        original = parent['model_state']
        split_features = {name: 'span_' + name for name in (
            'byte_embedding.weight','token_projection.weight','token_projection.bias',
            'encoder.weight_ih_l0','encoder.weight_hh_l0','encoder.bias_ih_l0','encoder.bias_hh_l0',
            'encoder.weight_ih_l0_reverse','encoder.weight_hh_l0_reverse',
            'encoder.bias_ih_l0_reverse','encoder.bias_hh_l0_reverse')}
        require(set(checkpoint['model_state']) == set(original) | set(split_features.values())
            and all(checkpoint['model_state'][name] == value for name,value in original.items())
            and all(checkpoint['model_state'][copy] == original[name] for name,copy in split_features.items()),
            'both initial feature branches must be exact source parent copies')
        baseline = diagnostics(torch, span, warm, curriculum, joint, checkpoint, data, plan, out, 'baseline', helper)
        parent_head_parity = initial_parent_head_parity(plan, data, baseline)
        parity = curriculum.source_only_parity(torch, span, warm, checkpoint,
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
        checkpoint = trained["checkpoint"]
        require(checkpoint["progress"] == prepared["final_progress"], "actual final progress differs")
        STATE["stage"] = "diagnostics"
        reports = diagnostics(torch, span, warm, curriculum, joint, checkpoint, data, plan, out, "trained", helper)
        trained_parity = curriculum.source_only_parity(torch, span, warm, checkpoint,
            data["diagnostic_populations"]["fresh_tune"], out, "trained")
        modality_retention = modality_comparison(plan, data, baseline, reports, out)
    for path, expected in plan["artifacts"].items():
        require({k: pin(path)[k] for k in ("bytes", "sha256")} == expected, "closing artifact drift: " + path)
    for path, expected in READ_PINS.items():
        require(pin(path) == expected, "closing consumed metadata identity drift")
    closing_owners = owner_origins(plan)
    write(out / "summary.json", dict(schema="split-feature-cell-results/v1", status="completed",
        cell=plan["cell"], attempt_name=plan["attempt_name"], actual_new_updates=32, actual_encoder_calls=0,
        actual_encoder_calls_scope='external_latent_or_context_encoders', initial_parent_head_parity=parent_head_parity,
        same_original_parent_model_sha256=plan["parent_model_state_sha256"], fresh_Adam=True,
        inherited_optimizer_moments=False, parent_optimizer_steps=400, configured_dimension=384, latent_enabled=False,
        training_count=168, prepared_schedule=prepared, checkpoint=checkpoint_pin, training=training_pin,
        initial_continuation_checkpoint_sha256=initial_continuation_sha, initial_checkpoint_sha256=initial_checkpoint_sha, baseline_optimizer_steps=0,
        baseline_model_state_sha256=baseline_model_state_sha,
        baseline_panels=baseline, baseline_reuse=plan["baseline_results"], diagnostics=reports,
        initial_parity=parity, trained_parity=trained_parity, modality_retention=modality_retention,
        parameter_partition=report["parameter_partition"], initial_model_state_sha256=report["initial_model_state_sha256"], final_model_state_sha256=report["final_model_state_sha256"],
        initial_branch_digests=report["initial_branch_digests"], final_branch_digests=report["final_branch_digests"],
        feature_paths_per_source_model_forward=2, equal_compute_budget_claimed=False,
        opening_owners=opening_owners, closing_owners=closing_owners,
        original_artifacts_byte_exact=True, elapsed_seconds=time.monotonic() - started,
        ctypes_dl_queries=queries, semantic_accuracy=None, independent_statutory_gold=False,
        promotion_gate=plan["promotion_gate"],
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
