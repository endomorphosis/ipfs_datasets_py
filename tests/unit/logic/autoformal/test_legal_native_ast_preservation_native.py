"""Native preservation custody using real fragments and synthetic tool results.

Only installed-toolchain discovery and the bounded process runner are stubbed.
Fake PID/artifacts/messages below exercise refusal boundaries and establish no
native proof, legal meaning, human review, source fidelity or training authority.
All test filesystem objects are ordinary files and directories.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation as preparer
from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation_native as native
from ipfs_datasets_py.logic.backends import process


_SPEC = importlib.util.spec_from_file_location(
    "_native_ast_preservation_genuine_fragment_fixture",
    Path(__file__).with_name("test_legal_native_ast_preservation.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)

TOOLCHAIN = _FIXTURE.TOOLCHAIN
PREVIEW_BYTES = 32768
FALSE_AUTHORITY = (
    "source_semantics_verified", "source_authenticity_verified",
    "admitted", "formalized", "proof_authority", "training_qualified",
    "training_gold_qualified", "model_executed", "learned_translation",
    "cross_family_equivalence_verified",
    "source_to_model_equivalence_proved", "source_fidelity_proved",
    "translation_preservation_proved", "general_emitter_preservation_proved",
    "general_serialized_AST_lowering_preservation_proved",
    "json_bytes_parser_verified", "json_bytes_parser_preservation_proved",
    "model_convergence_proved", "convergence_proved",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def original_data(family="fol"):
    data = _FIXTURE.fragment_data(family)
    preparation = _FIXTURE.prepare(data)
    return data, preparation


@pytest.fixture(scope="module")
def base():
    return original_data()


def arguments(data, preparation):
    return {
        "expected_preparation_sha256": preparer.preparation_sha256(preparation),
        "expected_fragment_file_sha256": sha(data["fragment_raw"]),
        "toolchain": data["toolchain"],
    }


def validate(data, preparation, **overrides):
    return native.validate_native_ast_preservation(
        preparation, data["fragment_raw"], **(arguments(data, preparation) | overrides)
    )


def build(data, preparation, executable, output, **overrides):
    return native.build_native_ast_preservation(
        preparation, data["fragment_raw"], **(arguments(data, preparation) | {
            "lake_executable": str(executable), "output_directory": output,
            "timeout_seconds": 12,
        } | overrides),
    )


def meta(preparation):
    return json.loads(preparation.manifest_json)


def reseal_manifest(preparation, manifest, files=None):
    files = dict(preparation.files) if files is None else files
    manifest["file_sha256"] = {
        name: sha(text.encode("utf-8")) for name, text in sorted(files.items())
    }
    sealed = contracts.seal_record({
        key: value for key, value in manifest.items()
        if key not in {"record_cid", "cid_scope"}
    })
    return replace(preparation, manifest_json=canonical(sealed).decode(),
                   files=tuple(sorted(files.items())))


def identity(pid=123, *, process_group_id=123, session_id=123, parent_pid=None):
    return process.NativeProcessIdentity(
        pid=pid, birth_ticks=1,
        parent_pid=os.getpid() if parent_pid is None else parent_pid,
        process_group_id=process_group_id, session_id=session_id,
    )


def lifecycle(**overrides):
    parent, _ = process._linux_owned_identity(os.getpid())
    values = {
        "parent_pid": os.getpid(), "parent_birth_ticks": parent.birth_ticks,
        "leader": identity(), "observed_descendants": (),
        "leader_reaped": True, "descendant_tracking_complete": True,
        "group_scan_complete": True, "remaining_group_members": (),
        "remaining_tracked_descendants": (), "readers_started": 2,
        "readers_joined": 2, "stdin_writer_started": 0,
        "stdin_writer_joined": 0, "workspace_device": 1,
        "workspace_inode": 1, "workspace_removed": True,
    }
    return process.NativeToolLifecycleObservation(**(values | overrides))


def axiom_stdout(preparation):
    return "\n".join(
        "'" + name + "' does not depend on any axioms"
        for name in meta(preparation)["theorems"]
    ) + "\n"


@pytest.fixture
def synthetic_compiler(monkeypatch, tmp_path):
    executable = tmp_path / "synthetic-lake"
    executable.write_bytes(b"explicit synthetic unit binary; never executed")
    compiler = tmp_path / "synthetic-lean"
    compiler.write_bytes(b"explicit synthetic sibling compiler; never executed")
    binary_pins = {str(path): sha(path.read_bytes()) for path in (executable, compiler)}
    monkeypatch.setattr(native, "_installed_toolchain",
                        lambda *args, **kwargs: (executable, binary_pins, {}))
    calls = []

    def install(preparation, *, result_changes=None, output_edit=None, after=None,
                stdout=None, cancellation=None):
        artifacts = tuple(
            ".lake/build/lib/lean/" + name.replace(".", "/") + ".olean"
            for name in meta(preparation)["expected_modules"]
        )
        expected_sources = dict(preparation.files)

        def synthetic_run(self, request, *, cancellation=None):
            calls.append(request)
            assert request.argv == (str(executable), "--offline", "--no-cache", "build", "legal")
            assert request.runtime is process.ToolRuntime.NATIVE
            assert request.owned_process_observation is True
            assert request.environment["ELAN_TOOLCHAIN"] == TOOLCHAIN
            assert request.environment["LEAN_NUM_THREADS"] == "1"
            assert request.limits.timeout_seconds == 12
            assert request.limits.max_output_files == 11
            assert request.limits.max_output_bytes == 2 * 1024**2
            assert request.limits.resident_memory_bytes == 2 * 1024**3
            assert request.limits.max_workspace_bytes == 128 * 1024**2
            assert request.output_paths == artifacts + tuple(sorted(expected_sources))
            assert dict(request.input_files) == expected_sources
            assert cancellation is expected_cancellation
            outputs = {name: b"synthetic olean bytes; no native proof evidence" for name in artifacts}
            outputs.update({name: text.encode() for name, text in expected_sources.items()})
            if output_edit is not None:
                output_edit(outputs, artifacts, tuple(sorted(expected_sources)))
            if after is not None:
                after()
            values = {
                "interface_version": "synthetic-unit-boundary/v1",
                "runtime": process.ToolRuntime.NATIVE, "command": request.argv,
                "returncode": 0, "stdout": axiom_stdout(preparation) if stdout is None else stdout,
                "stderr": "", "elapsed_seconds": 0.01, "output_files": outputs,
                "pid": 123, "native_lifecycle": lifecycle(), "workspace_cleaned": True,
                "process_tree_terminated": False,
            }
            values.update(result_changes or {})
            return process.ToolRunResult(**values)

        expected_cancellation = cancellation
        monkeypatch.setattr(process.BoundedToolRunner, "run", synthetic_run)
        return executable, calls

    return install


def assert_no_authority(receipt):
    for name in FALSE_AUTHORITY:
        assert receipt[name] is False, name
    assert receipt["training_mask"] == receipt["evaluation_gold_mask"] == 0
    assert type(receipt["training_mask"]) is type(receipt["evaluation_gold_mask"]) is int
    assert all(value is False for value in receipt["authority"].values())


def test_public_native_import_is_stdlib_only():
    code = r"""
