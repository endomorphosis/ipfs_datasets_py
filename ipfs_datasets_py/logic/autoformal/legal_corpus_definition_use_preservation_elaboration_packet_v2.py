"""Replay retained theorem-elaboration bytes without executing a native tool.

Independent pins are external provenance premises. This bytes-only adapter
replays current source/review/preparation compatibility, validates historical
observations and retains them unchanged. It neither authenticates execution nor
rechecks compiler artifacts, observes current PIDs, issues proof receipts or
grants source/legal/cache/model authority. Public import is stdlib-only.
"""
from __future__ import annotations

from abc import ABCMeta
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
from types import ModuleType

SCHEMA = "legal-corpus-v2-preservation-elaboration-packet-observation/v1"
PROFILE = "replayed-retained-v2-corpus-theorem-type-elaboration-byte-packet/v1"
MAX_RECORD_BYTES = 1024 * 1024
MAX_PACKET_BYTES = 64 * MAX_RECORD_BYTES
MAX_INPUT_BYTES = 48 * MAX_RECORD_BYTES
MAX_LINEAGE_BYTES = 8 * MAX_RECORD_BYTES
MAX_PROJECT_BYTES = 8 * MAX_RECORD_BYTES
MAX_LOG_BYTES = 12 * MAX_RECORD_BYTES
MAX_FILES = 53
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_TOOLCHAIN = re.compile(r"leanprover/lean4:v([0-9]+\.[0-9]+\.[0-9]+)\Z")
_LOG_FILES = frozenset({"stdout.txt", "stderr.txt", "runner-error.txt"})
_ROOT_FILES = _LOG_FILES | {"build-receipt.json", "type-checks.json"}
_PACKET_ARGUMENTS = frozenset({
    "expected_preparation_sha256", "expected_corpus_preparation_sha256",
    "expected_assessment_file_sha256", "expected_receipt_file_sha256",
    "expected_bundle_sha256", "review_inputs", "toolchain", "expected_binary_sha256",
})
_REVIEW_FIELDS = frozenset({
    "subject", "registry", "policy", "reviews", "dependency_manifest",
    "component_raw", "expected_component_pin", "use_inputs", "expected_subject_sha256",
    "expected_registry_sha256", "expected_policy_sha256", "expected_reviews_sha256",
    "expected_manifest_sha256", "at_time_utc", "observed_artifact_sha256s", "observed_pins", "evidence_artifacts",
})
_OBSERVATION_FIELDS = frozenset({
    "command", "expected_command", "runtime", "pid", "returncode", "expected_modules", "compiled_modules",
    "manifest_coverage_passed", "executed_project_readback_passed", "executed_project_sha256", "producer_pins",
    "binary_sha256", "binaries_unchanged", "version_probes", "toolchain_probed", "installed_pair_binary_verified",
    "installed_stdlib_artifact_closure_verified", "post_run_validation_passed", "post_run_validation_error",
    "binary_recheck_error", "original_preparation_unchanged", "artifact_sha256", "artifact_bytes", "artifact_files",
    "theorems", "original_theorems", "probe_theorems", "theorem_axiom_dependencies", "axiom_observations_passed",
    "axiom_observation_errors", "type_checks", "type_checks_passed", "type_check_errors", "type_checks_sha256",
    "type_checks_bytes", "type_checks_file", "type_check_scope", "stdout", "stderr", "error", "log_sha256",
    "log_bytes", "receipt_text_truncated", "elapsed_seconds", "termination_reason", "timed_out", "cancelled",
    "unavailable", "output_truncated", "workspace_limit_exceeded", "resource_exhausted", "workspace_cleaned",
    "process_tree_terminated", "native_lifecycle", "cleanup_confirmed", "observed_process_scope_passed",
    "ownership_is_sampled", "kernel_containment_attested", "native_runtime_verified",
})
_RECEIPT_FIELDS = frozenset({
    "schema", "profile", "record_cid", "cid_scope", "preparation_cid", "preparation_full_canonical_sha256",
    "preparation_manifest_sha256", "lineage_sha256", "packet_observation_sha256", "packet_bundle_sha256",
    "receipt_file_sha256", "corpus_preparation_full_canonical_sha256", "assessment_file_sha256", "toolchain",
    "original_preparation_state", "native_observations", "build_passed", "status", "proof_scope", "trust_boundary",
    "authority", "training_mask", "evaluation_gold_mask",
})
_NATIVE_SUCCESS_FLAGS = frozenset({
    "backend_executed", "native_execution_performed", "fresh_native_execution_performed", "installed_compiler_revalidated",
    "lean_compilation_verified", "proof_checked", "kernel_proofs_checked", "elaborated_type_verified",
    "elaborated_type_equality_verified", "kernel_definitional_equality_verified", "kernel_probe_aliases_checked",
})
_PROOF_SCOPE = "Fifteen actual original theorem types exactly match namespace-preserving generated alias types, with kernel checks and empty axiom inventories for thirty original/alias declarations. The original donor, consumer and alias hypotheses remain parameters; no fact or legal/source correspondence is established."
_NATIVE_TRUST_BOUNDARY = [
    "The installed standard library and dynamically loaded compiler libraries are external trust premises; only the installed sibling lake/lean ELF pair is pinned and version-probed.",
    "This clean build consumes seventeen regenerated source inputs and no retained compiled artifact.",
    "Native observations do not construct a FormalizationArtifact, BackendRequest, BackendAttempt, ProofResult or typed ProofReceipt and do not authorize legal/cache admission.",
]
FALSE_FLAGS = dict.fromkeys((
    "source_authenticity_verified publisher_authenticity_verified legal_currentness_verified "
    "source_semantics_verified applicability_verified context_closure_verified independently_reviewed "
    "human_identity_verified human_independence_verified meaning_admitted admitted formalized semantic_graph_admitted "
    "proof_authority training_qualified training_gold_qualified evaluation_gold_qualified Lean_admitted model_executed "
    "learned_translation source_to_model_equivalence_proved source_fidelity_proved translation_preservation_proved "
    "cross_family_equivalence_verified general_emitter_preservation_proved general_serialized_AST_lowering_preservation_proved "
    "json_bytes_parser_verified json_bytes_parser_preservation_proved model_convergence_proved convergence_proved "
    "backend_executed lean_compilation_verified proof_checked kernel_proofs_checked corpus_native_AST_preservation_proved "
    "conditional_proofs_verified alias_assumption_proved legal_proof_cache_compatible proof_cache_admission_verified "
    "semantic_definition_binding_verified per_occurrence_lookup_verified accepted_view_eligible combined_use_review_verified "
    "native_execution_performed fresh_native_execution_performed proof_validation_performed olean_kernel_rechecked "
    "installed_compiler_revalidated cryptographic_authenticity_verified elaborated_type_verified executable_kernel_target_prepared "
    "formalization_artifact_created backend_request_prepared typed_native_attempt_observed typed_theorem_result_observed "
    "theorem_receipt_issued compiled_artifact_execution_reused elaborated_term_dependencies_verified source_prose_correspondence_proved "
    "installed_stdlib_artifact_closure_verified elaborated_type_equality_verified kernel_definitional_equality_verified "
    "kernel_probe_aliases_checked kernel_claim_prepared backend_attempt_created proof_result_created proof_receipt_issued cache_write_performed"
).split(), False)
AUTHORITY = dict.fromkeys(("source", "legal", "review", "proof", "model", "training", "gold", "corpus_admission"), False)


