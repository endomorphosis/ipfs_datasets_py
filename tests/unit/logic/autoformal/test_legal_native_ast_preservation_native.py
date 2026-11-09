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
for name in ('validate_native_ast_preservation','build_native_ast_preservation','validate_relational_ast_preservation','build_relational_ast_preservation','validate_counted_ast_preservation','build_counted_ast_preservation','compilation_receipt_sha256'):
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


# Reuse the original relational builder and pure preparation fixture; these
# synthetic compiler controls establish no native proof or legal authority.
relational_preservation_fixtures = _FIXTURE.relational_preservation_fixtures


@pytest.fixture(scope="module")
def relational_base(relational_preservation_fixtures):
    fixtures = relational_preservation_fixtures
    captured = _FIXTURE._relational_preservation_capture(fixtures, fixtures.approval_request())
    return captured, _FIXTURE._prepare_relational_preservation(captured)


def relational_arguments(captured, preparation):
    report, request_raw = captured
    return {
        "expected_preparation_sha256": preparer.preparation_sha256(preparation),
        "expected_report_sha256": sha(canonical(report)),
        "expected_request_sha256": sha(request_raw),
        "toolchain": TOOLCHAIN,
    }


def validate_relational(captured, preparation, **overrides):
    report, request_raw = captured
    return native.validate_relational_ast_preservation(
        preparation, report, request_raw,
        **(relational_arguments(captured, preparation) | overrides),
    )


def build_relational(captured, preparation, executable, output, **overrides):
    report, request_raw = captured
    return native.build_relational_ast_preservation(
        preparation, report, request_raw,
        **(relational_arguments(captured, preparation) | {
            "lake_executable": str(executable), "output_directory": output,
            "timeout_seconds": 12,
        } | overrides),
    )


def test_relational_native_profile_reuses_four_modules_seven_inputs_and_five_obligations(
        relational_base, synthetic_compiler, tmp_path):
    captured, preparation = relational_base
    before = deepcopy(captured)
    assert validate_relational(captured, preparation) == preparation
    executable, calls = synthetic_compiler(preparation)
    output = tmp_path / "relational-native"
    receipt = build_relational(captured, preparation, executable, output)
    observed, manifest = receipt["native_observations"], meta(preparation)
    assert len(calls) == 1
    assert receipt["profile"] == native.RELATIONAL_PROFILE != native.PROFILE
    assert receipt["original_preparation_state"]["preparation_only"] is True
    assert receipt["build_passed"] is receipt["kernel_proofs_checked"] is True
    assert len(observed["compiled_modules"]) == len(observed["artifact_sha256"]) == 4
    assert len(observed["executed_project_sha256"]) == 7
    assert observed["theorems"] == manifest["theorems"]
    assert len(observed["theorem_axiom_dependencies"]) == 5
    assert observed["theorem_axiom_dependencies"] == {name: [] for name in manifest["theorems"]}
    for field in ("relational_report_sha256", "original_request_sha256",
                  "typed_expression_sha256", "argument_roles_sha256"):
        assert receipt[field] == manifest[field]
    assert "Five exact concrete checks" in receipt["proof_scope"]
    assert observed["cleanup_confirmed"] is observed["observed_process_scope_passed"] is True
    assert_no_authority(receipt)
    assert captured == before
    assert json.loads((output / "build-receipt.json").read_bytes()) == receipt


@pytest.mark.parametrize("index", range(5))
def test_each_relational_theorem_requires_its_own_exact_observation(
        relational_base, synthetic_compiler, tmp_path, index):
    captured, preparation = relational_base
    lines = axiom_stdout(preparation).splitlines()
    missing = lines.pop(index)
    executable, _ = synthetic_compiler(preparation, stdout="\n".join(lines) + "\n")
    receipt = build_relational(captured, preparation, executable, tmp_path / "missing-relational-theorem")
    observed = receipt["native_observations"]
    assert receipt["build_passed"] is receipt["kernel_proofs_checked"] is False
    assert len(observed["theorem_axiom_dependencies"]) == 4
    assert observed["axiom_observations_passed"] is False
    assert missing.split("'", 2)[1] not in observed["theorem_axiom_dependencies"]
    assert_no_authority(receipt)