import importlib.util,sys
blocked=('ipfs_datasets_py','torch','transformers','tensorflow','numpy','multiformats','cryptography','pyarrow','requests')
class Deny:
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==name or fullname.startswith(name+'.') for name in blocked):
            raise AssertionError('operation owner reached: '+fullname)
sys.meta_path.insert(0,Deny())
spec=importlib.util.spec_from_file_location('_native_ast_cold',sys.argv[1])
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)
for name in ('validate_native_ast_preservation','build_native_ast_preservation','compilation_receipt_sha256'):
    assert callable(getattr(module,name))
assert not any(any(name==prefix or name.startswith(prefix+'.') for prefix in blocked) for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code, native.__file__],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_exact_handoff_captures_all_modules_inputs_and_three_kernel_observations(
    family, synthetic_compiler, tmp_path,
):
    data, preparation = original_data(family)
    before = deepcopy(data)
    original_manifest = preparation.manifest_json
    assert validate(data, preparation) == preparation
    token = process.CancellationToken()
    executable, calls = synthetic_compiler(preparation, cancellation=token)
    output = tmp_path / "native-preservation"
    receipt = build(data, preparation, executable, output, cancellation=token)
    observed = receipt["native_observations"]
    assert len(calls) == 1
    assert receipt["build_passed"] is receipt["native_ast_value_preservation_proved"] is True
    assert receipt["proof_checked"] is receipt["kernel_proofs_checked"] is True
    assert receipt["lean_compilation_verified"] is receipt["backend_executed"] is True
    assert observed["native_runtime_verified"] is True
    assert observed["cleanup_confirmed"] is True
    assert observed["observed_process_scope_passed"] is True
    assert observed["process_tree_terminated"] is False
    assert observed["expected_modules"] == observed["compiled_modules"] == meta(preparation)["expected_modules"]
    assert len(observed["artifact_sha256"]) == 4
    assert len(observed["executed_project_sha256"]) == 7
    assert observed["theorem_axiom_dependencies"] == {name: [] for name in meta(preparation)["theorems"]}
    for name in ("manifest_coverage_passed", "executed_project_readback_passed",
                 "post_run_validation_passed", "binaries_unchanged"):
        assert observed[name] is True, name
    assert_no_authority(receipt)
    for name, text in preparation.files:
        assert (output / "project" / name).read_bytes() == text.encode()
        assert (output / "executed-inputs" / name).read_bytes() == text.encode()
    assert (output / "project" / "corpus-manifest.json").read_bytes() == original_manifest.encode()
    assert json.loads((output / "build-receipt.json").read_bytes()) == receipt
    assert len([path for path in output.rglob("*") if path.is_file()]) == 23
    for name, path in observed["artifact_files"].items():
        assert sha((output / path).read_bytes()) == observed["artifact_sha256"][name]
    assert data == before and preparation.manifest_json == original_manifest


