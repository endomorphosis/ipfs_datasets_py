"""Bounded native observation of namespace-bound corpus theorem elaboration.

An additive clean source build checks fifteen aliases against the actual original
theorems. Machine observations retain both elaborated types and kernel equality
checks. They do not issue backend requests, typed theorem receipts, legal/source
admission, compiler-artifact reuse credentials, or model convergence evidence.
Public import uses only the standard library.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re

BUILD_SCHEMA = "legal-corpus-v2-preservation-elaboration-native-build/v1"
PROFILE = "clean-native-corpus-theorem-type-elaboration/v1"
TYPE_CHECK_SCHEMA = "legal-corpus-v2-native-theorem-type-check/v1"
MAX_RECORD_BYTES = 1024 * 1024
MAX_PROJECT_BYTES = 8 * MAX_RECORD_BYTES
MAX_PREPARATION_BYTES = 20 * MAX_RECORD_BYTES
MAX_INPUT_BYTES = 48 * MAX_RECORD_BYTES
MAX_CAPTURE_BYTES = 4 * MAX_RECORD_BYTES
MAX_LOG_PREVIEW_BYTES = 32768
MAX_FILES = 17
MAX_MODULES = 13
MAX_THEOREMS = 30
MAX_TYPE_CHECKS = 15
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_OPERATION_PINS = None
_PREPARATION_MODULE = "ipfs_datasets_py.logic.autoformal.legal_corpus_definition_use_preservation_elaboration_v2"
_PACKET_ARGUMENTS = frozenset({
    "expected_preparation_sha256", "expected_corpus_preparation_sha256",
    "expected_assessment_file_sha256", "expected_receipt_file_sha256",
    "expected_bundle_sha256", "review_inputs", "toolchain", "expected_binary_sha256",
    "expected_packet_observation_sha256",
})
_TRUE_TYPE_FLAGS = frozenset(("expr_equal", "kernel_defeq", "original_kernel_check", "alias_kernel_check",
                              "closed_types", "prop_type", "level_params_equal"))
_TYPE_FIELDS = _TRUE_TYPE_FLAGS | frozenset(("schema", "original_name", "alias_name", "original_type", "alias_type",
                                            "original_level_params", "alias_level_params"))
FALSE_FLAGS = dict.fromkeys((
    "source_authenticity_verified publisher_authenticity_verified legal_currentness_verified "
    "source_semantics_verified applicability_verified context_closure_verified independently_reviewed "
    "human_identity_verified human_independence_verified meaning_admitted admitted formalized "
    "semantic_graph_admitted proof_authority training_qualified training_gold_qualified "
    "evaluation_gold_qualified Lean_admitted model_executed learned_translation "
    "source_to_model_equivalence_proved source_fidelity_proved translation_preservation_proved "
    "cross_family_equivalence_verified general_emitter_preservation_proved "
    "general_serialized_AST_lowering_preservation_proved json_bytes_parser_verified "
    "json_bytes_parser_preservation_proved model_convergence_proved convergence_proved "
    "backend_executed lean_compilation_verified proof_checked kernel_proofs_checked "
    "corpus_native_AST_preservation_proved conditional_proofs_verified alias_assumption_proved "
    "legal_proof_cache_compatible proof_cache_admission_verified semantic_definition_binding_verified "
    "per_occurrence_lookup_verified accepted_view_eligible combined_use_review_verified "
    "native_execution_performed fresh_native_execution_performed proof_validation_performed "
    "olean_kernel_rechecked installed_compiler_revalidated cryptographic_authenticity_verified "
    "elaborated_type_verified executable_kernel_target_prepared formalization_artifact_created "
    "backend_request_prepared typed_native_attempt_observed typed_theorem_result_observed "
    "theorem_receipt_issued compiled_artifact_execution_reused elaborated_term_dependencies_verified "
    "source_prose_correspondence_proved installed_stdlib_artifact_closure_verified "
    "elaborated_type_equality_verified kernel_definitional_equality_verified kernel_probe_aliases_checked"
).split(), False)
AUTHORITY = dict.fromkeys(("source", "legal", "review", "proof", "model", "training", "gold", "corpus_admission"), False)


def _need(value, message):
    if not value:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(value, label):
    _need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
          "independent lowercase SHA256 required: " + label)


def _bound_tree(value, maximum, *, allow_bytes=False):
    remaining, nodes = maximum, 1_000_000

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 96, "native elaboration JSON node/depth bound exceeded")
        if type(item) is dict:
            remaining -= 2 + 2 * len(item)
            for key, child in item.items():
                _need(type(key) is str, "ordinary native elaboration JSON keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            remaining -= 2 + len(item)
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= remaining, "bounded native elaboration UTF8 required")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise ValueError("valid native elaboration UTF8 required") from error
        elif allow_bytes and type(item) is bytes:
            remaining -= len(item)
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded native elaboration integer required")
            remaining -= 20
        elif type(item) is float:
            _need(math.isfinite(item), "finite native elaboration numbers required")
            remaining -= 32
        else:
            raise ValueError("ordinary native elaboration JSON required")
        _need(remaining >= 0, "complete native elaboration JSON byte bound exceeded")

    visit(value, 0)


def _wire(value, maximum=MAX_RECORD_BYTES):
    _bound_tree(value, maximum)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("finite ordinary native elaboration JSON required") from error
    _need(len(raw) <= maximum, "complete native elaboration JSON byte bound exceeded")
    return raw


def _parse(raw, maximum=MAX_RECORD_BYTES):
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded native elaboration JSON bytes required")

    def pairs(items):
        result = {}
        for key, child in items:
            _need(key not in result, "duplicate native elaboration JSON key")
            result[key] = child
        return result

    def constant(_):
        raise ValueError("nonfinite native elaboration JSON refused")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        _wire(value, maximum)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("duplicate-free finite bounded native elaboration JSON required") from error
    _need(type(value) is dict, "native elaboration JSON object required")
    return value


def _owners():
    from . import legal_corpus_definition_use_preservation_elaboration_v2 as preparation
    from . import legal_corpus_definition_use_preservation_theorem_lineage_v2 as lineage
    from . import legal_corpus_definition_use_preservation_packet_v2 as reader
    from . import legal_corpus_definition_use_preservation_index_v2 as index
    from . import legal_corpus_definition_use_preservation_native_v2 as native
    from . import legal_corpus_lake as transport
    from . import legal_corpus_shared_lake as shared
    from . import legal_pilot_lake as installed
    from ..backends import process
    return preparation, lineage, reader, index, native, transport, shared, installed, process


def _producer_pins(manifest, owners):
    global _OPERATION_PINS
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "native elaboration executor changed since import")
    pins = dict(manifest["producer_pins"])
    pins.update({str(Path(owner.__file__).resolve()): _sha(Path(owner.__file__).read_bytes()) for owner in owners})
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    for path, expected in pins.items():
        _pin(expected, "native elaboration producer")
        _need(type(path) is str and Path(path).is_absolute() and str(Path(path).resolve()) == path
              and _sha(Path(path).read_bytes()) == expected, "native elaboration producer changed: " + path)
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(pins)
    _need(pins == _OPERATION_PINS, "native elaboration producer closure changed since first operation")
    return pins


def preparation_sha256(preparation):
    """Address the complete manifest and seventeen source files; no validation."""
    from . import legal_corpus_definition_use_preservation_elaboration_v2 as owner
    return owner.preparation_sha256(preparation)


def validate_definition_use_preservation_elaboration_native_v2(
        preparation, lineage, packet_files, corpus_preparation, assessment_raw, *,
        expected_elaboration_preparation_sha256, expected_lineage_sha256, **packet_arguments):
    """Require the full public lineage, source/review and augmentation replay."""
    _pin(expected_elaboration_preparation_sha256, "complete elaboration preparation")
    _pin(expected_lineage_sha256, "exact source theorem lineage")
    _need(set(packet_arguments) == _PACKET_ARGUMENTS, "complete closed elaboration packet arguments required")
    _bound_tree(packet_arguments, MAX_INPUT_BYTES, allow_bytes=True)
    _need(type(assessment_raw) is bytes and 0 < len(assessment_raw) <= MAX_RECORD_BYTES,
          "bounded original assessment bytes required")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "native elaboration executor changed since import")
    owners = _owners()
    checked = owners[0].validate_definition_use_preservation_elaboration_v2(
        preparation, lineage, packet_files, corpus_preparation, assessment_raw,
        expected_elaboration_preparation_sha256=expected_elaboration_preparation_sha256,
        expected_lineage_sha256=expected_lineage_sha256, **packet_arguments)
    _need(type(checked) is owners[0].ElaborationPreparation and preparation_sha256(checked) == expected_elaboration_preparation_sha256,
          "exact current complete elaboration preparation required")
    _need(len(checked.manifest_json.encode("utf-8")) <= MAX_RECORD_BYTES
          and sum(len(body.encode("utf-8")) for _, body in checked.files) <= MAX_PROJECT_BYTES,
          "complete elaboration preparation must fit retained transport before execution")
    _producer_pins(checked.to_dict(), owners)
    return checked


def _closed_type(expression, level_parameters):
    """Validate the exact bounded Expr/Level/Name serializer's closed grammar.

    This validates a captured representation, not a second Lean elaborator or
    kernel. Native equality and proposition checks remain compiler observations.
    """
    _need(type(level_parameters) is list and len(level_parameters) <= 64,
          "bounded explicit theorem universe parameter list required")

    def natural(value):
        _need(type(value) is int and 0 <= value < (1 << 63), "ordinary bounded natural index required")

    def name(value):
        _need(type(value) is dict and type(value.get("kind")) is str, "closed structured Lean name required")
        kind = value["kind"]
        if kind == "anonymous":
            _need(set(value) == {"kind"}, "closed anonymous Lean name required")
        elif kind in {"str", "num"}:
            _need(set(value) == {"kind", "parent", "value"}, "closed Lean name component required")
            name(value["parent"])
            if kind == "str":
                _need(type(value["value"]) is str and value["value"] and "\x00" not in value["value"],
                      "ordinary nonempty Lean name string required")
            else:
                natural(value["value"])
        else:
            raise ValueError("unknown structured Lean name kind")

    for parameter in level_parameters:
        name(parameter)
        _need(parameter["kind"] != "anonymous", "named theorem universe parameters required")
    allowed = {_wire(parameter) for parameter in level_parameters}
    _need(len(allowed) == len(level_parameters), "unique theorem universe parameter names required")

    def level(value):
        _need(type(value) is dict and type(value.get("kind")) is str, "closed structured Lean level required")
        kind = value["kind"]
        if kind == "zero":
            _need(set(value) == {"kind"}, "closed zero universe level required")
        elif kind == "succ":
            _need(set(value) == {"kind", "of"}, "closed successor universe level required")
            level(value["of"])
        elif kind in {"max", "imax"}:
            _need(set(value) == {"kind", "left", "right"}, "closed binary universe level required")
            level(value["left"])
            level(value["right"])
        elif kind == "param":
            _need(set(value) == {"kind", "name"}, "closed named universe level required")
            name(value["name"])
            _need(_wire(value["name"]) in allowed, "unbound theorem universe parameter refused")
        else:
            raise ValueError("unresolved or unknown structured Lean universe level")

    def expr(value, binders):
        _need(type(value) is dict and type(value.get("kind")) is str, "closed structured Lean expression required")
        kind = value["kind"]
        if kind == "bvar":
            _need(set(value) == {"kind", "index"}, "closed bound-variable expression required")
            natural(value["index"])
            _need(value["index"] < binders, "loose Lean bound variable refused")
        elif kind == "sort":
            _need(set(value) == {"kind", "level"}, "closed sort expression required")
            level(value["level"])
        elif kind == "const":
            _need(set(value) == {"kind", "name", "levels"}, "closed constant expression required")
            name(value["name"])
            _need(value["name"]["kind"] != "anonymous" and type(value["levels"]) is list and len(value["levels"]) <= 64,
                  "named Lean constant with bounded universe instantiation required")
            for item in value["levels"]:
                level(item)
        elif kind == "app":
            _need(set(value) == {"kind", "fn", "arg"}, "closed application expression required")
            expr(value["fn"], binders)
            expr(value["arg"], binders)
        elif kind in {"lam", "forallE"}:
            _need(set(value) == {"kind", "binder_name", "binder_info", "binder_type", "body"}, "closed Lean binder expression required")
            name(value["binder_name"])
            _need(value["binder_info"] in {"default", "implicit", "strictImplicit", "instImplicit"}, "closed Lean binder-info kind required")
            expr(value["binder_type"], binders)
            expr(value["body"], binders + 1)
        elif kind == "letE":
            _need(set(value) == {"kind", "name", "type", "value", "body", "nondep"} and type(value["nondep"]) is bool,
                  "closed Lean let expression required")
            name(value["name"])
            expr(value["type"], binders)
            expr(value["value"], binders)
            expr(value["body"], binders + 1)
        elif kind in {"natVal", "strVal"}:
            _need(set(value) == {"kind", "value"}, "closed Lean literal expression required")
            if kind == "natVal":
                natural(value["value"])
            else:
                _need(type(value["value"]) is str, "ordinary Lean string literal required")
        elif kind == "proj":
            _need(set(value) == {"kind", "name", "index", "value"}, "closed Lean projection expression required")
            name(value["name"])
            natural(value["index"])
            expr(value["value"], binders)
        else:
            raise ValueError("unresolved, metadata-bearing or unknown structured Lean expression")

    expr(expression, 0)


def _type_observations(stdout, stderr, manifest):
    expected = {row["original_theorem_name"]: row["probe_theorem_name"] for row in manifest["probe_bindings"]}
    _need(len(expected) == MAX_TYPE_CHECKS and list(expected) == manifest["original_theorems"]
          and list(expected.values()) == manifest["probe_theorems"], "exact fifteen ordered theorem type bindings required")
    observed, errors = {}, []
    prefix = re.compile(r"(?:info: (?:\./)*LegalCorpusV2Elaboration\.lean:[1-9][0-9]*:[0-9]+: )?CORPUS_TYPE_CHECK:(.*)\Z")
    for number, line in enumerate(stdout.splitlines(), 1):
        if "CORPUS_TYPE_CHECK" not in line:
            continue
        try:
            match = prefix.fullmatch(line)
            _need(match is not None, "unknown machine observation prefix")
            raw = match.group(1).encode("utf-8")
            value = _parse(raw)
            _need(set(value) == _TYPE_FIELDS and value["schema"] == TYPE_CHECK_SCHEMA,
                  "closed exact theorem type observation required")
            name = value["original_name"]
            _need(type(name) is str and name in expected and name not in observed
                  and value["alias_name"] == expected[name], "unique exact theorem type binding required")
            _need(all(value[field] is True for field in _TRUE_TYPE_FLAGS), "all exact kernel type checks must pass")
            _need(type(value["original_type"]) is dict and type(value["alias_type"]) is dict
                  and _wire(value["original_type"]) == _wire(value["alias_type"])
                  and type(value["original_level_params"]) is list and type(value["alias_level_params"]) is list
                  and _wire(value["original_level_params"]) == _wire(value["alias_level_params"]),
                  "exact complete elaborated type and universe parameter equality required")
            _closed_type(value["original_type"], value["original_level_params"])
            _closed_type(value["alias_type"], value["alias_level_params"])
            observed[name] = value
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
            errors.append("invalid theorem type observation at stdout line " + str(number) + ": " + str(error)[:1024])
    for number, line in enumerate(stderr.splitlines(), 1):
        if "CORPUS_TYPE_CHECK" in line:
            errors.append("stderr cannot establish a theorem type observation at line " + str(number))
    for name in expected:
        if name not in observed:
            errors.append("missing exact theorem type observation: " + name)
    try:
        _wire(observed, MAX_RECORD_BYTES)
    except ValueError:
        # Complete capture remains in the retained stdout file. An oversized
        # typed group cannot become a partial successful receipt observation.
        observed = {}
        errors.append("complete captured theorem type group exceeds receipt byte bound")
    return observed, errors[:64], not errors and set(observed) == set(expected)


def _type_capture_payload(types):
    """Retain full closed type captures outside the shallower sealed receipt.

    Every compact row addresses the complete canonical record, type and universe
    bytes. The payload uses this owner's existing one-MiB/depth-96 contract;
    existing corpus-record depth limits remain unchanged.
    """
    _need(type(types) is dict and len(types) <= MAX_TYPE_CHECKS,
          "bounded complete theorem type capture mapping required")
    raw = _wire(types, MAX_RECORD_BYTES)
    captured = _parse(raw, MAX_RECORD_BYTES)
    compact = {}
    for name, value in captured.items():
        _need(type(name) is str and type(value) is dict and set(value) == _TYPE_FIELDS
              and value["schema"] == TYPE_CHECK_SCHEMA and value["original_name"] == name
              and type(value["alias_name"]) is str and all(value[field] is True for field in _TRUE_TYPE_FLAGS),
              "closed successful theorem type capture record required")
        _need(_wire(value["original_type"]) == _wire(value["alias_type"])
              and _wire(value["original_level_params"]) == _wire(value["alias_level_params"]),
              "complete captured type and universe identities must agree")
        _closed_type(value["original_type"], value["original_level_params"])
        _closed_type(value["alias_type"], value["alias_level_params"])
        record_raw = _wire(value)
        row = {"schema": "legal-corpus-v2-native-theorem-type-check-reference/v1",
               "original_name": name, "alias_name": value["alias_name"],
               "record_sha256": _sha(record_raw), "record_bytes": len(record_raw),
               **{field: value[field] for field in sorted(_TRUE_TYPE_FLAGS)}}
        for field in ("original_type", "alias_type", "original_level_params", "alias_level_params"):
            field_raw = _wire(value[field])
            row[field + "_sha256"] = _sha(field_raw)
            row[field + "_bytes"] = len(field_raw)
        compact[name] = row
    _wire(compact, MAX_RECORD_BYTES)
    return raw, compact


def _axiom_observations(stdout, stderr, manifest):
    expected = manifest["theorems"]
    _need(type(expected) is list and len(expected) == MAX_THEOREMS
          and expected == manifest["original_theorems"] + manifest["probe_theorems"]
          and len(set(expected)) == MAX_THEOREMS
          and all(type(name) is str and len(name) <= 256
                  and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", name) for name in expected),
          "exact thirty original and probe theorem names required")
    dependencies, errors = {}, []
    marker = re.compile(r"\b(?:axiom|axioms|sorry|sorryAx)\b")
    for number, line in enumerate(stdout.splitlines(), 1):
        if not marker.search(line):
            continue
        accepted = False
        for name in expected:
            module = name.rsplit(".", 1)[0]
            path = (module.replace(".", "/") + ".lean") if name in manifest["original_theorems"] else "LegalCorpusV2Elaboration.lean"
            prefix = r"(?:info: (?:\./)*" + re.escape(path) + r":[1-9][0-9]*:[0-9]+: )?"
            if re.fullmatch(prefix + re.escape("'" + name + "' does not depend on any axioms"), line):
                if name in dependencies:
                    errors.append("duplicate empty-axiom observation: " + name)
                else:
                    dependencies[name] = []
                accepted = True
                break
        if not accepted:
            errors.append("unrecognized or nonempty stdout axiom observation at line " + str(number))
    for number, line in enumerate(stderr.splitlines(), 1):
        if marker.search(line):
            errors.append("stderr cannot establish an axiom observation at line " + str(number))
    for name in expected:
        if name not in dependencies:
            errors.append("missing empty-axiom observation: " + name)
    return dependencies, errors[:64], not errors and set(dependencies) == set(expected)


def _persist_build(checked, output, owners, artifacts, executed_sources, logs, receipt, *, type_capture_raw=None):
    transport, shared = owners[5], owners[6]
    _need(sum(len(body.encode("utf-8")) for _, body in checked.files) <= MAX_PROJECT_BYTES
          and len(checked.manifest_json.encode("utf-8")) <= MAX_RECORD_BYTES,
          "frozen elaboration project must fit existing transport bounds")
    for contents in (artifacts, executed_sources):
        _need(all(type(body) is bytes and len(body) <= MAX_PROJECT_BYTES for body in contents.values())
              and sum(map(len, contents.values())) <= MAX_PROJECT_BYTES,
              "bounded complete retained elaboration artifact group required")
    receipt_raw = _wire(receipt)
    if type_capture_raw is not None:
        _need(type(type_capture_raw) is bytes and _wire(_parse(type_capture_raw)) == type_capture_raw,
              "complete canonical bounded standalone type capture required")
    shared._write_frozen_project(checked, output / "project")
    compiled = {name.removeprefix(".lake/build/lib/lean/"): body for name, body in artifacts.items()}
    for directory, contents, maximum in (("compiled", compiled, MAX_MODULES), ("executed-inputs", executed_sources, MAX_FILES)):
        shared._write_compiled(output / directory, contents)
        _need(transport._read_files(output / directory, set(contents), maximum_files=maximum) == contents,
              "retained elaboration artifacts failed exact readback")
    root_fd = os.open(output, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    try:
        transport._check_directories(output, root_fd)
        for name, raw in logs.items():
            transport._write_new_file(root_fd, name, raw)
        if type_capture_raw is not None:
            transport._write_new_file(root_fd, "type-checks.json", type_capture_raw)
        transport._write_new_file(root_fd, "build-receipt.json", receipt_raw)
        os.fsync(root_fd)
        transport._check_directories(output, root_fd)
    finally:
        os.close(root_fd)
    _need((output / "build-receipt.json").read_bytes() == receipt_raw,
          "retained elaboration receipt failed exact readback")
    for name, raw in logs.items():
        _need((output / name).read_bytes() == raw, "retained elaboration log failed exact readback")
    if type_capture_raw is not None:
        _need((output / "type-checks.json").read_bytes() == type_capture_raw,
              "retained standalone type capture failed exact readback")


def build_definition_use_preservation_elaboration_native_v2(
        preparation, lineage, packet_files, corpus_preparation, assessment_raw, *,
        expected_elaboration_preparation_sha256, expected_lineage_sha256,
        lake_executable, output_directory, timeout_seconds=60, cancellation=None, **packet_arguments):
    """Clean-build seventeen sources and observe fifteen exact native type checks.

    The installed standard library and dynamic compiler libraries remain an
    explicit external trust premise. Only the supplied sibling ELF pair is
    hashed and version-probed. Unresolved native cleanup retains its owner.
    """
    _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
          and 0 < timeout_seconds <= 60, "finite elaboration compiler timeout in (0,60] required")
    validated = validate_definition_use_preservation_elaboration_native_v2(
        preparation, lineage, packet_files, corpus_preparation, assessment_raw,
        expected_elaboration_preparation_sha256=expected_elaboration_preparation_sha256,
        expected_lineage_sha256=expected_lineage_sha256, **packet_arguments)
    owners = _owners()
    preparer, lineage_owner, reader, index, native, transport, shared, installed, process = owners
    checked = preparer.ElaborationPreparation(validated.manifest_json, tuple(validated.files))
    manifest = checked.to_dict()
    producers = _producer_pins(manifest, owners)
    corpus_snapshot = (corpus_preparation.manifest_json, tuple(corpus_preparation.files))
    lineage_pin = lineage_owner.lineage_sha256(lineage)
    packet_pin = reader.packet_sha256(packet_files)
    arguments_pin = index._tree_digest(packet_arguments)
    original_state = manifest["original_preparation_state"]
    output = transport._path(output_directory)
    transport._check_directories(output.parent, allow_missing=True)
    _need(not output.exists() and not output.is_symlink(), "fresh native elaboration output directory required")
    executable, binaries, probes = native._installed_toolchain(lake_executable, packet_arguments["toolchain"])
    _need(binaries == manifest["expected_binary_sha256"] == packet_arguments["expected_binary_sha256"]
          and native._binary_recheck(binaries), "installed compiler binary pair differs from independently pinned original packet")
    command = (str(executable), "--offline", "--no-cache", "build", "legal")
    modules = manifest["expected_modules"]
    _need(type(modules) is list and len(modules) == MAX_MODULES and len(set(modules)) == MAX_MODULES,
          "exact thirteen clean native elaboration modules required")
    artifact_paths = tuple(".lake/build/lib/lean/" + module.replace(".", "/") + ".olean" for module in modules)
    source_files = {name: body.encode("utf-8") for name, body in checked.files}
    _need(len(source_files) == MAX_FILES and all(not name.endswith(".olean") for name in source_files),
          "exact seventeen source-only native inputs required")
    output_paths = artifact_paths + tuple(source_files)
    request = process.ToolRunRequest(argv=command, input_files=dict(checked.files), output_paths=output_paths,
        owned_process_observation=True,
        environment={"ELAN_TOOLCHAIN": packet_arguments["toolchain"], "LEAN_NUM_THREADS": "1"},
        limits=process.ToolRunLimits(timeout_seconds=timeout_seconds, cpu_seconds=timeout_seconds,
            resident_memory_bytes=2 * 1024**3, max_output_bytes=MAX_CAPTURE_BYTES,
            max_input_bytes=MAX_PROJECT_BYTES, max_workspace_bytes=128 * MAX_RECORD_BYTES,
            max_output_files=MAX_FILES + MAX_MODULES))
    try:
        run = process.BoundedToolRunner().run(request, cancellation=cancellation)
    except process.OwnedToolCleanupError as error:
        try:
            refusal = transport.contracts.seal_record({
                "schema": BUILD_SCHEMA, "profile": PROFILE,
                "preparation_cid": manifest["record_cid"], "preparation_full_canonical_sha256": expected_elaboration_preparation_sha256,
                "lineage_sha256": expected_lineage_sha256, "toolchain": packet_arguments["toolchain"],
                "original_preparation_state": original_state,
                "native_observations": {"expected_command": list(command), "execution_status": "no_complete_native_result_returned",
                    "cleanup_owner_retained_on_exception": True, "cleanup_confirmed": False, "error": str(error)[:2048],
                    "artifact_sha256": {}, "artifact_files": {}, "type_checks": {}, "theorem_axiom_dependencies": {}},
                "build_passed": False, "status": "owned_native_cleanup_unresolved",
                "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0, **FALSE_FLAGS})
            _persist_build(checked, output, owners, {}, {}, {}, refusal)
            error.add_note("Unqualified frozen theorem elaboration project retained at " + str(output))
        except (ValueError, TypeError, OSError) as preservation_error:
            error.add_note("Theorem elaboration cleanup refusal preservation also failed: " + type(preservation_error).__name__)
        raise
    _need(type(run) is process.ToolRunResult, "genuine existing bounded tool result required")
    post_error, binary_error = None, None
    try:
        validate_definition_use_preservation_elaboration_native_v2(
            preparation, lineage, packet_files, corpus_preparation, assessment_raw,
            expected_elaboration_preparation_sha256=expected_elaboration_preparation_sha256,
            expected_lineage_sha256=expected_lineage_sha256, **packet_arguments)
        _need(preparation == checked and (corpus_preparation.manifest_json, tuple(corpus_preparation.files)) == corpus_snapshot
              and lineage_owner.lineage_sha256(lineage) == lineage_pin == expected_lineage_sha256
              and reader.packet_sha256(packet_files) == packet_pin
              and index._tree_digest(packet_arguments) == arguments_pin
              and _producer_pins(manifest, owners) == producers,
              "complete source/review/lineage/elaboration inputs or producers changed during compilation")
    except (ValueError, TypeError, KeyError, IndexError, OSError, UnicodeError, RecursionError) as error:
        post_error = {"type": type(error).__name__, "message": str(error)[:2048]}
    try:
        unchanged = native._binary_recheck(binaries)
    except (ValueError, TypeError, OSError) as error:
        unchanged = False
        binary_error = {"type": type(error).__name__, "message": str(error)[:2048]}
    artifacts = {name: run.output_files[name] for name in artifact_paths if name in run.output_files}
    coverage = (set(run.output_files) == set(output_paths) and set(artifacts) == set(artifact_paths)
                and all(type(raw) is bytes and raw for raw in artifacts.values()))
    source_readback = all(run.output_files.get(name) == raw for name, raw in source_files.items())
    native_runtime = bool(run.runtime is process.ToolRuntime.NATIVE and type(run.pid) is int and run.pid > 0 and not run.unavailable)
    lifecycle = run.native_lifecycle
    process_scope = native._observed_process_scope(lifecycle, run.pid, process)
    cleanup_confirmed = bool(type(lifecycle) is process.NativeToolLifecycleObservation
        and type(lifecycle.leader) is process.NativeProcessIdentity and lifecycle.leader.pid == run.pid and lifecycle.cleanup_confirmed)
    type_capture_raw, compact_types = _wire({}), {}
    try:
        types, type_errors, types_passed = _type_observations(run.stdout, run.stderr, manifest)
        type_capture_raw, compact_types = _type_capture_payload(types)
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError, RecursionError) as error:
        types, type_errors, types_passed = {}, ["type capture refused: " + str(error)[:1024]], False
    try:
        axioms, axiom_errors, axioms_passed = _axiom_observations(run.stdout, run.stderr, manifest)
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError, RecursionError) as error:
        axioms, axiom_errors, axioms_passed = {}, ["axiom capture refused: " + str(error)[:1024]], False
    passed = bool(run.ok and type(run.returncode) is int and run.returncode == 0
        and type(run.elapsed_seconds) in (int, float) and math.isfinite(run.elapsed_seconds) and run.elapsed_seconds >= 0
        and native_runtime and tuple(run.command) == command and coverage and source_readback
        and unchanged and post_error is None and not run.output_truncated and not run.workspace_limit_exceeded
        and not run.resource_exhausted and run.workspace_cleaned and cleanup_confirmed and process_scope
        and not run.error and types_passed and axioms_passed)
    logs = {"stdout.txt": run.stdout.encode("utf-8"), "stderr.txt": run.stderr.encode("utf-8"), "runner-error.txt": run.error.encode("utf-8")}
    _need(all(len(raw) <= 3 * MAX_CAPTURE_BYTES for raw in logs.values()), "bounded full native elaboration logs required")
    previews = {name: raw[:MAX_LOG_PREVIEW_BYTES].decode("utf-8", errors="replace").replace("\x00", "\\u0000") for name, raw in logs.items()}
    observations = {
        "command": list(run.command), "expected_command": list(command), "runtime": run.runtime.value, "pid": run.pid, "returncode": run.returncode,
        "expected_modules": modules, "compiled_modules": [module for module, path in zip(modules, artifact_paths, strict=True) if path in artifacts and artifacts[path]],
        "manifest_coverage_passed": bool(coverage), "executed_project_readback_passed": bool(source_readback),
        "executed_project_sha256": {name: _sha(run.output_files[name]) for name in source_files if name in run.output_files},
        "producer_pins": producers, "binary_sha256": binaries, "binaries_unchanged": unchanged, "version_probes": probes,
        "toolchain_probed": True, "installed_pair_binary_verified": unchanged, "installed_stdlib_artifact_closure_verified": False,
        "post_run_validation_passed": post_error is None, "post_run_validation_error": post_error, "binary_recheck_error": binary_error,
        "original_preparation_unchanged": post_error is None,
        "artifact_sha256": {name: _sha(raw) for name, raw in artifacts.items()}, "artifact_bytes": {name: len(raw) for name, raw in artifacts.items()},
        "artifact_files": {name: "compiled/" + name.removeprefix(".lake/build/lib/lean/") for name in artifacts},
        "theorems": manifest["theorems"], "original_theorems": manifest["original_theorems"], "probe_theorems": manifest["probe_theorems"],
        "theorem_axiom_dependencies": axioms, "axiom_observations_passed": axioms_passed, "axiom_observation_errors": axiom_errors,
        "type_checks": compact_types, "type_checks_passed": types_passed, "type_check_errors": type_errors,
        "type_checks_sha256": _sha(type_capture_raw), "type_checks_bytes": len(type_capture_raw),
        "type_checks_file": {"path": "type-checks.json", "sha256": _sha(type_capture_raw), "bytes": len(type_capture_raw)},
        "type_check_scope": "actual original and namespace-preserving alias theorem types; no inferred legal interpretation",
        "stdout": previews["stdout.txt"], "stderr": previews["stderr.txt"], "error": previews["runner-error.txt"],
        "log_sha256": {name: _sha(raw) for name, raw in logs.items()}, "log_bytes": {name: len(raw) for name, raw in logs.items()},
        "receipt_text_truncated": any(len(raw) > MAX_LOG_PREVIEW_BYTES for raw in logs.values()),
        "elapsed_seconds": run.elapsed_seconds, "termination_reason": run.termination_reason,
        "timed_out": run.timed_out, "cancelled": run.cancelled, "unavailable": run.unavailable, "output_truncated": run.output_truncated,
        "workspace_limit_exceeded": run.workspace_limit_exceeded, "resource_exhausted": run.resource_exhausted, "workspace_cleaned": run.workspace_cleaned,
        "process_tree_terminated": run.process_tree_terminated,
        "native_lifecycle": lifecycle.to_dict() if type(lifecycle) is process.NativeToolLifecycleObservation else None,
        "cleanup_confirmed": cleanup_confirmed, "observed_process_scope_passed": process_scope,
        "ownership_is_sampled": True, "kernel_containment_attested": False, "native_runtime_verified": native_runtime,
    }
    observed_flags = {"backend_executed": native_runtime, "native_execution_performed": native_runtime,
        "fresh_native_execution_performed": native_runtime, "installed_compiler_revalidated": unchanged,
        "lean_compilation_verified": passed, "proof_checked": passed, "kernel_proofs_checked": passed,
        "elaborated_type_verified": passed, "elaborated_type_equality_verified": passed,
        "kernel_definitional_equality_verified": passed, "kernel_probe_aliases_checked": passed}
    receipt = transport.contracts.seal_record({
        "schema": BUILD_SCHEMA, "profile": PROFILE, "preparation_cid": manifest["record_cid"],
        "preparation_full_canonical_sha256": expected_elaboration_preparation_sha256,
        "preparation_manifest_sha256": _sha(checked.manifest_json.encode("utf-8")), "lineage_sha256": expected_lineage_sha256,
        "packet_observation_sha256": packet_arguments["expected_packet_observation_sha256"],
        "packet_bundle_sha256": packet_arguments["expected_bundle_sha256"], "receipt_file_sha256": packet_arguments["expected_receipt_file_sha256"],
        "corpus_preparation_full_canonical_sha256": packet_arguments["expected_corpus_preparation_sha256"],
        "assessment_file_sha256": packet_arguments["expected_assessment_file_sha256"], "toolchain": packet_arguments["toolchain"],
        "original_preparation_state": original_state, "native_observations": observations, "build_passed": passed,
        "status": "corpus_theorem_type_elaboration_checks_passed" if passed else "corpus_theorem_type_elaboration_checks_failed",
        "proof_scope": "Fifteen actual original theorem types exactly match namespace-preserving generated alias types, with kernel checks and empty axiom inventories for thirty original/alias declarations. The original donor, consumer and alias hypotheses remain parameters; no fact or legal/source correspondence is established.",
        "trust_boundary": [
            "The installed standard library and dynamically loaded compiler libraries are external trust premises; only the installed sibling lake/lean ELF pair is pinned and version-probed.",
            "This clean build consumes seventeen regenerated source inputs and no retained compiled artifact.",
            "Native observations do not construct a FormalizationArtifact, BackendRequest, BackendAttempt, ProofResult or typed ProofReceipt and do not authorize legal/cache admission."],
        "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0, **(FALSE_FLAGS | observed_flags)})
    executed_sources = {name: run.output_files[name] for name in source_files if name in run.output_files}
    _persist_build(checked, output, owners, artifacts, executed_sources, logs, receipt, type_capture_raw=type_capture_raw)
    return receipt


__all__ = ["preparation_sha256", "validate_definition_use_preservation_elaboration_native_v2",
           "build_definition_use_preservation_elaboration_native_v2"]


def read_planned_physical_whole_norm_type_capture_v2(
        preparation, stdout_raw, stderr_raw, *, expected_preparation_sha256,
        expected_stdout_sha256, expected_stderr_sha256):
    """Read one pinned physical type observation without running a compiler.

    The two complete closed types can differ in raw expression identity.
    The retained observation must report kernel definitional equality, both
    constant checks, and both types' proposition status.
    """
    from . import legal_corpus_definition_use_preservation_elaboration_v2 as preparer

    _pin(expected_preparation_sha256, "physical elaboration preparation")
    _pin(expected_stdout_sha256, "physical elaboration stdout")
    _pin(expected_stderr_sha256, "physical elaboration stderr")
    envelope = preparer._envelope(preparation)
    _need(_sha(preparer._wire(envelope)) == expected_preparation_sha256,
          "exact pinned physical elaboration preparation required")
    manifest = _parse(envelope["manifest_json"].encode("utf-8"))
    _need(manifest.get("schema") == preparer.PHYSICAL_PROBE_SCHEMA
          and manifest.get("profile") == preparer.PHYSICAL_PROBE_PROFILE,
          "exact physical whole-norm elaboration preparation schema and profile required")
    for raw, expected in ((stdout_raw, expected_stdout_sha256), (stderr_raw, expected_stderr_sha256)):
        _need(type(raw) is bytes and len(raw) <= MAX_CAPTURE_BYTES and _sha(raw) == expected,
              "exact pinned bounded physical elaboration log bytes required")
    try:
        stdout = stdout_raw.decode("utf-8")
        stderr = stderr_raw.decode("utf-8")
    except UnicodeError as error:
        raise ValueError("physical elaboration logs require exact UTF-8") from error

    original = manifest["original_theorem"]
    alias = manifest["alias_theorem"]
    probe = manifest["probe_module"]
    identifier = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*")
    _need(all(type(name) is str and len(name) <= 256 and identifier.fullmatch(name)
              for name in (original, alias, probe))
          and original != alias and "." in original
          and original.rsplit(".", 1)[0] == alias.rsplit(".", 1)[0]
          and manifest["source_path"] == original.rsplit(".", 1)[0].replace(".", "/") + ".lean",
          "exact physical original and namespace-preserving probe identities required")
    type_line = manifest["type_report_line"]
    alias_line = manifest["alias_axiom_report_line"]
    _need(type(type_line) is int and type(alias_line) is int and 0 < alias_line < type_line,
          "exact positive physical type and alias report locations required")

    name = probe.replace(".", "/") + ".lean"
    files = dict(preparation.files)
    source = files.get(name)
    _need(type(source) is str and _sha(source.encode("utf-8")) == manifest["probe_source_sha256"],
          "exact physical type probe source required")
    lines = source.splitlines()
    _need(type_line <= len(lines)
          and lines[alias_line - 1] == "#print axioms " + alias.rsplit(".", 1)[1]
          and lines[type_line - 1] == "run_elab CorpusPreservationElaboration.check `" + original + " `" + alias,
          "physical observation lines differ from the pinned probe source")
    original_source = files.get(manifest["source_path"])
    _need(type(original_source) is str, "exact physical original theorem source required")
    original_command = "#print axioms " + original.rsplit(".", 1)[1]
    original_lines = [number for number, line in enumerate(original_source.split("\n"), 1)
                      if line == original_command]
    _need(len(original_lines) == 1, "exact unique original theorem axiom command required")
    original_axiom_line, = original_lines
    probe_path = re.escape(name)
    source_path = re.escape(manifest["source_path"])
    info = r"info: (?:\./)*"
    type_report = re.compile(info + probe_path + rf":{type_line}:0: CORPUS_TYPE_CHECK:(.+)")
    axiom_reports = {
        original: re.compile(info + source_path + rf":{original_axiom_line}:0: "
                             + re.escape(f"'{original}' does not depend on any axioms")),
        alias: re.compile(info + probe_path + rf":{alias_line}:0: "
                          + re.escape(f"'{alias}' does not depend on any axioms")),
    }
    axioms_word = re.compile(r"\b(?:axiom|axioms|sorry|sorryAx)\b")
    selected_names = re.compile(r"(?<![A-Za-z0-9_.])(?:"
                               + re.escape(original) + "|" + re.escape(alias)
                               + r")(?![A-Za-z0-9_.])")
    probe_location = re.compile(info + probe_path + r":[1-9][0-9]*:[0-9]+: ")
    value = None
    empty_axioms = set()
    for line in stdout.splitlines():
        if "CORPUS_TYPE_CHECK" in line:
            match = type_report.fullmatch(line)
            _need(value is None and match is not None,
                  "exactly one anchored physical theorem type observation required")
            value = _parse(match.group(1).encode("utf-8"))
        elif axioms_word.search(line) and (selected_names.search(line) or probe_location.match(line)):
            matched = [name for name, pattern in axiom_reports.items() if pattern.fullmatch(line)]
            _need(len(matched) == 1 and matched[0] not in empty_axioms,
                  "exact unique empty original and alias axiom observations required")
            empty_axioms.add(matched[0])
    _need(not any("CORPUS_TYPE_CHECK" in line
                  or axioms_word.search(line) and (selected_names.search(line) or probe_location.match(line))
                  for line in stderr.splitlines()),
          "stderr cannot establish physical theorem type or axiom observations")
    _need(value is not None and empty_axioms == set(axiom_reports),
          "missing exact physical theorem type or empty axiom observation")
    _need(set(value) == _TYPE_FIELDS
          and value["schema"] == preparer.PHYSICAL_TYPE_OBSERVATION_SCHEMA
          and value["original_name"] == original and value["alias_name"] == alias
          and type(value["expr_equal"]) is bool
          and all(value[field] is True for field in _TRUE_TYPE_FLAGS - {"expr_equal"}),
          "exact physical theorem identities and successful closed kernel checks required")
    _need(type(value["original_type"]) is dict and type(value["alias_type"]) is dict
          and type(value["original_level_params"]) is list and type(value["alias_level_params"]) is list
          and _wire(value["original_level_params"]) == _wire(value["alias_level_params"]),
          "complete closed physical types and exact equal universe parameters required")
    _need(value["expr_equal"] is (_wire(value["original_type"]) == _wire(value["alias_type"])),
          "observed exact expression equality contradicts the retained types")
    _closed_type(value["original_type"], value["original_level_params"])
    _closed_type(value["alias_type"], value["alias_level_params"])
    return _wire({original: value})


__all__ += ["read_planned_physical_whole_norm_type_capture_v2"]


_CHECKED_CAPTURE_BINDINGS = (
    "physical_request_sha256", "graph_sha256", "admission_sha256", "preservation_sha256",
    "realization_sha256", "unit", "source_definition", "proposition_utf8_sha256",
)
_CHECKED_CAPTURE_REVIEW_FIELDS = (
    "request_sha256", "graph_sha256", "admission_sha256", "registry_sha256", "policy_sha256",
    "reviews_sha256", "at_time_utc", "caller_observation_sha256", "current_assessment_sha256",
    "dependency_invalidation_sha256", "evaluation_clock_authenticated", "registry_freshness_authenticated",
)
_CHECKED_CAPTURE_EVIDENCE_FIELDS = (
    "reviewed_version", "instance_identity_profile", "definition_application_profile", "artifact_cid",
    "profile", "request_sha256", "component_cids", "graph_sha256", "admission_sha256",
    "preservation_sha256", "reviewed_crosswalk_sha256", "ordered_unit_ids", "fixture_only",
    "permitted_uses", "formal_assumptions", "preservation_obligations", "retained_native",
    "current_review_observation", "checked_native_observation",
)
_CHECKED_CAPTURE_UNIT_FIELDS = {
    "unit_id", "complete_ir_sha256", "interpretation_record_cid", "scope_record_cid",
    "source_occurrence_cid", "source_use_binding_sha256", "source_version_cid",
}


def _checked_release_type_capture_context(report):
    from . import corpus_contracts as contracts, corpus_qualification as qualification
    from . import legal_graph_review as review_owner

    _need(report.get("schema") == "legal-uscode-release-closure-report/v4"
          and type(report.get("reviewed_version")) is int and report["reviewed_version"] == 4
          and report.get("profile") == "reviewed-source-use-whole-norm-physical-source-replay/v1"
          and report.get("instance_identity_profile") == "reviewed-source-use/v1"
          and report.get("definition_application_profile") == "whole-norm-definition-expansion/v1"
          and all(report.get(field) is True for field in (
              "local_replay_complete", "local_source_cache_entity_bindings_verified",
              "independent_reviewed_crosswalk_verified")),
          "complete local reviewed physical V4 closure required")
    masks = ("admission_mask", "release_mask", "training_mask", "gold_mask", "evaluation_gold_mask")
    _need(all(type(report.get(mask)) is int and report[mask] == 0 for mask in masks)
          and all(report.get(field) is False for field in (
              "admitted", "release_ready", "release_eligible", "formalized", "proof_verified",
              "source_semantics_verified", "model_or_compiler_execution_performed")),
          "retained physical V4 report cannot widen authority or masks")
    review = contracts.validate_record(report.get("current_review_observation"),
        schema="legal-corpus-physical-v4-current-review-observation/v1", fields=_CHECKED_CAPTURE_REVIEW_FIELDS)
    for field in _CHECKED_CAPTURE_REVIEW_FIELDS:
        if field.endswith("_sha256"):
            contracts.require_sha256(review[field], field)
    review_owner._time(review["at_time_utc"])
    checked = contracts.validate_record(report.get("checked_native_observation"),
        schema="legal-corpus-physical-v4-checked-native-observation/v1", fields=(
            *_CHECKED_CAPTURE_BINDINGS, "planned_request_sha256", "current_review_observation_cid",
            "live_result_cid", "declaration", "claim_digest", "obligation_digest", "retained_receipt_sha256",
            "retained_packet_sha256", "native_execution_authenticated", "checked_under_explicit_hypotheses",
            "premise_remains_quantified", "axiom_dependencies", "qualified_request_execution", "proof_receipt_issued",
        ))
    _need(all(review[field] is False for field in (
              "evaluation_clock_authenticated", "registry_freshness_authenticated"))
          and checked["current_review_observation_cid"] == review["record_cid"]
          and all(checked[field] is True for field in (
              "native_execution_authenticated", "checked_under_explicit_hypotheses", "premise_remains_quantified"))
          and all(checked[field] is False for field in ("qualified_request_execution", "proof_receipt_issued"))
          and checked["axiom_dependencies"] == [],
          "matching retained review and conditional Native observation required")
    _need(checked["physical_request_sha256"] == review["request_sha256"] == report.get("request_sha256")
          and all(checked[field] == review[field] == report.get(field)
                  for field in ("graph_sha256", "admission_sha256"))
          and checked["preservation_sha256"] == report.get("preservation_sha256"),
          "checked Native identity differs from the reviewed release")
    for field in ("physical_request_sha256", "graph_sha256", "admission_sha256", "preservation_sha256",
                  "realization_sha256", "proposition_utf8_sha256", "planned_request_sha256", "claim_digest",
                  "obligation_digest", "retained_receipt_sha256", "retained_packet_sha256"):
        contracts.require_sha256(checked[field], field)
    contracts.require_cid(checked["live_result_cid"], "retained live result", codecs=("dag-json",))

    population = report.get("unit_preservation_bindings")
    ids = report.get("unit_ids")
    _need(type(population) is list and all(type(row) is dict and type(row.get("unit_id")) is str
                                           for row in population)
          and ids == [row["unit_id"] for row in population] and len(ids) == len(set(ids)),
          "exact reviewed preservation population required")
    units = {row["unit_id"]: row for row in population}
    for field, kind, fields in (
            ("unit", "norm", _CHECKED_CAPTURE_UNIT_FIELDS | {"relational_request_sha256"}),
            ("source_definition", "definition", _CHECKED_CAPTURE_UNIT_FIELDS)):
        selected = contracts.require_keys(checked[field], fields, field)
        unit_id = contracts.require_text(selected["unit_id"], field + " ID")
        for key in fields - {"unit_id"}:
            if key.endswith("_sha256"):
                contracts.require_sha256(selected[key], key)
            else:
                contracts.require_cid(selected[key], key, codecs=("dag-json",))
        preserved = units.get(unit_id, {})
        _need(preserved.get("kind") == kind
              and all(preserved.get(key) == value for key, value in selected.items()),
              "checked Native unit or source definition differs from the reviewed release")

    evidence = contracts.validate_record(report.get("declared_eligibility_evidence"),
        schema="legal-corpus-physical-v4-qualification-evidence/v1", fields=_CHECKED_CAPTURE_EVIDENCE_FIELDS)
    _need(all(evidence[field] == report.get(field) for field in (
              "reviewed_version", "instance_identity_profile", "definition_application_profile", "profile",
              "request_sha256", "graph_sha256", "admission_sha256", "preservation_sha256",
              "reviewed_crosswalk_sha256", "fixture_only"))
          and type(evidence["fixture_only"]) is bool and evidence["ordered_unit_ids"] == ids
          and evidence["current_review_observation"] == review and evidence["checked_native_observation"] == checked,
          "declared qualification evidence differs from the checked release")
    roles = ("graph", "admission", "preservation", "dependency", "reviewed_crosswalk")
    components = contracts.require_keys(evidence["component_cids"], roles, "release components")
    artifacts = report.get("artifacts")
    _need(type(artifacts) is list and all(type(row) is dict for row in artifacts),
          "exact physical release artifact inventory required")
    for role in roles:
        matches = [row for row in artifacts if row.get("family") == role]
        _need(len(matches) == 1, "exact release component artifact required: " + role)
        transport_sha256 = matches[0].get("sha256")
        contracts.require_cid_sha256(components[role], transport_sha256, role)
        # The preservation identity above hashes its decoded preparation, not its transport bytes.
        if role in ("graph", "admission", "reviewed_crosswalk"):
            _need(transport_sha256 == evidence[role + "_sha256"], "release component digest differs: " + role)
    artifact_cid = evidence["artifact_cid"]
    _need(artifact_cid == components["graph"], "declared qualification must bind the exact reviewed graph")
    declared = qualification.validate_qualification(report.get("declared_qualification"),
        artifact_cid=artifact_cid, profile=evidence["profile"])
    eligibility = qualification.validate_eligibility(report.get("declared_eligibility"), declared,
        artifact_cid=artifact_cid, profile=evidence["profile"])
    dimensions = declared["dimensions"]
    _need(declared["theorem_requested"] is True
          and dimensions["native_translation"]["status"] == "not_run"
          and dimensions["lean_compilation"]["status"] == "not_run"
          and dimensions["proof"]["status"] == "pending"
          and dimensions["processing"]["evidence_cids"] == [evidence["record_cid"]]
          and dimensions["interpretation"]["evidence_cids"] == [components["admission"], review["record_cid"]]
          and eligibility["views"]["reviewed_graph"]["declared_eligible"] is True
          and eligibility["views"]["checked_lean"]["declared_eligible"] is False,
          "conditional type evidence must retain reviewed graph and pending Lean qualification")
    return checked, evidence, declared, eligibility


def read_checked_release_physical_whole_norm_type_capture_v2(
        planned_request, original_files, stdout_raw, stderr_raw, *,
        checked_release_report_raw, expected_checked_release_report_sha256,
        expected_retained_receipt_sha256, expected_retained_packet_sha256,
        expected_preparation_sha256, expected_stdout_sha256, expected_stderr_sha256):
    """Join a retained type capture to an independently pinned checked V4 report.

    Use the independently retained report and the original receipt and logical
    packet inventory pins from the probe selection. Recreate the probe from its checked plan and exact original project, then
    replay the separately pinned logs. The returned provenance describes this
    retained join and carries no new execution, proof, review, or admission.
    """
    from . import corpus_contracts as contracts
    from . import legal_corpus_definition_use_native_v2 as native
    from . import legal_corpus_definition_use_preservation_elaboration_v2 as preparer

    report = contracts.load_record_bytes(
        checked_release_report_raw, expected_sha256=expected_checked_release_report_sha256)
    checked, evidence, declared, eligibility = _checked_release_type_capture_context(report)
    _pin(expected_retained_receipt_sha256, "original retained receipt")
    _pin(expected_retained_packet_sha256, "original retained packet inventory")
    _need(checked["retained_receipt_sha256"] == expected_retained_receipt_sha256
          and checked["retained_packet_sha256"] == expected_retained_packet_sha256,
          "retained receipt or packet inventory differs from the checked release")
    request_pin = checked["planned_request_sha256"]
    plan_wire = native._physical_whole_norm_request_wire(planned_request, request_pin)
    plan = native._parse(plan_wire[1], native.MAX_RECORD_BYTES)
    payload = plan["payload"]
    context = payload.get("context")
    _need(type(context) is dict and all(context.get(field) == checked[field] for field in _CHECKED_CAPTURE_BINDINGS)
          and plan["declaration_id"] == checked["declaration"] == context.get("theorem")
          and all(plan[field] == checked[field] for field in ("claim_digest", "obligation_digest")),
          "planned theorem identity or context differs from the checked release")

    prepared = preparer.prepare_planned_physical_whole_norm_type_probe_v2(
        planned_request, original_files, expected_request_sha256=request_pin)
    type_capture = read_planned_physical_whole_norm_type_capture_v2(prepared, stdout_raw, stderr_raw,
        expected_preparation_sha256=expected_preparation_sha256,
        expected_stdout_sha256=expected_stdout_sha256, expected_stderr_sha256=expected_stderr_sha256)
    provenance = contracts.seal_record({
        "schema": "legal-corpus-physical-v4-checked-release-type-capture-provenance/v1",
        "checked_release_report_sha256": expected_checked_release_report_sha256,
        "checked_native_observation_cid": checked["record_cid"],
        "current_review_observation_cid": checked["current_review_observation_cid"],
        "retained_live_result_cid": checked["live_result_cid"],
        "release_qualification_evidence_cid": evidence["record_cid"],
        "declared_qualification_cid": declared["record_cid"],
        "declared_eligibility_cid": eligibility["record_cid"],
        "reviewed_graph_cid": evidence["artifact_cid"],
        **{field: checked[field] for field in (
            *_CHECKED_CAPTURE_BINDINGS, "declaration", "planned_request_sha256", "claim_digest",
            "obligation_digest", "retained_receipt_sha256", "retained_packet_sha256")},
        "planned_context_sha256": payload["context_sha256"],
        "probe_preparation_sha256": expected_preparation_sha256,
        "probe_stdout_sha256": expected_stdout_sha256,
        "probe_stderr_sha256": expected_stderr_sha256,
        "type_capture_sha256": _sha(type_capture),
        "fixture_only": evidence["fixture_only"],
        "checked_under_explicit_hypotheses": True,
        "premise_remains_quantified": True,
        "axiom_dependencies": [],
        "fresh_native_execution_performed": False,
        "proof_receipt_issued": False,
        "authority": dict(AUTHORITY),
        "training_mask": 0,
        "evaluation_gold_mask": 0,
    })
    return {"type_capture": type_capture, "provenance": provenance}


__all__ += ["read_checked_release_physical_whole_norm_type_capture_v2"]
