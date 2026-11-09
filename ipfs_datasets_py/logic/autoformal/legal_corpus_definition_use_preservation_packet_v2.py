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


def _bound_tree(value, maximum, *, allow_bytes=False, maximum_depth=96, maximum_nodes=2_000_000):
    remaining, nodes = maximum, maximum_nodes

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= maximum_depth, "retained packet input node/depth bound exceeded")
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


# Opt-in retained direct-parent norm observations. The official49-file profile
# and every existing preparation, packet and index API remain unchanged.
PARENT_NORM_PACKET_SCHEMA = "legal-corpus-parent-norm-native-packet-observation/v1"
PARENT_NORM_PACKET_PROFILE = "replayed-retained-parent-literal-complete-authored-norm-native-byte-packet/v1"
_PARENT_NORM_PACKET_BUILD_SCHEMA = "legal-corpus-parent-norm-native-build/v1"
_PARENT_NORM_PACKET_NATIVE_PROFILE = "replayed-parent-literal-complete-authored-norm-native-build/v1"
_PARENT_NORM_PACKET_PREPARATION_SCHEMA = "legal-corpus-parent-norm-lake-preparation/v1"
_PARENT_NORM_PACKET_PREPARATION_PROFILE = "replayed-parent-literal-complete-authored-norm-project/v1"
_PARENT_NORM_PACKET_REPLAY_FIELDS = frozenset({"scope_report", "relational_report", "mapping_request_raw",
    "expected_scope_report_sha256", "expected_relational_report_sha256",
    "expected_mapping_request_sha256", "scope_replay_inputs", "relational_request_raw",
    "expected_relational_request_sha256"})
_PARENT_NORM_PACKET_SCOPE = ("Only original_norm_preserved, a definitional alias identity under explicit "
    "Entity, Agent, Interpretation and time. No norm truth, source meaning, governing edition, "
    "definition applicability, graph/corpus admission, model equivalence or convergence claim.")
_PARENT_NORM_PACKET_SUCCESS_FLAGS = frozenset({"backend_executed", "lean_compilation_verified",
    "proof_checked", "kernel_proofs_checked", "conditional_proofs_verified"})
_PARENT_NORM_PACKET_RECEIPT_FIELDS = (_OBSERVATION_FIELDS - {
    "theorems", "preservation_theorems", "concrete_kernel_status"}) | frozenset({
    "schema", "profile", "record_cid", "cid_scope", "preparation_cid",
    "preparation_full_canonical_sha256", "preparation_manifest_sha256", "toolchain",
    "correspondence_sha256", "original_input_commitment_sha256", "parent_source_binding_sha256",
    "original_norm_sha256", "review_intake_binding_sha256", "source_context_sha256",
    "retained_unresolved_sha256", "review_blockers", "original_preparation_build_eligible",
    "original_preparation_execution_handoff", "preservation_kind", "theorem_assumptions",
    "original_preparation_theorem_assumptions", "build_passed", "status", "alias_assumption_proved",
    "source_to_model_equivalence_proved", "authority", "training_mask", "evaluation_gold_mask", "scope",
})


def _parent_norm_packet_document(packet_files, *, maximum_files=23, expected_groups=(8, 7, 4)):
    """Use the existing inventory wire contract with a separate23-file population."""
    _need(type(packet_files) is tuple and len(packet_files) == maximum_files,
          "complete immutable twenty-three-file parent norm packet required")
    names, inventory, contents, total = [], [], {}, 0
    groups = {"project": 0, "executed-inputs": 0, "compiled": 0}
    sizes = dict.fromkeys(groups, 0)
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
            limit = MAX_RECORD_BYTES if name == "project/corpus-manifest.json" else MAX_PROJECT_BYTES
            if name != "project/corpus-manifest.json":
                sizes[group] += len(raw)
        _need(len(raw) <= limit, "retained packet file exceeds its bound")
        total += len(raw)
        _need(total <= MAX_PACKET_BYTES, "complete retained packet exceeds sixty-four MiB")
        names.append(name); contents[name] = raw
        inventory.append({"path": name, "bytes": len(raw), "sha256": _sha(raw)})
    _need(names == sorted(set(names)), "distinct canonical sorted retained packet paths required")
    _need(set(name for name in names if "/" not in name) == _ROOT_FILES
          and groups == dict(zip(("project", "executed-inputs", "compiled"), expected_groups, strict=True))
          and all(size <= MAX_PROJECT_BYTES for size in sizes.values()),
          "complete bounded parent norm project/input/artifact/log populations required")
    return contents, inventory


def parent_norm_packet_sha256(packet_files):
    """Commit the direct-parent23-file inventory without accepting execution."""
    _, inventory = _parent_norm_packet_document(packet_files)
    return _sha(_wire(inventory))


def _parent_norm_packet_storage(preparation, *, maximum_files=7,
        preparation_schema=_PARENT_NORM_PACKET_PREPARATION_SCHEMA,
        preparation_profile=_PARENT_NORM_PACKET_PREPARATION_PROFILE):
    cls = type(preparation)
    _need(cls.__module__ == _CORPUS_MODULE and cls.__name__ == "DefinitionUseCorpusPreparation",
          "original typed direct parent norm preparation required")
    try:
        data = object.__getattribute__(preparation, "__dict__")
    except AttributeError as error:
        raise ValueError("closed original parent norm preparation storage required") from error
    _keys(data, {"manifest_json", "files"}, "original parent norm preparation storage")
    text, files = data["manifest_json"], data["files"]
    _need(type(text) is str and type(files) is tuple and len(files) == maximum_files,
          "complete original seven-file parent norm preparation required")
    manifest = _parse(text.encode("utf-8"))
    _need(type(manifest) is dict and manifest.get("schema") == preparation_schema
          and manifest.get("profile") == preparation_profile,
          "explicit direct parent norm preparation schema/profile required")
    names, pairs, total = [], [], 0
    for item in files:
        _need(type(item) is tuple and len(item) == 2, "original parent norm path/text pairs required")
        name, body = item
        _need(type(name) is str and len(name) <= 256 and type(body) is str
              and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?", name) is not None
              and all(part not in (".", "..") for part in name.split("/")) and "\x00" not in body,
              "canonical original parent norm paths/source required")
        try:
            total += len(body.encode("utf-8"))
        except UnicodeError as error:
            raise ValueError("valid original parent norm source UTF8 required") from error
        _need(total <= MAX_PROJECT_BYTES, "complete parent norm source byte bound exceeded")
        names.append(name); pairs.append([name, body])
    _need(names == sorted(set(names)), "distinct sorted original parent norm files required")
    return {"manifest_json": text, "files": pairs}


def _parent_norm_packet_copy(value):
    # The complete ordinary tree is bounded before this callback-free copier.
    if type(value) is dict:
        return {key: _parent_norm_packet_copy(child) for key, child in value.items()}
    if type(value) is list:
        return [_parent_norm_packet_copy(child) for child in value]
    _need(value is None or type(value) in (str, bytes, bool, int, float),
          "ordinary parent norm original input required")
    return value