@pytest.mark.parametrize("index", range(4))
def test_each_compiled_module_is_required_even_with_other_modules_and_axiom_lines(
    base, synthetic_compiler, tmp_path, index,
):
    data, preparation = base
    executable, _ = synthetic_compiler(preparation,
        output_edit=lambda outputs, artifacts, sources: outputs.pop(artifacts[index]))
    receipt = build(data, preparation, executable, tmp_path / "missing-module")
    assert receipt["build_passed"] is receipt["native_ast_value_preservation_proved"] is False
    assert receipt["native_observations"]["manifest_coverage_passed"] is False
    assert_no_authority(receipt)


@pytest.mark.parametrize("index", range(7))
def test_each_executed_input_requires_exact_returned_bytes(base, synthetic_compiler, tmp_path, index):
    data, preparation = base
    executable, _ = synthetic_compiler(preparation, output_edit=lambda outputs, artifacts, sources:
        outputs.__setitem__(sources[index], b"changed exact input"))
    receipt = build(data, preparation, executable, tmp_path / "changed-source")
    assert receipt["build_passed"] is receipt["native_ast_value_preservation_proved"] is False
    assert receipt["native_observations"]["executed_project_readback_passed"] is False
    assert_no_authority(receipt)


@pytest.mark.parametrize("damage", ["empty_nonfirst", "extra_artifact", "missing_source"])
def test_complete_nonempty_closed_output_population_is_required(base, synthetic_compiler, tmp_path, damage):
    data, preparation = base
    def edit(outputs, artifacts, sources):
        if damage == "empty_nonfirst": outputs[artifacts[2]] = b""
        elif damage == "extra_artifact": outputs["unrequested.olean"] = b"foreign artifact"
        else: outputs.pop(sources[-1])
    executable, _ = synthetic_compiler(preparation, output_edit=edit)
    receipt = build(data, preparation, executable, tmp_path / "closed-population")
    assert receipt["native_observations"]["manifest_coverage_passed"] is False
    assert receipt["build_passed"] is False
    assert_no_authority(receipt)


@pytest.mark.parametrize("damage", [
    "missing", "duplicate", "unknown", "nonempty_axioms", "wrong_qualification",
    "unquoted", "inline_claim", "wrong_module_prefix", "stderr_claim", "sorry",
])
def test_three_exact_compiler_axiom_lines_cannot_be_inferred_or_forged(base, synthetic_compiler, tmp_path, damage):
    data, preparation = base
    names = meta(preparation)["theorems"]
    lines = axiom_stdout(preparation).splitlines()
    changes = {}
    if damage == "missing": lines.pop(1)
    elif damage == "duplicate": lines.append(lines[0])
    elif damage == "unknown": lines.append("'Foreign.fake' does not depend on any axioms")
    elif damage == "nonempty_axioms": lines[1] = "'" + names[1] + "' depends on axioms: [Classical.choice]"
    elif damage == "wrong_qualification": lines[0] = "'native_value_exact' does not depend on any axioms"
    elif damage == "unquoted": lines[0] = names[0] + " does not depend on any axioms"
    elif damage == "inline_claim": lines[0] = "untrusted arbitrary prefix " + lines[0]
    elif damage == "wrong_module_prefix": lines[0] = "info: Foreign.lean:1:0: " + lines[0]
    elif damage == "stderr_claim": changes["stderr"] = lines.pop(1) + "\n"
    else: lines.append("warning: declaration uses sorryAx")
    executable, _ = synthetic_compiler(preparation, stdout="\n".join(lines) + "\n", result_changes=changes)
    receipt = build(data, preparation, executable, tmp_path / "axiom-refusal")
    assert receipt["build_passed"] is receipt["kernel_proofs_checked"] is False
    assert receipt["native_ast_value_preservation_proved"] is False
    assert_no_authority(receipt)


