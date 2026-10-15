"""Conditional V2 build custody with real replay and synthetic process results.

The authored donor/consumer sources, review signatures and six-module preparation
use their actual owners. Only installed-toolchain discovery and the shared tool
runner are replaced. Fake PIDs, artifacts and Lean messages below test adapter
boundaries; they qualify no native theorem, statutory meaning or human review.
All retained test objects are ordinary files and directories.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as preparer
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_native_v2 as native
from ipfs_datasets_py.logic.backends import process


_SPEC = importlib.util.spec_from_file_location(
    "_authored_combined_v2_native_build_fixture",
    Path(__file__).with_name("test_legal_corpus_definition_use_lake_v2.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)

TOOLCHAIN = "leanprover/lean4:v4.34.1"
PREVIEW_BYTES = 32768
FALSE_AUTHORITY = (
    "source_semantics_verified", "source_authenticity_verified",
    "applicability_verified", "context_closure_verified", "independently_reviewed",
    "admitted", "formalized", "proof_authority", "training_qualified",
    "training_gold_qualified", "model_executed", "learned_translation",
    "semantic_definition_binding_verified", "per_occurrence_lookup_verified",
    "accepted_view_eligible", "combined_use_review_verified",
    "translation_preservation_proved", "human_identity_verified",
    "human_independence_verified", "legal_dependency_inventory_exhaustive",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def original_data(family="fol"):
    data = _FIXTURE.assessment_data(family)
    preparation = preparer.prepare_definition_use_corpus_v2(**_FIXTURE.arguments(data))
    return data, preparation


@pytest.fixture(scope="module")
def base():
    return original_data()


def arguments(data, preparation):
    return {
        "expected_preparation_sha256": native.preparation_sha256(preparation),
        "expected_assessment_file_sha256": data["expected_assessment_file_sha256"],
        "review_inputs": data["review_inputs"],
        "toolchain": data["toolchain"],
    }


def validate(data, preparation, **overrides):
    return native.validate_definition_use_native_v2(
        preparation, data["assessment_raw"], **(arguments(data, preparation) | overrides)
    )


def build(data, preparation, executable, output, **overrides):
    return native.build_definition_use_native_v2(
        preparation, data["assessment_raw"],
        **(arguments(data, preparation) | {
            "lake_executable": str(executable), "output_directory": output,
            "timeout_seconds": 12,
        } | overrides),
    )


def reseal_manifest(preparation, manifest, files=None):
    files = dict(preparation.files) if files is None else files
    manifest["file_sha256"] = {
        name: sha(text.encode("utf-8")) for name, text in sorted(files.items())
    }
    sealed = contracts.seal_record({
        key: value for key, value in manifest.items()
        if key not in {"record_cid", "cid_scope"}
    })
    return replace(
        preparation, manifest_json=canonical(sealed).decode("utf-8"),
        files=tuple(sorted(files.items())),
    )


def identity(pid=123, *, process_group_id=123, session_id=123, parent_pid=None):
    return process.NativeProcessIdentity(
        pid=pid, birth_ticks=1,
        parent_pid=os.getpid() if parent_pid is None else parent_pid,
        process_group_id=process_group_id, session_id=session_id,
    )


def lifecycle(**overrides):
    values = {
        "parent_pid": os.getpid(), "parent_birth_ticks": 1, "leader": identity(),
        "observed_descendants": (), "leader_reaped": True,
        "descendant_tracking_complete": True, "group_scan_complete": True,
        "remaining_group_members": (), "remaining_tracked_descendants": (),
        "readers_started": 2, "readers_joined": 2,
        "stdin_writer_started": 0, "stdin_writer_joined": 0,
        "workspace_device": 1, "workspace_inode": 1, "workspace_removed": True,
    }
    return process.NativeToolLifecycleObservation(**(values | overrides))


def axiom_stdout(preparation):
    return "\n".join(
        "'" + name + "' does not depend on any axioms"
        for name in preparation.to_dict()["conditional_theorems"]
    ) + "\n"


@pytest.fixture
def synthetic_compiler(monkeypatch, tmp_path):
    """Stub exactly the toolchain boundary and runner; never replay owners."""
    executable = tmp_path / "synthetic-lake"
    executable.write_bytes(b"explicit synthetic unit binary; never executed")
    compiler = tmp_path / "synthetic-lean"
    compiler.write_bytes(b"explicit synthetic sibling compiler; never executed")
    binary_pins = {
        str(path): sha(path.read_bytes()) for path in (executable, compiler)
    }
    monkeypatch.setattr(
        native, "_installed_toolchain",
        lambda *args, **kwargs: (executable, binary_pins, {}),
    )
    calls = []

    def install(preparation, *, result_changes=None, output_edit=None, after=None,
                stdout=None, cancellation=None):
        modules = preparation.to_dict()["expected_modules"]
        artifacts = tuple(
            ".lake/build/lib/lean/" + name.replace(".", "/") + ".olean"
            for name in modules
        )
        expected_sources = dict(preparation.files)

        def synthetic_run(self, request, *, cancellation=None):
            calls.append(request)
            assert request.argv == (
                str(executable), "--offline", "--no-cache", "build", "legal",
            )
            assert request.runtime is process.ToolRuntime.NATIVE
            assert request.owned_process_observation is True
            assert request.environment["ELAN_TOOLCHAIN"] == TOOLCHAIN
            assert request.environment["LEAN_NUM_THREADS"] == "1"
            assert request.limits.timeout_seconds == 12
            assert request.limits.max_output_files == 15
            assert request.limits.max_output_bytes == 2 * 1024**2
            assert request.limits.resident_memory_bytes == 2 * 1024**3
            assert request.limits.max_workspace_bytes == 128 * 1024**2
            assert request.output_paths == artifacts + tuple(sorted(expected_sources))
            assert dict(request.input_files) == expected_sources
            assert cancellation is expected_cancellation
            outputs = {
                name: b"synthetic olean bytes; no native proof evidence"
                for name in artifacts
            }
            outputs.update({name: text.encode("utf-8") for name, text in expected_sources.items()})
            if output_edit is not None:
                output_edit(outputs, artifacts, tuple(sorted(expected_sources)))
            if after is not None:
                after()
            values = {
                "interface_version": "synthetic-unit-boundary/v1",
                "runtime": process.ToolRuntime.NATIVE, "command": request.argv,
                "returncode": 0, "stdout": axiom_stdout(preparation) if stdout is None else stdout,
                "stderr": "", "elapsed_seconds": 0.01,
                "output_files": outputs, "pid": 123,
                "native_lifecycle": lifecycle(), "workspace_cleaned": True,
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
    assert receipt["ownership_is_sampled"] is True
    assert receipt["kernel_containment_attested"] is False


def test_public_import_uses_only_stdlib_without_operation_owners():
    code = r"""