@pytest.mark.parametrize("damage", ["duplicate", "unknown", "renamed", "reordered", "legacy_profile"])
def test_relational_theorem_allowlist_cannot_be_replaced_by_five_arbitrary_reports(relational_base, damage):
    _, preparation = relational_base
    manifest = deepcopy(meta(preparation))
    lines = axiom_stdout(preparation).splitlines()
    if damage == "duplicate":
        lines.append(lines[-1])
    elif damage == "unknown":
        lines.append("'Foreign.role_denotation_matches_native' does not depend on any axioms")
    else:
        if damage == "renamed":
            manifest["theorems"][-1] = manifest["expected_modules"][2] + ".arbitrary_proof"
        elif damage == "reordered":
            manifest["theorems"][-2:] = list(reversed(manifest["theorems"][-2:]))
        else:
            manifest["profile"] = preparer.PROFILE
        with pytest.raises(ValueError):
            native._axiom_observations("\n".join(lines) + "\n", "", manifest)
        return
    _, errors, passed = native._axiom_observations("\n".join(lines) + "\n", "", manifest)
    assert errors and passed is False


@pytest.mark.parametrize("field", [
    "expected_preparation_sha256", "expected_report_sha256", "expected_request_sha256",
])
def test_relational_independent_commitments_refuse_before_lazy_owners(relational_base, field):
    captured, preparation = relational_base
    with patch.object(native, "_owners", side_effect=AssertionError("operation owners reached")):
        with pytest.raises(ValueError):
            validate_relational(captured, preparation, **{field: "0" * 64})


@pytest.mark.parametrize("damage", [
    "report_nonfinite", "report_not_dict", "request_mutable",
    "request_duplicate", "request_nonfinite", "request_oversize",
])
def test_relational_ordinary_input_bounds_precede_lazy_owners(relational_base, damage):
    captured, preparation = relational_base
    report, request_raw = captured
    kwargs = relational_arguments(captured, preparation)
    if damage == "report_nonfinite":
        report = {"bad": float("nan")}
    elif damage == "report_not_dict":
        report = []
    elif damage == "request_mutable":
        request_raw = bytearray(request_raw)
    else:
        if damage == "request_oversize":
            request_raw = b" " * (native.MAX_RELATIONAL_REQUEST_BYTES + 1)
        else:
            request_raw = (b'{"x":0,"x":0}' if damage == "request_duplicate" else b'{"x":NaN}')
        kwargs["expected_request_sha256"] = sha(request_raw)
    with patch.object(native, "_owners", side_effect=AssertionError("operation owners reached")):
        with pytest.raises(ValueError):
            native.validate_relational_ast_preservation(preparation, report, request_raw, **kwargs)


@pytest.mark.parametrize("route", ["legacy", "relational"])
def test_profiles_require_their_explicit_native_validation_route(base, relational_base, route):
    captured, relational = relational_base
    data, legacy = base
    with patch.object(native, "_owners", side_effect=AssertionError("operation owners reached")):
        with pytest.raises(ValueError):
            if route == "legacy":
                validate(data, relational)
            else:
                validate_relational(captured, legacy)


@pytest.mark.parametrize("damage", ["roles", "request", "profile"])
def test_relational_original_replay_refuses_before_compiler_probe(
        relational_base, monkeypatch, tmp_path, damage):
    original, preparation = relational_base
    report, request_raw = deepcopy(original)
    if damage == "roles":
        report["argument_roles"][0]["roles"].reverse()
    elif damage == "request":
        request = json.loads(request_raw)
        request["argument_roles"][0]["roles"].reverse()
        request_raw = canonical(request)
    else:
        manifest = meta(preparation)
        manifest["profile"] = preparer.PROFILE
        preparation = reseal_manifest(preparation, manifest)
    monkeypatch.setattr(native, "_installed_toolchain", lambda *a, **k: pytest.fail("probe reached before replay"))
    monkeypatch.setattr(process.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("runner reached before replay"))
    output = tmp_path / "must-not-export-relational"
    with pytest.raises(ValueError):
        build_relational((report, request_raw), preparation, tmp_path / "never-executed", output)
    assert not output.exists()