def _parent_norm_packet_runtime_observations(receipt, files, binaries, toolchain):
    """Validate flattened direct-native retained observations, never live tools."""
    _integer(receipt["pid"], "historical native PID", 1)
    _integer(receipt["returncode"], "historical successful returncode", 0, 0)
    names = _binary_map(binaries)
    command = [names["lake"], "--offline", "--no-cache", "build", "legal"]
    _need(receipt["command"] == receipt["expected_command"] == command
          and receipt["runtime"] == "native" and receipt["binary_sha256"] == binaries,
          "historical parent norm command/runtime/binary commitments differ")
    for name in ("manifest_coverage_passed", "executed_project_readback_passed", "binaries_unchanged",
                 "post_run_validation_passed", "original_preparation_unchanged", "axiom_observations_passed",
                 "workspace_cleaned", "cleanup_confirmed", "observed_process_scope_passed",
                 "ownership_is_sampled", "native_runtime_verified", "build_passed"):
        _need(receipt[name] is True, "unsuccessful retained parent norm observation: " + name)
    for name in ("timed_out", "cancelled", "unavailable", "output_truncated", "workspace_limit_exceeded",
                 "resource_exhausted", "kernel_containment_attested", "toolchain_probed",
                 "installed_toolchain_verified", "build_eligible", "native_build_profile_registered"):
        _need(receipt[name] is False, "failed or overstated retained parent norm observation: " + name)
    _need(type(receipt["process_tree_terminated"]) is bool,
          "historical termination intervention must be an ordinary bool")
    _need(receipt["post_run_validation_error"] is None and receipt["binary_recheck_error"] is None
          and type(receipt["axiom_observation_errors"]) is list and receipt["axiom_observation_errors"] == [],
          "retained parent norm qualification errors present")
    _need(type(receipt["elapsed_seconds"]) in (int, float) and math.isfinite(receipt["elapsed_seconds"])
          and receipt["elapsed_seconds"] >= 0 and type(receipt["termination_reason"]) is str
          and len(receipt["termination_reason"]) <= 256,
          "bounded historical native duration/termination observations required")
    _historical_lifecycle(receipt["native_lifecycle"], receipt["pid"])
    _keys(receipt["version_probes"], {"lake", "lean"}, "retained native version probes")
    version = _TOOLCHAIN.fullmatch(toolchain).group(1)
    for name, probe in receipt["version_probes"].items():
        _keys(probe, {"command", "returncode", "stdout", "stderr"}, "retained version probe")
        _integer(probe["returncode"], "historical version probe returncode", 0, 0)
        _need(probe["command"] == [names[name], "--version"]
              and type(probe["stdout"]) is str and type(probe["stderr"]) is str
              and len(probe["stdout"].encode()) <= MAX_RECORD_BYTES
              and len(probe["stderr"].encode()) <= MAX_RECORD_BYTES
              and re.search(r"\bversion " + re.escape(version) + r"(?:[,\s)])", probe["stdout"]),
              "historical version probe differs from externally selected toolchain")
    _keys(receipt["log_sha256"], _LOG_FILES, "retained compiler log hashes")
    _keys(receipt["log_bytes"], _LOG_FILES, "retained compiler log lengths")
    for name, field in (("stdout.txt", "stdout"), ("stderr.txt", "stderr"), ("runner-error.txt", "error")):
        raw = files[name]
        _integer(receipt["log_bytes"][name], "retained compiler log length")
        _pin(receipt["log_sha256"][name], "retained compiler log")
        _need(receipt["log_bytes"][name] == len(raw) and receipt["log_sha256"][name] == _sha(raw),
              "complete retained compiler log differs")
        try:
            raw.decode("utf-8")
        except UnicodeError as error:
            raise ValueError("retained compiler logs require original valid UTF8") from error
        preview = raw[:MAX_LOG_PREVIEW_BYTES].decode("utf-8", errors="replace").replace("\x00", "\\u0000")
        _need(receipt[field] == preview, "retained compiler log preview differs")
    _need(files["runner-error.txt"] == b"" and receipt["error"] == ""
          and receipt["receipt_text_truncated"] is any(len(files[name]) > MAX_LOG_PREVIEW_BYTES for name in _LOG_FILES),
          "retained runner error or log preview truncation differs")


def _parent_norm_packet_owners():
    from . import legal_corpus_definition_use_native_v2, corpus_contracts
    return legal_corpus_definition_use_native_v2, corpus_contracts


def _parent_norm_packet_current_preparation(owners, preparation, correspondence, arguments):
    return owners[0].validate_parent_norm_native_v1(preparation, correspondence, **arguments)


def _parent_norm_packet_receipt_matches(receipt, files, prepared, arguments,
                                        expected_preparation_sha256, owners, *, parent_bound_context=None):
    native, contracts = owners
    selected_bound = parent_bound_context is not None
    if selected_bound:
        storage = _parent_bound_norm_packet_storage(prepared)
        manifest = _parse(storage["manifest_json"].encode())
        authority = manifest.get("authority")
        _need(type(authority) is dict and bool(authority)
              and all(value is False for value in authority.values()),
              "exact unadmitted parent bound preparation authority required")
        flags = {**authority, **native.FALSE_FLAGS}
        receipt_fields = _PARENT_BOUND_NORM_PACKET_RECEIPT_FIELDS
        build_schema, native_profile = _PARENT_BOUND_NORM_PACKET_BUILD_SCHEMA, _PARENT_BOUND_NORM_PACKET_NATIVE_PROFILE
        proof_scope = _PARENT_BOUND_NORM_PACKET_SCOPE
    else:
        storage = _parent_norm_packet_storage(prepared)
        manifest = _parse(storage["manifest_json"].encode())
        preparer = native._owners()[0]
        flags = {**preparer.PARENT_NORM_FALSE_FLAGS, **native.FALSE_FLAGS}
        receipt_fields = _PARENT_NORM_PACKET_RECEIPT_FIELDS
        build_schema, native_profile = _PARENT_NORM_PACKET_BUILD_SCHEMA, _PARENT_NORM_PACKET_NATIVE_PROFILE
        proof_scope = _PARENT_NORM_PACKET_SCOPE
    _keys(receipt, receipt_fields | set(flags), "complete retained parent norm native receipt")
    _need(receipt["schema"] == build_schema
          and receipt["profile"] == native_profile,
          "retained direct parent norm native receipt schema/profile differs")
    contracts.validate_record(receipt, schema=build_schema,
                             fields=set(receipt) - {"schema", "record_cid", "cid_scope"})
    _need(receipt["status"] == "conditional_native_checks_passed" and receipt["scope"] == proof_scope
          and receipt["preservation_kind"] == "definitional_alias_identity_only",
          "exact retained parent norm alias-identity scope required")
    for name in flags:
        _need(receipt[name] is (name in _PARENT_NORM_PACKET_SUCCESS_FLAGS),
              "retained parent norm source/proof/cache scope differs: " + name)
    _need(receipt["authority"] == AUTHORITY and all(value is False for value in receipt["authority"].values())
          and receipt["alias_assumption_proved"] is False and receipt["source_to_model_equivalence_proved"] is False,
          "retained parent norm receipt grants unsupported authority")
    for name in (("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask")
                 if selected_bound else ("training_mask", "evaluation_gold_mask")):
        _integer(receipt[name], "retained authority mask", 0, 0)
    expected = {}
    if not selected_bound:
        expected = {
            "preparation_cid": manifest["record_cid"],
            "preparation_full_canonical_sha256": expected_preparation_sha256,
            "preparation_manifest_sha256": _sha(storage["manifest_json"].encode()),
            "correspondence_sha256": arguments["expected_correspondence_sha256"],
            "original_input_commitment_sha256": manifest["original_input_commitment_sha256"],
            "parent_source_binding_sha256": manifest["parent_source_binding_sha256"],
            "original_norm_sha256": _sha(_wire(manifest["original_norm"])),
            "review_intake_binding_sha256": _sha(_wire(manifest["review_intake_binding"])),
            "source_context_sha256": _sha(_wire(manifest["original_parent_context"])),
            "retained_unresolved_sha256": _sha(_wire(manifest["correspondence"]["retained_unresolved"])),
            "review_blockers": manifest["review_blockers"],
            "original_preparation_build_eligible": manifest["build_eligible"],
            "original_preparation_execution_handoff": manifest["execution_handoff"],
            "original_preparation_theorem_assumptions": manifest["theorem_assumptions"],
            "theorem_assumptions": manifest["theorem_assumptions"],
            "toolchain": arguments["toolchain"],
        }
    else:
        expected = _parent_bound_norm_packet_bindings(manifest, storage, arguments, expected_preparation_sha256)
    _need(_wire({name: receipt[name] for name in expected}) == _wire(expected),
          "retained parent norm receipt differs from complete current original bindings")
    modules, theorems = manifest["expected_modules"], manifest["conditional_theorems"]
    module_count = 6 if selected_bound else 4
    theorem_count = ((2 if manifest["bound_definition_mode"] == "instance_only" else 3)
                     if selected_bound else 1)
    _need(type(modules) is list and len(modules) == module_count and len(set(modules)) == module_count
          and receipt["expected_modules"] == receipt["compiled_modules"] == modules
          and type(theorems) is list and len(theorems) == theorem_count and theorems[-1].endswith(".original_norm_preserved")
          and receipt["conditional_theorems"] == theorems
          and manifest["original_norm"]["source_binding"] is None
          and manifest["original_norm"]["source_bound"] is False,
          "exact unadmitted parent norm module/theorem population required")
    source_files = {name: body.encode() for name, body in storage["files"]}
    artifact_paths = [".lake/build/lib/lean/" + name.replace(".", "/") + ".olean" for name in modules]
    artifact_files = {path: "compiled/" + path.removeprefix(".lake/build/lib/lean/") for path in artifact_paths}
    expected_names = ({"project/" + name for name in source_files} | {"project/corpus-manifest.json"}
        | {"executed-inputs/" + name for name in source_files} | set(artifact_files.values()) | _ROOT_FILES)
    _need(set(files) == expected_names and len(expected_names) == (29 if selected_bound else 23),
          "complete exact retained parent norm packet paths differ from current project")
    _need(files["project/corpus-manifest.json"] == storage["manifest_json"].encode()
          and all(files["project/" + name] == raw == files["executed-inputs/" + name]
                  for name, raw in source_files.items()),
          "retained parent norm frozen/executed project differs from authoritative replay")
    _need(receipt["executed_project_sha256"] == {name: _sha(raw) for name, raw in source_files.items()},
          "retained parent norm executed input commitments differ")
    for name in ("artifact_sha256", "artifact_bytes", "artifact_files"):
        _keys(receipt[name], artifact_paths, "retained parent norm artifact population")
    _need(receipt["artifact_files"] == artifact_files, "retained parent norm artifact path mapping differs")
    for path, retained in artifact_files.items():
        raw = files[retained]
        _integer(receipt["artifact_bytes"][path], "retained compiled module bytes", 1)
        _pin(receipt["artifact_sha256"][path], "retained compiled module")
        _need(raw and receipt["artifact_bytes"][path] == len(raw) and receipt["artifact_sha256"][path] == _sha(raw),
              "retained parent norm compiled module identity differs")
    _parent_norm_packet_runtime_observations(receipt, files, arguments["expected_binary_sha256"], arguments["toolchain"])
    axioms, errors, passed = native._axiom_observations(
        files["stdout.txt"].decode(), files["stderr.txt"].decode(), manifest, maximum_theorems=3 if selected_bound else 1)
    _need(passed and errors == [] and axioms == {name: [] for name in theorems}
          and receipt["theorem_axiom_dependencies"] == axioms
          and receipt["conditional_kernel_status"] == "checked_under_explicit_hypotheses",
          "retained single empty-axiom alias observation differs")
    current = (_parent_bound_norm_packet_pins(parent_bound_context, manifest) if selected_bound
               else native._parent_norm_native_pins(native._owners(), manifest))
    _need(receipt["producer_pins"] == current,
          "historical parent norm producer paths/generations differ from current owners; no relocation fallback")
    return manifest, current