import importlib.util,sys
blocked=('ipfs_datasets_py','torch','transformers','tensorflow','numpy','multiformats','cryptography','pyarrow','requests')
class Deny:
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==name or fullname.startswith(name+'.') for name in blocked):
            raise AssertionError('production owner reached: '+fullname)
sys.meta_path.insert(0,Deny())
spec=importlib.util.spec_from_file_location('_conditional_v2_native_cold',sys.argv[1])
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)
for name in ('preparation_sha256','validate_definition_use_native_v2','build_definition_use_native_v2','compilation_receipt_sha256'):
    assert callable(getattr(module,name))
assert not any(any(name==prefix or name.startswith(prefix+'.') for prefix in blocked) for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", code, native.__file__],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_exact_native_handoff_retains_full_conditional_preparation_and_original_authority(
    family, synthetic_compiler, tmp_path
):
    data, preparation = original_data(family)
    before = deepcopy(data["review_inputs"])
    original_manifest = preparation.manifest_json
    assert validate(data, preparation) == preparation
    token = process.CancellationToken()
    executable, calls = synthetic_compiler(preparation, cancellation=token)
    output = tmp_path / "conditional-project"
    receipt = build(data, preparation, executable, output, cancellation=token)
    manifest = preparation.to_dict()
    assert len(calls) == 1
    assert receipt["schema"] == "legal-corpus-v2-definition-use-native-build/v1"
    assert receipt["profile"] == "replayed-v2-definition-use-conditional-native-build/v1"
    assert receipt["preparation_full_canonical_sha256"] == native.preparation_sha256(preparation)
    assert receipt["preparation_manifest_sha256"] == sha(preparation.manifest_json.encode("utf-8"))
    assert receipt["assessment_file_sha256"] == data["expected_assessment_file_sha256"]
    assert receipt["review_intake_binding"] == manifest["review_intake_binding"]
    assert receipt["build_passed"] is True
    assert receipt["lean_compilation_verified"] is True
    for name in ("proof_checked", "kernel_proofs_checked", "conditional_proofs_verified"):
        assert receipt[name] is True
    assert receipt["native_runtime_verified"] is True
    assert receipt["cleanup_confirmed"] is True
    assert receipt["observed_process_scope_passed"] is True
    assert receipt["process_tree_terminated"] is False
    assert receipt["expected_modules"] == receipt["compiled_modules"] == manifest["expected_modules"]
    assert len(receipt["artifact_sha256"]) == 6
    assert len(receipt["executed_project_sha256"]) == 9
    assert receipt["theorem_axiom_dependencies"] == {
        name: [] for name in manifest["conditional_theorems"]
    }
    assert receipt["original_preparation_theorem_assumptions"] == manifest["theorem_assumptions"]
    assert receipt["theorem_assumptions"] == [
        text for text in manifest["theorem_assumptions"]
        if text != "Modular joint equivalence is a generated definitional obligation; native kernel checking has not run."
    ]
    assert receipt["manifest_coverage_passed"] is True
    assert receipt["executed_project_readback_passed"] is True
    assert receipt["post_run_validation_passed"] is True
    assert receipt["binaries_unchanged"] is True
    assert_no_authority(receipt)
    for name, text in preparation.files:
        raw = text.encode("utf-8")
        assert (output / "project" / name).read_bytes() == raw
        assert (output / "executed-inputs" / name).read_bytes() == raw
    assert (output / "project" / "corpus-manifest.json").read_bytes() == original_manifest.encode("utf-8")
    assert json.loads((output / "build-receipt.json").read_bytes()) == receipt
    assert len((output / "build-receipt.json").read_bytes()) <= 1024**2
    for name, path in receipt["artifact_files"].items():
        raw = (output / path).read_bytes()
        assert sha(raw) == receipt["artifact_sha256"][name]
    assert data["review_inputs"] == before
    assert preparation.manifest_json == original_manifest
    assert manifest["execution_handoff"]["build_eligible"] is False
    assert manifest["preparation_only"] is True
    assert manifest["review_source_binding"]["alias_record"]["assumed_not_proved"] is True
    assert all(value is False for value in receipt["authority"].values())


