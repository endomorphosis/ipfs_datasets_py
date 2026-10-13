"""Freeze matched authored inputs and per-cell plans without numerical work."""
import argparse
import copy
import importlib
import importlib.abc
import json
from pathlib import Path
import sys

import run_permission_retention as runner

F = Path(__file__).resolve().parent
T = F.parent / "legal-temporal-binding-20261012-01"
N2 = F.parent / "legal-targeted-loss-20261012-01"


class NoML(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"torch", "numpy", "transformers", "sentence_transformers"}:
            raise ValueError("numerical import forbidden in preparation: " + fullname)
        return None


def freeze_data():
    """Reuse byte-identical exposed data; never parse model or full references."""
    def audit(event, values):
        if event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn")) or event == "os.system":
            raise ValueError("network/process forbidden in preparation")
    sys.addaudithook(audit)
    sys.meta_path.insert(0, NoML())
    prior_path = N2 / "registration-v01.json"
    prior_pin = runner.pin(prior_path)
    prior = runner.read(prior_path)
    runner.require(prior_pin["sha256"] == "122dd798a3dbe26f8caf5f0115c5ae4369bc05b8f62adb426d129cf5e9142818", "qualified prior registration required")
    expected_data = prior["data_export"]
    runner.require(runner.pin(expected_data["path"]) == expected_data, "prior data drift")
    raw = Path(expected_data["path"]).read_bytes()
    runner.require(__import__("hashlib").sha256(raw).hexdigest() == expected_data["sha256"], "copied data identity differs")
    destination = F / "training-export-v01.json"
    with destination.open("xb") as stream:
        stream.write(raw); stream.flush(); __import__("os").fsync(stream.fileno())
    destination.chmod(0o444)
    data_pin = runner.pin(destination)
    runner.require({k:data_pin[k] for k in ("bytes","sha256")} == {k:expected_data[k] for k in ("bytes","sha256")}, "raw copied data differs")
    data = runner.read(destination)
    owners = {}
    for name, expected in prior["source_owner_pins"].items():
        path = F / "datasets" / Path(expected["path"]).relative_to(N2 / "datasets")
        current = runner.pin(path)
        runner.require({k:current[k] for k in ("bytes","sha256")} == {k:expected[k] for k in ("bytes","sha256")}, "retained source changed: " + name)
        owners[name] = current
    helper = runner.helpers(); helper.bootstrap(F / "datasets")
    importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_permission_retention")
    observed = {}
    for name, module in list(sys.modules.items()):
        if name.startswith("ipfs_datasets_py.") and getattr(module, "__file__", None):
            observed[name] = runner.pin(Path(module.__file__).resolve())
            runner.require(name not in owners or observed[name] == owners[name], "pure producer drift")
            owners[name] = observed[name]
    runner.require(not any(x.split(".")[0] in {"torch","numpy","transformers","sentence_transformers"} for x in sys.modules), "numerical import occurred")
    artifacts = copy.deepcopy(prior["artifacts"])
    for path, expected in artifacts.items():
        runner.require({k:runner.pin(path)[k] for k in ("bytes","sha256")} == expected, "prior immutable source/input drift")
    required = [Path(__file__).resolve(), F/"run_permission_retention.py", F/"run_scope_guardian.py",
        F/"bootstrap_inert.py", F/"run_inert_tests.py", destination, runner.HELPER,
        F/"resource-baseline-audit-design-v01.json", prior_path]
    required.extend(Path(v["path"]) for v in owners.values())
    for path in required:
        value=runner.pin(path); artifacts[str(path)]={k:value[k] for k in ("bytes","sha256")}
    reference_pin=prior["reference_packet"]
    runner.require(reference_pin == dict(path=str(N2/"authored-reference-packet-v01.json"), bytes=8262146, sha256="b926dbbc459c8d21a51fd8876598c8b3830a979730b44a4b3c8d15d8f613676e"), "registered reference descriptor differs")
    registration=dict(schema="permission-retention-curriculum-registration/v1", data_export=data_pin,
        reference_packet=reference_pin, prior_registration=prior_pin,
        prior_plan=runner.pin(T/"experiment-plan-v02.json"),source_owner_pins=owners,artifacts=artifacts,
        training_manifests=prior["training_manifests"],tuning_manifest_sha256=prior["tuning_manifest_sha256"],
        context_contract=prior["context_contract"],observed_pure_package_producers=observed,
        semantic_gold=False,reference_packet_child_access=False,previously_exposed_authored_evaluation=True,
        independent_semantic_holdout=False,model_calls=0,checkpoint_JSON_parsed=False,
        resource_admission=False,compiler_calls=0)
    runner.require(runner.pin(prior_path) == prior_pin, "registration custody drift")
    runner.write(F/"registration-v01.json",registration)
    print(json.dumps(dict(status="prepared_byte_identical_exposed_data_without_numerical_imports",owners=len(owners),training_populations=1,authored_eval_references_in_child_export=False)))


