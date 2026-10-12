"""Freeze matched authored inputs and per-cell plans without numerical work."""
import argparse
import copy
import importlib
import importlib.abc
import json
from pathlib import Path
import sys

import run_targeted_loss as runner

F = Path(__file__).resolve().parent
T = F.parent / "legal-temporal-binding-20261012-01"


class NoML(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"torch", "numpy", "transformers", "sentence_transformers"}:
            raise ValueError("numerical import forbidden in preparation: " + fullname)
        return None


def freeze_data():
    """Author-visible references stay in a distinct child-forbidden packet."""
    def audit(event, values):
        if event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn")) or event == "os.system":
            raise ValueError("network/process forbidden in preparation")
    sys.addaudithook(audit)
    sys.meta_path.insert(0, NoML())
    helper = runner.helpers()
    helper.bootstrap(F / "datasets")
    corpus = importlib.import_module("ipfs_datasets_py.logic.legal_ir.targeted_loss_curriculum")
    span = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_formula")
    importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_continuation")
    importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_targeted_loss")
    importlib.import_module("ipfs_datasets_py.logic.legal_ir.joint_span_selection")
    importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture")
    old_plan = runner.read(T / "experiment-plan-v02.json")
    runner.require(runner.pin(old_plan["data_export"]["path"]) == old_plan["data_export"], "frozen prior export drift")
    prior = runner.read(old_plan["data_export"]["path"])
    authored = corpus.build_curriculum(prior)
    reference_pin = runner.write(F / "authored-reference-packet-v01.json", authored)
    populations = copy.deepcopy(authored["diagnostic_populations"])
    populations["authored_eval"] = [{k: row[k] for k in ("id", "source_text", "latent")}
                                    for row in populations["authored_eval"]]
    metadata = copy.deepcopy(authored["diagnostic_metadata"])
    metadata.pop("authored_eval", None)
    data = dict(schema=runner.DATA_SCHEMA, training_populations=authored["training_populations"],
        training_metadata=authored["training_metadata"], diagnostic_populations=populations,
        diagnostic_metadata=metadata, semantic_gold=False,
        reference_scope=runner.REFERENCE_SCOPE)
    for key, rows in data["training_populations"].items():
        runner.require(len(rows) == 168 and span.audit_examples(rows)["all_supported"], "unsupported matched rows: " + key)
    for key in ("old_tune", "fresh_tune", "fresh_challenge", "old_authored_eval", "authored_dev"):
        runner.require(span.audit_examples(populations[key])["all_supported"], "unsupported authored panel: " + key)
    data_pin = runner.write(F / "training-export-v01.json", data)
    observed = {}
    for name, module in list(sys.modules.items()):
        if name.startswith("ipfs_datasets_py.") and getattr(module, "__file__", None):
            observed[name] = runner.pin(Path(module.__file__).resolve())
    # Keep all existing owner identities, even when a producer is not imported
    # during this particular preparation, then add the explicit new producers.
    owners = {}
    for name, expected in old_plan["source_owner_pins"].items():
        path = F / "datasets" / Path(expected["path"]).relative_to(T / "datasets")
        current = runner.pin(path)
        runner.require({k: current[k] for k in ("bytes", "sha256")} ==
                       {k: expected[k] for k in ("bytes", "sha256")}, "legacy producer drift: " + name)
        owners[name] = current
    owners.update(observed)
    runner.require(not any(x.split(".")[0] in {"torch", "numpy", "transformers", "sentence_transformers"}
                           for x in sys.modules), "numerical import occurred")
    artifacts = copy.deepcopy(old_plan["artifacts"])
    for path, expected in artifacts.items():
        runner.require({k: runner.pin(path)[k] for k in ("bytes", "sha256")} == expected, "prior immutable source/input drift")
    required = [Path(__file__).resolve(), F / "run_targeted_loss.py", F / "run_scope_guardian.py",
                F / "bootstrap_inert.py", F / "run_inert_tests.py", Path(data_pin["path"]), runner.HELPER,
                F / "resource-baseline-audit-design-v01.json"]
    required.extend(Path(v["path"]) for v in owners.values())
    for path in required:
        value = runner.pin(path)
        artifacts[str(path)] = {k: value[k] for k in ("bytes", "sha256")}
    registration = dict(schema="targeted-loss-curriculum-registration/v1", data_export=data_pin,
        reference_packet=reference_pin, prior_plan=runner.pin(T / "experiment-plan-v02.json"),
        source_owner_pins=owners, artifacts=artifacts,
        training_manifests={k: runner.digest(v) for k, v in data["training_populations"].items()},
        tuning_manifest_sha256=runner.digest(populations["old_tune"]),
        context_contract=dict(dimension=384, representation_id="targeted-loss-source-only-dormant384/v1",
            producer_sha256=runner.pin(Path(__file__).resolve())["sha256"],
            training_index_sha256=runner.digest({k: runner.digest(v) for k, v in data["training_populations"].items()})),
        observed_pure_package_producers=observed, semantic_gold=False, reference_packet_child_access=False,
        model_calls=0, checkpoint_JSON_parsed=False, resource_admission=False, compiler_calls=0)
    runner.write(F / "registration-v01.json", registration)
    print(json.dumps(dict(status="prepared_without_numerical_imports", owners=len(owners),
                         training_populations=1, authored_eval_references_in_child_export=False)))


def make_plan(cell_id, baseline_summary=None, attempt_suffix="01"):
    registration = runner.read(F / "registration-v01.json")
    old = runner.read(T / "experiment-plan-v02.json")
    runner.require(runner.pin(T / "experiment-plan-v02.json") == registration["prior_plan"], "prior plan registration drift")
    data = runner.read(registration["data_export"]["path"])
    runner.require(runner.pin(registration["data_export"]["path"]) == registration["data_export"], "registered data drift")
    cells = {f"rank{rank}-presence{presence}": dict(id=f"rank{rank}-presence{presence}",
             actor_ranking_enabled=bool(rank), presence_ce_weight=presence, modality_loss_weight=2)
             for rank in (0, 1) for presence in (1, 2)}
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
    plan = dict(schema=runner.SCHEMA, package_root=str(F / "datasets"), runner_path=str(F / "run_targeted_loss.py"),
        guardian_path=str(F / "run_scope_guardian.py"), helper_pin=runner.pin(runner.HELPER),
        attempt_name="targeted-loss-20261012-" + cell_id + "-" + attempt_suffix,
        source_owner_pins=registration["source_owner_pins"], artifacts=artifacts,
        ctypes_dl_resolution=old["ctypes_dl_resolution"], historical_parent_file_pin=old["historical_parent_file_pin"],
        historical_parent_canonical_sha256=old["historical_parent_canonical_sha256"],
        parent_base_canonical_sha256=old["parent_base_canonical_sha256"], parent_model_state_sha256=old["parent_model_state_sha256"],
        data_export=registration["data_export"], cell=cell, training_manifest_sha256=registration["training_manifests"][key],
        tuning_manifest_sha256=registration["tuning_manifest_sha256"],
        diagnostic_panels=[dict(name=name, count=len(rows), has_authored_reference=name not in ("authored_eval", "law"),
            provenance="authored_reference_deferred_until_matrix_complete" if name == "authored_eval" else
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