def _need(value, message):
    if not value:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(value, label):
    _need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None, "independent lowercase SHA256 required: " + label)


def _keys(value, fields, label):
    _need(type(value) is dict and set(value) == set(fields), "closed " + label + " fields required")


def _integer(value, label, minimum=0, maximum=(1 << 63) - 1):
    _need(type(value) is int and minimum <= value <= maximum, "bounded integer required: " + label)


def _bound_tree(value, maximum, *, allow_bytes=False):
    remaining, nodes = maximum, 2_000_000

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 96, "elaboration packet input node/depth bound exceeded")
        if type(item) is dict:
            remaining -= 2 + 2 * len(item)
            for key, child in item.items():
                _need(type(key) is str, "ordinary elaboration packet keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            remaining -= 2 + len(item)
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= remaining, "bounded elaboration packet text required")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise ValueError("valid elaboration packet UTF8 required") from error
        elif allow_bytes and type(item) is bytes:
            remaining -= len(item)
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _integer(item, "JSON integer", -(1 << 63) + 1)
            remaining -= 20
        elif type(item) is float:
            _need(math.isfinite(item), "finite elaboration packet numbers required")
            remaining -= 32
        else:
            raise ValueError("ordinary bounded elaboration packet values required")
        _need(remaining >= 0, "complete elaboration packet input byte bound exceeded")

    visit(value, 0)


def _wire(value, maximum=MAX_RECORD_BYTES):
    _bound_tree(value, maximum)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("finite ordinary elaboration packet JSON required") from error
    _need(len(raw) <= maximum, "complete elaboration packet JSON byte bound exceeded")
    return raw


def _parse(raw, maximum=MAX_RECORD_BYTES):
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded original elaboration packet JSON bytes required")

    def pairs(items):
        value = {}
        for key, child in items:
            _need(key not in value, "duplicate elaboration packet JSON key")
            value[key] = child
        return value

    def constant(_):
        raise ValueError("nonfinite elaboration packet JSON refused")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        _wire(value, maximum)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("duplicate-free finite bounded elaboration packet JSON required") from error
    return value


def _snapshot(value):
    if type(value) is dict:
        return ("object", tuple((key, _snapshot(value[key])) for key in sorted(value)))
    if type(value) is list:
        return ("array", tuple(_snapshot(child) for child in value))
    if type(value) is bytes:
        return ("bytes", value)
    if type(value) is str:
        return ("string", value)
    if type(value) is bool:
        return ("boolean", value)
    if type(value) is int:
        return ("integer", value)
    if type(value) is float:
        return ("float", value.hex())
    if value is None:
        return ("null",)
    raise ValueError("ordinary bounded elaboration snapshot values required")


