"""Close actual pure runner imports without altering the retained experiment.

No model, numerical library, network, subprocess, checkpoint JSON restore or
resource admission is permitted. The old recipe/plan/data remain byte-exact.
Only missing observed package producer pins and this helper/prior-plan pins are
added to the new plan. The import closure is a bounded engineering observation,
not qualification of later Torch/third-party imports or legal model behavior.
"""
from pathlib import Path
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
import os
import sys

F = Path(__file__).resolve().parent
D = F / "datasets"
OLD_PLAN = F / "experiment-plan-v01.json"
NEW_PLAN = F / "experiment-plan-v02.json"
REPORT = F / "plan-import-closure-preflight-v02.json"
IMPORTS = (
    "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_formula",
    "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_continuation",
    "ipfs_datasets_py.logic.legal_ir.joint_span_selection",
    "ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink(),
            "ordinary absolute source file required")
    value = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        initial = os.fstat(stream.fileno())
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(block)
            value.update(block)
        final = os.fstat(stream.fileno())
    require((initial.st_dev, initial.st_ino, initial.st_size, initial.st_mtime_ns)
            == (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns) and size == final.st_size,
            "source changed during hash observation")
    return dict(path=str(path), bytes=size, sha256=value.hexdigest())


class DenyNumerical(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"torch", "numpy", "transformers", "sentence_transformers"}:
            raise AssertionError("pure import closure prohibits numerical/model import: " + fullname)
        return None


def audit(event, values):
    if event.startswith(("subprocess.", "os.exec", "os.spawn", "socket.")) or event == "os.system":
        raise AssertionError("pure import closure prohibits network/process: " + event)
    if event == "open":
        path, mode, flags = values
        writing = isinstance(mode, str) and any(char in mode for char in "wax+")
        writing |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writing:
            require(isinstance(path, (str, bytes, os.PathLike))
                    and Path(os.fsdecode(path)).absolute() in {NEW_PLAN, REPORT},
                    "pure closure writes only new plan/report")


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(F, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return pin(path)


def main():
    require(not NEW_PLAN.exists() and not REPORT.exists(), "new immutable closure outputs required")
    require(not any(name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py.") for name in sys.modules),
            "fresh import probe process required")
    sys.dont_write_bytecode = True
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"] = "0"
    sys.meta_path.insert(0, DenyNumerical())
    sys.addaudithook(audit)
    old = read(OLD_PLAN)
    old_pin = pin(OLD_PLAN)
    require(len(old["artifacts"]) == 94, "exact retained94 artifact map required")
    for path, expected in old["artifacts"].items():
        require({key: pin(path)[key] for key in ("bytes", "sha256")} == expected, "retained artifact differs")
    spec = importlib.util.spec_from_file_location("readonly_retained_temporal_recipe", F / "run_temporal_contrast_pilot.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.validate_plan(old)
    runner.bootstrap(D)
    for name in IMPORTS:
        importlib.import_module(name)
    observed = {}
    namespaces = []
    for name, module in list(sys.modules.items()):
        if not (name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py.")):
            continue
        source = getattr(module, "__file__", None)
        if source is None:
            namespaces.append(name)
            continue
        source = Path(source).resolve()
        expected_file = D.joinpath(*name.split(".")).with_suffix(".py")
        expected_package = D.joinpath(*name.split("."), "__init__.py")
        require(source in {expected_file, expected_package} and source.is_relative_to(D), "unexpected producer physical origin")
        observed[name] = pin(source)
    require(set(IMPORTS) <= set(observed), "required pure runner imports missing")
    missing = {name: value for name, value in observed.items() if name not in old["source_owner_pins"]}
    require(bool(missing), "actual failed producer gap was not reproduced")
    for name in set(observed) & set(old["source_owner_pins"]):
        require(observed[name] == old["source_owner_pins"][name], "previous owner origin/hash changed")
    try:
        runner.owner_origins(old)
    except ValueError as error:
        old_refusal = str(error)
        require(old_refusal.startswith("unfrozen package producer: "), "previous failure boundary differs")
    else:
        raise ValueError("old plan unexpectedly accepted missing producers")
    new = read(OLD_PLAN)
    new["source_owner_pins"].update(missing)
    additions = {str(Path(value["path"])): {key: value[key] for key in ("bytes", "sha256")} for value in missing.values()}
    for path in (Path(__file__).resolve(), OLD_PLAN):
        value = pin(path)
        additions[str(path)] = {key: value[key] for key in ("bytes", "sha256")}
    require(not set(additions) & set(old["artifacts"]), "new closure artifact collides with retained94 map")
    new["artifacts"].update(additions)
    require(all(new[key] == old[key] for key in old if key not in {"source_owner_pins", "artifacts"}),
            "scientific/data/initialization/budget fields changed")
    require(all(new["artifacts"][key] == value for key, value in old["artifacts"].items()), "retained94 artifacts changed")
    runner.validate_plan(new)
    runner.validate_data(new, read(new["data_export"]["path"]))
    owner_names = runner.owner_origins(new)
    require(owner_names == sorted(observed), "actual full package owner replay differs")
    require(not any(name.split(".")[0] in {"torch", "numpy", "transformers", "sentence_transformers"} for name in sys.modules),
            "prohibited numerical/model module loaded")
    require(pin(OLD_PLAN) == old_pin and all(pin(value["path"]) == value for value in observed.values()),
            "closing old plan/package bytes differ")
    new_pin = write(NEW_PLAN, new)
    report = dict(schema="temporal-contrast-pure-package-import-closure/v1", passed=True, findings=[],
        old_plan=old_pin, new_plan=new_pin, helper=pin(Path(__file__).resolve()), exact_runner_imports=list(IMPORTS),
        observed_package_producers=observed, explicit_namespace_bootstrap=sorted(namespaces), missing_prior_producers=missing,
        reproduced_old_refusal=old_refusal, old_artifact_count=94, new_artifact_count=len(new["artifacts"]),
        added_artifact_pins=additions, prior94_preserved=True, scientific_data_init_budgets_unchanged=True,
        actual_plan_data_and_owner_preflight_passed=True, numerical_imports_denied=True, network_process_denied=True,
        model_calls=0, optimizer_updates=0, encoder_calls=0, checkpoint_JSON_restore=False, compiler_calls=0,
        resource_admission=False, HF_mutation=False, statutory_gold=False,
        scope="Same four existing pre-Torch runner imports only; all actual physical package owners enumerated. Later numerical/third-party import graph is not qualified.")
    write(REPORT, report)
    print(json.dumps(dict(status="pure_closure_preflight_passed", missing_producers=sorted(missing),
                          observed_producers=len(observed), new_artifacts=len(new["artifacts"]))))


if __name__ == "__main__":
    main()
