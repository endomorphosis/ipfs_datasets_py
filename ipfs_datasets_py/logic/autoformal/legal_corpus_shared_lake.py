"""Shared source-bound definitions and conditional native Lean composition.

This bounded orchestration delegates native parsing and lowering. Identical
explicit definition interpretations may share a module only with identical
scope, source and physical origins. Kernel checking does not establish law.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

from . import corpus_contracts as contracts
from . import legal_corpus_lake as joint_owner

SCHEMA = "legal-corpus-shared-definition-lake-preparation/v1"
KEY_SCHEMA = "legal-corpus-exact-definition-sharing-key/v1"
BUILD_SCHEMA = "legal-corpus-shared-definition-native-build/v1"
PROFILE = "exact-source-scoped-unary-definition-sharing/v1"
MAX_FILES = 2 * joint_owner.MAX_CANDIDATES + 5
FALSE_FLAGS = dict(joint_owner.FALSE_FLAGS)
FIELDS = {
    "profile", "toolchain", "population", "population_cid", "original_preparation_cid",
    "definition_modules", "norm_bindings", "expected_modules", "file_sha256",
    "producer_pins", "native_producer_pins", "shared_definition_deduplication",
    "external_definition_resolution", "preparation_only", "theorem_assumptions", *FALSE_FLAGS,
}


@dataclass(frozen=True)
class SharedCorpusPreparation:
    manifest_json: str
    files: tuple[tuple[str, str], ...]

    def to_dict(self):
        raw = self.manifest_json.encode("utf-8")
        return contracts.load_record_bytes(raw, expected_sha256=_sha(raw))


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _fail(message):
    raise contracts.CorpusContractError(message)


def _pins():
    return joint_owner._pins() | {str(Path(joint_owner.__file__).resolve()):
        _sha(Path(joint_owner.__file__).read_bytes()), str(Path(__file__).resolve()):
        _sha(Path(__file__).read_bytes())}


def _sharing_key(candidate):
    bindings = [row for row in candidate["source_bindings"]
                if row["role"].startswith("definition_") or row["role"] == "scope_literal"]
    touched = {index for row in bindings for index in row["paragraph_indices"]}
    bindings += [row for row in candidate["source_bindings"] if row["role"].startswith("physical_paragraph/")
                 and touched.intersection(row["paragraph_indices"])]
    origins = {row["source_occurrence_cid"] for row in bindings}
    return contracts.seal_record({
        "schema": KEY_SCHEMA, "profile": PROFILE,
        "source_version_cid": candidate["source_version"]["record_cid"],
        "scope_record_cid": candidate["scope_record"]["record_cid"],
        "declaration": candidate["definition_record"]["declaration"],
        "native_ast": candidate["definition_record"]["native_ast"],
        "definition_symbol_rebinding": candidate["symbol_record"]["definition_symbol_rebinding"],
        "source_bindings": bindings,
        "source_occurrences": [row for row in candidate["source_occurrences"]
                               if row["record_cid"] in origins],
    })


def _module(prefix, identity):
    return "LegalCorpus." + prefix + _sha(identity.encode("utf-8"))


def _file(module, imports, body):
    return "\n".join("import " + item for item in imports) + "\nnamespace " + module + "\n" + body + "\nend " + module + "\n"


def prepare_shared_definition_corpus(candidate_inputs, *, expected_population, toolchain):
    """Share exact explicit definitions while preserving every original norm."""
    pins = _pins()
    original = joint_owner.prepare_definition_norm_corpus(
        candidate_inputs, expected_population=expected_population, toolchain=toolchain)
    original_manifest = original.to_dict()
    from . import legal_source_definition_norm_lake as native

    routes, emitter = native.bridge.routes, native.emitters
    files = {
        "lakefile.toml": 'name = "legal_corpus_shared"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "legal"\nroots = ["LegalCorpus"]\n',
        "lean-toolchain": toolchain + "\n",
        "LegalCorpus/Prelude.lean": "namespace LegalCorpus\n" + emitter.PRELUDE + "\nend LegalCorpus\n",
        "definition-inputs.json": dict(original.files)["definition-inputs.json"],
    }
    definitions, norms = {}, []
    for inputs, population, binding in zip(
            candidate_inputs, original_manifest["population"], original_manifest["bindings"], strict=True):
        candidate = contracts.load_record_bytes(inputs["candidate_raw"], expected_sha256=population["candidate_sha256"])
        report = contracts.load_record_bytes(inputs["report_raw"], expected_sha256=population["report_sha256"])
        definition_ast = candidate["definition_record"]["native_ast"]
        norm_ast = candidate["norm_record"]["native_ast"]
        joint_ast = candidate["ast_record"]["native_ast"]
        if (joint_ast.get("node_type") != "BinaryFormula" or joint_ast.get("operator", {}).get("value") != "∧"
                or joint_ast.get("left") != definition_ast or joint_ast.get("right") != norm_ast):
            _fail("shared components do not preserve the original ordered joint AST")
        key = _sharing_key(candidate)
        key_cid = key["record_cid"]
        definition_module = _module("Definition", key_cid)
        contributor = {
            "ordinal": binding["ordinal"], "candidate_cid": candidate["record_cid"],
            "definition_record_cid": candidate["definition_record"]["record_cid"],
            "interpretation_cid": candidate["report_record"]["record_cid"],
            "term_record_cid": candidate["term_record"]["record_cid"],
            "symbol_record_cid": candidate["symbol_record"]["record_cid"],
        }
        if key_cid not in definitions:
            fragment = routes.prepare_native_fragment(
                family="fol", formula=report["bound_definition_native"]["formula"], expected_ast=definition_ast)
            body = emitter.FormulaRenderer().formula(definition_ast["formula"]["right"], {"x": "entity"})
            body_declaration = ("def bodyAt {Entity Agent : Type} (i : Interpretation Entity Agent) "
                                "(entity : Entity) : Nat → Prop := " + body)
            path = definition_module.replace(".", "/") + ".lean"
            files[path] = _file(definition_module, ["LegalCorpus.Prelude"], fragment["lean_body"] + "\n" + body_declaration)
            definitions[key_cid] = {
                "sharing_key": key, "sharing_key_cid": key_cid,
                "module": definition_module, "module_path": path,
                "qualified_declaration": definition_module + ".formula_0",
                "body_declaration": definition_module + ".bodyAt",
                "contributors": [], "native_fragment": fragment,
                "module_sha256": _sha(files[path].encode("utf-8")),
            }
        definitions[key_cid]["contributors"].append(contributor)
        parsed = routes.qualification._strict_tdfol(report["native"]["formula"])[0]
        fragment = routes.prepare_native_fragment(
            family=report["family"], formula=parsed.right.to_string(), expected_ast=norm_ast)
        consequence = emitter.FormulaRenderer().formula(norm_ast["formula"]["right"], {"x": "entity"})
        module = _module("Norm", candidate["record_cid"])
        path = module.replace(".", "/") + ".lean"
        body = (fragment["lean_body"] + "\n"
            + "def modalActionAt {Entity Agent : Type} (i : Interpretation Entity Agent) "
              "(entity : Entity) : Nat → Prop := " + consequence + "\n"
            + "def jointAt {Entity Agent : Type} (i : Interpretation Entity Agent) : Nat → Prop := "
              "fun t => " + definition_module + ".formula_0 i t ∧ formula_0 i t\n"
            + "theorem consequence_of_definition {Entity Agent : Type} (i : Interpretation Entity Agent) "
              "(t : Nat) (entity : Entity)\n"
            + "    (hDef : " + definition_module + ".formula_0 i t) (hNorm : formula_0 i t)\n"
            + "    (hBody : " + definition_module + ".bodyAt i entity t) : modalActionAt i entity t := by\n"
            + "  exact hNorm entity ((hDef entity).mpr hBody)\n"
            + "#print axioms consequence_of_definition")
        files[path] = _file(module, [definition_module], body)
        norms.append({
            "ordinal": binding["ordinal"], "candidate_cid": candidate["record_cid"],
            "definition_key_cid": key_cid, "definition_module": definition_module,
            "module": module, "module_path": path,
            "qualified_declaration": module + ".formula_0",
            "joint_declaration": module + ".jointAt",
            "composition_theorem": module + ".consequence_of_definition",
            "module_sha256": _sha(files[path].encode("utf-8")),
            "native_norm_fragment": fragment, "original_joint_binding": binding,
            "original_joint_lean_sha256": _sha(candidate["ast_record"]["lean_body"].encode("utf-8")),
        })
    definition_rows = [definitions[key] for key in sorted(definitions)]
    files["LegalCorpus.lean"] = "\n".join("import " + row["module"] for row in norms) + "\n"
    if (len(files) > MAX_FILES or sum(len(body.encode("utf-8")) for body in files.values()) > joint_owner.MAX_PROJECT_BYTES
            or any(native.shared._REFUSED.search(body) for name, body in files.items() if name.endswith(".lean"))):
        _fail("unsupported or oversized complete shared Lean project")
    if _pins() != pins:
        _fail("shared corpus implementation changed during preparation")
    manifest = contracts.seal_record({
        "schema": SCHEMA, "profile": PROFILE, "toolchain": toolchain,
        "population": original_manifest["population"], "population_cid": original_manifest["population_cid"],
        "original_preparation_cid": original_manifest["record_cid"],
        "definition_modules": definition_rows, "norm_bindings": norms,
        "expected_modules": ["LegalCorpus.Prelude", *[row["module"] for row in definition_rows],
                             *[row["module"] for row in norms], "LegalCorpus"],
        "file_sha256": {name: _sha(body.encode("utf-8")) for name, body in sorted(files.items())},
        "producer_pins": pins, "native_producer_pins": original_manifest["native_preparation_manifest"]["producer_pins"],
        "shared_definition_deduplication": True, "external_definition_resolution": False,
        "preparation_only": True,
        "theorem_assumptions": ["The exact shared definition holds at the evaluation time.",
            "The universally guarded norm holds at that same time under the same interpretation.",
            "The declared definition body holds for the supplied entity at that time.",
            "The conclusion is the parameterized modal action; it does not establish actual action truth or legal truth."],
        **FALSE_FLAGS,
    })
    return SharedCorpusPreparation(canonical_dag_json_bytes(manifest).decode("utf-8"), tuple(sorted(files.items())))


def validate_shared_definition_corpus(preparation, *, candidate_inputs, expected_population, toolchain):
    if type(preparation) is not SharedCorpusPreparation:
        _fail("typed shared corpus preparation required")
    contracts.validate_record(preparation.to_dict(), schema=SCHEMA, fields=FIELDS)
    expected = prepare_shared_definition_corpus(
        candidate_inputs, expected_population=expected_population, toolchain=toolchain)
    if preparation != expected:
        _fail("shared corpus differs from independent complete regeneration")
    return preparation


def load_shared_definition_corpus(directory, *, expected_manifest_sha256,
                                  candidate_inputs, expected_population, toolchain):
    expected = prepare_shared_definition_corpus(
        candidate_inputs, expected_population=expected_population, toolchain=toolchain)
    files = joint_owner._read_files(directory, {name for name, _ in expected.files}
                                   | {joint_owner.MANIFEST_FILE}, maximum_files=MAX_FILES)
    raw = files.pop(joint_owner.MANIFEST_FILE)
    contracts.load_record_bytes(raw, expected_sha256=expected_manifest_sha256)
    if raw != expected.manifest_json.encode("utf-8") or files != {
            name: body.encode("utf-8") for name, body in expected.files}:
        _fail("shared corpus project differs from independent complete regeneration")
    return expected


def write_shared_definition_corpus(preparation, directory, *, candidate_inputs, expected_population, toolchain):
    checked = validate_shared_definition_corpus(
        preparation, candidate_inputs=candidate_inputs, expected_population=expected_population, toolchain=toolchain)

    def readback(root, raw):
        load_shared_definition_corpus(root, expected_manifest_sha256=_sha(raw),
            candidate_inputs=candidate_inputs, expected_population=expected_population, toolchain=toolchain)

    return joint_owner._write_project(checked, directory, readback=readback, maximum_files=MAX_FILES)


def build_shared_definition_corpus(preparation, *, candidate_inputs, expected_population, toolchain,
                                   lake_executable, output_directory, timeout_seconds=60, cancellation=None):
    """Compile exact bound files; callers acquire the shared validation lease."""
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 60:
        _fail("bounded native build timeout required")
    output = joint_owner._path(output_directory)
    joint_owner._check_directories(output.parent, allow_missing=True)
    if output.exists() or output.is_symlink():
        _fail("fresh shared build output directory required")
    checked = validate_shared_definition_corpus(
        preparation, candidate_inputs=candidate_inputs, expected_population=expected_population, toolchain=toolchain)
    from . import legal_source_definition_norm_lake as native

    executable, binaries, probes = native.shared._installed_toolchain(lake_executable, toolchain)
    manifest = checked.to_dict()
    command = (str(executable), "--offline", "--no-cache", "build", "legal")
    modules = manifest["expected_modules"]
    paths = tuple(".lake/build/lib/lean/" + module.replace(".", "/") + ".olean" for module in modules)
    result = native.process.BoundedToolRunner().run(native.process.ToolRunRequest(
        argv=command, input_files=dict(checked.files), output_paths=paths,
        environment={"ELAN_TOOLCHAIN": toolchain, "LEAN_NUM_THREADS": "1"},
        limits=native.process.ToolRunLimits(timeout_seconds=timeout_seconds, cpu_seconds=timeout_seconds,
            resident_memory_bytes=2 * 1024**3, max_output_bytes=262144,
            max_input_bytes=joint_owner.MAX_PROJECT_BYTES, max_workspace_bytes=128 * 1024**2,
            max_output_files=2 * joint_owner.MAX_CANDIDATES + 2)),
        **({"cancellation": cancellation} if cancellation is not None else {}))
    post_run_error = None
    try:
        validate_shared_definition_corpus(
            checked, candidate_inputs=candidate_inputs, expected_population=expected_population, toolchain=toolchain)
    except (ValueError, TypeError, KeyError, IndexError, OSError, UnicodeError, RecursionError) as error:
        post_run_error = {"type": type(error).__name__, "message": str(error)[:2048]}
    binary_error = None
    try:
        unchanged = all(_sha(Path(name).read_bytes()) == digest for name, digest in binaries.items())
    except OSError as error:
        unchanged = False
        binary_error = {"type": type(error).__name__, "message": str(error)[:2048]}
    coverage = set(result.output_files) == set(paths) and all(result.output_files.values())
    axioms = {}
    for row in manifest["norm_bindings"]:
        theorem = row["composition_theorem"]
        if "'" + theorem + "' does not depend on any axioms" in result.stdout:
            axioms[theorem] = []
    passed = bool(result.ok and result.pid is not None and tuple(result.command) == command and coverage and unchanged
        and len(axioms) == len(manifest["norm_bindings"]) and not result.output_truncated
        and not result.workspace_limit_exceeded and result.workspace_cleaned and not result.error
        and post_run_error is None and not re.search(r"\b(?:sorry|sorryAx)\b", result.stdout + result.stderr))
    receipt = contracts.seal_record({
        "schema": BUILD_SCHEMA, "profile": PROFILE, "preparation_cid": manifest["record_cid"],
        "preparation_manifest_sha256": _sha(checked.manifest_json.encode("utf-8")),
        "toolchain": toolchain, "command": list(command), "returncode": result.returncode,
        "pid": result.pid, "expected_modules": modules,
        "compiled_modules": [module for module, path in zip(modules, paths, strict=True) if path in result.output_files],
        "manifest_coverage_passed": bool(coverage), "binary_sha256": binaries, "binaries_unchanged": unchanged,
        "post_run_validation_passed": post_run_error is None, "post_run_validation_error": post_run_error,
        "binary_recheck_error": binary_error, "execution_error": result.error,
        "version_probes": probes, "artifact_sha256": {name: _sha(raw) for name, raw in result.output_files.items()},
        "artifact_files": {name: "compiled/" + name.removeprefix(".lake/build/lib/lean/")
                           for name in paths if name in result.output_files},
        "theorem_axiom_dependencies": axioms, "theorem_assumptions": manifest["theorem_assumptions"],
        "stdout": result.stdout, "stderr": result.stderr, "timed_out": result.timed_out,
        "output_truncated": result.output_truncated, "workspace_limit_exceeded": result.workspace_limit_exceeded,
        "resource_exhausted": result.resource_exhausted, "workspace_cleaned": result.workspace_cleaned,
        "cancelled": result.cancelled, "unavailable": result.unavailable,
        "process_tree_terminated": result.process_tree_terminated, "build_passed": passed,
        "composition_obligations_checked": passed,
        **(FALSE_FLAGS | {"backend_executed": result.pid is not None, "lean_compilation_verified": passed}),
    })
    _write_frozen_project(checked, output / "project")
    _write_compiled(output / "compiled", {name.removeprefix(".lake/build/lib/lean/"): result.output_files[name]
                                          for name in paths if name in result.output_files})
    with (output / "build-receipt.json").open("xb") as destination:
        destination.write(canonical_dag_json_bytes(receipt))
    return receipt


def _write_frozen_project(preparation, directory):
    """Retain exactly executed inputs, including failed post-run qualification."""
    expected_files = {name: body.encode("utf-8") for name, body in preparation.files}
    expected_files[joint_owner.MANIFEST_FILE] = preparation.manifest_json.encode("utf-8")

    def readback(root, raw):
        observed = joint_owner._read_files(root, set(expected_files), maximum_files=MAX_FILES)
        if raw != expected_files[joint_owner.MANIFEST_FILE] or observed != expected_files:
            _fail("frozen executed project failed exact readback")

    return joint_owner._write_project(preparation, directory, readback=readback, maximum_files=MAX_FILES)


def _write_compiled(directory, artifacts):
    directory.mkdir(mode=0o700, exist_ok=False)
    root_fd = os.open(directory, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    descriptors = {"": root_fd}
    try:
        for name, raw in artifacts.items():
            dirname, _, basename = name.rpartition("/")
            if dirname and dirname not in descriptors:
                os.mkdir(dirname, mode=0o700, dir_fd=root_fd)
                descriptors[dirname] = os.open(
                    dirname, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY, dir_fd=root_fd)
            joint_owner._write_new_file(descriptors[dirname], basename, raw)
        for fd in descriptors.values():
            os.fsync(fd)
    finally:
        for fd in reversed(list(descriptors.values())):
            os.close(fd)


__all__ = ["SharedCorpusPreparation", "prepare_shared_definition_corpus", "validate_shared_definition_corpus",
    "write_shared_definition_corpus", "load_shared_definition_corpus", "build_shared_definition_corpus"]