def _registered_class(module_name, class_name):
    owner = sys.modules.get(module_name)
    _need(type(owner) is ModuleType and vars(owner).get("__name__") == module_name,
          "already registered genuine typed owner required: " + class_name)
    cls = vars(owner).get(class_name)
    metaclass = ABCMeta if (module_name, class_name) == ("ipfs_datasets_py.logic.ir_core.claims", "FrozenMap") else type
    _need(type(cls) is metaclass and vars(cls).get("__module__") == module_name
          and type.__getattribute__(cls, "__name__") == class_name,
          "already registered genuine typed class required: " + class_name)
    return cls


def _corpus_document(corpus):
    _need(type(corpus) is _registered_class("ipfs_datasets_py.logic.autoformal.legal_corpus_definition_use_lake_v2", "DefinitionUseCorpusPreparation"),
          "genuine original corpus preparation required")
    data = object.__getattribute__(corpus, "__dict__")
    _keys(data, {"manifest_json", "files"}, "original corpus preparation storage")
    text, files = data["manifest_json"], data["files"]
    _need(type(text) is str and len(text) <= MAX_RECORD_BYTES and type(files) is tuple and len(files) == 9,
          "bounded complete original nine-file corpus storage required")
    manifest = _parse(text.encode("utf-8"))
    pairs, names, total = [], [], 0
    for pair in files:
        _need(type(pair) is tuple and len(pair) == 2, "immutable original corpus source pairs required")
        name, body = pair
        _need(type(name) is str and len(name) <= 256 and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?", name)
              and all(part not in (".", "..") for part in name.split("/")) and type(body) is str and "\x00" not in body,
              "closed original corpus path/text required")
        total += len(body.encode("utf-8"))
        _need(total <= MAX_PROJECT_BYTES, "complete original corpus source budget exceeded")
        names.append(name)
        pairs.append([name, body])
    _need(names == sorted(set(names)), "distinct sorted original corpus source files required")
    return {"manifest": manifest, "files": pairs}


def _lineage_document(lineage):
    _need(type(lineage) is _registered_class("ipfs_datasets_py.logic.autoformal.legal_corpus_definition_use_preservation_theorem_lineage_v2", "RetainedCorpusTheoremLineage"),
          "genuine original theorem lineage required")
    raw_text = object.__getattribute__(lineage, "lineage_json")
    claims = object.__getattribute__(lineage, "claims")
    _need(type(raw_text) is str and 0 < len(raw_text) <= MAX_LINEAGE_BYTES
          and type(claims) is tuple and len(claims) == 15, "bounded complete original typed lineage storage required")
    raw = raw_text.encode("utf-8")
    document = _parse(raw, MAX_LINEAGE_BYTES)
    module = "ipfs_datasets_py.logic.ir_core.claims"
    fields = {
        _registered_class(module, "IRClaim"): ("claim_id", "statement", "assumptions", "obligations", "domain", "declaration_id", "source_refs", "metadata", "schema_version"),
        _registered_class(module, "Assumption"): ("assumption_id", "statement", "source_refs", "metadata", "schema_version"),
        _registered_class(module, "ProofObligation"): ("obligation_id", "statement", "assumption_ids", "logic_family", "source_refs", "metadata", "schema_version"),
    }
    frozen = _registered_class(module, "FrozenMap")
    budget, nodes = MAX_LINEAGE_BYTES, 500_000

    def visit(value, depth):
        nonlocal budget, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 80, "bounded typed lineage node/depth required")
        kind = type(value)
        if value is None or kind is bool:
            budget -= 5
            result = value
        elif kind is str:
            _need("\x00" not in value and len(value) <= budget, "bounded ordinary typed lineage text required")
            budget -= len(value.encode("utf-8")) + 2
            result = value
        elif kind is int:
            _integer(value, "typed lineage integer", -(1 << 63) + 1)
            budget -= 20
            result = value
        elif kind is float:
            _need(math.isfinite(value), "finite typed lineage number required")
            budget -= 32
            result = value
        elif kind is tuple:
            budget -= 2 + len(value)
            result = [visit(child, depth + 1) for child in value]
        elif kind is frozen:
            pairs = object.__getattribute__(value, "_items")
            _need(type(pairs) is tuple and len(pairs) <= 4096, "bounded genuine frozen lineage map required")
            budget -= 2 + 2 * len(pairs)
            result, previous = {}, None
            for pair in pairs:
                _need(type(pair) is tuple and len(pair) == 2 and type(pair[0]) is str
                      and (previous is None or previous < pair[0]), "canonical frozen typed lineage keys required")
                previous = pair[0]
                result[visit(pair[0], depth + 1)] = visit(pair[1], depth + 1)
        elif kind in fields:
            budget -= 200
            result = {name: visit(object.__getattribute__(value, name), depth + 1) for name in fields[kind]}
        else:
            raise ValueError("genuine recursively immutable typed lineage storage required")
        _need(budget >= 0, "complete original typed lineage byte bound exceeded")
        return result

    typed = visit(claims, 0)
    _need(type(document) is dict and _wire(document.get("claims"), MAX_LINEAGE_BYTES) == _wire(typed, MAX_LINEAGE_BYTES),
          "serialized and typed original lineage storage differ")
    return raw, typed


