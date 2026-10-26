"""Observe conditional native proofs for source-bound definition/use projects.

Public import uses only the standard library. The existing preparation owner
retains all source, review, native rendering and interpretation decisions. This
adapter replays that owner before and after one bounded offline Lake invocation
and writes a separate engineering receipt. Conditional kernel checks never
admit source meaning, legal interpretation, reviews, training data or a corpus.
Callers retain their existing owned validation resources throughout execution.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re

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
        preparation_document_reader=None, closing_custody_guard=None):
    """One bounded native execution path, with each source profile replayed by its owner."""
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
    theorems = (list(dict.fromkeys(name for row in receipt_binding["theorem_contributors"]
                                  for name in row["conditional_theorems"])) if shared_type
                else manifest["conditional_theorems"])
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
            resident_memory_bytes=2 * 1024**3, max_output_bytes=MAX_CAPTURE_BYTES,
            max_input_bytes=MAX_PROJECT_BYTES, max_workspace_bytes=128 * MAX_RECORD_BYTES,
            max_output_files=len(output_paths)))
    try:
        run = process.BoundedToolRunner().run(invocation, cancellation=cancellation)
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
                "theorem_assumptions": manifest["theorem_assumptions"],
                "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
                **flags,
            })
            _persist_build(checked, output, owners, {}, {}, {}, refusal,
                           maximum_files=maximum_files, maximum_modules=maximum_modules)
            error.add_note("Unqualified frozen project/cleanup refusal retained at " + str(output))
        except (ValueError, TypeError, OSError) as preservation_error:
            error.add_note("Native cleanup refusal preservation also failed: " + type(preservation_error).__name__)
        raise
    if closing_custody_guard is not None:
        closing_custody_guard("runner_returned", dict(run=run))
    post_error, binary_error = None, None
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
    _need(all(len(raw) <= 3 * MAX_CAPTURE_BYTES for raw in logs.values()),
          "bounded native process observations required")
    previews = {name: raw[:MAX_LOG_PREVIEW_BYTES].decode("utf-8", errors="replace").replace("\x00", "\\u0000")
                for name, raw in logs.items()}
    # Retain the complete original preparation list separately; this observation
    # carries every real hypothesis without its obsolete execution-status text.
    assumptions = [text for text in manifest["theorem_assumptions"]
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
        "original_preparation_theorem_assumptions": manifest["theorem_assumptions"],
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
        "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
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