@pytest.mark.parametrize("field", ["report", "request"])
def test_relational_inputs_are_replayed_after_the_original_runner(
        relational_base, synthetic_compiler, tmp_path, field):
    original, preparation = relational_base
    captured = deepcopy(original)
    report, request_raw = captured
    if field == "report":
        def mutate():
            report["argument_roles"][0]["roles"].reverse()
    else:
        def mutate():
            report["request_raw_utf8"] = request_raw.decode() + " "
    executable, _ = synthetic_compiler(preparation, after=mutate)
    receipt = build_relational(captured, preparation, executable, tmp_path / "changed-relational-input")
    assert receipt["build_passed"] is False
    assert receipt["native_observations"]["post_run_validation_passed"] is False
    assert receipt["relational_report_sha256"] == meta(preparation)["relational_report_sha256"]
    assert_no_authority(receipt)


def test_legacy_and_relational_operation_pins_have_separate_stable_profiles(
        base, relational_base, monkeypatch):
    data, legacy = base
    captured, relational = relational_base
    monkeypatch.setattr(native, "_OPERATION_PINS", {})
    assert validate(data, legacy) == legacy
    original = deepcopy(native._OPERATION_PINS[preparer.PROFILE])
    assert validate_relational(captured, relational) == relational
    assert validate(data, legacy) == legacy
    assert set(native._OPERATION_PINS) == {preparer.PROFILE, preparer.RELATIONAL_PROFILE}
    assert native._OPERATION_PINS[preparer.PROFILE] == original


def test_relational_cleanup_exception_retains_original_handle_and_profile(
        relational_base, synthetic_compiler, monkeypatch, tmp_path):
    captured, preparation = relational_base
    executable, _ = synthetic_compiler(preparation)
    handle = object()
    original = process.OwnedToolCleanupError(handle, "synthetic unresolved relational cleanup")
    def fail(self, request, *, cancellation=None):
        assert request.owned_process_observation is True
        raise original
    monkeypatch.setattr(process.BoundedToolRunner, "run", fail)
    output = tmp_path / "retained-relational-cleanup"
    with pytest.raises(process.OwnedToolCleanupError) as caught:
        build_relational(captured, preparation, executable, output)
    assert caught.value is original and caught.value.cleanup_handle is handle
    receipt = json.loads((output / "build-receipt.json").read_bytes())
    assert receipt["profile"] == native.RELATIONAL_PROFILE
    assert receipt["native_observations"]["cleanup_owner_retained_on_exception"] is True
    assert receipt["build_passed"] is False
    assert receipt["original_request_sha256"] == meta(preparation)["original_request_sha256"]
    assert_no_authority(receipt)


@pytest.fixture(scope="module")
def counted_base():
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    request_raw = canonical(counted.authored_counted_frame_request())
    report = counted.prepare_counted_frame(request_raw, expected_request_sha256=sha(request_raw))
    preparation = preparer.prepare_counted_ast_preservation(
        report, request_raw, expected_report_sha256=sha(canonical(report)),
        expected_request_sha256=sha(request_raw), toolchain=TOOLCHAIN)
    return (report, request_raw), preparation


def validate_counted(captured, preparation, **overrides):
    report, request_raw = captured
    return native.validate_counted_ast_preservation(
        preparation, report, request_raw,
        **(relational_arguments(captured, preparation) | overrides))


