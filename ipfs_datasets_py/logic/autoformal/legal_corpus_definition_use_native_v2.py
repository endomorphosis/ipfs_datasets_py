"""Observe conditional native proofs for source-bound definition/use projects.

Public import uses only the standard library. The existing preparation owner
retains all source, review, native rendering and interpretation decisions. This
adapter replays that owner before and after one bounded offline Lake invocation
and writes a separate engineering receipt. Conditional kernel checks never
admit source meaning, legal interpretation, reviews, training data or a corpus.
Callers retain their existing owned validation resources throughout execution.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import threading
import types
import weakref

BUILD_SCHEMA = "legal-corpus-v2-definition-use-native-build/v1"
PROFILE = "replayed-v2-definition-use-conditional-native-build/v1"
PARENT_BUILD_SCHEMA = "legal-corpus-parent-definition-use-native-build/v1"
PARENT_PROFILE = "replayed-parent-definition-use-conditional-native-build/v1"
PARENT_SHARED_BUILD_SCHEMA = "legal-corpus-parent-shared-definition-use-native-build/v1"
PARENT_SHARED_PROFILE = "replayed-parent-shared-definition-use-conditional-native-build/v1"
BOUND_NORM_BUILD_SCHEMA = "legal-corpus-bound-norm-definition-native-build/v1"
BOUND_NORM_PROFILE = "replayed-bound-norm-definition-conditional-native-build/v1"
_BOUND_NORM_PREPARATION_SCHEMA = "legal-corpus-bound-norm-definition-lake-preparation/v1"
_BOUND_NORM_PREPARATION_PROFILE = "replayed-bound-norm-definition-conditional-project/v1"
_BOUND_DEFINITION_INPUT_FIELDS = {
    "companion", "request_raw", "expected_companion_sha256",
    "expected_request_sha256", "companion_inputs",
}
MAX_RECORD_BYTES = 1024 * 1024
MAX_INPUT_BYTES = 48 * MAX_RECORD_BYTES
MAX_PROJECT_BYTES = 8 * MAX_RECORD_BYTES
MAX_PREPARATION_BYTES = 20 * MAX_RECORD_BYTES
MAX_CAPTURE_BYTES = 2 * MAX_RECORD_BYTES
MAX_LOG_PREVIEW_BYTES = 32768
MAX_RECEIPT_BYTES = MAX_RECORD_BYTES
MAX_FILES = 9
MAX_MODULES = 6
MAX_THEOREMS = 3
MAX_PARENT_SHARED_COMPONENTS = 8
MAX_PARENT_SHARED_FILES = 52
MAX_PARENT_SHARED_MODULES = 34
MAX_PARENT_SHARED_THEOREMS = 24
_TOOLCHAIN = re.compile(r"leanprover/lean4:v[0-9]+\.[0-9]+\.[0-9]+\Z")
_PREPARATION_MODULE = "ipfs_datasets_py.logic.autoformal.legal_corpus_definition_use_lake_v2"
_PARENT_SHARED_MODULE = "ipfs_datasets_py.logic.autoformal.legal_corpus_shared_lake"
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
        "human_independence_verified", "applicability_semantics_verified",
        "external_definition_resolution_verified",
        "legal_dependency_inventory_exhaustive", "meaning_admitted", "admitted",
        "formalized", "semantic_graph_admitted", "proof_authority",
        "proof_checked", "kernel_proofs_checked", "conditional_proofs_verified",
        "translation_preservation_proved", "cross_family_equivalence_verified",
        "training_qualified", "training_gold_qualified", "evaluation_gold_qualified",
        "Lean_admitted", "model_executed", "learned_translation",
        "backend_executed", "lean_compilation_verified", "build_eligible",
        "semantic_definition_binding_verified", "per_occurrence_lookup_verified",
        "accepted_view_eligible", "combined_use_review_verified",
        "installed_toolchain_verified", "toolchain_probed",
        "native_build_profile_registered",
    ),
    False,
)
# Public import remains stdlib-only. The complete parent preparation flags are
# also retained at execution, after its actual owner has been loaded and replayed.
PARENT_FALSE_FLAGS = {
    **FALSE_FLAGS,
    "governing_scope_verified": False,
    "governing_edition_verified": False,
    "contributor_completeness_verified": False,
    "source_region_roles_verified": False,
}
AUTHORITY = dict.fromkeys(
    ("source", "legal", "review", "proof", "model", "training", "gold", "corpus_admission"),
    False,
)
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_OPERATION_PINS = None
_BOUND_NORM_OPERATION_PINS = None


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(value, label):
    _need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
          "independent lowercase SHA256 required: " + label)


def _bound_tree(value, maximum, *, allow_bytes=False):
    """Bound the complete ordinary input tree before importing operation owners."""
    remaining, nodes = maximum, 2_000_000

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 64, "native definition-use input node/depth bound exceeded")
        if type(item) is dict:
            remaining -= 2 + 2 * len(item)
            for key, child in item.items():
                _need(type(key) is str, "ordinary native definition-use JSON keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            remaining -= 2 + len(item)
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= remaining,
                  "bounded native definition-use UTF8 text required")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise ValueError("valid native definition-use UTF8 required") from error
        elif allow_bytes and type(item) is bytes:
            remaining -= len(item)
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded native definition-use integer required")
            remaining -= 20
        elif type(item) is float:
            _need(math.isfinite(item), "finite native definition-use JSON required")
            remaining -= 32
        else:
            raise ValueError("ordinary bounded native definition-use input values required")
        _need(remaining >= 0, "complete native definition-use input byte bound exceeded")

    visit(value, 0)


def _wire(value, maximum):
    _bound_tree(value, maximum)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("finite ordinary native definition-use JSON required") from error
    _need(len(raw) <= maximum, "complete native definition-use JSON byte bound exceeded")
    return raw


def _parse(raw, maximum):
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded original JSON bytes required")

    def pairs(items):
        result = {}
        for key, child in items:
            _need(key not in result, "duplicate native definition-use JSON key")
            result[key] = child
        return result

    def constant(_):
        raise ValueError("finite native definition-use JSON required")

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                            parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("duplicate-free finite native definition-use JSON required") from error
    _need(type(result) is dict, "native definition-use JSON object required")
    _wire(result, maximum)
    return result


def _preparation_document(preparation, *, parent_shared=False, expected_files=None):
    # The exact class is checked after all caller-controlled inputs are bounded.
    # Reading the frozen dataclass storage here does not import its owner.
    cls = type(preparation)
    module, name = ((_PARENT_SHARED_MODULE, "ParentSharedCorpusPreparation") if parent_shared
                    else (_PREPARATION_MODULE, "DefinitionUseCorpusPreparation"))
    _need(cls.__module__ == module and cls.__name__ == name,
          "existing typed parent shared preparation required" if parent_shared
          else "existing typed V2 definition-use preparation required")
    data = object.__getattribute__(preparation, "__dict__")
    _need(type(data) is dict and set(data) == {"manifest_json", "files"},
          "closed original V2 preparation fields required")
    text, original_files = data["manifest_json"], data["files"]
    _need(type(text) is str and 0 < len(text) <= MAX_RECORD_BYTES,
          "bounded original V2 preparation manifest text required")
    manifest = _parse(text.encode("utf-8"), MAX_RECORD_BYTES)
    _need(expected_files is None or (not parent_shared and type(expected_files) is int
          and expected_files == 7), "only the explicit seven-file parent norm reader may opt in")
    _need(type(original_files) is tuple and
          (1 <= len(original_files) <= MAX_PARENT_SHARED_FILES if parent_shared
           else len(original_files) == (MAX_FILES if expected_files is None else expected_files)),
          "bounded complete parent shared project required" if parent_shared
          else "exact nine-file V2 definition-use project required")
    names, files, total = [], [], 0
    for item in original_files:
        _need(type(item) is tuple and len(item) == 2, "exact generated file pairs required")
        name, body = item
        _need(type(name) is str and type(body) is str, "ordinary generated file path/text required")
        _need(len(name) <= 256 and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?", name)
              and all(part not in (".", "..") for part in name.split("/")),
              "closed two-level generated paths required")
        _need("\x00" not in body and len(body) <= MAX_PROJECT_BYTES,
              "bounded generated UTF8 source text required")
        total += len(body.encode("utf-8"))
        _need(total <= MAX_PROJECT_BYTES, "complete generated project byte bound exceeded")
        names.append(name)
        files.append([name, body])
    _need(names == sorted(set(names)), "distinct sorted complete generated file population required")
    return {"manifest": manifest, "files": files}


def preparation_sha256(preparation):
    """Commit the FULL canonical original manifest plus all nine file texts.

    This pure commitment helper is not a preparation validator. Execution also
    enforces the exact existing owner type and independently regenerates bytes.
    """
    return _sha(_wire(_preparation_document(preparation), MAX_PREPARATION_BYTES))


def parent_shared_preparation_sha256(preparation):
    """Commit the complete shared manifest and files, without granting authority."""
    return _sha(_wire(_preparation_document(preparation, parent_shared=True),
                      MAX_PREPARATION_BYTES))


def _parent_shared_preflight(preparation, component_inputs, *, expected_population,
                             expected_preparation_sha256, toolchain):
    _pin(expected_preparation_sha256, "complete parent shared preparation")
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain),
          "explicit version-pinned Lean toolchain required")
    document = _preparation_document(preparation, parent_shared=True)
    _need(type(component_inputs) is list and
          1 <= len(component_inputs) <= MAX_PARENT_SHARED_COMPONENTS,
          "bounded complete parent shared component population required")
    _need(type(expected_population) is list and len(expected_population) == len(component_inputs),
          "complete independent ordered parent shared population required")
    # Bound the entire offered project and expanded original inputs together
    # before hashing their full bodies or importing any operation owner.
    _bound_tree({"preparation": document, "component_inputs": component_inputs,
                 "expected_population": expected_population, "toolchain": toolchain},
                MAX_INPUT_BYTES, allow_bytes=True)
    _need(_sha(_wire(document, MAX_PREPARATION_BYTES)) == expected_preparation_sha256,
          "independent complete parent shared preparation pin differs")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "native definition-use owner changed since import")


def validate_parent_shared_definition_use_native_v1(
        preparation, *, component_inputs, expected_population,
        expected_preparation_sha256, toolchain):
    """Replay all original parent components and the exact aggregate project."""
    _parent_shared_preflight(preparation, component_inputs,
        expected_population=expected_population,
        expected_preparation_sha256=expected_preparation_sha256, toolchain=toolchain)
    owners = _owners()
    shared = owners[4]
    _need(type(preparation) is shared.ParentSharedCorpusPreparation,
          "exact existing parent shared preparation type required")
    checked = shared.validate_parent_shared_definition_use_corpus_v1(
        preparation, component_inputs=component_inputs,
        expected_population=expected_population, toolchain=toolchain)
    manifest = checked.to_dict()
    _need(manifest["schema"] == shared.PARENT_SCHEMA and
          manifest["profile"] == shared.PARENT_PROFILE,
          "native shared preparation must retain its exact source/review profile")
    _pins(owners, manifest)
    return checked


def _preflight(preparation, assessment_raw, expected_preparation_sha256,
               expected_assessment_file_sha256, review_inputs, toolchain):
    _pin(expected_preparation_sha256, "complete V2 definition-use preparation")
    _pin(expected_assessment_file_sha256, "original combined-review assessment file")
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain),
          "explicit version-pinned Lean toolchain required")
    _need(preparation_sha256(preparation) == expected_preparation_sha256,
          "independent complete preparation pin differs")
    _parse(assessment_raw, MAX_RECORD_BYTES)
    _need(_sha(assessment_raw) == expected_assessment_file_sha256,
          "original assessment file pin differs")
    _need(type(review_inputs) is dict and set(review_inputs) == _REVIEW_FIELDS,
          "closed complete original combined-review inputs required")
    _bound_tree({"assessment_raw": assessment_raw, "review_inputs": review_inputs},
                MAX_INPUT_BYTES, allow_bytes=True)
    for field in ("expected_subject_sha256", "expected_registry_sha256",
                  "expected_policy_sha256", "expected_reviews_sha256",
                  "expected_manifest_sha256"):
        _pin(review_inputs[field], field)
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "native definition-use owner changed since import")


def _owners():
    from . import legal_corpus_definition_use_lake_v2, legal_corpus_lake
    from . import legal_pilot_lake, legal_corpus_shared_lake
    from ..backends import process

    return (legal_corpus_definition_use_lake_v2, legal_corpus_lake,
            legal_pilot_lake, process, legal_corpus_shared_lake)


def _observed_producer_pins(owners, manifest):
    """Observe original producer custody without joining profile cache domains."""
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "native definition-use owner changed since import")
    pins = dict(manifest["producer_pins"])
    pins.update(manifest["native_producer_pins"])
    pins.update(owners[1]._pins())
    pins.update({str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
                 for module in owners})
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    for path, expected in pins.items():
        _pin(expected, "native definition-use producer")
        _need(_sha(Path(path).read_bytes()) == expected,
              "native definition-use producer changed: " + path)
    return pins


def _pins(owners, manifest):
    global _OPERATION_PINS
    pins = _observed_producer_pins(owners, manifest)
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(pins)
    _need(pins == _OPERATION_PINS, "native definition-use operation owners changed since first use")
    return pins


def _bound_norm_pins(owners, manifest):
    global _BOUND_NORM_OPERATION_PINS
    pins = _observed_producer_pins(owners, manifest)
    if _BOUND_NORM_OPERATION_PINS is None:
        _BOUND_NORM_OPERATION_PINS = dict(pins)
    _need(pins == _BOUND_NORM_OPERATION_PINS,
          "bound norm native operation owners changed since first use")
    return pins


def _validate_definition_use_native(preparation, assessment_raw, *,
        expected_preparation_sha256, expected_assessment_file_sha256,
        review_inputs, toolchain, parent=False):
    """Bound original inputs, verify the external whole pin and publicly replay."""
    _preflight(preparation, assessment_raw, expected_preparation_sha256,
               expected_assessment_file_sha256, review_inputs, toolchain)
    owners = _owners()
    preparer = owners[0]
    _need(type(preparation) is preparer.DefinitionUseCorpusPreparation,
          "exact existing V2 definition-use preparation type required")
    validate_preparation = (preparer.validate_parent_definition_use_corpus_v1 if parent
                            else preparer.validate_definition_use_corpus_v2)
    checked = validate_preparation(
        preparation, assessment_raw,
        expected_assessment_file_sha256=expected_assessment_file_sha256,
        review_inputs=review_inputs, toolchain=toolchain)
    manifest = checked.to_dict()
    _need(manifest["schema"] == (preparer.PARENT_SCHEMA if parent else preparer.SCHEMA)
          and manifest["profile"] == (preparer.PARENT_PROFILE if parent else preparer.PROFILE),
          "native preparation must retain its exact fixed source/review profile")
    _pins(owners, manifest)
    return checked


def _installed_toolchain(lake_executable, toolchain):
    """Reuse the existing ELF, sibling compiler and version-probe owner."""
    return _owners()[2]._installed_toolchain(lake_executable, toolchain)


def _binary_recheck(binaries):
    _need(type(binaries) is dict and len(binaries) == 2,
          "both installed sibling compiler binary pins required")
    for path, expected in binaries.items():
        _pin(expected, "installed compiler binary")
        if _sha(Path(path).read_bytes()) != expected:
            return False
    return True


def _axiom_observations(stdout, stderr, manifest, *, maximum_theorems=None):
    """Accept one exact Lean empty-axiom result per original qualified theorem.

    A normal Lake ``info: <generated-source>:line:column:`` prefix is allowed;
    arbitrary inline claims, stderr claims, unknown theorems and duplicates are
    not proof observations. Complete captures remain separately retained.
    """
    expected = manifest["conditional_theorems"]
    _need(type(expected) is list and
          (len(expected) == MAX_THEOREMS if maximum_theorems is None
           else 1 <= len(expected) <= maximum_theorems) and
          all(type(name) is str and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*", name)
              for name in expected) and len(set(expected)) == len(expected),
          "exact distinct conditional theorem obligations required")
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
    # Error descriptions omit arbitrary compiler text and remain receipt-bounded.
    return dependencies, errors[:64], not errors and set(dependencies) == set(expected)


def _observed_process_scope(lifecycle, pid, process):
    if type(lifecycle) is not process.NativeToolLifecycleObservation:
        return False
    if (type(lifecycle.parent_pid) is not int or lifecycle.parent_pid != os.getpid()
            or type(lifecycle.parent_birth_ticks) is not int or lifecycle.parent_birth_ticks <= 0):
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


def _compilation_receipt_sha256(receipt, *, parent=False):
    """Full canonical observation commitment; never an admission credential."""
    _need(type(receipt) is dict
          and receipt.get("schema") == (PARENT_BUILD_SCHEMA if parent else BUILD_SCHEMA),
          "parent definition-use native compilation receipt required" if parent
          else "V2 definition-use native compilation receipt required")
    return _sha(_wire(receipt, MAX_RECEIPT_BYTES))


def _persist_build(checked, output, owners, artifacts, executed_sources, logs, receipt,
                   *, maximum_files=MAX_FILES, maximum_modules=MAX_MODULES):
    transport, shared = owners[1], owners[4]
    shared._write_frozen_project(checked, output / "project")
    compiled = {name.removeprefix(".lake/build/lib/lean/"): body
                for name, body in artifacts.items()}
    for directory, contents, maximum in (("compiled", compiled, maximum_modules),
                                         ("executed-inputs", executed_sources, maximum_files)):
        shared._write_compiled(output / directory, contents)
        observed = transport._read_files(output / directory, set(contents), maximum_files=maximum)
        _need(observed == contents, "retained native observations failed exact readback")
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
          "retained native receipt failed exact readback")
    for name, raw in logs.items():
        _need((output / name).read_bytes() == raw, "retained native compiler log failed exact readback")


def _build_definition_use_native(preparation, assessment_raw, *,
        expected_preparation_sha256, expected_assessment_file_sha256,
        review_inputs, toolchain, lake_executable, output_directory,
        timeout_seconds=60, cancellation=None, parent=False):
    """Run the existing conditional project under bounded, owned native tools.

    Valid pending or rejected assessments remain pending or rejected. Native
    success concerns only the three conditional theorems in the exact generated
    project. Unresolved cleanup re-raises the original exception and live owner.
    """
    _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
          and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")
    validate_native = (validate_parent_definition_use_native_v1 if parent
                       else validate_definition_use_native_v2)
    validated = validate_native(
        preparation, assessment_raw, expected_preparation_sha256=expected_preparation_sha256,
        expected_assessment_file_sha256=expected_assessment_file_sha256,
        review_inputs=review_inputs, toolchain=toolchain)
    owners = _owners()
    preparer = owners[0]
    flags = dict(preparer.PARENT_FALSE_FLAGS if parent else preparer.FALSE_FLAGS)
    flags.update(PARENT_FALSE_FLAGS if parent else FALSE_FLAGS)
    def binding(manifest):
        return {"assessment_file_sha256": expected_assessment_file_sha256,
                "review_intake_binding": manifest["review_intake_binding"],
                "review_evidence_status": manifest["review_evidence_status"],
                "review_blockers": manifest["review_blockers"],
                "review_prerequisites_satisfied_under_selected_trust":
                    manifest["review_prerequisites_satisfied_under_selected_trust"],
                "original_preparation_build_eligible": manifest["build_eligible"],
                "original_preparation_execution_handoff": manifest["execution_handoff"]}
    def replay():
        return validate_native(preparation, assessment_raw,
            expected_preparation_sha256=expected_preparation_sha256,
            expected_assessment_file_sha256=expected_assessment_file_sha256,
            review_inputs=review_inputs, toolchain=toolchain)
    return _build_validated_native(preparation, validated,
        replay=replay, expected_preparation_sha256=expected_preparation_sha256,
        toolchain=toolchain, lake_executable=lake_executable,
        output_directory=output_directory, timeout_seconds=timeout_seconds,
        cancellation=cancellation, build_schema=PARENT_BUILD_SCHEMA if parent else BUILD_SCHEMA,
        profile=PARENT_PROFILE if parent else PROFILE, flags=flags, receipt_binding=binding)


def _build_validated_native(preparation, validated, *, replay,
        expected_preparation_sha256, toolchain, lake_executable, output_directory,
        timeout_seconds, cancellation, build_schema, profile, flags, receipt_binding,
        maximum_files=MAX_FILES, maximum_modules=MAX_MODULES,
        maximum_theorems=None, producer_pin_reader=None, receipt_scope=None,
        preparation_document_reader=None, closing_custody_guard=None, execution_observer=None,
        frozen_authority=None, instance_identity_profile=None, definition_application_profile=None):
    """One bounded native execution path, with each source profile replayed by its owner."""
    selected_identity = _reviewed_source_use_kwargs(instance_identity_profile)
    selected_application = _reviewed_definition_application_kwargs(definition_application_profile)
    if frozen_authority is not None:
        _need(type(frozen_authority) is dict and frozen_authority
              and all(type(key) is str and value is False for key, value in frozen_authority.items()),
              "explicit frozen false native observation authority required")
        frozen_authority = dict(frozen_authority)

    def receipt_authority():
        return dict(AUTHORITY) if frozen_authority is None else dict(frozen_authority)

    owners = _owners()
    # Resolve the legacy reader dynamically: existing callers and monkeypatches
    # retain the original cache domain unless a new public profile opts in.
    pin_reader = _pins if producer_pin_reader is None else producer_pin_reader
    preparer, transport, _, process, _ = owners
    # Keep a private immutable snapshot for invocation and failed-run transport.
    # A caller changing its original object during execution must not replace
    # the retained project with different bytes after the native observation.
    checked = type(validated)(validated.manifest_json, tuple(validated.files))
    shared_type = type(checked) is owners[4].ParentSharedCorpusPreparation
    snapshot_document = (_preparation_document(checked, parent_shared=shared_type)
                         if preparation_document_reader is None
                         else preparation_document_reader(checked))
    _need(_sha(_wire(snapshot_document, MAX_PREPARATION_BYTES)) == expected_preparation_sha256,
          "frozen native preparation differs from independent complete pin")
    manifest = checked.to_dict()
    receipt_binding = receipt_binding(manifest)
    producers = pin_reader(owners, manifest)
    if closing_custody_guard is not None:
        closing_custody_guard("snapshot", dict(checked=checked, manifest=manifest,
            receipt_binding=receipt_binding, producers=producers))
    output = transport._path(output_directory)
    transport._check_directories(output.parent, allow_missing=True)
    _need(not output.exists() and not output.is_symlink(), "fresh native build output directory required")
    modules = manifest["expected_modules"]
    _need(type(modules) is list and 1 <= len(modules) <= maximum_modules
          and len(set(modules)) == len(modules)
          and (maximum_modules != MAX_MODULES or len(modules) == MAX_MODULES),
          "complete bounded native module population required")
    _need(1 <= len(checked.files) <= maximum_files, "complete bounded native file population required")
    reviewed_type = (type(checked) is getattr(owners[4], "ReviewedPreservationCorpusPreparation", None))
    physical_realization = False
    if reviewed_type:
        # Freeze both closed domains. Mutable public aliases cannot give a V3
        # project the original V2 receipt profile (or the converse).
        reviewed_domains = {
            ("legal-corpus-reviewed-preservation-preparation/v2",
             "reviewed-multi-unit-object-relational-preservation/v2"):
                ("legal-corpus-reviewed-preservation-native-build/v2",
                 "replayed-reviewed-multiunit-preservation-native-build/v2"),
            ("legal-corpus-reviewed-preservation-preparation/v3",
             "reviewed-multi-unit-mixed-relational-preservation/v3"):
                ("legal-corpus-reviewed-preservation-native-build/v3",
                 "replayed-reviewed-mixed-multiunit-preservation-native-build/v3"),
            ("legal-reviewed-definition-realization-preparation/v1",
             "reviewed-unary-object-definition-realization/v1"):
                ("legal-reviewed-definition-realization-native-build/v1",
                 "replayed-reviewed-definition-realization-native-build/v1"),
        }
        physical_realization = manifest.get("schema") == "legal-reviewed-physical-definition-realization-preparation/v2"
        if physical_realization:
            _reviewed_physical_definition_realization_native_policy(owners[4],
                **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
            _reviewed_source_use_manifest(manifest, instance_identity_profile)
            _reviewed_definition_application_manifest(manifest, definition_application_profile)
            _need(receipt_binding.get("instance_identity_profile") == instance_identity_profile
                  and receipt_binding.get("definition_application_profile") == definition_application_profile,
                  "physical realization receipt requires both selected profiles")
            reviewed_domains = {("legal-reviewed-physical-definition-realization-preparation/v2",
                "reviewed-source-use-whole-norm-definition-physical-evidence-realization/v2"):
                ("legal-reviewed-physical-definition-realization-native-build/v2",
                 _reviewed_realization_domain("replayed-reviewed-physical-definition-realization-native-build/v2",
                    instance_identity_profile, definition_application_profile))}
        else:
            if selected_identity:
                reviewed_domains = {(schema, source_profile + "+reviewed-source-use/v1"):
                    (schema_out, native_profile + "+reviewed-source-use/v1")
                    for (schema, source_profile), (schema_out, native_profile) in reviewed_domains.items()}
                _reviewed_source_use_manifest(manifest, instance_identity_profile)
                _need(receipt_binding.get("instance_identity_profile") == instance_identity_profile,
                      "explicit source-use receipt identity selection required")
            if selected_application:
                _need(manifest.get("schema") == "legal-reviewed-definition-realization-preparation/v1",
                      "definition application requires its explicit realization project")
                reviewed_domains = {(schema, source_profile + "+whole-norm-definition-expansion/v1"):
                    (schema_out, native_profile + "+whole-norm-definition-expansion/v1")
                    for (schema, source_profile), (schema_out, native_profile) in reviewed_domains.items()
                    if schema == "legal-reviewed-definition-realization-preparation/v1"}
                _reviewed_definition_application_manifest(manifest, definition_application_profile)
                _need(receipt_binding.get("definition_application_profile") == definition_application_profile,
                      "explicit whole-norm receipt application selection required")
        reviewed_domain = (manifest.get("schema"), manifest.get("profile"))
        _need(reviewed_domain in reviewed_domains
              and (build_schema, profile) == reviewed_domains[reviewed_domain],
              "reviewed preservation projects require their exact closed native domain")
        theorems = manifest["preservation_obligations"]
        # These are concrete preservation theorems, not statutory truth claims.
        # The declaration's formal assumptions remain separate, unproved data.
        theorem_assumptions = []
    else:
        _need(not selected_identity and not selected_application, "explicit identity/application requires a reviewed preservation project")
        theorems = (list(dict.fromkeys(name for row in receipt_binding["theorem_contributors"]
                                      for name in row["conditional_theorems"])) if shared_type
                    else manifest["conditional_theorems"])
        theorem_assumptions = manifest["theorem_assumptions"]
    _need(1 <= len(theorems) <= (MAX_THEOREMS if maximum_theorems is None else maximum_theorems),
          "complete bounded conditional theorem population required")
    executable, binaries, probes = _installed_toolchain(lake_executable, toolchain)
    _need(_binary_recheck(binaries), "installed compiler binaries changed during version probes")
    if closing_custody_guard is not None:
        closing_custody_guard("toolchain", dict(binaries=binaries, probes=probes))
    command = (str(executable), "--offline", "--no-cache", "build", "legal")
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
            resident_memory_bytes=2 * 1024**3, max_output_bytes=64 * 1024**2 if physical_realization else MAX_CAPTURE_BYTES,
            max_input_bytes=128 * 1024**2 if physical_realization else MAX_PROJECT_BYTES,
            max_workspace_bytes=256 * 1024**2 if physical_realization else 128 * MAX_RECORD_BYTES,
            max_file_bytes=128 * 1024**2 if physical_realization else None,
            max_output_files=len(output_paths)))
    runner = process.BoundedToolRunner()
    if execution_observer is not None:
        execution_observer("before", dict(process=process, runner=runner, invocation=invocation))
    try:
        run = runner.run(invocation, cancellation=cancellation)
    except process.OwnedToolCleanupError as error:
        try:
            refusal = transport.contracts.seal_record({
                "schema": build_schema,
                "profile": profile,
                "preparation_cid": manifest["record_cid"],
                "preparation_full_canonical_sha256": expected_preparation_sha256,
                **receipt_binding,
                **({"scope": receipt_scope} if receipt_scope is not None else {}),
                "conditional_theorems": theorems,
                "toolchain": toolchain, "expected_command": list(command),
                "build_passed": False, "status": "owned_native_cleanup_unresolved",
                "execution_status": "no_complete_native_result_returned",
                "cleanup_owner_retained_on_exception": True, "cleanup_confirmed": False,
                "error": str(error)[:2048], "artifact_sha256": {}, "artifact_files": {},
                "theorem_axiom_dependencies": {},
                "theorem_assumptions": theorem_assumptions,
                "authority": receipt_authority(), "training_mask": 0, "evaluation_gold_mask": 0,
                **flags,
            })
            _persist_build(checked, output, owners, {}, {}, {}, refusal,
                           maximum_files=maximum_files, maximum_modules=maximum_modules)
            error.add_note("Unqualified frozen project/cleanup refusal retained at " + str(output))
        except (ValueError, TypeError, OSError) as preservation_error:
            error.add_note("Native cleanup refusal preservation also failed: " + type(preservation_error).__name__)
        raise
    execution_observer_error = None
    if execution_observer is not None:
        try:
            execution_observer("after", dict(process=process, runner=runner, invocation=invocation, run=run))
        except _LiveNativeObserverRefusal as error:
            # Only the private live observer uses this typed refusal, after it
            # has checked that all remaining postprocessing/persistence owners
            # are still original. Keep the completed native observations in the
            # existing failed receipt before its closing guard re-raises.
            execution_observer_error = {"type": type(error).__name__, "message": str(error)[:2048]}
    if closing_custody_guard is not None:
        closing_custody_guard("runner_returned", dict(run=run))
    post_error, binary_error = execution_observer_error, None
    try:
        replay()
        _need(preparation == checked, "original preparation changed during native compilation")
        _need(pin_reader(owners, manifest) == producers, "native producers changed during compilation")
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
                             and lifecycle.leader.pid == run.pid and lifecycle.cleanup_confirmed)
    axioms, axiom_errors, axiom_passed = _axiom_observations(
        run.stdout, run.stderr, {"conditional_theorems": theorems},
        maximum_theorems=maximum_theorems)
    passed = bool(run.ok and native_runtime and tuple(run.command) == command
                  and coverage and source_readback and unchanged and post_error is None
                  and not run.output_truncated and not run.workspace_limit_exceeded
                  and not run.resource_exhausted and run.workspace_cleaned
                  and cleanup_confirmed and process_scope and not run.error and axiom_passed)
    logs = {"stdout.txt": run.stdout.encode("utf-8"),
            "stderr.txt": run.stderr.encode("utf-8"),
            "runner-error.txt": run.error.encode("utf-8")}
    _need(all(len(raw) <= (8 * 1024**2 if physical_realization else 3 * MAX_CAPTURE_BYTES) for raw in logs.values()),
          "bounded native process observations required")
    previews = {name: raw[:MAX_LOG_PREVIEW_BYTES].decode("utf-8", errors="replace").replace("\x00", "\\u0000")
                for name, raw in logs.items()}
    reviewed_execution = {}
    if reviewed_type:
        try:
            reviewed_execution["reviewed_execution_evidence"] = _reviewed_native_execution_projection(invocation, run, process, physical_realization=physical_realization)
            reviewed_execution["reviewed_execution_projection_error"] = None
        except (ValueError, TypeError, KeyError, OSError, UnicodeError, RecursionError) as error:
            passed = False
            reviewed_execution = {"reviewed_execution_evidence": None,
                "reviewed_execution_projection_error": {"type": type(error).__name__, "message": str(error)[:2048]}}
    # Retain the complete original preparation list separately; this observation
    # carries every real hypothesis without its obsolete execution-status text.
    assumptions = [text for text in theorem_assumptions
                   if text not in {
                       "Modular joint equivalence is a generated definitional obligation; native kernel checking has not run.",
                       "This profile prepares files only; native and incremental qualification have not run."}]
    receipt = transport.contracts.seal_record({
        "schema": build_schema,
        "profile": profile,
        "preparation_cid": manifest["record_cid"],
        "preparation_full_canonical_sha256": expected_preparation_sha256,
        "preparation_manifest_sha256": _sha(checked.manifest_json.encode("utf-8")),
        **receipt_binding,
        **reviewed_execution,
        "original_preparation_unchanged": post_error is None,
        "toolchain": toolchain, "command": list(run.command), "expected_command": list(command),
        "runtime": run.runtime.value, "pid": run.pid, "returncode": run.returncode,
        "expected_modules": modules,
        "compiled_modules": [name for name, path in zip(modules, artifact_paths, strict=True)
                             if path in artifacts and artifacts[path]],
        "manifest_coverage_passed": bool(coverage),
        "executed_project_readback_passed": bool(source_readback),
        "executed_project_sha256": {name: _sha(run.output_files[name])
                                    for name in source_files if name in run.output_files},
        "producer_pins": producers,
        "binary_sha256": binaries, "binaries_unchanged": unchanged, "version_probes": probes,
        "post_run_validation_passed": post_error is None,
        "post_run_validation_error": post_error, "binary_recheck_error": binary_error,
        "artifact_sha256": {name: _sha(body) for name, body in artifacts.items()},
        "artifact_bytes": {name: len(body) for name, body in artifacts.items()},
        "artifact_files": {name: "compiled/" + name.removeprefix(".lake/build/lib/lean/")
                           for name in artifacts},
        "conditional_theorems": theorems,
        "conditional_kernel_status": "checked_under_explicit_hypotheses" if passed else "not_verified",
        "theorem_axiom_dependencies": axioms,
        "axiom_observations_passed": axiom_passed,
        "axiom_observation_errors": axiom_errors,
        "theorem_assumptions": assumptions,
        "original_preparation_theorem_assumptions": theorem_assumptions,
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
        "build_passed": passed, "native_runtime_verified": native_runtime,
        "status": "conditional_native_checks_passed" if passed else "conditional_native_checks_failed",
        "alias_assumption_proved": False, "source_to_model_equivalence_proved": False,
        "authority": receipt_authority(), "training_mask": 0, "evaluation_gold_mask": 0,
        "scope": (receipt_scope if receipt_scope is not None else
                  "Exact conditional kernel theorems under the retained donor, consumer and alias hypotheses; no source-fidelity proof, legal truth, review admission or model-convergence claim."),
        **(flags | {"backend_executed": native_runtime, "lean_compilation_verified": passed,
                    "proof_checked": passed, "kernel_proofs_checked": passed,
                    "conditional_proofs_verified": passed}),
    })
    executed_sources = {name: run.output_files[name] for name in source_files if name in run.output_files}
    if closing_custody_guard is not None:
        custody_error = closing_custody_guard("before_persistence", dict(checked=checked, manifest=manifest,
            run=run, artifacts=artifacts, executed_sources=executed_sources, logs=logs,
            receipt=receipt, output=output))
        if custody_error is not None:
            receipt = transport.contracts.seal_record({
                **{key: value for key, value in receipt.items() if key not in {"record_cid", "cid_scope"}},
                "build_passed": False, "status": "conditional_native_checks_failed",
                "original_preparation_unchanged": False, "post_run_validation_passed": False,
                "post_run_validation_error": receipt["post_run_validation_error"] or custody_error,
                "post_run_custody_error": custody_error,
                "conditional_kernel_status": "not_verified", "lean_compilation_verified": False,
                "proof_checked": False, "kernel_proofs_checked": False, "conditional_proofs_verified": False})
            closing_custody_guard("refused_persistence", dict(receipt=receipt))
    _persist_build(checked, output, owners, artifacts, executed_sources, logs, receipt,
                   maximum_files=maximum_files, maximum_modules=maximum_modules)
    if closing_custody_guard is not None:
        closing_custody_guard("after_persistence", dict(checked=checked, manifest=manifest,
            run=run, artifacts=artifacts, executed_sources=executed_sources, logs=logs,
            receipt=receipt, output=output))
    return receipt


def validate_definition_use_native_v2(
    preparation,
    assessment_raw,
    *,
    expected_preparation_sha256,
    expected_assessment_file_sha256,
    review_inputs,
    toolchain,
):
    """Replay the unchanged official V2 definition-use preparation profile."""
    return _validate_definition_use_native(
        preparation,
        assessment_raw,
        expected_preparation_sha256=expected_preparation_sha256,
        expected_assessment_file_sha256=expected_assessment_file_sha256,
        review_inputs=review_inputs,
        toolchain=toolchain,
        parent=False
    )


def validate_parent_definition_use_native_v1(
    preparation,
    assessment_raw,
    *,
    expected_preparation_sha256,
    expected_assessment_file_sha256,
    review_inputs,
    toolchain,
):
    """Replay the fixed parent preparation and all original source/review inputs."""
    return _validate_definition_use_native(
        preparation,
        assessment_raw,
        expected_preparation_sha256=expected_preparation_sha256,
        expected_assessment_file_sha256=expected_assessment_file_sha256,
        review_inputs=review_inputs,
        toolchain=toolchain,
        parent=True
    )


def build_definition_use_native_v2(
    preparation,
    assessment_raw,
    *,
    expected_preparation_sha256,
    expected_assessment_file_sha256,
    review_inputs,
    toolchain,
    lake_executable,
    output_directory,
    timeout_seconds=60,
    cancellation=None,
):
    """Observe official V2 conditional checks under existing caller-owned resources."""
    return _build_definition_use_native(
        preparation,
        assessment_raw,
        expected_preparation_sha256=expected_preparation_sha256,
        expected_assessment_file_sha256=expected_assessment_file_sha256,
        review_inputs=review_inputs,
        toolchain=toolchain,
        lake_executable=lake_executable,
        output_directory=output_directory,
        timeout_seconds=timeout_seconds,
        cancellation=cancellation,
        parent=False
    )


def build_parent_definition_use_native_v1(
    preparation,
    assessment_raw,
    *,
    expected_preparation_sha256,
    expected_assessment_file_sha256,
    review_inputs,
    toolchain,
    lake_executable,
    output_directory,
    timeout_seconds=60,
    cancellation=None,
):
    """Observe parent conditional native checks under existing caller-owned resources."""
    return _build_definition_use_native(
        preparation,
        assessment_raw,
        expected_preparation_sha256=expected_preparation_sha256,
        expected_assessment_file_sha256=expected_assessment_file_sha256,
        review_inputs=review_inputs,
        toolchain=toolchain,
        lake_executable=lake_executable,
        output_directory=output_directory,
        timeout_seconds=timeout_seconds,
        cancellation=cancellation,
        parent=True
    )


def compilation_receipt_sha256(receipt):
    """Commit the complete official V2 observation; no validation or authority is implied."""
    return _compilation_receipt_sha256(
        receipt,
        parent=False
    )


def parent_compilation_receipt_sha256(receipt):
    """Commit the complete parent observation; no validation or authority is implied."""
    return _compilation_receipt_sha256(
        receipt,
        parent=True
    )


def build_parent_shared_definition_use_native_v1(
        preparation, *, component_inputs, expected_population,
        expected_preparation_sha256, toolchain, lake_executable,
        output_directory, timeout_seconds=60, cancellation=None):
    """Observe the exact aggregate under every child's retained conditional premises.

    Callers retain the original source and native resource owners. The compiler
    timeout bounds the Lake invocation, separately from complete source/review
    replay. No combined legal review or incremental cache result is inferred.
    """
    _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
          and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")

    def replay():
        return validate_parent_shared_definition_use_native_v1(
            preparation, component_inputs=component_inputs,
            expected_population=expected_population,
            expected_preparation_sha256=expected_preparation_sha256, toolchain=toolchain)

    validated = replay()
    def binding(manifest):
        contributors = [
            {"ordinal": row["ordinal"], "component_cid": row["component_cid"],
             "conditional_theorems": list(row["conditional_theorems"])}
            for row in manifest["components"]]
        _need(1 <= len(contributors) <= MAX_PARENT_SHARED_COMPONENTS,
              "complete bounded parent shared contributor population required")
        # Every contribution survives; the engine observes each unique generated
        # theorem once in stable first-occurrence order.
        return {
            "population": manifest["population"],
            "components": manifest["components"],
            "input_commitment_sha256": manifest["input_commitment_sha256"],
            "theorem_contributors": contributors,
            "original_preparation_build_eligible": manifest["build_eligible"],
            "original_preparation_lean_compilation_status": manifest["lean_compilation_status"],
            "parent_incremental_cache_status": "not_run",
        }
    flags = dict(_owners()[4].PARENT_FALSE_FLAGS)
    flags.update(PARENT_FALSE_FLAGS)
    return _build_validated_native(preparation, validated,
        replay=replay, expected_preparation_sha256=expected_preparation_sha256,
        toolchain=toolchain, lake_executable=lake_executable,
        output_directory=output_directory, timeout_seconds=timeout_seconds,
        cancellation=cancellation, build_schema=PARENT_SHARED_BUILD_SCHEMA,
        profile=PARENT_SHARED_PROFILE, flags=flags, receipt_binding=binding,
        maximum_files=MAX_PARENT_SHARED_FILES, maximum_modules=MAX_PARENT_SHARED_MODULES,
        maximum_theorems=MAX_PARENT_SHARED_THEOREMS)


def parent_shared_compilation_receipt_sha256(receipt):
    """Commit a shared native observation; no validation or authority is implied."""
    _need(type(receipt) is dict and receipt.get("schema") == PARENT_SHARED_BUILD_SCHEMA,
          "parent shared definition-use native compilation receipt required")
    return _sha(_wire(receipt, MAX_RECEIPT_BYTES))



def _bound_norm_preflight(preparation, bound_report, *, expected_preparation_sha256,
        expected_bound_report_sha256, bound_definition_inputs, toolchain):
    """Reject bounded wire/profile/pin failures before loading replay owners."""
    _pin(expected_preparation_sha256, "complete bound norm definition preparation")
    _pin(expected_bound_report_sha256, "complete original bound definition report")
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain),
          "explicit version-pinned Lean toolchain required")
    document = _preparation_document(preparation)
    manifest = document["manifest"]
    _need(manifest.get("schema") == _BOUND_NORM_PREPARATION_SCHEMA
          and manifest.get("profile") == _BOUND_NORM_PREPARATION_PROFILE,
          "exact bound norm definition preparation profile required")
    _need(type(bound_report) is dict, "complete original bound definition report required")
    _need(type(bound_definition_inputs) is dict
          and set(bound_definition_inputs) == _BOUND_DEFINITION_INPUT_FIELDS,
          "closed original bound definition replay inputs required")
    _need(type(bound_definition_inputs["companion"]) is dict
          and type(bound_definition_inputs["companion_inputs"]) is dict,
          "ordinary complete original companion replay objects required")
    request_raw = bound_definition_inputs["request_raw"]
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= 128 * 1024,
          "bounded original bound definition request bytes required")
    _pin(bound_definition_inputs["expected_companion_sha256"], "original companion")
    _pin(bound_definition_inputs["expected_request_sha256"], "original request bytes")
    _bound_tree({"preparation": document, "bound_report": bound_report,
                 "bound_definition_inputs": bound_definition_inputs, "toolchain": toolchain},
                MAX_INPUT_BYTES, allow_bytes=True)
    _need(_sha(_wire(document, MAX_PREPARATION_BYTES)) == expected_preparation_sha256,
          "independent complete bound norm preparation pin differs")
    _need(_sha(_wire(bound_report, MAX_PROJECT_BYTES)) == expected_bound_report_sha256,
          "independent complete bound definition report pin differs")
    _need(_sha(request_raw) == bound_definition_inputs["expected_request_sha256"],
          "independent original bound definition request pin differs")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "native definition-use owner changed since import")


def validate_bound_norm_definition_native_v1(preparation, bound_report, *,
        expected_preparation_sha256, expected_bound_report_sha256,
        bound_definition_inputs, toolchain):
    """Replay the exact complete norm and conditional occurrence project.

    This accepts only its separate preparation profile. It does not select an
    interpretation, establish membership or adopt a definition into the norm.
    """
    _bound_norm_preflight(preparation, bound_report,
        expected_preparation_sha256=expected_preparation_sha256,
        expected_bound_report_sha256=expected_bound_report_sha256,
        bound_definition_inputs=bound_definition_inputs, toolchain=toolchain)
    owners = _owners()
    preparer = owners[0]
    _need(type(preparation) is preparer.DefinitionUseCorpusPreparation,
          "exact existing bound norm preparation type required")
    checked = preparer.validate_bound_norm_definition_corpus_v1(
        preparation, bound_report, expected_preparation_sha256=expected_preparation_sha256,
        expected_bound_report_sha256=expected_bound_report_sha256,
        bound_definition_inputs=bound_definition_inputs, toolchain=toolchain)
    _need(checked == preparation
          and preparation_sha256(checked) == expected_preparation_sha256,
          "replayed bound norm preparation differs from complete original pin")
    manifest = checked.to_dict()
    mode = manifest.get("bound_definition_mode")
    _need(mode in ("instance_only", "body_with_membership")
          and type(manifest.get("conditional_theorems")) is list
          and len(manifest["conditional_theorems"]) == (2 if mode == "instance_only" else 3),
          "exact mode-dependent bound norm conditional theorem population required")
    _need(manifest["bound_definition_report_sha256"] == expected_bound_report_sha256
          and manifest["schema"] == preparer.BOUND_NORM_SCHEMA
          and manifest["profile"] == preparer.BOUND_NORM_PROFILE,
          "native bound norm preparation must retain exact source/review profile")
    _bound_norm_pins(owners, manifest)
    return checked


def build_bound_norm_definition_native_v1(preparation, bound_report, *,
        expected_preparation_sha256, expected_bound_report_sha256,
        bound_definition_inputs, toolchain, lake_executable, output_directory,
        timeout_seconds=60, cancellation=None):
    """Observe only the exact conditional project with original resource owners.

    The complete unchanged relational norm and bound unary definition retain
    their original sources. Successful compilation supplies no source meaning,
    membership, governing applicability, accepted graph or corpus admission.
    """
    _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
          and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")

    def replay():
        return validate_bound_norm_definition_native_v1(
            preparation, bound_report, expected_preparation_sha256=expected_preparation_sha256,
            expected_bound_report_sha256=expected_bound_report_sha256,
            bound_definition_inputs=bound_definition_inputs, toolchain=toolchain)

    validated = replay()

    def binding(manifest):
        # The frozen nine-file project retains the complete structures. Bind
        # their full canonical contents here without duplicating a near-limit
        # preparation manifest in the separate one-MiB observation receipt.
        commitments = {key: _sha(_wire(manifest[key], MAX_RECORD_BYTES)) for key in (
            "original_norm", "occurrence_binding", "selected_link",
            "definition_alternatives", "nomination_inventory", "review_intake_binding",
            "conditional_source_binding")}
        return {
            "bound_definition_report_sha256": expected_bound_report_sha256,
            "original_input_commitment_sha256": manifest["original_input_commitment_sha256"],
            "bound_definition_mode": manifest["bound_definition_mode"],
            "retained_manifest_field_sha256": commitments,
            "definition_alternatives_count": len(manifest["definition_alternatives"]),
            "nomination_inventory_count": len(manifest["nomination_inventory"]),
            "review_evidence_status": manifest["review_evidence_status"],
            "review_blockers": manifest["review_blockers"],
            "review_prerequisites_satisfied_under_selected_trust":
                manifest["review_prerequisites_satisfied_under_selected_trust"],
            "original_preparation_build_eligible": manifest["build_eligible"],
            "original_preparation_execution_handoff": manifest["execution_handoff"],
        }

    flags = dict(_owners()[0].BOUND_NORM_FALSE_FLAGS)
    flags.update(FALSE_FLAGS)
    return _build_validated_native(preparation, validated,
        replay=replay, expected_preparation_sha256=expected_preparation_sha256,
        toolchain=toolchain, lake_executable=lake_executable,
        output_directory=output_directory, timeout_seconds=timeout_seconds,
        cancellation=cancellation, build_schema=BOUND_NORM_BUILD_SCHEMA,
        profile=BOUND_NORM_PROFILE, flags=flags, receipt_binding=binding,
        maximum_theorems=MAX_THEOREMS, producer_pin_reader=_bound_norm_pins,
        receipt_scope=("Exact conditional definition theorems and definitional preservation "
            "of the complete unchanged norm under explicit carrier, Interpretation, fixed "
            "time, binder valuation, hDefinition and any declared hMembership premises. "
            "No norm truth, actual membership, source meaning, governing applicability, "
            "graph admission, corpus admission or model-convergence claim."))


def bound_norm_definition_compilation_receipt_sha256(receipt):
    """Commit the full bounded native observation, without granting authority."""
    _need(type(receipt) is dict and receipt.get("schema") == BOUND_NORM_BUILD_SCHEMA,
          "bound norm definition native compilation receipt required")
    return _sha(_wire(receipt, MAX_RECEIPT_BYTES))


__all__ = ["preparation_sha256", "validate_definition_use_native_v2",
           "build_definition_use_native_v2", "compilation_receipt_sha256",
           "validate_parent_definition_use_native_v1", "build_parent_definition_use_native_v1",
           "parent_compilation_receipt_sha256", "parent_shared_preparation_sha256",
           "validate_parent_shared_definition_use_native_v1",
           "build_parent_shared_definition_use_native_v1",
           "parent_shared_compilation_receipt_sha256",
           "validate_bound_norm_definition_native_v1",
           "build_bound_norm_definition_native_v1",
           "bound_norm_definition_compilation_receipt_sha256"]


# Explicit direct complete authored norm execution; no definition profile is widened.
PARENT_NORM_BUILD_SCHEMA = "legal-corpus-parent-norm-native-build/v1"
PARENT_NORM_NATIVE_PROFILE = "replayed-parent-literal-complete-authored-norm-native-build/v1"
_PARENT_NORM_PREPARATION_SCHEMA = "legal-corpus-parent-norm-lake-preparation/v1"
_PARENT_NORM_PREPARATION_PROFILE = "replayed-parent-literal-complete-authored-norm-project/v1"
_PARENT_NORM_REPLAY_FIELDS = {"scope_report", "relational_report", "mapping_request_raw",
    "expected_scope_report_sha256", "expected_relational_report_sha256",
    "expected_mapping_request_sha256", "scope_replay_inputs", "relational_request_raw",
    "expected_relational_request_sha256"}
_PARENT_NORM_OPERATION_PINS = None


def _parent_norm_native_document(preparation):
    return _preparation_document(preparation, expected_files=7)


def _parent_norm_native_preflight(preparation, original):
    """Bound all original inputs and independent pins before operation imports."""
    _need(type(original) is dict and set(original) == {"correspondence",
        "expected_correspondence_sha256", "correspondence_inputs", "toolchain"},
        "closed original complete parent norm native inputs required")
    document = _parent_norm_native_document(preparation)
    manifest = document["manifest"]
    _need(manifest.get("schema") == _PARENT_NORM_PREPARATION_SCHEMA
          and manifest.get("profile") == _PARENT_NORM_PREPARATION_PROFILE,
          "explicit direct parent norm preparation profile required")
    toolchain = original["toolchain"]
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain)
          and manifest.get("toolchain") == toolchain, "exact pinned parent norm toolchain required")
    replay = original["correspondence_inputs"]
    _need(type(original["correspondence"]) is dict and type(replay) is dict
          and set(replay) == _PARENT_NORM_REPLAY_FIELDS,
          "complete parent correspondence and closed nine-field originals required")
    _bound_tree({"preparation": document, "original": original}, MAX_INPUT_BYTES, allow_bytes=True)
    _pin(original["expected_correspondence_sha256"], "full original parent correspondence")
    _need(_sha(_wire(original["correspondence"], MAX_PROJECT_BYTES))
          == original["expected_correspondence_sha256"], "independent parent correspondence pin differs")
    from . import legal_norm_scope_correspondence_v1 as correspondence
    _need(original["correspondence"].get("schema") == correspondence.SCHEMA_V2
          and original["correspondence"].get("profile")
          == "parent-literal-occurrence-authored-correspondence/v2",
          "genuine parent correspondence v2 required; no HTML relabeling")
    mapping = correspondence._parse(replay["mapping_request_raw"],
        replay["expected_mapping_request_sha256"], request_schema=correspondence.REQUEST_SCHEMA_V2)
    scope, relational = correspondence._owners()  # Stdlib-only public owners.
    relational_request = relational._parse(replay["relational_request_raw"],
                                           replay["expected_relational_request_sha256"])
    snapshot, commitments = correspondence._parent_correspondence_snapshot(
        replay["scope_report"], replay["relational_report"], replay["scope_replay_inputs"], scope)
    for field in ("scope_report", "relational_report"):
        expected = replay["expected_" + field + "_sha256"]
        _pin(expected, "full original " + field)
        _need(mapping[field + "_sha256"] == commitments[field]["sha256"] == expected,
              "independent complete parent original report pin differs")
    _need(sum(row["bytes"] for row in commitments.values()) + len(replay["mapping_request_raw"])
          + len(replay["relational_request_raw"]) <= correspondence.MAX_TOTAL_BYTES,
          "complete parent original correspondence bound exceeded")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "parent norm native producer changed before operation imports")
    return {"document": document, "mapping_request": mapping,
            "relational_request": relational_request, "snapshot": snapshot, "commitments": commitments}


def _parent_norm_native_pins(owners, manifest):
    global _PARENT_NORM_OPERATION_PINS
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "parent norm native owner changed since import")
    sources = [manifest["producer_pins"], manifest["native_producer_pins"], owners[1]._pins(),
        {str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes()) for module in owners},
        {str(Path(__file__).resolve()): _SELF_PIN}]
    pins = {}
    for source in sources:
        for path, expected in source.items():
            _pin(expected, "parent norm native producer")
            _need(path not in pins or pins[path] == expected,
                  "parent norm native producer observations disagree")
            _need(_sha(Path(path).read_bytes()) == expected, "parent norm native producer changed: " + path)
            pins[path] = expected
    if _PARENT_NORM_OPERATION_PINS is None:
        _PARENT_NORM_OPERATION_PINS = dict(pins)
    _need(pins == _PARENT_NORM_OPERATION_PINS,
          "parent norm native producer closure changed since first use")
    return pins


def _parent_norm_native_callbacks(owners):
    preparer, transport, _, process, shared = owners
    from . import legal_norm_scope_correspondence_v1 as correspondence
    functions = (_preparation_document, _parent_norm_native_document, _parent_norm_native_preflight,
        _parent_norm_native_pins, _parent_norm_native_callbacks, _parent_norm_native_runtime,
        _parent_norm_native_operation, _parent_norm_native_serialized_fence,
        _parent_norm_native_run_value, _parent_norm_native_persisted,
        validate_parent_norm_native_v1, build_parent_norm_native_v1,
        parent_norm_compilation_receipt_sha256, _bound_tree, _wire, _parse,
        _build_validated_native, _installed_toolchain, _binary_recheck,
        _axiom_observations, _observed_process_scope, _persist_build,
        process.BoundedToolRunner.run, process.ToolRunResult.to_dict,
        process.NativeToolLifecycleObservation.to_dict,
        preparer.validate_parent_norm_corpus_v1, preparer.parent_norm_preparation_sha256,
        preparer._parent_norm_capture, preparer._parent_norm_storage,
        preparer._parent_norm_file_plan, preparer._parent_norm_file_witness,
        transport._read_files, transport._write_new_file,
        shared._write_frozen_project, shared._write_compiled,
        transport.contracts.seal_record, transport.contracts.load_record_bytes)
    observed = tuple((function, getattr(function, "__code__", None),
        id(getattr(function, "__defaults__", None)), id(getattr(function, "__kwdefaults__", None)))
        for function in functions)
    return observed + preparer._parent_norm_callbacks(correspondence, preparer._owners())


def _parent_norm_native_runtime(owners):
    return {"build_schema": PARENT_NORM_BUILD_SCHEMA, "native_profile": PARENT_NORM_NATIVE_PROFILE,
        "preparation_schema": _PARENT_NORM_PREPARATION_SCHEMA,
        "preparation_profile": _PARENT_NORM_PREPARATION_PROFILE,
        "replay_fields": sorted(_PARENT_NORM_REPLAY_FIELDS), "authority": dict(AUTHORITY),
        "false_flags": dict(FALSE_FLAGS), "record_bytes": MAX_RECORD_BYTES,
        "input_bytes": MAX_INPUT_BYTES, "project_bytes": MAX_PROJECT_BYTES,
        "preparation_bytes": MAX_PREPARATION_BYTES, "capture_bytes": MAX_CAPTURE_BYTES,
        "log_preview_bytes": MAX_LOG_PREVIEW_BYTES, "receipt_bytes": MAX_RECEIPT_BYTES,
        "legacy_files": MAX_FILES, "legacy_modules": MAX_MODULES, "legacy_theorems": MAX_THEOREMS,
        "selected_files": 7, "selected_modules": 4, "selected_theorems": 1,
        "toolchain_pattern": _TOOLCHAIN.pattern,
        "preparer_runtime": owners[0]._parent_norm_runtime(owners[0]._owners())}


def _parent_norm_native_run_value(run, process):
    _need(type(run) is process.ToolRunResult, "genuine typed bounded native runner result required")
    value = run.to_dict()
    # The ordinary diagnostic to_dict decodes arbitrary binary artifacts with
    # replacement. Custody retains every original binary byte independently.
    _need(all(type(path) is str and type(body) is bytes for path, body in run.output_files.items()),
          "ordinary exact native output byte population required")
    value["output_files"] = dict(run.output_files)
    return value


def _parent_norm_native_serialized_fence(receipt, expected_wire):
    _need(_wire(receipt, MAX_RECEIPT_BYTES) == expected_wire,
          "parent norm native receipt changed after serialization")
    direct = json.dumps(receipt, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=False, allow_nan=False).encode("utf-8")
    _need(direct == expected_wire, "parent norm native receipt changed after final encoder returned")


def _parent_norm_native_persisted(checked, output, owners, artifacts, executed_sources, logs, receipt, *,
                                  maximum_files=7, maximum_modules=4):
    """Read the existing writer layout; no new transport or receipt format."""
    transport = owners[1]
    expected_project = {name: text.encode("utf-8") for name, text in checked.files}
    expected_project[transport.MANIFEST_FILE] = checked.manifest_json.encode("utf-8")
    expected_compiled = {name.removeprefix(".lake/build/lib/lean/"): raw for name, raw in artifacts.items()}
    groups = (("project", expected_project, maximum_files + 1),
              ("compiled", expected_compiled, maximum_modules),
              ("executed-inputs", executed_sources, maximum_files))
    actual, plan = [], []
    for directory, expected, maximum in groups:
        values = transport._read_files(output / directory, set(expected), maximum_files=maximum)
        _need(values == expected, "retained direct parent norm native files differ")
        actual.append(values)
        for name, raw in expected.items():
            plan.append({"descriptor": {"local_path": str(output / directory / name),
                "sha256": _sha(raw), "bytes": len(raw)}, "maximum": 128 * MAX_RECORD_BYTES})
    for name, raw in {**logs, "build-receipt.json": _wire(receipt, MAX_RECEIPT_BYTES)}.items():
        plan.append({"descriptor": {"local_path": str(output / name), "sha256": _sha(raw),
                                    "bytes": len(raw)}, "maximum": 128 * MAX_RECORD_BYTES})
    return actual, plan


def _parent_norm_native_operation(preparation, original, *, expected_preparation_sha256, operation=None):
    _pin(expected_preparation_sha256, "complete direct parent norm preparation")
    preflight = _parent_norm_native_preflight(preparation, original)
    _need(_sha(_wire(preflight["document"], MAX_PREPARATION_BYTES)) == expected_preparation_sha256,
          "independent complete direct parent norm preparation pin differs")
    owners = _owners()
    preparer, _, _, process, _ = owners
    _need(type(preparation) is preparer.DefinitionUseCorpusPreparation,
          "exact existing direct parent norm preparation type required")
    copied, commitment, _ = preparer._parent_norm_capture(original, preparation)
    from . import legal_norm_scope_correspondence_v1 as correspondence
    scope = correspondence._owners()[0]
    held, run_holds, preparation_holds = [], [], []
    state = dict(opened=None, closed=None, receipt=None, receipt_wire=None,
                 physical_plan=None, physical_witness=None, output_plan=None, output_witness=None,
                 binaries=None, binary_plan=None, binary_witness=None)
    callbacks = _parent_norm_native_callbacks(owners)
    runtime = _parent_norm_native_runtime(owners)
    pins = None
    primary = None

    def commitment_of(value):
        _bound_tree(value, 128 * MAX_RECORD_BYTES, allow_bytes=True)
        return preparer._parent_commitment(value)

    def hold(value, label):
        held.append((value, commitment_of(value), label))
        return value

    hold(preflight, "original parsed native preflight")

    def fence():
        _need(preparer._parent_norm_capture(original, preparation)[1] == commitment,
              "caller parent norm native originals or preparation changed")
        _need(preparer._parent_commitment(preparer._ParentInputBudget().copy(copied)) == commitment,
              "detached parent norm native originals changed")
        _need(_parent_norm_native_callbacks(owners) == callbacks,
              "parent norm native operation callable changed")
        _need(_parent_norm_native_runtime(owners) == runtime, "parent norm native runtime declarations changed")
        if pins is not None:
            _need(_parent_norm_native_pins(owners, state["opened"].to_dict()) == pins,
                  "parent norm native source producer changed")
        for value, expected, label in held:
            _need(commitment_of(value) == expected, "held direct parent norm native return changed: " + label)
        for value, expected in preparation_holds:
            _need(commitment_of(preparer._parent_norm_storage(value)) == expected,
                  "actual parent norm preparation raw storage changed after capture")
        for run, expected in run_holds:
            _need(commitment_of(_parent_norm_native_run_value(run, process)) == expected,
                  "actual native runner return changed after capture")
        if state["binaries"] is not None:
            _need(_binary_recheck(state["binaries"])
                  and preparer._parent_norm_file_witness(state["binary_plan"]) == state["binary_witness"],
                  "installed native sibling binaries changed after genuine probes")
        if state["physical_plan"] is not None:
            _need(preparer._parent_norm_file_witness(state["physical_plan"]) == state["physical_witness"],
                  "original parent/cache physical files changed during native operation")
        if state["output_plan"] is not None:
            _need(preparer._parent_norm_file_witness(state["output_plan"]) == state["output_witness"],
                  "persisted parent norm native files changed after genuine readback")
        for name in ("opened", "closed"):
            if state[name] is not None:
                _need(commitment_of(preparer._parent_norm_storage(state[name]))
                      == commitment_of(copied["offered"]),
                      "actual genuine parent norm preparation raw return changed")
        if state["receipt"] is not None:
            _need(_wire(state["receipt"], MAX_RECEIPT_BYTES) == state["receipt_wire"],
                  "direct parent norm native receipt changed after genuine final check")

    def replay():
        fence()
        checked = preparer.validate_parent_norm_corpus_v1(preparation, copied["correspondence"],
            expected_preparation_sha256=expected_preparation_sha256,
            expected_correspondence_sha256=copied["expected_correspondence_sha256"],
            correspondence_inputs=copied["correspondence_inputs"], toolchain=copied["toolchain"])
        _need(commitment_of(preparer._parent_norm_storage(checked)) == commitment_of(copied["offered"])
              and preparer.parent_norm_preparation_sha256(checked) == expected_preparation_sha256,
              "genuine direct parent norm preparation differs from original complete pin")
        name = "opened" if state["opened"] is None else "closed"
        state[name] = checked
        preparation_holds.append((checked, commitment_of(preparer._parent_norm_storage(checked))))
        hold(checked.to_dict(), "genuine " + name + " direct parent norm manifest")
        return checked

    def guard(stage, payload):
        if stage == "snapshot":
            for name in ("manifest", "receipt_binding", "producers"):
                hold(payload[name], "actual engine " + name)
            document = _parent_norm_native_document(payload["checked"])
            preparation_holds.append((payload["checked"],
                                      commitment_of(preparer._parent_norm_storage(payload["checked"]))))
            hold(document, "engine frozen preparation")
        elif stage == "toolchain":
            hold(payload["binaries"], "actual installed binary pins")
            hold(payload["probes"], "actual installed version probes")
            state["binaries"] = payload["binaries"]
            plan = [{"descriptor": {"local_path": path, "sha256": expected,
                "bytes": Path(path).lstat().st_size}, "maximum": 512 * MAX_RECORD_BYTES}
                for path, expected in sorted(payload["binaries"].items())]
            state["binary_plan"] = hold(plan, "actual installed binary physical plan")
            state["binary_witness"] = hold(preparer._parent_norm_file_witness(plan),
                                            "actual installed binary physical identities")
        elif stage == "runner_returned":
            run = payload["run"]
            run_holds.append((run, commitment_of(_parent_norm_native_run_value(run, process))))
        elif stage == "before_persistence":
            for name in ("artifacts", "executed_sources", "logs", "receipt"):
                hold(payload[name], "actual native " + name)
            state["receipt"] = payload["receipt"]
            state["receipt_wire"] = _wire(payload["receipt"], MAX_RECEIPT_BYTES)
            # A changed writer callback must never be invoked. Other post-run
            # custody failures retain an explicitly false receipt and the exact
            # frozen observations before the terminal fence raises.
            _need(_parent_norm_native_callbacks(owners) == callbacks,
                  "native persistence callable changed before failed observation retention")
            try:
                fence()
            except (ValueError, TypeError, KeyError, IndexError, OSError, UnicodeError, RecursionError) as error:
                return {"type": type(error).__name__, "message": str(error)[:2048]}
        elif stage == "refused_persistence":
            state["receipt"] = hold(payload["receipt"], "sealed unqualified native custody refusal")
            state["receipt_wire"] = _wire(payload["receipt"], MAX_RECEIPT_BYTES)
        elif stage == "after_persistence":
            actual, plan = _parent_norm_native_persisted(payload["checked"], payload["output"], owners,
                payload["artifacts"], payload["executed_sources"], payload["logs"], payload["receipt"])
            for values in actual:
                hold(values, "actual persisted native file readback")
            state["output_plan"] = hold(plan, "retained native output file plan")
            state["output_witness"] = hold(preparer._parent_norm_file_witness(plan),
                                           "retained native output file identities")
            fence()
        else:
            raise ValueError("unknown direct parent norm native custody stage")

    def final_receipt():
        if state["receipt"] is not None:
            _parent_norm_native_serialized_fence(state["receipt"], state["receipt_wire"])

    try:
        fence()
        checked = replay()
        manifest = checked.to_dict()
        _need(len(manifest["expected_modules"]) == 4
              and len(manifest["conditional_theorems"]) == 1
              and manifest["conditional_theorems"][0].endswith(".original_norm_preserved")
              and manifest["original_norm"]["source_binding"] is None
              and manifest["original_norm"]["source_bound"] is False
              and manifest["build_eligible"] is False
              and all(value is False for value in manifest["authority"].values())
              and all(type(manifest[key]) is int and manifest[key] == 0
                      for key in ("training_mask", "evaluation_gold_mask")),
              "exact unadmitted complete parent norm alias project required")
        pins = _parent_norm_native_pins(owners, manifest)
        fence()  # Only genuine original replay authorizes physical nominations.
        state["physical_plan"] = hold(preparer._parent_norm_file_plan(copied["correspondence_inputs"]),
                                      "complete original parent/cache file plan")
        state["physical_witness"] = hold(preparer._parent_norm_file_witness(state["physical_plan"]),
                                         "original parent/cache file identities")
        fence()
        return checked if operation is None else operation(checked, replay, guard, owners)
    except BaseException as error:
        primary = error
        raise
    finally:
        scope._parent_finish((fence, final_receipt, fence, final_receipt, fence), primary)


def validate_parent_norm_native_v1(preparation, correspondence, *, expected_preparation_sha256,
        expected_correspondence_sha256, correspondence_inputs, toolchain):
    """Validate the exact complete authored parent project; execute no tool."""
    original = dict(correspondence=correspondence, expected_correspondence_sha256=expected_correspondence_sha256,
                    correspondence_inputs=correspondence_inputs, toolchain=toolchain)
    return _parent_norm_native_operation(preparation, original,
        expected_preparation_sha256=expected_preparation_sha256)


def build_parent_norm_native_v1(preparation, correspondence, *, expected_preparation_sha256,
        expected_correspondence_sha256, correspondence_inputs, toolchain,
        lake_executable, output_directory, timeout_seconds=60, cancellation=None):
    """Observe only the unchanged authored norm's definitional alias identity.

    An actual build grants no source meaning, governing edition, definition
    applicability, norm truth, graph/corpus admission, training or convergence.
    """
    _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
          and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")
    original = dict(correspondence=correspondence, expected_correspondence_sha256=expected_correspondence_sha256,
                    correspondence_inputs=correspondence_inputs, toolchain=toolchain)

    def execute(checked, replay, guard, owners):
        def binding(manifest):
            return {"correspondence_sha256": expected_correspondence_sha256,
                "original_input_commitment_sha256": manifest["original_input_commitment_sha256"],
                "parent_source_binding_sha256": manifest["parent_source_binding_sha256"],
                "original_norm_sha256": _sha(_wire(manifest["original_norm"], MAX_RECORD_BYTES)),
                "review_intake_binding_sha256": _sha(_wire(manifest["review_intake_binding"], MAX_RECORD_BYTES)),
                "source_context_sha256": _sha(_wire(manifest["original_parent_context"], MAX_RECORD_BYTES)),
                "retained_unresolved_sha256": _sha(_wire(manifest["correspondence"]["retained_unresolved"], MAX_RECORD_BYTES)),
                "review_blockers": manifest["review_blockers"],
                "original_preparation_build_eligible": manifest["build_eligible"],
                "original_preparation_execution_handoff": manifest["execution_handoff"],
                "preservation_kind": "definitional_alias_identity_only"}
        flags = dict(owners[0].PARENT_NORM_FALSE_FLAGS)
        flags.update(FALSE_FLAGS)
        return _build_validated_native(preparation, checked, replay=replay,
            expected_preparation_sha256=expected_preparation_sha256, toolchain=toolchain,
            lake_executable=lake_executable, output_directory=output_directory,
            timeout_seconds=timeout_seconds, cancellation=cancellation,
            build_schema=PARENT_NORM_BUILD_SCHEMA, profile=PARENT_NORM_NATIVE_PROFILE,
            flags=flags, receipt_binding=binding, maximum_files=7, maximum_modules=4,
            maximum_theorems=1, producer_pin_reader=_parent_norm_native_pins,
            preparation_document_reader=_parent_norm_native_document,
            closing_custody_guard=guard,
            receipt_scope=("Only original_norm_preserved, a definitional alias identity under explicit "
                "Entity, Agent, Interpretation and time. No norm truth, source meaning, governing edition, "
                "definition applicability, graph/corpus admission, model equivalence or convergence claim."))

    return _parent_norm_native_operation(preparation, original,
        expected_preparation_sha256=expected_preparation_sha256, operation=execute)


def parent_norm_compilation_receipt_sha256(receipt):
    """Commit the complete bounded engineering receipt; grant no admission."""
    _need(type(receipt) is dict and receipt.get("schema") == PARENT_NORM_BUILD_SCHEMA
          and receipt.get("profile") == PARENT_NORM_NATIVE_PROFILE,
          "explicit direct parent norm native compilation receipt required")
    return _sha(_wire(receipt, MAX_RECEIPT_BYTES))


__all__ += ["validate_parent_norm_native_v1", "build_parent_norm_native_v1",
            "parent_norm_compilation_receipt_sha256"]

# Explicit parent-bound conditional projects; legacy preparation domains stay closed.
PARENT_BOUND_NORM_BUILD_SCHEMA = "legal-corpus-parent-bound-norm-definition-native-build/v1"
PARENT_BOUND_NORM_NATIVE_PROFILE = "replayed-parent-bound-norm-definition-conditional-native-build/v1"
_PARENT_BOUND_NORM_PREPARATION_SCHEMA = "legal-corpus-parent-bound-norm-definition-lake-preparation/v1"
_PARENT_BOUND_NORM_PREPARATION_PROFILE = "replayed-parent-bound-norm-definition-conditional-project/v1"
_PARENT_BOUND_NORM_REPORT_SCHEMA = "legal-parent-bound-variable-definition-report/v1"
_PARENT_BOUND_NORM_REPORT_PROFILE = "conditional-parent-unary-definition-at-bound-variable/v1"
_PARENT_BOUND_NORM_REQUEST_SCHEMA = "legal-parent-bound-variable-definition-request/v1"
_PARENT_BOUND_NORM_NATIVE_INPUT_FIELDS = {"bound_report", "expected_bound_report_sha256",
                                        "bound_definition_inputs", "toolchain"}
_PARENT_BOUND_NORM_COMPANION_INPUT_FIELDS = {"norm_preparation", "request_raw",
    "expected_norm_preparation_sha256", "expected_request_sha256", "norm_inputs", "definitions"}
_PARENT_BOUND_NORM_NATIVE_OPERATION_PINS = None


def _parent_bound_norm_native_preparer():
    """Load the existing explicit preparation owner only after pure preflight."""
    from . import legal_corpus_parent_bound_norm_lake_v1
    return legal_corpus_parent_bound_norm_lake_v1


def _parent_bound_norm_native_preflight(preparation, original, *, expected_preparation_sha256):
    """Bound complete originals and independent domains before lazy imports."""
    _pin(expected_preparation_sha256, "complete parent bound norm preparation")
    _need(type(original) is dict and set(original) == _PARENT_BOUND_NORM_NATIVE_INPUT_FIELDS,
          "closed original parent bound norm native inputs required")
    document = _preparation_document(preparation)
    manifest = document["manifest"]
    _need(manifest.get("schema") == _PARENT_BOUND_NORM_PREPARATION_SCHEMA
          and manifest.get("profile") == _PARENT_BOUND_NORM_PREPARATION_PROFILE,
          "explicit parent bound norm preparation profile required")
    toolchain = original["toolchain"]
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain)
          and manifest.get("toolchain") == toolchain,
          "exact version-pinned parent bound norm toolchain required")
    report, inputs = original["bound_report"], original["bound_definition_inputs"]
    _need(type(report) is dict and type(inputs) is dict
          and set(inputs) == _BOUND_DEFINITION_INPUT_FIELDS,
          "complete parent bound report and closed five-field originals required")
    _need(type(inputs["companion"]) is dict and type(inputs["companion_inputs"]) is dict
          and set(inputs["companion_inputs"]) == _PARENT_BOUND_NORM_COMPANION_INPUT_FIELDS,
          "complete parent nomination and closed original companion inputs required")
    request_raw = inputs["request_raw"]
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= 128 * 1024,
          "bounded original parent bound request bytes required")
    _bound_tree({"preparation": document, "original": original}, MAX_INPUT_BYTES, allow_bytes=True)
    _pin(original["expected_bound_report_sha256"], "complete original parent bound report")
    _pin(inputs["expected_companion_sha256"], "complete original parent nomination")
    _pin(inputs["expected_request_sha256"], "original parent bound request")
    _need(_sha(_wire(document, MAX_PREPARATION_BYTES)) == expected_preparation_sha256,
          "independent complete parent bound preparation pin differs")
    _need(_sha(_wire(report, MAX_PROJECT_BYTES)) == original["expected_bound_report_sha256"],
          "independent complete parent bound report pin differs")
    _need(_sha(_wire(inputs["companion"], MAX_PROJECT_BYTES)) == inputs["expected_companion_sha256"],
          "independent complete parent nomination pin differs")
    _need(_sha(request_raw) == inputs["expected_request_sha256"],
          "independent original parent bound request pin differs")
    _need(report.get("schema") == _PARENT_BOUND_NORM_REPORT_SCHEMA
          and report.get("profile") == _PARENT_BOUND_NORM_REPORT_PROFILE,
          "explicit genuine parent bound report required, never HTML relabeling")
    request = _parse(request_raw, 128 * 1024)
    _need(request.get("schema") == _PARENT_BOUND_NORM_REQUEST_SCHEMA
          and request.get("profile") == _PARENT_BOUND_NORM_REPORT_PROFILE
          and request.get("companion_sha256") == inputs["expected_companion_sha256"]
          and report.get("companion_sha256") == inputs["expected_companion_sha256"]
          and report.get("request_sha256") == inputs["expected_request_sha256"]
          and _wire(report.get("request"), 128 * 1024) == _wire(request, 128 * 1024),
          "parent bound report/request/companion domains differ")
    mode = request.get("mode")
    _need(type(mode) is str and mode in ("instance_only", "body_with_membership")
          and manifest.get("bound_definition_mode") == mode
          and type(manifest.get("conditional_theorems")) is list
          and len(manifest["conditional_theorems"]) == (2 if mode == "instance_only" else 3),
          "exact mode-dependent parent bound theorem population required")
    _need(all(type(report.get(key)) is int and report[key] == 0 for key in
              ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"))
          and report.get("selected_interpretation") is None
          and report.get("governing_definition_use") is None,
          "original parent bound masks and unresolved decisions must remain unchanged")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "parent bound native owner changed before operation imports")
    return {"document": document, "request": request}


def _parent_bound_norm_native_pins(owners, manifest):
    """Keep one strict producer generation separate from every legacy cache."""
    global _PARENT_BOUND_NORM_NATIVE_OPERATION_PINS
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "parent bound native owner changed since import")
    sources = [manifest["producer_pins"], manifest["native_producer_pins"], owners[1]._pins(),
        {str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
         for module in owners}, {str(Path(__file__).resolve()): _SELF_PIN}]
    pins = {}
    for source in sources:
        _need(type(source) is dict, "ordinary complete parent bound producer map required")
        for path, expected in source.items():
            _need(type(path) is str and Path(path).is_absolute(),
                  "absolute parent bound native producer path required")
            _pin(expected, "parent bound native producer")
            _need(path not in pins or pins[path] == expected,
                  "parent bound native producer observations disagree")
            _need(_sha(Path(path).read_bytes()) == expected,
                  "parent bound native producer changed: " + path)
            pins[path] = expected
    if _PARENT_BOUND_NORM_NATIVE_OPERATION_PINS is None:
        _PARENT_BOUND_NORM_NATIVE_OPERATION_PINS = dict(pins)
    _need(pins == _PARENT_BOUND_NORM_NATIVE_OPERATION_PINS,
          "parent bound native producer closure changed since first use")
    return pins


def _parent_bound_norm_native_callbacks(owners, preparer, bound_owners, evidence_owners):
    _, transport, _, process, shared = owners
    functions = (_parent_bound_norm_native_preparer, _parent_bound_norm_native_preflight,
        _parent_bound_norm_native_pins, _parent_bound_norm_native_callbacks,
        _parent_bound_norm_native_runtime, _parent_bound_norm_native_operation,
        validate_parent_bound_norm_definition_native_v1,
        build_parent_bound_norm_definition_native_v1,
        parent_bound_norm_definition_compilation_receipt_sha256,
        _owners, _preparation_document, preparation_sha256, _bound_tree, _wire, _parse, _sha, _pin, _need,
        _build_validated_native, _installed_toolchain, _binary_recheck,
        _axiom_observations, _observed_process_scope, _persist_build,
        _parent_norm_native_run_value, _parent_norm_native_serialized_fence,
        _parent_norm_native_persisted,
        process.BoundedToolRunner.run, process.ToolRunResult.to_dict,
        process.NativeToolLifecycleObservation.to_dict,
        transport._read_files, transport._write_new_file,
        shared._write_frozen_project, shared._write_compiled,
        transport.contracts.seal_record, transport.contracts.load_record_bytes,
        json.dumps, json.loads)
    observed = tuple((function, getattr(function, "__code__", None),
        id(getattr(function, "__defaults__", None)), id(getattr(function, "__kwdefaults__", None)))
        for function in functions)
    return observed + preparer._parent_bound_norm_callbacks(
        preparer.lake._owners(), bound_owners, evidence_owners)


def _parent_bound_norm_native_runtime(owners, preparer, bound_owners, evidence_owners):
    return {"build_schema": PARENT_BOUND_NORM_BUILD_SCHEMA,
        "native_profile": PARENT_BOUND_NORM_NATIVE_PROFILE,
        "preparation_schema": _PARENT_BOUND_NORM_PREPARATION_SCHEMA,
        "preparation_profile": _PARENT_BOUND_NORM_PREPARATION_PROFILE,
        "report_schema": _PARENT_BOUND_NORM_REPORT_SCHEMA,
        "report_profile": _PARENT_BOUND_NORM_REPORT_PROFILE,
        "request_schema": _PARENT_BOUND_NORM_REQUEST_SCHEMA,
        "input_fields": sorted(_PARENT_BOUND_NORM_NATIVE_INPUT_FIELDS),
        "bound_definition_fields": sorted(_BOUND_DEFINITION_INPUT_FIELDS),
        "companion_fields": sorted(_PARENT_BOUND_NORM_COMPANION_INPUT_FIELDS),
        "authority": dict(AUTHORITY), "false_flags": dict(FALSE_FLAGS),
        "record_bytes": MAX_RECORD_BYTES, "input_bytes": MAX_INPUT_BYTES,
        "project_bytes": MAX_PROJECT_BYTES, "preparation_bytes": MAX_PREPARATION_BYTES,
        "capture_bytes": MAX_CAPTURE_BYTES, "receipt_bytes": MAX_RECEIPT_BYTES,
        "log_preview_bytes": MAX_LOG_PREVIEW_BYTES,
        "legacy_files": MAX_FILES, "legacy_modules": MAX_MODULES,
        "legacy_theorems": MAX_THEOREMS, "preparation_module": _PREPARATION_MODULE,
        "selected_files": 9, "selected_modules": 6, "maximum_theorems": 3,
        "toolchain_pattern": _TOOLCHAIN.pattern,
        "document_reader_kwdefaults": (None if _preparation_document.__kwdefaults__ is None
            else dict(_preparation_document.__kwdefaults__)),
        "persisted_reader_kwdefaults": (None if _parent_norm_native_persisted.__kwdefaults__ is None
            else dict(_parent_norm_native_persisted.__kwdefaults__)),
        "engine_kwdefaults": (None if _build_validated_native.__kwdefaults__ is None
            else dict(_build_validated_native.__kwdefaults__)),
        "preparer_runtime": preparer._parent_bound_norm_runtime(
            preparer.lake._owners(), bound_owners, evidence_owners)}


def _parent_bound_norm_native_operation(preparation, original, *, expected_preparation_sha256,
                                      operation=None):
    preflight = _parent_bound_norm_native_preflight(preparation, original,
        expected_preparation_sha256=expected_preparation_sha256)
    preparer = _parent_bound_norm_native_preparer()
    _need(type(preparation) is preparer.DefinitionUseCorpusPreparation,
          "exact existing parent bound preparation type required")
    copied, commitment, _ = preparer._parent_bound_norm_capture(original, preparation)
    pure_preflight = preparer._parent_bound_norm_preflight(copied)
    owners = _owners()
    bound = preparer.bound
    bound_owners = bound._owners()
    evidence_owners = bound.evidence._parent_definition_owners()
    _, lineage, scope = evidence_owners
    held, run_holds, preparation_holds, physical = [], [], [], []
    state = dict(opened=None, closed=None, receipt=None, receipt_wire=None,
                 output_plan=None, output_witness=None, binaries=None,
                 binary_plan=None, binary_witness=None)
    callbacks = _parent_bound_norm_native_callbacks(owners, preparer, bound_owners, evidence_owners)
    pins = None
    primary = None

    def commitment_of(value):
        _bound_tree(value, 128 * MAX_RECORD_BYTES, allow_bytes=True)
        return preparer.lake._parent_commitment(value)

    runtime = commitment_of(_parent_bound_norm_native_runtime(
        owners, preparer, bound_owners, evidence_owners))

    def hold(value, label):
        held.append((value, commitment_of(value), label))
        return value

    hold(preflight, "original bounded native preflight")
    hold(list(pure_preflight), "complete original parent-bound pure preflight")

    def fence():
        _need(preparer._parent_bound_norm_capture(original, preparation)[1] == commitment,
              "caller parent bound native originals or preparation changed")
        _need(preparer.lake._parent_commitment(preparer.lake._ParentInputBudget().copy(copied))
              == commitment, "detached parent bound native originals changed")
        _need(_parent_bound_norm_native_callbacks(owners, preparer, bound_owners, evidence_owners)
              == callbacks, "parent bound native operation callable changed")
        _need(commitment_of(_parent_bound_norm_native_runtime(
                  owners, preparer, bound_owners, evidence_owners)) == runtime,
              "parent bound native runtime declarations changed")
        if pins is not None:
            _need(_parent_bound_norm_native_pins(owners, state["opened"].to_dict()) == pins,
                  "parent bound native source producer changed")
        for value, expected, label in held:
            _need(commitment_of(value) == expected,
                  "held parent bound native return changed: " + label)
        for value, expected in preparation_holds:
            _need(commitment_of(preparer._parent_bound_norm_storage(value)) == expected,
                  "actual parent bound preparation raw storage changed after capture")
        for run, expected in run_holds:
            _need(commitment_of(_parent_norm_native_run_value(run, owners[3])) == expected,
                  "actual parent bound native runner return changed after capture")
        for plan, witness, frozen in physical:
            _need(commitment_of(plan) == frozen
                  and bound.evidence._parent_definition_file_witness(plan, lineage) == witness,
                  "original parent norm or definition physical files changed")
        for prefix, message in (("binary", "installed native sibling binaries"),
                                ("output", "persisted parent bound native files")):
            if state[prefix + "_plan"] is not None:
                _need(bound.evidence._parent_definition_file_witness(
                          state[prefix + "_plan"], lineage) == state[prefix + "_witness"],
                      message + " changed after genuine readback")
        if state["binaries"] is not None:
            _need(_binary_recheck(state["binaries"]),
                  "installed parent bound compiler binaries changed")
        for name in ("opened", "closed"):
            if state[name] is not None:
                _need(commitment_of(preparer._parent_bound_norm_storage(state[name]))
                      == commitment_of(copied["offered"]),
                      "actual genuine parent bound preparation raw return changed")
        if state["receipt"] is not None:
            _need(_wire(state["receipt"], MAX_RECEIPT_BYTES) == state["receipt_wire"],
                  "parent bound native receipt changed after genuine final check")

    def replay():
        fence()
        checked = preparer.validate_parent_bound_norm_definition_corpus_v1(
            preparation, copied["bound_report"],
            expected_preparation_sha256=expected_preparation_sha256,
            expected_bound_report_sha256=copied["expected_bound_report_sha256"],
            bound_definition_inputs=copied["bound_definition_inputs"], toolchain=copied["toolchain"])
        _need(commitment_of(preparer._parent_bound_norm_storage(checked))
              == commitment_of(copied["offered"])
              and preparer.parent_bound_norm_definition_preparation_sha256(checked)
                  == expected_preparation_sha256,
              "genuine parent bound preparation differs from original complete pin")
        name = "opened" if state["opened"] is None else "closed"
        state[name] = checked
        preparation_holds.append((checked,
            commitment_of(preparer._parent_bound_norm_storage(checked))))
        hold(checked.to_dict(), "genuine " + name + " parent bound manifest")
        return checked

    def guard(stage, payload):
        if stage == "native_flags":
            hold(payload["document"], "actual validated native flags project document")
            hold(payload["flags"], "actual exact-false native profile flags")
            fence()
        elif stage == "snapshot":
            for name in ("manifest", "receipt_binding", "producers"):
                hold(payload[name], "actual engine " + name)
            preparation_holds.append((payload["checked"],
                commitment_of(preparer._parent_bound_norm_storage(payload["checked"]))))
            hold(_preparation_document(payload["checked"]), "engine frozen parent bound preparation")
            fence()
        elif stage == "toolchain":
            hold(payload["binaries"], "actual installed binary pins")
            hold(payload["probes"], "actual installed version probes")
            state["binaries"] = payload["binaries"]
            plan = [{"descriptor": {"local_path": path, "sha256": expected,
                "bytes": Path(path).lstat().st_size}, "maximum": 512 * MAX_RECORD_BYTES}
                for path, expected in sorted(payload["binaries"].items())]
            state["binary_plan"] = hold(plan, "actual installed binary physical plan")
            state["binary_witness"] = hold(
                bound.evidence._parent_definition_file_witness(plan, lineage),
                "actual installed binary physical identities")
            fence()  # A late probe mutation must refuse before the compiler call.
        elif stage == "runner_returned":
            run = payload["run"]
            run_holds.append((run, commitment_of(_parent_norm_native_run_value(run, owners[3]))))
        elif stage == "before_persistence":
            for name in ("artifacts", "executed_sources", "logs", "receipt"):
                hold(payload[name], "actual parent bound native " + name)
            state["receipt"] = payload["receipt"]
            state["receipt_wire"] = _wire(payload["receipt"], MAX_RECEIPT_BYTES)
            _need(_parent_bound_norm_native_callbacks(owners, preparer, bound_owners, evidence_owners)
                  == callbacks, "native persistence callable changed before failed observation retention")
            try:
                fence()
            except (ValueError, TypeError, KeyError, IndexError, OSError, UnicodeError, RecursionError) as error:
                return {"type": type(error).__name__, "message": str(error)[:2048]}
        elif stage == "refused_persistence":
            state["receipt"] = hold(payload["receipt"], "sealed unqualified parent bound custody refusal")
            state["receipt_wire"] = _wire(payload["receipt"], MAX_RECEIPT_BYTES)
        elif stage == "after_persistence":
            actual, plan = _parent_norm_native_persisted(payload["checked"], payload["output"], owners,
                payload["artifacts"], payload["executed_sources"], payload["logs"], payload["receipt"],
                maximum_files=9, maximum_modules=6)
            hold(actual, "whole actual persisted parent bound native readback")
            for values in actual:
                hold(values, "actual persisted parent bound native file readback")
            state["output_plan"] = hold(plan, "retained parent bound native output file plan")
            state["output_witness"] = hold(
                bound.evidence._parent_definition_file_witness(plan, lineage),
                "retained parent bound native output file identities")
            fence()
        else:
            raise ValueError("unknown parent bound norm native custody stage")

    def final_receipt():
        if state["receipt"] is not None:
            _parent_norm_native_serialized_fence(state["receipt"], state["receipt_wire"])

    def terminal():
        fence()
        if state["receipt"] is not None:
            _parent_norm_native_serialized_fence(state["receipt"], state["receipt_wire"])
            # Observe mutations after the last overridable receipt helper returns.
            fence()
            direct = json.dumps(state["receipt"], sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False).encode("utf-8")
            _need(direct == state["receipt_wire"],
                  "parent bound native receipt changed after final direct encoding")

    try:
        fence()
        checked = replay()
        manifest = hold(checked.to_dict(), "actual verified parent bound native manifest")
        mode = manifest["bound_definition_mode"]
        _need(len(manifest["expected_modules"]) == 6 and len(checked.files) == 9
              and len(manifest["conditional_theorems"]) == (2 if mode == "instance_only" else 3)
              and manifest["conditional_theorems"][-1].endswith(".original_norm_preserved")
              and manifest["original_norm"]["source_binding"] is None
              and manifest["original_norm"]["source_bound"] is False
              and manifest["build_eligible"] is False
              and manifest["selected_interpretation"] is None
              and manifest["governing_definition_use"] is None
              and all(value is False for value in manifest["authority"].values())
              and all(type(manifest[key]) is int and manifest[key] == 0 for key in
                      ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask")),
              "exact unadmitted parent norm and conditional definition project required")
        pins = _parent_bound_norm_native_pins(owners, manifest)
        fence()  # Only complete genuine replay authorizes physical nominations.
        inputs = copied["bound_definition_inputs"]["companion_inputs"]
        replays = [inputs["norm_inputs"]["correspondence_inputs"]["scope_replay_inputs"]["replay_inputs"]]
        replays.extend(endpoint["preparation_inputs"]["parent_inputs"]["replay_inputs"]
                       for endpoint in inputs["definitions"])
        for replay_inputs in replays:
            fence()
            plan = hold(bound.evidence._parent_definition_file_plan(replay_inputs, lineage),
                        "complete original parent norm/definition physical plan")
            witness = hold(bound.evidence._parent_definition_file_witness(plan, lineage),
                           "complete original parent norm/definition physical identities")
            physical.append((plan, witness, commitment_of(plan)))
            fence()
        return checked if operation is None else operation(checked, replay, guard, owners)
    except BaseException as error:
        primary = error
        raise
    finally:
        # The peer preparation validator already replays original parent-bound
        # evidence at opening and closing. Only the existing engine's post-run
        # replay adds another semantic validation; terminal custody adds none.
        scope._parent_finish((fence, final_receipt, fence, final_receipt, terminal), primary)


def validate_parent_bound_norm_definition_native_v1(preparation, bound_report, *,
        expected_preparation_sha256, expected_bound_report_sha256,
        bound_definition_inputs, toolchain):
    """Replay the exact nine-file parent-bound project without executing tools."""
    original = dict(bound_report=bound_report, expected_bound_report_sha256=expected_bound_report_sha256,
                    bound_definition_inputs=bound_definition_inputs, toolchain=toolchain)
    return _parent_bound_norm_native_operation(preparation, original,
        expected_preparation_sha256=expected_preparation_sha256)


def build_parent_bound_norm_definition_native_v1(preparation, bound_report, *,
        expected_preparation_sha256, expected_bound_report_sha256,
        bound_definition_inputs, toolchain, lake_executable, output_directory,
        timeout_seconds=60, cancellation=None):
    """Observe conditional definition proofs beside the complete unchanged norm.

    Source meaning, governing applicability, membership, corpus/graph admission,
    source-to-model equivalence and convergence remain unverified.
    """
    _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
          and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")
    original = dict(bound_report=bound_report, expected_bound_report_sha256=expected_bound_report_sha256,
                    bound_definition_inputs=bound_definition_inputs, toolchain=toolchain)

    def execute(checked, replay, guard, owners):
        def binding(manifest):
            keys = ("original_norm", "occurrence_binding", "selected_link",
                "definition_alternative_refs", "nomination_inventory", "review_intake_binding",
                "conditional_source_binding", "original_parent_context_bindings",
                "parent_bound_definition_report_ref", "conditional_theorem_statements")
            return {"bound_definition_report_sha256": expected_bound_report_sha256,
                "original_input_commitment_sha256": manifest["original_input_commitment_sha256"],
                "bound_definition_mode": manifest["bound_definition_mode"],
                "retained_manifest_field_sha256": {
                    key: _sha(_wire(manifest[key], MAX_RECORD_BYTES)) for key in keys},
                "parent_bound_definition_report_ref": manifest["parent_bound_definition_report_ref"],
                "definition_alternative_refs_count": len(manifest["definition_alternative_refs"]),
                "nomination_inventory_count": len(manifest["nomination_inventory"]),
                "review_evidence_status": manifest["review_evidence_status"],
                "review_blockers": manifest["review_blockers"],
                "review_prerequisites_satisfied_under_selected_trust":
                    manifest["review_prerequisites_satisfied_under_selected_trust"],
                "original_preparation_build_eligible": manifest["build_eligible"],
                "original_preparation_execution_handoff": manifest["execution_handoff"],
                "preservation_kind": "definitional_alias_identity_only",
                "selected_interpretation": None, "governing_definition_use": None,
                "norm_interpretation_ready": False,
                "semantic_mask": 0, "consumer_mask": 0}

        document = _preparation_document(checked)
        authority = document["manifest"].get("authority")
        _need(type(authority) is dict and bool(authority)
              and all(value is False for value in authority.values()),
              "exact unadmitted validated parent bound authority required")
        flags = dict(authority)
        flags.update(FALSE_FLAGS)
        guard("native_flags", dict(document=document, flags=flags))
        return _build_validated_native(preparation, checked, replay=replay,
            expected_preparation_sha256=expected_preparation_sha256, toolchain=toolchain,
            lake_executable=lake_executable, output_directory=output_directory,
            timeout_seconds=timeout_seconds, cancellation=cancellation,
            build_schema=PARENT_BOUND_NORM_BUILD_SCHEMA, profile=PARENT_BOUND_NORM_NATIVE_PROFILE,
            flags=flags, receipt_binding=binding, maximum_files=9, maximum_modules=6,
            maximum_theorems=3, producer_pin_reader=_parent_bound_norm_native_pins,
            closing_custody_guard=guard,
            receipt_scope=("Only exact conditional definition instances under explicit hDefinition "
                "and any matching hMembership premises, plus definitional alias preservation of the "
                "complete unchanged norm. No norm truth, governing applicability, membership proof, "
                "source meaning, corpus/graph admission, model equivalence or convergence claim."))

    return _parent_bound_norm_native_operation(preparation, original,
        expected_preparation_sha256=expected_preparation_sha256, operation=execute)


def parent_bound_norm_definition_compilation_receipt_sha256(receipt):
    """Commit the complete bounded engineering receipt; grant no admission."""
    _need(type(receipt) is dict and receipt.get("schema") == PARENT_BOUND_NORM_BUILD_SCHEMA
          and receipt.get("profile") == PARENT_BOUND_NORM_NATIVE_PROFILE,
          "explicit parent bound norm native compilation receipt required")
    return _sha(_wire(receipt, MAX_RECEIPT_BYTES))


__all__ += ["PARENT_BOUND_NORM_BUILD_SCHEMA", "PARENT_BOUND_NORM_NATIVE_PROFILE",
    "validate_parent_bound_norm_definition_native_v1", "build_parent_bound_norm_definition_native_v1",
    "parent_bound_norm_definition_compilation_receipt_sha256"]


# Closed additive port for the existing reviewed multiunit preservation project.
# This profile proves concrete IR/rendering preservation only. It neither proves
# a statute true nor applies a governing definition across distinct source units.
REVIEWED_PRESERVATION_BUILD_SCHEMA = "legal-corpus-reviewed-preservation-native-build/v2"
REVIEWED_PRESERVATION_NATIVE_PROFILE = "replayed-reviewed-multiunit-preservation-native-build/v2"
MAX_REVIEWED_PRESERVATION_UNITS = 8
MAX_REVIEWED_PRESERVATION_FILES = 9 * MAX_REVIEWED_PRESERVATION_UNITS + 6
MAX_REVIEWED_PRESERVATION_MODULES = MAX_REVIEWED_PRESERVATION_UNITS + 3
MAX_REVIEWED_PRESERVATION_THEOREMS = 5 * MAX_REVIEWED_PRESERVATION_UNITS
_REVIEWED_PRESERVATION_OPERATION_PINS = None


def _reviewed_source_use_kwargs(instance_identity_profile):
    """Select one caller-requested source-use domain; never infer from records."""
    if instance_identity_profile is None:
        return {}
    if type(instance_identity_profile) is not str or instance_identity_profile != "reviewed-source-use/v1":
        raise ValueError("explicit reviewed-source-use/v1 instance identity profile required")
    return {"instance_identity_profile": instance_identity_profile}


def _reviewed_source_use_domain(profile, instance_identity_profile):
    _reviewed_source_use_kwargs(instance_identity_profile)
    return profile if instance_identity_profile is None else profile + "+reviewed-source-use/v1"


def _reviewed_source_use_manifest(manifest, instance_identity_profile):
    """Check the exact verified Shared unit echoes, without granting authority."""
    selected = _reviewed_source_use_kwargs(instance_identity_profile)
    if not selected:
        return {}
    _need(type(manifest) is dict and manifest.get("instance_identity_profile") == instance_identity_profile
          and type(manifest.get("units")) is list and 3 <= len(manifest["units"]) <= 8,
          "complete explicitly selected source-use manifest required")
    keys = {"schema", "unit_id", "source_version_cid", "source_occurrence_cid", "complete_ir_sha256",
            "graph_unit_record_cid", "graph_ast_record_cid", "scope_record_cid", "interpretation_record_cid"}
    instances = []
    for unit in manifest["units"]:
        _need(type(unit) is dict and type(unit.get("source_use_binding")) is dict,
              "complete source-use binding for every reviewed unit required")
        binding = unit["source_use_binding"]
        _need(set(binding) == keys and all(type(value) is str and 0 < len(value) <= 2048
                                         for value in binding.values())
              and binding["schema"] == "legal-native-reviewed-source-use-binding/v1"
              and all(binding[key] == unit[key] for key in keys - {"schema"}),
              "source-use binding differs from exact reviewed unit provenance")
        _pin(unit.get("source_use_binding_sha256"), "reviewed source-use binding")
        _need(_sha(_wire(binding, MAX_RECORD_BYTES)) == unit["source_use_binding_sha256"],
              "source-use binding canonical commitment differs")
        instances.append(unit["instance_module"])
    _need(len(instances) == len(set(instances)), "one distinct source-use instance per reviewed unit required")
    return selected


def _reviewed_preservation_native_document(preparation):
    cls = type(preparation)
    _need(cls.__module__ == _PARENT_SHARED_MODULE and cls.__name__ == "ReviewedPreservationCorpusPreparation",
          "existing typed reviewed preservation preparation required")
    storage = object.__getattribute__(preparation, "__dict__")
    _need(type(storage) is dict and set(storage) == {"manifest_json", "files"},
          "closed reviewed preservation preparation fields required")
    text, offered = storage["manifest_json"], storage["files"]
    _need(type(text) is str and 0 < len(text) <= MAX_RECORD_BYTES,
          "bounded reviewed preservation manifest required")
    # Parse only for bounded structural diagnostics. The public preparation pin
    # commits the exact manifest string, including its original UTF8 bytes.
    _parse(text.encode("utf-8"), MAX_RECORD_BYTES)
    _need(type(offered) is tuple and 1 <= len(offered) <= MAX_REVIEWED_PRESERVATION_FILES,
          "complete bounded reviewed preservation file population required")
    files, names, size = [], [], 0
    for item in offered:
        _need(type(item) is tuple and len(item) == 2, "exact reviewed project file pairs required")
        name, body = item
        _need(type(name) is str and len(name) <= 256
              and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?", name)
              and all(part not in (".", "..") for part in name.split("/")),
              "closed reviewed preservation project paths required")
        _need(type(body) is str and "\x00" not in body, "ordinary reviewed project UTF8 text required")
        try:
            size += len(body.encode("utf-8"))
        except UnicodeError as error:
            raise ValueError("valid reviewed project UTF8 required") from error
        _need(size <= MAX_PROJECT_BYTES, "complete reviewed preservation project byte bound exceeded")
        names.append(name); files.append([name, body])
    _need(names == sorted(set(names)), "sorted distinct complete reviewed project files required")
    # This reviewed-only reader also feeds the frozen gate in the original
    # native engine. Keep the canonical shared owner's public transport recipe.
    return {"manifest_json": text, "files": files}


def _reviewed_preservation_native_pins(owners, manifest, *, instance_identity_profile=None):
    global _REVIEWED_PRESERVATION_OPERATION_PINS
    shared = owners[4]
    _reviewed_source_use_kwargs(instance_identity_profile)
    if instance_identity_profile is not None:
        _reviewed_preservation_native_manifest(manifest, shared, instance_identity_profile=instance_identity_profile)
    current = shared._reviewed_preservation_pins(shared._reviewed_preservation_owners())
    pins = _observed_producer_pins(owners, manifest)
    for path, expected in current.items():
        _need(path not in pins or pins[path] == expected, "reviewed native producer pin collision")
        pins[path] = expected
    if _REVIEWED_PRESERVATION_OPERATION_PINS is None:
        _REVIEWED_PRESERVATION_OPERATION_PINS = dict(pins)
    _need(pins == _REVIEWED_PRESERVATION_OPERATION_PINS,
          "reviewed native operation owners changed since first use")
    return pins


def _reviewed_preservation_native_manifest(manifest, shared, *, instance_identity_profile=None):
    _reviewed_source_use_kwargs(instance_identity_profile)
    if instance_identity_profile is not None:
        _need(shared.REVIEWED_SOURCE_USE_PRESERVATION_PROFILE == shared.REVIEWED_PRESERVATION_PROFILE + "+reviewed-source-use/v1",
              "closed Shared source-use preservation profile required")
    _reviewed_source_use_manifest(manifest, instance_identity_profile)
    _need(manifest.get("schema") == shared.REVIEWED_PRESERVATION_SCHEMA
          and manifest.get("profile") == (shared.REVIEWED_PRESERVATION_PROFILE if instance_identity_profile is None
              else shared.REVIEWED_SOURCE_USE_PRESERVATION_PROFILE),
          "exact current reviewed preservation preparation profile required")
    _need(shared.MAX_REVIEWED_PRESERVATION_FILES == MAX_REVIEWED_PRESERVATION_FILES
          and shared.MAX_REVIEWED_PRESERVATION_MODULES == MAX_REVIEWED_PRESERVATION_MODULES
          and shared.MAX_REVIEWED_PRESERVATION_OBLIGATIONS == MAX_REVIEWED_PRESERVATION_THEOREMS,
          "reviewed native and preparation bounds require an explicit port")
    units = manifest["units"]
    _need(type(units) is list and 3 <= len(units) <= MAX_REVIEWED_PRESERVATION_UNITS,
          "complete three-to-eight reviewed source units required")
    theorems = [name for unit in units for name in unit["preservation_obligations"]]
    _need(all(len(unit["preservation_obligations"]) == 5 for unit in units)
          and len(theorems) == len(set(theorems)) == 5 * len(units)
          and manifest["preservation_obligations"] == theorems,
          "all five ordered concrete obligations per reviewed unit required")
    _need(manifest["support_profile"]["cross_unit_definition_application_proved"] is False
          and manifest["preparation_only"] is True
          and manifest["proof_status"] == "not_executed"
          and manifest["lean_compilation_status"] == "not_executed",
          "preparation cannot supply its own native or definition-application proof")
    return manifest


def _reviewed_preservation_native_operation(preparation, graph, admission, args, kwargs, *,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256,
        toolchain, operation=None, reviewed_version=2, instance_identity_profile=None, definition_application_profile=None, realization_preservation=None,
        expected_upstream_preservation_sha256=None, physical_request_raw=None, expected_physical_request_sha256=None):
    _need(type(reviewed_version) is int and reviewed_version in (2, 3, 4, 5),
          "explicit closed reviewed native version required")
    _reviewed_definition_application_kwargs(definition_application_profile)
    _need(definition_application_profile is None or reviewed_version in (4, 5),
          "whole-norm application requires the explicit realization native domain")
    _need(reviewed_version == 5 or physical_request_raw is expected_physical_request_sha256 is None,
          "physical request requires the explicit physical realization native domain")
    if reviewed_version == 5:
        return _reviewed_physical_definition_realization_native_operation(preparation, realization_preservation,
            graph, admission, args, kwargs, expected_realization_sha256=expected_preservation_sha256,
            expected_preservation_sha256=expected_upstream_preservation_sha256,
            expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
            toolchain=toolchain, operation=operation, physical_request_raw=physical_request_raw,
            expected_physical_request_sha256=expected_physical_request_sha256,
            **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    if reviewed_version == 4:
        return _reviewed_definition_realization_native_operation(preparation, realization_preservation,
            graph, admission, args, kwargs, expected_realization_sha256=expected_preservation_sha256,
            expected_preservation_sha256=expected_upstream_preservation_sha256,
            expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
            toolchain=toolchain, operation=operation, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    if reviewed_version == 3:
        _reviewed_mixed_native_policy(**_reviewed_source_use_kwargs(instance_identity_profile))
    _reviewed_source_use_kwargs(instance_identity_profile)
    document = _reviewed_preservation_native_document(preparation)
    for value, label in ((expected_preservation_sha256, "complete reviewed preservation preparation"),
                         (expected_graph_sha256, "complete reviewed graph"),
                         (expected_admission_sha256, "complete current reviewed admission")):
        _pin(value, label)
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain),
          "explicit version-pinned Lean toolchain required")
    _need(len(args) == 4 and type(kwargs) is dict, "complete original admission replay arguments required")
    original = dict(graph=graph, admission=admission, args=list(args), kwargs=kwargs,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain)
    if instance_identity_profile is not None:
        original["instance_identity_profile"] = instance_identity_profile
    _bound_tree({"preparation": document, **original}, MAX_INPUT_BYTES, allow_bytes=True)
    _need(_sha(_wire(document, MAX_PREPARATION_BYTES)) == expected_preservation_sha256,
          "independent complete reviewed preservation preparation pin differs")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "reviewed native owner changed since import")
    owners = _owners(); shared = owners[4]
    _need(type(preparation) is shared.ReviewedPreservationCorpusPreparation,
          "exact canonical reviewed preservation preparation type required")
    _need(shared.reviewed_preservation_corpus_sha256(preparation) == expected_preservation_sha256,
          "canonical public reviewed preservation preparation pin differs")
    if reviewed_version == 2:
        admission_owner = shared._reviewed_preservation_owners()[1]
        validate_project = shared.validate_reviewed_norm_preservation_corpus_v2
        validate_manifest = _reviewed_preservation_native_manifest
        read_pins = _reviewed_preservation_native_pins
        domain_callables = ()
    else:
        _reviewed_mixed_native_policy(shared, **_reviewed_source_use_kwargs(instance_identity_profile))
        admission_owner = shared._reviewed_mixed_preservation_owners()[1]
        validate_project = shared.validate_reviewed_norm_preservation_corpus_v3
        validate_manifest = _reviewed_mixed_preservation_native_manifest
        read_pins = _reviewed_mixed_preservation_native_pins
        domain_callables = tuple((name, _live_callable_state(getattr(shared, name))) for name in (
            "validate_reviewed_norm_preservation_corpus_v3", "_reviewed_mixed_preservation_owners",
            "_reviewed_preservation_pins"))
    detached, commitment = admission_owner.norm._snapshot(original)
    frozen_document, project_commitment = admission_owner.norm._snapshot(document)
    # Parsed semantics are execution data, never a replacement for the exact
    # raw manifest envelope authenticated by the public shared preparation pin.
    execution_document, _ = admission_owner.norm._snapshot({
        "manifest": _parse(frozen_document["manifest_json"].encode("utf-8"), MAX_RECORD_BYTES),
        "files": frozen_document["files"]})

    def fence():
        if reviewed_version == 3:
            _reviewed_mixed_native_policy(shared, **_reviewed_source_use_kwargs(instance_identity_profile))
            _need(all(_live_callable_matches(getattr(shared, name), state) for name, state in domain_callables),
                  "mixed shared preparation callbacks changed during native replay")
        _need(admission_owner.norm._snapshot(original)[1] == commitment
              and admission_owner.norm._snapshot(detached)[1] == commitment
              and admission_owner.norm._snapshot(_reviewed_preservation_native_document(preparation))[1]
                    == project_commitment
              and shared.reviewed_preservation_corpus_sha256(preparation) == expected_preservation_sha256,
              "reviewed native source, graph, admission, project or current observations changed")

    def replay():
        fence()
        project_validator = (shared.validate_reviewed_norm_preservation_corpus_v2
                             if reviewed_version == 2 else validate_project)
        checked = project_validator(preparation,
            detached["graph"], detached["admission"], *detached["args"],
            expected_preservation_sha256=expected_preservation_sha256,
            expected_graph_sha256=detached["expected_graph_sha256"],
            expected_admission_sha256=detached["expected_admission_sha256"],
            toolchain=toolchain, **detached["kwargs"], **_reviewed_source_use_kwargs(instance_identity_profile))
        _need(_reviewed_preservation_native_document(checked) == frozen_document
              and shared.reviewed_preservation_corpus_sha256(checked) == expected_preservation_sha256,
              "canonical current reviewed project replay differs")
        parsed_manifest = checked.to_dict()
        _need(parsed_manifest == execution_document["manifest"],
              "parsed reviewed preservation execution manifest differs from exact envelope")
        if reviewed_version == 2:
            _reviewed_preservation_native_manifest(parsed_manifest, shared, **_reviewed_source_use_kwargs(instance_identity_profile))
            _reviewed_preservation_native_pins(owners, parsed_manifest, **_reviewed_source_use_kwargs(instance_identity_profile))
        else:
            validate_manifest(parsed_manifest, shared, **_reviewed_source_use_kwargs(instance_identity_profile))
            read_pins(owners, parsed_manifest, **_reviewed_source_use_kwargs(instance_identity_profile))
        fence()
        return checked

    checked = replay()
    if operation is None:
        return checked
    error = None

    def custody(stage, values):
        nonlocal error
        try:
            fence()
            if reviewed_version == 2:
                _reviewed_preservation_native_pins(owners, checked.to_dict(), **_reviewed_source_use_kwargs(instance_identity_profile))
            else:
                read_pins(owners, checked.to_dict(), **_reviewed_source_use_kwargs(instance_identity_profile))
        except (ValueError, TypeError, KeyError, OSError, UnicodeError, RecursionError) as failure:
            if stage in ("snapshot", "toolchain", "after_persistence"):
                raise
            error = {"type": type(failure).__name__, "message": str(failure)[:2048]}
        return error if stage == "before_persistence" else None

    result = operation(checked, replay, custody)
    fence()
    return result


def validate_reviewed_norm_preservation_native_v2(preparation, graph, admission, *args,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256,
        toolchain, instance_identity_profile=None, **kwargs):
    """Replay the complete current source/review/graph/project, without building.

    Validation of preparation is not validation of a previous native receipt.
    No generic Lean receipt or caller eligibility boolean can replace this replay.
    """
    return _reviewed_preservation_native_operation(preparation, graph, admission, args, kwargs,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, **_reviewed_source_use_kwargs(instance_identity_profile))


def _reviewed_preservation_receipt_binding(manifest, admission, *, instance_identity_profile=None):
    return {name: manifest[name] for name in (
        "input_commitment_sha256", "reviewed_graph_sha256", "reviewed_admission_sha256",
        "declaration_sha256", "provenance_kind", "scope_record_cid", "interpretation_record_cid",
        "units", "signature_header", "predicate_compatibility_ledger", "module_imports",
        "preservation_obligations", "file_sha256", "support_profile")} | {
        "preservation_only": True, "cross_unit_definition_application_proved": False,
        "statutory_meaning_proved": False, "release_ready": False,
        "full_formal_corpus_consistency_verified": False,
        "generic_lean_v3_receipt_substituted": False,
        "formal_assumptions": admission["formal_assumptions"], "formal_assumptions_proved": False} | _reviewed_source_use_manifest(manifest, instance_identity_profile)


def build_reviewed_norm_preservation_native_v2(preparation, graph, admission, *args,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256,
        toolchain, lake_executable, output_directory, timeout_seconds=60, cancellation=None, instance_identity_profile=None, **kwargs):
    """Observe all concrete multiunit preservation obligations through the old runner.

    Callers must retain existing admitted native resources. Current original
    inputs are replayed before and after the one bounded offline Lake build.
    No source meaning, governing definition application or corpus readiness is
    established. Generic v3 Main.lean receipts remain a separate proof profile.
    """
    _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
          and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")

    def execute(checked, replay, custody):
        def binding(manifest):
            return _reviewed_preservation_receipt_binding(manifest, admission, **_reviewed_source_use_kwargs(instance_identity_profile))
        return _build_validated_native(preparation, checked, replay=replay,
            expected_preparation_sha256=expected_preservation_sha256, toolchain=toolchain,
            lake_executable=lake_executable, output_directory=output_directory,
            timeout_seconds=timeout_seconds, cancellation=cancellation,
            build_schema=REVIEWED_PRESERVATION_BUILD_SCHEMA, profile=_reviewed_source_use_domain(REVIEWED_PRESERVATION_NATIVE_PROFILE, instance_identity_profile),
            flags=dict(PARENT_FALSE_FLAGS), receipt_binding=binding,
            maximum_files=MAX_REVIEWED_PRESERVATION_FILES,
            maximum_modules=MAX_REVIEWED_PRESERVATION_MODULES,
            maximum_theorems=MAX_REVIEWED_PRESERVATION_THEOREMS,
            producer_pin_reader=(_reviewed_preservation_native_pins if instance_identity_profile is None else
                lambda owners, manifest: _reviewed_preservation_native_pins(owners, manifest, instance_identity_profile=instance_identity_profile)),
            preparation_document_reader=_reviewed_preservation_native_document,
            closing_custody_guard=custody,
            receipt_scope="Five exact independent concrete IR/native preservation obligations for each current reviewed source unit; no cross-unit governing-definition application, statutory truth, universal compiler theorem, legal review or corpus/release admission.", **_reviewed_source_use_kwargs(instance_identity_profile))

    return _reviewed_preservation_native_operation(preparation, graph, admission, args, kwargs,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, operation=execute, **_reviewed_source_use_kwargs(instance_identity_profile))


__all__ += ["REVIEWED_PRESERVATION_BUILD_SCHEMA", "REVIEWED_PRESERVATION_NATIVE_PROFILE",
            "validate_reviewed_norm_preservation_native_v2", "build_reviewed_norm_preservation_native_v2"]


_REVIEWED_EXECUTION_SCHEMA = "legal-reviewed-preservation-execution-projection/v1"
_REVIEWED_RUN_FIELDS = ("interface_version", "runtime", "command", "returncode", "pid", "elapsed_seconds",
    "timed_out", "cancelled", "unavailable", "output_truncated", "workspace_limit_exceeded",
    "process_tree_terminated", "resource_exhausted", "workspace_cleaned", "termination_reason", "native_lifecycle")


def _reviewed_native_lifecycle_from_dict(value, process):
    """Closed structural decoder; this observes no process and grants no authority."""
    if value is None:
        return None
    _bound_tree(value, MAX_RECORD_BYTES)
    fields = {"schema", "parent", "leader", "observed_descendants", "leader_reaped",
        "descendant_tracking_complete", "group_scan_complete", "remaining_group_members",
        "remaining_tracked_descendants", "readers", "stdin_writer", "workspace", "observation_errors",
        "ownership_is_sampled", "kernel_containment_attested", "cleanup_confirmed"}
    _need(type(value) is dict and set(value) == fields and value["schema"] == "native-owned-tool-lifecycle@1",
          "closed supported native lifecycle record required")
    _need(value["ownership_is_sampled"] is True and value["kernel_containment_attested"] is False,
          "sampled ownership cannot become kernel containment")
    parent = value["parent"]
    _need(type(parent) is dict and set(parent) == {"pid", "birth_ticks"}
          and all(type(item) is int and item > 0 for item in parent.values()), "closed parent identity required")

    def identity(row):
        _need(type(row) is dict and set(row) == {"pid", "birth_ticks", "parent_pid", "process_group_id", "session_id"}
              and all(type(item) is int and item > 0 for item in row.values()), "closed positive native identity required")
        return process.NativeProcessIdentity(**row)

    groups = {}
    for name in ("observed_descendants", "remaining_group_members", "remaining_tracked_descendants"):
        rows = value[name]
        _need(type(rows) is list and len(rows) <= 4096, "bounded complete sampled identity array required")
        groups[name] = tuple(identity(row) for row in rows)
        _need(len({(row.pid, row.birth_ticks) for row in groups[name]}) == len(rows),
              "duplicate sampled native identity refused")
    for name in ("leader_reaped", "descendant_tracking_complete", "group_scan_complete", "cleanup_confirmed"):
        _need(type(value[name]) is bool, "exact native lifecycle boolean required")
    counts = {}
    for name, bound in (("readers", 2), ("stdin_writer", 1)):
        row = value[name]
        _need(type(row) is dict and set(row) == {"started", "joined"}
              and all(type(item) is int and 0 <= item <= bound for item in row.values())
              and row["joined"] <= row["started"], "closed native I/O counts required")
        counts[name] = row
    workspace = value["workspace"]
    _need(type(workspace) is dict and set(workspace) == {"device", "inode", "removed"}
          and type(workspace["device"]) is int and workspace["device"] >= 0
          and type(workspace["inode"]) is int and workspace["inode"] > 0
          and type(workspace["removed"]) is bool, "closed native workspace observation required")
    errors = value["observation_errors"]
    _need(type(errors) is list and len(errors) <= 64
          and all(type(item) is str and len(item.encode("utf-8")) <= 2048 for item in errors),
          "bounded complete lifecycle errors required")
    result = process.NativeToolLifecycleObservation(parent_pid=parent["pid"], parent_birth_ticks=parent["birth_ticks"],
        leader=identity(value["leader"]), **groups, leader_reaped=value["leader_reaped"],
        descendant_tracking_complete=value["descendant_tracking_complete"], group_scan_complete=value["group_scan_complete"],
        readers_started=counts["readers"]["started"], readers_joined=counts["readers"]["joined"],
        stdin_writer_started=counts["stdin_writer"]["started"], stdin_writer_joined=counts["stdin_writer"]["joined"],
        workspace_device=workspace["device"], workspace_inode=workspace["inode"], workspace_removed=workspace["removed"],
        observation_errors=tuple(errors))
    _need(result.to_dict() == value, "native lifecycle derived cleanup or exact shape differs")
    return result


def _reviewed_native_execution_projection(invocation, run, process, *, physical_realization=False):
    """Pure, lossless sidecar identities; binary artifacts are never text-decoded.

    Capturing a result records its supplied interface and lifecycle. This is not
    independent execution attestation or a persisted-receipt qualification.
    """
    _need(type(physical_realization) is bool, "closed physical projection domain required")
    from dataclasses import fields
    from types import MappingProxyType
    _need(type(invocation) is process.ToolRunRequest and type(run) is process.ToolRunResult,
          "exact canonical tool request and result required")
    _need(invocation.stdin is None and not invocation.secrets and invocation.owned_process_observation is True,
          "closed source-only owned native invocation required")
    _need(type(invocation.limits) is process.ToolRunLimits and type(run.runtime) is process.ToolRuntime
          and (run.returncode is None or type(run.returncode) is int)
          and all(type(getattr(run, name)) is bool for name in _REVIEWED_RUN_FIELDS
                  if name not in ("interface_version", "runtime", "command", "returncode", "pid", "elapsed_seconds",
                                  "termination_reason", "native_lifecycle")), "typed ordinary original runner fields required")
    _need(len(invocation.input_files) <= MAX_REVIEWED_PRESERVATION_FILES
          and type(run.output_files) in (dict, MappingProxyType)
          and len(run.output_files) <= MAX_REVIEWED_PRESERVATION_FILES + MAX_REVIEWED_PRESERVATION_MODULES,
          "bounded ordinary raw source/output mappings required")
    _need(all(type(getattr(run, name)) is str for name in ("stdout", "stderr", "error")),
          "ordinary raw diagnostic text required")
    _bound_tree({"sources": dict(invocation.input_files), "outputs": dict(run.output_files),
                 "stdout": run.stdout, "stderr": run.stderr, "error": run.error}, (128 * 1024**2 if physical_realization else MAX_INPUT_BYTES), allow_bytes=True)
    def byte_ref(raw):
        _need(type(raw) is bytes, "raw sidecar bytes required")
        return {"bytes": len(raw), "sha256": _sha(raw)}
    sources = {}
    for name, body in invocation.input_files.items():
        _need(type(name) is str and type(body) in (str, bytes), "ordinary source input required")
        sources[name] = body.encode("utf-8") if type(body) is str else body
    _need(sum(len(raw) for raw in sources.values()) <= MAX_PROJECT_BYTES,
          "complete projected source byte bound exceeded")
    outputs = dict(run.output_files)
    _need(len(outputs) <= MAX_REVIEWED_PRESERVATION_FILES + MAX_REVIEWED_PRESERVATION_MODULES
          and all(type(name) is str and type(raw) is bytes for name, raw in outputs.items())
          and sum(len(raw) for raw in outputs.values()) <= invocation.limits.max_workspace_bytes,
          "complete raw projected output population bound exceeded")
    logs = {name: getattr(run, attr).encode("utf-8") for name, attr in
            (("stdout.txt", "stdout"), ("stderr.txt", "stderr"), ("runner-error.txt", "error"))}
    _need(all(len(raw) <= (8 * 1024**2 if physical_realization else 3 * MAX_CAPTURE_BYTES) for raw in logs.values()), "complete raw diagnostic bound exceeded")
    lifecycle = None
    if run.native_lifecycle is not None:
        _need(type(run.native_lifecycle) is process.NativeToolLifecycleObservation, "typed native lifecycle required")
        lifecycle = run.native_lifecycle.to_dict()
        _reviewed_native_lifecycle_from_dict(lifecycle, process)
    metadata = {name: getattr(run, name) for name in _REVIEWED_RUN_FIELDS
                if name not in ("runtime", "command", "native_lifecycle")}
    metadata.update(runtime=run.runtime.value, command=list(run.command), native_lifecycle=lifecycle)
    result = {"schema": _REVIEWED_EXECUTION_SCHEMA, "invocation": {
        "argv": list(invocation.argv), "runtime": invocation.runtime.value,
        "limits": {field.name: getattr(invocation.limits, field.name) for field in fields(process.ToolRunLimits)},
        "environment": dict(invocation.environment), "owned_process_observation": True,
        "input_file_refs": {name: byte_ref(raw) for name, raw in sorted(sources.items())},
        "output_paths": list(invocation.output_paths)}, "result": metadata,
        "raw_logs": {name: byte_ref(raw) for name, raw in logs.items()},
        "output_file_refs": {name: byte_ref(raw) for name, raw in sorted(outputs.items())}}
    _wire(result, MAX_RECORD_BYTES)
    return result


def _reviewed_native_execution_from_projection(value, *, sources, outputs, logs, process, physical_realization=False):
    """Reconstruct ordinary typed metadata and raw bytes, with no tool execution.

    The future persisted loader must still bind full current project semantics,
    independently trusted receipt/owner evidence, strict proof reports and all
    producer/toolchain/closure identities. This helper grants none of those.
    """
    _need(type(physical_realization) is bool, "closed physical projection domain required")
    from dataclasses import fields
    _bound_tree({"projection": value, "sources": sources, "outputs": outputs, "logs": logs},
                (128 * 1024**2 if physical_realization else MAX_INPUT_BYTES), allow_bytes=True)
    _bound_tree(value, MAX_RECORD_BYTES)
    _need(type(value) is dict and set(value) == {"schema", "invocation", "result", "raw_logs", "output_file_refs"}
          and value["schema"] == _REVIEWED_EXECUTION_SCHEMA, "closed reviewed execution projection required")
    invocation, metadata = value["invocation"], value["result"]
    _need(type(invocation) is dict and set(invocation) == {"argv", "runtime", "limits", "environment",
        "owned_process_observation", "input_file_refs", "output_paths"}, "closed original native invocation required")
    _need(type(metadata) is dict and set(metadata) == set(_REVIEWED_RUN_FIELDS), "closed original result metadata required")
    _need(type(sources) is dict and type(outputs) is dict and type(logs) is dict
          and set(sources) == set(invocation["input_file_refs"])
          and set(outputs) == set(value["output_file_refs"])
          and set(logs) == set(value["raw_logs"]) == {"stdout.txt", "stderr.txt", "runner-error.txt"},
          "complete independently supplied raw source/output/log populations required")
    for actual, refs in ((sources, invocation["input_file_refs"]), (outputs, value["output_file_refs"]), (logs, value["raw_logs"])):
        _need(type(refs) is dict, "closed raw byte references required")
        for name, raw in actual.items():
            reference = refs[name]
            _need(type(name) is str and type(raw) is bytes and type(reference) is dict
                  and set(reference) == {"bytes", "sha256"}
                  and type(reference["bytes"]) is int and reference["bytes"] == len(raw)
                  and reference["sha256"] == _sha(raw), "complete raw sidecar reference differs")
    limits = invocation["limits"]
    _need(type(limits) is dict and set(limits) == {field.name for field in fields(process.ToolRunLimits)},
          "complete original invocation limits required")
    _need(type(invocation["argv"]) is list and type(invocation["output_paths"]) is list
          and type(metadata["command"]) is list and type(invocation["environment"]) is dict,
          "ordinary original invocation arrays and environment required")
    _need(0 < len(invocation["argv"]) <= 256 and len(invocation["output_paths"]) <= MAX_REVIEWED_PRESERVATION_FILES + MAX_REVIEWED_PRESERVATION_MODULES
          and len(metadata["command"]) <= 256 and len(invocation["environment"]) <= 64,
          "bounded original argument/path/environment population required")
    for parts in (invocation["argv"], metadata["command"]):
        _need(all(type(part) is str and "\x00" not in part and len(part.encode("utf-8")) <= 4096 for part in parts),
              "ordinary original argument strings required")
    _need(all(type(name) is str and type(body) is str and "\x00" not in name + body
              for name, body in invocation["environment"].items()), "ordinary original environment required")
    _need(all(type(path) is str and 0 < len(path) <= 512 and not path.startswith("/")
              and "\\" not in path and "\x00" not in path
              and all(part not in ("", ".", "..") for part in path.split("/"))
              for path in invocation["output_paths"]), "closed original output paths required")
    for name in _REVIEWED_RUN_FIELDS:
        if name in ("interface_version", "termination_reason"):
            _need(type(metadata[name]) is str and len(metadata[name].encode("utf-8")) <= 256,
                  "bounded original runner text required")
        elif name not in ("runtime", "command", "native_lifecycle", "returncode", "pid", "elapsed_seconds"):
            _need(type(metadata[name]) is bool, "exact original result boolean required")
    _need(metadata["returncode"] is None or type(metadata["returncode"]) is int, "ordinary original exit code required")
    _need(metadata["pid"] is None or (type(metadata["pid"]) is int and metadata["pid"] > 0),
          "ordinary positive original tool PID required")
    _need(type(metadata["elapsed_seconds"]) in (int, float) and math.isfinite(metadata["elapsed_seconds"])
          and metadata["elapsed_seconds"] >= 0, "finite original tool elapsed time required")
    request = process.ToolRunRequest(argv=tuple(invocation["argv"]), runtime=invocation["runtime"],
        limits=process.ToolRunLimits(**limits), input_files=sources, output_paths=tuple(invocation["output_paths"]),
        environment=invocation["environment"], owned_process_observation=invocation["owned_process_observation"])
    texts = {name: raw.decode("utf-8") for name, raw in logs.items()}
    record = dict(metadata, runtime=process.ToolRuntime(metadata["runtime"]), command=tuple(metadata["command"]),
        native_lifecycle=_reviewed_native_lifecycle_from_dict(metadata["native_lifecycle"], process),
        stdout=texts["stdout.txt"], stderr=texts["stderr.txt"], error=texts["runner-error.txt"], output_files=outputs)
    result = process.ToolRunResult(**record)
    _need(_reviewed_native_execution_projection(request, result, process, physical_realization=physical_realization) == value,
          "complete original execution projection differs after typed raw reconstruction")
    return request, result


# Retained reviewed-native observations remain zero-authority. A trusted
# original admitted-success adapter is a separate, currently absent prerequisite.
REVIEWED_RECEIPT_REPLAY_SCHEMA = "legal-reviewed-native-receipt-replay/v1"
REVIEWED_RECEIPT_REPLAY_PROFILE = "current-reviewed-native-retained-observation-replay/v1"
_REVIEWED_REPLAY_ACTUAL = "retained-native-observation/v1"
_REVIEWED_REPLAY_FICTIONAL = "fictional-authored-observation/v1"
_REVIEWED_REPLAY_BINDINGS = (
    "input_commitment_sha256", "reviewed_graph_sha256", "reviewed_admission_sha256",
    "declaration_sha256", "provenance_kind", "scope_record_cid", "interpretation_record_cid",
    "units", "signature_header", "predicate_compatibility_ledger", "module_imports",
    "preservation_obligations", "file_sha256", "support_profile",
    "preservation_only", "cross_unit_definition_application_proved", "statutory_meaning_proved",
    "release_ready", "full_formal_corpus_consistency_verified", "generic_lean_v3_receipt_substituted",
    "formal_assumptions", "formal_assumptions_proved",
)
_REVIEWED_REPLAY_CORE_FIELDS = frozenset({
    "schema", "profile", "record_cid", "cid_scope", "preparation_cid",
    "preparation_full_canonical_sha256", "preparation_manifest_sha256",
    "reviewed_execution_evidence", "reviewed_execution_projection_error",
    "original_preparation_unchanged", "toolchain", "command", "expected_command", "runtime",
    "pid", "returncode", "expected_modules", "compiled_modules", "manifest_coverage_passed",
    "executed_project_readback_passed", "executed_project_sha256", "producer_pins",
    "binary_sha256", "binaries_unchanged", "version_probes", "post_run_validation_passed",
    "post_run_validation_error", "binary_recheck_error", "artifact_sha256", "artifact_bytes",
    "artifact_files", "conditional_theorems", "conditional_kernel_status",
    "theorem_axiom_dependencies", "axiom_observations_passed", "axiom_observation_errors",
    "theorem_assumptions", "original_preparation_theorem_assumptions", "stdout", "stderr", "error",
    "log_sha256", "log_bytes", "receipt_text_truncated", "elapsed_seconds", "termination_reason",
    "timed_out", "cancelled", "unavailable", "output_truncated", "workspace_limit_exceeded",
    "resource_exhausted", "workspace_cleaned", "process_tree_terminated", "native_lifecycle",
    "cleanup_confirmed", "observed_process_scope_passed", "ownership_is_sampled",
    "kernel_containment_attested", "build_passed", "native_runtime_verified", "status",
    "alias_assumption_proved", "source_to_model_equivalence_proved", "authority",
    "training_mask", "evaluation_gold_mask", "scope",
}) | frozenset(_REVIEWED_REPLAY_BINDINGS) | frozenset(PARENT_FALSE_FLAGS)
_REVIEWED_REPLAY_SCOPE = (
    "Five exact independent concrete IR/native preservation obligations for each current reviewed "
    "source unit; no cross-unit governing-definition application, statutory truth, universal compiler "
    "theorem, legal review or corpus/release admission.")


def reviewed_norm_preservation_receipt_bytes_v2(receipt, *, instance_identity_profile=None):
    """Format one complete reviewed-profile observation, granting no authority.

    This is a bounded closed formatter, not receipt validation, producer
    authentication or an original-success adapter. No operation owner is loaded.
    """
    selected = _reviewed_source_use_kwargs(instance_identity_profile)
    _bound_tree(receipt, MAX_RECEIPT_BYTES)
    _reviewed_source_use_manifest(receipt, instance_identity_profile)
    _need(type(receipt) is dict and set(receipt) == _REVIEWED_REPLAY_CORE_FIELDS | set(selected)
          and receipt["schema"] == REVIEWED_PRESERVATION_BUILD_SCHEMA
          and receipt["profile"] == _reviewed_source_use_domain(REVIEWED_PRESERVATION_NATIVE_PROFILE, instance_identity_profile),
          "closed complete reviewed-native receipt required")
    return _wire(receipt, MAX_RECEIPT_BYTES)


def _reviewed_retained_packet(packet_files):
    _need(type(packet_files) in (tuple, list)
          and 1 <= len(packet_files) <= 2 * MAX_REVIEWED_PRESERVATION_FILES
              + MAX_REVIEWED_PRESERVATION_MODULES + 5,
          "bounded complete reviewed-native byte packet required")
    pairs, names = [], []
    for item in packet_files:
        _need(type(item) in (tuple, list) and len(item) == 2,
              "exact retained path/raw-byte pairs required")
        name, raw = item
        _need(type(name) is str and 0 < len(name) <= 512
              and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", name)
              and all(part not in (".", "..") for part in name.split("/"))
              and type(raw) is bytes, "closed retained paths and complete raw bytes required")
        names.append(name); pairs.append([name, raw])
    _need(names == sorted(set(names)), "sorted unique complete retained byte paths required")
    _bound_tree(pairs, MAX_INPUT_BYTES, allow_bytes=True)
    inventory = [{"path": name, "bytes": len(raw), "sha256": _sha(raw)} for name, raw in pairs]
    return dict(pairs), inventory


def reviewed_norm_preservation_packet_sha256_v2(packet_files, *, instance_identity_profile=None):
    """Commit the complete retained byte inventory, without authenticating it."""
    _reviewed_source_use_kwargs(instance_identity_profile)
    _, inventory = _reviewed_retained_packet(packet_files)
    return _sha(_wire(inventory, MAX_RECORD_BYTES))


def _reviewed_replay_binary_observations(receipt, expected, toolchain, observation_profile, packets):
    _need(type(expected) is dict and len(expected) == 2 and receipt["binary_sha256"] == expected,
          "complete independently pinned compiler identities required")
    for path, digest in expected.items():
        _pin(digest, "retained compiler binary")
        _need(type(path) is str and path.startswith("/") and "\x00" not in path
              and "\\" not in path and all(p not in ("", ".", "..") for p in path[1:].split("/")),
              "canonical retained compiler pathname required")
    if observation_profile == _REVIEWED_REPLAY_FICTIONAL:
        # Preserve the existing authored boundary honestly; never relabel its
        # fake binary/probe interface as a genuine native observation.
        names = {Path(path).name: path for path in expected}
        _need(set(names) == {"synthetic-lake", "synthetic-lean"}
              and len({str(Path(path).parent) for path in expected}) == 1
              and receipt["version_probes"] == {}, "exact fictional compiler boundary required")
        return names["synthetic-lake"]
    names = packets._binary_map(expected)
    probes = receipt["version_probes"]
    _need(type(probes) is dict and set(probes) == {"lake", "lean"}, "complete retained version probes required")
    version = toolchain.rsplit("v", 1)[1]
    for name, probe in probes.items():
        _need(type(probe) is dict and set(probe) == {"command", "returncode", "stdout", "stderr"}
              and probe["command"] == [names[name], "--version"]
              and type(probe["returncode"]) is int and probe["returncode"] == 0
              and type(probe["stdout"]) is str and type(probe["stderr"]) is str
              and re.search(r"\bversion " + re.escape(version) + r"(?:[,\s)])", probe["stdout"]),
              "retained version probe differs from selected toolchain")
    return names["lake"]


def validate_reviewed_norm_preservation_native_receipt_v2(
        receipt_raw, preparation, graph, admission, *args,
        packet_files, expected_receipt_sha256, expected_packet_sha256, expected_binary_sha256,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256,
        toolchain, observation_profile=_REVIEWED_REPLAY_ACTUAL, instance_identity_profile=None, **kwargs):
    """Replay retained observations and current complete semantics without Lean.

    The caller owns physical acquisition and independently trusted receipt,
    packet and compiler pins. Historical PIDs are never inspected. This API
    cannot authenticate original admitted success, validate olean bytes in the
    kernel or authorize release/cache/native/statutory admission. The missing
    original-success adapter remains an explicit prerequisite in every result.
    """
    for value, label in ((expected_receipt_sha256, "retained reviewed receipt"),
                         (expected_packet_sha256, "whole retained reviewed packet")):
        _pin(value, label)
    _bound_tree(expected_binary_sha256, MAX_RECORD_BYTES)
    contents, inventory = _reviewed_retained_packet(packet_files)
    _need(_sha(_wire(inventory, MAX_RECORD_BYTES)) == expected_packet_sha256,
          "independent complete retained packet commitment differs")
    _need(type(receipt_raw) is bytes and 0 < len(receipt_raw) <= MAX_RECEIPT_BYTES
          and _sha(receipt_raw) == expected_receipt_sha256
          and contents.get("build-receipt.json") == receipt_raw,
          "independent original receipt bytes differ")
    receipt = _parse(receipt_raw, MAX_RECEIPT_BYTES)
    _need(reviewed_norm_preservation_receipt_bytes_v2(receipt, **_reviewed_source_use_kwargs(instance_identity_profile)) == receipt_raw,
          "original reviewed receipt must retain its canonical complete bytes")
    _need(type(observation_profile) is str
          and observation_profile in (_REVIEWED_REPLAY_ACTUAL, _REVIEWED_REPLAY_FICTIONAL),
          "explicit supported retained observation profile required")
    if observation_profile == _REVIEWED_REPLAY_FICTIONAL:
        _need(type(admission) is dict and admission.get("fixture_only") is True
              and admission.get("provenance_kind") == "fictional_fixture",
              "fictional interface requires unchanged explicit fictional admission")
    # The existing source/admission/graph/project owner retains all current
    # review, revocation and source replay; no saved eligibility flag replaces it.
    checked = validate_reviewed_norm_preservation_native_v2(preparation, graph, admission, *args,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, **kwargs, **_reviewed_source_use_kwargs(instance_identity_profile))
    owners = _owners(); transport, process = owners[1], owners[3]
    from . import legal_corpus_definition_use_preservation_packet_v2 as packets
    packet_owner_pin = _sha(Path(packets.__file__).read_bytes())
    _need(packet_owner_pin == packets._SELF_PIN, "existing retained-packet validator changed since import")
    manifest = checked.to_dict(); contracts = transport.contracts
    contracts.validate_record(receipt, schema=REVIEWED_PRESERVATION_BUILD_SCHEMA,
        fields=set(receipt) - {"schema", "record_cid", "cid_scope"})
    binding = _reviewed_preservation_receipt_binding(manifest, admission, **_reviewed_source_use_kwargs(instance_identity_profile))
    binding.update(preparation_cid=manifest["record_cid"],
        preparation_full_canonical_sha256=expected_preservation_sha256,
        preparation_manifest_sha256=_sha(checked.manifest_json.encode("utf-8")), toolchain=toolchain,
        expected_modules=manifest["expected_modules"], compiled_modules=manifest["expected_modules"],
        producer_pins=_reviewed_preservation_native_pins(owners, manifest, **_reviewed_source_use_kwargs(instance_identity_profile)),
        conditional_theorems=manifest["preservation_obligations"],
        original_preparation_theorem_assumptions=[], theorem_assumptions=[], scope=_REVIEWED_REPLAY_SCOPE)
    _need(_wire({name: receipt[name] for name in binding}, MAX_RECEIPT_BYTES)
          == _wire(binding, MAX_RECEIPT_BYTES),
          "retained receipt differs from current whole reviewed semantics or producers")
    success_flags = {"backend_executed", "lean_compilation_verified", "proof_checked",
                     "kernel_proofs_checked", "conditional_proofs_verified"}
    for name in PARENT_FALSE_FLAGS:
        _need(receipt[name] is (name in success_flags), "retained authority/profile flag differs: " + name)
    _need(receipt["authority"] == AUTHORITY and all(v is False for v in receipt["authority"].values())
          and type(receipt["training_mask"]) is int and receipt["training_mask"] == 0
          and type(receipt["evaluation_gold_mask"]) is int and receipt["evaluation_gold_mask"] == 0,
          "retained receipt cannot grant authority or training masks")
    for name in ("original_preparation_unchanged", "manifest_coverage_passed", "executed_project_readback_passed",
                 "binaries_unchanged", "post_run_validation_passed", "axiom_observations_passed",
                 "workspace_cleaned", "cleanup_confirmed", "observed_process_scope_passed",
                 "ownership_is_sampled", "build_passed", "native_runtime_verified"):
        _need(receipt[name] is True, "retained successful observation differs: " + name)
    for name in ("timed_out", "cancelled", "unavailable", "output_truncated", "workspace_limit_exceeded",
                 "resource_exhausted", "kernel_containment_attested", "alias_assumption_proved",
                 "source_to_model_equivalence_proved"):
        _need(receipt[name] is False, "retained failure/authority field differs: " + name)
    _need(receipt["reviewed_execution_projection_error"] is None
          and receipt["post_run_validation_error"] is None and receipt["binary_recheck_error"] is None
          and receipt["status"] == "conditional_native_checks_passed"
          and receipt["conditional_kernel_status"] == "checked_under_explicit_hypotheses",
          "retained profile reports an incomplete or failed build")
    sources = {name: body.encode("utf-8") for name, body in checked.files}
    artifacts = [".lake/build/lib/lean/" + name.replace(".", "/") + ".olean"
                 for name in manifest["expected_modules"]]
    wanted = ({"build-receipt.json", "stdout.txt", "stderr.txt", "runner-error.txt",
               "project/" + transport.MANIFEST_FILE}
              | {"project/" + name for name in sources} | {"executed-inputs/" + name for name in sources}
              | {"compiled/" + name.removeprefix(".lake/build/lib/lean/") for name in artifacts})
    _need(set(contents) == wanted
          and contents["project/" + transport.MANIFEST_FILE] == checked.manifest_json.encode("utf-8")
          and all(contents["project/" + name] == contents["executed-inputs/" + name] == raw
                  for name, raw in sources.items()), "complete original project/source packet differs")
    outputs = {**sources, **{name: contents["compiled/" + name.removeprefix(".lake/build/lib/lean/")]
                            for name in artifacts}}
    logs = {name: contents[name] for name in ("stdout.txt", "stderr.txt", "runner-error.txt")}
    invocation, run = _reviewed_native_execution_from_projection(receipt["reviewed_execution_evidence"],
        sources=sources, outputs=outputs, logs=logs, process=process)
    expected_interface = ("synthetic-unit-boundary/v1" if observation_profile == _REVIEWED_REPLAY_FICTIONAL
                          else process.BOUNDED_TOOL_RUNNER_VERSION)
    _need(run.interface_version == expected_interface and run.runtime is process.ToolRuntime.NATIVE
          and invocation.runtime is process.ToolRuntime.NATIVE
          and type(receipt["runtime"]) is str and receipt["runtime"] == run.runtime.value
          and type(run.pid) is int and run.pid > 0 and type(run.returncode) is int and run.returncode == 0
          and run.ok and run.workspace_cleaned and not run.error,
          "retained runner interface or successful typed result differs")
    executable = _reviewed_replay_binary_observations(receipt, expected_binary_sha256,
        toolchain, observation_profile, packets)
    command = (executable, "--offline", "--no-cache", "build", "legal")
    _need(invocation.argv == run.command == command and receipt["command"] == receipt["expected_command"] == list(command)
          and dict(invocation.environment) == {"ELAN_TOOLCHAIN": toolchain, "LEAN_NUM_THREADS": "1"}
          and invocation.output_paths == tuple(artifacts) + tuple(sources),
          "original complete invocation, environment or artifact paths differ")
    from dataclasses import fields
    timeout = invocation.limits.timeout_seconds
    _need(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 60,
          "original bounded compiler timeout required")
    expected_limits = process.ToolRunLimits(timeout_seconds=timeout, cpu_seconds=timeout,
        resident_memory_bytes=2 * 1024**3, max_output_bytes=MAX_CAPTURE_BYTES,
        max_input_bytes=MAX_PROJECT_BYTES, max_workspace_bytes=128 * MAX_RECORD_BYTES,
        max_output_files=len(outputs))
    _need(all(getattr(invocation.limits, f.name) == getattr(expected_limits, f.name)
              and type(getattr(invocation.limits, f.name)) is type(getattr(expected_limits, f.name))
              for f in fields(process.ToolRunLimits)), "original native resource limits differ")
    packets._historical_lifecycle(receipt["native_lifecycle"], run.pid)
    _need(receipt["native_lifecycle"] == run.native_lifecycle.to_dict()
          and receipt["pid"] == run.pid and type(receipt["pid"]) is int
          and receipt["returncode"] == run.returncode and type(receipt["returncode"]) is int
          and type(receipt["process_tree_terminated"]) is bool,
          "historical lifecycle and result bindings differ")
    for name in ("elapsed_seconds", "termination_reason", "timed_out", "cancelled", "unavailable",
                 "output_truncated", "workspace_limit_exceeded", "resource_exhausted",
                 "workspace_cleaned", "process_tree_terminated"):
        _need(type(receipt[name]) is type(getattr(run, name)) and receipt[name] == getattr(run, name),
              "retained runner scalar differs: " + name)
    artifact_hashes = {name: _sha(outputs[name]) for name in artifacts}
    expected_artifacts = {"artifact_sha256": artifact_hashes,
        "artifact_bytes": {name: len(outputs[name]) for name in artifacts},
        "artifact_files": {name: "compiled/" + name.removeprefix(".lake/build/lib/lean/") for name in artifacts},
        "executed_project_sha256": {name: _sha(raw) for name, raw in sources.items()}}
    _need(all(outputs[name] for name in artifacts)
          and _wire({name: receipt[name] for name in expected_artifacts}, MAX_RECEIPT_BYTES)
              == _wire(expected_artifacts, MAX_RECEIPT_BYTES),
          "retained complete source/artifact commitments differ")
    for name, field in (("stdout.txt", "stdout"), ("stderr.txt", "stderr"), ("runner-error.txt", "error")):
        raw = logs[name]
        _need(receipt["log_sha256"][name] == _sha(raw) and type(receipt["log_bytes"][name]) is int
              and receipt["log_bytes"][name] == len(raw)
              and receipt[field] == raw[:MAX_LOG_PREVIEW_BYTES].decode("utf-8", errors="replace").replace("\x00", "\\u0000"),
              "retained complete compiler logs or previews differ")
    _need(set(receipt["log_sha256"]) == set(receipt["log_bytes"]) == set(logs)
          and logs["runner-error.txt"] == b""
          and receipt["receipt_text_truncated"] is any(len(raw) > MAX_LOG_PREVIEW_BYTES for raw in logs.values()),
          "retained diagnostics or truncation frame differs")
    axioms, errors, passed = _axiom_observations(run.stdout, run.stderr,
        {"conditional_theorems": manifest["preservation_obligations"]},
        maximum_theorems=MAX_REVIEWED_PRESERVATION_THEOREMS)
    _need(passed is True and errors == receipt["axiom_observation_errors"] == []
          and axioms == receipt["theorem_axiom_dependencies"],
          "retained exact preservation obligation/axiom reports differ")
    # Recheck current source/review/graph dependencies after the full byte replay.
    validate_reviewed_norm_preservation_native_v2(preparation, graph, admission, *args,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, **kwargs, **_reviewed_source_use_kwargs(instance_identity_profile))
    _need(_sha(Path(packets.__file__).read_bytes()) == packet_owner_pin,
          "retained-packet validator changed during replay")
    return contracts.seal_record({**dict(PARENT_FALSE_FLAGS), "schema": REVIEWED_RECEIPT_REPLAY_SCHEMA,
        "profile": _reviewed_source_use_domain(REVIEWED_RECEIPT_REPLAY_PROFILE, instance_identity_profile),
        **_reviewed_source_use_kwargs(instance_identity_profile), "observation_profile": observation_profile,
        "retained_receipt_sha256": expected_receipt_sha256, "retained_packet_sha256": expected_packet_sha256,
        "preparation_sha256": expected_preservation_sha256, "graph_sha256": expected_graph_sha256,
        "admission_sha256": expected_admission_sha256, "retained_observations_consistent": True,
        "current_complete_semantics_replayed": True, "obligations": list(manifest["preservation_obligations"]),
        "packet_inventory": inventory, "producer_pins": {**_reviewed_preservation_native_pins(owners, manifest, **_reviewed_source_use_kwargs(instance_identity_profile)),
            str(Path(packets.__file__).resolve()): packet_owner_pin},
        "original_success_authenticated": False, "native_execution_authenticated": False,
        "native_execution_performed": False, "olean_kernel_rechecked": False,
        "release_ready": False, "Lean_admitted": False, "training_mask": 0, "evaluation_gold_mask": 0,
        "authority": dict(AUTHORITY), "missing_prerequisites": [
            "Independently trusted original admitted-success custody adapter for this reviewed profile.",
            "Source-matched actual native qualification and reviewed release-native consumer integration."],
        "scope": "Retained observation consistency and current replay only; no historical process, kernel, legal or release authority."})


def load_reviewed_norm_preservation_native_v2(packet_files, preparation, graph, admission, *args, instance_identity_profile=None, **kwargs):
    """Reopen an acquired byte packet; caller owns physical file acquisition.

    No path is opened and no compiler/process is run by this entry. The existing
    replay owners may read their pinned code as part of current-source fencing.
    This returns the same zero-authority observation as the explicit validator.
    """
    contents, _ = _reviewed_retained_packet(packet_files)
    _need("build-receipt.json" in contents, "original complete native receipt required")
    return validate_reviewed_norm_preservation_native_receipt_v2(contents["build-receipt.json"],
        preparation, graph, admission, *args, packet_files=packet_files, **kwargs, **_reviewed_source_use_kwargs(instance_identity_profile))


__all__ += ["REVIEWED_RECEIPT_REPLAY_SCHEMA", "REVIEWED_RECEIPT_REPLAY_PROFILE",
    "reviewed_norm_preservation_receipt_bytes_v2", "reviewed_norm_preservation_packet_sha256_v2",
    "validate_reviewed_norm_preservation_native_receipt_v2", "load_reviewed_norm_preservation_native_v2"]


# This capability authenticates a fresh execution by this native owner. It does
# not authenticate the caller's separate Source/native/storage admission or its
# parent closeout. Python process memory and the standard library are cooperative
# trusted infrastructure; this is not a sandbox against arbitrary Python code.
REVIEWED_LIVE_SUCCESS_SCHEMA = "legal-reviewed-native-live-success/v1"
REVIEWED_LIVE_SUCCESS_PROFILE = "current-reviewed-live-native-owner-success/v1"
REVIEWED_MIXED_LIVE_SUCCESS_SCHEMA = "legal-reviewed-native-live-success/v3"
REVIEWED_MIXED_LIVE_SUCCESS_PROFILE = "current-reviewed-mixed-live-native-owner-success/v3"
_LIVE_SUCCESS_HANDLES = weakref.WeakKeyDictionary()
_LIVE_MODULE_BINDINGS = None
_LIVE_REVIEW_BINDINGS = None
_LIVE_MIXED_REVIEW_BINDINGS = None


class _LiveNativeObserverRefusal(ValueError):
    """Private completed-run refusal whose genuine persistence remains safe."""


class VerifiedReviewedPreservationNativeSuccess:
    """Opaque, nonserializable, process/native-thread-local live build handle.

    Only a fresh successful original native execution can issue one. Saved JSON,
    retained packets, historical receipts and reconstructed instances cannot.
    The handle carries no parent-admission or legal/release authority.
    """

    __slots__ = ("__weakref__",)
    __hash__ = object.__hash__
    __eq__ = object.__eq__

    def __new__(cls):
        raise TypeError("live success handles are issued only by the fresh native builder")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("live success handles cannot be subclassed")

    def __reduce_ex__(self, protocol):
        raise TypeError("live success handles cannot be copied or serialized")

    def __repr__(self):
        return "<VerifiedReviewedPreservationNativeSuccess>"


def _live_callable_state(function):
    return (function, function.__code__, function.__defaults__,
            tuple(sorted((function.__kwdefaults__ or {}).items())))


def _live_callable_matches(function, state):
    if (type(function) is not types.FunctionType or function is not state[0]
            or function.__code__ is not state[1] or function.__defaults__ is not state[2]):
        return False
    current = function.__kwdefaults__ or {}
    return (set(current) == {key for key, _ in state[3]}
            and all(current[key] is value for key, value in state[3]))


def _live_descriptor_function(descriptor):
    if type(descriptor) in (staticmethod, classmethod):
        return descriptor.__func__
    if type(descriptor) is property:
        return descriptor.fget
    return descriptor


def _live_compiled_module_bindings(module):
    """Verify source function origin before lazily accepting runtime identities.

    Comparing a fresh nested code map prevents first-use monkeypatches from
    becoming the baseline. Dataclass-generated methods are identity/code/default
    fenced together with the source-declared class methods after that check.
    No imported source is executed by this provenance operation.
    """
    _need(type(module) is types.ModuleType and sys.modules.get(module.__name__) is module,
          "live success callable bindings changed: canonical owner module required")
    filename = str(Path(module.__file__).resolve())
    raw = Path(filename).read_bytes()
    tree = ast.parse(raw, filename=filename)
    compiled = compile(raw, filename, "exec", dont_inherit=True, optimize=sys.flags.optimize)
    codes = {}

    def walk(code):
        codes[code.co_qualname] = code
        for constant in code.co_consts:
            if type(constant) is types.CodeType:
                walk(constant)

    walk(compiled)
    functions, classes = [], []

    def source_function(name, function):
        expected = codes.get(name)
        _need(type(function) is types.FunctionType and expected is not None
              and function.__code__ == expected and function.__globals__ is vars(module)
              and function.__module__ == module.__name__ and function.__qualname__ == name,
              "live success callable bindings changed: source origin " + name)

    for node in tree.body:
        if type(node) in (ast.FunctionDef, ast.AsyncFunctionDef):
            function = vars(module).get(node.name)
            source_function(node.name, function)
            functions.append((None, node.name, _live_callable_state(function)))
        elif type(node) is ast.ClassDef:
            owner = vars(module).get(node.name)
            _need(isinstance(owner, type) and owner.__module__ == module.__name__
                  and owner.__qualname__ == node.name,
                  "live success callable bindings changed: source class " + node.name)
            declared = {child.name for child in node.body
                        if type(child) in (ast.FunctionDef, ast.AsyncFunctionDef)}
            # A lazy baseline must never bless a newly supplied lookup hook.
            # Dataclasses generate equality/initialization/frozen setters, but
            # do not generate attribute-lookup or descriptor-control hooks.
            forbidden = {"__getattribute__", "__getattr__", "__call__", "__get__", "__set__", "__delete__"}
            _need(not ((set(vars(owner)) & forbidden) - declared),
                  "live success callable bindings changed: undeclared class lookup " + node.name)
            if module.__name__ == "ipfs_datasets_py.logic.backends.process" and node.name in (
                    "BoundedToolRunner", "SubprocessExecutor"):
                _need(type(owner) is type and owner.__bases__ == (object,)
                      and owner.__getattribute__ is object.__getattribute__
                      and owner.__new__ is object.__new__
                      and owner.__setattr__ is object.__setattr__
                      and owner.__delattr__ is object.__delattr__
                      and not hasattr(owner, "__getattr__"),
                      "live success callable bindings changed: original runner class lookup")
            classes.append((node.name, owner, type(owner), owner.__bases__, frozenset(vars(owner))))
            for child in node.body:
                if type(child) in (ast.FunctionDef, ast.AsyncFunctionDef):
                    function = _live_descriptor_function(vars(owner).get(child.name))
                    source_function(node.name + "." + child.name, function)
            for name, descriptor in vars(owner).items():
                function = _live_descriptor_function(descriptor)
                if type(function) is types.FunctionType:
                    functions.append((owner, name, _live_callable_state(function)))
    return (module, filename, _sha(raw), tuple(classes), tuple(functions))


def _live_check_module_bindings(snapshot, *, skip=()):
    module, filename, digest, classes, functions = snapshot
    _need(sys.modules.get(module.__name__) is module and str(Path(module.__file__).resolve()) == filename
          and _sha(Path(filename).read_bytes()) == digest,
          "live success callable bindings changed: owner source")
    for name, owner, metaclass, bases, keys in classes:
        _need(vars(module).get(name) is owner and type(owner) is metaclass
              and owner.__bases__ is bases and frozenset(vars(owner)) == keys,
              "live success callable bindings changed: owner class " + name)
    for owner, name, state in functions:
        if owner is not None and (owner.__name__, name) in skip:
            continue
        current = vars(module).get(name) if owner is None else _live_descriptor_function(vars(owner).get(name))
        _need(_live_callable_matches(current, state),
              "live success callable bindings changed: owner function " + name)


def _live_success_guard(owners=None, *, reviewed_version=2):
    """Fence code identity, not caller-provided success booleans or callbacks."""
    global _LIVE_MODULE_BINDINGS, _LIVE_REVIEW_BINDINGS, _LIVE_MIXED_REVIEW_BINDINGS
    _need(type(reviewed_version) is int and reviewed_version in (2, 3, 4, 5),
          "explicit closed live guard version required")
    for name, state in _LIVE_NATIVE_FUNCTIONS:
        _need(_live_callable_matches(globals().get(name), state),
              "live success callable bindings changed: native function " + name)
    for name, state in _LIVE_HANDLE_FUNCTIONS:
        _need(_live_callable_matches(_live_descriptor_function(
            vars(VerifiedReviewedPreservationNativeSuccess).get(name)), state),
            "live success callable bindings changed: opaque handle")
    _need(VerifiedReviewedPreservationNativeSuccess is _LIVE_HANDLE_CLASS
          and type(_LIVE_HANDLE_CLASS) is _LIVE_HANDLE_METACLASS
          and _LIVE_HANDLE_CLASS.__bases__ is _LIVE_HANDLE_BASES
          and frozenset(vars(_LIVE_HANDLE_CLASS)) == _LIVE_HANDLE_KEYS
          and vars(_LIVE_HANDLE_CLASS).get("__hash__") is object.__hash__
          and vars(_LIVE_HANDLE_CLASS).get("__eq__") is object.__eq__
          and subprocess.Popen is _LIVE_POPEN_CLASS
          and type(_LIVE_POPEN_CLASS) is _LIVE_POPEN_METACLASS
          and _LIVE_POPEN_CLASS.__bases__ is _LIVE_POPEN_BASES
          and frozenset(vars(_LIVE_POPEN_CLASS)) == _LIVE_POPEN_KEYS,
          "live success callable bindings changed: native class")
    for name, state in _LIVE_POPEN_FUNCTIONS:
        _need(_live_callable_matches(_live_descriptor_function(vars(subprocess.Popen).get(name)), state),
              "live success callable bindings changed: stdlib Popen " + name)
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "live success callable bindings changed: native source")
    canonical_name = "ipfs_datasets_py.logic.autoformal.legal_corpus_definition_use_native_v2"
    canonical = sys.modules.get(canonical_name)
    _need(__name__ == canonical_name and type(canonical) is types.ModuleType
          and vars(canonical) is globals(),
          "live success callable bindings changed: canonical native owner required")
    if owners is not None:
        _need(type(owners) is tuple and len(owners) == 5
              and owners[3].__name__ == "ipfs_datasets_py.logic.backends.process",
              "live success callable bindings changed: exact execution owner")
        _need(Path(__file__).resolve() == Path(owners[4].__file__).resolve().with_name(
                  "legal_corpus_definition_use_native_v2.py"),
              "live success callable bindings changed: canonical native source path required")
        if _LIVE_MODULE_BINDINGS is None:
            candidate = tuple(_live_compiled_module_bindings(module) for module in owners)
            for snapshot in candidate:
                _live_check_module_bindings(snapshot)
            _LIVE_MODULE_BINDINGS = candidate
        _need(all(owners[index] is state[0] for index, state in enumerate(_LIVE_MODULE_BINDINGS)),
              "live success callable bindings changed: execution owner identity")
        for snapshot in _LIVE_MODULE_BINDINGS:
            _live_check_module_bindings(snapshot)
        direct, admission_owner = _live_review_components(owners, reviewed_version)
        bindings = _LIVE_REVIEW_BINDINGS if reviewed_version == 2 else _LIVE_MIXED_REVIEW_BINDINGS
        if bindings is None:
            first = tuple(_live_compiled_module_bindings(module) for module in direct)
            # Check source origins before nested current-review callbacks run.
            nested = (*admission_owner._reviewed_owners(), *admission_owner.norm._owners())
            extra = tuple(module for index, module in enumerate(nested)
                          if module not in direct and module not in nested[:index])
            bindings = (first, tuple(_live_compiled_module_bindings(module) for module in extra))
            if reviewed_version == 2:
                _LIVE_REVIEW_BINDINGS = bindings
            else:
                _LIVE_MIXED_REVIEW_BINDINGS = bindings
        first, extra = bindings
        _need(tuple(state[0] for state in first) == direct,
              "live success callable bindings changed: current review owners")
        for snapshot in (*first, *extra):
            _live_check_module_bindings(snapshot)
        nested = (*admission_owner._reviewed_owners(), *admission_owner.norm._owners())
        _need(all(module in direct or any(module is state[0] for state in extra) for module in nested),
              "live success callable bindings changed: nested current review owners")


def _live_postrun_persistence_trusted(owners, *, reviewed_version=2):
    """Allow evidence retention only through still-original remaining owners."""
    try:
        _need(type(reviewed_version) is int and reviewed_version in (2, 3, 4, 5), "closed live persistence version required")
        bindings = _LIVE_REVIEW_BINDINGS if reviewed_version == 2 else _LIVE_MIXED_REVIEW_BINDINGS
        for name, state in _LIVE_NATIVE_FUNCTIONS:
            _need(_live_callable_matches(globals().get(name), state),
                  "live success callable bindings changed: post-run persistence")
        _need(_LIVE_MODULE_BINDINGS is not None and bindings is not None,
              "live success original persistence bindings required")
        for index, snapshot in enumerate(_LIVE_MODULE_BINDINGS):
            _need(owners[index] is snapshot[0], "live success original persistence owner required")
            _live_check_module_bindings(snapshot, skip=(
                (("BoundedToolRunner", "run"), ("SubprocessExecutor", "execute")) if index == 3 else ()))
        first, extra = bindings
        for snapshot in (*first, *extra):
            _live_check_module_bindings(snapshot)
        return True
    except (ValueError, TypeError, OSError, KeyError, AttributeError):
        return False


def _live_freeze_inputs(value):
    """Detach the entire ordinary current-review tree, retaining byte bodies."""
    remaining, nodes = MAX_INPUT_BYTES + MAX_PREPARATION_BYTES, 2_000_000

    def freeze(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 64, "bounded live success original inputs required")
        if type(item) is dict:
            _need(all(type(key) is str for key in item), "ordinary live success input keys required")
            result = ("dict", tuple((freeze(key, depth + 1), freeze(item[key], depth + 1))
                                    for key in sorted(item)))
            remaining -= 2 + 2 * len(item)
        elif type(item) in (tuple, list):
            result = ("tuple" if type(item) is tuple else "list",
                      tuple(freeze(child, depth + 1) for child in item))
            remaining -= 2 + len(item)
        elif type(item) in (str, bytes):
            raw = item.encode("utf-8") if type(item) is str else item
            remaining -= len(raw) + 2
            result = ("str" if type(item) is str else "bytes", raw)
        elif item is None or type(item) in (bool, int):
            remaining -= 24
            result = (type(item).__name__, item)
        elif type(item) is float and math.isfinite(item):
            remaining -= 32
            result = ("float", item.hex())
        else:
            raise ValueError("ordinary detached live success original inputs required")
        _need(remaining >= 0, "complete live success original input byte bound exceeded")
        return result

    return freeze(value, 0)


def _live_original_inputs(preparation, graph, admission, args, kwargs, *,
        realization_preservation=None, expected_upstream_preservation_sha256=None, definition_application_profile=None,
        physical_request_raw=None, expected_physical_request_sha256=None):
    original = (_reviewed_preservation_native_document(preparation), graph, admission, args, kwargs)
    if realization_preservation is not None:
        _pin(expected_upstream_preservation_sha256, "complete original realization upstream")
        original = (*original, _reviewed_preservation_native_document(realization_preservation),
                    expected_upstream_preservation_sha256)
    if _reviewed_definition_application_kwargs(definition_application_profile):
        original = (*original, definition_application_profile)
    _need((physical_request_raw is None) == (expected_physical_request_sha256 is None),
          "physical request bytes and independent pin must be paired")
    if physical_request_raw is not None:
        _pin(expected_physical_request_sha256, "complete original physical request")
        _need(type(physical_request_raw) is bytes and 0 < len(physical_request_raw) <= MAX_INPUT_BYTES
              and _sha(physical_request_raw) == expected_physical_request_sha256,
              "complete original physical request bytes differ")
        original = (*original, physical_request_raw, expected_physical_request_sha256)
    return _live_freeze_inputs(original)


def _live_read_persisted_packet(output, checked, receipt, transport, *, reviewed_version=2, instance_identity_profile=None, definition_application_profile=None):
    """Reopen the closed original packet through existing no-follow readers."""
    output = transport._path(output)
    transport._check_directories(output)
    root_fd = os.open(output, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    leaf_names = {"build-receipt.json", "stdout.txt", "stderr.txt", "runner-error.txt"}
    wanted = leaf_names | {"project", "compiled", "executed-inputs"}
    contents = {}
    try:
        transport._check_directories(output, root_fd)
        with os.scandir(root_fd) as entries:
            observed = set()
            for entry in entries:
                _need(not entry.is_symlink() and entry.name in wanted,
                      "complete ordinary live success packet required")
                observed.add(entry.name)
        _need(observed == wanted, "complete original persisted live success packet required")
        for name in sorted(leaf_names):
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root_fd)
            with os.fdopen(descriptor, "rb") as source:
                before = os.fstat(source.fileno())
                _need(stat.S_ISREG(before.st_mode) and before.st_size <= (8 * 1024**2 if reviewed_version == 5 else 3 * MAX_CAPTURE_BYTES),
                      "bounded ordinary live success packet file required")
                raw = source.read((8 * 1024**2 if reviewed_version == 5 else 3 * MAX_CAPTURE_BYTES) + 1)
                after = os.fstat(source.fileno())
                current = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
                _need(transport._stable_stat(before) == transport._stable_stat(after)
                      == transport._stable_stat(current) and len(raw) == before.st_size,
                      "live success packet changed during readback")
                contents[name] = raw
        sources = {name for name, _ in checked.files}
        compiled = {name.removeprefix("compiled/") for name in receipt["artifact_files"].values()}
        for directory, names, maximum in (
                ("project", sources | {transport.MANIFEST_FILE}, MAX_REVIEWED_PRESERVATION_FILES + 1),
                ("executed-inputs", sources, MAX_REVIEWED_PRESERVATION_FILES),
                ("compiled", compiled, MAX_REVIEWED_PRESERVATION_MODULES)):
            files = transport._read_files(output / directory, names, maximum_files=maximum)
            contents.update((directory + "/" + name, raw) for name, raw in files.items())
        transport._check_directories(output, root_fd)
    finally:
        os.close(root_fd)
    packet = tuple(sorted(contents.items()))
    (_reviewed_physical_retained_packet_v2 if reviewed_version == 5 else _reviewed_retained_packet)(packet)
    _need(contents["build-receipt.json"] == _live_success_domain(reviewed_version, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))[9](receipt, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)),
          "persisted live success receipt differs from original returned receipt")
    return packet


def _live_handle_entry(handle, *, reviewed_version=2, instance_identity_profile=None, definition_application_profile=None):
    _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)
    _need(type(reviewed_version) is int and reviewed_version in (2, 3, 4, 5),
          "explicit closed live handle version required")
    _need(definition_application_profile is None or reviewed_version in (4, 5),
          "whole-norm application requires an explicit realization live handle")
    if reviewed_version == 5:
        _need(instance_identity_profile == "reviewed-source-use/v1"
              and definition_application_profile == "whole-norm-definition-expansion/v1",
              "physical live handle requires fixed joint source-use whole-norm profiles")
    # This check intentionally precedes every owner import and preparation read.
    _need(type(handle) is _LIVE_HANDLE_CLASS
          and VerifiedReviewedPreservationNativeSuccess is _LIVE_HANDLE_CLASS
          and type(_LIVE_HANDLE_CLASS) is _LIVE_HANDLE_METACLASS
          and _LIVE_HANDLE_CLASS.__bases__ is _LIVE_HANDLE_BASES
          and frozenset(vars(_LIVE_HANDLE_CLASS)) == _LIVE_HANDLE_KEYS
          and vars(_LIVE_HANDLE_CLASS).get("__hash__") is object.__hash__
          and vars(_LIVE_HANDLE_CLASS).get("__eq__") is object.__eq__,
          "live success handle was not issued by this process and native thread")
    entry = _LIVE_SUCCESS_HANDLES.get(handle)
    _need(type(entry) is tuple and len(entry) == 9 + int(instance_identity_profile is not None) + int(definition_application_profile is not None) and type(entry[8]) is int
          and entry[8] == reviewed_version
          and (instance_identity_profile is None or entry[9] == instance_identity_profile)
          and (definition_application_profile is None or entry[9 + int(instance_identity_profile is not None)] == definition_application_profile) and entry[0] == os.getpid() and entry[1] == threading.get_native_id()
          and entry[6]() is threading.current_thread() and entry[7]() is handle,
          "live success handle was not issued by this process and native thread")
    return entry


def _live_success_domain(reviewed_version, *, instance_identity_profile=None, definition_application_profile=None):
    """Select one closed literal domain after the independent callable fence."""
    _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)
    _need(type(reviewed_version) is int and reviewed_version in (2, 3, 4, 5),
          "explicit closed live success version required")
    _need(type(PARENT_FALSE_FLAGS) is dict and set(PARENT_FALSE_FLAGS) == _REVIEWED_MIXED_FALSE_KEYS
          and all(value is False for value in PARENT_FALSE_FLAGS.values())
          and type(AUTHORITY) is dict and set(AUTHORITY) == _REVIEWED_MIXED_AUTHORITY_KEYS
          and all(value is False for value in AUTHORITY.values()),
          "live success cannot widen its closed false-authority policy")
    _need(definition_application_profile is None or reviewed_version in (4, 5),
          "whole-norm application requires the explicit realization live domain")
    if reviewed_version == 5:
        _reviewed_physical_definition_realization_native_policy(instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)
        return (REVIEWED_PHYSICAL_DEFINITION_REALIZATION_BUILD_SCHEMA,
            _reviewed_realization_domain(REVIEWED_PHYSICAL_DEFINITION_REALIZATION_NATIVE_PROFILE, instance_identity_profile, definition_application_profile),
            REVIEWED_PHYSICAL_DEFINITION_REALIZATION_LIVE_SUCCESS_SCHEMA,
            _reviewed_realization_domain(REVIEWED_PHYSICAL_DEFINITION_REALIZATION_LIVE_SUCCESS_PROFILE, instance_identity_profile, definition_application_profile),
            _reviewed_physical_definition_realization_receipt_binding, _reviewed_physical_definition_realization_native_pins,
            reviewed_physical_definition_realization_packet_sha256_v2, _reviewed_physical_definition_realization_load_adapter,
            _reviewed_physical_definition_realization_validate_adapter, reviewed_physical_definition_realization_receipt_bytes_v2,
            _reviewed_definition_realization_scope(definition_application_profile))
    if reviewed_version == 4:
        _reviewed_definition_realization_native_policy(**_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
        return (REVIEWED_DEFINITION_REALIZATION_BUILD_SCHEMA, _reviewed_realization_domain(REVIEWED_DEFINITION_REALIZATION_NATIVE_PROFILE, instance_identity_profile, definition_application_profile),
            REVIEWED_DEFINITION_REALIZATION_LIVE_SUCCESS_SCHEMA, _reviewed_realization_domain(REVIEWED_DEFINITION_REALIZATION_LIVE_SUCCESS_PROFILE, instance_identity_profile, definition_application_profile),
            _reviewed_definition_realization_receipt_binding, _reviewed_definition_realization_native_pins,
            reviewed_definition_realization_packet_sha256_v1, _reviewed_definition_realization_load_adapter,
            _reviewed_definition_realization_validate_adapter, reviewed_definition_realization_receipt_bytes_v1,
            _reviewed_definition_realization_scope(definition_application_profile))
    if reviewed_version == 2:
        _need((REVIEWED_PRESERVATION_BUILD_SCHEMA, REVIEWED_PRESERVATION_NATIVE_PROFILE,
               REVIEWED_LIVE_SUCCESS_SCHEMA, REVIEWED_LIVE_SUCCESS_PROFILE) == (
            "legal-corpus-reviewed-preservation-native-build/v2",
            "replayed-reviewed-multiunit-preservation-native-build/v2",
            "legal-reviewed-native-live-success/v1", "current-reviewed-live-native-owner-success/v1"),
            "closed Object live success domain cannot alias another profile")
        return ("legal-corpus-reviewed-preservation-native-build/v2",
            _reviewed_source_use_domain("replayed-reviewed-multiunit-preservation-native-build/v2", instance_identity_profile),
            "legal-reviewed-native-live-success/v1", _reviewed_source_use_domain("current-reviewed-live-native-owner-success/v1", instance_identity_profile),
            _reviewed_preservation_receipt_binding, _reviewed_preservation_native_pins,
            reviewed_norm_preservation_packet_sha256_v2, load_reviewed_norm_preservation_native_v2,
            validate_reviewed_norm_preservation_native_v2, reviewed_norm_preservation_receipt_bytes_v2,
            _REVIEWED_REPLAY_SCOPE)
    _reviewed_mixed_native_policy(**_reviewed_source_use_kwargs(instance_identity_profile))
    _need((REVIEWED_MIXED_LIVE_SUCCESS_SCHEMA, REVIEWED_MIXED_LIVE_SUCCESS_PROFILE) == (
        "legal-reviewed-native-live-success/v3", "current-reviewed-mixed-live-native-owner-success/v3"),
        "closed mixed live success domain cannot alias another profile")
    return ("legal-corpus-reviewed-preservation-native-build/v3",
        _reviewed_source_use_domain("replayed-reviewed-mixed-multiunit-preservation-native-build/v3", instance_identity_profile),
        "legal-reviewed-native-live-success/v3", _reviewed_source_use_domain("current-reviewed-mixed-live-native-owner-success/v3", instance_identity_profile),
        _reviewed_mixed_preservation_receipt_binding, _reviewed_mixed_preservation_native_pins,
        reviewed_norm_preservation_packet_sha256_v3, load_reviewed_norm_preservation_native_v3,
        validate_reviewed_norm_preservation_native_v3, reviewed_norm_preservation_receipt_bytes_v3,
        _REVIEWED_MIXED_SCOPE)


def _live_review_components(owners, reviewed_version):
    """Retain the existing V2 owners and the explicit V3 legacy-alias closure."""
    _need(type(reviewed_version) is int and reviewed_version in (2, 3, 4, 5),
          "explicit closed live review version required")
    if reviewed_version == 2:
        graph, admission, preservation = owners[4]._reviewed_preservation_owners()
        return ((graph, admission, preservation, admission.norm, admission.content, admission.reader),
                admission)
    graph, admission, preservation = owners[4]._reviewed_mixed_preservation_owners()
    _need(type(admission) is types.ModuleType, "original mixed review module required")
    legacy = vars(admission).get("legacy")
    _need(type(legacy) is types.ModuleType and vars(admission).get("norm") is vars(legacy).get("norm"),
          "mixed live review alias bindings changed")
    for name in ("_need", "_keys", "_sha", "_auth", "_reviewed_refs", "_distinct_pair",
                 "_reviewed_owners", "norm_content_adjudication_sha256"):
        _need(vars(admission).get(name) is vars(legacy).get(name),
              "mixed live review alias bindings changed: " + name)
    for name in ("_need", "_keys", "_sha"):
        _need(vars(legacy).get(name) is vars(legacy.norm).get(name),
              "mixed live legacy predicate binding changed: " + name)
    return ((graph, admission, preservation, legacy, legacy.norm, legacy.content, legacy.reader), legacy)


def _build_verified_reviewed_norm_preservation_native(preparation, graph, admission, *args,
        _live_integrity_state, reviewed_version, expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256,
        toolchain, lake_executable, output_directory, timeout_seconds=60, cancellation=None, instance_identity_profile=None, definition_application_profile=None,
        realization_preservation=None, expected_upstream_preservation_sha256=None,
        physical_request_raw=None, expected_physical_request_sha256=None, **kwargs):
    """Issue an opaque handle after one fresh default native build and replay.

    Existing Source/native/storage admission remains with the original caller.
    Historical packets and caller-authored ToolRunResults cannot issue handles.
    No fixture executor, runner, toolchain or persistence injection is accepted.
    """

    _need(reviewed_version == 5 or physical_request_raw is expected_physical_request_sha256 is None,
          "physical request requires the explicit physical realization live domain")
    domain_arguments = ({} if reviewed_version not in (4, 5) else {
        "realization_preservation": realization_preservation,
        "expected_upstream_preservation_sha256": expected_upstream_preservation_sha256})
    if reviewed_version == 5:
        domain_arguments.update(physical_request_raw=physical_request_raw,
            expected_physical_request_sha256=expected_physical_request_sha256)
    (integrity_function, integrity_code, integrity_defaults,
     integrity_keywords, persistence_state) = _live_integrity_state

    def integrity_fence(owners=None):
        # The required private bundle comes from a lexical public entry, never
        # an admission keyword or a mutable global checker lookup.
        if (integrity_function.__code__ is not integrity_code
                or integrity_function.__defaults__ is not integrity_defaults
                or set(integrity_function.__kwdefaults__ or {}) != {key for key, _ in integrity_keywords}
                or not all((integrity_function.__kwdefaults__ or {})[key] is value
                           for key, value in integrity_keywords)):
            raise ValueError("live success callable bindings changed: captured core integrity")
        return integrity_function(owners, reviewed_version=reviewed_version)

    def persistence_trusted(owners):
        function, code, defaults, keywords = persistence_state
        if (globals().get("_live_postrun_persistence_trusted") is not function
                or function.__code__ is not code or function.__defaults__ is not defaults
                or set(function.__kwdefaults__ or {}) != {key for key, _ in keywords}
                or not all((function.__kwdefaults__ or {})[key] is value
                           for key, value in keywords)):
            return False
        return function(owners, reviewed_version=reviewed_version)

    _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
          and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")
    integrity_fence()
    domain = _live_success_domain(reviewed_version, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    (build_schema, native_profile, live_schema, live_profile, receipt_binding, pin_reader,
     packet_hasher, retained_loader, validator, formatter, receipt_scope) = domain
    authority_snapshot = dict(AUTHORITY)
    original = _live_original_inputs(preparation, graph, admission, args, kwargs, **domain_arguments,
        **_reviewed_definition_application_kwargs(definition_application_profile))
    owners = _owners()
    integrity_fence(owners)
    process = owners[3]
    observed = {}

    def fence():
        integrity_fence(owners)
        _need(_live_success_domain(reviewed_version, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)) == domain, "live success domain changed during build")
        _need(_live_original_inputs(preparation, graph, admission, args, kwargs, **domain_arguments,
            **_reviewed_definition_application_kwargs(definition_application_profile)) == original,
              "live success original inputs changed during build")

    def execution(stage, values):
        try:
            fence()
        except (ValueError, TypeError, OSError) as error:
            if stage == "after" and persistence_trusted(owners):
                raise _LiveNativeObserverRefusal(str(error)) from error
            error.add_note("No live success handle issued; remaining native persistence owners were not trusted.")
            raise
        runner, invocation = values["runner"], values["invocation"]
        _need(values["process"] is process and type(runner) is process.BoundedToolRunner
              and runner._default_executor is True
              and type(runner._executor) is process.SubprocessExecutor
              and runner._executor._popen is _LIVE_POPEN_CLASS
              and runner._executor._clock is process.time.monotonic
              and set(vars(runner)) == {"_default_executor", "_executor", "_workspace_root",
                                      "_base_environment", "_executable_roots"}
              and set(vars(runner._executor)) == {"_popen", "_clock", "_poll_interval_seconds"}
              and type(invocation) is process.ToolRunRequest and invocation.owned_process_observation is True,
              "original default live success native execution required")
        if stage == "before":
            _need(not observed, "single original live success native invocation required")
            observed.update(runner=runner, invocation=invocation)
        else:
            _need(stage == "after" and observed.get("runner") is runner
                  and observed.get("invocation") is invocation and "projection" not in observed
                  and type(values["run"]) is process.ToolRunResult,
                  "same original live success native invocation/result required")
            observed["projection"] = _wire(_reviewed_native_execution_projection(
                invocation, values["run"], process, physical_realization=reviewed_version == 5), MAX_RECEIPT_BYTES)

    def execute(checked, replay, custody):
        integrity_fence(owners)
        refusal = None

        def guard(stage, values):
            nonlocal refusal
            integrity_fence(owners)
            result = custody(stage, values)
            try:
                fence()
            except (ValueError, TypeError, OSError) as error:
                if stage in ("snapshot", "toolchain") or not persistence_trusted(owners):
                    error.add_note("No live success handle issued; untrusted remaining persistence was not invoked.")
                    raise
                refusal = {"type": type(error).__name__, "message": str(error)[:2048]}
                if stage == "after_persistence":
                    error.add_note("Completed original native observations retained as a failed receipt at "
                                   + str(values["output"]) + "; no live success handle issued.")
                    raise
            return (refusal or result) if stage == "before_persistence" else result

        receipt = _build_validated_native(preparation, checked, replay=replay,
            expected_preparation_sha256=expected_preservation_sha256, toolchain=toolchain,
            lake_executable=lake_executable, output_directory=output_directory,
            timeout_seconds=timeout_seconds, cancellation=cancellation,
            build_schema=build_schema, profile=native_profile,
            flags=dict(PARENT_FALSE_FLAGS),
            receipt_binding=lambda manifest: receipt_binding(manifest, admission, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)),
            maximum_files=MAX_REVIEWED_PRESERVATION_FILES,
            maximum_modules=MAX_REVIEWED_PRESERVATION_MODULES,
            maximum_theorems=MAX_REVIEWED_PRESERVATION_THEOREMS,
            producer_pin_reader=(pin_reader if not _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile) else
                lambda owners, manifest: pin_reader(owners, manifest, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))),
            preparation_document_reader=_reviewed_preservation_native_document,
            closing_custody_guard=guard, execution_observer=execution, receipt_scope=receipt_scope,
            frozen_authority=authority_snapshot, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
        fence()
        _need(receipt["build_passed"] is True and "projection" in observed
              and _wire(receipt["reviewed_execution_evidence"], MAX_RECEIPT_BYTES) == observed["projection"],
              "successful original live native execution required")
        packet = _live_read_persisted_packet(output_directory, checked, receipt, owners[1],
                                            reviewed_version=reviewed_version, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
        receipt_hash = _sha(dict(packet)["build-receipt.json"])
        packet_hash = packet_hasher(packet, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
        old = retained_loader(packet, preparation, graph, admission, *args,
            expected_receipt_sha256=receipt_hash, expected_packet_sha256=packet_hash,
            expected_binary_sha256=receipt["binary_sha256"],
            expected_preservation_sha256=expected_preservation_sha256,
            expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
            toolchain=toolchain, **domain_arguments, **kwargs, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
        fence()
        _need(old["retained_observations_consistent"] is True
              and old["current_complete_semantics_replayed"] is True
              and _binary_recheck(receipt["binary_sha256"]),
              "original live success closing replay or compiler custody differs")
        joins = _live_freeze_inputs((reviewed_version, expected_preservation_sha256, expected_graph_sha256,
            expected_admission_sha256, toolchain, receipt["binary_sha256"],
            old["producer_pins"], receipt_hash, packet_hash))
        return packet, joins, observed["projection"]

    packet, joins, projection = _reviewed_preservation_native_operation(
        preparation, graph, admission, args, kwargs,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, operation=execute, reviewed_version=reviewed_version, **domain_arguments,
        **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    # The existing after-persistence custody and final outer semantic fence have
    # finished before any capability is inserted into the issuance registry.
    fence()
    handle = object.__new__(VerifiedReviewedPreservationNativeSuccess)
    entry = (os.getpid(), threading.get_native_id(), packet, joins, projection, original,
             weakref.ref(threading.current_thread()), weakref.ref(handle), reviewed_version)
    if instance_identity_profile is not None:
        entry = (*entry, instance_identity_profile)
    if definition_application_profile is not None:
        entry = (*entry, definition_application_profile)
    _LIVE_SUCCESS_HANDLES[handle] = entry
    # A return-hook mutation cannot leave an issued handle after our last check.
    try:
        fence()
    except BaseException:
        _LIVE_SUCCESS_HANDLES.pop(handle, None)
        raise
    return handle


def _load_verified_reviewed_norm_preservation_native(handle, packet_files, preparation, graph, admission, *args,
        _live_integrity_state, reviewed_version, expected_receipt_sha256, expected_packet_sha256, expected_binary_sha256,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain, instance_identity_profile=None, definition_application_profile=None,
        realization_preservation=None, expected_upstream_preservation_sha256=None,
        physical_request_raw=None, expected_physical_request_sha256=None, **kwargs):
    """Join this process's live issuance to exact bytes and current review state.

    Reads invoke no compiler, executable, cleanup action or historical PID probe.
    Parent admitted-success custody, legal admission and release remain absent.
    """

    _need(reviewed_version == 5 or physical_request_raw is expected_physical_request_sha256 is None,
          "physical request requires the explicit physical realization live domain")
    domain_arguments = ({} if reviewed_version not in (4, 5) else {
        "realization_preservation": realization_preservation,
        "expected_upstream_preservation_sha256": expected_upstream_preservation_sha256})
    if reviewed_version == 5:
        domain_arguments.update(physical_request_raw=physical_request_raw,
            expected_physical_request_sha256=expected_physical_request_sha256)
    (integrity_function, integrity_code, integrity_defaults,
     integrity_keywords, persistence_state) = _live_integrity_state

    def integrity_fence(owners=None):
        # The required private bundle comes from a lexical public entry, never
        # an admission keyword or a mutable global checker lookup.
        if (integrity_function.__code__ is not integrity_code
                or integrity_function.__defaults__ is not integrity_defaults
                or set(integrity_function.__kwdefaults__ or {}) != {key for key, _ in integrity_keywords}
                or not all((integrity_function.__kwdefaults__ or {})[key] is value
                           for key, value in integrity_keywords)):
            raise ValueError("live success callable bindings changed: captured core integrity")
        return integrity_function(owners, reviewed_version=reviewed_version)

    def persistence_trusted(owners):
        function, code, defaults, keywords = persistence_state
        if (globals().get("_live_postrun_persistence_trusted") is not function
                or function.__code__ is not code or function.__defaults__ is not defaults
                or set(function.__kwdefaults__ or {}) != {key for key, _ in keywords}
                or not all((function.__kwdefaults__ or {})[key] is value
                           for key, value in keywords)):
            return False
        return function(owners, reviewed_version=reviewed_version)

    integrity_fence()
    entry = _live_handle_entry(handle, reviewed_version=reviewed_version, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    integrity_fence()
    domain = _live_success_domain(reviewed_version, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    (build_schema, native_profile, live_schema, live_profile, receipt_binding, pin_reader,
     packet_hasher, retained_loader, validator, formatter, receipt_scope) = domain
    authority_snapshot = dict(AUTHORITY)
    contents, _ = (_reviewed_physical_retained_packet_v2 if reviewed_version == 5 else _reviewed_retained_packet)(packet_files)
    packet = tuple(sorted(contents.items()))
    _need(packet == entry[2], "exact issued live success packet required")
    original = _live_original_inputs(preparation, graph, admission, args, kwargs, **domain_arguments,
        **_reviewed_definition_application_kwargs(definition_application_profile))
    _need(original == entry[5], "exact issued live success original inputs required")
    owners = _owners()
    integrity_fence(owners)

    def fence():
        _need(_live_success_domain(reviewed_version, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)) == domain, "live success domain changed during read")
        _need(_live_handle_entry(handle, reviewed_version=reviewed_version, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)) is entry,
              "same issued live success handle required")
        integrity_fence(owners)
        _need(_live_original_inputs(preparation, graph, admission, args, kwargs, **domain_arguments,
            **_reviewed_definition_application_kwargs(definition_application_profile)) == original,
              "live success original inputs changed during read")

    replay = retained_loader(packet, preparation, graph, admission, *args,
        expected_receipt_sha256=expected_receipt_sha256, expected_packet_sha256=expected_packet_sha256,
        expected_binary_sha256=expected_binary_sha256,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, **domain_arguments, **kwargs, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    fence()
    joins = _live_freeze_inputs((reviewed_version, expected_preservation_sha256, expected_graph_sha256,
        expected_admission_sha256, toolchain, expected_binary_sha256,
        replay["producer_pins"], expected_receipt_sha256, expected_packet_sha256))
    _need(joins == entry[3] and _wire(_parse(contents["build-receipt.json"], MAX_RECEIPT_BYTES)
          ["reviewed_execution_evidence"], MAX_RECEIPT_BYTES) == entry[4],
          "exact issued live success commitments required")
    checked = validator(preparation, graph, admission, *args,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, **domain_arguments, **kwargs, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    fence()
    _need(_live_original_inputs(checked, graph, admission, args, kwargs, **domain_arguments,
        **_reviewed_definition_application_kwargs(definition_application_profile)) == original,
          "exact issued live success regenerated project required")
    binding = receipt_binding(checked.to_dict(), admission, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)) if reviewed_version in (3, 4, 5) else {}
    fence()
    result = owners[1].contracts.seal_record({
        **{key: value for key, value in replay.items() if key not in {"schema", "profile", "record_cid", "cid_scope"}},
        **binding,
        "schema": live_schema, "profile": live_profile,
        "original_success_authenticated": False, "live_native_success_authenticated": True,
        "native_execution_authenticated": True, "original_admitted_parent_custody_authenticated": False,
        "native_execution_performed": False, "olean_kernel_rechecked": False,
        "release_ready": False, "Lean_admitted": False, "authority": authority_snapshot,
        "training_mask": 0, "evaluation_gold_mask": 0,
        "missing_prerequisites": [
            "Independently trusted original admitted-success parent Source/native/storage custody adapter for this reviewed profile.",
            "Source-matched actual native qualification and reviewed release-native consumer integration."],
        "scope": "Exact current-review replay joined to a fresh native-owner execution in this cooperative process/native thread; no original parent-admission, kernel recheck, legal or release authority."})
    fence()
    return result


def build_verified_reviewed_norm_preservation_native_v2(preparation, graph, admission, *args,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256,
        toolchain, lake_executable, output_directory, timeout_seconds=60, cancellation=None, instance_identity_profile=None, **kwargs):
    """Issue this explicit reviewed domain through the shared original live engine."""
    _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
          and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")
    _live_entry_guard(2)
    return _build_verified_reviewed_norm_preservation_native(
        preparation, graph, admission, *args, reviewed_version=2,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, lake_executable=lake_executable, output_directory=output_directory,
        timeout_seconds=timeout_seconds, cancellation=cancellation, **kwargs, **_reviewed_source_use_kwargs(instance_identity_profile))


def load_verified_reviewed_norm_preservation_native_v2(handle, packet_files, preparation, graph, admission, *args,
        expected_receipt_sha256, expected_packet_sha256, expected_binary_sha256,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain, instance_identity_profile=None, **kwargs):
    """Join this explicit domain's original live issuance without new execution."""
    _live_handle_entry(handle, reviewed_version=2, **_reviewed_source_use_kwargs(instance_identity_profile))
    _live_entry_guard(2)
    return _load_verified_reviewed_norm_preservation_native(
        handle, packet_files, preparation, graph, admission, *args, reviewed_version=2,
        expected_receipt_sha256=expected_receipt_sha256, expected_packet_sha256=expected_packet_sha256,
        expected_binary_sha256=expected_binary_sha256,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, **kwargs, **_reviewed_source_use_kwargs(instance_identity_profile))


__all__ += ["REVIEWED_LIVE_SUCCESS_SCHEMA", "REVIEWED_LIVE_SUCCESS_PROFILE",
    "VerifiedReviewedPreservationNativeSuccess", "build_verified_reviewed_norm_preservation_native_v2",
    "load_verified_reviewed_norm_preservation_native_v2"]

# Explicit mixed reviewed aggregate domain. Existing V2 public operations keep
# their original signatures and ASTs; no report is retagged between domains.
REVIEWED_MIXED_PRESERVATION_BUILD_SCHEMA = "legal-corpus-reviewed-preservation-native-build/v3"
REVIEWED_MIXED_PRESERVATION_NATIVE_PROFILE = "replayed-reviewed-mixed-multiunit-preservation-native-build/v3"
REVIEWED_MIXED_RECEIPT_REPLAY_SCHEMA = "legal-reviewed-native-receipt-replay/v3"
REVIEWED_MIXED_RECEIPT_REPLAY_PROFILE = "current-reviewed-mixed-native-retained-observation-replay/v3"
_REVIEWED_MIXED_PRESERVATION_OPERATION_PINS = None
_REVIEWED_MIXED_FALSE_KEYS = frozenset(PARENT_FALSE_FLAGS)
_REVIEWED_MIXED_AUTHORITY_KEYS = frozenset(AUTHORITY)
_REVIEWED_MIXED_SCOPE = (
    "Five exact independent concrete preservation obligations for every complete reviewed V3 source unit; "
    "each unchanged Object-native or mixed-renderer child keeps its own signature namespace, ordered roles "
    "and raw formula. No cross-namespace carrier coercion, cross-unit governing-definition application, "
    "native TDFOL/parser for mixed units, statutory truth, universal compiler theorem or corpus/release admission.")
_REVIEWED_MIXED_BINDINGS = (
    "input_commitment_sha256", "reviewed_graph_sha256", "reviewed_admission_sha256",
    "declaration_sha256", "provenance_kind", "scope_record_cid", "interpretation_record_cid",
    "units", "definition_use_record_cids", "signature_headers_by_unit", "predicate_compatibility_ledger",
    "common_module_profiles", "module_imports", "preservation_obligations", "file_sha256", "support_profile",
    "preservation_only", "cross_unit_definition_application_proved", "statutory_meaning_proved",
    "release_ready", "full_formal_corpus_consistency_verified", "generic_lean_v3_receipt_substituted",
    "formal_assumptions", "formal_assumptions_proved",
)
_REVIEWED_MIXED_CORE_FIELDS = (
    _REVIEWED_REPLAY_CORE_FIELDS - frozenset(_REVIEWED_REPLAY_BINDINGS)
    | frozenset(_REVIEWED_MIXED_BINDINGS))
_REVIEWED_MIXED_CHILD_DOMAINS = {
    "authored-object-relational-deontic/v1": (
        "typed-relational-deontic-native-preservation/v1", "deontic_fol", "LegalRelationalAstPreservation",
        ("native_value_exact", "native_ast_closed", "denotation_matches_native",
         "typed_source_lowering_exact", "role_denotation_matches_native")),
    "authored-many-sorted-relational-deontic/v1": (
        "typed-many-sorted-relational-deontic-renderer-preservation/v1", "tdfol", "LegalMixedRelationalAstPreservation",
        ("mixed_typed_value_exact", "mixed_renderer_value_exact", "mixed_ast_closed",
         "mixed_denotation_matches_lowering", "mixed_role_denotation_matches_lowering")),
}


def _reviewed_mixed_native_policy(shared=None, *, instance_identity_profile=None):
    _reviewed_source_use_kwargs(instance_identity_profile)
    _need((REVIEWED_MIXED_PRESERVATION_BUILD_SCHEMA, REVIEWED_MIXED_PRESERVATION_NATIVE_PROFILE,
           REVIEWED_MIXED_RECEIPT_REPLAY_SCHEMA, REVIEWED_MIXED_RECEIPT_REPLAY_PROFILE) == (
        "legal-corpus-reviewed-preservation-native-build/v3",
        "replayed-reviewed-mixed-multiunit-preservation-native-build/v3",
        "legal-reviewed-native-receipt-replay/v3",
        "current-reviewed-mixed-native-retained-observation-replay/v3"),
        "closed mixed native/retained profiles cannot alias another domain")
    _need(all(type(value) is int for value in (
        MAX_REVIEWED_PRESERVATION_UNITS, MAX_REVIEWED_PRESERVATION_FILES,
        MAX_REVIEWED_PRESERVATION_MODULES, MAX_REVIEWED_PRESERVATION_THEOREMS,
        MAX_RECORD_BYTES, MAX_INPUT_BYTES, MAX_PROJECT_BYTES, MAX_PREPARATION_BYTES,
        MAX_CAPTURE_BYTES, MAX_RECEIPT_BYTES, MAX_LOG_PREVIEW_BYTES))
          and (MAX_REVIEWED_PRESERVATION_UNITS, MAX_REVIEWED_PRESERVATION_FILES,
           MAX_REVIEWED_PRESERVATION_MODULES, MAX_REVIEWED_PRESERVATION_THEOREMS,
           MAX_RECORD_BYTES, MAX_INPUT_BYTES, MAX_PROJECT_BYTES, MAX_PREPARATION_BYTES,
           MAX_CAPTURE_BYTES, MAX_RECEIPT_BYTES, MAX_LOG_PREVIEW_BYTES) == (
        8, 78, 11, 40, 1024**2, 48 * 1024**2, 8 * 1024**2, 20 * 1024**2,
        2 * 1024**2, 1024**2, 32768), "mixed native bounds require a separate explicit port")
    _need(type(PARENT_FALSE_FLAGS) is dict and set(PARENT_FALSE_FLAGS) == _REVIEWED_MIXED_FALSE_KEYS
          and all(value is False for value in PARENT_FALSE_FLAGS.values())
          and type(AUTHORITY) is dict and set(AUTHORITY) == _REVIEWED_MIXED_AUTHORITY_KEYS
          and all(value is False for value in AUTHORITY.values()),
          "mixed native execution cannot widen its closed false-authority policy")
    _need(_REVIEWED_MIXED_CHILD_DOMAINS == {
        "authored-object-relational-deontic/v1": (
            "typed-relational-deontic-native-preservation/v1", "deontic_fol", "LegalRelationalAstPreservation",
            ("native_value_exact", "native_ast_closed", "denotation_matches_native",
             "typed_source_lowering_exact", "role_denotation_matches_native")),
        "authored-many-sorted-relational-deontic/v1": (
            "typed-many-sorted-relational-deontic-renderer-preservation/v1", "tdfol", "LegalMixedRelationalAstPreservation",
            ("mixed_typed_value_exact", "mixed_renderer_value_exact", "mixed_ast_closed",
             "mixed_denotation_matches_lowering", "mixed_role_denotation_matches_lowering"))},
        "mixed native child domains and theorem populations cannot be replaced")
    if shared is not None:
        if instance_identity_profile is not None:
            _need(shared.REVIEWED_MIXED_SOURCE_USE_PRESERVATION_PROFILE ==
                  shared.REVIEWED_MIXED_PRESERVATION_PROFILE + "+reviewed-source-use/v1",
                  "closed Shared mixed source-use preservation profile required")
        _need((shared.REVIEWED_MIXED_PRESERVATION_SCHEMA, shared.REVIEWED_MIXED_PRESERVATION_PROFILE,
               shared.REVIEWED_MIXED_PRESERVATION_ROOT) == (
            "legal-corpus-reviewed-preservation-preparation/v3",
            "reviewed-multi-unit-mixed-relational-preservation/v3", "LegalReviewedMixedNormPreservation")
            and all(type(value) is int for value in (
                shared.MAX_REVIEWED_PRESERVATION_UNITS, shared.MAX_REVIEWED_PRESERVATION_FILES,
                shared.MAX_REVIEWED_PRESERVATION_MODULES, shared.MAX_REVIEWED_PRESERVATION_OBLIGATIONS))
            and (shared.MAX_REVIEWED_PRESERVATION_UNITS, shared.MAX_REVIEWED_PRESERVATION_FILES,
                 shared.MAX_REVIEWED_PRESERVATION_MODULES, shared.MAX_REVIEWED_PRESERVATION_OBLIGATIONS)
                == (8, 78, 11, 40), "closed current mixed shared preparation domain required")


def _reviewed_mixed_preservation_native_pins(owners, manifest, *, instance_identity_profile=None):
    global _REVIEWED_MIXED_PRESERVATION_OPERATION_PINS
    shared = owners[4]
    _reviewed_source_use_kwargs(instance_identity_profile)
    if instance_identity_profile is not None:
        _reviewed_mixed_preservation_native_manifest(manifest, shared, instance_identity_profile=instance_identity_profile)
    _reviewed_mixed_native_policy(shared, **_reviewed_source_use_kwargs(instance_identity_profile))
    current = shared._reviewed_preservation_pins(shared._reviewed_mixed_preservation_owners())
    pins = _observed_producer_pins(owners, manifest)
    for path, expected in current.items():
        _need(path not in pins or pins[path] == expected, "mixed native producer pin collision")
        pins[path] = expected
    if _REVIEWED_MIXED_PRESERVATION_OPERATION_PINS is None:
        _REVIEWED_MIXED_PRESERVATION_OPERATION_PINS = dict(pins)
    _need(pins == _REVIEWED_MIXED_PRESERVATION_OPERATION_PINS,
          "mixed native operation owners changed since first use")
    return pins


def _reviewed_mixed_preservation_native_manifest(manifest, shared, *, instance_identity_profile=None):
    _reviewed_mixed_native_policy(shared, **_reviewed_source_use_kwargs(instance_identity_profile))
    _reviewed_source_use_manifest(manifest, instance_identity_profile)
    _need(manifest.get("schema") == "legal-corpus-reviewed-preservation-preparation/v3"
          and manifest.get("profile") == _reviewed_source_use_domain(
              "reviewed-multi-unit-mixed-relational-preservation/v3", instance_identity_profile),
          "exact current mixed reviewed preservation preparation required")
    units = manifest["units"]
    _need(type(units) is list and 3 <= len(units) <= 8,
          "complete three-to-eight explicit V3 reviewed units required")
    headers, namespace_units, common = [], {}, {}
    obligations, instances = [], []
    for ordinal, unit in enumerate(units):
        domain = _REVIEWED_MIXED_CHILD_DOMAINS.get(unit.get("relational_profile"))
        _need(domain is not None, "unknown reviewed unit preservation domain")
        profile, family, root, suffixes = domain
        profile = _reviewed_source_use_domain(profile, instance_identity_profile)
        instance = unit["instance_module"]
        _need(type(unit["ordinal"]) is int and unit["ordinal"] == ordinal
              and unit["child_preservation_profile"] == profile and unit["child_family"] == family
              and re.fullmatch(re.escape(root) + r"\.Instance[0-9a-f]{64}", instance)
              and instance not in instances, "complete unchanged profile-specific unit instance required")
        wanted = [instance + "." + suffix for suffix in suffixes]
        _need(unit["preservation_obligations"] == wanted, "five exact ordered obligations for each unit required")
        instances.append(instance); obligations.extend(wanted)
        header = unit["signature_header"]
        namespace = _sha(_wire({"relational_profile": unit["relational_profile"], "signature_header": header}, MAX_RECORD_BYTES))
        _need(unit["signature_namespace_sha256"] == namespace and unit["signature_id"] == header["signature_id"],
              "complete per-unit signature namespace commitment differs")
        headers.append({"unit_id": unit["unit_id"], "relational_profile": unit["relational_profile"],
            "signature_header": header, "signature_namespace_sha256": namespace})
        key = unit["relational_profile"] + ":" + _sha(_wire(header, MAX_RECORD_BYTES))
        namespace_units.setdefault(key, []).append(unit["unit_id"])
        common[root] = {"relational_profile": unit["relational_profile"], "preservation_profile": profile,
            "family": family, "project_root": root, "modules": [root + ".Prelude", root + ".Semantics"],
            "theorem_suffixes": list(suffixes)}
    _need(manifest["signature_headers_by_unit"] == headers
          and set(manifest["predicate_compatibility_ledger"]) == set(namespace_units),
          "complete ordered headers and exact signature namespaces required")
    for key, unit_ids in namespace_units.items():
        ledger = manifest["predicate_compatibility_ledger"][key]
        exemplar = next(row for row in headers if row["unit_id"] == unit_ids[0])
        _need(type(ledger) is dict and set(ledger) == {"relational_profile", "signature_header", "unit_ids", "predicates"}
              and ledger["unit_ids"] == unit_ids and ledger["relational_profile"] == exemplar["relational_profile"]
              and ledger["signature_header"] == exemplar["signature_header"]
              and type(ledger["predicates"]) is dict and ledger["predicates"],
              "within-namespace predicate and ordered-role ledger cannot be omitted or merged")
    profiles = [common[key] for key in sorted(common)]
    modules = [name for row in profiles for name in row["modules"]] + instances + ["LegalReviewedMixedNormPreservation"]
    _need(manifest["common_module_profiles"] == profiles and manifest["expected_modules"] == modules
          and len(modules) <= 11 and len(set(modules)) == len(modules)
          and manifest["preservation_obligations"] == obligations
          and len(set(obligations)) == 5 * len(units) <= 40
          and type(manifest["definition_use_record_cids"]) is list and manifest["definition_use_record_cids"],
          "complete common-module, definition-use and obligation populations required")
    support = manifest["support_profile"]
    _need(support["cross_namespace_signature_or_carrier_coercion"] is False
          and support["cross_unit_definition_application_proved"] is False
          and support["predicate_compatibility_is_syntactic_only"] is True
          and manifest["preparation_only"] is True and manifest["proof_status"] == "not_executed"
          and manifest["lean_compilation_status"] == "not_executed",
          "preparation cannot acquire native, cross-namespace or governing-definition authority")
    return manifest


def _reviewed_mixed_preservation_receipt_binding(manifest, admission, *, instance_identity_profile=None):
    keys = ("input_commitment_sha256", "reviewed_graph_sha256", "reviewed_admission_sha256",
        "declaration_sha256", "provenance_kind", "scope_record_cid", "interpretation_record_cid",
        "units", "definition_use_record_cids", "signature_headers_by_unit", "predicate_compatibility_ledger",
        "common_module_profiles", "module_imports", "preservation_obligations", "file_sha256", "support_profile")
    return {name: manifest[name] for name in keys} | {
        "preservation_only": True, "cross_unit_definition_application_proved": False,
        "statutory_meaning_proved": False, "release_ready": False,
        "full_formal_corpus_consistency_verified": False, "generic_lean_v3_receipt_substituted": False,
        "formal_assumptions": admission["formal_assumptions"], "formal_assumptions_proved": False} | _reviewed_source_use_manifest(manifest, instance_identity_profile)


def validate_reviewed_norm_preservation_native_v3(preparation, graph, admission, *args,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain, instance_identity_profile=None, **kwargs):
    """Replay complete current V3 source, review, mixed graph and exact project."""
    _reviewed_mixed_native_policy(**_reviewed_source_use_kwargs(instance_identity_profile))
    return _reviewed_preservation_native_operation(preparation, graph, admission, args, kwargs,
        expected_preservation_sha256=expected_preservation_sha256, expected_graph_sha256=expected_graph_sha256,
        expected_admission_sha256=expected_admission_sha256, toolchain=toolchain, reviewed_version=3, **_reviewed_source_use_kwargs(instance_identity_profile))


def build_reviewed_norm_preservation_native_v3(preparation, graph, admission, *args,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256,
        toolchain, lake_executable, output_directory, timeout_seconds=60, cancellation=None, instance_identity_profile=None, **kwargs):
    """Build every complete V3 unit with its unchanged child semantics and formula."""
    _reviewed_mixed_native_policy(**_reviewed_source_use_kwargs(instance_identity_profile))
    _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
          and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")

    def execute(checked, replay, custody):
        def binding(manifest):
            return _reviewed_mixed_preservation_receipt_binding(manifest, admission, **_reviewed_source_use_kwargs(instance_identity_profile))
        return _build_validated_native(preparation, checked, replay=replay,
            expected_preparation_sha256=expected_preservation_sha256, toolchain=toolchain,
            lake_executable=lake_executable, output_directory=output_directory,
            timeout_seconds=timeout_seconds, cancellation=cancellation,
            build_schema="legal-corpus-reviewed-preservation-native-build/v3",
            profile=_reviewed_source_use_domain("replayed-reviewed-mixed-multiunit-preservation-native-build/v3", instance_identity_profile),
            flags=dict(PARENT_FALSE_FLAGS), receipt_binding=binding,
            maximum_files=MAX_REVIEWED_PRESERVATION_FILES, maximum_modules=MAX_REVIEWED_PRESERVATION_MODULES,
            maximum_theorems=MAX_REVIEWED_PRESERVATION_THEOREMS,
            producer_pin_reader=(_reviewed_mixed_preservation_native_pins if instance_identity_profile is None else
                lambda owners, manifest: _reviewed_mixed_preservation_native_pins(owners, manifest, instance_identity_profile=instance_identity_profile)),
            preparation_document_reader=_reviewed_preservation_native_document,
            closing_custody_guard=custody, receipt_scope=_REVIEWED_MIXED_SCOPE,
            frozen_authority=dict(AUTHORITY), **_reviewed_source_use_kwargs(instance_identity_profile))

    return _reviewed_preservation_native_operation(preparation, graph, admission, args, kwargs,
        expected_preservation_sha256=expected_preservation_sha256, expected_graph_sha256=expected_graph_sha256,
        expected_admission_sha256=expected_admission_sha256, toolchain=toolchain,
        operation=execute, reviewed_version=3, **_reviewed_source_use_kwargs(instance_identity_profile))


def reviewed_norm_preservation_receipt_bytes_v3(receipt, *, instance_identity_profile=None):
    """Format one complete mixed aggregate observation, without authentication."""
    _reviewed_mixed_native_policy(**_reviewed_source_use_kwargs(instance_identity_profile))
    selected = _reviewed_source_use_kwargs(instance_identity_profile)
    _bound_tree(receipt, MAX_RECEIPT_BYTES)
    _reviewed_source_use_manifest(receipt, instance_identity_profile)
    _need(type(receipt) is dict and set(receipt) == _REVIEWED_MIXED_CORE_FIELDS | set(selected)
          and receipt.get("schema") == "legal-corpus-reviewed-preservation-native-build/v3"
          and receipt.get("profile") == _reviewed_source_use_domain("replayed-reviewed-mixed-multiunit-preservation-native-build/v3", instance_identity_profile),
          "closed complete mixed aggregate receipt required")
    return _wire(receipt, MAX_RECEIPT_BYTES)


def reviewed_norm_preservation_packet_sha256_v3(packet_files, *, instance_identity_profile=None):
    """Commit every complete sorted retained path/byte pair, without authority."""
    _reviewed_source_use_kwargs(instance_identity_profile)
    _reviewed_mixed_native_policy(**_reviewed_source_use_kwargs(instance_identity_profile))
    _, inventory = _reviewed_retained_packet(packet_files)
    return _sha(_wire(inventory, MAX_RECORD_BYTES))


__all__ += ["REVIEWED_MIXED_PRESERVATION_BUILD_SCHEMA", "REVIEWED_MIXED_PRESERVATION_NATIVE_PROFILE",
    "REVIEWED_MIXED_RECEIPT_REPLAY_SCHEMA", "REVIEWED_MIXED_RECEIPT_REPLAY_PROFILE",
    "validate_reviewed_norm_preservation_native_v3", "build_reviewed_norm_preservation_native_v3",
    "reviewed_norm_preservation_receipt_bytes_v3", "reviewed_norm_preservation_packet_sha256_v3"]


def _validate_reviewed_native_retained_domain(
        receipt_raw, preparation, graph, admission, *args,
        packet_files, expected_receipt_sha256, expected_packet_sha256, expected_binary_sha256,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256,
        toolchain, observation_profile=_REVIEWED_REPLAY_ACTUAL, instance_identity_profile=None, definition_application_profile=None, reviewed_version=3,
        realization_preservation=None, expected_upstream_preservation_sha256=None,
        physical_request_raw=None, expected_physical_request_sha256=None, **kwargs):
    """Replay the complete retained V3 mixed aggregate and current inputs without Lean.

    The caller owns physical acquisition and independently trusted receipt,
    packet and compiler pins. Historical PIDs are never inspected. This API
    cannot authenticate original admitted success, validate olean bytes in the
    kernel or authorize release/cache/native/statutory admission. The missing
    original-success adapter remains an explicit prerequisite in every result.
    """
    _need(type(reviewed_version) is int and reviewed_version in (3, 4, 5), "closed retained native domain required")
    _reviewed_definition_application_kwargs(definition_application_profile)
    _need(definition_application_profile is None or reviewed_version in (4, 5),
          "whole-norm application requires the explicit realization retained domain")
    _need(reviewed_version == 5 or physical_request_raw is expected_physical_request_sha256 is None,
          "physical request requires the explicit physical realization retained domain")
    domain_arguments = ({} if reviewed_version == 3 else {
        "realization_preservation": realization_preservation,
        "expected_upstream_preservation_sha256": expected_upstream_preservation_sha256})
    if reviewed_version == 5:
        domain_arguments.update(physical_request_raw=physical_request_raw,
            expected_physical_request_sha256=expected_physical_request_sha256)
    if reviewed_version == 3:
        domain_policy = _reviewed_mixed_native_policy
        build_schema, replay_schema, replay_profile = (REVIEWED_MIXED_PRESERVATION_BUILD_SCHEMA,
            REVIEWED_MIXED_RECEIPT_REPLAY_SCHEMA, REVIEWED_MIXED_RECEIPT_REPLAY_PROFILE)
        replay_profile = _reviewed_source_use_domain(replay_profile, instance_identity_profile)
        validator, formatter = validate_reviewed_norm_preservation_native_v3, reviewed_norm_preservation_receipt_bytes_v3
        receipt_binding, pin_reader, receipt_scope = (_reviewed_mixed_preservation_receipt_binding,
            _reviewed_mixed_preservation_native_pins, _REVIEWED_MIXED_SCOPE)
    elif reviewed_version == 5:
        domain_policy = _reviewed_physical_definition_realization_native_policy
        build_schema, replay_schema, replay_profile = (REVIEWED_PHYSICAL_DEFINITION_REALIZATION_BUILD_SCHEMA,
            REVIEWED_PHYSICAL_DEFINITION_REALIZATION_RECEIPT_REPLAY_SCHEMA,
            REVIEWED_PHYSICAL_DEFINITION_REALIZATION_RECEIPT_REPLAY_PROFILE)
        replay_profile = _reviewed_realization_domain(replay_profile, instance_identity_profile, definition_application_profile)
        validator, formatter = (_reviewed_physical_definition_realization_validate_adapter,
            reviewed_physical_definition_realization_receipt_bytes_v2)
        receipt_binding, pin_reader, receipt_scope = (_reviewed_physical_definition_realization_receipt_binding,
            _reviewed_physical_definition_realization_native_pins, _reviewed_definition_realization_scope(definition_application_profile))
    else:
        domain_policy = _reviewed_definition_realization_native_policy
        build_schema, replay_schema, replay_profile = (REVIEWED_DEFINITION_REALIZATION_BUILD_SCHEMA,
            REVIEWED_DEFINITION_REALIZATION_RECEIPT_REPLAY_SCHEMA, REVIEWED_DEFINITION_REALIZATION_RECEIPT_REPLAY_PROFILE)
        replay_profile = _reviewed_realization_domain(replay_profile, instance_identity_profile, definition_application_profile)
        validator, formatter = _reviewed_definition_realization_validate_adapter, reviewed_definition_realization_receipt_bytes_v1
        receipt_binding, pin_reader, receipt_scope = (_reviewed_definition_realization_receipt_binding,
            _reviewed_definition_realization_native_pins, _reviewed_definition_realization_scope(definition_application_profile))
    domain_policy(**_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    for value, label in ((expected_receipt_sha256, "retained reviewed receipt"),
                         (expected_packet_sha256, "whole retained reviewed packet")):
        _pin(value, label)
    _bound_tree(expected_binary_sha256, MAX_RECORD_BYTES)
    contents, inventory = (_reviewed_physical_retained_packet_v2 if reviewed_version == 5 else _reviewed_retained_packet)(packet_files)
    _need(_sha(_wire(inventory, MAX_RECORD_BYTES)) == expected_packet_sha256,
          "independent complete retained packet commitment differs")
    _need(type(receipt_raw) is bytes and 0 < len(receipt_raw) <= MAX_RECEIPT_BYTES
          and _sha(receipt_raw) == expected_receipt_sha256
          and contents.get("build-receipt.json") == receipt_raw,
          "independent original receipt bytes differ")
    receipt = _parse(receipt_raw, MAX_RECEIPT_BYTES)
    _need(formatter(receipt, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)) == receipt_raw,
          "original reviewed receipt must retain its canonical complete bytes")
    _need(type(observation_profile) is str
          and observation_profile in (_REVIEWED_REPLAY_ACTUAL, _REVIEWED_REPLAY_FICTIONAL),
          "explicit supported retained observation profile required")
    if observation_profile == _REVIEWED_REPLAY_FICTIONAL:
        _need(type(admission) is dict and admission.get("fixture_only") is True
              and admission.get("provenance_kind") == "fictional_fixture",
              "fictional interface requires unchanged explicit fictional admission")
    # The existing source/admission/graph/project owner retains all current
    # review, revocation and source replay; no saved eligibility flag replaces it.
    checked = validator(preparation, graph, admission, *args,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, **domain_arguments, **kwargs, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    owners = _owners(); transport, process = owners[1], owners[3]
    from . import legal_corpus_definition_use_preservation_packet_v2 as packets
    packet_owner_pin = _sha(Path(packets.__file__).read_bytes())
    _need(packet_owner_pin == packets._SELF_PIN, "existing retained-packet validator changed since import")
    manifest = checked.to_dict(); contracts = transport.contracts
    contracts.validate_record(receipt, schema=build_schema,
        fields=set(receipt) - {"schema", "record_cid", "cid_scope"})
    binding = receipt_binding(manifest, admission, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    binding.update(preparation_cid=manifest["record_cid"],
        preparation_full_canonical_sha256=expected_preservation_sha256,
        preparation_manifest_sha256=_sha(checked.manifest_json.encode("utf-8")), toolchain=toolchain,
        expected_modules=manifest["expected_modules"], compiled_modules=manifest["expected_modules"],
        producer_pins=pin_reader(owners, manifest, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)),
        conditional_theorems=manifest["preservation_obligations"],
        original_preparation_theorem_assumptions=[], theorem_assumptions=[], scope=receipt_scope)
    _need(_wire({name: receipt[name] for name in binding}, MAX_RECEIPT_BYTES)
          == _wire(binding, MAX_RECEIPT_BYTES),
          "retained receipt differs from current whole reviewed semantics or producers")
    success_flags = {"backend_executed", "lean_compilation_verified", "proof_checked",
                     "kernel_proofs_checked", "conditional_proofs_verified"}
    for name in PARENT_FALSE_FLAGS:
        _need(receipt[name] is (name in success_flags), "retained authority/profile flag differs: " + name)
    _need(receipt["authority"] == AUTHORITY and all(v is False for v in receipt["authority"].values())
          and type(receipt["training_mask"]) is int and receipt["training_mask"] == 0
          and type(receipt["evaluation_gold_mask"]) is int and receipt["evaluation_gold_mask"] == 0,
          "retained receipt cannot grant authority or training masks")
    for name in ("original_preparation_unchanged", "manifest_coverage_passed", "executed_project_readback_passed",
                 "binaries_unchanged", "post_run_validation_passed", "axiom_observations_passed",
                 "workspace_cleaned", "cleanup_confirmed", "observed_process_scope_passed",
                 "ownership_is_sampled", "build_passed", "native_runtime_verified"):
        _need(receipt[name] is True, "retained successful observation differs: " + name)
    for name in ("timed_out", "cancelled", "unavailable", "output_truncated", "workspace_limit_exceeded",
                 "resource_exhausted", "kernel_containment_attested", "alias_assumption_proved",
                 "source_to_model_equivalence_proved"):
        _need(receipt[name] is False, "retained failure/authority field differs: " + name)
    _need(receipt["reviewed_execution_projection_error"] is None
          and receipt["post_run_validation_error"] is None and receipt["binary_recheck_error"] is None
          and receipt["status"] == "conditional_native_checks_passed"
          and receipt["conditional_kernel_status"] == "checked_under_explicit_hypotheses",
          "retained profile reports an incomplete or failed build")
    sources = {name: body.encode("utf-8") for name, body in checked.files}
    artifacts = [".lake/build/lib/lean/" + name.replace(".", "/") + ".olean"
                 for name in manifest["expected_modules"]]
    wanted = ({"build-receipt.json", "stdout.txt", "stderr.txt", "runner-error.txt",
               "project/" + transport.MANIFEST_FILE}
              | {"project/" + name for name in sources} | {"executed-inputs/" + name for name in sources}
              | {"compiled/" + name.removeprefix(".lake/build/lib/lean/") for name in artifacts})
    _need(set(contents) == wanted
          and contents["project/" + transport.MANIFEST_FILE] == checked.manifest_json.encode("utf-8")
          and all(contents["project/" + name] == contents["executed-inputs/" + name] == raw
                  for name, raw in sources.items()), "complete original project/source packet differs")
    outputs = {**sources, **{name: contents["compiled/" + name.removeprefix(".lake/build/lib/lean/")]
                            for name in artifacts}}
    logs = {name: contents[name] for name in ("stdout.txt", "stderr.txt", "runner-error.txt")}
    _need(all(len(raw) <= (8 * 1024**2 if reviewed_version == 5 else MAX_CAPTURE_BYTES) for raw in outputs.values())
          and all(len(raw) <= (8 * 1024**2 if reviewed_version == 5 else 3 * MAX_CAPTURE_BYTES) for raw in logs.values()),
          "complete retained mixed outputs and diagnostics exceed original capture bounds")
    invocation, run = _reviewed_native_execution_from_projection(receipt["reviewed_execution_evidence"],
        sources=sources, outputs=outputs, logs=logs, process=process, physical_realization=reviewed_version == 5)
    expected_interface = ("synthetic-unit-boundary/v1" if observation_profile == _REVIEWED_REPLAY_FICTIONAL
                          else process.BOUNDED_TOOL_RUNNER_VERSION)
    _need(run.interface_version == expected_interface and run.runtime is process.ToolRuntime.NATIVE
          and invocation.runtime is process.ToolRuntime.NATIVE
          and type(receipt["runtime"]) is str and receipt["runtime"] == run.runtime.value
          and type(run.pid) is int and run.pid > 0 and type(run.returncode) is int and run.returncode == 0
          and run.ok and run.workspace_cleaned and not run.error,
          "retained runner interface or successful typed result differs")
    executable = _reviewed_replay_binary_observations(receipt, expected_binary_sha256,
        toolchain, observation_profile, packets)
    command = (executable, "--offline", "--no-cache", "build", "legal")
    _need(invocation.argv == run.command == command and receipt["command"] == receipt["expected_command"] == list(command)
          and dict(invocation.environment) == {"ELAN_TOOLCHAIN": toolchain, "LEAN_NUM_THREADS": "1"}
          and invocation.output_paths == tuple(artifacts) + tuple(sources),
          "original complete invocation, environment or artifact paths differ")
    from dataclasses import fields
    timeout = invocation.limits.timeout_seconds
    _need(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 60,
          "original bounded compiler timeout required")
    expected_limits = process.ToolRunLimits(timeout_seconds=timeout, cpu_seconds=timeout,
        resident_memory_bytes=2 * 1024**3, max_output_bytes=64 * 1024**2 if reviewed_version == 5 else MAX_CAPTURE_BYTES,
        max_input_bytes=128 * 1024**2 if reviewed_version == 5 else MAX_PROJECT_BYTES,
        max_workspace_bytes=256 * 1024**2 if reviewed_version == 5 else 128 * MAX_RECORD_BYTES,
        max_file_bytes=128 * 1024**2 if reviewed_version == 5 else None,
        max_output_files=len(outputs))
    _need(all(getattr(invocation.limits, f.name) == getattr(expected_limits, f.name)
              and type(getattr(invocation.limits, f.name)) is type(getattr(expected_limits, f.name))
              for f in fields(process.ToolRunLimits)), "original native resource limits differ")
    packets._historical_lifecycle(receipt["native_lifecycle"], run.pid)
    _need(receipt["native_lifecycle"] == run.native_lifecycle.to_dict()
          and receipt["pid"] == run.pid and type(receipt["pid"]) is int
          and receipt["returncode"] == run.returncode and type(receipt["returncode"]) is int
          and type(receipt["process_tree_terminated"]) is bool,
          "historical lifecycle and result bindings differ")
    for name in ("elapsed_seconds", "termination_reason", "timed_out", "cancelled", "unavailable",
                 "output_truncated", "workspace_limit_exceeded", "resource_exhausted",
                 "workspace_cleaned", "process_tree_terminated"):
        _need(type(receipt[name]) is type(getattr(run, name)) and receipt[name] == getattr(run, name),
              "retained runner scalar differs: " + name)
    artifact_hashes = {name: _sha(outputs[name]) for name in artifacts}
    expected_artifacts = {"artifact_sha256": artifact_hashes,
        "artifact_bytes": {name: len(outputs[name]) for name in artifacts},
        "artifact_files": {name: "compiled/" + name.removeprefix(".lake/build/lib/lean/") for name in artifacts},
        "executed_project_sha256": {name: _sha(raw) for name, raw in sources.items()}}
    _need(all(outputs[name] for name in artifacts)
          and _wire({name: receipt[name] for name in expected_artifacts}, MAX_RECEIPT_BYTES)
              == _wire(expected_artifacts, MAX_RECEIPT_BYTES),
          "retained complete source/artifact commitments differ")
    for name, field in (("stdout.txt", "stdout"), ("stderr.txt", "stderr"), ("runner-error.txt", "error")):
        raw = logs[name]
        _need(receipt["log_sha256"][name] == _sha(raw) and type(receipt["log_bytes"][name]) is int
              and receipt["log_bytes"][name] == len(raw)
              and receipt[field] == raw[:MAX_LOG_PREVIEW_BYTES].decode("utf-8", errors="replace").replace("\x00", "\\u0000"),
              "retained complete compiler logs or previews differ")
    _need(set(receipt["log_sha256"]) == set(receipt["log_bytes"]) == set(logs)
          and logs["runner-error.txt"] == b""
          and receipt["receipt_text_truncated"] is any(len(raw) > MAX_LOG_PREVIEW_BYTES for raw in logs.values()),
          "retained diagnostics or truncation frame differs")
    axioms, errors, passed = _axiom_observations(run.stdout, run.stderr,
        {"conditional_theorems": manifest["preservation_obligations"]},
        maximum_theorems=MAX_REVIEWED_PRESERVATION_THEOREMS)
    _need(passed is True and errors == receipt["axiom_observation_errors"] == []
          and axioms == receipt["theorem_axiom_dependencies"],
          "retained exact preservation obligation/axiom reports differ")
    # Recheck current source/review/graph dependencies after the full byte replay.
    validator(preparation, graph, admission, *args,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, **domain_arguments, **kwargs, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    _need(_sha(Path(packets.__file__).read_bytes()) == packet_owner_pin,
          "retained-packet validator changed during replay")
    domain_policy(**_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    return contracts.seal_record({**dict(PARENT_FALSE_FLAGS),
        **(receipt_binding(manifest, admission, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)) if reviewed_version in (4, 5) else {}), "schema": replay_schema,
        "profile": replay_profile, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile), "observation_profile": observation_profile,
        "retained_receipt_sha256": expected_receipt_sha256, "retained_packet_sha256": expected_packet_sha256,
        "preparation_sha256": expected_preservation_sha256, "graph_sha256": expected_graph_sha256,
        "admission_sha256": expected_admission_sha256, "retained_observations_consistent": True,
        "current_complete_semantics_replayed": True, "obligations": list(manifest["preservation_obligations"]),
        "packet_inventory": inventory, "producer_pins": {**pin_reader(owners, manifest, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)),
            str(Path(packets.__file__).resolve()): packet_owner_pin},
        "original_success_authenticated": False, "native_execution_authenticated": False,
        "live_native_success_authenticated": False, "original_admitted_parent_custody_authenticated": False,
        "native_execution_performed": False, "olean_kernel_rechecked": False,
        "release_ready": False, "Lean_admitted": False, "training_mask": 0, "evaluation_gold_mask": 0,
        "authority": dict(AUTHORITY), "missing_prerequisites": [
            "Independently trusted original admitted-success custody adapter for this reviewed profile.",
            "Source-matched actual native qualification and reviewed release-native consumer integration."],
        "scope": "Retained observation consistency and current replay only; no historical process, kernel, legal or release authority."})


def validate_reviewed_norm_preservation_native_receipt_v3(
        receipt_raw, preparation, graph, admission, *args,
        packet_files, expected_receipt_sha256, expected_packet_sha256, expected_binary_sha256,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256,
        toolchain, observation_profile=_REVIEWED_REPLAY_ACTUAL, instance_identity_profile=None, **kwargs):
    """Replay retained V3 bytes through the unchanged closed V3 domain."""
    return _validate_reviewed_native_retained_domain(receipt_raw, preparation, graph, admission, *args,
        packet_files=packet_files, expected_receipt_sha256=expected_receipt_sha256,
        expected_packet_sha256=expected_packet_sha256, expected_binary_sha256=expected_binary_sha256,
        expected_preservation_sha256=expected_preservation_sha256, expected_graph_sha256=expected_graph_sha256,
        expected_admission_sha256=expected_admission_sha256, toolchain=toolchain,
        observation_profile=observation_profile, reviewed_version=3, **kwargs,
        **_reviewed_source_use_kwargs(instance_identity_profile))



def load_reviewed_norm_preservation_native_v3(packet_files, preparation, graph, admission, *args, instance_identity_profile=None, **kwargs):
    """Replay every retained byte under the explicit mixed V3 receipt domain."""
    _reviewed_mixed_native_policy(**_reviewed_source_use_kwargs(instance_identity_profile))
    contents, _ = _reviewed_retained_packet(packet_files)
    _need("build-receipt.json" in contents, "original complete mixed native receipt required")
    return validate_reviewed_norm_preservation_native_receipt_v3(contents["build-receipt.json"],
        preparation, graph, admission, *args, packet_files=packet_files, **kwargs, **_reviewed_source_use_kwargs(instance_identity_profile))


__all__ += ["validate_reviewed_norm_preservation_native_receipt_v3", "load_reviewed_norm_preservation_native_v3"]


def build_verified_reviewed_norm_preservation_native_v3(preparation, graph, admission, *args,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256,
        toolchain, lake_executable, output_directory, timeout_seconds=60, cancellation=None, instance_identity_profile=None, **kwargs):
    """Issue this explicit reviewed domain through the shared original live engine."""
    _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
          and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")
    _live_entry_guard(3)
    return _build_verified_reviewed_norm_preservation_native(
        preparation, graph, admission, *args, reviewed_version=3,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, lake_executable=lake_executable, output_directory=output_directory,
        timeout_seconds=timeout_seconds, cancellation=cancellation, **kwargs, **_reviewed_source_use_kwargs(instance_identity_profile))


def load_verified_reviewed_norm_preservation_native_v3(handle, packet_files, preparation, graph, admission, *args,
        expected_receipt_sha256, expected_packet_sha256, expected_binary_sha256,
        expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain, instance_identity_profile=None, **kwargs):
    """Join this explicit domain's original live issuance without new execution."""
    _live_handle_entry(handle, reviewed_version=3, **_reviewed_source_use_kwargs(instance_identity_profile))
    _live_entry_guard(3)
    return _load_verified_reviewed_norm_preservation_native(
        handle, packet_files, preparation, graph, admission, *args, reviewed_version=3,
        expected_receipt_sha256=expected_receipt_sha256, expected_packet_sha256=expected_packet_sha256,
        expected_binary_sha256=expected_binary_sha256,
        expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, **kwargs, **_reviewed_source_use_kwargs(instance_identity_profile))


__all__ += ["REVIEWED_MIXED_LIVE_SUCCESS_SCHEMA", "REVIEWED_MIXED_LIVE_SUCCESS_PROFILE",
    "build_verified_reviewed_norm_preservation_native_v3", "load_verified_reviewed_norm_preservation_native_v3"]



# New constructed-model domain. Old reviewed V2/V3 source/receipt identities
# remain separate; no existing native success is retagged into this profile.
REVIEWED_DEFINITION_REALIZATION_BUILD_SCHEMA = "legal-reviewed-definition-realization-native-build/v1"
REVIEWED_DEFINITION_REALIZATION_NATIVE_PROFILE = "replayed-reviewed-definition-realization-native-build/v1"
REVIEWED_DEFINITION_REALIZATION_RECEIPT_REPLAY_SCHEMA = "legal-reviewed-definition-realization-receipt-replay/v1"
REVIEWED_DEFINITION_REALIZATION_RECEIPT_REPLAY_PROFILE = "current-reviewed-definition-realization-retained-observation/v1"
REVIEWED_DEFINITION_REALIZATION_LIVE_SUCCESS_SCHEMA = "legal-reviewed-definition-realization-live-success/v1"
REVIEWED_DEFINITION_REALIZATION_LIVE_SUCCESS_PROFILE = "current-reviewed-definition-realization-live-native-owner-success/v1"
_REVIEWED_DEFINITION_REALIZATION_OPERATION_PINS = None
_REVIEWED_DEFINITION_APPLICATION_OPERATION_PINS = None
_REVIEWED_DEFINITION_REALIZATION_SCOPE = (
    "Exact original child preservation plus constructed unary Object definition realization and every reviewed "
    "head occurrence's original-source/body connection. Only the explicitly constructed Object/Mixed models "
    "are checked; no arbitrary-model equivalence, legal membership, opaque modal replacement, statutory "
    "correspondence, legal proof-cache authority or corpus/release admission is supplied.")
_REVIEWED_DEFINITION_REALIZATION_BINDINGS = (
    "input_commitment_sha256", "reviewed_preservation_sha256", "reviewed_graph_sha256",
    "reviewed_admission_sha256", "declaration_sha256", "selection", "upstream_manifest",
    "original_file_sha256", "theorem_bindings", "units", "module_imports", "preservation_obligations",
    "realization_obligations", "file_sha256", "support_profile", "provenance_kind", "scope_record_cid",
    "interpretation_record_cid", "definition_use_record_cids", "preservation_only", "constructed_model_only",
    "cross_unit_definition_application_proved", "statutory_meaning_proved", "release_ready",
    "full_formal_corpus_consistency_verified", "generic_lean_v3_receipt_substituted", "formal_assumptions",
    "formal_assumptions_proved")
_REVIEWED_DEFINITION_REALIZATION_CORE_FIELDS = (
    _REVIEWED_REPLAY_CORE_FIELDS - frozenset(_REVIEWED_REPLAY_BINDINGS)
    | frozenset(_REVIEWED_DEFINITION_REALIZATION_BINDINGS))


def _reviewed_definition_application_kwargs(definition_application_profile):
    if definition_application_profile is None:
        return {}
    _need(type(definition_application_profile) is str
          and definition_application_profile == "whole-norm-definition-expansion/v1",
          "explicit supported whole-norm definition application profile required")
    return {"definition_application_profile": definition_application_profile}


def _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile):
    return (_reviewed_source_use_kwargs(instance_identity_profile)
            | _reviewed_definition_application_kwargs(definition_application_profile))


def _reviewed_realization_domain(profile, instance_identity_profile, definition_application_profile):
    selected = _reviewed_definition_application_kwargs(definition_application_profile)
    return (_reviewed_source_use_domain(profile, instance_identity_profile)
            + ("+whole-norm-definition-expansion/v1" if selected else ""))


def _reviewed_definition_application_manifest(manifest, definition_application_profile):
    selected = _reviewed_definition_application_kwargs(definition_application_profile)
    fields = {"definition_application_profile", "definition_applications", "definition_application_obligations"}
    _need(type(manifest) is dict, "ordinary definition application binding required")
    if not selected:
        _need(not fields.intersection(manifest), "legacy realization cannot acquire definition application witnesses")
        return {}
    _need(fields <= set(manifest)
          and manifest["definition_application_profile"] == definition_application_profile
          and type(manifest["definition_applications"]) is list
          and 1 <= len(manifest["definition_applications"]) <= MAX_REVIEWED_PRESERVATION_MODULES
          and type(manifest["definition_application_obligations"]) is list
          and 2 <= len(manifest["definition_application_obligations"]) <= MAX_REVIEWED_PRESERVATION_THEOREMS,
          "complete explicitly selected whole-norm application witnesses required")
    return {key: manifest[key] for key in sorted(fields)}


def _reviewed_definition_realization_scope(definition_application_profile):
    if not _reviewed_definition_application_kwargs(definition_application_profile):
        return _REVIEWED_DEFINITION_REALIZATION_SCOPE
    return ("Exact original child preservation and constructed-model realization obligations plus whole-norm "
        "definition expansion conditional on satisfaction of the exact original independently denoted SOURCE "
        "definition under unchanged arbitrary original atom interpretations. Mixed evaluation uses the canonical "
        "Object restriction of the same original mixed atoms. No source-definition truth, unconditional equivalence, "
        "governing legal applicability, statutory meaning, training, corpus or release authority is supplied.")


def _reviewed_definition_realization_native_policy(shared=None, *, instance_identity_profile=None, definition_application_profile=None):
    _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)
    _reviewed_mixed_native_policy(shared, **_reviewed_source_use_kwargs(instance_identity_profile))
    _need((REVIEWED_DEFINITION_REALIZATION_BUILD_SCHEMA, REVIEWED_DEFINITION_REALIZATION_NATIVE_PROFILE,
           REVIEWED_DEFINITION_REALIZATION_RECEIPT_REPLAY_SCHEMA, REVIEWED_DEFINITION_REALIZATION_RECEIPT_REPLAY_PROFILE,
           REVIEWED_DEFINITION_REALIZATION_LIVE_SUCCESS_SCHEMA, REVIEWED_DEFINITION_REALIZATION_LIVE_SUCCESS_PROFILE) == (
        "legal-reviewed-definition-realization-native-build/v1", "replayed-reviewed-definition-realization-native-build/v1",
        "legal-reviewed-definition-realization-receipt-replay/v1", "current-reviewed-definition-realization-retained-observation/v1",
        "legal-reviewed-definition-realization-live-success/v1", "current-reviewed-definition-realization-live-native-owner-success/v1"),
        "closed realization native, retained and live profiles cannot alias another domain")
    if shared is not None:
        _need((shared.REVIEWED_DEFINITION_REALIZATION_SCHEMA, shared.REVIEWED_DEFINITION_REALIZATION_PROFILE,
               shared.REVIEWED_DEFINITION_REALIZATION_ROOT) == (
            "legal-reviewed-definition-realization-preparation/v1", "reviewed-unary-object-definition-realization/v1",
            "LegalReviewedDefinitionRealization"), "exact current constructed-model source profile required")
        shared._reviewed_definition_realization_policy(**_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))


def _reviewed_definition_realization_native_pins(owners, manifest, *, instance_identity_profile=None, definition_application_profile=None):
    global _REVIEWED_DEFINITION_REALIZATION_OPERATION_PINS, _REVIEWED_DEFINITION_APPLICATION_OPERATION_PINS
    shared = owners[4]
    _reviewed_definition_realization_native_policy(shared, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    if instance_identity_profile is not None or definition_application_profile is not None:
        _reviewed_definition_realization_native_manifest(manifest, shared, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    current = shared._reviewed_preservation_pins(shared._reviewed_mixed_preservation_owners())
    pins = _observed_producer_pins(owners, manifest)
    for path, expected in current.items():
        _need(path not in pins or pins[path] == expected, "realization native producer pin collision")
        pins[path] = expected
    # The selected transform adds canonical algebra to its producer closure.
    # Each fixed application domain retains its complete first-use pin latch;
    # switching a caller profile never resets or weakens either observation.
    if definition_application_profile is None:
        if _REVIEWED_DEFINITION_REALIZATION_OPERATION_PINS is None:
            _REVIEWED_DEFINITION_REALIZATION_OPERATION_PINS = dict(pins)
        expected = _REVIEWED_DEFINITION_REALIZATION_OPERATION_PINS
    else:
        if _REVIEWED_DEFINITION_APPLICATION_OPERATION_PINS is None:
            _REVIEWED_DEFINITION_APPLICATION_OPERATION_PINS = dict(pins)
        expected = _REVIEWED_DEFINITION_APPLICATION_OPERATION_PINS
    _need(pins == expected, "realization native operation owners changed since first use")
    return pins


def _reviewed_definition_realization_native_manifest(manifest, shared, *, instance_identity_profile=None, definition_application_profile=None):
    _reviewed_definition_realization_native_policy(shared, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    _reviewed_source_use_manifest(manifest, instance_identity_profile)
    _need(instance_identity_profile is not None or "instance_identity_profile" not in manifest,
          "legacy realization cannot acquire source-use identity")
    _need(manifest.get("schema") == shared.REVIEWED_DEFINITION_REALIZATION_SCHEMA
          and manifest.get("profile") == _reviewed_realization_domain(shared.REVIEWED_DEFINITION_REALIZATION_PROFILE, instance_identity_profile, definition_application_profile),
          "exact reviewed definition realization preparation required")
    application = _reviewed_definition_application_manifest(manifest, definition_application_profile)
    upstream = _reviewed_mixed_preservation_native_manifest(manifest["upstream_manifest"], shared,
        **_reviewed_source_use_kwargs(instance_identity_profile))
    for key in ("units", "reviewed_graph_sha256", "reviewed_admission_sha256", "declaration_sha256"):
        _need(manifest[key] == upstream[key], "complete original reviewed realization binding differs: " + key)
    selection = manifest["selection"]
    units = manifest["units"]
    if instance_identity_profile is not None:
        _need(selection.get("instance_identity_profile") == instance_identity_profile
              and selection.get("source_use_bindings") == [{"unit_id": unit["unit_id"],
                  "source_use_binding": unit["source_use_binding"],
                  "source_use_binding_sha256": unit["source_use_binding_sha256"]} for unit in units],
              "realization selection must bind every exact ordered physical source use")
    else:
        _need(not any(key in selection for key in ("instance_identity_profile", "source_use_bindings")),
              "legacy realization selection cannot acquire source-use identity")
    definitions = [unit for unit in units if unit["kind"] == "definition"]
    _need(len(definitions) == 1 and selection["definition_unit_id"] == definitions[0]["unit_id"]
          and selection["definition_instance_module"] == definitions[0]["instance_module"],
          "one exact original definition instance required")
    extra = [name for name in manifest["expected_modules"] if name not in upstream["expected_modules"]]
    _need(len(extra) == 2 and extra[1] == "LegalReviewedDefinitionRealization"
          and re.fullmatch(r"LegalReviewedDefinitionRealization\.Instance[0-9a-f]{64}", extra[0]),
          "one exact realization instance and distinct realization root required")
    instance, root = extra
    identity_payload = {"profile": _reviewed_realization_domain(shared.REVIEWED_DEFINITION_REALIZATION_PROFILE, instance_identity_profile, definition_application_profile),
        "upstream_preservation_sha256": manifest["reviewed_preservation_sha256"], "selection": selection}
    if application:
        shared._reviewed_definition_application_rows(application["definition_applications"], selection, units,
            definition_application_profile=definition_application_profile)
        identity_payload["definition_applications"] = application["definition_applications"]
    identity = _sha(_wire(identity_payload, MAX_RECORD_BYTES))
    _need(instance == "LegalReviewedDefinitionRealization.Instance" + identity,
          "exact explicitly selected realization theorem identity required")
    _need(manifest["expected_modules"] == upstream["expected_modules"] + extra
          and len(set(manifest["expected_modules"])) == len(manifest["expected_modules"]) <= 11,
          "complete original and new realization module population required")
    wanted_imports = dict(upstream["module_imports"])
    wanted_imports[instance] = [unit["instance_module"] for unit in units]
    wanted_imports[root] = ["LegalReviewedMixedNormPreservation", instance]
    _need(manifest["module_imports"] == wanted_imports,
          "exact original sub-DAG and realization import closure required")
    occurrences = selection["occurrences"]
    _need(type(occurrences) is list and 1 <= len(occurrences) <= MAX_REVIEWED_PRESERVATION_THEOREMS
          and all(type(row["ordinal"]) is int for row in occurrences)
          and [row["ordinal"] for row in occurrences] == list(range(len(occurrences)))
          and set(row["unit_id"] for row in occurrences) == set(unit["unit_id"] for unit in units if unit["kind"] == "norm")
          and all(row["definition_use_record_cid"] in upstream["definition_use_record_cids"] for row in occurrences),
          "every exact reviewed head occurrence and physical norm use required")
    suffixes = ["definition_body_source_exact", "definition_realized"]
    for ordinal in range(len(occurrences)):
        suffixes.extend(("occurrence_" + str(ordinal) + "_source_exact", "occurrence_" + str(ordinal) + "_matches_body"))
    suffixes.extend("unit_" + str(ordinal) + "_preservation_under_realization" for ordinal in range(len(units)))
    application_suffixes = [name for unit in units if unit["kind"] == "norm"
        for name in ("unit_" + str(unit["ordinal"]) + "_expansion_source_exact",
                     "unit_" + str(unit["ordinal"]) + "_whole_norm_definition_expansion")] if application else []
    if application:
        _need(application["definition_application_obligations"] == [instance + "." + name for name in application_suffixes],
              "exact ordered whole-norm application obligations required")
        suffixes.extend(application_suffixes)
    new = [instance + "." + suffix for suffix in suffixes]
    _need(manifest["realization_obligations"] == new
          and manifest["preservation_obligations"] == upstream["preservation_obligations"] + new
          and len(set(manifest["preservation_obligations"])) == len(manifest["preservation_obligations"]) <= 40
          and [row["theorem"] for row in manifest["theorem_bindings"]] == new,
          "exact complete source-equality, realization, occurrence and child obligations required")
    support = manifest["support_profile"]
    application_support = {"conditional_whole_norm_obligations", "source_definition_premise_required", "original_atom_interpretations_unchanged"}
    _need((all(support.get(key) is True for key in application_support) if application
           else not application_support.intersection(support)),
          "exact conditional application support scope required")
    _need(support["cross_unit_definition_application_proved"] is False
          and support["implicit_namespace_coercion"] is False and support["opaque_modal_rewrite"] is False
          and support["single_binder_quantifier_nodes_only"] is True
          and (support["max_units"], support["max_files"], support["max_modules"], support["max_obligations"],
               support["max_project_utf8_bytes"]) == (8, 78, 11, 40, 8 * 1024**2)
          and manifest["preparation_only"] is True and manifest["proof_status"] == "not_executed"
          and manifest["lean_compilation_status"] == "not_executed" and manifest["semantic_use_eligible"] is False
          and type(manifest["training_mask"]) is int and manifest["training_mask"] == 0
          and type(manifest["evaluation_gold_mask"]) is int and manifest["evaluation_gold_mask"] == 0,
          "realization preparation cannot claim native, semantic or corpus authority")
    return manifest


def _reviewed_definition_realization_receipt_binding(manifest, admission, *, instance_identity_profile=None, definition_application_profile=None):
    _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)
    _reviewed_source_use_manifest(manifest, instance_identity_profile)
    _need(instance_identity_profile is not None or "instance_identity_profile" not in manifest,
          "legacy realization receipt cannot acquire source-use identity")
    application = _reviewed_definition_application_manifest(manifest, definition_application_profile)
    upstream = manifest["upstream_manifest"]
    binding = {key: manifest[key] for key in _REVIEWED_DEFINITION_REALIZATION_BINDINGS
               if key in manifest}
    binding.update({key: upstream[key] for key in ("provenance_kind", "scope_record_cid",
        "interpretation_record_cid", "definition_use_record_cids")})
    return binding | application | _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile) | {"preservation_only": False, "constructed_model_only": definition_application_profile is None,
        "cross_unit_definition_application_proved": False, "statutory_meaning_proved": False,
        "release_ready": False, "full_formal_corpus_consistency_verified": False,
        "generic_lean_v3_receipt_substituted": False,
        "formal_assumptions": admission["formal_assumptions"], "formal_assumptions_proved": False}


def _reviewed_definition_realization_native_operation(preparation, preservation, graph, admission, args, kwargs, *,
        expected_realization_sha256, expected_preservation_sha256, expected_graph_sha256,
        expected_admission_sha256, toolchain, operation=None, instance_identity_profile=None, definition_application_profile=None):
    _reviewed_definition_realization_native_policy(**_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    document = _reviewed_preservation_native_document(preparation)
    upstream_document = _reviewed_preservation_native_document(preservation)
    for value, label in ((expected_realization_sha256, "complete realization preparation"),
            (expected_preservation_sha256, "complete original V3 preservation"),
            (expected_graph_sha256, "complete reviewed graph"), (expected_admission_sha256, "complete reviewed admission")):
        _pin(value, label)
    _need(_sha(_wire(document, MAX_PREPARATION_BYTES)) == expected_realization_sha256
          and _sha(_wire(upstream_document, MAX_PREPARATION_BYTES)) == expected_preservation_sha256,
          "independent realization or upstream preservation envelope differs")
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain)
          and len(args) == 4 and type(kwargs) is dict, "complete pinned realization replay inputs required")
    original = dict(graph=graph, admission=admission, args=list(args), kwargs=kwargs,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain)
    if instance_identity_profile is not None:
        original["instance_identity_profile"] = instance_identity_profile
    if definition_application_profile is not None:
        original["definition_application_profile"] = definition_application_profile
    _bound_tree({"preparation": document, "preservation": upstream_document, **original}, MAX_INPUT_BYTES, allow_bytes=True)
    owners = _owners(); shared = owners[4]
    _reviewed_definition_realization_native_policy(shared, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    _need(type(preparation) is type(preservation) is shared.ReviewedPreservationCorpusPreparation,
          "exact canonical realization and upstream preparation types required")
    reviewer = shared._reviewed_mixed_preservation_owners()[1]
    detached, commitment = reviewer.norm._snapshot(original)
    _, project_pin = reviewer.norm._snapshot(document)
    _, upstream_pin = reviewer.norm._snapshot(upstream_document)
    callbacks = tuple((name, _live_callable_state(globals()[name])) for name in (
        "_reviewed_definition_realization_native_policy", "_reviewed_mixed_native_policy",
        "_reviewed_definition_realization_native_manifest", "_reviewed_definition_realization_native_operation",
        "_reviewed_preservation_native_document", "_reviewed_definition_realization_native_pins",
        "_reviewed_definition_realization_receipt_binding", "_reviewed_source_use_kwargs",
        "_reviewed_source_use_domain", "_reviewed_source_use_manifest",
        "_reviewed_definition_application_kwargs", "_reviewed_realization_kwargs",
        "_reviewed_realization_domain", "_reviewed_definition_application_manifest",
        "_reviewed_definition_realization_scope"))
    shared_callbacks = tuple((name, _live_callable_state(getattr(shared, name))) for name in (
        "validate_reviewed_definition_realization_corpus_v1", "_reviewed_definition_realization_policy",
        "_reviewed_mixed_preservation_policy", "_reviewed_preservation_pins",
        *(("_reviewed_definition_application_rows", "_reviewed_definition_application_expression") if definition_application_profile is not None else ())))
    application_contract_callbacks = (tuple((name, _live_callable_state(getattr(shared.contracts, name)))
        for name in ("require_text", "require_int")) if definition_application_profile is not None else ())

    def fence():
        _reviewed_definition_realization_native_policy(shared, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
        _need(all(_live_callable_matches(globals().get(name), state) for name, state in callbacks)
              and all(_live_callable_matches(getattr(shared, name), state) for name, state in shared_callbacks)
              and all(_live_callable_matches(getattr(shared.contracts, name), state)
                      for name, state in application_contract_callbacks)
              and reviewer.norm._snapshot(original)[1] == commitment
              and reviewer.norm._snapshot(detached)[1] == commitment
              and reviewer.norm._snapshot(_reviewed_preservation_native_document(preparation))[1] == project_pin
              and reviewer.norm._snapshot(_reviewed_preservation_native_document(preservation))[1] == upstream_pin,
              "realization native source, upstream, callbacks or current observations changed")

    def replay():
        fence()
        checked = shared.validate_reviewed_definition_realization_corpus_v1(preparation, preservation,
            detached["graph"], detached["admission"], *detached["args"],
            expected_realization_sha256=expected_realization_sha256,
            expected_preservation_sha256=expected_preservation_sha256,
            expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
            toolchain=toolchain, **detached["kwargs"], **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
        _need(_reviewed_preservation_native_document(checked) == document,
              "current complete realization regeneration differs")
        _reviewed_definition_realization_native_manifest(checked.to_dict(), shared, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
        _reviewed_definition_realization_native_pins(owners, checked.to_dict(), **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
        fence()
        return checked
    checked = replay()
    if operation is None:
        return checked
    error = None

    def custody(stage, values):
        nonlocal error
        try:
            fence()
            _reviewed_definition_realization_native_pins(owners, checked.to_dict(), **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
        except (ValueError, TypeError, KeyError, OSError, UnicodeError, RecursionError) as failure:
            if stage in ("snapshot", "toolchain", "after_persistence"):
                raise
            error = {"type": type(failure).__name__, "message": str(failure)[:2048]}
        return error if stage == "before_persistence" else None
    result = operation(checked, replay, custody)
    fence()
    return result


def validate_reviewed_definition_realization_native_v1(preparation, preservation, graph, admission, *args,
        expected_realization_sha256, expected_preservation_sha256, expected_graph_sha256,
        expected_admission_sha256, toolchain, instance_identity_profile=None, definition_application_profile=None, **kwargs):
    """Replay complete current source/review and both exact project envelopes."""
    return _reviewed_definition_realization_native_operation(preparation, preservation, graph, admission, args, kwargs,
        expected_realization_sha256=expected_realization_sha256, expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))


def build_reviewed_definition_realization_native_v1(preparation, preservation, graph, admission, *args,
        expected_realization_sha256, expected_preservation_sha256, expected_graph_sha256,
        expected_admission_sha256, toolchain, lake_executable, output_directory,
        timeout_seconds=60, cancellation=None, instance_identity_profile=None, definition_application_profile=None, **kwargs):
    """Check all constructed-model obligations through the existing native runner."""
    _reviewed_definition_realization_native_policy(**_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
          and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")
    def execute(checked, replay, custody):
        return _build_validated_native(preparation, checked, replay=replay,
            expected_preparation_sha256=expected_realization_sha256, toolchain=toolchain,
            lake_executable=lake_executable, output_directory=output_directory,
            timeout_seconds=timeout_seconds, cancellation=cancellation,
            build_schema=REVIEWED_DEFINITION_REALIZATION_BUILD_SCHEMA,
            profile=_reviewed_realization_domain(REVIEWED_DEFINITION_REALIZATION_NATIVE_PROFILE, instance_identity_profile, definition_application_profile),
            flags=dict(PARENT_FALSE_FLAGS),
            receipt_binding=lambda manifest: _reviewed_definition_realization_receipt_binding(manifest, admission, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)),
            maximum_files=MAX_REVIEWED_PRESERVATION_FILES, maximum_modules=MAX_REVIEWED_PRESERVATION_MODULES,
            maximum_theorems=MAX_REVIEWED_PRESERVATION_THEOREMS,
            producer_pin_reader=(_reviewed_definition_realization_native_pins if not _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile) else
                lambda owners, manifest: _reviewed_definition_realization_native_pins(owners, manifest, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))),
            preparation_document_reader=_reviewed_preservation_native_document,
            closing_custody_guard=custody, receipt_scope=_reviewed_definition_realization_scope(definition_application_profile),
            frozen_authority=dict(AUTHORITY), **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    return _reviewed_definition_realization_native_operation(preparation, preservation, graph, admission, args, kwargs,
        expected_realization_sha256=expected_realization_sha256, expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, operation=execute, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))


def reviewed_definition_realization_receipt_bytes_v1(receipt, *, instance_identity_profile=None, definition_application_profile=None):
    _reviewed_definition_realization_native_policy(**_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    fields = _REVIEWED_DEFINITION_REALIZATION_CORE_FIELDS | (frozenset({"instance_identity_profile"}) if instance_identity_profile is not None else frozenset())
    fields |= (frozenset({"definition_application_profile", "definition_applications", "definition_application_obligations"})
               if definition_application_profile is not None else frozenset())
    _need(type(receipt) is dict and set(receipt) == fields
          and receipt.get("schema") == REVIEWED_DEFINITION_REALIZATION_BUILD_SCHEMA
          and receipt.get("profile") == _reviewed_realization_domain(REVIEWED_DEFINITION_REALIZATION_NATIVE_PROFILE, instance_identity_profile, definition_application_profile)
          and (instance_identity_profile is None or receipt.get("instance_identity_profile") == instance_identity_profile),
          "exact complete realization native receipt required")
    _reviewed_source_use_manifest(receipt, instance_identity_profile)
    _reviewed_definition_application_manifest(receipt, definition_application_profile)
    _need(receipt["constructed_model_only"] is (definition_application_profile is None),
          "exact conditional versus constructed-model receipt scope required")
    return _wire(receipt, MAX_RECEIPT_BYTES)


def reviewed_definition_realization_packet_sha256_v1(packet_files, *, instance_identity_profile=None, definition_application_profile=None):
    _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)
    contents, inventory = _reviewed_retained_packet(packet_files)
    return _sha(_wire(inventory, MAX_RECORD_BYTES))


def _reviewed_definition_realization_validate_adapter(preparation, graph, admission, *args,
        expected_preservation_sha256, realization_preservation, expected_upstream_preservation_sha256, instance_identity_profile=None, definition_application_profile=None, **kwargs):
    return validate_reviewed_definition_realization_native_v1(preparation, realization_preservation, graph, admission,
        *args, expected_realization_sha256=expected_preservation_sha256,
        expected_preservation_sha256=expected_upstream_preservation_sha256, **kwargs,
        **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))


def _reviewed_definition_realization_load_adapter(packet_files, preparation, graph, admission, *args,
        expected_preservation_sha256, realization_preservation, expected_upstream_preservation_sha256, instance_identity_profile=None, definition_application_profile=None, **kwargs):
    return load_reviewed_definition_realization_native_v1(packet_files, preparation, realization_preservation, graph, admission,
        *args, expected_realization_sha256=expected_preservation_sha256,
        expected_preservation_sha256=expected_upstream_preservation_sha256, **kwargs,
        **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))


def validate_reviewed_definition_realization_native_receipt_v1(receipt_raw, preparation, preservation, graph, admission, *args,
        packet_files, expected_receipt_sha256, expected_packet_sha256, expected_binary_sha256,
        expected_realization_sha256, expected_preservation_sha256, expected_graph_sha256,
        expected_admission_sha256, toolchain, observation_profile=_REVIEWED_REPLAY_ACTUAL, instance_identity_profile=None, definition_application_profile=None, **kwargs):
    """Replay this separate retained domain, without new native execution."""
    _reviewed_definition_realization_native_policy(**_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    return _validate_reviewed_native_retained_domain(receipt_raw, preparation, graph, admission, *args,
        reviewed_version=4, realization_preservation=preservation,
        expected_upstream_preservation_sha256=expected_preservation_sha256,
        packet_files=packet_files, expected_receipt_sha256=expected_receipt_sha256,
        expected_packet_sha256=expected_packet_sha256, expected_binary_sha256=expected_binary_sha256,
        expected_preservation_sha256=expected_realization_sha256, expected_graph_sha256=expected_graph_sha256,
        expected_admission_sha256=expected_admission_sha256, toolchain=toolchain,
        observation_profile=observation_profile, **kwargs, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))


def load_reviewed_definition_realization_native_v1(packet_files, preparation, preservation, graph, admission, *args, instance_identity_profile=None, definition_application_profile=None, **kwargs):
    _reviewed_definition_realization_native_policy(**_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
    contents, _ = _reviewed_retained_packet(packet_files)
    _need("build-receipt.json" in contents, "original complete realization native receipt required")
    return validate_reviewed_definition_realization_native_receipt_v1(contents["build-receipt.json"],
        preparation, preservation, graph, admission, *args, packet_files=packet_files, **kwargs,
        **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))


__all__ += ["REVIEWED_DEFINITION_REALIZATION_BUILD_SCHEMA", "REVIEWED_DEFINITION_REALIZATION_NATIVE_PROFILE",
    "REVIEWED_DEFINITION_REALIZATION_RECEIPT_REPLAY_SCHEMA", "REVIEWED_DEFINITION_REALIZATION_RECEIPT_REPLAY_PROFILE",
    "REVIEWED_DEFINITION_REALIZATION_LIVE_SUCCESS_SCHEMA", "REVIEWED_DEFINITION_REALIZATION_LIVE_SUCCESS_PROFILE",
    "validate_reviewed_definition_realization_native_v1", "build_reviewed_definition_realization_native_v1",
    "validate_reviewed_definition_realization_native_receipt_v1", "load_reviewed_definition_realization_native_v1",
    "reviewed_definition_realization_receipt_bytes_v1", "reviewed_definition_realization_packet_sha256_v1",
    "build_verified_reviewed_definition_realization_native_v1", "load_verified_reviewed_definition_realization_native_v1"]


def _reviewed_physical_retained_packet_v2(packet_files):
    _need(type(packet_files) in (tuple, list)
          and 1 <= len(packet_files) <= 2 * MAX_REVIEWED_PRESERVATION_FILES
              + MAX_REVIEWED_PRESERVATION_MODULES + 5,
          "bounded complete reviewed-native byte packet required")
    pairs, names = [], []
    for item in packet_files:
        _need(type(item) in (tuple, list) and len(item) == 2,
              "exact retained path/raw-byte pairs required")
        name, raw = item
        _need(type(name) is str and 0 < len(name) <= 512
              and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", name)
              and all(part not in (".", "..") for part in name.split("/"))
              and type(raw) is bytes, "closed retained paths and complete raw bytes required")
        names.append(name); pairs.append([name, raw])
    _need(names == sorted(set(names)), "sorted unique complete retained byte paths required")
    _need(all(len(raw) <= 8 * 1024**2 for _name, raw in pairs)
          and sum(len(raw) for _name, raw in pairs) <= 48 * 1024**2,
          "complete physical native packet byte envelope exceeded")
    _bound_tree(pairs, 64 * 1024**2, allow_bytes=True)
    inventory = [{"path": name, "bytes": len(raw), "sha256": _sha(raw)} for name, raw in pairs]
    return dict(pairs), inventory

REVIEWED_PHYSICAL_DEFINITION_REALIZATION_BUILD_SCHEMA = "legal-reviewed-physical-definition-realization-native-build/v2"
REVIEWED_PHYSICAL_DEFINITION_REALIZATION_NATIVE_PROFILE = "replayed-reviewed-physical-definition-realization-native-build/v2"
REVIEWED_PHYSICAL_DEFINITION_REALIZATION_RECEIPT_REPLAY_SCHEMA = "legal-reviewed-physical-definition-realization-receipt-replay/v2"
REVIEWED_PHYSICAL_DEFINITION_REALIZATION_RECEIPT_REPLAY_PROFILE = "current-reviewed-physical-definition-realization-retained-observation/v2"
REVIEWED_PHYSICAL_DEFINITION_REALIZATION_LIVE_SUCCESS_SCHEMA = "legal-reviewed-physical-definition-realization-live-success/v2"
REVIEWED_PHYSICAL_DEFINITION_REALIZATION_LIVE_SUCCESS_PROFILE = "current-reviewed-physical-definition-realization-live-native-owner-success/v2"
_PHYSICAL_REALIZATION_BINDINGS_V2 = frozenset({"physical_context", "physical_context_owner_sha256", "physical_context_sha256", "physical_bridge_version"})
_REVIEWED_PHYSICAL_DEFINITION_REALIZATION_BINDINGS = _REVIEWED_DEFINITION_REALIZATION_BINDINGS
_REVIEWED_PHYSICAL_DEFINITION_REALIZATION_OPERATION_PINS = None


def _reviewed_physical_definition_realization_native_policy(shared=None, *, instance_identity_profile=None, definition_application_profile=None):
    _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)
    _reviewed_mixed_native_policy(shared, **_reviewed_source_use_kwargs(instance_identity_profile))
    _need((REVIEWED_PHYSICAL_DEFINITION_REALIZATION_BUILD_SCHEMA, REVIEWED_PHYSICAL_DEFINITION_REALIZATION_NATIVE_PROFILE,
           REVIEWED_PHYSICAL_DEFINITION_REALIZATION_RECEIPT_REPLAY_SCHEMA, REVIEWED_PHYSICAL_DEFINITION_REALIZATION_RECEIPT_REPLAY_PROFILE,
           REVIEWED_PHYSICAL_DEFINITION_REALIZATION_LIVE_SUCCESS_SCHEMA, REVIEWED_PHYSICAL_DEFINITION_REALIZATION_LIVE_SUCCESS_PROFILE) == (
        "legal-reviewed-physical-definition-realization-native-build/v2", "replayed-reviewed-physical-definition-realization-native-build/v2",
        "legal-reviewed-physical-definition-realization-receipt-replay/v2", "current-reviewed-physical-definition-realization-retained-observation/v2",
        "legal-reviewed-physical-definition-realization-live-success/v2", "current-reviewed-physical-definition-realization-live-native-owner-success/v2"),
        "closed realization native, retained and live profiles cannot alias another domain")
    _need(instance_identity_profile == "reviewed-source-use/v1"
          and definition_application_profile == "whole-norm-definition-expansion/v1",
          "physical realization requires fixed joint source-use whole-norm profiles")
    if shared is not None:
        _need((shared.REVIEWED_PHYSICAL_REALIZATION_SCHEMA_V2, shared.REVIEWED_PHYSICAL_REALIZATION_PROFILE_V2,
               shared.REVIEWED_DEFINITION_REALIZATION_ROOT) == (
            "legal-reviewed-physical-definition-realization-preparation/v2",
            "reviewed-source-use-whole-norm-definition-physical-evidence-realization/v2",
            "LegalReviewedDefinitionRealization"), "exact current physical realization source profile required")
        shared._reviewed_physical_realization_policy_v2()
        shared._reviewed_joint_physical_profiles_v2(instance_identity_profile, definition_application_profile)
        shared._reviewed_definition_realization_policy(instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)


def _reviewed_physical_definition_realization_native_pins(owners, manifest, *, instance_identity_profile="reviewed-source-use/v1", definition_application_profile="whole-norm-definition-expansion/v1"):
    global _REVIEWED_PHYSICAL_DEFINITION_REALIZATION_OPERATION_PINS
    shared = owners[4]
    _reviewed_physical_definition_realization_native_policy(shared, instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)
    _reviewed_physical_definition_realization_native_manifest(manifest, shared, instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)
    pins = _observed_producer_pins(owners, manifest)
    current = shared._reviewed_preservation_pins(shared._reviewed_mixed_preservation_owners())
    from . import legal_release_coordinator_v1 as physical_owner
    physical_pin = _sha(Path(physical_owner.__file__).read_bytes())
    _need(physical_pin == manifest["physical_context_owner_sha256"], "physical context owner differs from current Source")
    current = {**current, str(Path(physical_owner.__file__).resolve()): physical_pin}
    for path, expected in current.items():
        _need(path not in pins or pins[path] == expected, "physical realization native producer pin collision")
        pins[path] = expected
    if _REVIEWED_PHYSICAL_DEFINITION_REALIZATION_OPERATION_PINS is None:
        _REVIEWED_PHYSICAL_DEFINITION_REALIZATION_OPERATION_PINS = dict(pins)
    _need(pins == _REVIEWED_PHYSICAL_DEFINITION_REALIZATION_OPERATION_PINS,
          "physical realization native operation owners changed since first use")
    return pins


def _reviewed_physical_definition_realization_native_manifest(manifest, shared, *, instance_identity_profile="reviewed-source-use/v1", definition_application_profile="whole-norm-definition-expansion/v1"):
    _reviewed_physical_definition_realization_native_policy(shared, instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)
    _reviewed_source_use_manifest(manifest, instance_identity_profile)
    _need(instance_identity_profile is not None or "instance_identity_profile" not in manifest,
          "legacy realization cannot acquire source-use identity")
    _need(manifest.get("schema") == shared.REVIEWED_PHYSICAL_REALIZATION_SCHEMA_V2
          and manifest.get("profile") == shared.REVIEWED_PHYSICAL_REALIZATION_PROFILE_V2,
          "exact reviewed definition realization preparation required")
    application = _reviewed_definition_application_manifest(manifest, definition_application_profile)
    upstream = _reviewed_mixed_preservation_native_manifest(manifest["upstream_manifest"], shared,
        **_reviewed_source_use_kwargs(instance_identity_profile))
    for key in ("units", "reviewed_graph_sha256", "reviewed_admission_sha256", "declaration_sha256"):
        _need(manifest[key] == upstream[key], "complete original reviewed realization binding differs: " + key)
    selection = manifest["selection"]
    units = manifest["units"]
    if instance_identity_profile is not None:
        _need(selection.get("instance_identity_profile") == instance_identity_profile
              and selection.get("source_use_bindings") == [{"unit_id": unit["unit_id"],
                  "source_use_binding": unit["source_use_binding"],
                  "source_use_binding_sha256": unit["source_use_binding_sha256"]} for unit in units],
              "realization selection must bind every exact ordered physical source use")
    else:
        _need(not any(key in selection for key in ("instance_identity_profile", "source_use_bindings")),
              "legacy realization selection cannot acquire source-use identity")
    definitions = [unit for unit in units if unit["kind"] == "definition"]
    _need(len(definitions) == 1 and selection["definition_unit_id"] == definitions[0]["unit_id"]
          and selection["definition_instance_module"] == definitions[0]["instance_module"],
          "one exact original definition instance required")
    extra = [name for name in manifest["expected_modules"] if name not in upstream["expected_modules"]]
    _need(len(extra) == 2 and extra[1] == "LegalReviewedDefinitionRealization"
          and re.fullmatch(r"LegalReviewedDefinitionRealization\.Instance[0-9a-f]{64}", extra[0]),
          "one exact realization instance and distinct realization root required")
    instance, root = extra
    identity_payload = {"profile": shared.REVIEWED_PHYSICAL_REALIZATION_PROFILE_V2,
        "upstream_preservation_sha256": manifest["reviewed_preservation_sha256"], "selection": selection}
    if application:
        shared._reviewed_definition_application_rows(application["definition_applications"], selection, units,
            definition_application_profile=definition_application_profile)
        identity_payload["definition_applications"] = application["definition_applications"]
    context = manifest.get("physical_context")
    _need(type(context) is dict and context.get("schema") == "legal-reviewed-physical-realization-context/v2"
          and context.get("profile") == "source-use-whole-norm-physical-crosswalk-evidence-only/v1"
          and context.get("instance_identity_profile") == instance_identity_profile
          and context.get("definition_application_profile") == definition_application_profile
          and manifest.get("physical_bridge_version") == 2
          and _sha(_wire(context, MAX_RECORD_BYTES)) == manifest.get("physical_context_sha256"),
          "complete explicit physical2 context binding required")
    _pin(manifest.get("physical_context_owner_sha256"), "physical context owner")
    identity_payload.update(physical_context_sha256=manifest["physical_context_sha256"],
        physical_context_owner_sha256=manifest["physical_context_owner_sha256"])
    identity = _sha(_wire(identity_payload, MAX_RECORD_BYTES))
    _need(instance == "LegalReviewedDefinitionRealization.Instance" + identity,
          "exact explicitly selected realization theorem identity required")
    _need(manifest["expected_modules"] == upstream["expected_modules"] + extra
          and len(set(manifest["expected_modules"])) == len(manifest["expected_modules"]) <= 11,
          "complete original and new realization module population required")
    wanted_imports = dict(upstream["module_imports"])
    wanted_imports[instance] = [unit["instance_module"] for unit in units]
    wanted_imports[root] = ["LegalReviewedMixedNormPreservation", instance]
    _need(manifest["module_imports"] == wanted_imports,
          "exact original sub-DAG and realization import closure required")
    occurrences = selection["occurrences"]
    _need(type(occurrences) is list and 1 <= len(occurrences) <= MAX_REVIEWED_PRESERVATION_THEOREMS
          and all(type(row["ordinal"]) is int for row in occurrences)
          and [row["ordinal"] for row in occurrences] == list(range(len(occurrences)))
          and set(row["unit_id"] for row in occurrences) == set(unit["unit_id"] for unit in units if unit["kind"] == "norm")
          and all(row["definition_use_record_cid"] in upstream["definition_use_record_cids"] for row in occurrences),
          "every exact reviewed head occurrence and physical norm use required")
    suffixes = ["definition_body_source_exact", "definition_realized"]
    for ordinal in range(len(occurrences)):
        suffixes.extend(("occurrence_" + str(ordinal) + "_source_exact", "occurrence_" + str(ordinal) + "_matches_body"))
    suffixes.extend("unit_" + str(ordinal) + "_preservation_under_realization" for ordinal in range(len(units)))
    application_suffixes = [name for unit in units if unit["kind"] == "norm"
        for name in ("unit_" + str(unit["ordinal"]) + "_expansion_source_exact",
                     "unit_" + str(unit["ordinal"]) + "_whole_norm_definition_expansion")] if application else []
    if application:
        _need(application["definition_application_obligations"] == [instance + "." + name for name in application_suffixes],
              "exact ordered whole-norm application obligations required")
        suffixes.extend(application_suffixes)
    new = [instance + "." + suffix for suffix in suffixes]
    _need(manifest["realization_obligations"] == new
          and manifest["preservation_obligations"] == upstream["preservation_obligations"] + new
          and len(set(manifest["preservation_obligations"])) == len(manifest["preservation_obligations"]) <= 40
          and [row["theorem"] for row in manifest["theorem_bindings"]] == new,
          "exact complete source-equality, realization, occurrence and child obligations required")
    support = manifest["support_profile"]
    application_support = {"conditional_whole_norm_obligations", "source_definition_premise_required", "original_atom_interpretations_unchanged"}
    _need((all(support.get(key) is True for key in application_support) if application
           else not application_support.intersection(support)),
          "exact conditional application support scope required")
    _need(support["cross_unit_definition_application_proved"] is False
          and support["implicit_namespace_coercion"] is False and support["opaque_modal_rewrite"] is False
          and support["single_binder_quantifier_nodes_only"] is True
          and (support["max_units"], support["max_files"], support["max_modules"], support["max_obligations"],
               support["max_project_utf8_bytes"]) == (8, 78, 11, 40, 8 * 1024**2)
          and manifest["preparation_only"] is True and manifest["proof_status"] == "not_executed"
          and manifest["lean_compilation_status"] == "not_executed" and manifest["semantic_use_eligible"] is False
          and type(manifest["training_mask"]) is int and manifest["training_mask"] == 0
          and type(manifest["evaluation_gold_mask"]) is int and manifest["evaluation_gold_mask"] == 0,
          "realization preparation cannot claim native, semantic or corpus authority")
    return manifest


def _reviewed_physical_definition_realization_receipt_binding(manifest, admission, *, instance_identity_profile="reviewed-source-use/v1", definition_application_profile="whole-norm-definition-expansion/v1"):
    _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)
    _reviewed_source_use_manifest(manifest, instance_identity_profile)
    _need(instance_identity_profile is not None or "instance_identity_profile" not in manifest,
          "legacy realization receipt cannot acquire source-use identity")
    application = _reviewed_definition_application_manifest(manifest, definition_application_profile)
    upstream = manifest["upstream_manifest"]
    binding = {key: manifest[key] for key in _REVIEWED_PHYSICAL_DEFINITION_REALIZATION_BINDINGS
               if key in manifest}
    binding.update({key: manifest[key] for key in _PHYSICAL_REALIZATION_BINDINGS_V2})
    binding.update({key: upstream[key] for key in ("provenance_kind", "scope_record_cid",
        "interpretation_record_cid", "definition_use_record_cids")})
    return binding | application | _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile) | {"preservation_only": False, "constructed_model_only": definition_application_profile is None,
        "cross_unit_definition_application_proved": False, "statutory_meaning_proved": False,
        "release_ready": False, "full_formal_corpus_consistency_verified": False,
        "generic_lean_v3_receipt_substituted": False,
        "formal_assumptions": admission["formal_assumptions"], "formal_assumptions_proved": False}


def _reviewed_physical_definition_realization_native_operation(preparation, preservation, graph, admission, args, kwargs, *,
        expected_realization_sha256, expected_preservation_sha256, expected_graph_sha256,
        expected_admission_sha256, toolchain, physical_request_raw, expected_physical_request_sha256, operation=None, instance_identity_profile="reviewed-source-use/v1", definition_application_profile="whole-norm-definition-expansion/v1"):
    _reviewed_physical_definition_realization_native_policy(instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)
    _pin(expected_physical_request_sha256, "complete physical realization request")
    _need(type(physical_request_raw) is bytes and 0 < len(physical_request_raw) <= MAX_INPUT_BYTES
          and _sha(physical_request_raw) == expected_physical_request_sha256,
          "complete original physical realization request bytes differ")
    document = _reviewed_preservation_native_document(preparation)
    upstream_document = _reviewed_preservation_native_document(preservation)
    for value, label in ((expected_realization_sha256, "complete realization preparation"),
            (expected_preservation_sha256, "complete original V3 preservation"),
            (expected_graph_sha256, "complete reviewed graph"), (expected_admission_sha256, "complete reviewed admission")):
        _pin(value, label)
    _need(_sha(_wire(document, MAX_PREPARATION_BYTES)) == expected_realization_sha256
          and _sha(_wire(upstream_document, MAX_PREPARATION_BYTES)) == expected_preservation_sha256,
          "independent realization or upstream preservation envelope differs")
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain)
          and len(args) == 4 and type(kwargs) is dict, "complete pinned realization replay inputs required")
    original = dict(graph=graph, admission=admission, args=list(args), kwargs=kwargs,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, physical_request_raw=physical_request_raw,
        expected_physical_request_sha256=expected_physical_request_sha256)
    if instance_identity_profile is not None:
        original["instance_identity_profile"] = instance_identity_profile
    if definition_application_profile is not None:
        original["definition_application_profile"] = definition_application_profile
    _bound_tree({"preparation": document, "preservation": upstream_document, **original}, MAX_INPUT_BYTES, allow_bytes=True)
    owners = _owners(); shared = owners[4]
    _reviewed_physical_definition_realization_native_policy(shared, instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)
    _need(type(preparation) is type(preservation) is shared.ReviewedPreservationCorpusPreparation,
          "exact canonical realization and upstream preparation types required")
    reviewer = shared._reviewed_mixed_preservation_owners()[1]
    detached, commitment = reviewer.norm._snapshot(original)
    _, project_pin = reviewer.norm._snapshot(document)
    _, upstream_pin = reviewer.norm._snapshot(upstream_document)
    callbacks = tuple((name, _live_callable_state(globals()[name])) for name in (
        "_reviewed_physical_definition_realization_native_policy", "_reviewed_mixed_native_policy",
        "_reviewed_physical_definition_realization_native_manifest", "_reviewed_physical_definition_realization_native_operation",
        "_reviewed_preservation_native_document", "_reviewed_physical_definition_realization_native_pins",
        "_reviewed_physical_definition_realization_receipt_binding", "_reviewed_source_use_kwargs",
        "_reviewed_source_use_domain", "_reviewed_source_use_manifest",
        "_reviewed_definition_application_kwargs", "_reviewed_realization_kwargs",
        "_reviewed_realization_domain", "_reviewed_definition_application_manifest",
        "_reviewed_definition_realization_scope"))
    shared_callbacks = tuple((name, _live_callable_state(getattr(shared, name))) for name in (
        "validate_reviewed_physical_definition_realization_corpus_v2", "_reviewed_physical_realization_policy_v2",
        "_reviewed_joint_physical_profiles_v2", "_reviewed_definition_realization_policy",
        "_reviewed_mixed_preservation_policy", "_reviewed_preservation_pins",
        *(("_reviewed_definition_application_rows", "_reviewed_definition_application_expression") if definition_application_profile is not None else ())))
    application_contract_callbacks = (tuple((name, _live_callable_state(getattr(shared.contracts, name)))
        for name in ("require_text", "require_int")) if definition_application_profile is not None else ())

    def fence():
        _reviewed_physical_definition_realization_native_policy(shared, instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)
        _need(all(_live_callable_matches(globals().get(name), state) for name, state in callbacks)
              and all(_live_callable_matches(getattr(shared, name), state) for name, state in shared_callbacks)
              and all(_live_callable_matches(getattr(shared.contracts, name), state)
                      for name, state in application_contract_callbacks)
              and reviewer.norm._snapshot(original)[1] == commitment
              and reviewer.norm._snapshot(detached)[1] == commitment
              and reviewer.norm._snapshot(_reviewed_preservation_native_document(preparation))[1] == project_pin
              and reviewer.norm._snapshot(_reviewed_preservation_native_document(preservation))[1] == upstream_pin,
              "realization native source, upstream, callbacks or current observations changed")

    def replay():
        fence()
        checked = shared.validate_reviewed_physical_definition_realization_corpus_v2(preparation, preservation,
            detached["graph"], detached["admission"], *detached["args"],
            expected_realization_sha256=expected_realization_sha256,
            expected_preservation_sha256=expected_preservation_sha256,
            expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
            toolchain=toolchain, physical_request_raw=detached["physical_request_raw"],
            expected_physical_request_sha256=detached["expected_physical_request_sha256"], **detached["kwargs"], instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)
        _need(_reviewed_preservation_native_document(checked) == document,
              "current complete realization regeneration differs")
        _reviewed_physical_definition_realization_native_manifest(checked.to_dict(), shared, instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)
        _reviewed_physical_definition_realization_native_pins(owners, checked.to_dict(), instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)
        fence()
        return checked
    checked = replay()
    if operation is None:
        return checked
    error = None

    def custody(stage, values):
        nonlocal error
        try:
            fence()
            _reviewed_physical_definition_realization_native_pins(owners, checked.to_dict(), instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)
        except (ValueError, TypeError, KeyError, OSError, UnicodeError, RecursionError) as failure:
            if stage in ("snapshot", "toolchain", "after_persistence"):
                raise
            error = {"type": type(failure).__name__, "message": str(failure)[:2048]}
        return error if stage == "before_persistence" else None
    result = operation(checked, replay, custody)
    fence()
    return result


def validate_reviewed_physical_definition_realization_native_v2(preparation, preservation, graph, admission, *args,
        expected_realization_sha256, expected_preservation_sha256, expected_graph_sha256,
        expected_admission_sha256, toolchain, physical_request_raw, expected_physical_request_sha256, instance_identity_profile, definition_application_profile, **kwargs):
    """Replay complete current source/review and both exact project envelopes."""
    return _reviewed_physical_definition_realization_native_operation(preparation, preservation, graph, admission, args, kwargs,
        expected_realization_sha256=expected_realization_sha256, expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, physical_request_raw=physical_request_raw,
        expected_physical_request_sha256=expected_physical_request_sha256, instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)


def build_reviewed_physical_definition_realization_native_v2(preparation, preservation, graph, admission, *args,
        expected_realization_sha256, expected_preservation_sha256, expected_graph_sha256,
        expected_admission_sha256, toolchain, lake_executable, output_directory,
        physical_request_raw, expected_physical_request_sha256, timeout_seconds=60, cancellation=None, instance_identity_profile, definition_application_profile, **kwargs):
    """Check all constructed-model obligations through the existing native runner."""
    _reviewed_physical_definition_realization_native_policy(instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)
    _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
          and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")
    def execute(checked, replay, custody):
        return _build_validated_native(preparation, checked, replay=replay,
            expected_preparation_sha256=expected_realization_sha256, toolchain=toolchain,
            lake_executable=lake_executable, output_directory=output_directory,
            timeout_seconds=timeout_seconds, cancellation=cancellation,
            build_schema=REVIEWED_PHYSICAL_DEFINITION_REALIZATION_BUILD_SCHEMA,
            profile=_reviewed_realization_domain(REVIEWED_PHYSICAL_DEFINITION_REALIZATION_NATIVE_PROFILE, instance_identity_profile, definition_application_profile),
            flags=dict(PARENT_FALSE_FLAGS),
            receipt_binding=lambda manifest: _reviewed_physical_definition_realization_receipt_binding(manifest, admission, instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile),
            maximum_files=MAX_REVIEWED_PRESERVATION_FILES, maximum_modules=MAX_REVIEWED_PRESERVATION_MODULES,
            maximum_theorems=MAX_REVIEWED_PRESERVATION_THEOREMS,
            producer_pin_reader=(_reviewed_physical_definition_realization_native_pins if not _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile) else
                lambda owners, manifest: _reviewed_physical_definition_realization_native_pins(owners, manifest, instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)),
            preparation_document_reader=_reviewed_preservation_native_document,
            closing_custody_guard=custody, receipt_scope=_reviewed_definition_realization_scope(definition_application_profile),
            frozen_authority=dict(AUTHORITY), instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)
    return _reviewed_physical_definition_realization_native_operation(preparation, preservation, graph, admission, args, kwargs,
        expected_realization_sha256=expected_realization_sha256, expected_preservation_sha256=expected_preservation_sha256,
        expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
        toolchain=toolchain, operation=execute, physical_request_raw=physical_request_raw,
        expected_physical_request_sha256=expected_physical_request_sha256, instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)


def reviewed_physical_definition_realization_receipt_bytes_v2(receipt, *, instance_identity_profile="reviewed-source-use/v1", definition_application_profile="whole-norm-definition-expansion/v1"):
    _reviewed_physical_definition_realization_native_policy(instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)
    fields = (_REVIEWED_DEFINITION_REALIZATION_CORE_FIELDS | _PHYSICAL_REALIZATION_BINDINGS_V2) | (frozenset({"instance_identity_profile"}) if instance_identity_profile is not None else frozenset())
    fields |= (frozenset({"definition_application_profile", "definition_applications", "definition_application_obligations"})
               if definition_application_profile is not None else frozenset())
    _need(type(receipt) is dict and set(receipt) == fields
          and receipt.get("schema") == REVIEWED_PHYSICAL_DEFINITION_REALIZATION_BUILD_SCHEMA
          and receipt.get("profile") == _reviewed_realization_domain(REVIEWED_PHYSICAL_DEFINITION_REALIZATION_NATIVE_PROFILE, instance_identity_profile, definition_application_profile)
          and (instance_identity_profile is None or receipt.get("instance_identity_profile") == instance_identity_profile),
          "exact complete realization native receipt required")
    _reviewed_source_use_manifest(receipt, instance_identity_profile)
    _reviewed_definition_application_manifest(receipt, definition_application_profile)
    _need(receipt["constructed_model_only"] is (definition_application_profile is None),
          "exact conditional versus constructed-model receipt scope required")
    return _wire(receipt, MAX_RECEIPT_BYTES)


def reviewed_physical_definition_realization_packet_sha256_v2(packet_files, *, instance_identity_profile="reviewed-source-use/v1", definition_application_profile="whole-norm-definition-expansion/v1"):
    _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)
    contents, inventory = _reviewed_physical_retained_packet_v2(packet_files)
    return _sha(_wire(inventory, MAX_RECORD_BYTES))


def _reviewed_physical_definition_realization_validate_adapter(preparation, graph, admission, *args,
        expected_preservation_sha256, realization_preservation, expected_upstream_preservation_sha256, physical_request_raw, expected_physical_request_sha256, instance_identity_profile="reviewed-source-use/v1", definition_application_profile="whole-norm-definition-expansion/v1", **kwargs):
    return validate_reviewed_physical_definition_realization_native_v2(preparation, realization_preservation, graph, admission,
        *args, expected_realization_sha256=expected_preservation_sha256,
        expected_preservation_sha256=expected_upstream_preservation_sha256, physical_request_raw=physical_request_raw,
        expected_physical_request_sha256=expected_physical_request_sha256, **kwargs,
        instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)


def _reviewed_physical_definition_realization_load_adapter(packet_files, preparation, graph, admission, *args,
        expected_preservation_sha256, realization_preservation, expected_upstream_preservation_sha256, physical_request_raw, expected_physical_request_sha256, instance_identity_profile="reviewed-source-use/v1", definition_application_profile="whole-norm-definition-expansion/v1", **kwargs):
    return load_reviewed_physical_definition_realization_native_v2(packet_files, preparation, realization_preservation, graph, admission,
        *args, expected_realization_sha256=expected_preservation_sha256,
        expected_preservation_sha256=expected_upstream_preservation_sha256, physical_request_raw=physical_request_raw,
        expected_physical_request_sha256=expected_physical_request_sha256, **kwargs,
        instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)


def validate_reviewed_physical_definition_realization_native_receipt_v2(receipt_raw, preparation, preservation, graph, admission, *args,
        packet_files, expected_receipt_sha256, expected_packet_sha256, expected_binary_sha256,
        expected_realization_sha256, expected_preservation_sha256, expected_graph_sha256,
        expected_admission_sha256, toolchain, physical_request_raw, expected_physical_request_sha256, observation_profile=_REVIEWED_REPLAY_ACTUAL, instance_identity_profile, definition_application_profile, **kwargs):
    """Replay this separate retained domain, without new native execution."""
    _reviewed_physical_definition_realization_native_policy(instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)
    return _validate_reviewed_native_retained_domain(receipt_raw, preparation, graph, admission, *args,
        reviewed_version=5, realization_preservation=preservation, physical_request_raw=physical_request_raw,
        expected_physical_request_sha256=expected_physical_request_sha256,
        expected_upstream_preservation_sha256=expected_preservation_sha256,
        packet_files=packet_files, expected_receipt_sha256=expected_receipt_sha256,
        expected_packet_sha256=expected_packet_sha256, expected_binary_sha256=expected_binary_sha256,
        expected_preservation_sha256=expected_realization_sha256, expected_graph_sha256=expected_graph_sha256,
        expected_admission_sha256=expected_admission_sha256, toolchain=toolchain,
        observation_profile=observation_profile, **kwargs, instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)


def load_reviewed_physical_definition_realization_native_v2(packet_files, preparation, preservation, graph, admission, *args, physical_request_raw, expected_physical_request_sha256, instance_identity_profile, definition_application_profile, **kwargs):
    _reviewed_physical_definition_realization_native_policy(instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)
    contents, _ = _reviewed_physical_retained_packet_v2(packet_files)
    _need("build-receipt.json" in contents, "original complete realization native receipt required")
    return validate_reviewed_physical_definition_realization_native_receipt_v2(contents["build-receipt.json"],
        preparation, preservation, graph, admission, *args, packet_files=packet_files,
        physical_request_raw=physical_request_raw, expected_physical_request_sha256=expected_physical_request_sha256, **kwargs,
        instance_identity_profile=instance_identity_profile, definition_application_profile=definition_application_profile)

__all__ += ['_reviewed_physical_definition_realization_native_policy', '_reviewed_physical_definition_realization_native_pins', '_reviewed_physical_definition_realization_native_manifest', '_reviewed_physical_definition_realization_receipt_binding', '_reviewed_physical_definition_realization_native_operation', 'validate_reviewed_physical_definition_realization_native_v2', 'build_reviewed_physical_definition_realization_native_v2', 'reviewed_physical_definition_realization_receipt_bytes_v2', 'reviewed_physical_definition_realization_packet_sha256_v2', '_reviewed_physical_definition_realization_validate_adapter', '_reviewed_physical_definition_realization_load_adapter', 'validate_reviewed_physical_definition_realization_native_receipt_v2', 'load_reviewed_physical_definition_realization_native_v2', 'build_verified_reviewed_physical_definition_realization_native_v2', 'load_verified_reviewed_physical_definition_realization_native_v2']

# Capture callable objects AND code/default bindings at import completion. The
# existing public profiles remain unchanged and never consult these guards.
_LIVE_NATIVE_FUNCTIONS = tuple((name, _live_callable_state(value))
    for name, value in tuple(globals().items())
    if type(value) is types.FunctionType and value.__module__ == __name__)
_LIVE_HANDLE_CLASS = VerifiedReviewedPreservationNativeSuccess
_LIVE_HANDLE_METACLASS = type(_LIVE_HANDLE_CLASS)
_LIVE_HANDLE_BASES = _LIVE_HANDLE_CLASS.__bases__
_LIVE_HANDLE_KEYS = frozenset(vars(_LIVE_HANDLE_CLASS))
_LIVE_HANDLE_FUNCTIONS = tuple((name, _live_callable_state(_live_descriptor_function(value)))
    for name, value in vars(_LIVE_HANDLE_CLASS).items()
    if type(_live_descriptor_function(value)) is types.FunctionType)
_LIVE_POPEN_CLASS = subprocess.Popen
_LIVE_POPEN_METACLASS = type(_LIVE_POPEN_CLASS)
_LIVE_POPEN_BASES = _LIVE_POPEN_CLASS.__bases__
_LIVE_POPEN_KEYS = frozenset(vars(_LIVE_POPEN_CLASS))
_LIVE_POPEN_FUNCTIONS = tuple((name, _live_callable_state(_live_descriptor_function(value)))
    for name, value in vars(_LIVE_POPEN_CLASS).items()
    if type(_live_descriptor_function(value)) is types.FunctionType)


# The original integrity checker must not enforce its own predicate's identity
# through that same mutable global predicate. Keep the qualified implementation
# and its import-time callable states in this independent closure. This protects
# cooperative callable drift; it does not claim hostile Python memory isolation.
def _bind_live_success_independent_guard_v1():
    """Bind both guard directions to actual callbacks, never mutable aliases."""
    original_guard = _live_success_guard
    original_build_core = _build_verified_reviewed_norm_preservation_native
    original_load_core = _load_verified_reviewed_norm_preservation_native
    original_handle_entry = _live_handle_entry
    function_type = type(original_guard)
    original_guard_code, original_guard_defaults = original_guard.__code__, original_guard.__defaults__
    original_guard_keywords = tuple(sorted((original_guard.__kwdefaults__ or {}).items()))
    issued_handles = _LIVE_SUCCESS_HANDLES
    issued_handle_class = VerifiedReviewedPreservationNativeSuccess

    def verify_native_functions():
        for name, state in states:
            function = globals().get(name)
            if (type(function) is not function_type or function is not state[0]
                    or function.__code__ is not state[1] or function.__defaults__ is not state[2]):
                raise ValueError("live success callable bindings changed: independent " + name)
            current = function.__kwdefaults__ or {}
            if (set(current) != {key for key, _ in state[3]}
                    or not all(current[key] is value for key, value in state[3])):
                raise ValueError("live success callable bindings changed: independent defaults " + name)

    def integrity(owners=None, *, reviewed_version=2):
        if (original_guard.__code__ is not original_guard_code
                or original_guard.__defaults__ is not original_guard_defaults
                or set(original_guard.__kwdefaults__ or {}) != {key for key, _ in original_guard_keywords}
                or not all((original_guard.__kwdefaults__ or {})[key] is value
                           for key, value in original_guard_keywords)):
            raise ValueError("live success callable bindings changed: captured original guard")
        verify_native_functions()
        result = original_guard(owners, reviewed_version=reviewed_version)
        # A genuine source read or callback may return after changing globals.
        # Check the immutable callback set again before the next stage proceeds.
        verify_native_functions()
        return result

    def guarded(owners=None, *, reviewed_version=2):
        return integrity(owners, reviewed_version=reviewed_version)

    def entry_guard(reviewed_version):
        if (globals().get("_live_success_guard") is not guarded
                or guarded.__code__ is not guard_code
                or guarded.__defaults__ is not guard_defaults
                or set(guarded.__kwdefaults__ or {}) != {key for key, _ in guard_keywords}
                or not all((guarded.__kwdefaults__ or {})[key] is value
                           for key, value in guard_keywords)):
            raise ValueError("live success callable bindings changed: independent guard")
        return guarded(reviewed_version=reviewed_version)

    guard_code, guard_defaults = guarded.__code__, guarded.__defaults__
    guard_keywords = tuple(sorted((guarded.__kwdefaults__ or {}).items()))
    persistence_function = _live_postrun_persistence_trusted
    persistence_state = (persistence_function, persistence_function.__code__, persistence_function.__defaults__,
                         tuple(sorted((persistence_function.__kwdefaults__ or {}).items())))
    integrity_state = (integrity, integrity.__code__, integrity.__defaults__,
                       tuple(sorted((integrity.__kwdefaults__ or {}).items())), persistence_state)
    entry_code, entry_defaults = entry_guard.__code__, entry_guard.__defaults__

    handle_code, handle_defaults = original_handle_entry.__code__, original_handle_entry.__defaults__
    handle_keywords = tuple(sorted((original_handle_entry.__kwdefaults__ or {}).items()))

    def build_verified_reviewed_norm_preservation_native_v2(preparation, graph, admission, *args,
            expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256,
            toolchain, lake_executable, output_directory, timeout_seconds=60, cancellation=None, instance_identity_profile=None, **kwargs):
        """Issue this explicit reviewed domain through the shared original live engine."""
        _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
              and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")
        if (entry_guard.__code__ is not entry_code
                or entry_guard.__defaults__ is not entry_defaults
                or guarded.__code__ is not guard_code
                or guarded.__defaults__ is not guard_defaults
                or set(guarded.__kwdefaults__ or {}) != {key for key, _ in guard_keywords}
                or not all((guarded.__kwdefaults__ or {})[key] is value
                           for key, value in guard_keywords)):
            raise ValueError("live success callable bindings changed: independent guard")
        if "_live_integrity_state" in kwargs:
            raise ValueError("private live integrity hook cannot be supplied")
        entry_guard(2)
        result = original_build_core(
            preparation, graph, admission, *args, _live_integrity_state=integrity_state, reviewed_version=2,
            expected_preservation_sha256=expected_preservation_sha256,
            expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
            toolchain=toolchain, lake_executable=lake_executable, output_directory=output_directory,
            timeout_seconds=timeout_seconds, cancellation=cancellation, **kwargs, **_reviewed_source_use_kwargs(instance_identity_profile))
        try:
            if (integrity.__code__ is not integrity_state[1]
                    or integrity.__defaults__ is not integrity_state[2]
                    or set(integrity.__kwdefaults__ or {}) != {key for key, _ in integrity_state[3]}
                    or not all((integrity.__kwdefaults__ or {})[key] is value
                               for key, value in integrity_state[3])):
                raise ValueError("live success callable bindings changed: captured public integrity")
            integrity(reviewed_version=2)
        except BaseException:
            if type(result) is issued_handle_class:
                issued_handles.pop(result, None)
            raise
        return result

    def load_verified_reviewed_norm_preservation_native_v2(handle, packet_files, preparation, graph, admission, *args,
            expected_receipt_sha256, expected_packet_sha256, expected_binary_sha256,
            expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain, instance_identity_profile=None, **kwargs):
        """Join this explicit domain's original live issuance without new execution."""
        if (globals().get("_live_handle_entry") is not original_handle_entry
                or original_handle_entry.__code__ is not handle_code
                or original_handle_entry.__defaults__ is not handle_defaults
                or set(original_handle_entry.__kwdefaults__ or {}) != {key for key, _ in handle_keywords}
                or not all((original_handle_entry.__kwdefaults__ or {})[key] is value
                           for key, value in handle_keywords)):
            raise ValueError("live success callable bindings changed: independent _live_handle_entry")
        original_handle_entry(handle, reviewed_version=2, **_reviewed_source_use_kwargs(instance_identity_profile))
        if (entry_guard.__code__ is not entry_code
                or entry_guard.__defaults__ is not entry_defaults
                or guarded.__code__ is not guard_code
                or guarded.__defaults__ is not guard_defaults
                or set(guarded.__kwdefaults__ or {}) != {key for key, _ in guard_keywords}
                or not all((guarded.__kwdefaults__ or {})[key] is value
                           for key, value in guard_keywords)):
            raise ValueError("live success callable bindings changed: independent guard")
        if "_live_integrity_state" in kwargs:
            raise ValueError("private live integrity hook cannot be supplied")
        entry_guard(2)
        result = original_load_core(
            handle, packet_files, preparation, graph, admission, *args, _live_integrity_state=integrity_state, reviewed_version=2,
            expected_receipt_sha256=expected_receipt_sha256, expected_packet_sha256=expected_packet_sha256,
            expected_binary_sha256=expected_binary_sha256,
            expected_preservation_sha256=expected_preservation_sha256,
            expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
            toolchain=toolchain, **kwargs, **_reviewed_source_use_kwargs(instance_identity_profile))
        if (integrity.__code__ is not integrity_state[1]
                or integrity.__defaults__ is not integrity_state[2]
                or set(integrity.__kwdefaults__ or {}) != {key for key, _ in integrity_state[3]}
                or not all((integrity.__kwdefaults__ or {})[key] is value
                           for key, value in integrity_state[3])):
            raise ValueError("live success callable bindings changed: captured public integrity")
        integrity(reviewed_version=2)
        return result

    def build_verified_reviewed_norm_preservation_native_v3(preparation, graph, admission, *args,
            expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256,
            toolchain, lake_executable, output_directory, timeout_seconds=60, cancellation=None, instance_identity_profile=None, **kwargs):
        """Issue this explicit reviewed domain through the shared original live engine."""
        _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
              and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")
        if (entry_guard.__code__ is not entry_code
                or entry_guard.__defaults__ is not entry_defaults
                or guarded.__code__ is not guard_code
                or guarded.__defaults__ is not guard_defaults
                or set(guarded.__kwdefaults__ or {}) != {key for key, _ in guard_keywords}
                or not all((guarded.__kwdefaults__ or {})[key] is value
                           for key, value in guard_keywords)):
            raise ValueError("live success callable bindings changed: independent guard")
        if "_live_integrity_state" in kwargs:
            raise ValueError("private live integrity hook cannot be supplied")
        entry_guard(3)
        result = original_build_core(
            preparation, graph, admission, *args, _live_integrity_state=integrity_state, reviewed_version=3,
            expected_preservation_sha256=expected_preservation_sha256,
            expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
            toolchain=toolchain, lake_executable=lake_executable, output_directory=output_directory,
            timeout_seconds=timeout_seconds, cancellation=cancellation, **kwargs, **_reviewed_source_use_kwargs(instance_identity_profile))
        try:
            if (integrity.__code__ is not integrity_state[1]
                    or integrity.__defaults__ is not integrity_state[2]
                    or set(integrity.__kwdefaults__ or {}) != {key for key, _ in integrity_state[3]}
                    or not all((integrity.__kwdefaults__ or {})[key] is value
                               for key, value in integrity_state[3])):
                raise ValueError("live success callable bindings changed: captured public integrity")
            integrity(reviewed_version=3)
        except BaseException:
            if type(result) is issued_handle_class:
                issued_handles.pop(result, None)
            raise
        return result

    def load_verified_reviewed_norm_preservation_native_v3(handle, packet_files, preparation, graph, admission, *args,
            expected_receipt_sha256, expected_packet_sha256, expected_binary_sha256,
            expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain, instance_identity_profile=None, **kwargs):
        """Join this explicit domain's original live issuance without new execution."""
        if (globals().get("_live_handle_entry") is not original_handle_entry
                or original_handle_entry.__code__ is not handle_code
                or original_handle_entry.__defaults__ is not handle_defaults
                or set(original_handle_entry.__kwdefaults__ or {}) != {key for key, _ in handle_keywords}
                or not all((original_handle_entry.__kwdefaults__ or {})[key] is value
                           for key, value in handle_keywords)):
            raise ValueError("live success callable bindings changed: independent _live_handle_entry")
        original_handle_entry(handle, reviewed_version=3, **_reviewed_source_use_kwargs(instance_identity_profile))
        if (entry_guard.__code__ is not entry_code
                or entry_guard.__defaults__ is not entry_defaults
                or guarded.__code__ is not guard_code
                or guarded.__defaults__ is not guard_defaults
                or set(guarded.__kwdefaults__ or {}) != {key for key, _ in guard_keywords}
                or not all((guarded.__kwdefaults__ or {})[key] is value
                           for key, value in guard_keywords)):
            raise ValueError("live success callable bindings changed: independent guard")
        if "_live_integrity_state" in kwargs:
            raise ValueError("private live integrity hook cannot be supplied")
        entry_guard(3)
        result = original_load_core(
            handle, packet_files, preparation, graph, admission, *args, _live_integrity_state=integrity_state, reviewed_version=3,
            expected_receipt_sha256=expected_receipt_sha256, expected_packet_sha256=expected_packet_sha256,
            expected_binary_sha256=expected_binary_sha256,
            expected_preservation_sha256=expected_preservation_sha256,
            expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
            toolchain=toolchain, **kwargs, **_reviewed_source_use_kwargs(instance_identity_profile))
        if (integrity.__code__ is not integrity_state[1]
                or integrity.__defaults__ is not integrity_state[2]
                or set(integrity.__kwdefaults__ or {}) != {key for key, _ in integrity_state[3]}
                or not all((integrity.__kwdefaults__ or {})[key] is value
                           for key, value in integrity_state[3])):
            raise ValueError("live success callable bindings changed: captured public integrity")
        integrity(reviewed_version=3)
        return result

    def build_verified_reviewed_definition_realization_native_v1(preparation, preservation, graph, admission, *args,
                expected_realization_sha256, expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256,
                toolchain, lake_executable, output_directory, timeout_seconds=60, cancellation=None, instance_identity_profile=None, definition_application_profile=None, **kwargs):
            """Issue this explicit reviewed domain through the shared original live engine."""
            _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)
            _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
                  and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")
            if (entry_guard.__code__ is not entry_code
                    or entry_guard.__defaults__ is not entry_defaults
                    or guarded.__code__ is not guard_code
                    or guarded.__defaults__ is not guard_defaults
                    or set(guarded.__kwdefaults__ or {}) != {key for key, _ in guard_keywords}
                    or not all((guarded.__kwdefaults__ or {})[key] is value
                               for key, value in guard_keywords)):
                raise ValueError("live success callable bindings changed: independent guard")
            if "_live_integrity_state" in kwargs:
                raise ValueError("private live integrity hook cannot be supplied")
            entry_guard(4)
            result = original_build_core(
                preparation, graph, admission, *args, _live_integrity_state=integrity_state, reviewed_version=4,
                expected_preservation_sha256=expected_realization_sha256,
                realization_preservation=preservation, expected_upstream_preservation_sha256=expected_preservation_sha256,
                expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
                toolchain=toolchain, lake_executable=lake_executable, output_directory=output_directory,
                timeout_seconds=timeout_seconds, cancellation=cancellation, **kwargs,
                **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
            try:
                if (integrity.__code__ is not integrity_state[1]
                        or integrity.__defaults__ is not integrity_state[2]
                        or set(integrity.__kwdefaults__ or {}) != {key for key, _ in integrity_state[3]}
                        or not all((integrity.__kwdefaults__ or {})[key] is value
                                   for key, value in integrity_state[3])):
                    raise ValueError("live success callable bindings changed: captured public integrity")
                integrity(reviewed_version=4)
            except BaseException:
                if type(result) is issued_handle_class:
                    issued_handles.pop(result, None)
                raise
            return result

    def load_verified_reviewed_definition_realization_native_v1(handle, packet_files, preparation, preservation, graph, admission, *args,
                expected_receipt_sha256, expected_packet_sha256, expected_binary_sha256,
                expected_realization_sha256, expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain, instance_identity_profile=None, definition_application_profile=None, **kwargs):
            """Join this explicit domain's original live issuance without new execution."""
            _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)
            if (globals().get("_live_handle_entry") is not original_handle_entry
                    or original_handle_entry.__code__ is not handle_code
                    or original_handle_entry.__defaults__ is not handle_defaults
                    or set(original_handle_entry.__kwdefaults__ or {}) != {key for key, _ in handle_keywords}
                    or not all((original_handle_entry.__kwdefaults__ or {})[key] is value
                               for key, value in handle_keywords)):
                raise ValueError("live success callable bindings changed: independent _live_handle_entry")
            original_handle_entry(handle, reviewed_version=4, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
            if (entry_guard.__code__ is not entry_code
                    or entry_guard.__defaults__ is not entry_defaults
                    or guarded.__code__ is not guard_code
                    or guarded.__defaults__ is not guard_defaults
                    or set(guarded.__kwdefaults__ or {}) != {key for key, _ in guard_keywords}
                    or not all((guarded.__kwdefaults__ or {})[key] is value
                               for key, value in guard_keywords)):
                raise ValueError("live success callable bindings changed: independent guard")
            if "_live_integrity_state" in kwargs:
                raise ValueError("private live integrity hook cannot be supplied")
            entry_guard(4)
            result = original_load_core(
                handle, packet_files, preparation, graph, admission, *args, _live_integrity_state=integrity_state, reviewed_version=4,
                expected_receipt_sha256=expected_receipt_sha256, expected_packet_sha256=expected_packet_sha256,
                expected_binary_sha256=expected_binary_sha256,
                expected_preservation_sha256=expected_realization_sha256,
                realization_preservation=preservation, expected_upstream_preservation_sha256=expected_preservation_sha256,
                expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
                toolchain=toolchain, **kwargs, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
            if (integrity.__code__ is not integrity_state[1]
                    or integrity.__defaults__ is not integrity_state[2]
                    or set(integrity.__kwdefaults__ or {}) != {key for key, _ in integrity_state[3]}
                    or not all((integrity.__kwdefaults__ or {})[key] is value
                               for key, value in integrity_state[3])):
                raise ValueError("live success callable bindings changed: captured public integrity")
            integrity(reviewed_version=4)
            return result

    def build_verified_reviewed_physical_definition_realization_native_v2(preparation, preservation, graph, admission, *args,
                expected_realization_sha256, expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256,
                toolchain, lake_executable, output_directory, physical_request_raw, expected_physical_request_sha256, timeout_seconds=60, cancellation=None, instance_identity_profile, definition_application_profile, **kwargs):
            """Issue this explicit reviewed domain through the shared original live engine."""
            _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)
            _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
                  and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")
            if (entry_guard.__code__ is not entry_code
                    or entry_guard.__defaults__ is not entry_defaults
                    or guarded.__code__ is not guard_code
                    or guarded.__defaults__ is not guard_defaults
                    or set(guarded.__kwdefaults__ or {}) != {key for key, _ in guard_keywords}
                    or not all((guarded.__kwdefaults__ or {})[key] is value
                               for key, value in guard_keywords)):
                raise ValueError("live success callable bindings changed: independent guard")
            if "_live_integrity_state" in kwargs:
                raise ValueError("private live integrity hook cannot be supplied")
            entry_guard(5)
            result = original_build_core(
                preparation, graph, admission, *args, _live_integrity_state=integrity_state, reviewed_version=5,
                expected_preservation_sha256=expected_realization_sha256,
                realization_preservation=preservation, expected_upstream_preservation_sha256=expected_preservation_sha256,
                physical_request_raw=physical_request_raw, expected_physical_request_sha256=expected_physical_request_sha256,
                expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
                toolchain=toolchain, lake_executable=lake_executable, output_directory=output_directory,
                timeout_seconds=timeout_seconds, cancellation=cancellation, **kwargs,
                **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
            try:
                if (integrity.__code__ is not integrity_state[1]
                        or integrity.__defaults__ is not integrity_state[2]
                        or set(integrity.__kwdefaults__ or {}) != {key for key, _ in integrity_state[3]}
                        or not all((integrity.__kwdefaults__ or {})[key] is value
                                   for key, value in integrity_state[3])):
                    raise ValueError("live success callable bindings changed: captured public integrity")
                integrity(reviewed_version=5)
            except BaseException:
                if type(result) is issued_handle_class:
                    issued_handles.pop(result, None)
                raise
            return result

    def load_verified_reviewed_physical_definition_realization_native_v2(handle, packet_files, preparation, preservation, graph, admission, *args,
                expected_receipt_sha256, expected_packet_sha256, expected_binary_sha256,
                expected_realization_sha256, expected_preservation_sha256, expected_graph_sha256, expected_admission_sha256, toolchain, physical_request_raw, expected_physical_request_sha256, instance_identity_profile, definition_application_profile, **kwargs):
            """Join this explicit domain's original live issuance without new execution."""
            _reviewed_realization_kwargs(instance_identity_profile, definition_application_profile)
            if (globals().get("_live_handle_entry") is not original_handle_entry
                    or original_handle_entry.__code__ is not handle_code
                    or original_handle_entry.__defaults__ is not handle_defaults
                    or set(original_handle_entry.__kwdefaults__ or {}) != {key for key, _ in handle_keywords}
                    or not all((original_handle_entry.__kwdefaults__ or {})[key] is value
                               for key, value in handle_keywords)):
                raise ValueError("live success callable bindings changed: independent _live_handle_entry")
            original_handle_entry(handle, reviewed_version=5, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
            if (entry_guard.__code__ is not entry_code
                    or entry_guard.__defaults__ is not entry_defaults
                    or guarded.__code__ is not guard_code
                    or guarded.__defaults__ is not guard_defaults
                    or set(guarded.__kwdefaults__ or {}) != {key for key, _ in guard_keywords}
                    or not all((guarded.__kwdefaults__ or {})[key] is value
                               for key, value in guard_keywords)):
                raise ValueError("live success callable bindings changed: independent guard")
            if "_live_integrity_state" in kwargs:
                raise ValueError("private live integrity hook cannot be supplied")
            entry_guard(5)
            result = original_load_core(
                handle, packet_files, preparation, graph, admission, *args, _live_integrity_state=integrity_state, reviewed_version=5,
                expected_receipt_sha256=expected_receipt_sha256, expected_packet_sha256=expected_packet_sha256,
                expected_binary_sha256=expected_binary_sha256,
                expected_preservation_sha256=expected_realization_sha256,
                realization_preservation=preservation, expected_upstream_preservation_sha256=expected_preservation_sha256,
                physical_request_raw=physical_request_raw, expected_physical_request_sha256=expected_physical_request_sha256,
                expected_graph_sha256=expected_graph_sha256, expected_admission_sha256=expected_admission_sha256,
                toolchain=toolchain, **kwargs, **_reviewed_realization_kwargs(instance_identity_profile, definition_application_profile))
            if (integrity.__code__ is not integrity_state[1]
                    or integrity.__defaults__ is not integrity_state[2]
                    or set(integrity.__kwdefaults__ or {}) != {key for key, _ in integrity_state[3]}
                    or not all((integrity.__kwdefaults__ or {})[key] is value
                               for key, value in integrity_state[3])):
                raise ValueError("live success callable bindings changed: captured public integrity")
            integrity(reviewed_version=5)
            return result

    functions = {name: value for name, value in tuple(globals().items())
                 if type(value) is function_type and value.__module__ == __name__}
    functions.update(_live_success_guard=guarded, _live_entry_guard=entry_guard,
        _live_integrity_checker=integrity,
        build_verified_reviewed_norm_preservation_native_v2=build_verified_reviewed_norm_preservation_native_v2,
        load_verified_reviewed_norm_preservation_native_v2=load_verified_reviewed_norm_preservation_native_v2,
        build_verified_reviewed_norm_preservation_native_v3=build_verified_reviewed_norm_preservation_native_v3,
        load_verified_reviewed_norm_preservation_native_v3=load_verified_reviewed_norm_preservation_native_v3,
        build_verified_reviewed_definition_realization_native_v1=build_verified_reviewed_definition_realization_native_v1,
        load_verified_reviewed_definition_realization_native_v1=load_verified_reviewed_definition_realization_native_v1,
        build_verified_reviewed_physical_definition_realization_native_v2=build_verified_reviewed_physical_definition_realization_native_v2,
        load_verified_reviewed_physical_definition_realization_native_v2=load_verified_reviewed_physical_definition_realization_native_v2)
    states = tuple((name, _live_callable_state(value)) for name, value in functions.items())
    return (guarded, entry_guard, integrity, build_verified_reviewed_norm_preservation_native_v2,
            load_verified_reviewed_norm_preservation_native_v2,
            build_verified_reviewed_norm_preservation_native_v3,
            load_verified_reviewed_norm_preservation_native_v3,
            build_verified_reviewed_definition_realization_native_v1,
            load_verified_reviewed_definition_realization_native_v1,
            build_verified_reviewed_physical_definition_realization_native_v2,
            load_verified_reviewed_physical_definition_realization_native_v2, states)


(_live_success_guard, _live_entry_guard, _live_integrity_checker, build_verified_reviewed_norm_preservation_native_v2,
 load_verified_reviewed_norm_preservation_native_v2, build_verified_reviewed_norm_preservation_native_v3,
 load_verified_reviewed_norm_preservation_native_v3,
 build_verified_reviewed_definition_realization_native_v1, load_verified_reviewed_definition_realization_native_v1,
 build_verified_reviewed_physical_definition_realization_native_v2, load_verified_reviewed_physical_definition_realization_native_v2,
 _LIVE_NATIVE_FUNCTIONS) = _bind_live_success_independent_guard_v1()