def _parent_norm_packet_callbacks(owners):
    native, contracts = owners
    functions = (_need, _sha, _pin, _keys, _integer, _bound_tree, _wire, _parse, _review_snapshot,
        _binary_map, _historical_lifecycle, _identity, _parent_norm_packet_document,
        parent_norm_packet_sha256, _parent_norm_packet_storage, _parent_norm_packet_copy,
        _parent_norm_packet_runtime_observations, _parent_norm_packet_owners,
        _parent_norm_packet_current_preparation, _parent_norm_packet_receipt_matches,
        _parent_norm_packet_callbacks, _parent_norm_packet_runtime,
        validate_parent_norm_native_packet_v1, RetainedDefinitionUsePreservationPacket,
        RetainedDefinitionUsePreservationPacket.__init__, RetainedDefinitionUsePreservationPacket.to_dict,
        contracts.validate_record, contracts.seal_record, json.dumps, json.loads)
    observed = tuple((function, getattr(function, "__code__", None),
        id(getattr(function, "__defaults__", None)), id(getattr(function, "__kwdefaults__", None)))
        for function in functions)
    return observed + native._parent_norm_native_callbacks(native._owners())


def _parent_norm_packet_runtime(owners):
    return {"schema": PARENT_NORM_PACKET_SCHEMA, "profile": PARENT_NORM_PACKET_PROFILE,
        "build_schema": _PARENT_NORM_PACKET_BUILD_SCHEMA, "native_profile": _PARENT_NORM_PACKET_NATIVE_PROFILE,
        "preparation_schema": _PARENT_NORM_PACKET_PREPARATION_SCHEMA,
        "preparation_profile": _PARENT_NORM_PACKET_PREPARATION_PROFILE,
        "replay_fields": sorted(_PARENT_NORM_PACKET_REPLAY_FIELDS),
        "receipt_fields": sorted(_PARENT_NORM_PACKET_RECEIPT_FIELDS), "scope": _PARENT_NORM_PACKET_SCOPE,
        "success_flags": sorted(_PARENT_NORM_PACKET_SUCCESS_FLAGS), "authority": dict(AUTHORITY),
        "false_flags": dict(FALSE_FLAGS), "root_files": sorted(_ROOT_FILES), "log_files": sorted(_LOG_FILES),
        "record_bytes": MAX_RECORD_BYTES, "packet_bytes": MAX_PACKET_BYTES, "input_bytes": MAX_INPUT_BYTES,
        "project_bytes": MAX_PROJECT_BYTES, "log_bytes": MAX_LOG_BYTES, "preview_bytes": MAX_LOG_PREVIEW_BYTES,
        "toolchain_pattern": _TOOLCHAIN.pattern, "corpus_module": _CORPUS_MODULE,
        "reader_path": str(Path(__file__).resolve()),
        "shared_helper_kwdefaults": _parent_norm_packet_kwdefaults(),
        "native_runtime": owners[0]._parent_norm_native_runtime(owners[0]._owners())}