def build_counted(captured, preparation, executable, output, **overrides):
    report, request_raw = captured
    return native.build_counted_ast_preservation(
        preparation, report, request_raw,
        **(relational_arguments(captured, preparation) | {
            "lake_executable": str(executable), "output_directory": output,
            "timeout_seconds": 12,
        } | overrides))


def test_counted_native_profile_retains_sorted_AST_and_boundary_evidence_without_native_fragment(
        counted_base, synthetic_compiler, tmp_path):
    captured, preparation = counted_base
    before = deepcopy(captured)
    assert validate_counted(captured, preparation) == preparation
    executable, calls = synthetic_compiler(preparation)
    receipt = build_counted(captured, preparation, executable, tmp_path / "counted-native")
    manifest, observed = meta(preparation), receipt["native_observations"]
    assert len(calls) == 1
    assert receipt["profile"] == native.COUNTED_PROFILE
    assert receipt["profile"] not in {native.PROFILE, native.RELATIONAL_PROFILE}
    assert len(observed["compiled_modules"]) == 4
    assert len(observed["executed_project_sha256"]) == 7
    assert observed["theorem_axiom_dependencies"] == {name: [] for name in manifest["theorems"]}
    assert len(observed["theorem_axiom_dependencies"]) == 5
    assert receipt["typed_ast_value_preservation_proved"] is True
    assert receipt["counted_ast_denotation_preservation_proved"] is True
    assert receipt["counted_boundary_counterexamples_checked"] is True
    assert receipt["native_ast_value_preservation_proved"] is False
    assert receipt["native_TDFOL_route_used"] is False
    for field in ("counted_report_sha256", "original_request_sha256", "typed_expression_sha256",
                  "typed_expression_content_digest", "lean_body_sha256", "typed_ast_node_count"):
        assert receipt[field] == manifest[field]
    for field in ("original_fragment_file_sha256", "original_fragment_canonical_sha256", "native_ast_sha256"):
        assert field not in receipt
    assert captured == before
    assert_no_authority(receipt)


@pytest.mark.parametrize("index", range(5))
def test_each_counted_obligation_including_both_cap_witnesses_requires_its_own_report(
        counted_base, synthetic_compiler, tmp_path, index):
    captured, preparation = counted_base
    lines = axiom_stdout(preparation).splitlines()
    lines.pop(index)
    executable, _ = synthetic_compiler(preparation, stdout="\n".join(lines) + "\n")
    receipt = build_counted(captured, preparation, executable, tmp_path / "missing-counted-theorem")
    assert receipt["build_passed"] is False
    assert receipt["typed_ast_value_preservation_proved"] is False
    assert receipt["counted_ast_denotation_preservation_proved"] is False
    assert receipt["counted_boundary_counterexamples_checked"] is False
    assert_no_authority(receipt)


@pytest.mark.parametrize("field", [
    "expected_preparation_sha256", "expected_report_sha256", "expected_request_sha256",
])
def test_counted_independent_commitments_precede_lazy_owners(counted_base, field):
    captured, preparation = counted_base
    with patch.object(native, "_owners", side_effect=AssertionError("operation owners reached")):
        with pytest.raises(ValueError):
            validate_counted(captured, preparation, **{field: "0" * 64})


def test_counted_profile_cannot_reuse_relational_theorem_names(counted_base):
    _, preparation = counted_base
    manifest = meta(preparation)
    manifest["theorems"] = [manifest["expected_modules"][2] + "." + suffix for suffix in (
        "native_value_exact", "native_ast_closed", "denotation_matches_native",
        "typed_source_lowering_exact", "role_denotation_matches_native")]
    with pytest.raises(ValueError):
        native._axiom_observations("", "", manifest)


def test_counted_report_is_replayed_after_the_original_runner(counted_base, synthetic_compiler, tmp_path):
    original, preparation = counted_base
    captured = deepcopy(original)
    def mutate():
        captured[0]["maximum"] = 4
    executable, _ = synthetic_compiler(preparation, after=mutate)
    receipt = build_counted(captured, preparation, executable, tmp_path / "changed-counted-report")
    assert receipt["native_observations"]["post_run_validation_passed"] is False
    assert receipt["typed_ast_value_preservation_proved"] is False
    assert receipt["counted_boundary_counterexamples_checked"] is False
    assert_no_authority(receipt)