def make_plan(cell_id, baseline_summary=None, attempt_suffix="01"):
    registration = runner.read(F / "registration-v01.json")
    old = runner.read(T / "experiment-plan-v02.json")
    runner.require(runner.pin(T / "experiment-plan-v02.json") == registration["prior_plan"], "prior plan registration drift")
    data = runner.read(registration["data_export"]["path"])
    runner.require(runner.pin(registration["data_export"]["path"]) == registration["data_export"], "registered data drift")
    cells = {name:dict(id=name, trainable_parameter_policy=name, actor_ranking_enabled=False,
        presence_ce_weight=1, modality_loss_weight=2) for name in ("all-parameters","span-heads-only")}
    runner.require(cell_id in cells and attempt_suffix.isdecimal() and 0 < len(attempt_suffix) <= 8,
                   "known cell and bounded numeric fresh suffix required")
    cell = cells[cell_id]
    key = "mixed"
    artifacts = copy.deepcopy(registration["artifacts"])
    for path in (F / "registration-v01.json", T / "experiment-plan-v02.json"):
        value = runner.pin(path);artifacts[str(path)] = {k: value[k] for k in ("bytes", "sha256")}
    baseline_pin = baseline_plan = None
    if baseline_summary is not None:
        baseline_pin = runner.pin(Path(baseline_summary).resolve())
        previous = runner.read(baseline_pin["path"])
        first_attempt = Path(baseline_pin["path"]).parent.parent
        baseline_plan = runner.pin(F / (previous["cell"]["id"] + "-plan-v01.json"))
        for p in (Path(baseline_pin["path"]), Path(baseline_plan["path"]), first_attempt / "guardian-exit.json", first_attempt / "pre-admission.json"):
            value = runner.pin(p);artifacts[str(p)] = {k: value[k] for k in ("bytes", "sha256")}
        for panel in previous["baseline_panels"]:
            for field in ("raw", "joint", "score"):
                if panel[field] is not None:
                    value = runner.pin(panel[field]["path"])
                    runner.require(value == panel[field], "baseline diagnostic changed")
                    artifacts[value["path"]] = {k: value[k] for k in ("bytes", "sha256")}
    plan = dict(schema=runner.SCHEMA, package_root=str(F / "datasets"), runner_path=str(F / "run_permission_retention.py"),
        guardian_path=str(F / "run_scope_guardian.py"), helper_pin=runner.pin(runner.HELPER),
        attempt_name="permission-retention-20261012-" + cell_id + "-" + attempt_suffix,
        source_owner_pins=registration["source_owner_pins"], artifacts=artifacts,
        ctypes_dl_resolution=old["ctypes_dl_resolution"], historical_parent_file_pin=old["historical_parent_file_pin"],
        historical_parent_canonical_sha256=old["historical_parent_canonical_sha256"],
        parent_base_canonical_sha256=old["parent_base_canonical_sha256"], parent_model_state_sha256=old["parent_model_state_sha256"],
        data_export=registration["data_export"], cell=cell, training_manifest_sha256=registration["training_manifests"][key],
        tuning_manifest_sha256=registration["tuning_manifest_sha256"],
        diagnostic_panels=[dict(name=name, count=len(rows), has_authored_reference=name not in ("authored_eval", "law"),
            provenance="previously_exposed_authored_evaluation_no_independent_gold" if name == "authored_eval" else
                       "previously_exposed_unreviewed_law_source_only" if name == "law" else
                       "previously_inspected_authored_evaluation_now_regression_only" if name == "old_authored_eval" else "authored_engineering_not_legal_gold")
            for name, rows in data["diagnostic_populations"].items()], context_contract=registration["context_contract"],
        resource_contract=old["resource_contract"], forbidden_reference_paths=old["forbidden_reference_paths"]
            + [str(F.parent / "legal-matched-curriculum-20261012-01" / "authored-reference-packet-v01.json"),
               registration["reference_packet"]["path"]], training_seconds=32, seed=1729, batch_order_seed=1729,
        dimension=384, latent_enabled=False, encoder_execution_planned=False, semantic_gold=False,
        independent_semantic_holdout=False, checkpoint_selection_executed=False, default_promotion=False, Lake_executed=False,
        baseline_results=baseline_pin, baseline_plan=baseline_plan,
        promotion_gate=dict(schema="legacy-exact-permission-preservation-gate/v1", required_old_exact=96,
            old_count=96, new_permission_to_obligation_allowed=0, applies_to="raw_and_joint_IR", automatic_selection=False))
    # JSON key sorting of the export must never silently change panel order.
    ordered = ["old_tune", "fresh_tune", "fresh_challenge", "old_authored_eval", "authored_dev", "authored_eval", "law"]
    plan["diagnostic_panels"].sort(key=lambda p: ordered.index(p["name"]))
    runner.validate_plan(plan)
    runner.validate_data(plan, data, runner.helpers())
    if baseline_pin is not None:
        runner.reuse_baseline(plan)
    runner.require(not (runner.RUN_ROOT / plan["attempt_name"]).exists(), "attempt already exists")
    output = runner.write(F / (cell_id + "-plan-v01.json"), plan)
    print(json.dumps(dict(status="one_cell_plan_prepared_no_model", plan=output, attempt=plan["attempt_name"])))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell")
    parser.add_argument("--baseline-summary")
    parser.add_argument("--attempt-suffix", default="01")
    args = parser.parse_args()
    if args.cell:
        make_plan(args.cell, args.baseline_summary, args.attempt_suffix)
    else:
        freeze_data()