def _packet_document(packet_files, *, preservation=False):
    expected = 49 if preservation else MAX_FILES
    roots = _LOG_FILES | {"build-receipt.json"} if preservation else _ROOT_FILES
    counts = {"project": 17, "executed-inputs": 16, "compiled": 12} if preservation else {"project": 18, "executed-inputs": 17, "compiled": 13}
    _need(type(packet_files) is tuple and len(packet_files) == expected, "complete immutable retained packet required")
    files, rows, names, total = {}, [], [], 0
    actual, sizes = dict.fromkeys(counts, 0), dict.fromkeys(counts, 0)
    for pair in packet_files:
        _need(type(pair) is tuple and len(pair) == 2, "immutable retained path/bytes pairs required")
        name, raw = pair
        _need(type(name) is str and len(name) <= 512
              and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+){0,2}", name)
              and all(part not in (".", "..") for part in name.split("/")) and type(raw) is bytes,
              "closed canonical immutable retained paths and bytes required")
        if "/" not in name:
            _need(name in roots, "unknown retained root file")
            maximum = MAX_LOG_BYTES if name in _LOG_FILES else MAX_RECORD_BYTES
        else:
            group = name.split("/", 1)[0]
            _need(group in counts, "unknown retained file group")
            actual[group] += 1
            _need(group != "compiled" or bool(raw), "nonempty retained compiled artifact required")
            maximum = MAX_RECORD_BYTES if name == "project/corpus-manifest.json" else MAX_PROJECT_BYTES
            if name != "project/corpus-manifest.json":
                sizes[group] += len(raw)
        _need(len(raw) <= maximum, "retained elaboration file byte bound exceeded")
        total += len(raw)
        _need(total <= MAX_PACKET_BYTES, "complete retained elaboration packet byte bound exceeded")
        names.append(name)
        files[name] = raw
        rows.append({"path": name, "bytes": len(raw), "sha256": _sha(raw)})
    _need(names == sorted(set(names)) and actual == counts
          and set(name for name in names if "/" not in name) == roots
          and all(size <= MAX_PROJECT_BYTES for size in sizes.values()),
          "complete distinct sorted retained packet population required")
    return files, rows


def packet_sha256(packet_files):
    """Address the complete sorted native packet inventory, without validation."""
    _, rows = _packet_document(packet_files)
    return _sha(_wire(rows))


def _binary_map(value):
    _need(type(value) is dict and len(value) == 2, "exact two historical compiler binary pins required")
    names, parent = {}, None
    for path_text, pin in value.items():
        _pin(pin, "historical sibling compiler")
        _need(type(path_text) is str and 0 < len(path_text) <= 4096 and "\\" not in path_text and "\x00" not in path_text,
              "ordinary canonical historical compiler path required")
        path = PurePosixPath(path_text)
        _need(path.is_absolute() and str(path) == path_text and path.name in {"lake", "lean"}
              and all(part not in (".", "..") for part in path.parts)
              and (parent is None or path.parent == parent), "canonical sibling compiler pathnames required")
        parent = path.parent
        names[path.name] = path_text
    _need(set(names) == {"lake", "lean"}, "one historical lake and one historical lean required")
    return names


def _owners():
    from . import legal_corpus_definition_use_preservation_elaboration_v2 as pure
    from . import legal_corpus_definition_use_preservation_elaboration_native_v2 as native
    from . import legal_corpus_definition_use_preservation_packet_v2 as preservation
    from . import corpus_contracts as contracts
    return pure, native, preservation, contracts


def _current_preparation(owners, lineage, packet, corpus, assessment, expected_preparation, expected_lineage, expected_observation, arguments):
    pure = owners[0]
    prepared = pure.prepare_definition_use_preservation_elaboration_v2(
        lineage, packet, corpus, assessment, expected_lineage_sha256=expected_lineage,
        expected_packet_observation_sha256=expected_observation, **arguments)
    _need(pure.preparation_sha256(prepared) == expected_preparation,
          "independent full current elaboration preparation differs")
    return prepared