def validate_parent_norm_native_packet_v1(
        packet_files, preparation, correspondence, *, expected_preparation_sha256,
        expected_correspondence_sha256, correspondence_inputs, toolchain,
        expected_receipt_file_sha256, expected_bundle_sha256, expected_binary_sha256):
    """Replay an exact retained23-file packet as consistency evidence only.

    A persisted successful receipt may precede a later outer custody refusal.
    This API has no accepted outer-result/closeout input and NEVER accepts that
    execution. Independently trusted raw pins are provenance premises, not
    authentication. Historical source paths must match current owners exactly;
    old frozen/relocated23 receipts have no implicit compatibility fallback.
    """
    for value, label in ((expected_preparation_sha256, "complete parent norm preparation"),
            (expected_correspondence_sha256, "complete original parent correspondence"),
            (expected_receipt_file_sha256, "exact retained parent norm native receipt file"),
            (expected_bundle_sha256, "complete retained twenty-three-file bundle")):
        _pin(value, label)
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain),
          "exact version-pinned parent norm packet toolchain required")
    _binary_map(expected_binary_sha256)
    binaries = dict(expected_binary_sha256)
    storage = _parent_norm_packet_storage(preparation)
    document = {"manifest": _parse(storage["manifest_json"].encode()), "files": storage["files"]}
    _need(_sha(_wire(document, 20 * MAX_RECORD_BYTES)) == expected_preparation_sha256,
          "independent complete parent norm preparation pin differs")
    _need(type(correspondence) is dict, "complete original parent correspondence required")
    _keys(correspondence_inputs, _PARENT_NORM_PACKET_REPLAY_FIELDS, "complete original parent correspondence replay")
    original = {"preparation": storage, "correspondence": correspondence,
        "correspondence_inputs": correspondence_inputs, "expected_binary_sha256": expected_binary_sha256,
        "expected_preparation_sha256": expected_preparation_sha256,
        "expected_correspondence_sha256": expected_correspondence_sha256, "toolchain": toolchain}
    _bound_tree(original, MAX_INPUT_BYTES, allow_bytes=True)
    snapshot = _review_snapshot(original)
    copied = _parent_norm_packet_copy(original)
    _need(_review_snapshot(copied) == snapshot, "complete detached parent norm original inputs differ")
    _need(_sha(_wire(correspondence, MAX_PROJECT_BYTES)) == expected_correspondence_sha256,
          "independent complete parent correspondence pin differs")
    files, inventory = _parent_norm_packet_document(packet_files)
    _need(_sha(_wire(inventory)) == expected_bundle_sha256, "independent complete retained bundle pin differs")
    receipt_raw = files["build-receipt.json"]
    _need(_sha(receipt_raw) == expected_receipt_file_sha256, "independent exact raw receipt file pin differs")
    receipt = _parse(receipt_raw)
    _need(type(receipt) is dict and receipt.get("schema") == _PARENT_NORM_PACKET_BUILD_SCHEMA
          and receipt.get("profile") == _PARENT_NORM_PACKET_NATIVE_PROFILE,
          "explicit retained direct parent norm native receipt required")
    _need(type(receipt.get("binary_sha256")) is dict and receipt["binary_sha256"] == binaries,
          "independent retained parent norm binary commitments differ")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "parent norm packet reader changed since import")
    # Independent pins, complete ordinary input bounds and exact byte population
    # precede lazy loading of genuine operation owners.
    owners = _parent_norm_packet_owners()
    native, contracts = owners
    native_owners = native._owners()
    preparer = native_owners[0]
    from . import legal_norm_scope_correspondence_v1 as correspondence_owner
    finish = correspondence_owner._owners()[0]._parent_finish
    _need(type(preparation) is preparer.DefinitionUseCorpusPreparation,
          "genuine current direct parent norm preparation type required")
    arguments = {"expected_preparation_sha256": expected_preparation_sha256,
        "expected_correspondence_sha256": expected_correspondence_sha256,
        "correspondence_inputs": copied["correspondence_inputs"], "toolchain": toolchain}
    receipt_arguments = {**arguments, "expected_binary_sha256": binaries}
    callbacks, runtime = _parent_norm_packet_callbacks(owners), _parent_norm_packet_runtime(owners)
    held, preparations = [], []
    state = {"pins": None, "plan": None, "witness": None, "observation": None, "wire": None, "result": None}
    primary = None

    def hold(value, label):
        _bound_tree(value, MAX_PACKET_BYTES, allow_bytes=True)
        held.append((value, _review_snapshot(value), label))
        return value

    hold(receipt, "parsed original receipt"); hold(inventory, "complete original inventory")
    hold(files, "complete original byte population"); hold(arguments, "detached replay arguments")
    hold(receipt_arguments, "detached receipt arguments"); hold(document, "original parsed preparation")

    def fence():
        _need(_parent_norm_packet_callbacks(owners) == callbacks
              and _parent_norm_packet_runtime(owners) == runtime,
              "parent norm packet operation callable or runtime declarations changed")
        _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "parent norm packet reader source changed")
        now = {**original, "preparation": _parent_norm_packet_storage(preparation)}
        _bound_tree(now, MAX_INPUT_BYTES, allow_bytes=True)
        _need(_review_snapshot(now) == snapshot and _review_snapshot(copied) == snapshot,
              "complete original or detached parent norm packet inputs changed")
        _need(parent_norm_packet_sha256(packet_files) == expected_bundle_sha256
              and expected_binary_sha256 == binaries, "original parent norm packet or binary commitments changed")
        for value, expected, label in held:
            _bound_tree(value, MAX_PACKET_BYTES, allow_bytes=True)
            _need(_review_snapshot(value) == expected, "held parent norm packet return changed: " + label)
        for value in preparations:
            _need(_parent_norm_packet_storage(value) == storage,
                  "genuine parent norm preparation raw return changed")
        if state["pins"] is not None:
            _need(native._parent_norm_native_pins(native_owners, document["manifest"]) == state["pins"],
                  "current parent norm producer identities changed")
        if state["plan"] is not None:
            _need(preparer._parent_norm_file_witness(state["plan"]) == state["witness"],
                  "original parent norm physical source/context witnesses changed")
        serialized_fence()

    def serialized_fence():
        if state["observation"] is not None:
            _need(_wire(state["observation"]) == state["wire"], "parent norm packet observation changed after serialization")
            direct = json.dumps(state["observation"], sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False).encode("utf-8")
            _need(direct == state["wire"], "parent norm packet observation changed after final encoder returned")
        if state["result"] is not None:
            result = state["result"]
            _need(type(result) is RetainedDefinitionUsePreservationPacket, "exact retained packet result type required")
            data = object.__getattribute__(result, "__dict__")
            _keys(data, {"observation_json", "files"}, "parent norm packet result storage")
            _need(type(data["observation_json"]) is str and data["observation_json"].encode() == state["wire"]
                  and type(data["files"]) is tuple and data["files"] == packet_files,
                  "actual parent norm packet result differs from final serialized observation/bytes")

    def replay():
        fence()
        checked = _parent_norm_packet_current_preparation(
            owners, preparation, copied["correspondence"], arguments)
        _need(type(checked) is preparer.DefinitionUseCorpusPreparation
              and _parent_norm_packet_storage(checked) == storage
              and preparer.parent_norm_preparation_sha256(checked) == expected_preparation_sha256,
              "genuine parent norm preparation replay differs from complete original pin")
        preparations.append(checked)
        fence()
        return checked

    try:
        prepared = replay()
        manifest, historical = _parent_norm_packet_receipt_matches(
            receipt, files, prepared, receipt_arguments, expected_preparation_sha256, owners)
        _need(_wire(manifest) == _wire(document["manifest"]),
              "opening receipt matcher changed the genuine parent norm manifest")
        hold(manifest, "opening genuine manifest"); hold(historical, "opening producer pins")
        state["pins"] = historical
        state["plan"] = hold(preparer._parent_norm_file_plan(copied["correspondence_inputs"]),
                             "genuine original physical witness plan")
        state["witness"] = hold(preparer._parent_norm_file_witness(state["plan"]),
                                "original physical source identities")
        fence()
        again = replay()
        closing_manifest, closing_pins = _parent_norm_packet_receipt_matches(
            receipt, files, again, receipt_arguments, expected_preparation_sha256, owners)
        hold(closing_manifest, "closing genuine manifest"); hold(closing_pins, "closing producer pins")
        _need(closing_manifest == manifest and closing_pins == historical,
              "closing parent norm packet replay or producer closure differs")
        current = dict(historical); current[str(Path(__file__).resolve())] = _SELF_PIN
        observation_input = {
            "schema": PARENT_NORM_PACKET_SCHEMA, "profile": PARENT_NORM_PACKET_PROFILE,
            "packet_bundle_sha256": expected_bundle_sha256, "receipt_file_sha256": expected_receipt_file_sha256,
            "preparation_full_canonical_sha256": expected_preparation_sha256,
            "correspondence_sha256": expected_correspondence_sha256, "toolchain": toolchain,
            "expected_binary_sha256": binaries, "current_producer_pins": current,
            "historical_producer_pins": historical, "historical_native_receipt": receipt,
            "packet_inventory": inventory, "readback_verified": True, "current_preparation_replayed": True,
            "receipt_consistency_only": True, "accepted_execution": False, "accepted_outer_operation": False,
            "accepted_operation_result_bound": False, "outer_operation_outcome": "unprovided",
            "historical_kernel_observations_retained": True,
            "preservation_kind": "definitional_alias_identity_only", "proof_scope": _PARENT_NORM_PACKET_SCOPE,
            "source_custody": {"original_parent_correspondence_and_physical_inputs_replayed": True,
                "current_producer_compatibility_required": True, "producer_relocation_performed": False,
                "historical_lifecycle_internal_consistency_checked": True,
                "historical_process_liveness_inspected": False, "filesystem_acquisition_performed": False,
                "source_review_eligibility_unchanged": True, "original_receipt_unchanged": True},
            "trust_boundary": [
                "Externally trusted exact raw receipt and bundle pins are provenance premises, not cryptographic authentication.",
                "A successful persisted receipt may precede later outer closing-custody refusal. No accepted outer result or closeout is supplied or inferred; execution remains unaccepted.",
                "The external acquirer owns filesystem races, symlink/hardlink refusal and immutable original byte acquisition.",
                "Historical lifecycle, compiler, artifact and alias-identity observations are internally checked retained claims; no live PID/binary inspection, Lean execution or olean kernel recheck occurs.",
                "Historical producer paths and generations must equal current replayed owners exactly. Frozen23 relocation and49/51 source compatibility require a separately reviewed contract; neither is inferred here.",
                "No source/edition/meaning, governing definition, model accuracy, training/gold, graph/corpus admission or proof-cache authority is granted.",
            ],
            "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
            **dict.fromkeys(set(FALSE_FLAGS) | set(preparer.PARENT_NORM_FALSE_FLAGS) | set(native.FALSE_FLAGS), False),
        }
        hold(observation_input, "complete original observation input")
        observation = contracts.seal_record(observation_input)
        _keys(observation, set(observation_input) | {"record_cid", "cid_scope"}, "sealed parent norm packet observation")
        _need(_wire({name: observation[name] for name in observation_input}) == _wire(observation_input),
              "sealed parent norm packet return differs from complete original observation")
        hold(observation, "sealed parent norm packet observation")
        contracts.validate_record(observation, schema=PARENT_NORM_PACKET_SCHEMA,
                                 fields=set(observation) - {"schema", "record_cid", "cid_scope"})
        wire = _wire(observation)
        state["observation"], state["wire"] = observation, wire
        fence()
        result = RetainedDefinitionUsePreservationPacket(wire.decode("utf-8"), packet_files)
        state["result"] = result
        fence()
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        # Preserve the original failure while recording every secondary custody
        # failure. Recheck serialization even if an input/source fence refuses.
        finish((fence, serialized_fence, fence, serialized_fence, fence), primary)


__all__ += ["validate_parent_norm_native_packet_v1", "parent_norm_packet_sha256"]