@pytest.mark.parametrize("damage", ["manifest", "files"])
def test_mutation_of_original_preparation_cannot_rewrite_retained_executed_project(
    base, synthetic_compiler, tmp_path, damage
):
    data, original = base
    preparation = replace(original)
    original_manifest, original_files = original.manifest_json, original.files

    def mutate():
        if damage == "manifest":
            manifest = preparation.to_dict()
            manifest["theorem_assumptions"] = []
            changed = reseal_manifest(preparation, manifest)
            object.__setattr__(preparation, "manifest_json", changed.manifest_json)
        else:
            files = dict(preparation.files)
            files["LegalCorpusV2.lean"] += "\n-- changed after invocation\n"
            object.__setattr__(preparation, "files", tuple(sorted(files.items())))

    executable, _ = synthetic_compiler(preparation, after=mutate)
    output = tmp_path / "post-preparation-mutation"
    receipt = build(data, preparation, executable, output)
    assert receipt["post_run_validation_passed"] is False
    assert receipt["original_preparation_unchanged"] is False
    assert receipt["build_passed"] is False
    assert (output / "project" / "corpus-manifest.json").read_bytes() == original_manifest.encode("utf-8")
    for name, text in original_files:
        assert (output / "project" / name).read_bytes() == text.encode("utf-8")
        assert (output / "executed-inputs" / name).read_bytes() == text.encode("utf-8")
    assert original.manifest_json == original_manifest and original.files == original_files
    assert_no_authority(receipt)