def _historical_observations(observation, files, arguments, owners):
    native, preservation = owners[1], owners[2]
    _keys(observation, _OBSERVATION_FIELDS, "historical elaboration native observations")
    _integer(observation["pid"], "historical native PID", 1)
    _integer(observation["returncode"], "historical successful returncode", 0, 0)
    names = _binary_map(arguments["expected_binary_sha256"])
    command = [names["lake"], "--offline", "--no-cache", "build", "legal"]
    _need(observation["command"] == observation["expected_command"] == command and observation["runtime"] == "native"
          and _wire(observation["binary_sha256"]) == _wire(arguments["expected_binary_sha256"]),
          "historical command/runtime/compiler commitments differ")
    for name in ("manifest_coverage_passed", "executed_project_readback_passed", "binaries_unchanged", "toolchain_probed",
                 "installed_pair_binary_verified", "post_run_validation_passed", "original_preparation_unchanged",
                 "axiom_observations_passed", "type_checks_passed", "workspace_cleaned", "cleanup_confirmed",
                 "observed_process_scope_passed", "ownership_is_sampled", "native_runtime_verified"):
        _need(observation[name] is True, "incomplete historical native observation: " + name)
    for name in ("installed_stdlib_artifact_closure_verified", "timed_out", "cancelled", "unavailable", "output_truncated",
                 "workspace_limit_exceeded", "resource_exhausted", "kernel_containment_attested"):
        _need(observation[name] is False, "failed or overstated historical native observation: " + name)
    _need(observation["post_run_validation_error"] is None and observation["binary_recheck_error"] is None
          and type(observation["axiom_observation_errors"]) is list and observation["axiom_observation_errors"] == []
          and type(observation["type_check_errors"]) is list and observation["type_check_errors"] == []
          and type(observation["process_tree_terminated"]) is bool
          and type(observation["elapsed_seconds"]) in (int, float) and math.isfinite(observation["elapsed_seconds"])
          and observation["elapsed_seconds"] >= 0 and observation["termination_reason"] == "completed",
          "historical native qualification errors or duration/termination mismatch")
    preservation._historical_lifecycle(observation["native_lifecycle"], observation["pid"])
    _keys(observation["version_probes"], {"lake", "lean"}, "historical installed pair probes")
    version = _TOOLCHAIN.fullmatch(arguments["toolchain"]).group(1)
    for name, probe in observation["version_probes"].items():
        _keys(probe, {"command", "returncode", "stdout", "stderr"}, "historical version probe")
        _integer(probe["returncode"], "historical version probe exit", 0, 0)
        _need(probe["command"] == [names[name], "--version"] and type(probe["stdout"]) is str and type(probe["stderr"]) is str
              and len(probe["stdout"].encode()) <= MAX_RECORD_BYTES and len(probe["stderr"].encode()) <= MAX_RECORD_BYTES
              and re.search(r"\bversion " + re.escape(version) + r"(?:[,\s)])", probe["stdout"]),
              "historical version probe differs from explicit toolchain")
    _keys(observation["log_sha256"], _LOG_FILES, "historical full log hashes")
    _keys(observation["log_bytes"], _LOG_FILES, "historical full log lengths")
    for name, field in (("stdout.txt", "stdout"), ("stderr.txt", "stderr"), ("runner-error.txt", "error")):
        raw = files[name]
        _integer(observation["log_bytes"][name], "historical full log bytes")
        _pin(observation["log_sha256"][name], "historical full log")
        raw.decode("utf-8", errors="strict")
        preview = raw[:native.MAX_LOG_PREVIEW_BYTES].decode("utf-8", errors="replace").replace("\x00", "\\u0000")
        _need(observation["log_bytes"][name] == len(raw) and observation["log_sha256"][name] == _sha(raw)
              and observation[field] == preview, "historical full log or preview differs")
    _need(files["runner-error.txt"] == b"" and observation["error"] == ""
          and observation["receipt_text_truncated"] is any(len(files[name]) > native.MAX_LOG_PREVIEW_BYTES for name in _LOG_FILES),
          "historical runner error or preview truncation differs")


