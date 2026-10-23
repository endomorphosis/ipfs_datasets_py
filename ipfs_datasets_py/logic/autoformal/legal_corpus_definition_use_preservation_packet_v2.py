"""Replay a complete retained corpus-preservation byte packet without Lean.

The caller supplies independently trusted receipt and whole-packet commitments
and owns filesystem acquisition. This bytes-only reader checks current public
source/review preparation replay and consistency of the retained engineering
observations. It does not authenticate their producer, execute a prover, check
an olean in the kernel, inspect historical PIDs, or grant cache authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re

SCHEMA = "legal-corpus-v2-definition-use-preservation-packet-observation/v1"
PROFILE = "replayed-retained-v2-corpus-preservation-byte-packet/v1"
MAX_RECORD_BYTES = 1024 * 1024
MAX_PACKET_BYTES = 64 * MAX_RECORD_BYTES
MAX_INPUT_BYTES = 48 * MAX_RECORD_BYTES
MAX_PROJECT_BYTES = 8 * MAX_RECORD_BYTES
MAX_LOG_BYTES = 12 * MAX_RECORD_BYTES
MAX_LOG_PREVIEW_BYTES = 32768
MAX_FILES = 49
MAX_MODULES = 12
MAX_THEOREMS = 15
_CORPUS_MODULE = "ipfs_datasets_py.logic.autoformal.legal_corpus_definition_use_lake_v2"
_TOOLCHAIN = re.compile(r"leanprover/lean4:v([0-9]+\.[0-9]+\.[0-9]+)\Z")
_REVIEW_FIELDS = frozenset({
    "subject", "registry", "policy", "reviews", "dependency_manifest",
    "component_raw", "expected_component_pin", "use_inputs",
    "expected_subject_sha256", "expected_registry_sha256", "expected_policy_sha256",
    "expected_reviews_sha256", "expected_manifest_sha256", "at_time_utc",
    "observed_artifact_sha256s", "observed_pins", "evidence_artifacts",
})
_ROOT_FILES = frozenset({"build-receipt.json", "stdout.txt", "stderr.txt", "runner-error.txt"})
_LOG_FILES = frozenset({"stdout.txt", "stderr.txt", "runner-error.txt"})
_OBSERVATION_FIELDS = frozenset({
    "command", "expected_command", "runtime", "pid", "returncode", "expected_modules",
    "compiled_modules", "manifest_coverage_passed", "executed_project_readback_passed",
    "executed_project_sha256", "producer_pins", "binary_sha256", "binaries_unchanged",
    "version_probes", "toolchain_probed", "installed_toolchain_verified",
    "post_run_validation_passed", "post_run_validation_error", "binary_recheck_error",
    "original_preparation_unchanged", "artifact_sha256", "artifact_bytes", "artifact_files",
    "theorems", "conditional_theorems", "preservation_theorems", "theorem_axiom_dependencies",
    "axiom_observations_passed", "axiom_observation_errors", "concrete_kernel_status",
    "conditional_kernel_status", "stdout", "stderr", "error", "log_sha256", "log_bytes",
    "receipt_text_truncated", "elapsed_seconds", "termination_reason", "timed_out",
    "cancelled", "unavailable", "output_truncated", "workspace_limit_exceeded",
    "resource_exhausted", "workspace_cleaned", "process_tree_terminated", "native_lifecycle",
    "cleanup_confirmed", "observed_process_scope_passed", "ownership_is_sampled",
    "kernel_containment_attested", "native_runtime_verified",
})
_RECEIPT_FIELDS = frozenset({
    "schema", "profile", "record_cid", "cid_scope", "preparation_cid",
    "preparation_full_canonical_sha256", "preparation_manifest_sha256",
    "corpus_preparation_full_canonical_sha256", "assessment_file_sha256", "toolchain",
    "original_preparation_state", "preservation_fragments", "reference_contract",
    "native_observations", "build_passed", "status", "authority", "training_mask",
    "evaluation_gold_mask", "proof_scope",
})
_PROOF_SCOPE = "Twelve exact concrete checks for the donor, consumer, alias and joint native AST values, closedness and denotation against each unchanged formula_0; three original conditional corpus theorems retain every donor, consumer and alias hypothesis. No assumed alias fact, universal emitter, JSON byte-parser, legal-source fidelity or model-convergence theorem is established."
FALSE_FLAGS = dict.fromkeys(
    (
        "source_authenticity_verified", "publisher_authenticity_verified",
        "legal_currentness_verified", "source_semantics_verified", "applicability_verified",
        "context_closure_verified", "independently_reviewed", "human_identity_verified",
        "human_independence_verified", "meaning_admitted", "admitted", "formalized",
        "semantic_graph_admitted", "proof_authority", "training_qualified",
        "training_gold_qualified", "evaluation_gold_qualified", "Lean_admitted",
        "model_executed", "learned_translation", "source_to_model_equivalence_proved",
        "source_fidelity_proved", "translation_preservation_proved",
        "cross_family_equivalence_verified", "general_emitter_preservation_proved",
        "general_serialized_AST_lowering_preservation_proved", "json_bytes_parser_verified",
        "json_bytes_parser_preservation_proved", "model_convergence_proved", "convergence_proved",
        "backend_executed", "lean_compilation_verified", "proof_checked", "kernel_proofs_checked",
        "corpus_native_AST_preservation_proved", "conditional_proofs_verified",
        "alias_assumption_proved", "legal_proof_cache_compatible", "proof_cache_admission_verified",
        "semantic_definition_binding_verified", "per_occurrence_lookup_verified",
        "accepted_view_eligible", "combined_use_review_verified", "native_execution_performed",
        "fresh_native_execution_performed", "proof_validation_performed",
        "olean_kernel_rechecked", "installed_compiler_revalidated", "cryptographic_authenticity_verified",
    ), False,
)
AUTHORITY = dict.fromkeys(
    ("source", "legal", "review", "proof", "model", "training", "gold", "corpus_admission"), False,
)
_SUCCESS_FLAGS = frozenset({
    "backend_executed", "lean_compilation_verified", "proof_checked", "kernel_proofs_checked",
    "corpus_native_AST_preservation_proved", "conditional_proofs_verified",
})
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _need(value, message):
    if not value:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(value, label):
    _need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
          "independent lowercase SHA256 required: " + label)


def _keys(value, fields, label):
    _need(type(value) is dict and set(value) == set(fields), "closed " + label + " fields required")


def _integer(value, label, minimum=0, maximum=(1 << 63) - 1):
    _need(type(value) is int and minimum <= value <= maximum, "bounded integer required: " + label)


def _bound_tree(value, maximum, *, allow_bytes=False):
    remaining, nodes = maximum, 2_000_000

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 96, "retained packet input node/depth bound exceeded")
        if type(item) is dict:
            remaining -= 2 + 2 * len(item)
            for key, child in item.items():
                _need(type(key) is str, "ordinary retained packet JSON keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            remaining -= 2 + len(item)
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= remaining, "bounded retained packet text required")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise ValueError("valid retained packet UTF8 required") from error
        elif allow_bytes and type(item) is bytes:
            remaining -= len(item)
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _integer(item, "JSON integer", -(1 << 63) + 1)
            remaining -= 20
        elif type(item) is float:
            _need(math.isfinite(item), "finite retained packet JSON required")
            remaining -= 32
        else:
            raise ValueError("ordinary retained packet input values required")
        _need(remaining >= 0, "complete retained packet input byte bound exceeded")

    visit(value, 0)


def _wire(value, maximum=MAX_RECORD_BYTES):
    _bound_tree(value, maximum)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("finite ordinary retained packet JSON required") from error
    _need(len(raw) <= maximum, "complete retained packet JSON byte bound exceeded")
    return raw


def _review_snapshot(value):
    """Detach a bounded review tree with exact immutable bytes and type tags."""
    if type(value) is dict:
        return ("object", tuple((key, _review_snapshot(value[key])) for key in sorted(value)))
    if type(value) is list:
        return ("array", tuple(_review_snapshot(child) for child in value))
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
    raise ValueError("ordinary bounded review tree required for immutable snapshot")


def _parse(raw, maximum=MAX_RECORD_BYTES):
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded ordinary retained JSON bytes required")

    def pairs(items):
        value = {}
        for key, child in items:
            _need(key not in value, "duplicate retained packet JSON key")
            value[key] = child
        return value

    def constant(_):
        raise ValueError("nonfinite retained packet JSON constant refused")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("duplicate-free finite retained packet JSON required") from error
    _wire(value, maximum)
    return value


def _packet_document(packet_files):
    _need(type(packet_files) is tuple and len(packet_files) == MAX_FILES,
          "complete immutable forty-nine-file packet required")
    names, inventory, total = [], [], 0
    groups = {"project": 0, "executed-inputs": 0, "compiled": 0}
    sizes = {name: 0 for name in groups}
    contents = {}
    for item in packet_files:
        _need(type(item) is tuple and len(item) == 2, "immutable retained path/bytes pairs required")
        name, raw = item
        _need(type(name) is str and len(name) <= 512
              and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+){0,2}", name) is not None
              and all(part not in (".", "..") for part in name.split("/")),
              "canonical closed three-level retained packet paths required")
        _need(type(raw) is bytes, "immutable original retained packet bytes required")
        if "/" not in name:
            _need(name in _ROOT_FILES, "unknown retained packet root file")
            limit = MAX_RECORD_BYTES if name == "build-receipt.json" else MAX_LOG_BYTES
        else:
            group = name.split("/", 1)[0]
            _need(group in groups, "unknown retained packet file group")
            groups[group] += 1
            if name == "project/corpus-manifest.json":
                limit = MAX_RECORD_BYTES
            else:
                limit = MAX_PROJECT_BYTES
                sizes[group] += len(raw)
        _need(len(raw) <= limit, "retained packet file exceeds its bound")
        total += len(raw)
        _need(total <= MAX_PACKET_BYTES, "complete retained packet exceeds sixty-four MiB")
        names.append(name)
        contents[name] = raw
        inventory.append({"path": name, "bytes": len(raw), "sha256": _sha(raw)})
    _need(names == sorted(set(names)), "distinct canonical sorted retained packet paths required")
    _need(set(name for name in names if "/" not in name) == _ROOT_FILES
          and groups == {"project": 17, "executed-inputs": 16, "compiled": 12}
          and all(size <= MAX_PROJECT_BYTES for size in sizes.values()),
          "complete bounded retained project/input/artifact/log populations required")
    return contents, inventory


def packet_sha256(packet_files):
    """Hash canonical sorted inventory rows; this commitment grants no authority."""
    _, inventory = _packet_document(packet_files)
    return _sha(_wire(inventory))


def _binary_map(value):
    _need(type(value) is dict and len(value) == 2, "two externally pinned sibling compiler identities required")
    names, parent = {}, None
    for name, pin in value.items():
        _pin(pin, "historical installed compiler")
        _need(type(name) is str and 0 < len(name) <= 4096 and "\\" not in name and "\x00" not in name,
              "canonical absolute historical compiler pathname required")
        path = PurePosixPath(name)
        _need(path.is_absolute() and str(path) == name and all(p not in (".", "..") for p in path.parts)
              and path.name in ("lake", "lean"), "canonical sibling lake/lean pathnames required")
        _need(parent is None or path.parent == parent, "historical compiler paths must be siblings")
        parent = path.parent
        names[path.name] = name
    _need(set(names) == {"lake", "lean"}, "one historical lake and one historical lean required")
    return names


def _corpus_document(preparation):
    cls = type(preparation)
    _need(cls.__module__ == _CORPUS_MODULE and cls.__name__ == "DefinitionUseCorpusPreparation",
          "original typed V2 corpus preparation required")
    try:
        data = object.__getattribute__(preparation, "__dict__")
    except AttributeError as error:
        raise ValueError("closed original corpus preparation storage required") from error
    _keys(data, {"manifest_json", "files"}, "original corpus preparation storage")
    text, files = data["manifest_json"], data["files"]
    _need(type(text) is str, "original corpus manifest text required")
    manifest = _parse(text.encode("utf-8"))
    _need(type(manifest) is dict and type(files) is tuple and len(files) == 9,
          "complete original nine-file V2 corpus required")
    names, pairs, total = [], [], 0
    for item in files:
        _need(type(item) is tuple and len(item) == 2, "original corpus path/text pairs required")
        name, body = item
        _need(type(name) is str and len(name) <= 256 and type(body) is str
              and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?", name) is not None
              and all(p not in (".", "..") for p in name.split("/")) and "\x00" not in body,
              "canonical original corpus paths and source text required")
        try:
            total += len(body.encode("utf-8"))
        except UnicodeError as error:
            raise ValueError("valid original corpus source UTF8 required") from error
        _need(total <= MAX_PROJECT_BYTES, "complete original corpus source budget exceeded")
        names.append(name)
        pairs.append([name, body])
    _need(names == sorted(set(names)), "complete distinct sorted original corpus files required")
    return {"manifest": manifest, "files": pairs}


def _identity(value):
    _keys(value, {"pid", "birth_ticks", "parent_pid", "process_group_id", "session_id"},
          "historical native process identity")
    for name, number in value.items():
        _integer(number, "historical " + name, 1)


def _historical_lifecycle(value, pid):
    """Check retained internal consistency, never current process identity."""
    _keys(value, {
        "schema", "parent", "leader", "observed_descendants", "leader_reaped",
        "descendant_tracking_complete", "group_scan_complete", "remaining_group_members",
        "remaining_tracked_descendants", "readers", "stdin_writer", "workspace",
        "observation_errors", "ownership_is_sampled", "kernel_containment_attested", "cleanup_confirmed",
    }, "historical native lifecycle")
    _need(value["schema"] == "native-owned-tool-lifecycle@1", "historical lifecycle schema differs")
    _keys(value["parent"], {"pid", "birth_ticks"}, "historical native parent")
    _integer(value["parent"]["pid"], "historical parent PID", 1)
    _integer(value["parent"]["birth_ticks"], "historical parent birth", 1)
    leader = value["leader"]
    _identity(leader)
    _need(leader["pid"] == pid and leader["parent_pid"] == value["parent"]["pid"]
          and leader["process_group_id"] == leader["session_id"] == pid
          and leader["birth_ticks"] >= value["parent"]["birth_ticks"],
          "historical native leader/parent/group/session binding differs")
    descendants = value["observed_descendants"]
    _need(type(descendants) is list and len(descendants) <= 4096,
          "bounded historical native descendant population required")
    seen = {(leader["pid"], leader["birth_ticks"])}
    for identity in descendants:
        _identity(identity)
        key = (identity["pid"], identity["birth_ticks"])
        _need(key not in seen and identity["pid"] != leader["pid"]
              and identity["birth_ticks"] >= leader["birth_ticks"]
              and identity["process_group_id"] == identity["session_id"] == pid,
              "historical descendant identity/group/session differs")
        seen.add(key)
    for name in ("leader_reaped", "descendant_tracking_complete", "group_scan_complete",
                 "ownership_is_sampled", "cleanup_confirmed"):
        _need(value[name] is True, "incomplete historical lifecycle: " + name)
    _need(value["kernel_containment_attested"] is False
          and type(value["remaining_group_members"]) is list and value["remaining_group_members"] == []
          and type(value["remaining_tracked_descendants"]) is list and value["remaining_tracked_descendants"] == []
          and type(value["observation_errors"]) is list and value["observation_errors"] == [],
          "historical lifecycle contains remaining custody or unsupported containment")
    for name, maximum in (("readers", 2), ("stdin_writer", 1)):
        row = value[name]
        _keys(row, {"started", "joined"}, "historical " + name)
        _integer(row["started"], "historical worker count", 0, maximum)
        _integer(row["joined"], "historical joined worker count", 0, maximum)
        _need(row["started"] == row["joined"], "historical native workers were not joined")
    _keys(value["workspace"], {"device", "inode", "removed"}, "historical private workspace")
    _integer(value["workspace"]["device"], "historical workspace device", 1)
    _integer(value["workspace"]["inode"], "historical workspace inode", 1)
    _need(value["workspace"]["removed"] is True, "historical workspace cleanup was not observed")


def _runtime_observations(observation, files, binaries, toolchain):
    _keys(observation, _OBSERVATION_FIELDS, "retained native observations")
    _integer(observation["pid"], "historical native PID", 1)
    _integer(observation["returncode"], "historical successful returncode", 0, 0)
    names = _binary_map(binaries)
    command = [names["lake"], "--offline", "--no-cache", "build", "legal"]
    _need(observation["command"] == observation["expected_command"] == command
          and observation["runtime"] == "native" and observation["binary_sha256"] == binaries,
          "historical command/runtime/external binary commitments differ")
    for name in ("manifest_coverage_passed", "executed_project_readback_passed", "binaries_unchanged",
                 "toolchain_probed", "installed_toolchain_verified", "post_run_validation_passed",
                 "original_preparation_unchanged", "axiom_observations_passed", "workspace_cleaned",
                 "cleanup_confirmed", "observed_process_scope_passed", "ownership_is_sampled",
                 "native_runtime_verified"):
        _need(observation[name] is True, "unsuccessful retained native observation: " + name)
    for name in ("timed_out", "cancelled", "unavailable", "output_truncated", "workspace_limit_exceeded",
                 "resource_exhausted", "kernel_containment_attested"):
        _need(observation[name] is False, "failed or overstated retained native observation: " + name)
    _need(type(observation["process_tree_terminated"]) is bool,
          "historical termination intervention must be an ordinary bool")
    _need(observation["post_run_validation_error"] is None and observation["binary_recheck_error"] is None
          and observation["axiom_observation_errors"] == [] and type(observation["axiom_observation_errors"]) is list,
          "retained native qualification errors present")
    _need(type(observation["elapsed_seconds"]) in (int, float)
          and math.isfinite(observation["elapsed_seconds"]) and observation["elapsed_seconds"] >= 0
          and type(observation["termination_reason"]) is str and len(observation["termination_reason"]) <= 256,
          "bounded historical native duration/termination observations required")
    _historical_lifecycle(observation["native_lifecycle"], observation["pid"])
    _keys(observation["version_probes"], {"lake", "lean"}, "retained native version probes")
    version = _TOOLCHAIN.fullmatch(toolchain).group(1)
    for name, probe in observation["version_probes"].items():
        _keys(probe, {"command", "returncode", "stdout", "stderr"}, "retained version probe")
        _integer(probe["returncode"], "historical version probe returncode", 0, 0)
        _need(probe["command"] == [names[name], "--version"]
              and type(probe["stdout"]) is str and type(probe["stderr"]) is str
              and len(probe["stdout"].encode()) <= MAX_RECORD_BYTES
              and len(probe["stderr"].encode()) <= MAX_RECORD_BYTES
              and re.search(r"\bversion " + re.escape(version) + r"(?:[,\s)])", probe["stdout"]),
              "historical version probe differs from externally selected toolchain")
    _keys(observation["log_sha256"], _LOG_FILES, "retained compiler log hashes")
    _keys(observation["log_bytes"], _LOG_FILES, "retained compiler log lengths")
    for name, field in (("stdout.txt", "stdout"), ("stderr.txt", "stderr"), ("runner-error.txt", "error")):
        raw = files[name]
        _integer(observation["log_bytes"][name], "retained compiler log length")
        _pin(observation["log_sha256"][name], "retained compiler log")
        _need(observation["log_bytes"][name] == len(raw)
              and observation["log_sha256"][name] == _sha(raw), "complete retained compiler log differs")
        try:
            raw.decode("utf-8")
        except UnicodeError as error:
            raise ValueError("retained compiler logs require original valid UTF8") from error
        preview = raw[:MAX_LOG_PREVIEW_BYTES].decode("utf-8", errors="replace").replace("\x00", "\\u0000")
        _need(observation[field] == preview, "retained compiler log preview differs")
    _need(files["runner-error.txt"] == b"" and observation["error"] == ""
          and observation["receipt_text_truncated"] is any(
              len(files[name]) > MAX_LOG_PREVIEW_BYTES for name in _LOG_FILES),
          "retained runner error or log preview truncation differs")


def _owners():
    from . import corpus_contracts, legal_corpus_definition_use_preservation_v2
    from . import legal_corpus_definition_use_preservation_native_v2

    return (legal_corpus_definition_use_preservation_v2,
            legal_corpus_definition_use_preservation_native_v2, corpus_contracts)


def _current_preparation(owners, corpus_preparation, assessment_raw, arguments, expected_preparation_sha256):
    pure, native, _ = owners
    prepared = pure.prepare_definition_use_preservation_v2(corpus_preparation, assessment_raw, **arguments)
    return native.validate_definition_use_preservation_native_v2(
        prepared, corpus_preparation, assessment_raw,
        expected_preparation_sha256=expected_preparation_sha256, **arguments)


def _receipt_matches(receipt, files, prepared, arguments, expected_preparation_sha256, owners):
    _, native, contracts = owners
    manifest = prepared.to_dict()
    _keys(receipt, _RECEIPT_FIELDS | set(native.FALSE_FLAGS), "complete retained native receipt")
    _need(receipt["schema"] == native.BUILD_SCHEMA and receipt["profile"] == native.PROFILE,
          "retained native receipt schema/profile differs")
    contracts.validate_record(receipt, schema=native.BUILD_SCHEMA,
        fields=set(receipt) - {"schema", "record_cid", "cid_scope"})
    _need(receipt["build_passed"] is True and receipt["status"] == "corpus_native_preservation_checks_passed"
          and receipt["proof_scope"] == _PROOF_SCOPE,
          "successful retained concrete corpus observation required")
    for name in native.FALSE_FLAGS:
        _need(receipt[name] is (name in _SUCCESS_FLAGS), "retained source/proof/cache scope differs: " + name)
    _need(receipt["authority"] == AUTHORITY
          and all(value is False for value in receipt["authority"].values()),
          "retained native receipt grants unsupported authority")
    for name in ("training_mask", "evaluation_gold_mask"):
        _integer(receipt[name], "retained authority mask", 0, 0)
    expected = {
        "preparation_cid": manifest["record_cid"],
        "preparation_full_canonical_sha256": expected_preparation_sha256,
        "preparation_manifest_sha256": _sha(prepared.manifest_json.encode()),
        "corpus_preparation_full_canonical_sha256": arguments["expected_corpus_preparation_sha256"],
        "assessment_file_sha256": arguments["expected_assessment_file_sha256"],
        "toolchain": arguments["toolchain"],
        "original_preparation_state": native._original_preparation_state(manifest),
        "preservation_fragments": manifest["preservation_fragments"],
        "reference_contract": manifest["reference_contract"],
    }
    _need(_wire({name: receipt[name] for name in expected}) == _wire(expected),
          "retained native receipt differs from full current preparation/source/review binding")
    observation = receipt["native_observations"]
    modules = manifest["expected_modules"]
    _need(len(modules) == MAX_MODULES and observation["expected_modules"] == observation["compiled_modules"] == modules,
          "complete retained module population differs")
    source_files = {name: body.encode() for name, body in prepared.files}
    artifact_paths = [".lake/build/lib/lean/" + name.replace(".", "/") + ".olean" for name in modules]
    artifact_files = {path: "compiled/" + path.removeprefix(".lake/build/lib/lean/") for path in artifact_paths}
    expected_names = ({"project/" + name for name in source_files}
        | {"project/corpus-manifest.json"} | {"executed-inputs/" + name for name in source_files}
        | set(artifact_files.values()) | _ROOT_FILES)
    _need(set(files) == expected_names and len(expected_names) == MAX_FILES,
          "complete exact retained packet file paths differ from current project")
    _need(files["project/corpus-manifest.json"] == prepared.manifest_json.encode()
          and all(files["project/" + name] == raw == files["executed-inputs/" + name]
                  for name, raw in source_files.items()),
          "retained frozen/executed project bytes differ from authoritative regeneration")
    _need(observation["executed_project_sha256"] == {name: _sha(raw) for name, raw in source_files.items()},
          "retained executed input commitments differ")
    for name in ("artifact_sha256", "artifact_bytes", "artifact_files"):
        _keys(observation[name], artifact_paths, "retained native artifact population")
    _need(observation["artifact_files"] == artifact_files,
          "retained artifact path mapping differs from original module identities")
    for path, retained in artifact_files.items():
        raw = files[retained]
        _integer(observation["artifact_bytes"][path], "retained compiled module bytes", 1)
        _pin(observation["artifact_sha256"][path], "retained compiled module")
        _need(raw and observation["artifact_bytes"][path] == len(raw)
              and observation["artifact_sha256"][path] == _sha(raw),
              "retained compiled module identity differs")
    for name in ("theorems", "conditional_theorems", "preservation_theorems"):
        _need(observation[name] == manifest[name], "retained theorem names/partition differ")
    axioms, errors, passed = native._axiom_observations(
        files["stdout.txt"].decode(), files["stderr.txt"].decode(), manifest)
    _need(len(manifest["theorems"]) == MAX_THEOREMS and passed and errors == []
          and observation["theorem_axiom_dependencies"] == axioms
          and observation["concrete_kernel_status"] == "checked_exact_four_fragment_instances"
          and observation["conditional_kernel_status"] == "checked_under_explicit_hypotheses",
          "complete retained fifteen empty-axiom observations differ")
    current = native._pins(native._owners(), manifest)
    _need(observation["producer_pins"] == current,
          "historical native producer pins differ from current qualified owners")
    return manifest, current


@dataclass(frozen=True)
class RetainedDefinitionUsePreservationPacket:
    observation_json: str
    files: tuple[tuple[str, bytes], ...]

    def to_dict(self):
        _need(type(self.observation_json) is str, "retained packet observation text required")
        value = _parse(self.observation_json.encode())
        _need(type(value) is dict, "retained packet observation object required")
        return value


def validate_definition_use_preservation_packet_v2(
        packet_files, corpus_preparation, assessment_raw, *, expected_preparation_sha256,
        expected_corpus_preparation_sha256, expected_assessment_file_sha256,
        expected_receipt_file_sha256, expected_bundle_sha256, review_inputs, toolchain,
        expected_binary_sha256):
    """Replay current owners and exact retained bytes, without native execution.

    Expected pins must come from independently trusted provenance. Self-sealed
    invented evidence with invented expected pins is not authenticated by this
    API. Filesystem identity/race/link custody belongs to the external acquirer.
    """
    for value, label in ((expected_preparation_sha256, "complete current preservation preparation"),
                         (expected_corpus_preparation_sha256, "complete original corpus preparation"),
                         (expected_assessment_file_sha256, "original assessment file"),
                         (expected_receipt_file_sha256, "exact retained native receipt file"),
                         (expected_bundle_sha256, "complete retained forty-nine-file bundle")):
        _pin(value, label)
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain),
          "exact version-pinned retained packet toolchain required")
    _binary_map(expected_binary_sha256)
    binaries = dict(expected_binary_sha256)
    _need(type(assessment_raw) is bytes and 0 < len(assessment_raw) <= MAX_RECORD_BYTES
          and _sha(assessment_raw) == expected_assessment_file_sha256,
          "independently pinned bounded original assessment bytes required")
    old = _corpus_document(corpus_preparation)
    old_raw = _wire(old, 20 * MAX_RECORD_BYTES)
    _need(_sha(old_raw) == expected_corpus_preparation_sha256,
          "independent complete original corpus preparation pin differs")
    _keys(review_inputs, _REVIEW_FIELDS, "complete original corpus review inputs")
    _bound_tree(review_inputs, MAX_INPUT_BYTES - len(old_raw) - len(assessment_raw), allow_bytes=True)
    for name in ("expected_subject_sha256", "expected_registry_sha256", "expected_policy_sha256",
                 "expected_reviews_sha256", "expected_manifest_sha256"):
        _pin(review_inputs[name], name)
    review_snapshot = _review_snapshot(review_inputs)
    files, inventory = _packet_document(packet_files)
    _need(_sha(_wire(inventory)) == expected_bundle_sha256, "independent complete retained bundle pin differs")
    receipt_raw = files["build-receipt.json"]
    _need(_sha(receipt_raw) == expected_receipt_file_sha256, "independent exact raw receipt file pin differs")
    # Original receipt bytes and the complete inventory are pinned before any
    # receipt parse or operation-owner import.
    receipt = _parse(receipt_raw)
    _need(type(receipt) is dict and type(receipt.get("native_observations")) is dict,
          "complete retained native receipt object required")
    _runtime_observations(receipt["native_observations"], files, binaries, toolchain)
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "retained packet reader changed since import")
    owners = _owners()
    arguments = {
        "expected_corpus_preparation_sha256": expected_corpus_preparation_sha256,
        "expected_assessment_file_sha256": expected_assessment_file_sha256,
        "review_inputs": review_inputs, "toolchain": toolchain,
    }
    prepared = _current_preparation(owners, corpus_preparation, assessment_raw, arguments, expected_preparation_sha256)
    manifest, historical_pins = _receipt_matches(
        receipt, files, prepared, arguments, expected_preparation_sha256, owners)
    again = _current_preparation(owners, corpus_preparation, assessment_raw, arguments, expected_preparation_sha256)
    _need(again == prepared and _corpus_document(corpus_preparation) == old
          and expected_binary_sha256 == binaries and packet_sha256(packet_files) == expected_bundle_sha256,
          "original retained packet, corpus or compatibility inputs changed during replay")
    _, current = _receipt_matches(receipt, files, again, arguments, expected_preparation_sha256, owners)
    _need(current == historical_pins and _sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "retained packet reader/current producer identities changed during replay")
    _keys(review_inputs, _REVIEW_FIELDS, "final original corpus review inputs")
    _bound_tree(review_inputs, MAX_INPUT_BYTES - len(old_raw) - len(assessment_raw), allow_bytes=True)
    _need(_review_snapshot(review_inputs) == review_snapshot,
          "complete original review inputs changed during retained packet replay")
    current_pins = dict(current)
    current_pins[str(Path(__file__).resolve())] = _SELF_PIN
    observation = owners[2].seal_record({
        "schema": SCHEMA, "profile": PROFILE,
        "packet_bundle_sha256": expected_bundle_sha256,
        "receipt_file_sha256": expected_receipt_file_sha256,
        "preparation_full_canonical_sha256": expected_preparation_sha256,
        "corpus_preparation_full_canonical_sha256": expected_corpus_preparation_sha256,
        "assessment_file_sha256": expected_assessment_file_sha256,
        "toolchain": toolchain, "expected_binary_sha256": binaries,
        "current_producer_pins": current_pins, "historical_producer_pins": historical_pins,
        "historical_native_receipt": receipt, "packet_inventory": inventory,
        "reference_contract": manifest["reference_contract"],
        "readback_verified": True, "current_preparation_replayed": True,
        "historical_kernel_observations_retained": True,
        "source_custody": {
            "original_corpus_source_review_dependencies_replayed": True,
            "current_producer_compatibility_required": True,
            "historical_lifecycle_internal_consistency_checked": True,
            "historical_process_liveness_inspected": False,
            "filesystem_acquisition_performed": False,
            "source_review_eligibility_unchanged": True,
            "original_receipt_unchanged": True,
        },
        "trust_boundary": [
            "Independent externally trusted raw receipt and whole-bundle pins are provenance premises; self-sealed claims are not cryptographic authentication.",
            "The external transport owns filesystem paths, identity races, symlink/hardlink refusal and faithful immutable byte acquisition.",
            "Historical process, compiler and kernel observations are validated as internally consistent retained evidence, not re-executed or independently attested.",
            "No installed compiler bytes or historical process liveness are inspected; no Lean execution, olean kernel check or proof-cache write occurs.",
            "Current source/review/preparation and producer compatibility is mandatory; producer drift has no weaker historical fallback in this profile.",
        ],
        "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        **FALSE_FLAGS,
    })
    result = RetainedDefinitionUsePreservationPacket(_wire(observation).decode(), tuple(packet_files))
    _need(result.files == packet_files, "retained packet bytes changed during observation assembly")
    return result


__all__ = ["RetainedDefinitionUsePreservationPacket", "packet_sha256",
           "validate_definition_use_preservation_packet_v2"]