@pytest.mark.parametrize("index", range(6))
def test_each_compiled_module_is_required_even_when_other_outputs_and_axioms_exist(
    base, synthetic_compiler, tmp_path, index
):
    data, preparation = base
    executable, _ = synthetic_compiler(
        preparation, output_edit=lambda outputs, artifacts, sources: outputs.pop(artifacts[index]),
    )
    receipt = build(data, preparation, executable, tmp_path / "missing-module")
    assert receipt["build_passed"] is False
    assert receipt["manifest_coverage_passed"] is False
    assert receipt["conditional_proofs_verified"] is False
    assert_no_authority(receipt)


@pytest.mark.parametrize("index", range(9))
def test_each_executed_input_requires_exact_returned_source_bytes(
    base, synthetic_compiler, tmp_path, index
):
    data, preparation = base
    executable, _ = synthetic_compiler(
        preparation,
        output_edit=lambda outputs, artifacts, sources: outputs.__setitem__(sources[index], b"changed source"),
    )
    receipt = build(data, preparation, executable, tmp_path / "changed-input")
    assert receipt["build_passed"] is False
    assert receipt["executed_project_readback_passed"] is False
    assert receipt["conditional_proofs_verified"] is False
    assert_no_authority(receipt)


@pytest.mark.parametrize("damage", ["empty_nonfirst", "extra_artifact", "missing_source"])
def test_nonempty_closed_output_population_is_required(base, synthetic_compiler, tmp_path, damage):
    data, preparation = base

    def edit(outputs, artifacts, sources):
        if damage == "empty_nonfirst":
            outputs[artifacts[4]] = b""
        elif damage == "extra_artifact":
            outputs["unrequested.olean"] = b"foreign artifact"
        else:
            outputs.pop(sources[-1])

    executable, _ = synthetic_compiler(preparation, output_edit=edit)
    receipt = build(data, preparation, executable, tmp_path / "closed-population")
    assert receipt["manifest_coverage_passed"] is False
    assert receipt["build_passed"] is False
    assert_no_authority(receipt)


@pytest.mark.parametrize("damage", [
    "missing", "duplicate", "unknown", "nonempty_axioms", "wrong_qualification",
    "unquoted", "inline_claim", "wrong_module_prefix", "stderr_claim", "sorry",
])
def test_three_exact_compiler_axiom_observations_cannot_be_inferred_or_forged(
    base, synthetic_compiler, tmp_path, damage
):
    data, preparation = base
    names = preparation.to_dict()["conditional_theorems"]
    lines = axiom_stdout(preparation).splitlines()
    changes = {}
    if damage == "missing":
        lines.pop(1)
    elif damage == "duplicate":
        lines.append(lines[0])
    elif damage == "unknown":
        lines.append("'Foreign.fake' does not depend on any axioms")
    elif damage == "nonempty_axioms":
        lines[1] = "'" + names[1] + "' depends on axioms: [Classical.choice]"
    elif damage == "wrong_qualification":
        lines[0] = "'consumer_predicate_iff_donor_body' does not depend on any axioms"
    elif damage == "unquoted":
        lines[0] = names[0] + " does not depend on any axioms"
    elif damage == "inline_claim":
        lines[0] = "untrusted arbitrary prefix " + lines[0]
    elif damage == "wrong_module_prefix":
        lines[0] = "info: LegalCorpusV2/Foreign.lean:1:0: " + lines[0]
    elif damage == "stderr_claim":
        changes["stderr"] = lines.pop(1) + "\n"
    else:
        lines.append("warning: declaration uses sorryAx")
    executable, _ = synthetic_compiler(
        preparation, stdout="\n".join(lines) + "\n", result_changes=changes,
    )
    receipt = build(data, preparation, executable, tmp_path / "axiom-refusal")
    assert receipt["build_passed"] is False
    assert receipt["conditional_proofs_verified"] is False
    assert receipt["kernel_proofs_checked"] is False
    assert_no_authority(receipt)


