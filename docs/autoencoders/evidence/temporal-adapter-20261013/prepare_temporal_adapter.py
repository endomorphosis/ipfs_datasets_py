"""Prepare training labels/source-only diagnostics and two fixed inert plans."""
import argparse
from copy import deepcopy
import hashlib
import importlib
import importlib.abc
import importlib.util
import os
from pathlib import Path
import sys

F = Path(__file__).resolve().parent
N4 = F.parent / "legal-split-feature-20261013-01"
N5 = F.parent / "legal-temporal-presence-20261013-01"
sys.dont_write_bytecode = True


class NoNumerical(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"torch", "numpy", "transformers", "sentence_transformers", "huggingface_hub"}:
            raise AssertionError("Numerical/SDK import forbidden during preparation")
        return None


def audit(event, args):
    if event.startswith(("subprocess.", "socket.", "os.exec", "os.spawn")) or event in ("os.system", "os.fork", "fcntl.flock"):
        raise AssertionError("No process, network, resource or lock operations during preparation")
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = Path(os.fsdecode(args[0])).absolute()
        mode, flags = args[1:]
        writing = isinstance(mode, str) and any(c in mode for c in "wax+")
        writing |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writing and path.parent != F:
            raise AssertionError("Only exclusive new preparation artifacts may be written")