# Explicit parent-bound norm/definition retained packets reuse the existing
# inventory, raw storage, runtime/log/lifecycle and receipt consistency checks.
PARENT_BOUND_NORM_PACKET_SCHEMA = "legal-corpus-parent-bound-norm-definition-native-packet-observation/v1"
PARENT_BOUND_NORM_PACKET_PROFILE = "replayed-retained-parent-bound-norm-definition-conditional-native-byte-packet/v1"
_PARENT_BOUND_NORM_PACKET_BUILD_SCHEMA = "legal-corpus-parent-bound-norm-definition-native-build/v1"
_PARENT_BOUND_NORM_PACKET_NATIVE_PROFILE = "replayed-parent-bound-norm-definition-conditional-native-build/v1"
_PARENT_BOUND_NORM_PACKET_PREPARATION_SCHEMA = "legal-corpus-parent-bound-norm-definition-lake-preparation/v1"
_PARENT_BOUND_NORM_PACKET_PREPARATION_PROFILE = "replayed-parent-bound-norm-definition-conditional-project/v1"
_PARENT_BOUND_NORM_PACKET_REPORT_SCHEMA = "legal-parent-bound-variable-definition-report/v1"
_PARENT_BOUND_NORM_PACKET_REPORT_PROFILE = "conditional-parent-unary-definition-at-bound-variable/v1"
_PARENT_BOUND_NORM_PACKET_REQUEST_SCHEMA = "legal-parent-bound-variable-definition-request/v1"
_PARENT_BOUND_NORM_PACKET_REPLAY_FIELDS = frozenset({
    "companion", "request_raw", "expected_companion_sha256", "expected_request_sha256", "companion_inputs"})
_PARENT_BOUND_NORM_PACKET_COMPANION_FIELDS = frozenset({"norm_preparation", "request_raw",
    "expected_norm_preparation_sha256", "expected_request_sha256", "norm_inputs", "definitions"})
_PARENT_BOUND_NORM_PACKET_ARGUMENTS = frozenset({"expected_preparation_sha256", "expected_bound_report_sha256",
    "bound_definition_inputs", "toolchain", "expected_receipt_file_sha256", "expected_bundle_sha256",
    "expected_binary_sha256"})
_PARENT_BOUND_NORM_PACKET_RETAINED_FIELDS = ("original_norm", "occurrence_binding", "selected_link",
    "definition_alternative_refs", "nomination_inventory", "review_intake_binding", "conditional_source_binding",
    "original_parent_context_bindings", "parent_bound_definition_report_ref", "conditional_theorem_statements")
_PARENT_BOUND_NORM_PACKET_SCOPE = ("Only exact conditional definition instances under explicit hDefinition "
    "and any matching hMembership premises, plus definitional alias preservation of the "
    "complete unchanged norm. No norm truth, governing applicability, membership proof, "
    "source meaning, corpus/graph admission, model equivalence or convergence claim.")
_PARENT_BOUND_NORM_PACKET_RECEIPT_FIELDS = (_OBSERVATION_FIELDS - {
    "theorems", "preservation_theorems", "concrete_kernel_status"}) | frozenset({
    "schema", "profile", "record_cid", "cid_scope", "preparation_cid", "preparation_full_canonical_sha256",
    "preparation_manifest_sha256", "toolchain", "bound_definition_report_sha256", "original_input_commitment_sha256",
    "bound_definition_mode", "retained_manifest_field_sha256", "parent_bound_definition_report_ref",
    "definition_alternative_refs_count", "nomination_inventory_count", "review_evidence_status", "review_blockers",
    "review_prerequisites_satisfied_under_selected_trust", "original_preparation_build_eligible",
    "original_preparation_execution_handoff", "preservation_kind", "selected_interpretation", "governing_definition_use",
    "norm_interpretation_ready", "semantic_mask", "consumer_mask", "theorem_assumptions",
    "original_preparation_theorem_assumptions", "build_passed", "status", "alias_assumption_proved",
    "source_to_model_equivalence_proved", "authority", "training_mask", "evaluation_gold_mask", "scope"})


def _parent_norm_packet_kwdefaults():
    """Snapshot actual shared policy defaults, including None and bool/int."""
    result = {}
    for function in (_bound_tree, _parent_norm_packet_document, _parent_norm_packet_storage, _parent_norm_packet_receipt_matches):
        values = getattr(function, "__kwdefaults__", None)
        if values is None:
            result[function.__name__] = None
            continue
        _need(type(values) is dict and all(type(key) is str for key in values), "ordinary shared helper defaults required")
        fields = {}
        for key, value in values.items():
            if type(value) is tuple:
                _need(all(child is None or type(child) in (str, bool, int, float) for child in value),
                      "ordinary immutable policy tuple required")
                fields[key] = {"type": "tuple", "items": [
                    {"type": type(child).__name__, "value": child} for child in value]}
            else:
                _need(value is None or type(value) in (str, bool, int, float), "ordinary shared helper policy required")
                fields[key] = {"type": type(value).__name__, "value": value}
        result[function.__name__] = fields
    return result


def _parent_bound_norm_packet_document(packet_files):
    return _parent_norm_packet_document(packet_files, maximum_files=29, expected_groups=(10, 9, 6))


def parent_bound_norm_definition_packet_sha256(packet_files):
    """Commit the exact29-file immutable inventory, without execution authority."""
    _, inventory = _parent_bound_norm_packet_document(packet_files)
    return _sha(_wire(inventory))


def _parent_bound_norm_packet_storage(preparation):
    return _parent_norm_packet_storage(preparation, maximum_files=9,
        preparation_schema=_PARENT_BOUND_NORM_PACKET_PREPARATION_SCHEMA,
        preparation_profile=_PARENT_BOUND_NORM_PACKET_PREPARATION_PROFILE)