def test_exact_module_position_prefixed_lean_diagnostics_are_accepted(
    base, synthetic_compiler, tmp_path
):
    data, preparation = base
    lines = []
    for name in preparation.to_dict()["conditional_theorems"]:
        module = name.rsplit(".", 1)[0]
        path = module.replace(".", "/") + ".lean"
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
def test_native_process_success_cannot_be_inferred_from_outputs_and_zero_exit(
    base, synthetic_compiler, tmp_path, field, value
):
    data, preparation = base
    executable, _ = synthetic_compiler(preparation, result_changes={field: value})
    receipt = build(data, preparation, executable, tmp_path / "process-refusal")
    assert receipt["build_passed"] is False
    assert receipt["conditional_proofs_verified"] is False
    assert_no_authority(receipt)


@pytest.mark.parametrize("damage", [
    "absent", "dictionary", "wrong_leader", "leader_unreaped", "untracked",
    "unscanned", "live_group", "live_tracked", "unjoined_reader",
    "unjoined_stdin", "workspace_retained", "observation_error", "foreign_group",
    "foreign_session", "wrong_leader_group", "wrong_leader_session",
    "wrong_parent", "boolean_parent", "zero_parent_birth", "boolean_parent_birth",
    "float_parent_birth", "mismatched_leader_parent",
])
def test_typed_owned_cleanup_and_observed_process_scope_are_required(
    base, synthetic_compiler, tmp_path, damage
):
    data, preparation = base
    variations = {
        "wrong_leader": {"leader": identity(124)},
        "leader_unreaped": {"leader_reaped": False},
        "untracked": {"descendant_tracking_complete": False},
        "unscanned": {"group_scan_complete": False},
        "live_group": {"remaining_group_members": (identity(124),)},
        "live_tracked": {"remaining_tracked_descendants": (identity(124),)},
        "unjoined_reader": {"readers_joined": 1},
        "unjoined_stdin": {"stdin_writer_started": 1},
        "workspace_retained": {"workspace_removed": False},
        "observation_error": {"observation_errors": ("synthetic incomplete scan",)},
        "foreign_group": {"observed_descendants": (identity(124, process_group_id=124),)},
        "foreign_session": {"observed_descendants": (identity(124, session_id=124),)},
        "wrong_leader_group": {"leader": identity(process_group_id=124)},
        "wrong_leader_session": {"leader": identity(session_id=124)},
        "wrong_parent": {"parent_pid": os.getpid() + 1},
        "boolean_parent": {"parent_pid": True},
        "zero_parent_birth": {"parent_birth_ticks": 0},
        "boolean_parent_birth": {"parent_birth_ticks": True},
        "float_parent_birth": {"parent_birth_ticks": 1.0},
        "mismatched_leader_parent": {"leader": identity(parent_pid=os.getpid() + 1)},
    }
    observation = None if damage == "absent" else lifecycle(**variations.get(damage, {}))
    if damage == "dictionary":
        observation = observation.to_dict()
    executable, _ = synthetic_compiler(
        preparation, result_changes={"native_lifecycle": observation},
    )
    receipt = build(data, preparation, executable, tmp_path / "custody-refusal")
    assert receipt["build_passed"] is False
    assert receipt["conditional_proofs_verified"] is False
    if damage in {
        "foreign_group", "foreign_session", "wrong_leader_group", "wrong_leader_session",
        "wrong_parent", "boolean_parent", "zero_parent_birth", "boolean_parent_birth",
        "float_parent_birth", "mismatched_leader_parent",
    }:
        assert receipt["observed_process_scope_passed"] is False
    else:
        assert receipt["cleanup_confirmed"] is False
    assert_no_authority(receipt)