sys.meta_path.insert(0, NoNumerical())
sys.addaudithook(audit)
spec = importlib.util.spec_from_file_location("temporal_adapter_runner_preparation", F / "run_temporal_adapter.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
_read_metadata = runner.read


def read_metadata(path):
    runner.require("checkpoint" not in Path(path).name and "reference-packet" not in Path(path).name,
                   "Checkpoint and evaluation-packet JSON parsing forbidden during preparation")
    return _read_metadata(path)


runner.read = read_metadata


def bind(artifacts, path, expected=None):
    descriptor = runner.pin(Path(path))
    runner.require(descriptor["path"] not in runner.READ_PINS or runner.READ_PINS[descriptor["path"]] == descriptor,
                   "Bound bytes differ from consumed metadata")
    if expected is not None:
        runner.require(descriptor == expected, "Expected retained descriptor differs")
    pair = {k: descriptor[k] for k in ("bytes", "sha256")}
    runner.require(descriptor["path"] not in artifacts or artifacts[descriptor["path"]] == pair, "Artifact pin conflict")
    artifacts[descriptor["path"]] = pair
    return descriptor


def prepare():
    freeze_path = N4 / "split-feature-output-freeze-v01.json"
    freeze_pin = runner.pin(freeze_path)
    runner.require(freeze_pin["sha256"] == "bcefd26d2b7ec9d96fd28d46ee3b6e69728d49a4cf13ababe50036a1d648c33b", "Qualified N4 freeze required")
    freeze = runner.read(freeze_path)
    runner.require(runner.READ_PINS[str(freeze_path)] == freeze_pin, "Consumed N4 freeze drift")
    original_path = Path(freeze["training_export"]["path"])
    runner.require(runner.pin(original_path) == freeze["training_export"], "Exact exposed source export required")
    original = runner.read(original_path)
    runner.require(runner.READ_PINS[str(original_path)] == freeze["training_export"], "Consumed source export differs")
    export = dict(schema="temporal-adapter-source-only-diagnostics-export/v1",
        training_rows=deepcopy(original["training_populations"]["mixed"]),
        training_metadata=deepcopy(original["training_metadata"]["mixed"]),
        diagnostic_sources={name: [{k: row[k] for k in ("id", "source_text", "latent")} for row in rows]
                            for name, rows in original["diagnostic_populations"].items()}, semantic_gold=False)
    data_pin = runner.write(F / "training-source-export-v01.json", export)
    artifacts = {}
    bind(artifacts, freeze_path)
    bind(artifacts, Path(freeze["registration"]["path"]), freeze["registration"])
    registration = runner.read(freeze["registration"]["path"])
    runner.require(runner.READ_PINS[freeze["registration"]["path"]] == freeze["registration"], "N4 registration drift")
    source_owners = {}
    for name, descriptor in registration["source_owner_pins"].items():
        path = F / "datasets" / Path(descriptor["path"]).relative_to(N4 / "datasets")
        new = runner.pin(path)
        runner.require({k: new[k] for k in ("bytes", "sha256")} == {k: descriptor[k] for k in ("bytes", "sha256")}, "Retained source bytes changed")
        source_owners[name] = new
    retained = runner.prior_runner()
    helper = retained.helpers()
    helper.bootstrap(F / "datasets")
    importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_temporal_adapter")
    for name, module in list(sys.modules.items()):
        if name.startswith("ipfs_datasets_py.") and getattr(module, "__file__", None):
            descriptor = runner.pin(Path(module.__file__).resolve())
            runner.require(name not in source_owners or source_owners[name] == descriptor, "Loaded producer differs")
            source_owners[name] = descriptor
    source_cell = freeze["cells"][0]
    bind(artifacts, Path(source_cell["summary"]["path"]), source_cell["summary"])
    summary = runner.read(source_cell["summary"]["path"])
    runner.require(runner.READ_PINS[source_cell["summary"]["path"]] == source_cell["summary"], "N4 summary drift")
    source_checkpoint = summary["checkpoint"]
    source_checkpoint = {k: source_checkpoint[k] for k in ("path", "bytes", "sha256")}
    runner.require(source_checkpoint["sha256"] == runner.SOURCE_SHA and source_checkpoint["bytes"] == 3592389,
                   "Exact completed split checkpoint required")
    bind(artifacts, Path(source_checkpoint["path"]), source_checkpoint)
    references = {}
    for panel in summary["diagnostics"]:
        references[panel["name"]] = {key: panel[key] for key in ("raw", "joint")}
        for descriptor in references[panel["name"]].values():
            runner.require(source_cell["results"][descriptor["path"]] == {k: descriptor[k] for k in ("bytes", "sha256")}, "N4 frozen reference drift")
            bind(artifacts, Path(descriptor["path"]), descriptor)
    old_plan_pin = bind(artifacts, N4 / "split-features-plan-v01.json")
    old_plan = runner.read(N4 / "split-features-plan-v01.json")
    runner.require(runner.READ_PINS[old_plan_pin["path"]] == old_plan_pin, "Consumed N4 plan drift")
    for path in (Path(__file__).resolve(), F / "run_temporal_adapter.py", F / "run_scope_guardian.py",
                 F / "bootstrap_inert.py", F / "run_inert_tests.py", runner.PRIOR_RUNNER, retained.HELPER,
                 F / "evaluation-contract-v01.json", N5 / "temporal-presence-training-proposal-v02.md",
                 N4 / "split-features-plan-v01.json", F / "datasets/tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_temporal_adapter_contracts.py"):
        bind(artifacts, path)
    for descriptor in source_owners.values():
        bind(artifacts, Path(descriptor["path"]), descriptor)
    for key in ("library_pin", "ctypes_util_pin", "cuda_pathfinder_pin"):
        descriptor = old_plan["ctypes_dl_resolution"][key]
        bind(artifacts, Path(descriptor["path"]), descriptor)
    bind(artifacts, Path(data_pin["path"]), data_pin)
    # Fresh baseline is evidence of unchanged metadata, not a guarantee of admission.
    baseline = F / "resource-baseline-v01.json"
    runner.require(baseline.is_file(), "Fresh resource baseline must be reviewed before freezing plans")
    bind(artifacts, baseline)
    for cell in runner.CELLS:
        plan = dict(schema="temporal-adapter-cell-plan/v1", package_root=str(F / "datasets"), runner_path=str(F / "run_temporal_adapter.py"),
            guardian_path=str(F / "run_scope_guardian.py"), attempt_name="temporal-adapter-20261013-" + cell + "-01", cell=cell,
            source_owner_pins=source_owners, artifacts=artifacts, data_export=data_pin, source_checkpoint=source_checkpoint,
            source_model_state_sha256=runner.SOURCE_STATE_SHA, context_contract=old_plan["context_contract"],
            training_manifest_sha256=runner.digest(export["training_rows"]), legacy_prefix_sha256=runner.digest(export["training_rows"][:96]),
            source_reference_panels=references, ctypes_dl_resolution=old_plan["ctypes_dl_resolution"],
            forbidden_reference_paths=list(retained.RETAINED_FORBIDDEN) + [str(original_path), freeze["reference_packet"]["path"],
                str(F.parent / "legal-matched-curriculum-20261012-01/authored-reference-packet-v01.json")],
            resource_contract=dict(cpu_slots=2, rss_mib=1536, child_slots=1, storage_bytes=200000000, deadline_seconds=300),
            training_seconds=32, diagnostic_panels=[dict(name=name, count=runner.COUNTS[name]) for name in runner.PANELS],
            reference_source_export=freeze["training_export"], reference_packet=freeze["reference_packet"],
            evaluation_contract=runner.pin(F / "evaluation-contract-v01.json"), proposal=runner.pin(N5 / "temporal-presence-training-proposal-v02.md"),
            configured_dimension=384, latent_enabled=False, default_promotion=False, Lake_executed=False)
        runner.validate_plan(plan)
        runner.validate_data(plan, export, helper)
        runner.require(not (runner.RUN_ROOT / plan["attempt_name"]).exists(), "Immutable attempt already exists")
        print(runner.write(F / (cell + "-plan-v01.json"), plan))
    for path, expected in artifacts.items():
        actual = runner.pin(Path(path))
        runner.require({k: actual[k] for k in ("bytes", "sha256")} == expected, "Closing preparation input drift")
    for path, expected in runner.READ_PINS.items():
        runner.require(runner.pin(Path(path)) == expected, "Closing consumed preparation metadata drift")
    runner.require(not any(name.split(".")[0] in {"torch", "numpy", "transformers", "sentence_transformers"} for name in sys.modules), "Unexpected numerical import")


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    prepare()