def test_three_preservation_profiles_have_separate_pin_caches(base, relational_base, counted_base, monkeypatch):
    data, legacy = base
    relational_data, relational = relational_base
    counted_data, counted = counted_base
    monkeypatch.setattr(native, "_OPERATION_PINS", {})
    assert validate(data, legacy) == legacy
    assert validate_relational(relational_data, relational) == relational
    assert validate_counted(counted_data, counted) == counted
    assert validate(data, legacy) == legacy
    assert validate_relational(relational_data, relational) == relational
    assert set(native._OPERATION_PINS) == {preparer.PROFILE, preparer.RELATIONAL_PROFILE, preparer.COUNTED_PROFILE}


def test_counted_cleanup_preserves_exception_without_fabricated_native_fragment(
        counted_base, synthetic_compiler, monkeypatch, tmp_path):
    captured, preparation = counted_base
    executable, _ = synthetic_compiler(preparation)
    handle = object()
    original = process.OwnedToolCleanupError(handle, "synthetic unresolved counted cleanup")
    def fail(self, request, *, cancellation=None):
        raise original
    monkeypatch.setattr(process.BoundedToolRunner, "run", fail)
    output = tmp_path / "retained-counted-cleanup"
    with pytest.raises(process.OwnedToolCleanupError) as caught:
        build_counted(captured, preparation, executable, output)
    assert caught.value is original and caught.value.cleanup_handle is handle
    receipt = json.loads((output / "build-receipt.json").read_bytes())
    assert receipt["profile"] == native.COUNTED_PROFILE
    assert receipt["native_observations"]["cleanup_owner_retained_on_exception"] is True
    assert receipt["typed_ast_value_preservation_proved"] is False
    assert receipt["counted_ast_denotation_preservation_proved"] is False
    assert receipt["counted_boundary_counterexamples_checked"] is False
    assert "original_fragment_file_sha256" not in receipt and "native_ast_sha256" not in receipt
    assert_no_authority(receipt)


def _installed_lean_campaign_binaries():
    """Explicit opt-in: missing/mismatched tools are failures when enabled."""
    if os.environ.get("IPFS_DATASETS_RUN_NATIVE_LEAN") != "1":
        pytest.skip("set IPFS_DATASETS_RUN_NATIVE_LEAN=1 for actual Lean checks")
    spelling = os.environ.get("IPFS_DATASETS_NATIVE_LAKE_TEST_EXECUTABLE")
    assert type(spelling) is str and spelling, "explicit installed native Lake ELF path required"
    executable = Path(spelling)
    assert executable.is_absolute() and executable.resolve(strict=True) == executable
    lean = executable.with_name("lean")
    assert lean.resolve(strict=True) == lean
    assert TOOLCHAIN == "leanprover/lean4:v4.34.1"
    pins = {}
    for path in (executable, lean):
        assert path.is_file() and not path.is_symlink(), "real sibling native ELF tools required"
        raw = path.read_bytes()
        assert raw[:4] == b"\x7fELF", "elan wrappers are not native Lean tools"
        pins[str(path)] = sha(raw)
    return executable, pins