def test_clean_observed_descendant_and_normal_exit_need_no_forced_termination(
    base, synthetic_compiler, tmp_path
):
    data, preparation = base
    executable, _ = synthetic_compiler(preparation, result_changes={
        "native_lifecycle": lifecycle(observed_descendants=(identity(124),)),
    })
    receipt = build(data, preparation, executable, tmp_path / "clean-descendant")
    assert receipt["build_passed"] is True
    assert receipt["cleanup_confirmed"] is True
    assert receipt["process_tree_terminated"] is False
    assert_no_authority(receipt)


def test_binary_identity_is_rechecked_after_the_returned_process(
    base, synthetic_compiler, tmp_path
):
    data, preparation = base
    executable, _ = synthetic_compiler(preparation)
    synthetic_compiler(
        preparation, after=lambda: executable.write_bytes(b"changed synthetic binary"),
    )
    receipt = build(data, preparation, executable, tmp_path / "changed-binary")
    assert receipt["binaries_unchanged"] is False
    assert receipt["build_passed"] is False
    assert_no_authority(receipt)


@pytest.mark.parametrize("damage", ["original_source", "review", "dependency_observation"])
def test_full_original_inputs_are_regenerated_after_native_execution(
    base, synthetic_compiler, tmp_path, damage
):
    original, preparation = base
    data = deepcopy(original)

    def mutate():
        inputs = data["review_inputs"]
        if damage == "original_source":
            donor = inputs["use_inputs"]["donor_evidence_inputs"]["candidate_inputs"]
            donor["raw_html"] += b"\nchanged after process"
        elif damage == "review":
            inputs["reviews"][0]["interpretation"]["rationale"] += " changed after process"
        else:
            key = next(iter(inputs["observed_artifact_sha256s"]))
            inputs["observed_artifact_sha256s"][key] = "0" * 64

    executable, _ = synthetic_compiler(preparation, after=mutate)
    receipt = build(data, preparation, executable, tmp_path / "post-run-replay")
    assert receipt["post_run_validation_passed"] is False
    assert receipt["build_passed"] is False
    assert receipt["conditional_proofs_verified"] is False
    assert_no_authority(receipt)


@pytest.mark.parametrize("damage", ["source", "review", "component", "assessment", "preparation"])
def test_original_replay_failures_refuse_before_toolchain_or_process(
    base, monkeypatch, tmp_path, damage
):
    original, preparation = base
    data = deepcopy(original)
    if damage == "source":
        inputs = data["review_inputs"]["use_inputs"]["donor_evidence_inputs"]["candidate_inputs"]
        inputs["raw_html"] += b" changed original source"
    elif damage == "review":
        data["review_inputs"]["reviews"][0]["interpretation"]["rationale"] += " unsigned change"
    elif damage == "component":
        inputs = data["review_inputs"]
        component = json.loads(inputs["component_raw"])
        component["alias_record"]["assumed_not_proved"] = False
        component = contracts.seal_record({k: v for k, v in component.items() if k not in {"record_cid", "cid_scope"}})
        inputs["component_raw"] = canonical(component)
        inputs["expected_component_pin"]["component_sha256"] = sha(inputs["component_raw"])
        inputs["expected_component_pin"]["component_cid"] = component["record_cid"]
    elif damage == "assessment":
        report = json.loads(data["assessment_raw"])
        report["alias_assumed_not_proved"] = False
        report["assessment_sha256"] = sha(canonical({k: v for k, v in report.items() if k != "assessment_sha256"}))
        data["assessment_raw"] = canonical(report)
        data["expected_assessment_file_sha256"] = sha(data["assessment_raw"])
    else:
        manifest = preparation.to_dict()
        manifest["theorem_assumptions"] = []
        preparation = reseal_manifest(preparation, manifest)
    monkeypatch.setattr(native, "_installed_toolchain", lambda *a, **k: pytest.fail("probe reached before replay"))
    monkeypatch.setattr(process.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("runner reached before replay"))
    output = tmp_path / "must-not-export"
    with pytest.raises(ValueError):
        build(data, preparation, tmp_path / "never-executed", output)
    assert not output.exists()