def _receipt_matches(receipt, files, prepared, arguments, expected_preparation, expected_lineage, expected_observation, owners):
    pure, native, _, contracts = owners
    _keys(receipt, _RECEIPT_FIELDS | set(native.FALSE_FLAGS), "complete retained elaboration receipt")
    _need(receipt["schema"] == native.BUILD_SCHEMA and receipt["profile"] == native.PROFILE,
          "retained elaboration receipt schema/profile differs")
    contracts.validate_record(receipt, schema=native.BUILD_SCHEMA, fields=set(receipt) - {"schema", "record_cid", "cid_scope"})
    _need(receipt["build_passed"] is True and receipt["status"] == "corpus_theorem_type_elaboration_checks_passed"
          and receipt["proof_scope"] == _PROOF_SCOPE and receipt["trust_boundary"] == _NATIVE_TRUST_BOUNDARY,
          "successful exact historical engineering type check required")
    _need(set(native.FALSE_FLAGS) <= set(FALSE_FLAGS), "current native false-flag contract changed")
    for name in native.FALSE_FLAGS:
        _need(receipt[name] is (name in _NATIVE_SUCCESS_FLAGS), "historical source/proof/cache scope differs: " + name)
    _need(type(receipt["authority"]) is dict and receipt["authority"] == AUTHORITY
          and all(value is False for value in receipt["authority"].values()), "historical receipt acquired unsupported authority")
    for name in ("training_mask", "evaluation_gold_mask"):
        _integer(receipt[name], "historical authority mask", 0, 0)
    manifest = prepared.to_dict()
    expected = {
        "preparation_cid": manifest["record_cid"], "preparation_full_canonical_sha256": expected_preparation,
        "preparation_manifest_sha256": _sha(prepared.manifest_json.encode()), "lineage_sha256": expected_lineage,
        "packet_observation_sha256": expected_observation, "packet_bundle_sha256": arguments["expected_bundle_sha256"],
        "receipt_file_sha256": arguments["expected_receipt_file_sha256"],
        "corpus_preparation_full_canonical_sha256": arguments["expected_corpus_preparation_sha256"],
        "assessment_file_sha256": arguments["expected_assessment_file_sha256"], "toolchain": arguments["toolchain"],
        "original_preparation_state": manifest["original_preparation_state"],
    }
    _need(_wire({name: receipt[name] for name in expected}) == _wire(expected), "historical receipt differs from full current preparation/source binding")
    observation = receipt["native_observations"]
    _historical_observations(observation, files, arguments, owners)
    modules = manifest["expected_modules"]
    _need(type(modules) is list and len(modules) == 13 and observation["expected_modules"] == observation["compiled_modules"] == modules,
          "complete historical compiled module population differs")
    sources = {name: body.encode("utf-8") for name, body in prepared.files}
    artifact_paths = [".lake/build/lib/lean/" + name.replace(".", "/") + ".olean" for name in modules]
    artifact_files = {path: "compiled/" + path.removeprefix(".lake/build/lib/lean/") for path in artifact_paths}
    expected_names = ({"project/" + name for name in sources} | {"project/corpus-manifest.json"}
        | {"executed-inputs/" + name for name in sources} | set(artifact_files.values()) | _ROOT_FILES)
    _need(len(sources) == 17 and len(expected_names) == MAX_FILES and set(files) == expected_names,
          "complete exact retained elaboration paths differ from current project")
    _need(files["project/corpus-manifest.json"] == prepared.manifest_json.encode("utf-8")
          and all(files["project/" + name] == raw == files["executed-inputs/" + name] for name, raw in sources.items())
          and _wire(observation["executed_project_sha256"]) == _wire({name: _sha(raw) for name, raw in sources.items()}),
          "retained frozen/executed source bytes differ from current authoritative preparation")
    for field in ("artifact_sha256", "artifact_bytes", "artifact_files"):
        _keys(observation[field], artifact_paths, "historical compiled artifact inventory")
    _need(observation["artifact_files"] == artifact_files, "historical artifact module/path identities differ")
    for path, retained in artifact_files.items():
        raw = files[retained]
        _integer(observation["artifact_bytes"][path], "historical compiled bytes", 1)
        _pin(observation["artifact_sha256"][path], "historical compiled artifact")
        _need(observation["artifact_bytes"][path] == len(raw) and observation["artifact_sha256"][path] == _sha(raw),
              "retained compiled artifact bytes differ")
    for field in ("theorems", "original_theorems", "probe_theorems"):
        _need(observation[field] == manifest[field], "historical theorem names/partitions differ")
    types, errors, passed = native._type_observations(files["stdout.txt"].decode(), files["stderr.txt"].decode(), manifest)
    _need(passed and errors == [] and len(types) == 15, "complete historical exact type observations required")
    type_raw, compact = native._type_capture_payload(types)
    _need(type_raw == files["type-checks.json"] and _wire(compact) == _wire(observation["type_checks"]),
          "standalone full type payload or compact per-record commitments differ from full captured logs")
    _integer(observation["type_checks_bytes"], "complete standalone type payload bytes", 1, MAX_RECORD_BYTES)
    _pin(observation["type_checks_sha256"], "complete standalone type payload")
    _need(observation["type_checks_bytes"] == len(type_raw) and observation["type_checks_sha256"] == _sha(type_raw)
          and _wire(observation["type_checks_file"]) == _wire({"path": "type-checks.json", "bytes": len(type_raw), "sha256": _sha(type_raw)})
          and observation["type_check_scope"] == "actual original and namespace-preserving alias theorem types; no inferred legal interpretation",
          "historical standalone type file scope/commitment differs")
    axioms, errors, passed = native._axiom_observations(files["stdout.txt"].decode(), files["stderr.txt"].decode(), manifest)
    _need(passed and errors == [] and len(axioms) == 30
          and _wire(observation["theorem_axiom_dependencies"]) == _wire(axioms), "complete thirty empty-axiom observations differ")
    current = native._producer_pins(manifest, native._owners())
    _need(_wire(current) == _wire(observation["producer_pins"]), "historical native producer closure differs from current owners")
    return manifest, current, compact


@dataclass(frozen=True, slots=True)
class RetainedElaborationPacket:
    observation_json: str
    files: tuple[tuple[str, bytes], ...]

    def to_dict(self):
        _need(type(self.observation_json) is str, "retained elaboration observation text required")
        value = _parse(self.observation_json.encode("utf-8"))
        _need(type(value) is dict, "retained elaboration observation object required")
        return value