def _assert_installed_lean_preservation(receipt, preparation, executable, binaries, profile):
    """Check genuine owner observations; no compiler/process stubs are used."""
    manifest, observed = meta(preparation), receipt["native_observations"]
    assert receipt["profile"] == profile
    assert receipt["build_passed"] is receipt["kernel_proofs_checked"] is True
    assert observed["native_runtime_verified"] is True
    assert observed["runtime"] == "native"
    assert type(observed["pid"]) is int and observed["pid"] > 0
    assert observed["command"] == [str(executable), "--offline", "--no-cache", "build", "legal"]
    assert observed["binary_sha256"] == binaries
    assert observed["binaries_unchanged"] is True
    for name, path in (("lake", executable), ("lean", executable.with_name("lean"))):
        probe = observed["version_probes"][name]
        assert probe["command"] == [str(path), "--version"] and probe["returncode"] == 0
        assert "4.34.1" in probe["stdout"]
        assert sha(path.read_bytes()) == binaries[str(path)]
    assert observed["cleanup_confirmed"] is observed["observed_process_scope_passed"] is True
    assert observed["native_lifecycle"]["parent"]["pid"] == os.getpid()
    assert observed["native_lifecycle"]["leader"]["pid"] == observed["pid"]
    assert observed["native_lifecycle"]["leader_reaped"] is True
    assert observed["manifest_coverage_passed"] is True
    assert observed["executed_project_readback_passed"] is True
    assert observed["post_run_validation_passed"] is True
    assert observed["compiled_modules"] == manifest["expected_modules"]
    assert len(observed["artifact_sha256"]) == 4 and all(observed["artifact_bytes"].values())
    assert len(observed["executed_project_sha256"]) == 7
    assert len(manifest["theorems"]) == 5
    assert observed["theorem_axiom_dependencies"] == {name: [] for name in manifest["theorems"]}
    assert observed["axiom_observations_passed"] is True
    assert observed["axiom_observation_errors"] == []
    assert_no_authority(receipt)


@pytest.mark.parametrize("operator", ["O", "P", "F"])
def test_installed_lean_relational_preservation(operator, relational_preservation_fixtures, tmp_path):
    """Actual O/P/F builds retain multiargument roles, exists and an exception."""
    executable, binaries = _installed_lean_campaign_binaries()
    fixtures = relational_preservation_fixtures
    builder = fixtures.Builder()
    approval = builder.atom("Approved", "approver", "actor", "recipient")
    exception = fixtures.ast.mk_not(builder.nid(), builder.atom("Exempt", "actor"))
    guard = builder.binary("and", approval, exception)
    action = builder.atom("Assign", "actor", "recipient")
    body = builder.binary("implies", guard, builder.modal(operator, action))
    request = fixtures.request_for(builder, body, [
        ("Approved", ("approver", "actor", "recipient")),
        ("Exempt", ("actor",)), ("Assign", ("actor", "recipient")),
    ], [("actor", "forall"), ("recipient", "exists"), ("approver", "forall")])
    captured = _FIXTURE._relational_preservation_capture(fixtures, request)
    preparation = _FIXTURE._prepare_relational_preservation(captured)
    receipt = build_relational(captured, preparation, executable,
        tmp_path / ("installed-relational-" + operator), timeout_seconds=45)
    _assert_installed_lean_preservation(receipt, preparation, executable, binaries, native.RELATIONAL_PROFILE)
    assert receipt["native_ast_value_preservation_proved"] is True


def test_installed_lean_counted_preservation(counted_base, tmp_path):
    """Actual sorted cap-three denotation and genuine Fin3/Fin4 witnesses."""
    executable, binaries = _installed_lean_campaign_binaries()
    captured, preparation = counted_base
    receipt = build_counted(captured, preparation, executable,
        tmp_path / "installed-counted-three", timeout_seconds=45)
    _assert_installed_lean_preservation(receipt, preparation, executable, binaries, native.COUNTED_PROFILE)
    suffixes = [name.rsplit(".", 1)[1] for name in meta(preparation)["theorems"]]
    assert suffixes[-2:] == ["cap_two_counterexample", "cap_four_counterexample"]
    assert receipt["typed_ast_value_preservation_proved"] is True
    assert receipt["counted_ast_denotation_preservation_proved"] is True
    assert receipt["counted_boundary_counterexamples_checked"] is True
    assert receipt["native_ast_value_preservation_proved"] is False
    assert receipt["native_TDFOL_route_used"] is False