@pytest.mark.parametrize("damage", ["drop_alias_premise", "wrong_theorem", "drop_source", "drop_module", "authority"])
def test_resealed_preparation_cannot_change_conditional_source_or_obligation_population(base, damage):
    data, original = base
    manifest, files = original.to_dict(), dict(original.files)
    if damage == "drop_alias_premise":
        module = manifest["conditional_theorems"][0].rsplit(".", 1)[0]
        path = module.replace(".", "/") + ".lean"
        files[path] = files[path].replace("(hAlias : formula_0 i t)", "")
    elif damage == "wrong_theorem":
        manifest["conditional_theorems"][1] = "Foreign.fake"
    elif damage == "drop_source":
        files.pop("LegalCorpusV2.lean")
    elif damage == "drop_module":
        manifest["expected_modules"].pop(4)
    else:
        manifest["conditional_proofs_verified"] = True
    changed = reseal_manifest(original, manifest, files)
    with pytest.raises(ValueError):
        validate(data, changed)


@pytest.mark.parametrize("field,value", [
    ("expected_preparation_sha256", "0" * 64),
    ("expected_preparation_sha256", True),
    ("expected_assessment_file_sha256", "0" * 64),
    ("expected_assessment_file_sha256", "A" * 64),
    ("toolchain", "leanprover/lean4:latest"),
    ("toolchain", TOOLCHAIN + "\n"),
])
def test_independent_pins_and_toolchain_refuse_before_lazy_owners(base, field, value):
    data, preparation = base
    with patch.object(native, "_owners", side_effect=AssertionError("lazy owners reached")):
        with pytest.raises(ValueError):
            validate(data, preparation, **{field: value})


@pytest.mark.parametrize("damage", ["mutable_bytes", "oversize_assessment", "duplicate_key", "nonfinite", "review_metadata"])
def test_bounded_ordinary_inputs_refuse_before_lazy_operation_imports(base, damage):
    original, preparation = base
    data = deepcopy(original)
    if damage == "mutable_bytes":
        data["assessment_raw"] = bytearray(data["assessment_raw"])
    elif damage == "oversize_assessment":
        data["assessment_raw"] = b" " * (1024**2 + 1)
    elif damage == "duplicate_key":
        data["assessment_raw"] = b'{"schema":"a","schema":"b"}'
    elif damage == "nonfinite":
        data["assessment_raw"] = b'{"bad":NaN}'
    else:
        data["review_inputs"]["foreign_replay_field"] = None
    data["expected_assessment_file_sha256"] = sha(data["assessment_raw"])
    with patch.object(native, "_owners", side_effect=AssertionError("lazy owners reached")):
        with pytest.raises(ValueError):
            validate(data, preparation)


@pytest.mark.parametrize("timeout", [True, 0, -1, 61, float("nan"), float("inf")])
def test_invalid_execution_bounds_refuse_without_native_probe_or_export(base, tmp_path, timeout):
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
    retained = output / "retained.txt"
    retained.write_bytes(b"preserve exact evidence")
    monkeypatch.setattr(native, "_installed_toolchain", lambda *a, **k: pytest.fail("probe reached"))
    monkeypatch.setattr(process.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("runner reached"))
    with pytest.raises(ValueError):
        build(data, preparation, tmp_path / "lake", output)
    assert {path.name: path.read_bytes() for path in output.iterdir()} == {"retained.txt": b"preserve exact evidence"}