def _parent_bound_norm_packet_capture(packet_files, preparation, bound_report, packet_arguments):
    """Pin complete ordinary originals before operation-owner imports."""
    _keys(packet_arguments, _PARENT_BOUND_NORM_PACKET_ARGUMENTS, "parent bound packet arguments")
    for name in ("expected_preparation_sha256", "expected_bound_report_sha256",
                 "expected_receipt_file_sha256", "expected_bundle_sha256"):
        _pin(packet_arguments[name], name)
    toolchain = packet_arguments["toolchain"]
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain),
          "exact parent bound packet toolchain required")
    _binary_map(packet_arguments["expected_binary_sha256"])
    binaries = dict(packet_arguments["expected_binary_sha256"])
    storage = _parent_bound_norm_packet_storage(preparation)
    document = {"manifest": _parse(storage["manifest_json"].encode()), "files": storage["files"]}
    _need(_sha(_wire(document, 20 * MAX_RECORD_BYTES)) == packet_arguments["expected_preparation_sha256"],
          "independent complete parent bound preparation pin differs")
    _need(type(bound_report) is dict, "complete original parent bound report required")
    inputs = packet_arguments["bound_definition_inputs"]
    _keys(inputs, _PARENT_BOUND_NORM_PACKET_REPLAY_FIELDS, "complete five-field parent bound replay")
    _keys(inputs["companion_inputs"], _PARENT_BOUND_NORM_PACKET_COMPANION_FIELDS, "complete parent nomination originals")
    original = {"preparation": storage, "bound_report": bound_report, "packet_arguments": packet_arguments}
    _bound_tree(original, MAX_INPUT_BYTES, allow_bytes=True, maximum_depth=48, maximum_nodes=1_000_000)
    copied = _parent_norm_packet_copy(original)
    _need(_review_snapshot(copied) == _review_snapshot(original), "complete detached parent bound packet inputs differ")
    _need(_sha(_wire(bound_report, MAX_PROJECT_BYTES)) == packet_arguments["expected_bound_report_sha256"],
          "independent complete original parent bound report pin differs")
    _pin(inputs["expected_companion_sha256"], "complete parent nomination")
    _pin(inputs["expected_request_sha256"], "exact original parent bound request")
    _need(type(inputs["companion"]) is dict
          and _sha(_wire(inputs["companion"], MAX_PROJECT_BYTES)) == inputs["expected_companion_sha256"],
          "independent complete original parent nomination pin differs")
    raw = inputs["request_raw"]
    _need(type(raw) is bytes and 0 < len(raw) <= 128 * 1024 and _sha(raw) == inputs["expected_request_sha256"],
          "independent exact original parent bound request pin differs")
    request = _parse(raw, 128 * 1024)
    _need(type(request) is dict, "ordinary original parent bound request object required")
    mode = request.get("mode")
    manifest = document["manifest"]
    _need(type(mode) is str and mode in ("instance_only", "body_with_membership")
          and manifest.get("bound_definition_mode") == mode and manifest.get("toolchain") == toolchain
          and type(manifest.get("conditional_theorems")) is list
          and len(manifest["conditional_theorems"]) == (2 if mode == "instance_only" else 3),
          "exact original parent bound mode, toolchain and theorem population required")
    _need(bound_report.get("schema") == _PARENT_BOUND_NORM_PACKET_REPORT_SCHEMA
          and bound_report.get("profile") == _PARENT_BOUND_NORM_PACKET_REPORT_PROFILE
          and request.get("schema") == _PARENT_BOUND_NORM_PACKET_REQUEST_SCHEMA
          and request.get("profile") == _PARENT_BOUND_NORM_PACKET_REPORT_PROFILE
          and request.get("companion_sha256") == inputs["expected_companion_sha256"]
          and bound_report.get("companion_sha256") == inputs["expected_companion_sha256"]
          and bound_report.get("request_sha256") == inputs["expected_request_sha256"]
          and _wire(bound_report.get("request"), 128 * 1024) == _wire(request, 128 * 1024),
          "complete parent report/request/companion domains differ")
    _need(all(type(bound_report.get(key)) is int and bound_report[key] == 0 for key in
              ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"))
          and bound_report.get("selected_interpretation") is None and bound_report.get("governing_definition_use") is None,
          "exact zero masks and unresolved parent bound decisions required")
    files, inventory = _parent_bound_norm_packet_document(packet_files)
    _need(_sha(_wire(inventory)) == packet_arguments["expected_bundle_sha256"], "independent complete29-file bundle pin differs")
    _need(_sha(files["build-receipt.json"]) == packet_arguments["expected_receipt_file_sha256"],
          "independent exact raw parent bound receipt pin differs")
    receipt = _parse(files["build-receipt.json"])
    _need(type(receipt) is dict and receipt.get("schema") == _PARENT_BOUND_NORM_PACKET_BUILD_SCHEMA
          and receipt.get("profile") == _PARENT_BOUND_NORM_PACKET_NATIVE_PROFILE
          and type(receipt.get("binary_sha256")) is dict and receipt["binary_sha256"] == binaries,
          "explicit parent bound receipt profile and independent binary commitments required")
    _need(all(type(receipt.get(key)) is int and receipt[key] == 0 for key in
              ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"))
          and receipt.get("selected_interpretation") is None and receipt.get("governing_definition_use") is None
          and receipt.get("norm_interpretation_ready") is False,
          "exact retained parent bound masks and unresolved decisions required")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "parent bound packet reader source changed")
    return {"original": original, "copied": copied, "storage": storage, "document": document,
        "binaries": binaries, "files": files, "inventory": inventory, "receipt": receipt}


def _parent_bound_norm_packet_owners():
    native, contracts = _parent_norm_packet_owners()
    preparer = native._parent_bound_norm_native_preparer()
    native_owners = native._owners()
    bound_owners = preparer.bound._owners()
    evidence_owners = preparer.bound.evidence._parent_definition_owners()
    return native, contracts, preparer, native_owners, bound_owners, evidence_owners


def _parent_bound_norm_packet_pins(owners, manifest):
    return owners[0]._parent_bound_norm_native_pins(owners[3], manifest)


def _parent_bound_norm_packet_file_plans(owners, bound_definition_inputs):
    preparer, evidence_owners = owners[2], owners[5]
    inputs = bound_definition_inputs["companion_inputs"]
    replays = [inputs["norm_inputs"]["correspondence_inputs"]["scope_replay_inputs"]["replay_inputs"]]
    replays.extend(endpoint["preparation_inputs"]["parent_inputs"]["replay_inputs"] for endpoint in inputs["definitions"])
    return [preparer.bound.evidence._parent_definition_file_plan(value, evidence_owners[1]) for value in replays]


def _parent_bound_norm_packet_file_witness(owners, plan):
    return owners[2].bound.evidence._parent_definition_file_witness(plan, owners[5][1])


def _parent_bound_norm_packet_current_preparation(owners, preparation, bound_report, arguments):
    return owners[0].validate_parent_bound_norm_definition_native_v1(preparation, bound_report, **arguments)


def _parent_bound_norm_packet_bindings(manifest, storage, arguments, expected_preparation_sha256):
    return {"preparation_cid": manifest["record_cid"],
        "preparation_full_canonical_sha256": expected_preparation_sha256,
        "preparation_manifest_sha256": _sha(storage["manifest_json"].encode()),
        "bound_definition_report_sha256": arguments["expected_bound_report_sha256"],
        "original_input_commitment_sha256": manifest["original_input_commitment_sha256"],
        "bound_definition_mode": manifest["bound_definition_mode"],
        "retained_manifest_field_sha256": {key: _sha(_wire(manifest[key])) for key in _PARENT_BOUND_NORM_PACKET_RETAINED_FIELDS},
        "parent_bound_definition_report_ref": manifest["parent_bound_definition_report_ref"],
        "definition_alternative_refs_count": len(manifest["definition_alternative_refs"]),
        "nomination_inventory_count": len(manifest["nomination_inventory"]),
        "review_evidence_status": manifest["review_evidence_status"], "review_blockers": manifest["review_blockers"],
        "review_prerequisites_satisfied_under_selected_trust": manifest["review_prerequisites_satisfied_under_selected_trust"],
        "original_preparation_build_eligible": manifest["build_eligible"],
        "original_preparation_execution_handoff": manifest["execution_handoff"],
        "original_preparation_theorem_assumptions": manifest["theorem_assumptions"],
        "theorem_assumptions": manifest["theorem_assumptions"], "toolchain": arguments["toolchain"],
        "preservation_kind": "definitional_alias_identity_only", "selected_interpretation": None,
        "governing_definition_use": None, "norm_interpretation_ready": False, "semantic_mask": 0, "consumer_mask": 0}


def _parent_bound_norm_packet_receipt_matches(receipt, files, prepared, arguments, expected_preparation_sha256, owners):
    _need(type(owners) is tuple and len(owners) == 6, "captured parent bound packet owners required")
    manifest, pins = _parent_norm_packet_receipt_matches(receipt, files, prepared, arguments,
        expected_preparation_sha256, owners[:2], parent_bound_context=owners)
    _need(manifest["selected_interpretation"] is None and manifest["governing_definition_use"] is None
          and manifest["norm_interpretation_ready"] is False and manifest["build_eligible"] is False
          and manifest["bound_definition_mode"] in ("instance_only", "body_with_membership"),
          "unresolved parent bound interpretation and exact explicit mode required")
    return manifest, pins


def _parent_bound_norm_packet_callbacks(owners):
    native, contracts, preparer, native_owners, bound_owners, evidence_owners = owners
    functions = (_need, _sha, _pin, _keys, _integer, _bound_tree, _wire, _parse, _review_snapshot,
        _binary_map, _historical_lifecycle, _identity, _parent_norm_packet_document, _parent_norm_packet_storage,
        _parent_norm_packet_copy, _parent_norm_packet_runtime_observations, _parent_norm_packet_receipt_matches,
        _parent_norm_packet_kwdefaults, _parent_bound_norm_packet_document, parent_bound_norm_definition_packet_sha256,
        _parent_bound_norm_packet_storage, _parent_bound_norm_packet_capture, _parent_bound_norm_packet_owners,
        _parent_bound_norm_packet_pins, _parent_bound_norm_packet_file_plans, _parent_bound_norm_packet_file_witness,
        _parent_bound_norm_packet_current_preparation, _parent_bound_norm_packet_bindings,
        _parent_bound_norm_packet_receipt_matches, _parent_bound_norm_packet_callbacks, _parent_bound_norm_packet_runtime,
        validate_parent_bound_norm_definition_native_packet_v1, RetainedDefinitionUsePreservationPacket,
        RetainedDefinitionUsePreservationPacket.__init__, RetainedDefinitionUsePreservationPacket.to_dict,
        contracts.validate_record, contracts.seal_record, json.dumps, json.loads, evidence_owners[2]._parent_finish)
    observed = tuple((function, getattr(function, "__code__", None),
        id(getattr(function, "__defaults__", None)), id(getattr(function, "__kwdefaults__", None))) for function in functions)
    return observed + native._parent_bound_norm_native_callbacks(native_owners, preparer, bound_owners, evidence_owners)


def _parent_bound_norm_packet_runtime(owners):
    native, _, preparer, native_owners, bound_owners, evidence_owners = owners
    return {"schema": PARENT_BOUND_NORM_PACKET_SCHEMA, "profile": PARENT_BOUND_NORM_PACKET_PROFILE,
        "build_schema": _PARENT_BOUND_NORM_PACKET_BUILD_SCHEMA, "native_profile": _PARENT_BOUND_NORM_PACKET_NATIVE_PROFILE,
        "preparation_schema": _PARENT_BOUND_NORM_PACKET_PREPARATION_SCHEMA,
        "preparation_profile": _PARENT_BOUND_NORM_PACKET_PREPARATION_PROFILE,
        "report_schema": _PARENT_BOUND_NORM_PACKET_REPORT_SCHEMA, "report_profile": _PARENT_BOUND_NORM_PACKET_REPORT_PROFILE,
        "request_schema": _PARENT_BOUND_NORM_PACKET_REQUEST_SCHEMA, "replay_fields": sorted(_PARENT_BOUND_NORM_PACKET_REPLAY_FIELDS),
        "companion_fields": sorted(_PARENT_BOUND_NORM_PACKET_COMPANION_FIELDS),
        "argument_fields": sorted(_PARENT_BOUND_NORM_PACKET_ARGUMENTS),
        "receipt_fields": sorted(_PARENT_BOUND_NORM_PACKET_RECEIPT_FIELDS),
        "retained_fields": list(_PARENT_BOUND_NORM_PACKET_RETAINED_FIELDS), "scope": _PARENT_BOUND_NORM_PACKET_SCOPE,
        "success_flags": sorted(_PARENT_NORM_PACKET_SUCCESS_FLAGS), "authority": dict(AUTHORITY), "false_flags": dict(FALSE_FLAGS),
        "root_files": sorted(_ROOT_FILES), "log_files": sorted(_LOG_FILES), "record_bytes": MAX_RECORD_BYTES,
        "packet_bytes": MAX_PACKET_BYTES, "input_bytes": MAX_INPUT_BYTES, "project_bytes": MAX_PROJECT_BYTES,
        "log_bytes": MAX_LOG_BYTES, "preview_bytes": MAX_LOG_PREVIEW_BYTES, "selected_files": 29,
        "source_files": 9, "modules": 6, "maximum_theorems": 3, "input_depth": 48, "input_nodes": 1_000_000,
        "terminal_raw_depth": 96, "terminal_raw_nodes": 2_000_000,
        "shared_helper_kwdefaults": _parent_norm_packet_kwdefaults(),
        "toolchain_pattern": _TOOLCHAIN.pattern, "corpus_module": _CORPUS_MODULE,
        "reader_path": str(Path(__file__).resolve()),
        "native_runtime": native._parent_bound_norm_native_runtime(native_owners, preparer, bound_owners, evidence_owners)}


def validate_parent_bound_norm_definition_native_packet_v1(packet_files, preparation, bound_report, *,
        expected_preparation_sha256, expected_bound_report_sha256, bound_definition_inputs, toolchain,
        expected_receipt_file_sha256, expected_bundle_sha256, expected_binary_sha256):
    """Replay exact29-file evidence as consistency, never accepted execution.

    Independently trusted raw pins are provenance premises. Historical producer
    paths and hashes must equal current original owners; no relocation fallback
    authenticates old frozen evidence or supplies an accepted outer closeout.
    """
    def raw_snapshot(value):
        # This local reader touches only exact ordinary storage and immutable
        # primitives. It calls no delegated serializer, witness or pin helper.
        remaining = 2_000_000
        def visit(item, depth):
            nonlocal remaining
            remaining -= 1
            if remaining < 0 or depth > 96:
                raise ValueError("bounded final raw packet custody required")
            cls = type(item)
            if item is None:
                return ("null",)
            if cls is float:
                return ("float", item.hex())
            if cls in (str, bytes, bool, int):
                return (cls.__name__, item)
            if cls in (list, tuple):
                return (cls.__name__, tuple(visit(child, depth + 1) for child in item))
            if cls is dict:
                if not all(type(key) is str for key in item):
                    raise ValueError("ordinary final raw packet keys required")
                return ("dict", tuple((key, visit(item[key], depth + 1)) for key in sorted(item)))
            raise ValueError("ordinary final raw packet storage required")
        return visit(value, 0)

    packet_arguments = dict(expected_preparation_sha256=expected_preparation_sha256,
        expected_bound_report_sha256=expected_bound_report_sha256, bound_definition_inputs=bound_definition_inputs,
        toolchain=toolchain, expected_receipt_file_sha256=expected_receipt_file_sha256,
        expected_bundle_sha256=expected_bundle_sha256, expected_binary_sha256=expected_binary_sha256)
    capture = _parent_bound_norm_packet_capture(packet_files, preparation, bound_report, packet_arguments)
    original, copied = capture["original"], capture["copied"]
    storage, document = capture["storage"], capture["document"]
    binaries, files, inventory, receipt = (capture[name] for name in ("binaries", "files", "inventory", "receipt"))
    snapshot = _review_snapshot(original)
    raw_preparation_type = type(preparation)
    raw_result_type = RetainedDefinitionUsePreservationPacket
    raw_preparation = raw_snapshot(object.__getattribute__(preparation, "__dict__"))
    raw_original = raw_snapshot({"preparation": object.__getattribute__(preparation, "__dict__"),
        "bound_report": bound_report, "packet_arguments": packet_arguments})
    raw_copied, raw_packet = raw_snapshot(copied), raw_snapshot(packet_files)
    owners = _parent_bound_norm_packet_owners()
    native, contracts, preparer, native_owners, bound_owners, evidence_owners = owners
    finish = evidence_owners[2]._parent_finish
    _need(type(preparation) is preparer.DefinitionUseCorpusPreparation, "exact current parent bound preparation type required")
    arguments = {"expected_preparation_sha256": expected_preparation_sha256,
        "expected_bound_report_sha256": expected_bound_report_sha256,
        "bound_definition_inputs": copied["packet_arguments"]["bound_definition_inputs"], "toolchain": toolchain}
    native_original = {"bound_report": copied["bound_report"], "expected_bound_report_sha256": expected_bound_report_sha256,
        "bound_definition_inputs": arguments["bound_definition_inputs"], "toolchain": toolchain}
    preflight = native._parent_bound_norm_native_preflight(preparation, native_original,
        expected_preparation_sha256=expected_preparation_sha256)
    receipt_arguments = {**arguments, "expected_binary_sha256": binaries}
    callbacks = _parent_bound_norm_packet_callbacks(owners)
    runtime = _review_snapshot(_parent_bound_norm_packet_runtime(owners))
    held, preparations, physical = [], [], []
    state = {"pins": None, "observation": None, "wire": None, "result": None}
    primary = None

    def hold(value, label):
        _bound_tree(value, MAX_PACKET_BYTES, allow_bytes=True)
        held.append((value, _review_snapshot(value), raw_snapshot(value), label))
        return value

    for name in ("document", "binaries", "files", "inventory", "receipt"):
        hold(capture[name], "actual pure capture " + name)
    hold(preflight, "actual native pure preflight")
    hold(arguments, "complete detached replay arguments"); hold(receipt_arguments, "complete detached receipt arguments")

    def serialized_fence():
        if state["observation"] is not None:
            _need(_wire(state["observation"]) == state["wire"], "parent bound packet observation changed after serialization")
            direct = json.dumps(state["observation"], sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
            _need(direct == state["wire"], "parent bound packet observation changed after encoder return")
        if state["result"] is not None:
            result = state["result"]
            _need(type(result) is RetainedDefinitionUsePreservationPacket, "exact immutable retained packet result required")
            data = object.__getattribute__(result, "__dict__")
            _keys(data, {"observation_json", "files"}, "parent bound packet actual result storage")
            _need(type(data["observation_json"]) is str and data["observation_json"].encode() == state["wire"]
                  and type(data["files"]) is tuple and data["files"] == packet_files,
                  "actual parent bound result differs from serialized observation and original bytes")

    def fence(*, serialization=True):
        _need(_parent_bound_norm_packet_callbacks(owners) == callbacks
              and _review_snapshot(_parent_bound_norm_packet_runtime(owners)) == runtime,
              "parent bound packet callback or type-sensitive runtime policy changed")
        _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "parent bound packet reader source changed")
        now = {"preparation": _parent_bound_norm_packet_storage(preparation), "bound_report": bound_report,
               "packet_arguments": packet_arguments}
        _bound_tree(now, MAX_INPUT_BYTES, allow_bytes=True, maximum_depth=48, maximum_nodes=1_000_000)
        _need(_review_snapshot(now) == snapshot and _review_snapshot(copied) == snapshot,
              "complete caller or detached parent bound originals changed")
        _need(parent_bound_norm_definition_packet_sha256(packet_files) == expected_bundle_sha256
              and _review_snapshot(expected_binary_sha256) == _review_snapshot(binaries),
              "original parent bound packet bytes or external binary pins changed")
        for value, expected, raw_expected, label in held:
            _bound_tree(value, MAX_PACKET_BYTES, allow_bytes=True)
            _need(_review_snapshot(value) == expected, "held actual parent bound packet return changed: " + label)
        for value in preparations:
            _need(_parent_bound_norm_packet_storage(value) == storage, "actual parent bound replay preparation raw storage changed")
        if state["pins"] is not None:
            _need(_parent_bound_norm_packet_pins(owners, document["manifest"]) == state["pins"],
                  "current parent bound producer paths/hashes changed")
        for plan, witness, expected in physical:
            _need(_review_snapshot(plan) == expected and _parent_bound_norm_packet_file_witness(owners, plan) == witness,
                  "original norm or definition physical replay files changed")
        if serialization:
            serialized_fence()

    def replay():
        fence()
        checked = _parent_bound_norm_packet_current_preparation(owners, preparation, copied["bound_report"], arguments)
        _need(type(checked) is preparer.DefinitionUseCorpusPreparation
              and _parent_bound_norm_packet_storage(checked) == storage
              and preparer.parent_bound_norm_definition_preparation_sha256(checked) == expected_preparation_sha256,
              "genuine complete parent bound packet preparation replay differs")
        if raw_snapshot(object.__getattribute__(checked, "__dict__")) != raw_preparation:
            raise ValueError("actual replay raw preparation differs from the original typed storage")
        preparations.append(checked)
        fence()
        return checked

    def raw_tail():
        # Run after the last delegated callback, including the final pin/witness
        # callback, and again after direct encoding. Comparisons retain types.
        if type(preparation) is not raw_preparation_type:
            raise ValueError("final original preparation class identity changed")
        now = {"preparation": object.__getattribute__(preparation, "__dict__"),
            "bound_report": bound_report, "packet_arguments": packet_arguments}
        if raw_snapshot(now) != raw_original or raw_snapshot(copied) != raw_copied:
            raise ValueError("final raw caller or detached parent bound inputs changed")
        if raw_snapshot(packet_files) != raw_packet:
            raise ValueError("final raw parent bound packet bytes changed")
        for value, expected, raw_expected, label in held:
            if raw_snapshot(value) != raw_expected:
                raise ValueError("final raw held packet value changed: " + label)
        for value in preparations:
            if type(value) is not raw_preparation_type or raw_snapshot(object.__getattribute__(value, "__dict__")) != raw_preparation:
                raise ValueError("final actual replay preparation raw storage changed")
        if state["result"] is not None:
            result = state["result"]
            if type(result) is not raw_result_type:
                raise ValueError("final actual parent bound packet type changed")
            expected = {"observation_json": state["wire"].decode(), "files": packet_files}
            if raw_snapshot(object.__getattribute__(result, "__dict__")) != raw_snapshot(expected):
                raise ValueError("final actual parent bound packet raw storage changed")

    def terminal():
        fence()
        serialized_fence()
        # The final ordinary/held/physical guard follows the last overridable
        # observation encoder, and performs no further observation serialization.
        fence(serialization=False)
        raw_tail()
        if state["observation"] is not None:
            direct = json.dumps(state["observation"], sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
            _need(direct == state["wire"], "parent bound packet changed after final direct encoding")
        if state["result"] is not None:
            data = object.__getattribute__(state["result"], "__dict__")
            _need(set(data) == {"observation_json", "files"} and type(data["observation_json"]) is str
                  and data["observation_json"].encode() == state["wire"] and type(data["files"]) is tuple
                  and data["files"] == packet_files, "parent bound packet final raw result storage changed")
        raw_tail()

    try:
        checked = replay()
        manifest, historical = _parent_bound_norm_packet_receipt_matches(receipt, files, checked,
            receipt_arguments, expected_preparation_sha256, owners)
        _need(_wire(manifest) == _wire(document["manifest"]), "opening matcher changed the genuine parent bound manifest")
        hold(manifest, "actual opening manifest"); hold(historical, "actual opening native producer pins")
        state["pins"] = historical
        plans = hold(_parent_bound_norm_packet_file_plans(owners, arguments["bound_definition_inputs"]),
                     "all original norm and definition physical plans")
        for plan in plans:
            witness = hold(_parent_bound_norm_packet_file_witness(owners, plan), "actual original physical witness")
            physical.append((plan, witness, _review_snapshot(plan)))
        fence()
        again = replay()
        closing_manifest, closing_pins = _parent_bound_norm_packet_receipt_matches(receipt, files, again,
            receipt_arguments, expected_preparation_sha256, owners)
        hold(closing_manifest, "actual closing manifest"); hold(closing_pins, "actual closing native producer pins")
        _need(closing_manifest == manifest and closing_pins == historical, "closing parent bound packet replay or producer closure differs")
        current = dict(historical); path = str(Path(__file__).resolve())
        _need(path not in current or current[path] == _SELF_PIN, "conflicting current packet producer pin")
        current[path] = _SELF_PIN
        observation_input = {"schema": PARENT_BOUND_NORM_PACKET_SCHEMA, "profile": PARENT_BOUND_NORM_PACKET_PROFILE,
            "packet_bundle_sha256": expected_bundle_sha256, "receipt_file_sha256": expected_receipt_file_sha256,
            "preparation_full_canonical_sha256": expected_preparation_sha256,
            "bound_definition_report_sha256": expected_bound_report_sha256, "bound_definition_mode": manifest["bound_definition_mode"],
            "retained_manifest_field_sha256": receipt["retained_manifest_field_sha256"],
            "parent_bound_definition_report_ref": manifest["parent_bound_definition_report_ref"],
            "toolchain": toolchain, "expected_binary_sha256": binaries, "current_producer_pins": current,
            "historical_producer_pins": historical, "historical_native_receipt": receipt, "packet_inventory": inventory,
            "readback_verified": True, "current_preparation_replayed": True, "receipt_consistency_only": True,
            "accepted_execution": False, "accepted_outer_operation": False, "accepted_operation_result_bound": False,
            "outer_operation_outcome": "unprovided", "historical_kernel_observations_retained": True,
            "preservation_kind": "definitional_alias_identity_only", "proof_scope": _PARENT_BOUND_NORM_PACKET_SCOPE,
            "selected_interpretation": None, "governing_definition_use": None, "norm_interpretation_ready": False,
            "semantic_mask": 0, "consumer_mask": 0,
            "source_custody": {"original_parent_bound_report_and_all_physical_inputs_replayed": True,
                "current_producer_compatibility_required": True, "producer_relocation_performed": False,
                "historical_lifecycle_internal_consistency_checked": True, "historical_process_liveness_inspected": False,
                "filesystem_acquisition_performed": False, "source_review_eligibility_unchanged": True, "original_receipt_unchanged": True},
            "trust_boundary": [
                "Externally trusted exact raw receipt and bundle pins are provenance premises, not cryptographic authentication.",
                "A persisted successful receipt may precede a later outer refusal. No accepted outer result or closeout is supplied or inferred.",
                "The external acquirer owns filesystem races, link refusal and immutable original byte acquisition.",
                "Historical compiler, artifact and lifecycle claims are retained consistency observations; no live PID/binary inspection, Lean execution or olean kernel recheck occurs.",
                "Historical producer paths and generations must equal current original replayed owners; no frozen relocation fallback is provided.",
                "hDefinition, any hMembership, shared carrier/time and original norm alias assumptions remain unverified; no source/meaning, model, graph/corpus, training/gold or proof-cache authority is granted."],
            "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
            **dict.fromkeys(set(FALSE_FLAGS) | set(manifest["authority"]) | set(native.FALSE_FLAGS), False)}
        hold(observation_input, "complete parent bound observation input")
        observation = contracts.seal_record(observation_input)
        _keys(observation, set(observation_input) | {"record_cid", "cid_scope"}, "sealed parent bound packet observation")
        _need(_wire({key: observation[key] for key in observation_input}) == _wire(observation_input),
              "sealed parent bound packet return substituted original observation")
        hold(observation, "actual sealed parent bound packet observation")
        contracts.validate_record(observation, schema=PARENT_BOUND_NORM_PACKET_SCHEMA,
            fields=set(observation) - {"schema", "record_cid", "cid_scope"})
        state["observation"], state["wire"] = observation, _wire(observation)
        fence()
        result = RetainedDefinitionUsePreservationPacket(state["wire"].decode(), packet_files)
        state["result"] = result
        fence()
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        finish((fence, serialized_fence, fence, serialized_fence, terminal), primary)


__all__ += ["PARENT_BOUND_NORM_PACKET_SCHEMA", "PARENT_BOUND_NORM_PACKET_PROFILE",
    "parent_bound_norm_definition_packet_sha256", "validate_parent_bound_norm_definition_native_packet_v1"]