def test_exact_module_position_prefixed_axiom_messages_are_accepted(base, synthetic_compiler, tmp_path):
    data, preparation = base
    lines = []
    for name in meta(preparation)["theorems"]:
        path = name.rsplit(".", 1)[0].replace(".", "/") + ".lean"
        lines.append("info: ./" + path + ":42:0: '" + name + "' does not depend on any axioms")
    executable, _ = synthetic_compiler(preparation, stdout="\n".join(lines) + "\n")
    receipt = build(data, preparation, executable, tmp_path / "prefixed-observations")
    assert receipt["build_passed"] is True
    assert_no_authority(receipt)


@pytest.mark.parametrize("field,value", [
    ("pid", None), ("pid", 0), ("pid", -1), ("pid", True),
    ("runtime", process.ToolRuntime.JVM), ("returncode", 1),
    ("timed_out", True), ("cancelled", True), ("unavailable", True),
    ("resource_exhausted", True), ("output_truncated", True),
    ("workspace_limit_exceeded", True), ("workspace_cleaned", False),
    ("error", "synthetic runner failure"),
    ("command", ("foreign-lake", "--offline", "--no-cache", "build", "legal")),
])
def test_process_identity_and_success_cannot_be_inferred_from_outputs(base, synthetic_compiler, tmp_path, field, value):
    data, preparation = base
    executable, _ = synthetic_compiler(preparation, result_changes={field: value})
    receipt = build(data, preparation, executable, tmp_path / "process-refusal")
    assert receipt["build_passed"] is receipt["native_ast_value_preservation_proved"] is False
    assert_no_authority(receipt)


@pytest.mark.parametrize("damage", [
    "absent", "dictionary", "wrong_leader", "leader_unreaped", "untracked",
    "unscanned", "live_group", "live_tracked", "unjoined_reader", "unjoined_stdin",
    "workspace_retained", "observation_error", "foreign_group", "foreign_session",
    "wrong_leader_group", "wrong_leader_session", "wrong_parent", "boolean_parent",
    "zero_parent_birth", "boolean_parent_birth", "float_parent_birth", "wrong_parent_birth",
    "mismatched_leader_parent",
])
def test_typed_owned_cleanup_current_caller_and_observed_group_session_are_required(
    base, synthetic_compiler, tmp_path, damage,
):
    data, preparation = base
    actual_parent, _ = process._linux_owned_identity(os.getpid())
    variations = {
        "wrong_leader": {"leader": identity(124)}, "leader_unreaped": {"leader_reaped": False},
        "untracked": {"descendant_tracking_complete": False}, "unscanned": {"group_scan_complete": False},
        "live_group": {"remaining_group_members": (identity(124),)},
        "live_tracked": {"remaining_tracked_descendants": (identity(124),)},
        "unjoined_reader": {"readers_joined": 1}, "unjoined_stdin": {"stdin_writer_started": 1},
        "workspace_retained": {"workspace_removed": False},
        "observation_error": {"observation_errors": ("synthetic incomplete scan",)},
        "foreign_group": {"observed_descendants": (identity(124, process_group_id=124),)},
        "foreign_session": {"observed_descendants": (identity(124, session_id=124),)},
        "wrong_leader_group": {"leader": identity(process_group_id=124)},
        "wrong_leader_session": {"leader": identity(session_id=124)},
        "wrong_parent": {"parent_pid": os.getpid() + 1}, "boolean_parent": {"parent_pid": True},
        "zero_parent_birth": {"parent_birth_ticks": 0}, "boolean_parent_birth": {"parent_birth_ticks": True},
        "float_parent_birth": {"parent_birth_ticks": float(actual_parent.birth_ticks)},
        "wrong_parent_birth": {"parent_birth_ticks": actual_parent.birth_ticks + 1},
        "mismatched_leader_parent": {"leader": identity(parent_pid=os.getpid() + 1)},
    }
    observation = None if damage == "absent" else lifecycle(**variations.get(damage, {}))
    if damage == "dictionary": observation = observation.to_dict()
    executable, _ = synthetic_compiler(preparation, result_changes={"native_lifecycle": observation})
    receipt = build(data, preparation, executable, tmp_path / "custody-refusal")
    assert receipt["build_passed"] is receipt["native_ast_value_preservation_proved"] is False
    assert_no_authority(receipt)