def test_full_bounded_logs_survive_while_receipt_previews_remain_small(
    base, synthetic_compiler, tmp_path
):
    data, preparation = base
    text = "x" * (PREVIEW_BYTES + 17) + "\n" + axiom_stdout(preparation)
    stderr = "z" * (PREVIEW_BYTES + 23)
    executable, _ = synthetic_compiler(preparation, stdout=text, result_changes={"stderr": stderr})
    output = tmp_path / "bounded-logs"
    receipt = build(data, preparation, executable, output)
    assert receipt["build_passed"] is True
    assert receipt["receipt_text_truncated"] is True
    assert receipt["stdout"] == text.encode()[:PREVIEW_BYTES].decode()
    assert receipt["stderr"] == stderr[:PREVIEW_BYTES]
    assert len((output / "build-receipt.json").read_bytes()) <= 1024**2
    expected = {"stdout.txt": text.encode(), "stderr.txt": stderr.encode(), "runner-error.txt": b""}
    for name, raw in expected.items():
        assert (output / name).read_bytes() == raw
        assert receipt["log_sha256"][name] == sha(raw)
        assert receipt["log_bytes"][name] == len(raw)
    assert_no_authority(receipt)


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_valid_blocked_reviews_retain_their_outcome_after_conditional_build(
    base, synthetic_compiler, tmp_path, status
):
    original, _ = base
    signed = deepcopy(original["signed"])
    if status == "pending":
        signed["registry"]["mode"] = signed["policy"]["mode"] = "unavailable"
        signed["registry"]["keys"] = []
        signed["reviews"] = []
        _FIXTURE._COMBINED._REVIEW.refresh(signed)
    else:
        signed["reviews"][0]["interpretation"]["rationale"] += " unsigned change"
    data = _FIXTURE.refresh_assessment(signed)
    preparation = preparer.prepare_definition_use_corpus_v2(**_FIXTURE.arguments(data))
    original_manifest = preparation.manifest_json
    executable, _ = synthetic_compiler(preparation)
    receipt = build(data, preparation, executable, tmp_path / "blocked-review-build")
    assert receipt["build_passed"] is True
    assert receipt["review_evidence_status"] == data["assessment"]["evidence_assessment_status"]
    assert receipt["review_blockers"] == data["assessment"]["blockers"]
    assert receipt["review_blockers"]
    assert receipt["original_preparation_build_eligible"] is False
    assert receipt["original_preparation_unchanged"] is True
    assert preparation.manifest_json == original_manifest
    assert_no_authority(receipt)


def test_utf8_preview_boundary_and_nul_escaping_preserve_complete_raw_log(
    base, synthetic_compiler, tmp_path
):
    data, preparation = base
    text = "header\x00\n" + "é" * PREVIEW_BYTES + "\n" + axiom_stdout(preparation)
    executable, _ = synthetic_compiler(preparation, stdout=text)
    output = tmp_path / "utf8-logs"
    receipt = build(data, preparation, executable, output)
    raw = text.encode("utf-8")
    assert receipt["build_passed"] is True
    assert receipt["stdout"] == raw[:PREVIEW_BYTES].decode("utf-8", errors="replace").replace("\x00", "\\u0000")
    assert "\x00" not in receipt["stdout"]
    assert (output / "stdout.txt").read_bytes() == raw
    assert receipt["log_sha256"]["stdout.txt"] == sha(raw)
    assert receipt["log_bytes"]["stdout.txt"] == len(raw)
    assert receipt["receipt_text_truncated"] is True
    assert_no_authority(receipt)


def test_unresolved_native_cleanup_preserves_same_exception_and_handle(
    base, synthetic_compiler, monkeypatch, tmp_path
):
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
    assert caught.value is original
    assert caught.value.cleanup_handle is handle
    receipt = json.loads((output / "build-receipt.json").read_bytes())
    assert receipt["status"] == "owned_native_cleanup_unresolved"
    assert receipt["cleanup_owner_retained_on_exception"] is True
    assert receipt["cleanup_confirmed"] is False
    assert receipt["build_passed"] is False
    assert receipt["conditional_proofs_verified"] is False
    assert receipt["artifact_sha256"] == {}
    for flag in FALSE_AUTHORITY:
        assert receipt[flag] is False
    for name, text in preparation.files:
        assert (output / "project" / name).read_bytes() == text.encode("utf-8")
