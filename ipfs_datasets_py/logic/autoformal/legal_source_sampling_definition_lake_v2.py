"""Compile an exact, independently replayed V2 definition candidate.

Public import uses only the standard library. Source extraction, sampled-source
review, definition interpretation, native rendering and closed project transport
retain their existing owners. A native build receipt is a separate observation:
it never upgrades the original candidate or its review/training authority.
Callers acquire and retain the established owned validation resources.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re

SCHEMA = "legal-source-sampling-definition-lake-preparation/v2"
BUILD_SCHEMA = "legal-source-sampling-definition-native-build/v2"
PROFILE = "sampled-source-unreviewed-unary-definition-native-build/v1"
MAX_RECORD_BYTES = 1024 * 1024
MAX_BINDING_BYTES = 4 * MAX_RECORD_BYTES
MAX_BUNDLE_BYTES = 64 * MAX_RECORD_BYTES
MAX_RESPONSE_BYTES = 64 * MAX_RECORD_BYTES
MAX_RAW_BYTES = 8_000_000
MAX_PROJECT_BYTES = 8 * MAX_RECORD_BYTES
MAX_PREPARATION_BYTES = 20 * MAX_RECORD_BYTES
MAX_CAPTURE_BYTES = 2 * MAX_RECORD_BYTES
MAX_LOG_PREVIEW_BYTES = 32768
MAX_RECEIPT_BYTES = MAX_RECORD_BYTES
MAX_FILES = 6
MAX_MODULES = 3
PROJECT_ROOT = "LegalSourceDefinitionV2"
_TOOLCHAIN = re.compile(r"leanprover/lean4:v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.]+)?\Z")
_REFUSED = re.compile(r"\b(?:sorry|admit|sorryAx|axiom|unsafe)\b")
_REPLAY_FIELDS = {
    "expected_request_sha256", "expected_bundle_sha256",
    "expected_response_sha256s", "expected_sampling_report_sha256",
    "descriptor", "expected_descriptor_sha256", "expected_raw_sha256",
    "expected_raw_bytes",
}
_OPTIONAL_REPLAY_FIELDS = {"view_limits", "sampling_limits"}
FALSE_FLAGS = dict.fromkeys(
    (
        "source_authenticity_verified", "publisher_authenticity_verified",
        "legal_currentness_verified", "source_semantics_verified",
        "applicability_verified", "context_closure_verified",
        "independently_reviewed", "meaning_admitted", "admitted", "formalized",
        "semantic_graph_admitted", "proof_authority", "proof_checked", "kernel_proofs_checked",
        "translation_preservation_proved", "cross_family_equivalence_verified",
        "training_qualified", "training_gold_qualified", "evaluation_gold_qualified",
        "Lean_admitted", "model_executed", "learned_translation",
        "backend_executed", "lean_compilation_verified",
    ),
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
    _need(
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
        "independent lowercase SHA256 required: " + label,
    )


def _wire(value, maximum):
    """Bound finite ordinary JSON before serialization or operation imports."""
    remaining, nodes = maximum, 2_000_000

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 64, "definition Lake JSON node/depth bound exceeded")
        if type(item) is dict:
            remaining -= 2 + 2 * len(item)
            for key, child in item.items():
                _need(type(key) is str, "ordinary definition Lake JSON keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            remaining -= 2 + len(item)
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= remaining, "bounded definition Lake JSON string required")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise ValueError("valid definition Lake UTF8 required") from error
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded definition Lake integer required")
            remaining -= 20
        elif type(item) is float:
            _need(math.isfinite(item), "finite definition Lake JSON required")
            remaining -= 32
        else:
            raise ValueError("ordinary definition Lake JSON values required")
        _need(remaining >= 0, "complete definition Lake JSON byte bound exceeded")

    visit(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded finite definition Lake JSON required") from error
    _need(len(raw) <= maximum, "complete definition Lake JSON byte bound exceeded")
    return raw


def _parse(raw, maximum):
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded original JSON bytes required")

    def pairs(items):
        value = {}
        for key, child in items:
            _need(key not in value, "duplicate definition Lake JSON key")
            value[key] = child
        return value

    def constant(_):
        raise ValueError("finite definition Lake JSON required")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("duplicate-free finite definition Lake JSON required") from error
    _need(type(value) is dict, "definition Lake JSON object required")
    _wire(value, maximum)
    return value


@dataclass(frozen=True)
class DefinitionLakePreparation:
    """Exact closed project and immutable manifest; preparation executes nothing."""

    manifest_json: str
    files: tuple[tuple[str, str], ...]

    def to_dict(self):
        _need(type(self.manifest_json) is str, "original preparation manifest text required")
        return _parse(self.manifest_json.encode("utf-8"), MAX_RECORD_BYTES)


def preparation_sha256(preparation):
    """FULL canonical manifest-and-files commitment, distinct from manifest SHA."""
    _need(type(preparation) is DefinitionLakePreparation, "typed V2 definition Lake preparation required")
    manifest = preparation.to_dict()
    _need(type(preparation.files) is tuple and len(preparation.files) == MAX_FILES, "exact six-file definition project required")
    names, files, total = [], [], 0
    for item in preparation.files:
        _need(type(item) is tuple and len(item) == 2, "exact generated path/text file pairs required")
        name, body = item
        _need(type(name) is str and type(body) is str, "ordinary generated path/text required")
        _need(
            len(name) <= 256 and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?", name) is not None
            and all(part not in (".", "..") for part in name.split("/")),
            "closed two-level generated file paths required",
        )
        total += len(body.encode("utf-8"))
        _need(total <= MAX_PROJECT_BYTES, "complete definition project byte bound exceeded")
        names.append(name)
        files.append([name, body])
    _need(names == sorted(set(names)), "exact distinct sorted generated file population required")
    return _sha(_wire({"manifest": manifest, "files": files}, MAX_PREPARATION_BYTES))


def _preflight(result, request_raw, bundle, responses, raw_html, expected_binding_sha256, toolchain, replay_inputs):
    _need(type(toolchain) is str and len(toolchain) <= 128 and _TOOLCHAIN.fullmatch(toolchain), "explicit version-pinned Lean toolchain required")
    _pin(expected_binding_sha256, "complete V2 definition binding")
    result_raw = _wire(result, MAX_BINDING_BYTES)
    _need(_sha(result_raw) == expected_binding_sha256, "independent complete definition binding pin differs")
    _need(
        type(result) is dict and set(result) == {"schema", "binding", "definition_report", "candidate", "population"}
        and result["schema"] == "legal-source-sampling-definition-binding/v2",
        "complete existing V2 definition binding required",
    )
    for name in ("binding", "definition_report", "candidate", "population"):
        _wire(result[name], MAX_RECORD_BYTES)
    _need(_REPLAY_FIELDS <= set(replay_inputs) <= _REPLAY_FIELDS | _OPTIONAL_REPLAY_FIELDS, "closed original definition binding replay inputs required")
    _wire(replay_inputs, MAX_RECORD_BYTES)
    for key in ("expected_request_sha256", "expected_bundle_sha256", "expected_sampling_report_sha256", "expected_descriptor_sha256", "expected_raw_sha256"):
        _pin(replay_inputs[key], key)
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= MAX_RECORD_BYTES, "bounded original definition request bytes required")
    _need(_sha(request_raw) == replay_inputs["expected_request_sha256"], "original definition request pin differs")
    _parse(request_raw, MAX_RECORD_BYTES)
    _need(type(bundle) is dict, "complete original sampled-source bundle required")
    _need(_sha(_wire(bundle, MAX_BUNDLE_BYTES)) == replay_inputs["expected_bundle_sha256"], "independent complete sampled-source bundle pin differs")
    _need(
        _sha(_wire(bundle.get("sampling_report"), 32 * MAX_RECORD_BYTES)) == replay_inputs["expected_sampling_report_sha256"],
        "independent complete sampling report pin differs",
    )
    _need(_sha(_wire(replay_inputs["descriptor"], MAX_RECORD_BYTES)) == replay_inputs["expected_descriptor_sha256"], "independent acquisition descriptor pin differs")
    pins = replay_inputs["expected_response_sha256s"]
    _need(type(responses) is list and len(responses) <= 8192 and type(pins) is list and len(pins) == len(responses), "one ordered independent pin per bounded original response required")
    total = 0
    for response, expected in zip(responses, pins, strict=True):
        _pin(expected, "complete sampled-source response")
        raw = _wire(response, MAX_RECORD_BYTES)
        total += len(raw)
        _need(total <= MAX_RESPONSE_BYTES, "complete definition response population byte bound exceeded")
        _need(_sha(raw) == expected, "independent complete response pin differs")
    _need(len(set(pins)) == len(pins), "duplicate exact source responses refused")
    count = replay_inputs["expected_raw_bytes"]
    _need(type(count) is int and 0 < count <= MAX_RAW_BYTES and type(raw_html) is bytes and len(raw_html) == count, "bounded exact original source HTML bytes required")
    _need(_sha(raw_html) == replay_inputs["expected_raw_sha256"], "independent original source HTML pin differs")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "definition Lake owner changed since import")


def _binding_owner():
    # This public import itself uses only the standard library. Its public
    # validator retains ownership of source/review/compiler/candidate replay.
    from . import legal_source_sampling_definition_binding_v2

    return legal_source_sampling_definition_binding_v2


def _owners():
    from . import legal_family_routes, legal_corpus_lake, legal_pilot_lake, legal_corpus_shared_lake
    from ..backends import process
    from ..formalization.autoencoder import native_family_lean_emitters

    return (_binding_owner(), legal_family_routes, native_family_lean_emitters,
            legal_corpus_lake, legal_pilot_lake, process, legal_corpus_shared_lake)


def _pins(owners, checked):
    global _OPERATION_PINS
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "definition Lake owner changed since import")
    pins = dict(checked["binding"]["producer_pins"])
    pins.update(checked["definition_report"]["producer_pins"])
    pins.update(owners[1].producer_pins())
    pins.update(owners[3]._pins())
    pins.update({str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes()) for module in owners})
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    for path, expected in pins.items():
        _need(_sha(Path(path).read_bytes()) == expected, "definition Lake producer changed: " + path)
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(pins)
    _need(pins == _OPERATION_PINS, "definition Lake operation owners changed since first use")
    return pins


def prepare_definition_lake_v2(result, request_raw, bundle, responses, raw_html, *, expected_binding_sha256, toolchain, **binding_replay_inputs):
    """Regenerate one complete unreviewed binding and prepare its exact module."""
    _preflight(result, request_raw, bundle, responses, raw_html, expected_binding_sha256, toolchain, binding_replay_inputs)
    checked = _binding_owner().validate_definition_binding_v2(
        result, request_raw, bundle, responses, raw_html,
        expected_binding_sha256=expected_binding_sha256, **binding_replay_inputs,
    )
    owners = _owners()
    _, routes, emitter, transport, _, _, _ = owners
    producers = _pins(owners, checked)
    report = checked["definition_report"]
    native = routes.prepare_native_fragment(family=report["family"], formula=report["native"]["formula"], expected_ast=report["native_ast"])
    _need(native == report["native"] and native["lean_body"] == report["lean_body"], "exact existing native fragment replay required")
    module = PROJECT_ROOT + ".Definition" + _sha(_wire({"binding_sha256": expected_binding_sha256, "family": report["family"]}, MAX_RECORD_BYTES))
    modules = [PROJECT_ROOT + ".Prelude", module, PROJECT_ROOT]
    imports = {modules[0]: [], module: [modules[0]], PROJECT_ROOT: [module]}
    files = {
        "lakefile.toml": 'name = "legal_source_definition_v2"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "legal"\nroots = ["LegalSourceDefinitionV2"]\n',
        "lean-toolchain": toolchain + "\n",
        "v2-input-bindings.json": _wire(checked["binding"], MAX_RECORD_BYTES).decode("utf-8") + "\n",
        PROJECT_ROOT + "/Prelude.lean": "namespace " + PROJECT_ROOT + "\n" + emitter.PRELUDE + "\nend " + PROJECT_ROOT + "\n",
        module.replace(".", "/") + ".lean": "import " + modules[0] + "\nnamespace " + module + "\n" + native["lean_body"] + "\nend " + module + "\n",
        PROJECT_ROOT + ".lean": "import " + module + "\n",
    }
    _need(len(files) == MAX_FILES and sum(len(body.encode("utf-8")) for body in files.values()) <= MAX_PROJECT_BYTES, "complete six-file definition project exceeds bounds")
    for name in modules:
        body = files[name.replace(".", "/") + ".lean"]
        _need(re.findall(r"(?m)^import ([A-Za-z][A-Za-z0-9_.]*)$", body) == imports[name] and not _REFUSED.search(body), "closed exact native module imports and placeholder-free source required")
    manifest = transport.contracts.seal_record({
        "schema": SCHEMA, "profile": PROFILE, "toolchain": toolchain, "target": "legal",
        "family": report["family"], "declaration_id": report["declaration_id"],
        "binding_full_canonical_sha256": expected_binding_sha256,
        "source_binding": checked["binding"],
        "candidate_full_canonical_sha256": _sha(_wire(checked["candidate"], MAX_RECORD_BYTES)),
        "population_full_canonical_sha256": _sha(_wire(checked["population"], MAX_RECORD_BYTES)),
        "native_ast_sha256": _sha(_wire(report["native_ast"], MAX_RECORD_BYTES)),
        "native_fragment_sha256": _sha(_wire(native, MAX_RECORD_BYTES)),
        "lean_body_sha256": _sha(native["lean_body"].encode("utf-8")),
        "review_status": checked["binding"]["status"],
        "expected_modules": modules, "module_imports": imports,
        "file_sha256": {name: _sha(body.encode("utf-8")) for name, body in sorted(files.items())},
        "producer_pins": producers, "preparation_only": True,
        "authority": dict(checked["binding"]["authority"]),
        "training_mask": 0, "evaluation_gold_mask": 0,
        "scope": "Exact parameterized definition declarations; no theorem, legal interpretation qualification or corpus admission.",
        **FALSE_FLAGS,
    })
    _need(_pins(owners, checked) == producers, "definition Lake producers changed during preparation")
    preparation = DefinitionLakePreparation(_wire(manifest, MAX_RECORD_BYTES).decode("utf-8"), tuple(sorted(files.items())))
    preparation_sha256(preparation)
    return preparation


def validate_definition_lake_v2(preparation, result, request_raw, bundle, responses, raw_html, *, expected_preparation_sha256, expected_binding_sha256, toolchain, **binding_replay_inputs):
    """Check the independent whole preparation pin and regenerate every file."""
    _pin(expected_preparation_sha256, "complete V2 definition Lake preparation")
    _need(preparation_sha256(preparation) == expected_preparation_sha256, "independent complete preparation pin differs")
    expected = prepare_definition_lake_v2(result, request_raw, bundle, responses, raw_html, expected_binding_sha256=expected_binding_sha256, toolchain=toolchain, **binding_replay_inputs)
    _need(expected == preparation, "definition Lake preparation differs from complete source/binding/native regeneration")
    return expected


def _installed_toolchain(lake_executable, toolchain):
    """Existing installed ELF/version owner; explicit injection point for tests."""
    return _owners()[4]._installed_toolchain(lake_executable, toolchain)


def _binary_recheck(binaries):
    _need(type(binaries) is dict and len(binaries) >= 1, "recorded installed toolchain binary pins required")
    for path, expected in binaries.items():
        _pin(expected, "installed compiler binary")
        if _sha(Path(path).read_bytes()) != expected:
            return False
    return True


def compilation_receipt_sha256(receipt):
    """Full canonical observation commitment; a receipt is not an admission token."""
    _need(type(receipt) is dict and receipt.get("schema") == BUILD_SCHEMA, "V2 definition native compilation receipt required")
    return _sha(_wire(receipt, MAX_RECEIPT_BYTES))


def _persist_build(checked, output, owners, artifacts, executed_sources, logs, receipt):
    """Delegate frozen project/artifact transport and durably retain observations."""
    transport, shared = owners[3], owners[6]
    shared._write_frozen_project(checked, output / "project")
    compiled = {name.removeprefix(".lake/build/lib/lean/"): body for name, body in artifacts.items()}
    for directory, contents, maximum in (
        ("compiled", compiled, MAX_MODULES),
        ("executed-inputs", executed_sources, MAX_FILES),
    ):
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
    _need((output / "build-receipt.json").read_bytes() == receipt_raw, "retained native receipt failed exact readback")
    for name, raw in logs.items():
        _need((output / name).read_bytes() == raw, "retained native compiler log failed exact readback")


def build_definition_lake_v2(preparation, result, request_raw, bundle, responses, raw_html, *, expected_preparation_sha256, expected_binding_sha256, toolchain, lake_executable, output_directory, timeout_seconds=60, cancellation=None, **binding_replay_inputs):
    """Run real offline Lake under caller-owned resources and retain observations.

    Input/pin/toolchain refusals raise before compilation. Operational compiler
    failure observations retain the exact project, returned compiler artifacts
    and receipt. Unresolved owned cleanup preserves its failure observation and
    re-raises the original cleanup exception/handle; the caller must retain its
    resources until that owner confirms cleanup. Source/review authority never
    follows from compilation or an owned-process observation.
    """
    _need(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds) and 0 < timeout_seconds <= 60, "finite compiler timeout in (0,60] required")
    checked = validate_definition_lake_v2(preparation, result, request_raw, bundle, responses, raw_html, expected_preparation_sha256=expected_preparation_sha256, expected_binding_sha256=expected_binding_sha256, toolchain=toolchain, **binding_replay_inputs)
    owners = _owners()
    _, _, _, transport, _, process, _ = owners
    output = transport._path(output_directory)
    transport._check_directories(output.parent, allow_missing=True)
    _need(not output.exists() and not output.is_symlink(), "fresh native build output directory required")
    executable, binaries, probes = _installed_toolchain(lake_executable, toolchain)
    _need(_binary_recheck(binaries), "installed compiler binaries changed during version probes")
    manifest = checked.to_dict()
    command = (str(executable), "--offline", "--no-cache", "build", "legal")
    modules = manifest["expected_modules"]
    artifact_paths = tuple(".lake/build/lib/lean/" + name.replace(".", "/") + ".olean" for name in modules)
    source_files = {name: body.encode("utf-8") for name, body in checked.files}
    output_paths = artifact_paths + tuple(source_files)
    invocation = process.ToolRunRequest(
        argv=command, input_files=dict(checked.files), output_paths=output_paths,
        owned_process_observation=True,
        environment={"ELAN_TOOLCHAIN": toolchain, "LEAN_NUM_THREADS": "1"},
        limits=process.ToolRunLimits(timeout_seconds=timeout_seconds, cpu_seconds=timeout_seconds,
            resident_memory_bytes=2 * 1024**3, max_output_bytes=MAX_CAPTURE_BYTES,
            max_input_bytes=MAX_PROJECT_BYTES, max_workspace_bytes=128 * MAX_RECORD_BYTES,
            max_output_files=MAX_MODULES + MAX_FILES))
    try:
        run = process.BoundedToolRunner().run(invocation, cancellation=cancellation)
    except process.OwnedToolCleanupError as error:
        # Do not replace or discard the real cleanup handle with a serialized
        # success flag. The same exception remains the caller's custody owner.
        try:
            refusal = transport.contracts.seal_record({
                "schema": BUILD_SCHEMA, "profile": PROFILE,
                "preparation_cid": manifest["record_cid"],
                "preparation_full_canonical_sha256": expected_preparation_sha256,
                "binding_full_canonical_sha256": expected_binding_sha256,
                "toolchain": toolchain, "expected_command": list(command),
                "build_passed": False, "status": "owned_native_cleanup_unresolved",
                "execution_status": "no_complete_native_result_returned",
                "cleanup_owner_retained_on_exception": True,
                "cleanup_confirmed": False,
                "error": str(error)[:2048], "artifact_sha256": {}, "artifact_files": {},
                "authority": dict(manifest["authority"]),
                "training_mask": 0, "evaluation_gold_mask": 0,
                **FALSE_FLAGS,
            })
            _persist_build(checked, output, owners, {}, {}, {}, refusal)
            error.add_note("Unqualified frozen project/cleanup refusal retained at " + str(output))
        except (ValueError, TypeError, OSError) as preservation_error:
            error.add_note("Native cleanup refusal preservation also failed: " + type(preservation_error).__name__)
        raise
    post_error, binary_error = None, None
    try:
        validate_definition_lake_v2(checked, result, request_raw, bundle, responses, raw_html, expected_preparation_sha256=expected_preparation_sha256, expected_binding_sha256=expected_binding_sha256, toolchain=toolchain, **binding_replay_inputs)
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
    native_runtime = bool(
        run.runtime is process.ToolRuntime.NATIVE
        and type(run.pid) is int and run.pid > 0 and not run.unavailable
    )
    lifecycle = run.native_lifecycle
    cleanup_confirmed = bool(
        type(lifecycle) is process.NativeToolLifecycleObservation
        and lifecycle.leader.pid == run.pid and lifecycle.cleanup_confirmed
    )
    passed = bool(run.ok and type(run.pid) is int and run.pid > 0 and native_runtime
        and tuple(run.command) == command and coverage and source_readback and unchanged
        and post_error is None and not run.output_truncated and not run.workspace_limit_exceeded
        and run.workspace_cleaned and cleanup_confirmed and not run.error
        and not re.search(r"\b(?:sorry|sorryAx)\b", run.stdout + run.stderr))
    logs = {
        "stdout.txt": run.stdout.encode("utf-8"),
        "stderr.txt": run.stderr.encode("utf-8"),
        "runner-error.txt": run.error.encode("utf-8"),
    }
    # The runner bounds captured bytes before replacing malformed UTF8. Each
    # replacement character may occupy three bytes in the retained UTF8 text.
    _need(all(len(raw) <= 3 * MAX_CAPTURE_BYTES for raw in logs.values()), "bounded native process observations required")
    # Complete bounded captures are retained separately. Their previews keep
    # the existing sealed corpus-record owner within its one-MiB limit.
    previews = {name: raw[:MAX_LOG_PREVIEW_BYTES].decode("utf-8", errors="replace").replace("\x00", "\\u0000") for name, raw in logs.items()}
    receipt = transport.contracts.seal_record({
        "schema": BUILD_SCHEMA, "profile": PROFILE,
        "preparation_cid": manifest["record_cid"],
        "preparation_full_canonical_sha256": expected_preparation_sha256,
        "preparation_manifest_sha256": _sha(checked.manifest_json.encode("utf-8")),
        "binding_full_canonical_sha256": expected_binding_sha256,
        "candidate_full_canonical_sha256": manifest["candidate_full_canonical_sha256"],
        "population_full_canonical_sha256": manifest["population_full_canonical_sha256"],
        "review_status": manifest["review_status"], "family": manifest["family"],
        "toolchain": toolchain, "command": list(run.command), "expected_command": list(command),
        "runtime": run.runtime.value, "pid": run.pid, "returncode": run.returncode,
        "expected_modules": modules,
        "compiled_modules": [name for name, path in zip(modules, artifact_paths, strict=True) if path in artifacts and artifacts[path]],
        "manifest_coverage_passed": bool(coverage), "executed_project_readback_passed": bool(source_readback),
        "executed_project_sha256": {name: _sha(run.output_files[name]) for name in source_files if name in run.output_files},
        "binary_sha256": binaries, "binaries_unchanged": unchanged, "version_probes": probes,
        "post_run_validation_passed": post_error is None, "post_run_validation_error": post_error,
        "binary_recheck_error": binary_error,
        "artifact_sha256": {name: _sha(body) for name, body in artifacts.items()},
        "artifact_bytes": {name: len(body) for name, body in artifacts.items()},
        "artifact_files": {name: "compiled/" + name.removeprefix(".lake/build/lib/lean/") for name in artifacts},
        "stdout": previews["stdout.txt"], "stderr": previews["stderr.txt"], "error": previews["runner-error.txt"],
        "log_sha256": {name: _sha(raw) for name, raw in logs.items()},
        "log_bytes": {name: len(raw) for name, raw in logs.items()},
        "receipt_text_truncated": any(len(raw) > MAX_LOG_PREVIEW_BYTES for raw in logs.values()),
        "elapsed_seconds": run.elapsed_seconds, "termination_reason": run.termination_reason,
        "timed_out": run.timed_out, "cancelled": run.cancelled, "unavailable": run.unavailable,
        "output_truncated": run.output_truncated, "workspace_limit_exceeded": run.workspace_limit_exceeded,
        "resource_exhausted": run.resource_exhausted, "workspace_cleaned": run.workspace_cleaned,
        # This means an intervention occurred, not that normal exit is unsafe.
        "process_tree_terminated": run.process_tree_terminated,
        "native_lifecycle": lifecycle.to_dict() if type(lifecycle) is process.NativeToolLifecycleObservation else None,
        "cleanup_confirmed": cleanup_confirmed,
        "ownership_is_sampled": True, "kernel_containment_attested": False,
        "build_passed": passed, "native_runtime_verified": native_runtime,
        "theorem_axiom_dependencies": {}, "theorem_assumptions": [],
        "authority": dict(manifest["authority"]), "training_mask": 0, "evaluation_gold_mask": 0,
        "scope": "Native compilation of exact parameterized declarations only; no theorem, source fidelity proof, legal review or corpus admission.",
        **(FALSE_FLAGS | {"backend_executed": type(run.pid) is int and run.pid > 0, "lean_compilation_verified": passed}),
    })
    executed_sources = {name: run.output_files[name] for name in source_files if name in run.output_files}
    _persist_build(checked, output, owners, artifacts, executed_sources, logs, receipt)
    return receipt


__all__ = [
    "DefinitionLakePreparation", "prepare_definition_lake_v2", "preparation_sha256",
    "validate_definition_lake_v2", "build_definition_lake_v2", "compilation_receipt_sha256",
]
