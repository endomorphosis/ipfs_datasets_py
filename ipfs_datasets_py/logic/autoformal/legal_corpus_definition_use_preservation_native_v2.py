"""Observe concrete AST preservation and conditional V2 corpus native checks.

Public import uses only the standard library. The new preparation owner keeps
complete original corpus/review/native replay and four exact AST interpretations.
This executor independently replays it before and after one bounded offline Lake
build. Twelve concrete preservation obligations and three original conditional
theorems remain separate observations. No alias fact, universal translator,
source fidelity, legal meaning, model convergence or admission is established.
Callers retain their established owned validation resources throughout cleanup.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re

BUILD_SCHEMA = "legal-corpus-v2-definition-use-preservation-native-build/v1"
PROFILE = "replayed-v2-definition-use-concrete-native-ast-preservation/v1"
MAX_RECORD_BYTES = 1024 * 1024
MAX_ASSESSMENT_BYTES = MAX_RECORD_BYTES
MAX_INPUT_BYTES = 48 * MAX_RECORD_BYTES
MAX_PROJECT_BYTES = 8 * MAX_RECORD_BYTES
MAX_PREPARATION_BYTES = 20 * MAX_RECORD_BYTES
MAX_CAPTURE_BYTES = 4 * MAX_RECORD_BYTES
MAX_LOG_PREVIEW_BYTES = 32768
MAX_RECEIPT_BYTES = MAX_RECORD_BYTES
MAX_FILES = 16
MAX_MODULES = 12
MAX_THEOREMS = 15
MAX_CONDITIONAL_THEOREMS = 3
MAX_PRESERVATION_THEOREMS = 12
_TOOLCHAIN = re.compile(r"leanprover/lean4:v[0-9]+\.[0-9]+\.[0-9]+\Z")
_PREPARATION_MODULE = "ipfs_datasets_py.logic.autoformal.legal_corpus_definition_use_preservation_v2"
_CORPUS_MODULE = "ipfs_datasets_py.logic.autoformal.legal_corpus_definition_use_lake_v2"
_REVIEW_FIELDS = {
    "subject", "registry", "policy", "reviews", "dependency_manifest",
    "component_raw", "expected_component_pin", "use_inputs",
    "expected_subject_sha256", "expected_registry_sha256",
    "expected_policy_sha256", "expected_reviews_sha256",
    "expected_manifest_sha256", "at_time_utc", "observed_artifact_sha256s",
    "observed_pins", "evidence_artifacts",
}
FALSE_FLAGS = dict.fromkeys(
    (
        "source_authenticity_verified", "publisher_authenticity_verified",
        "legal_currentness_verified", "source_semantics_verified",
        "applicability_verified", "context_closure_verified",
        "independently_reviewed", "human_identity_verified",
        "human_independence_verified", "meaning_admitted", "admitted",
        "formalized", "semantic_graph_admitted", "proof_authority",
        "training_qualified", "training_gold_qualified", "evaluation_gold_qualified",
        "Lean_admitted", "model_executed", "learned_translation",
        "source_to_model_equivalence_proved", "source_fidelity_proved",
        "translation_preservation_proved", "cross_family_equivalence_verified",
        "general_emitter_preservation_proved",
        "general_serialized_AST_lowering_preservation_proved",
        "json_bytes_parser_verified", "json_bytes_parser_preservation_proved",
        "model_convergence_proved", "convergence_proved",
        "backend_executed", "lean_compilation_verified", "proof_checked",
        "kernel_proofs_checked", "corpus_native_AST_preservation_proved",
        "conditional_proofs_verified", "alias_assumption_proved",
        "legal_proof_cache_compatible", "proof_cache_admission_verified",
        "semantic_definition_binding_verified", "per_occurrence_lookup_verified",
        "accepted_view_eligible", "combined_use_review_verified",
    ),
    False,
)
AUTHORITY = dict.fromkeys(
    ("source", "legal", "review", "proof", "model", "training", "gold", "corpus_admission"),
    False,
)
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_OPERATION_PINS = None


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(value, label):
    _need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
          "independent lowercase SHA256 required: " + label)


def _bound_tree(value, maximum, *, allow_bytes=False):
    """Bound complete ordinary finite JSON before importing operation owners."""
    remaining, nodes = maximum, 2_000_000

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 64, "native preservation JSON node/depth bound exceeded")
        if type(item) is dict:
            remaining -= 2 + 2 * len(item)
            for key, child in item.items():
                _need(type(key) is str, "ordinary native preservation JSON keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            remaining -= 2 + len(item)
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= remaining,
                  "bounded native preservation UTF8 text required")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise ValueError("valid native preservation UTF8 required") from error
        elif allow_bytes and type(item) is bytes:
            remaining -= len(item)
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded native preservation integer required")
            remaining -= 20
        elif type(item) is float:
            _need(math.isfinite(item), "finite native preservation JSON required")
            remaining -= 32
        else:
            raise ValueError("ordinary native preservation JSON values required")
        _need(remaining >= 0, "complete native preservation JSON byte bound exceeded")

    visit(value, 0)


def _wire(value, maximum):
    _bound_tree(value, maximum)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("finite ordinary native preservation JSON required") from error
    _need(len(raw) <= maximum, "complete native preservation JSON byte bound exceeded")
    return raw


def _parse(raw, maximum):
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded original JSON bytes required")

    def pairs(items):
        result = {}
        for key, child in items:
            _need(key not in result, "duplicate native preservation JSON key")
            result[key] = child
        return result

    def constant(_):
        raise ValueError("finite native preservation JSON required")

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                            parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("duplicate-free finite native preservation JSON required") from error
    _need(type(result) is dict, "native preservation JSON object required")
    _wire(result, maximum)
    return result


def _class_document(preparation, *, expected_module, expected_class, expected_files):
    # Bound original immutable class storage before loading any operation owner.
    cls = type(preparation)
    _need(cls.__module__ == expected_module and cls.__name__ == expected_class,
          "existing typed definition-use preparation required")
    data = object.__getattribute__(preparation, "__dict__")
    _need(type(data) is dict and set(data) == {"manifest_json", "files"},
          "closed original definition-use preparation fields required")
    original_text, original_files = data["manifest_json"], data["files"]
    _need(type(original_text) is str and 0 < len(original_text) <= MAX_RECORD_BYTES,
          "bounded original corpus preservation manifest text required")
    manifest = _parse(original_text.encode("utf-8"), MAX_RECORD_BYTES)
    _need(type(original_files) is tuple and len(original_files) == expected_files,
          "exact complete definition-use project file population required")
    names, files, total = [], [], 0
    for item in original_files:
        _need(type(item) is tuple and len(item) == 2, "exact generated file pairs required")
        name, body = item
        _need(type(name) is str and type(body) is str, "ordinary generated path/text required")
        _need(len(name) <= 256 and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?", name)
              and all(part not in (".", "..") for part in name.split("/")),
              "closed two-level generated paths required")
        _need("\x00" not in body and len(body) <= MAX_PROJECT_BYTES,
              "bounded generated source text required")
        try:
            total += len(body.encode("utf-8"))
        except UnicodeError as error:
            raise ValueError("valid generated UTF8 source required") from error
        _need(total <= MAX_PROJECT_BYTES, "complete generated project byte bound exceeded")
        names.append(name)
        files.append([name, body])
    _need(names == sorted(set(names)), "distinct sorted complete generated file population required")
    return {"manifest": manifest, "files": files}


def _preparation_document(preparation):
    return _class_document(
        preparation, expected_module=_PREPARATION_MODULE,
        expected_class="DefinitionUsePreservationPreparation", expected_files=MAX_FILES)


def _corpus_document(preparation):
    return _class_document(
        preparation, expected_module=_CORPUS_MODULE,
        expected_class="DefinitionUseCorpusPreparation", expected_files=9)


def preparation_sha256(preparation):
    """Commit the FULL canonical original manifest and sixteen generated files.

    This pure commitment helper does not validate a preparation. Execution also
    requires the exact owner class and publicly regenerates the complete project.
    """
    return _sha(_wire(_preparation_document(preparation), MAX_PREPARATION_BYTES))


def _preflight(preparation, corpus_preparation, assessment_raw,
               expected_preparation_sha256, expected_corpus_preparation_sha256,
               expected_assessment_file_sha256, review_inputs, toolchain):
    _pin(expected_preparation_sha256, "complete definition-use preservation preparation")
    _pin(expected_corpus_preparation_sha256, "complete original definition-use preparation")
    _pin(expected_assessment_file_sha256, "original combined review assessment file")
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain),
          "explicit version-pinned Lean toolchain required")
    _need(preparation_sha256(preparation) == expected_preparation_sha256,
          "independent complete preservation preparation pin differs")
    _need(_sha(_wire(_corpus_document(corpus_preparation), MAX_PREPARATION_BYTES))
          == expected_corpus_preparation_sha256,
          "independent complete original corpus preparation pin differs")
    _parse(assessment_raw, MAX_ASSESSMENT_BYTES)
    _need(_sha(assessment_raw) == expected_assessment_file_sha256,
          "original combined review assessment file pin differs")
    _need(type(review_inputs) is dict and set(review_inputs) == _REVIEW_FIELDS,
          "closed complete original combined-review inputs required")
    _bound_tree({"assessment_raw": assessment_raw, "review_inputs": review_inputs},
                MAX_INPUT_BYTES, allow_bytes=True)
    for field in ("expected_subject_sha256", "expected_registry_sha256",
                  "expected_policy_sha256", "expected_reviews_sha256",
                  "expected_manifest_sha256"):
        _pin(review_inputs[field], field)
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "definition-use preservation executor changed since import")


def _owners():
    from . import legal_corpus_definition_use_preservation_v2, legal_corpus_lake
    from . import legal_pilot_lake, legal_corpus_shared_lake
    from . import legal_corpus_definition_use_lake_v2
    from ..backends import process

    return (legal_corpus_definition_use_preservation_v2, legal_corpus_lake,
            legal_pilot_lake, process, legal_corpus_shared_lake,
            legal_corpus_definition_use_lake_v2)


def _pins(owners, manifest):
    global _OPERATION_PINS
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "corpus preservation executor changed since import")
    pins = dict(manifest["producer_pins"])
    pins.update(manifest["native_producer_pins"])
    pins.update(owners[1]._pins())
    pins.update({str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
                 for module in owners})
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    for path, expected in pins.items():
        _pin(expected, "corpus preservation producer")
        _need(_sha(Path(path).read_bytes()) == expected,
              "corpus preservation producer changed: " + path)
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(pins)
    _need(pins == _OPERATION_PINS,
          "corpus preservation operation owners changed since first use")
    return pins


def validate_definition_use_preservation_native_v2(
        preparation, corpus_preparation, assessment_raw, *,
        expected_preparation_sha256, expected_corpus_preparation_sha256,
        expected_assessment_file_sha256, review_inputs, toolchain):
    """Bound original inputs, verify both whole-project pins, and replay."""
    _preflight(preparation, corpus_preparation, assessment_raw,
               expected_preparation_sha256, expected_corpus_preparation_sha256,
               expected_assessment_file_sha256, review_inputs, toolchain)
    owners = _owners()
    preparer = owners[0]
    _need(type(preparation) is preparer.DefinitionUsePreservationPreparation,
          "exact existing definition-use preservation preparation type required")
    _need(type(corpus_preparation) is owners[5].DefinitionUseCorpusPreparation,
          "exact original V2 definition-use preparation type required")
    checked = preparer.validate_definition_use_preservation_v2(
        preparation, corpus_preparation, assessment_raw,
        expected_preparation_sha256=expected_preparation_sha256,
        expected_corpus_preparation_sha256=expected_corpus_preparation_sha256,
        expected_assessment_file_sha256=expected_assessment_file_sha256,
        review_inputs=review_inputs, toolchain=toolchain)
    _pins(owners, checked.to_dict())
    return checked


def _installed_toolchain(lake_executable, toolchain):
    """Reuse the installed sibling ELF compiler and version-probe owner."""
    return _owners()[2]._installed_toolchain(lake_executable, toolchain)


def _binary_recheck(binaries):
    _need(type(binaries) is dict and len(binaries) == 2,
          "both installed sibling compiler binary pins required")
    for path, expected in binaries.items():
        _pin(expected, "installed compiler binary")
        if _sha(Path(path).read_bytes()) != expected:
            return False
    return True


def _axiom_observations(stdout, stderr, manifest):
    """Require one exact empty-axiom stdout observation per qualified theorem."""
    expected = manifest["theorems"]
    _need(type(expected) is list and len(expected) == MAX_THEOREMS
          and all(type(name) is str and len(name) <= 256
                  and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", name)
                  for name in expected)
          and len(set(expected)) == MAX_THEOREMS,
          "exact fifteen qualified corpus theorem obligations required")
    conditional, preservation = manifest["conditional_theorems"], manifest["preservation_theorems"]
    _need(type(conditional) is list and len(conditional) == MAX_CONDITIONAL_THEOREMS
          and type(preservation) is list and len(preservation) == MAX_PRESERVATION_THEOREMS
          and expected == conditional + preservation,
          "exact original conditional and four-fragment preservation theorem partition required")
    dependencies, errors = {}, []
    marker = re.compile(r"\b(?:axiom|axioms|sorry|sorryAx)\b")
    for number, line in enumerate(stdout.splitlines(), 1):
        if not marker.search(line):
            continue
        accepted = False
        for theorem in expected:
            path = theorem.rsplit(".", 1)[0].replace(".", "/") + ".lean"
            prefix = r"(?:info: (?:\./)*" + re.escape(path) + r":[1-9][0-9]*:[0-9]+: )?"
            message = "'" + theorem + "' does not depend on any axioms"
            if re.fullmatch(prefix + re.escape(message), line):
                if theorem in dependencies:
                    errors.append("duplicate empty-axiom observation: " + theorem)
                else:
                    dependencies[theorem] = []
                accepted = True
                break
        if not accepted:
            errors.append("unrecognized or nonempty stdout axiom observation at line " + str(number))
    for number, line in enumerate(stderr.splitlines(), 1):
        if marker.search(line):
            errors.append("stderr cannot establish an axiom observation at line " + str(number))
    for theorem in expected:
        if theorem not in dependencies:
            errors.append("missing empty-axiom observation: " + theorem)
    return dependencies, errors[:64], not errors and set(dependencies) == set(expected)


def _observed_process_scope(lifecycle, pid, process):
    if type(lifecycle) is not process.NativeToolLifecycleObservation:
        return False
    if (type(lifecycle.parent_pid) is not int or lifecycle.parent_pid != os.getpid()
            or type(lifecycle.parent_birth_ticks) is not int or lifecycle.parent_birth_ticks <= 0):
        return False
    try:
        current_parent, _ = process._linux_owned_identity(os.getpid())
    except (OSError, ValueError, IndexError, process.ToolProcessError):
        return False
    if (type(current_parent) is not process.NativeProcessIdentity
            or current_parent.pid != lifecycle.parent_pid
            or current_parent.birth_ticks != lifecycle.parent_birth_ticks):
        return False
    leader = lifecycle.leader
    if (type(leader) is not process.NativeProcessIdentity or type(pid) is not int or pid <= 0
            or leader.pid != pid or leader.parent_pid != lifecycle.parent_pid
            or leader.process_group_id != pid or leader.session_id != pid):
        return False
    for identity in (leader, *lifecycle.observed_descendants):
        if type(identity) is not process.NativeProcessIdentity:
            return False
        if not all(type(getattr(identity, name)) is int and getattr(identity, name) > 0
                   for name in ("pid", "birth_ticks", "parent_pid", "process_group_id", "session_id")):
            return False
        if identity.process_group_id != leader.process_group_id or identity.session_id != leader.session_id:
            return False
    return True


def compilation_receipt_sha256(receipt):
    """Commit a complete observation; this is never an admission credential."""
    _need(type(receipt) is dict and receipt.get("schema") == BUILD_SCHEMA,
          "corpus preservation compilation receipt required")
    return _sha(_wire(receipt, MAX_RECEIPT_BYTES))


def receipt_reference(receipt_raw, expected_receipt_file_sha256):
    """Address exact runtime-observation bytes as explicitly unreviewed evidence.

    This helper checks the supplied file pin and content seals/key only. It does
    not replay a preparation, read artifacts, execute a tool, validate a proof,
    grant cache admission, or infer that a claimed successful build occurred.
    """
    _pin(expected_receipt_file_sha256, "exact provided native receipt file")
    receipt = _parse(receipt_raw, MAX_RECEIPT_BYTES)
    _need(_sha(receipt_raw) == expected_receipt_file_sha256,
          "provided native receipt file pin differs")
    _need(receipt.get("schema") == BUILD_SCHEMA and receipt.get("profile") == PROFILE,
          "existing corpus preservation native receipt required")
    _pin(receipt.get("preparation_full_canonical_sha256"), "referenced complete preparation")
    reference = receipt.get("reference_contract")
    _need(type(reference) is dict
          and reference.get("schema") == "legal-corpus-v2-preservation-engineering-reference/v1"
          and reference.get("scope") == "exact_engineering_observation_only"
          and type(reference.get("key_material")) is dict,
          "existing non-authorizing engineering reference contract required")
    _pin(reference.get("reference_key_sha256"), "engineering reference key")
    _need(_sha(_wire(reference["key_material"], MAX_RECORD_BYTES)) == reference["reference_key_sha256"],
          "engineering reference key differs from its complete key material")
    from . import corpus_contracts as contracts
    from ..ir_core.evidence import EvidenceKind, EvidenceRef, EvidenceReviewStatus

    for record, schema in ((receipt, BUILD_SCHEMA),
                           (reference, "legal-corpus-v2-preservation-engineering-reference/v1")):
        # Only the envelope identity is checked here. Schema semantics and
        # historical compiler/proof claims deliberately retain their owners.
        contracts.validate_record(
            record, schema=schema,
            fields=set(record) - {"schema", "record_cid", "cid_scope"})
    result = EvidenceRef(
        evidence_id="legal-corpus-native-preservation-" + expected_receipt_file_sha256,
        kind=EvidenceKind.RUNTIME_OBSERVATION,
        content_sha256=expected_receipt_file_sha256,
        media_type="application/json",
        review_status=EvidenceReviewStatus.UNREVIEWED,
        metadata={
            "schema": BUILD_SCHEMA,
            "record_cid": receipt["record_cid"],
            "preparation_full_canonical_sha256": receipt["preparation_full_canonical_sha256"],
            "reference_contract_cid": reference["record_cid"],
            "reference_key_sha256": reference["reference_key_sha256"],
            "validation_scope": "exact_provided_file_pin_and_record_seals_only",
            "preparation_replayed": False,
            "retained_artifacts_validated": False,
            "native_execution_performed": False,
            "proof_validation_performed": False,
            "legal_proof_cache_compatible": False,
            "proof_cache_admission_verified": False,
        })
    # The record CID addresses the envelope payload excluding record_cid; leave
    # content_cid empty rather than mislabel it as the CID of the full raw file.
    result.validate()
    return result


def _persist_build(checked, output, owners, artifacts, executed_sources, logs, receipt):
    transport, shared = owners[1], owners[4]
    _need(sum(len(body.encode("utf-8")) for _, body in checked.files) <= MAX_PROJECT_BYTES
          and len(checked.manifest_json.encode("utf-8")) <= MAX_RECORD_BYTES,
          "frozen project and manifest must fit existing closed transport bounds")
    for contents in (artifacts, executed_sources):
        _need(all(type(body) is bytes and len(body) <= MAX_PROJECT_BYTES for body in contents.values())
              and sum(len(body) for body in contents.values()) <= MAX_PROJECT_BYTES,
              "complete retained observation group exceeds existing transport bounds")
    # Check the existing one-MiB receipt contract before creating output trees.
    _wire(receipt, MAX_RECEIPT_BYTES)
    shared._write_frozen_project(checked, output / "project")
    compiled = {name.removeprefix(".lake/build/lib/lean/"): body
                for name, body in artifacts.items()}
    for directory, contents, maximum in (("compiled", compiled, MAX_MODULES),
                                         ("executed-inputs", executed_sources, MAX_FILES)):
        shared._write_compiled(output / directory, contents)
        observed = transport._read_files(output / directory, set(contents), maximum_files=maximum)
        _need(observed == contents, "retained preservation observations failed exact readback")
    root_fd = os.open(output, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    try:
        transport._check_directories(output, root_fd)
        for name, raw in logs.items():
            transport._write_new_file(root_fd, name, raw)
        receipt_raw = _wire(receipt, MAX_RECEIPT_BYTES)
        transport._write_new_file(root_fd, "build-receipt.json", receipt_raw)
        os.fsync(root_fd)
        transport._check_directories(output, root_fd)
    finally:
        os.close(root_fd)
    _need((output / "build-receipt.json").read_bytes() == receipt_raw,
          "retained preservation receipt failed exact readback")
    for name, raw in logs.items():
        _need((output / name).read_bytes() == raw,
              "retained preservation compiler log failed exact readback")


def _original_preparation_state(manifest):
    """Keep original corpus/review and unexecuted preparation claims explicit."""
    return {
        "preparation_only": manifest["preparation_only"],
        "reported_flags": {key: value for key, value in manifest.items() if type(value) is bool},
        "authority": dict(manifest["authority"]),
        "original_corpus_preparation_state": manifest["original_preparation_state"],
        "theorem_assumptions": manifest["theorem_assumptions"],
        "reference_contract": manifest["reference_contract"],
    }


def build_definition_use_preservation_native_v2(
        preparation, corpus_preparation, assessment_raw, *,
        expected_preparation_sha256, expected_corpus_preparation_sha256,
        expected_assessment_file_sha256, review_inputs, toolchain,
        lake_executable, output_directory, timeout_seconds=60, cancellation=None):
    """Observe twelve concrete AST checks and three conditional corpus theorems.

    Original donor/consumer/alias hypotheses remain explicit. The caller retains
    its established resources through cleanup and durable output disposition.
    Unresolved cleanup re-raises the original exception and live owner.
    """
    _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
          and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")
    validated = validate_definition_use_preservation_native_v2(
        preparation, corpus_preparation, assessment_raw,
        expected_preparation_sha256=expected_preparation_sha256,
        expected_corpus_preparation_sha256=expected_corpus_preparation_sha256,
        expected_assessment_file_sha256=expected_assessment_file_sha256,
        review_inputs=review_inputs, toolchain=toolchain)
    owners = _owners()
    preparer, transport, _, process, _, _ = owners
    checked = preparer.DefinitionUsePreservationPreparation(
        validated.manifest_json, tuple(validated.files))
    corpus_snapshot = (corpus_preparation.manifest_json, tuple(corpus_preparation.files))
    manifest = checked.to_dict()
    producers = _pins(owners, manifest)
    original_state = _original_preparation_state(manifest)
    output = transport._path(output_directory)
    transport._check_directories(output.parent, allow_missing=True)
    _need(not output.exists() and not output.is_symlink(),
          "fresh native corpus preservation output directory required")
    executable, binaries, probes = _installed_toolchain(lake_executable, toolchain)
    _need(_binary_recheck(binaries), "installed compiler binaries changed during version probes")
    command = (str(executable), "--offline", "--no-cache", "build", "legal")
    modules = manifest["expected_modules"]
    _need(type(modules) is list and len(modules) == MAX_MODULES
          and len(set(modules)) == MAX_MODULES,
          "exact twelve native corpus preservation modules required")
    artifact_paths = tuple(".lake/build/lib/lean/" + name.replace(".", "/") + ".olean"
                           for name in modules)
    source_files = {name: body.encode("utf-8") for name, body in checked.files}
    output_paths = artifact_paths + tuple(source_files)
    invocation = process.ToolRunRequest(
        argv=command, input_files=dict(checked.files), output_paths=output_paths,
        owned_process_observation=True,
        environment={"ELAN_TOOLCHAIN": toolchain, "LEAN_NUM_THREADS": "1"},
        limits=process.ToolRunLimits(
            timeout_seconds=timeout_seconds, cpu_seconds=timeout_seconds,
            resident_memory_bytes=2 * 1024**3, max_output_bytes=MAX_CAPTURE_BYTES,
            max_input_bytes=MAX_PROJECT_BYTES, max_workspace_bytes=128 * MAX_RECORD_BYTES,
            max_output_files=MAX_FILES + MAX_MODULES))
    try:
        run = process.BoundedToolRunner().run(invocation, cancellation=cancellation)
    except process.OwnedToolCleanupError as error:
        try:
            refusal = transport.contracts.seal_record({
                "schema": BUILD_SCHEMA, "profile": PROFILE,
                "preparation_cid": manifest["record_cid"],
                "preparation_full_canonical_sha256": expected_preparation_sha256,
                "corpus_preparation_full_canonical_sha256": expected_corpus_preparation_sha256,
                "assessment_file_sha256": expected_assessment_file_sha256,
                "toolchain": toolchain, "original_preparation_state": original_state,
                "reference_contract": manifest["reference_contract"],
                "native_observations": {
                    "expected_command": list(command),
                    "execution_status": "no_complete_native_result_returned",
                    "cleanup_owner_retained_on_exception": True,
                    "cleanup_confirmed": False,
                    "error": str(error)[:2048],
                    "artifact_sha256": {}, "artifact_files": {},
                    "theorem_axiom_dependencies": {},
                },
                "build_passed": False, "status": "owned_native_cleanup_unresolved",
                "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
                **FALSE_FLAGS,
            })
            _persist_build(checked, output, owners, {}, {}, {}, refusal)
            error.add_note("Unqualified frozen corpus preservation project/cleanup refusal retained at " + str(output))
        except (ValueError, TypeError, OSError) as preservation_error:
            error.add_note("Native cleanup refusal preservation also failed: " + type(preservation_error).__name__)
        raise
    post_error, binary_error = None, None
    try:
        validate_definition_use_preservation_native_v2(
            preparation, corpus_preparation, assessment_raw,
            expected_preparation_sha256=expected_preparation_sha256,
            expected_corpus_preparation_sha256=expected_corpus_preparation_sha256,
            expected_assessment_file_sha256=expected_assessment_file_sha256,
            review_inputs=review_inputs, toolchain=toolchain)
        _need(preparation == checked, "original preservation preparation changed during compilation")
        _need((corpus_preparation.manifest_json, tuple(corpus_preparation.files)) == corpus_snapshot,
              "original corpus preparation changed during compilation")
        _need(_pins(owners, manifest) == producers, "corpus preservation producers changed during compilation")
    except (ValueError, TypeError, KeyError, IndexError, OSError, UnicodeError, RecursionError) as error:
        post_error = {"type": type(error).__name__, "message": str(error)[:2048]}
    try:
        unchanged = _binary_recheck(binaries)
    except (ValueError, TypeError, OSError) as error:
        unchanged = False
        binary_error = {"type": type(error).__name__, "message": str(error)[:2048]}
    artifacts = {name: run.output_files[name] for name in artifact_paths if name in run.output_files}
    coverage = (set(run.output_files) == set(output_paths)
                and set(artifacts) == set(artifact_paths)
                and all(type(body) is bytes and bool(body) for body in artifacts.values()))
    source_readback = all(run.output_files.get(name) == body for name, body in source_files.items())
    native_runtime = bool(run.runtime is process.ToolRuntime.NATIVE
                          and type(run.pid) is int and run.pid > 0 and not run.unavailable)
    lifecycle = run.native_lifecycle
    process_scope = _observed_process_scope(lifecycle, run.pid, process)
    cleanup_confirmed = bool(type(lifecycle) is process.NativeToolLifecycleObservation
                             and type(lifecycle.leader) is process.NativeProcessIdentity
                             and lifecycle.leader.pid == run.pid and lifecycle.cleanup_confirmed)
    axioms, axiom_errors, axiom_passed = _axiom_observations(run.stdout, run.stderr, manifest)
    passed = bool(run.ok and native_runtime and tuple(run.command) == command
                  and coverage and source_readback and unchanged and post_error is None
                  and not run.output_truncated and not run.workspace_limit_exceeded
                  and not run.resource_exhausted and run.workspace_cleaned
                  and cleanup_confirmed and process_scope and not run.error and axiom_passed)
    logs = {"stdout.txt": run.stdout.encode("utf-8"),
            "stderr.txt": run.stderr.encode("utf-8"),
            "runner-error.txt": run.error.encode("utf-8")}
    _need(all(len(raw) <= 3 * MAX_CAPTURE_BYTES for raw in logs.values()),
          "bounded preservation process observations required")
    previews = {name: raw[:MAX_LOG_PREVIEW_BYTES].decode("utf-8", errors="replace").replace("\x00", "\\u0000")
                for name, raw in logs.items()}
    observations = {
        "command": list(run.command), "expected_command": list(command),
        "runtime": run.runtime.value, "pid": run.pid, "returncode": run.returncode,
        "expected_modules": modules,
        "compiled_modules": [name for name, path in zip(modules, artifact_paths, strict=True)
                             if path in artifacts and artifacts[path]],
        "manifest_coverage_passed": bool(coverage),
        "executed_project_readback_passed": bool(source_readback),
        "executed_project_sha256": {name: _sha(run.output_files[name])
                                    for name in source_files if name in run.output_files},
        "producer_pins": producers,
        "binary_sha256": binaries, "binaries_unchanged": unchanged,
        "version_probes": probes, "toolchain_probed": True,
        "installed_toolchain_verified": unchanged,
        "post_run_validation_passed": post_error is None,
        "post_run_validation_error": post_error,
        "binary_recheck_error": binary_error,
        "original_preparation_unchanged": post_error is None,
        "artifact_sha256": {name: _sha(body) for name, body in artifacts.items()},
        "artifact_bytes": {name: len(body) for name, body in artifacts.items()},
        "artifact_files": {name: "compiled/" + name.removeprefix(".lake/build/lib/lean/")
                           for name in artifacts},
        "theorems": manifest["theorems"],
        "conditional_theorems": manifest["conditional_theorems"],
        "preservation_theorems": manifest["preservation_theorems"],
        "theorem_axiom_dependencies": axioms,
        "axiom_observations_passed": axiom_passed,
        "axiom_observation_errors": axiom_errors,
        "concrete_kernel_status": "checked_exact_four_fragment_instances" if passed else "not_verified",
        "conditional_kernel_status": "checked_under_explicit_hypotheses" if passed else "not_verified",
        "stdout": previews["stdout.txt"], "stderr": previews["stderr.txt"],
        "error": previews["runner-error.txt"],
        "log_sha256": {name: _sha(raw) for name, raw in logs.items()},
        "log_bytes": {name: len(raw) for name, raw in logs.items()},
        "receipt_text_truncated": any(len(raw) > MAX_LOG_PREVIEW_BYTES for raw in logs.values()),
        "elapsed_seconds": run.elapsed_seconds, "termination_reason": run.termination_reason,
        "timed_out": run.timed_out, "cancelled": run.cancelled, "unavailable": run.unavailable,
        "output_truncated": run.output_truncated, "workspace_limit_exceeded": run.workspace_limit_exceeded,
        "resource_exhausted": run.resource_exhausted, "workspace_cleaned": run.workspace_cleaned,
        "process_tree_terminated": run.process_tree_terminated,
        "native_lifecycle": lifecycle.to_dict()
                            if type(lifecycle) is process.NativeToolLifecycleObservation else None,
        "cleanup_confirmed": cleanup_confirmed, "observed_process_scope_passed": process_scope,
        "ownership_is_sampled": True, "kernel_containment_attested": False,
        "native_runtime_verified": native_runtime,
    }
    receipt = transport.contracts.seal_record({
        "schema": BUILD_SCHEMA, "profile": PROFILE,
        "preparation_cid": manifest["record_cid"],
        "preparation_full_canonical_sha256": expected_preparation_sha256,
        "preparation_manifest_sha256": _sha(checked.manifest_json.encode("utf-8")),
        "corpus_preparation_full_canonical_sha256": expected_corpus_preparation_sha256,
        "assessment_file_sha256": expected_assessment_file_sha256,
        "toolchain": toolchain,
        "original_preparation_state": original_state,
        "preservation_fragments": manifest["preservation_fragments"],
        "reference_contract": manifest["reference_contract"],
        "native_observations": observations,
        "build_passed": passed,
        "status": "corpus_native_preservation_checks_passed" if passed else "corpus_native_preservation_checks_failed",
        "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        "proof_scope": "Twelve exact concrete checks for the donor, consumer, alias and joint native AST values, closedness and denotation against each unchanged formula_0; three original conditional corpus theorems retain every donor, consumer and alias hypothesis. No assumed alias fact, universal emitter, JSON byte-parser, legal-source fidelity or model-convergence theorem is established.",
        **(FALSE_FLAGS | {
            "backend_executed": native_runtime, "lean_compilation_verified": passed,
            "proof_checked": passed, "kernel_proofs_checked": passed,
            "corpus_native_AST_preservation_proved": passed,
            "conditional_proofs_verified": passed,
        }),
    })
    executed_sources = {name: run.output_files[name] for name in source_files if name in run.output_files}
    _persist_build(checked, output, owners, artifacts, executed_sources, logs, receipt)
    return receipt


__all__ = ["preparation_sha256", "validate_definition_use_preservation_native_v2",
           "build_definition_use_preservation_native_v2", "compilation_receipt_sha256",
           "receipt_reference"]