def observation_sha256(observation):
    """Address exact bounded stored observation bytes, without validation."""
    _need(type(observation) is RetainedElaborationPacket, "genuine retained elaboration observation required")
    RetainedElaborationPacket.to_dict(observation)
    return _sha(observation.observation_json.encode("utf-8"))


def validate_definition_use_preservation_elaboration_packet_v2(
        native_packet_files, lineage, preservation_packet_files, corpus_preparation, assessment_raw, *,
        expected_native_receipt_file_sha256, expected_type_payload_file_sha256, expected_native_bundle_sha256,
        expected_elaboration_preparation_sha256, expected_lineage_sha256, expected_packet_observation_sha256, **packet_arguments):
    """Replay exact current sources and trusted retained bytes, without Lean.

    Independent trusted pins are required provenance premises. Caller-selected
    hashes of self-sealed invented success records are not authentication.
    Filesystem acquisition remains the external transport's responsibility.
    """
    _keys(packet_arguments, _PACKET_ARGUMENTS, "complete original preservation packet arguments")
    for value, label in ((expected_native_receipt_file_sha256, "exact native receipt"),
        (expected_type_payload_file_sha256, "complete standalone type payload"), (expected_native_bundle_sha256, "complete native bundle"),
        (expected_elaboration_preparation_sha256, "complete current elaboration preparation"), (expected_lineage_sha256, "complete original typed lineage"),
        (expected_packet_observation_sha256, "exact original packet observation")):
        _pin(value, label)
    for name in ("expected_preparation_sha256", "expected_corpus_preparation_sha256", "expected_assessment_file_sha256",
                 "expected_receipt_file_sha256", "expected_bundle_sha256"):
        _pin(packet_arguments[name], name)
    _need(type(packet_arguments["toolchain"]) is str and len(packet_arguments["toolchain"]) <= 128
          and _TOOLCHAIN.fullmatch(packet_arguments["toolchain"]), "exact version-pinned historical toolchain required")
    _binary_map(packet_arguments["expected_binary_sha256"])
    _keys(packet_arguments["review_inputs"], _REVIEW_FIELDS, "complete original review input")
    _bound_tree(packet_arguments, MAX_INPUT_BYTES, allow_bytes=True)
    for name in ("expected_subject_sha256", "expected_registry_sha256", "expected_policy_sha256", "expected_reviews_sha256", "expected_manifest_sha256"):
        _pin(packet_arguments["review_inputs"][name], name)
    _need(type(assessment_raw) is bytes and 0 < len(assessment_raw) <= MAX_RECORD_BYTES
          and _sha(assessment_raw) == packet_arguments["expected_assessment_file_sha256"], "independently pinned original assessment bytes required")
    files, inventory = _packet_document(native_packet_files)
    old_files, old_inventory = _packet_document(preservation_packet_files, preservation=True)
    _need(_sha(_wire(inventory)) == expected_native_bundle_sha256
          and _sha(files["build-receipt.json"]) == expected_native_receipt_file_sha256
          and _sha(files["type-checks.json"]) == expected_type_payload_file_sha256,
          "independent complete native packet/receipt/type payload pin differs")
    _need(_sha(_wire(old_inventory)) == packet_arguments["expected_bundle_sha256"]
          and _sha(old_files["build-receipt.json"]) == packet_arguments["expected_receipt_file_sha256"],
          "independent complete original preservation packet/receipt pin differs")
    corpus_raw = _wire(_corpus_document(corpus_preparation), 20 * MAX_RECORD_BYTES)
    lineage_raw, typed_claims = _lineage_document(lineage)
    _need(_sha(corpus_raw) == packet_arguments["expected_corpus_preparation_sha256"] and _sha(lineage_raw) == expected_lineage_sha256,
          "independent complete original corpus/lineage pin differs")
    _need(len(corpus_raw) + len(lineage_raw) + len(assessment_raw) <= MAX_INPUT_BYTES, "complete original typed input budget exceeded")
    argument_budget = MAX_INPUT_BYTES - len(corpus_raw) - len(lineage_raw) - len(assessment_raw)
    _bound_tree(packet_arguments, argument_budget, allow_bytes=True)
    inputs_snapshot = _snapshot(packet_arguments)
    claims_raw = _wire(typed_claims, MAX_LINEAGE_BYTES)
    receipt = _parse(files["build-receipt.json"])
    _parse(files["type-checks.json"])
    _need(type(receipt) is dict and _sha(Path(__file__).read_bytes()) == _SELF_PIN, "native packet reader changed since import")

    def unchanged(producers=None):
        _bound_tree(packet_arguments, argument_budget, allow_bytes=True)
        current_lineage_raw, current_claims = _lineage_document(lineage)
        _need(_snapshot(packet_arguments) == inputs_snapshot
              and _wire(_corpus_document(corpus_preparation), 20 * MAX_RECORD_BYTES) == corpus_raw
              and current_lineage_raw == lineage_raw and _wire(current_claims, MAX_LINEAGE_BYTES) == claims_raw
              and packet_sha256(native_packet_files) == expected_native_bundle_sha256
              and _sha(_wire(_packet_document(preservation_packet_files, preservation=True)[1])) == packet_arguments["expected_bundle_sha256"]
              and _sha(assessment_raw) == packet_arguments["expected_assessment_file_sha256"]
              and _wire(receipt) == _wire(_parse(files["build-receipt.json"]))
              and (producers is None or all(_sha(Path(path).read_bytes()) == pin for path, pin in producers.items()))
              and _sha(Path(__file__).read_bytes()) == _SELF_PIN,
              "complete original retained/readback inputs or producer identities changed across operation boundary")

    owners = _owners()
    unchanged()
    prepared = _current_preparation(owners, lineage, preservation_packet_files, corpus_preparation, assessment_raw,
        expected_elaboration_preparation_sha256, expected_lineage_sha256, expected_packet_observation_sha256, packet_arguments)
    unchanged()
    prepared_snapshot = (prepared.manifest_json, tuple(prepared.files))
    manifest, historical_pins, compact = _receipt_matches(receipt, files, prepared, packet_arguments,
        expected_elaboration_preparation_sha256, expected_lineage_sha256, expected_packet_observation_sha256, owners)
    current_pins = {**historical_pins, str(Path(__file__).resolve()): _SELF_PIN}
    unchanged(current_pins)
    regenerated = _current_preparation(owners, lineage, preservation_packet_files, corpus_preparation, assessment_raw,
        expected_elaboration_preparation_sha256, expected_lineage_sha256, expected_packet_observation_sha256, packet_arguments)
    unchanged(current_pins)
    _need((regenerated.manifest_json, tuple(regenerated.files)) == prepared_snapshot
          and _wire(owners[1]._producer_pins(regenerated.to_dict(), owners[1]._owners())) == _wire(historical_pins),
          "complete current elaboration preparation/producers changed across retained readback")
    record = owners[3].seal_record({
        "schema": SCHEMA, "profile": PROFILE, "native_bundle_sha256": expected_native_bundle_sha256,
        "native_receipt_file_sha256": expected_native_receipt_file_sha256, "type_payload_file_sha256": expected_type_payload_file_sha256,
        "elaboration_preparation_full_canonical_sha256": expected_elaboration_preparation_sha256, "lineage_file_sha256": expected_lineage_sha256,
        "packet_observation_sha256": expected_packet_observation_sha256, "preservation_packet_bundle_sha256": packet_arguments["expected_bundle_sha256"],
        "corpus_preparation_full_canonical_sha256": packet_arguments["expected_corpus_preparation_sha256"],
        "assessment_file_sha256": packet_arguments["expected_assessment_file_sha256"], "toolchain": packet_arguments["toolchain"],
        "expected_binary_sha256": dict(packet_arguments["expected_binary_sha256"]), "historical_native_receipt": receipt,
        "historical_producer_pins": historical_pins, "current_producer_pins": current_pins, "packet_inventory": inventory,
        "type_payload_file": {"path": "type-checks.json", "bytes": len(files["type-checks.json"]), "sha256": expected_type_payload_file_sha256},
        "type_check_references": compact, "readback_verified": True, "current_preparation_replayed": True,
        "historical_kernel_type_observations_retained": True,
        "source_custody": {"complete_current_source_review_lineage_preparation_replayed": True,
            "original_source_review_state_unchanged": True, "historical_lifecycle_internal_consistency_checked": True,
            "historical_process_liveness_inspected": False, "filesystem_acquisition_performed": False,
            "original_native_receipt_unchanged": True, "complete_type_payload_matches_retained_logs": True,
            "current_producer_compatibility_required": True},
        "trust_boundary": [
            "Independent external native receipt, standalone type payload and whole-bundle pins are provenance premises; hashing self-sealed observations does not authenticate execution.",
            "The external transport owns faithful immutable byte acquisition and filesystem link/race/identity custody.",
            "Historical native/compiler/kernel/lifecycle observations are internally checked retained evidence; no compiler, installed binary, olean or historical process is re-executed or revalidated.",
            "The installed standard and dynamic libraries remain an unverified external toolchain premise.",
            "Complete current original source/review/typed lineage/preparation and producer compatibility is mandatory, without a weaker historical fallback.",
            "Full structured types remain in the separately pinned bounded payload; compact observation references do not create a kernel claim, backend request, result, proof receipt or cache admission."],
        "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0, **FALSE_FLAGS})
    observation_raw = _wire(record)
    unchanged(current_pins)
    return RetainedElaborationPacket(observation_raw.decode("utf-8"), tuple(native_packet_files))


__all__ = ["RetainedElaborationPacket", "packet_sha256", "observation_sha256",
           "validate_definition_use_preservation_elaboration_packet_v2"]