def test_clean_observed_descendant_needs_no_forced_termination(base, synthetic_compiler, tmp_path):
    data, preparation = base
    executable, _ = synthetic_compiler(preparation,
        result_changes={"native_lifecycle": lifecycle(observed_descendants=(identity(124),))})
    receipt = build(data, preparation, executable, tmp_path / "clean-descendant")
    assert receipt["build_passed"] is True
    assert receipt["native_observations"]["process_tree_terminated"] is False
    assert_no_authority(receipt)


def test_binary_identity_is_rechecked_after_process_return(base, synthetic_compiler, tmp_path):
    data, preparation = base
    executable, _ = synthetic_compiler(preparation)
    synthetic_compiler(preparation, after=lambda: executable.write_bytes(b"changed synthetic binary"))
    receipt = build(data, preparation, executable, tmp_path / "changed-binary")
    assert receipt["native_observations"]["binaries_unchanged"] is False
    assert receipt["build_passed"] is False
    assert_no_authority(receipt)


@pytest.mark.parametrize("damage", ["manifest", "files"])
def test_mutation_of_original_preparation_cannot_rewrite_frozen_executed_project(base, synthetic_compiler, tmp_path, damage):
    data, original = base
    preparation = replace(original)
    original_manifest, original_files = preparation.manifest_json, preparation.files
    def mutate():
        if damage == "manifest":
            changed = meta(preparation)
            changed["theorems"] = []
            revised = reseal_manifest(preparation, changed)
            object.__setattr__(preparation, "manifest_json", revised.manifest_json)
        else:
            files = dict(preparation.files)
            path = next(name for name in files if name.endswith(".lean"))
            files[path] += "\n-- changed after process\n"
            object.__setattr__(preparation, "files", tuple(sorted(files.items())))
    executable, _ = synthetic_compiler(preparation, after=mutate)
    output = tmp_path / "post-preparation-mutation"
    receipt = build(data, preparation, executable, output)
    assert receipt["native_observations"]["post_run_validation_passed"] is False
    assert receipt["build_passed"] is False
    assert (output / "project" / "corpus-manifest.json").read_bytes() == original_manifest.encode()
    for name, text in original_files:
        assert (output / "project" / name).read_bytes() == text.encode()
        assert (output / "executed-inputs" / name).read_bytes() == text.encode()
    assert original.manifest_json == original_manifest and original.files == original_files
    assert_no_authority(receipt)


@pytest.mark.parametrize("damage", ["fragment", "preparation"])
def test_original_replay_failures_refuse_before_toolchain_or_process(base, monkeypatch, tmp_path, damage):
    original, preparation = base
    data = deepcopy(original)
    if damage == "fragment":
        fragment = json.loads(data["fragment_raw"])
        fragment["lean_body"] = fragment["lean_body"].replace("↔", "→")
        data["fragment_raw"] = canonical(fragment)
    else:
        manifest = meta(preparation)
        manifest["theorems"][0] = "Foreign.fake"
        preparation = reseal_manifest(preparation, manifest)
    monkeypatch.setattr(native, "_installed_toolchain", lambda *a, **k: pytest.fail("probe reached before replay"))
    monkeypatch.setattr(process.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("runner reached before replay"))
    output = tmp_path / "must-not-export"
    with pytest.raises(ValueError):
        build(data, preparation, tmp_path / "never-executed", output)
    assert not output.exists()


@pytest.mark.parametrize("field,value", [
    ("expected_preparation_sha256", "0" * 64), ("expected_preparation_sha256", True),
    ("expected_fragment_file_sha256", "0" * 64), ("expected_fragment_file_sha256", "A" * 64),
    ("toolchain", "leanprover/lean4:latest"), ("toolchain", TOOLCHAIN + "\n"),
])
def test_independent_pins_and_toolchain_refuse_before_lazy_owners(base, field, value):
    data, preparation = base
    with patch.object(native, "_owners", side_effect=AssertionError("lazy owners reached")):
        with pytest.raises(ValueError):
            validate(data, preparation, **{field: value})


