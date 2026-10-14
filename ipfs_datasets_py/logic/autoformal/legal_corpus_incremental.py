"""Verified legacy Lean artifact reuse through the existing LegalIR compiler.

Every current interpretation is regenerated. Only compiler artifacts are reused;
review and legal authority never follow from a cache hit. Public import is inert.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
import time
from pathlib import Path

from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_dag_json

from . import corpus_contracts as contracts
from . import legal_corpus_shared_lake as shared

CACHE_SCHEMA = "legal-corpus-direct-lean-cache/v1"
CONTRACT_SCHEMA = "legal-corpus-direct-lean-execution-contract/v1"
BUILD_SCHEMA = "legal-corpus-incremental-native-build/v1"
PROFILE = "verified-legacy-olean-per-module/v1"
MAX_ARTIFACT_BYTES = 4 * 1024**2
MAX_ARTIFACT_POPULATION_BYTES = 32 * 1024**2
MAX_LIBRARY_FILES = 16384
MAX_LIBRARY_BYTES = 3 * 1024**3
MAX_CLOSURE_BYTES = 4 * 1024**2
MAX_OBSERVATION_BYTES = 8 * 1024**2
_MODULE = re.compile(r"LegalCorpus(?:\.[A-Za-z][A-Za-z0-9]*)?\Z")
_IMPORT = re.compile(r"^import (LegalCorpus(?:\.[A-Za-z][A-Za-z0-9]*)?)$", re.M)
FALSE_FLAGS = {key: value for key, value in shared.FALSE_FLAGS.items()
               if key not in {"backend_executed", "lean_compilation_verified"}}
CACHE_FIELDS = {"profile", "qualified", "execution_contract", "module_facts", "artifact_root_cid", *FALSE_FLAGS}
CONTRACT_FIELDS = {"profile", "toolchain", "binary_sha256", "toolchain_closure", "owner_pins", "platform", "argv_recipe", "environment"}
FACT_FIELDS = {"module", "source", "imports", "recipe", "output"}
OUTPUT_FIELDS = {"module", "recipe_cid", "source_sha256", "import_artifact_sha256", "artifact_sha256",
                 "artifact_bytes", "theorem_axiom_dependencies", "kernel_checked"}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _fail(message):
    raise contracts.CorpusContractError(message)


def _owners():
    from ..integration.reasoning import legal_ir_incremental_compiler as incremental
    from ..integration.reasoning import legal_ir_pass_manager as passes
    from . import legal_source_definition_norm_lake as native

    return incremental, passes, native


def _owner_pins(incremental, passes):
    native = _owners()[2]
    return shared._pins() | native.pins() | {
        str(path.resolve()): _sha(path.read_bytes())
        for path in (Path(__file__), Path(incremental.__file__), Path(passes.__file__))}


def _deadline(deadline, cancellation):
    if time.monotonic() >= deadline:
        _fail("complete incremental build deadline exceeded")
    if cancellation is not None:
        predicate = getattr(cancellation, "is_cancelled", None) or getattr(cancellation, "is_set", None)
        if predicate is None and callable(cancellation):
            predicate = cancellation
        if predicate is None:
            _fail("supported incremental cancellation interface required")
        if predicate():
            _fail("incremental build admission cancelled")


def _identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _toolchain_closure(executable, deadline, cancellation):
    """Stream the complete selected installed library population, never tensors."""
    root = Path(executable).parent.parent / "lib" / "lean"
    shared.joint_owner._check_directories(root)
    endings = (".olean", ".olean.server", ".olean.private", ".ir.sig", ".ir", ".so")
    selected, entries = [], 0
    for path in root.rglob("*"):
        _deadline(deadline, cancellation)
        entries += 1
        if entries > 65536 or path.is_symlink():
            _fail("unsupported linked or oversized installed toolchain tree")
        if path.name.endswith(endings) or ".so." in path.name:
            selected.append(path)
            if len(selected) > MAX_LIBRARY_FILES:
                _fail("complete installed library file bound exceeded")
    raw, total = bytearray(), 0
    for path in sorted(selected, key=lambda item: item.relative_to(root).as_posix()):
        _deadline(deadline, cancellation)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                _fail("ordinary installed compiler library files required")
            total += before.st_size
            if total > MAX_LIBRARY_BYTES:
                _fail("complete installed library byte bound exceeded")
            digest, count = hashlib.sha256(), 0
            while block := stream.read(1024**2):
                _deadline(deadline, cancellation)
                count += len(block)
                digest.update(block)
                if count > before.st_size:
                    _fail("installed compiler library changed while reading")
            after = os.fstat(stream.fileno())
        if count != before.st_size or _identity(before) != _identity(after) or _identity(before) != _identity(path.lstat()):
            _fail("installed compiler library identity changed while reading")
        row = {"path": path.relative_to(root).as_posix(), "bytes": count, "sha256": digest.hexdigest()}
        raw.extend(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n")
        if len(raw) > MAX_CLOSURE_BYTES:
            _fail("complete toolchain closure manifest bound exceeded")
    if not selected or not (root / "Init.olean").is_file():
        _fail("installed implicit Init closure required")
    summary = contracts.seal_record({"schema": "legal-corpus-installed-lean-library-closure/v1",
        "profile": "all-olean-parts-ir-and-shared-libraries/v1", "file_count": len(selected),
        "file_bytes": total, "manifest_bytes": len(raw), "manifest_sha256": _sha(raw)})
    return summary, bytes(raw)


def _recipe(module, source, imports, contract):
    return {"module": module, "source_sha256": _sha(source.encode("utf-8")),
            "imports": imports, "contract_cid": contract["record_cid"]}


def _facts(preparation, contract):
    manifest, files = preparation.to_dict(), dict(preparation.files)
    facts = []
    for module in manifest["expected_modules"]:
        if not _MODULE.fullmatch(module):
            _fail("bounded generated module identity required")
        source = files[module.replace(".", "/") + ".lean"]
        imports = _IMPORT.findall(source)
        if re.search(r"^\s*module(?:\s|$)", source, re.M):
            _fail("module-system artifacts require a different cache profile")
        facts.append({"module": module, "source": source, "imports": imports,
                      "recipe": _recipe(module, source, imports, contract), "output": None})
    known = {row["module"] for row in facts}
    if len(known) != len(facts) or any(item not in known for row in facts for item in row["imports"]):
        _fail("complete closed generated module population required")
    return facts


def _artifact_root(facts):
    return cid_for_dag_json({row["module"]: row["output"]["artifact_sha256"] for row in facts})


def _previous(raw, expected_sha256, artifacts):
    if raw is None:
        if expected_sha256 is not None or artifacts is not None:
            _fail("previous cache, independent pin and complete artifacts must be supplied together")
        return None
    value = contracts.load_record_bytes(raw, expected_sha256=expected_sha256)
    value = contracts.validate_record(value, schema=CACHE_SCHEMA, fields=CACHE_FIELDS)
    if (value["profile"] != PROFILE or value["qualified"] is not True
            or any(value[key] is not False for key in FALSE_FLAGS)):
        _fail("independently pinned qualified technical cache required")
    contract = contracts.validate_record(value["execution_contract"], schema=CONTRACT_SCHEMA, fields=CONTRACT_FIELDS)
    facts = value["module_facts"]
    if type(facts) is not list or not 1 <= len(facts) <= 130 or type(artifacts) is not dict:
        _fail("bounded complete prior module/artifact population required")
    by_module = {row.get("module"): row for row in facts if type(row) is dict}
    if len(by_module) != len(facts) or set(by_module) != set(artifacts):
        _fail("prior artifact population differs or repeats a module")
    total = 0
    for row in facts:
        contracts.require_keys(row, FACT_FIELDS, "prior module fact")
        module = contracts.require_text(row["module"], "prior module")
        if not _MODULE.fullmatch(module):
            _fail("unsupported prior module identity")
        source = contracts.require_text(row["source"], "prior generated source", max_bytes=contracts.MAX_RECORD_BYTES)
        imports = _IMPORT.findall(source)
        if row["imports"] != imports or any(item not in by_module for item in imports):
            _fail("prior import population differs")
        recipe = _recipe(module, source, imports, contract)
        if row["recipe"] != recipe:
            _fail("prior recipe differs from its exact source and contract")
        output = contracts.require_keys(row["output"], OUTPUT_FIELDS, "prior native output")
        artifact = artifacts[module]
        if type(artifact) is not bytes or not 1 <= len(artifact) <= MAX_ARTIFACT_BYTES:
            _fail("bounded complete prior compiler artifact bytes required")
        total += len(artifact)
        if total > MAX_ARTIFACT_POPULATION_BYTES:
            _fail("prior artifact aggregate byte bound exceeded")
        expected_imports = {item: by_module[item]["output"]["artifact_sha256"] for item in imports}
        if (output["module"] != module or output["recipe_cid"] != cid_for_dag_json(recipe)
                or output["source_sha256"] != recipe["source_sha256"]
                or output["import_artifact_sha256"] != expected_imports
                or output["artifact_sha256"] != _sha(artifact) or output["artifact_bytes"] != len(artifact)
                or output["kernel_checked"] is not True):
            _fail("prior module output differs from independently pinned artifacts/recipe")
        theorems = re.findall(r"^theorem ([A-Za-z0-9_]+)", source, re.M)
        if output["theorem_axiom_dependencies"] != {module + "." + name: [] for name in theorems}:
            _fail("prior theorem evidence differs from exact generated declarations")
    if value["artifact_root_cid"] != _artifact_root(facts):
        _fail("prior artifact root differs")
    return value


def _key(module):
    return "m" + _sha(module.encode())


def _compiler(facts, functions, incremental, passes):
    def order(module):
        if module == "LegalCorpus.Prelude":
            return 0
        if module.startswith("LegalCorpus.Definition"):
            return 1
        if module.startswith("LegalCorpus.Norm"):
            return 2
        if module == "LegalCorpus":
            return 3
        _fail("unsupported generated module role")

    specs = [passes.LegalIRPassSpec(pass_id=_key(row["module"]), title=row["module"],
        kind=passes.LegalIRPassKind.COMPILER, order=order(row["module"]),
        declared_inputs=("requests." + _key(row["module"]),),
        declared_outputs=("compiled." + _key(row["module"]),),
        depends_on=tuple(_key(item) for item in row["imports"]),
        metadata={"native_recipe": row["recipe"]}) for row in facts]
    return incremental.LegalIRIncrementalCompiler(specs, functions, max_workers=1, resource_limits={"cpu": 1})


def _state(facts):
    return {"requests": {_key(row["module"]): row["recipe"] for row in facts}}


def _run(compiler, facts, previous=None):
    return compiler.compile(_state(facts), previous=previous, sources={}, citations={}, symbols={}, temporal={})


def build_incremental_shared_corpus(preparation, *, candidate_inputs, expected_population, toolchain,
        lake_executable, output_directory, previous_cache_raw=None, expected_previous_cache_sha256=None,
        previous_artifacts=None, timeout_seconds=60, cancellation=None):
    """Compile/reuse exact modules under the caller's shared validation lease."""
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 60:
        _fail("bounded complete incremental build timeout required")
    started, deadline = time.monotonic(), time.monotonic() + timeout_seconds
    _deadline(deadline, cancellation)
    output = shared.joint_owner._path(output_directory)
    shared.joint_owner._check_directories(output.parent, allow_missing=True)
    if output.exists() or output.is_symlink():
        _fail("fresh incremental output directory required")
    checked = shared.validate_shared_definition_corpus(preparation, candidate_inputs=candidate_inputs,
        expected_population=expected_population, toolchain=toolchain)
    prior = _previous(previous_cache_raw, expected_previous_cache_sha256, previous_artifacts)
    incremental, passes, native = _owners()
    owner_pins = _owner_pins(incremental, passes)
    _deadline(deadline, cancellation)
    # The two installed-toolchain version probes each have a five-second cap.
    if deadline - time.monotonic() < 10:
        _fail("insufficient complete build deadline for bounded version probes")
    executable, binaries, probes = native.shared._installed_toolchain(lake_executable, toolchain)
    _deadline(deadline, cancellation)
    lean = Path(executable).parent / "lean"
    closure, closure_raw = _toolchain_closure(executable, deadline, cancellation)
    contract = contracts.seal_record({"schema": CONTRACT_SCHEMA, "profile": PROFILE, "toolchain": toolchain,
        "binary_sha256": binaries, "toolchain_closure": closure, "owner_pins": owner_pins,
        "platform": {"system": platform.system(), "machine": platform.machine(), "libc": list(platform.libc_ver())},
        "argv_recipe": ["installed-sibling-lean", "-o", "compiled/<module>.olean", "<module>.lean"],
        "environment": {"LEAN_PATH": "compiled", "LEAN_NUM_THREADS": "1"}})
    facts = _facts(checked, contract)
    by_module = {row["module"]: row for row in facts}
    artifacts = {} if prior is None else {name: raw for name, raw in previous_artifacts.items() if name in by_module}
    old_snapshot = None
    if prior is not None:
        old_facts = prior["module_facts"]
        functions = {_key(row["module"]): (lambda _state, row=row: {"compiled": {_key(row["module"]): row["output"]}})
                     for row in old_facts}
        old_result = _run(_compiler(old_facts, functions, incremental, passes), old_facts)
        if not old_result.successful:
            _fail("prior module dependency graph failed independent reconstruction")
        old_snapshot = old_result.snapshot
    observations, fresh = [], []

    def function(row):
        def compile_module(state):
            module, recipe = row["module"], row["recipe"]
            dependencies = {item: state.get("compiled", {}).get(_key(item)) for item in row["imports"]}
            import_shas = {item: item_output["artifact_sha256"] for item, item_output in dependencies.items()
                           if item_output is not None and item_output["kernel_checked"]}
            result_output = {"module": module, "recipe_cid": cid_for_dag_json(recipe),
                "source_sha256": recipe["source_sha256"], "import_artifact_sha256": import_shas,
                "artifact_sha256": None, "artifact_bytes": 0, "theorem_axiom_dependencies": {}, "kernel_checked": False}
            if len(import_shas) != len(dependencies):
                _fail("current dependency lacks a checked compiler artifact")
            _deadline(deadline, cancellation)
            needed, frontier = set(), list(row["imports"])
            while frontier:
                item = frontier.pop()
                if item not in needed:
                    needed.add(item)
                    frontier.extend(by_module[item]["imports"])
            inputs = {module.replace(".", "/") + ".lean": row["source"], "compiled/.keep": b""}
            for item in sorted(needed):
                item_output = state["compiled"][_key(item)]
                if item not in artifacts or _sha(artifacts[item]) != item_output["artifact_sha256"]:
                    _fail("dependency artifact differs before native import")
                inputs["compiled/" + item.replace(".", "/") + ".olean"] = artifacts[item]
            path = "compiled/" + module.replace(".", "/") + ".olean"
            # The root has no imports only in a one-module profile; create its
            # relative output parent without trusting any external filesystem.
            inputs["compiled/LegalCorpus/.keep"] = b""
            command = (str(lean), "-o", path, module.replace(".", "/") + ".lean")
            result = native.process.BoundedToolRunner().run(native.process.ToolRunRequest(
                argv=command, input_files=inputs, output_paths=(path,), environment=contract["environment"],
                limits=native.process.ToolRunLimits(timeout_seconds=max(0.001, deadline - time.monotonic()),
                    cpu_seconds=max(0.001, deadline - time.monotonic()), resident_memory_bytes=2 * 1024**3,
                    max_output_bytes=MAX_ARTIFACT_BYTES, max_input_bytes=40 * 1024**2, max_workspace_bytes=128 * 1024**2,
                    max_output_files=1)), **({"cancellation": cancellation} if cancellation is not None else {}))
            fresh.append(module)
            observations.append({"module": module, **result.to_dict(),
                "output_files": {name: {"bytes": len(raw), "sha256": _sha(raw)} for name, raw in result.output_files.items()}})
            raw = result.output_files.get(path)
            expected_theorems = [module + "." + name for name in re.findall(r"^theorem ([A-Za-z0-9_]+)", row["source"], re.M)]
            axioms = {name: [] for name in expected_theorems if "'" + name + "' does not depend on any axioms" in result.stdout}
            passed = bool(result.ok and result.pid is not None and tuple(result.command) == command
                and set(result.output_files) == {path} and type(raw) is bytes and 1 <= len(raw) <= MAX_ARTIFACT_BYTES
                and result.workspace_cleaned and not result.error and not result.output_truncated
                and not result.workspace_limit_exceeded and len(axioms) == len(expected_theorems)
                and not re.search(r"\b(?:sorry|sorryAx)\b", result.stdout + result.stderr))
            if passed:
                artifacts[module] = raw
                result_output.update(artifact_sha256=_sha(raw), artifact_bytes=len(raw),
                                     theorem_axiom_dependencies=axioms, kernel_checked=True)
            else:
                artifacts.pop(module, None)
                _fail("native module compilation failed: " + module)
            return {"compiled": {_key(module): result_output}}
        return compile_module

    functions = {_key(row["module"]): function(row) for row in facts}
    result = _run(_compiler(facts, functions, incremental, passes), facts, old_snapshot)
    for row in facts:
        row["output"] = result.output_state.get("compiled", {}).get(_key(row["module"]))
    post_error = None
    try:
        _deadline(deadline, cancellation)
        shared.validate_shared_definition_corpus(checked, candidate_inputs=candidate_inputs,
            expected_population=expected_population, toolchain=toolchain)
        after_closure, after_raw = _toolchain_closure(executable, deadline, cancellation)
        if closure != after_closure or closure_raw != after_raw or _owner_pins(incremental, passes) != owner_pins:
            _fail("compiler closure or owner changed during native compilation")
        if any(_sha(Path(name).read_bytes()) != digest for name, digest in binaries.items()):
            _fail("native compiler executable changed during compilation")
    except (ValueError, TypeError, KeyError, IndexError, OSError, UnicodeError, RecursionError) as error:
        post_error = {"type": type(error).__name__, "message": str(error)[:2048]}
    qualified = bool(result.successful and post_error is None and all(
        row["output"] is not None and row["output"]["kernel_checked"] is True
        and row["output"]["recipe_cid"] == cid_for_dag_json(row["recipe"])
        and row["output"]["source_sha256"] == row["recipe"]["source_sha256"]
        and row["output"]["import_artifact_sha256"] == {
            item: _sha(artifacts[item]) for item in row["imports"] if item in artifacts}
        and len(row["output"]["import_artifact_sha256"]) == len(row["imports"])
        and row["output"]["theorem_axiom_dependencies"] == {
            row["module"] + "." + name: []
            for name in re.findall(r"^theorem ([A-Za-z0-9_]+)", row["source"], re.M)}
        and row["module"] in artifacts and _sha(artifacts[row["module"]]) == row["output"]["artifact_sha256"]
        for row in facts))
    retained = {row["module"]: artifacts[row["module"]] for row in facts if row["module"] in artifacts
                and row["output"] is not None and row["output"]["kernel_checked"]}
    if sum(map(len, retained.values())) > MAX_ARTIFACT_POPULATION_BYTES:
        _fail("complete compiled artifact population exceeds byte bound")
    artifact_root = cid_for_dag_json({name: _sha(raw) for name, raw in sorted(retained.items())})
    cache = contracts.seal_record({"schema": CACHE_SCHEMA, "profile": PROFILE, "qualified": qualified,
        "execution_contract": contract, "module_facts": facts, "artifact_root_cid": artifact_root, **FALSE_FLAGS})
    cache_raw = canonical_dag_json_bytes(cache)
    reused = [row["module"] for row in facts if row["module"] not in fresh and row["output"] is not None
              and row["output"]["kernel_checked"]]
    observation_raw = b"".join(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
                               for row in observations)
    if len(observation_raw) > MAX_OBSERVATION_BYTES:
        _fail("complete native execution observation byte bound exceeded")
    receipt = contracts.seal_record({"schema": BUILD_SCHEMA, "profile": PROFILE,
        "preparation_cid": checked.to_dict()["record_cid"], "execution_contract_cid": contract["record_cid"],
        "cache_identity": {"record_cid": cache["record_cid"], "sha256": _sha(cache_raw), "bytes": len(cache_raw)},
        "previous_cache_cid": None if prior is None else prior["record_cid"],
        "compiled_modules": fresh, "reused_modules": reused, "expected_modules": [row["module"] for row in facts],
        "fresh_theorems": [name for row in facts if row["module"] in fresh and row["output"] is not None
                           for name in row["output"]["theorem_axiom_dependencies"]],
        "reused_theorems": [name for row in facts if row["module"] in reused for name in row["output"]["theorem_axiom_dependencies"]],
        "artifact_files": {name: "compiled/" + name.replace(".", "/") + ".olean" for name in retained},
        "artifact_sha256": {name: _sha(raw) for name, raw in retained.items()}, "artifact_root_cid": artifact_root,
        "toolchain_closure": closure, "version_probes": probes, "post_run_validation_error": post_error,
        "execution_observations": {"path": "module-executions.jsonl", "bytes": len(observation_raw),
                                   "sha256": _sha(observation_raw)},
        "toolchain_probes_executed": True, "module_compile_invocations": len(observations),
        "framework_successful": result.successful, "framework_diagnostics": [item.to_dict() for item in result.diagnostics],
        "framework_metrics": result.metrics.to_dict(), "observed_wall_seconds": time.monotonic() - started,
        "build_passed": qualified, "lean_compilation_verified": qualified, "backend_executed": bool(observations),
        "composition_obligations_checked": qualified, **FALSE_FLAGS})
    shared._write_frozen_project(checked, output / "project")
    shared._write_compiled(output / "compiled", {name.replace(".", "/") + ".olean": raw for name, raw in retained.items()})
    for name, raw in (("cache.json", cache_raw), ("toolchain-closure.jsonl", closure_raw),
                      ("module-executions.jsonl", observation_raw)):
        with (output / name).open("xb") as stream:
            stream.write(raw)
        if (output / name).read_bytes() != raw:
            _fail("retained native build evidence differs on readback")
    # Publish the receipt only after all referenced compiler evidence exists.
    receipt_raw = canonical_dag_json_bytes(receipt)
    with (output / "build-receipt.json").open("xb") as stream:
        stream.write(receipt_raw)
    if (output / "build-receipt.json").read_bytes() != receipt_raw:
        _fail("retained native build receipt differs on readback")
    return receipt


__all__ = ["build_incremental_shared_corpus"]