@pytest.mark.parametrize("damage", ["mutable", "oversize", "duplicate", "nonfinite"])
def test_bounded_ordinary_fragment_refuses_before_lazy_operation_imports(base, damage):
    original, preparation = base
    data = deepcopy(original)
    data["fragment_raw"] = {
        "mutable": bytearray(data["fragment_raw"]), "oversize": b" " * (1024**2 + 1),
        "duplicate": b'{"schema":"a","schema":"b"}', "nonfinite": b'{"bad":NaN}',
    }[damage]
    with patch.object(native, "_owners", side_effect=AssertionError("lazy owners reached")):
        with pytest.raises(ValueError):
            validate(data, preparation)


@pytest.mark.parametrize("timeout", [True, 0, -1, 61, float("nan"), float("inf")])
def test_bad_execution_bound_refuses_without_native_probe_or_export(base, tmp_path, timeout):
    data, preparation = base
    output = tmp_path / "must-not-export"
    with patch.object(native, "_owners", side_effect=AssertionError("operation owners reached")):
        with pytest.raises(ValueError):
            build(data, preparation, tmp_path / "lake", output, timeout_seconds=timeout)
    assert not output.exists()


def test_existing_output_is_preserved_and_never_executed(base, monkeypatch, tmp_path):
    data, preparation = base
    output = tmp_path / "existing"
    output.mkdir(mode=0o700)
    (output / "retained.txt").write_bytes(b"preserve exact evidence")
    monkeypatch.setattr(native, "_installed_toolchain", lambda *a, **k: pytest.fail("probe reached"))
    monkeypatch.setattr(process.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("runner reached"))
    with pytest.raises(ValueError):
        build(data, preparation, tmp_path / "lake", output)
    assert {path.name: path.read_bytes() for path in output.iterdir()} == {"retained.txt": b"preserve exact evidence"}


def test_full_bounded_utf8_logs_survive_with_small_receipt_previews(base, synthetic_compiler, tmp_path):
    data, preparation = base
    text = "header\x00\n" + "é" * PREVIEW_BYTES + "\n" + axiom_stdout(preparation)
    stderr = "z" * (PREVIEW_BYTES + 23)
    executable, _ = synthetic_compiler(preparation, stdout=text, result_changes={"stderr": stderr})
    output = tmp_path / "bounded-logs"
    receipt = build(data, preparation, executable, output)
    observed = receipt["native_observations"]
    raw = text.encode()
    assert receipt["build_passed"] is True
    assert observed["receipt_text_truncated"] is True
    assert observed["stdout"] == raw[:PREVIEW_BYTES].decode("utf-8", errors="replace").replace("\x00", "\\u0000")
    assert observed["stderr"] == stderr[:PREVIEW_BYTES]
    assert len((output / "build-receipt.json").read_bytes()) <= 1024**2
    for name, expected in {"stdout.txt": raw, "stderr.txt": stderr.encode(), "runner-error.txt": b""}.items():
        assert (output / name).read_bytes() == expected
        assert observed["log_sha256"][name] == sha(expected)
        assert observed["log_bytes"][name] == len(expected)
    assert_no_authority(receipt)


def test_unresolved_native_cleanup_preserves_same_exception_and_handle(base, synthetic_compiler, monkeypatch, tmp_path):
    data, preparation = base
    executable, _ = synthetic_compiler(preparation)
    handle = object()
    original = process.OwnedToolCleanupError(handle, "synthetic unresolved cleanup")
    def fail(self, request, *, cancellation=None):
        assert request.owned_process_observation is True
        raise original
    monkeypatch.setattr(process.BoundedToolRunner, "run", fail)
    output = tmp_path / "retained-cleanup-refusal"
    with pytest.raises(process.OwnedToolCleanupError) as caught:
        build(data, preparation, executable, output)
    assert caught.value is original and caught.value.cleanup_handle is handle
    receipt = json.loads((output / "build-receipt.json").read_bytes())
    observed = receipt["native_observations"]
    assert receipt["status"] == "owned_native_cleanup_unresolved"
    assert observed["cleanup_owner_retained_on_exception"] is True
    assert observed["cleanup_confirmed"] is False
    assert receipt["build_passed"] is receipt["native_ast_value_preservation_proved"] is False
    assert observed["artifact_sha256"] == {}
    for name, text in preparation.files:
        assert (output / "project" / name).read_bytes() == text.encode()
    assert_no_authority(receipt)
