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
            assert request.limits.max_output_files == len(modules) + len(expected_sources)
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


# The new complete-norm profile reuses the authored fixture and original native
# boundary. Synthetic observations below never supply real Lean proof evidence.
def bound_norm_native_data(mode="body_with_membership"):
    data, preparation = _FIXTURE.bound_norm_definition_data(mode)
    return data, preparation


def bound_norm_native_arguments(data, preparation):
    return {
        "expected_preparation_sha256": preparer.bound_norm_definition_preparation_sha256(preparation),
        "expected_bound_report_sha256": data["expected_bound_report_sha256"],
        "bound_definition_inputs": data["bound_definition_inputs"],
        "toolchain": data["toolchain"],
    }


def bound_norm_native_validate(data, preparation, **overrides):
    return native.validate_bound_norm_definition_native_v1(
        preparation, data["bound_report"],
        **(bound_norm_native_arguments(data, preparation) | overrides))


def bound_norm_native_build(data, preparation, executable, output, **overrides):
    return native.build_bound_norm_definition_native_v1(
        preparation, data["bound_report"],
        **(bound_norm_native_arguments(data, preparation) | {
            "lake_executable": str(executable), "output_directory": output,
            "timeout_seconds": 12,
        } | overrides))


@pytest.fixture(scope="module")
def bound_norm_native_base():
    return bound_norm_native_data()


@pytest.mark.parametrize("mode,theorem_count", [
    ("instance_only", 2), ("body_with_membership", 3),
])
def test_bound_norm_native_exact_mode_handoff_retains_frozen_originals(
        mode, theorem_count, synthetic_compiler, tmp_path):
    data, preparation = bound_norm_native_data(mode)
    original_inputs = deepcopy(data)
    assert native.preparation_sha256(preparation) == (
        preparer.bound_norm_definition_preparation_sha256(preparation))
    assert bound_norm_native_validate(data, preparation) == preparation
    executable, calls = synthetic_compiler(preparation)
    output = tmp_path / "complete-norm-project"
    receipt = bound_norm_native_build(data, preparation, executable, output)
    manifest = preparation.to_dict()
    assert len(calls) == 1 and receipt["build_passed"] is True
    assert receipt["schema"] == native.BOUND_NORM_BUILD_SCHEMA
    assert receipt["profile"] == native.BOUND_NORM_PROFILE
    assert len(receipt["conditional_theorems"]) == theorem_count
    assert receipt["theorem_axiom_dependencies"] == {
        name: [] for name in manifest["conditional_theorems"]}
    assert len(receipt["artifact_sha256"]) == 6
    assert len(receipt["executed_project_sha256"]) == 9
    assert receipt["bound_definition_report_sha256"] == data["expected_bound_report_sha256"]
    assert receipt["bound_definition_mode"] == mode
    assert receipt["original_input_commitment_sha256"] == manifest["original_input_commitment_sha256"]
    for key, pin in receipt["retained_manifest_field_sha256"].items():
        assert pin == sha(canonical(manifest[key])), key
    assert receipt["definition_alternatives_count"] == len(manifest["definition_alternatives"])
    assert receipt["nomination_inventory_count"] == len(manifest["nomination_inventory"])
    assert receipt["review_evidence_status"] == "unsigned_pending_source_meaning_and_applicability"
    assert receipt["review_blockers"] == manifest["review_blockers"]
    assert receipt["review_prerequisites_satisfied_under_selected_trust"] is False
    assert receipt["original_preparation_build_eligible"] is False
    for key in ("norm_truth_proved", "definition_applied_to_norm",
                "membership_assumption_verified", "source_adoption_verified",
                "governing_definition_use_verified"):
        assert receipt[key] is False, key
    assert receipt["theorem_assumptions"] == manifest["theorem_assumptions"]
    assert "complete unchanged norm" in receipt["scope"]
    assert_no_authority(receipt)
    for name, text in preparation.files:
        assert (output / "project" / name).read_text() == text
        assert (output / "executed-inputs" / name).read_bytes() == text.encode("utf-8")
    assert json.loads((output / "build-receipt.json").read_bytes()) == receipt
    assert native.bound_norm_definition_compilation_receipt_sha256(receipt) == sha(canonical(receipt))
    assert data == original_inputs


@pytest.mark.parametrize("failure", [
    "wrong_profile", "preparation_pin", "bound_report_pin", "extra_replay_input",
    "request_pin", "complete_input_bound",
])
def test_bound_norm_native_preflight_refuses_before_lazy_owners(
        bound_norm_native_base, monkeypatch, failure):
    data, preparation = bound_norm_native_base
    offered = deepcopy(data)
    kwargs = bound_norm_native_arguments(offered, preparation)
    if failure == "wrong_profile":
        manifest = preparation.to_dict()
        manifest["profile"] = preparer.PROFILE
        preparation = reseal_manifest(preparation, manifest)
        kwargs["expected_preparation_sha256"] = native.preparation_sha256(preparation)
    elif failure == "preparation_pin":
        kwargs["expected_preparation_sha256"] = "0" * 64
    elif failure == "bound_report_pin":
        kwargs["expected_bound_report_sha256"] = "0" * 64
    elif failure == "extra_replay_input":
        kwargs["bound_definition_inputs"]["unexpected"] = None
    elif failure == "request_pin":
        kwargs["bound_definition_inputs"]["expected_request_sha256"] = "0" * 64
    else:
        kwargs["bound_definition_inputs"]["companion_inputs"]["too_large"] = "x" * (49 * 1024**2)
    def forbidden():
        raise AssertionError("invalid native inputs reached replay owners")
    monkeypatch.setattr(native, "_owners", forbidden)
    with pytest.raises(ValueError):
        native.validate_bound_norm_definition_native_v1(
            preparation, offered["bound_report"], **kwargs)


def test_bound_norm_native_legacy_cache_remains_separate(
        bound_norm_native_base, base):
    old_data, old_preparation = base
    data, preparation = bound_norm_native_base
    assert validate(old_data, old_preparation) == old_preparation
    old_cache = dict(native._OPERATION_PINS)
    assert bound_norm_native_validate(data, preparation) == preparation
    bound_cache = dict(native._BOUND_NORM_OPERATION_PINS)
    assert native._OPERATION_PINS == old_cache
    assert bound_cache != old_cache
    assert validate(old_data, old_preparation) == old_preparation
    assert native._OPERATION_PINS == old_cache
    assert native._BOUND_NORM_OPERATION_PINS == bound_cache


@pytest.mark.parametrize("fault", ["artifact_missing", "source_changed", "input_changed", "missing_axiom"])
def test_bound_norm_native_failed_observation_retains_original_project(
        bound_norm_native_base, synthetic_compiler, tmp_path, fault):
    original_data, preparation = bound_norm_native_base
    before = deepcopy(original_data)
    data = deepcopy(original_data)
    kwargs = {}
    if fault == "artifact_missing":
        kwargs["output_edit"] = lambda outputs, artifacts, sources: outputs.pop(artifacts[0])
    elif fault == "source_changed":
        kwargs["output_edit"] = lambda outputs, artifacts, sources: outputs.__setitem__(
            sources[0], b"changed executed input")
    elif fault == "input_changed":
        kwargs["after"] = lambda: data["bound_definition_inputs"]["companion"].__setitem__(
            "selected_interpretation", "unsupported post-run caller mutation")
    else:
        kwargs["stdout"] = "\n".join(axiom_stdout(preparation).splitlines()[:-1]) + "\n"
    executable, calls = synthetic_compiler(preparation, **kwargs)
    output = tmp_path / "failed-complete-norm-project"
    receipt = bound_norm_native_build(data, preparation, executable, output)
    assert len(calls) == 1 and receipt["build_passed"] is False
    assert receipt["lean_compilation_verified"] is False
    assert receipt["conditional_proofs_verified"] is False
    assert receipt["status"] == "conditional_native_checks_failed"
    assert_no_authority(receipt)
    for name, text in preparation.files:
        assert (output / "project" / name).read_text() == text
    assert json.loads((output / "build-receipt.json").read_bytes()) == receipt
    if fault == "input_changed":
        assert receipt["post_run_validation_passed"] is False
    assert original_data == before



@pytest.fixture(scope="module")
def bound_norm_installed_lake():
    """Skip before constructing replay inputs unless original custody admits Lean."""
    value = os.environ.get("IPFS_DATASETS_BOUND_NORM_NATIVE_LAKE")
    if not value:
        pytest.skip("set IPFS_DATASETS_BOUND_NORM_NATIVE_LAKE for admitted installed Lean checks")
    executable = Path(value)
    archive = os.environ.get("IPFS_DATASETS_BOUND_NORM_NATIVE_ARCHIVE")
    if archive:
        expected_archive_install = Path.home() / ".elan" / "toolchains" / "leanprover--lean4---v4.34.1" / "bin" / "lake"
        if executable != expected_archive_install:
            raise ValueError("archive-backed Lean witness: canonical home toolchain path required")
        return _bound_norm_archive_native_witness(
            executable, Path(archive),
            expected_archive_sha256=_BOUND_NORM_AMD64_RELEASE_ARCHIVE_SHA256)
    expected = Path("/home/barberb/.elan/toolchains/leanprover--lean4---v4.34.1/bin/lake")
    assert executable.is_absolute() and executable == executable.resolve() == expected
    pins = {
        str(executable): "f80f50cbab5322e35bcb0bf88937e22e9d908b5e4e336e83ddfc30eb1506aacf",
        str(executable.parent / "lean"): "79fb1d26fa5a39385d59fdc48a711a14b0710ca6480271acce99b4d177cea085",
    }
    for name, pin in pins.items():
        path = Path(name)
        assert path.is_file() and not path.is_symlink()
        raw = path.read_bytes()
        assert raw.startswith(b"\x7fELF") and sha(raw) == pin
    return executable, pins


@pytest.fixture(scope="module")
def bound_norm_actual_project(bound_norm_installed_lake, tmp_path_factory):
    # The opt-in prerequisite resolves before this intentionally expensive
    # complete source/definition replay. The two cases share one positive build.
    executable, binary_pins = bound_norm_installed_lake
    data, preparation = bound_norm_native_data("body_with_membership")
    output = tmp_path_factory.mktemp("bound-norm-native", numbered=False) / "positive"
    receipt = native.build_bound_norm_definition_native_v1(
        preparation, data["bound_report"],
        **bound_norm_native_arguments(data, preparation),
        lake_executable=str(executable), output_directory=output, timeout_seconds=60)
    return data, preparation, output, receipt, executable, binary_pins


def test_bound_norm_native_installed_lean_three_conditional_theorems(bound_norm_actual_project):
    """One actual offline build plus the unchanged owner's two version probes."""
    data, preparation, output, receipt, executable, binary_pins = bound_norm_actual_project
    manifest = preparation.to_dict()
    assert receipt["build_passed"] is True, receipt
    assert receipt["runtime"] == "native" and receipt["native_runtime_verified"] is True
    assert type(receipt["pid"]) is int and receipt["pid"] > 0
    assert receipt["binary_sha256"] == binary_pins
    assert receipt["command"] == [str(executable), "--offline", "--no-cache", "build", "legal"]
    assert receipt["cleanup_confirmed"] is True
    assert receipt["observed_process_scope_passed"] is True
    assert receipt["original_preparation_unchanged"] is True
    assert receipt["post_run_validation_passed"] is True
    assert receipt["manifest_coverage_passed"] is True
    assert receipt["executed_project_readback_passed"] is True
    assert len(receipt["compiled_modules"]) == 6
    assert len(receipt["conditional_theorems"]) == 3
    assert receipt["theorem_axiom_dependencies"] == {
        name: [] for name in manifest["conditional_theorems"]}
    assert receipt["review_evidence_status"] == "unsigned_pending_source_meaning_and_applicability"
    assert receipt["review_prerequisites_satisfied_under_selected_trust"] is False
    assert receipt["original_preparation_build_eligible"] is False
    for key in ("norm_truth_proved", "definition_applied_to_norm",
                "membership_assumption_verified", "source_adoption_verified",
                "governing_definition_use_verified"):
        assert receipt[key] is False, key
    assert_no_authority(receipt)
    for name, text in preparation.files:
        assert (output / "project" / name).read_bytes() == text.encode("utf-8")
        assert (output / "executed-inputs" / name).read_bytes() == text.encode("utf-8")
    for module in manifest["expected_modules"]:
        assert (output / "compiled" / (module.replace(".", "/") + ".olean")).stat().st_size > 0
    for name, pin in receipt["log_sha256"].items():
        assert sha((output / name).read_bytes()) == pin
    assert json.loads((output / "build-receipt.json").read_bytes()) == receipt
    assert native.bound_norm_definition_compilation_receipt_sha256(receipt) == sha(canonical(receipt))


def test_bound_norm_native_installed_lean_norm_is_not_membership(bound_norm_actual_project):
    """A separate original-runner negative cannot turn hNorm into hMembership."""
    data, preparation, positive_output, positive, executable, binary_pins = bound_norm_actual_project
    assert positive["build_passed"] is True and positive["binary_sha256"] == binary_pins
    assert native._binary_recheck(binary_pins)
    manifest = preparation.to_dict()
    norm_module = next(row["module"] for row in manifest["native_fragments"] if row["role"] == "norm")
    definition_module = next(row["module"] for row in manifest["native_fragments"] if row["role"] == "definition")
    namespace = manifest["expected_modules"][-1]
    files = dict(preparation.files)
    root_name = namespace + ".lean"
    files[root_name] = (
        "import " + norm_module + "\nimport " + definition_module + "\n"
        "namespace " + namespace + "\nopen " + definition_module + "\n"
        "theorem invalid_norm_driven_body {Entity Agent : Type} "
        "(i : Interpretation Entity Agent) (t : Nat) (entity : Entity)\n"
        "    (hNorm : " + norm_module + ".formula_0 i t) "
        "(hDefinition : formula_0 i t) : bodyAt i entity t := by\n"
        "  exact (hDefinition entity).mp hNorm\n"
        "end " + namespace + "\n")
    for module in (manifest["expected_modules"][0], norm_module, definition_module):
        name = module.replace(".", "/") + ".lean"
        assert files[name] == dict(preparation.files)[name]
    # The production API must reject this forged project before discovering
    # toolchain or running a compiler; only this bounded negative control runs it.
    forged = reseal_manifest(preparation, manifest, files)
    with patch.object(native, "_installed_toolchain", side_effect=AssertionError("forged native dispatch")):
        with pytest.raises(ValueError):
            bound_norm_native_validate(data, forged,
                expected_preparation_sha256=native.preparation_sha256(forged))
    command = tuple(positive["command"])
    request = process.ToolRunRequest(
        argv=command, input_files=files, output_paths=tuple(sorted(files)),
        owned_process_observation=True,
        environment={"ELAN_TOOLCHAIN": TOOLCHAIN, "LEAN_NUM_THREADS": "1"},
        limits=process.ToolRunLimits(
            timeout_seconds=60, cpu_seconds=60, resident_memory_bytes=2 * 1024**3,
            max_output_bytes=2 * 1024**2, max_input_bytes=8 * 1024**2,
            max_workspace_bytes=128 * 1024**2, max_output_files=len(files)))
    run = process.BoundedToolRunner().run(request)
    assert native._binary_recheck(binary_pins)
    assert tuple(run.command) == command and run.runtime is process.ToolRuntime.NATIVE
    assert type(run.pid) is int and run.pid > 0
    assert run.returncode is not None and run.returncode > 0 and not run.ok
    assert not (run.unavailable or run.timed_out or run.cancelled or run.resource_exhausted
                or run.workspace_limit_exceeded or run.output_truncated or run.error)
    assert run.workspace_cleaned and run.native_lifecycle.cleanup_confirmed
    assert native._observed_process_scope(run.native_lifecycle, run.pid, process)
    assert run.output_files == {name: body.encode("utf-8") for name, body in files.items()}
    diagnostics = run.stdout + "\n" + run.stderr
    assert "type mismatch" in diagnostics.lower() and "hNorm" in diagnostics
    assert all(text not in diagnostics.lower() for text in (
        "unknown identifier", "unknown constant", "unknown module", "sorry"))
    output = positive_output.parent / "negative-norm-is-not-membership"
    output.mkdir()
    for name, text in sorted(files.items()):
        retained = output / "executed-inputs" / name
        retained.parent.mkdir(parents=True, exist_ok=True)
        retained.write_bytes(run.output_files[name])
        assert retained.read_bytes() == text.encode("utf-8")
    (output / "stdout.txt").write_bytes(run.stdout.encode("utf-8"))
    (output / "stderr.txt").write_bytes(run.stderr.encode("utf-8"))
    observation = {
        "schema": "authored-bound-norm-no-membership-negative/v1",
        "positive_preparation_sha256": native.preparation_sha256(preparation),
        "positive_native_receipt_sha256": native.bound_norm_definition_compilation_receipt_sha256(positive),
        "input_sha256": {name: sha(text.encode("utf-8")) for name, text in sorted(files.items())},
        "unchanged_modules": [manifest["expected_modules"][0], norm_module, definition_module],
        "command": list(run.command), "binary_sha256": binary_pins,
        "pid": run.pid, "returncode": run.returncode,
        "native_lifecycle": run.native_lifecycle.to_dict(),
        "expected_failure": "hNorm has the complete norm type, not headAt membership",
        "expected_compiler_type_mismatch_observed": True,
        "source_readback_passed": True, "authority": dict(native.AUTHORITY),
        "training_mask": 0, "evaluation_gold_mask": 0,
    }
    (output / "negative-observation.json").write_bytes(canonical(observation))
    assert json.loads((output / "negative-observation.json").read_bytes()) == observation


# Direct parent-norm native observations use only the separately qualified
# complete authored parent fixture. The old HTML/bound-definition cohorts stay
# untouched and are not regenerated by this focused profile.
_PARENT_NORM_NATIVE_HELPER = None
_PARENT_NORM_NATIVE_BASELINE = None


def _parent_norm_native_new(directory):
    global _PARENT_NORM_NATIVE_HELPER
    if _PARENT_NORM_NATIVE_HELPER is None:
        _PARENT_NORM_NATIVE_HELPER = _FIXTURE.parent_norm_helpers.__wrapped__()
    data = _FIXTURE._parent_norm_materialize(_PARENT_NORM_NATIVE_HELPER, directory)
    return data, preparer.prepare_parent_norm_corpus_v1(**data)


def _parent_norm_native_cached(directory):
    global _PARENT_NORM_NATIVE_BASELINE
    if _PARENT_NORM_NATIVE_BASELINE is None:
        _PARENT_NORM_NATIVE_BASELINE = _parent_norm_native_new(directory)
    return _PARENT_NORM_NATIVE_BASELINE


@pytest.fixture(scope="module")
def parent_norm_native_base(tmp_path_factory):
    return _parent_norm_native_cached(
        tmp_path_factory.mktemp("direct-parent-norm-originals", numbered=False))


def _parent_norm_native_arguments(data, preparation):
    return {"expected_preparation_sha256": preparer.parent_norm_preparation_sha256(preparation),
            "expected_correspondence_sha256": data["expected_correspondence_sha256"],
            "correspondence_inputs": data["correspondence_inputs"], "toolchain": data["toolchain"]}


def _parent_norm_native_validate(data, preparation, **overrides):
    return native.validate_parent_norm_native_v1(preparation, data["correspondence"],
        **(_parent_norm_native_arguments(data, preparation) | overrides))


def _parent_norm_native_build(data, preparation, executable, output, **overrides):
    return native.build_parent_norm_native_v1(preparation, data["correspondence"],
        **(_parent_norm_native_arguments(data, preparation) | {
            "lake_executable": str(executable), "output_directory": output,
            "timeout_seconds": 12} | overrides))


def _parent_norm_no_promotion(receipt):
    assert_no_authority(receipt)
    assert receipt["authority"] and all(value is False for value in receipt["authority"].values())
    for name in ("norm_truth_proved", "definition_applied_to_norm", "membership_assumption_verified",
                 "governing_definition_use_verified", "source_to_model_equivalence_proved"):
        assert receipt[name] is False, name


def _parent_norm_native_project_readback(output, preparation):
    for name, text in preparation.files:
        assert (output / "project" / name).read_bytes() == text.encode("utf-8")


def test_parent_norm_native_opt_in_reader_preserves_legacy_and_shared_storage_defaults():
    from ipfs_datasets_py.logic.autoformal import legal_corpus_shared_lake as shared
    # These are deliberately only storage/commitment shapes, not accepted
    # source projects or replacement positive evidence fixtures.
    files = tuple(("Shape" + str(index) + ".lean", "-- storage shape only\n")
                  for index in range(9))
    legacy = preparer.DefinitionUseCorpusPreparation("{}", files)
    assert len(native._preparation_document(legacy)["files"]) == 9
    assert native.preparation_sha256(legacy) == sha(canonical(native._preparation_document(legacy)))
    with pytest.raises(ValueError, match="nine"):
        native._preparation_document(replace(legacy, files=files[:7]))
    parent = shared.ParentSharedCorpusPreparation("{}", files[:1])
    assert len(native._preparation_document(parent, parent_shared=True)["files"]) == 1
    with pytest.raises(ValueError):
        native._preparation_document(parent)
    assert native.MAX_FILES == 9 and native.MAX_MODULES == 6 and native.MAX_PARENT_SHARED_FILES == 52


def test_parent_norm_native_validation_replays_genuine_seven_file_project_without_tools(
        parent_norm_native_base, monkeypatch):
    data, preparation = parent_norm_native_base
    before = deepcopy(data)
    legacy_cache, bound_cache = native._OPERATION_PINS, native._BOUND_NORM_OPERATION_PINS
    genuine = preparer.validate_parent_norm_corpus_v1
    observed = []
    def checked(*args, **kwargs):
        result = genuine(*args, **kwargs)
        observed.append(result)
        return result
    def forbidden(*args, **kwargs):
        raise AssertionError("native validation may not probe or execute a compiler")
    monkeypatch.setattr(preparer, "validate_parent_norm_corpus_v1", checked)
    monkeypatch.setattr(native, "_installed_toolchain", forbidden)
    monkeypatch.setattr(process.BoundedToolRunner, "run", forbidden)
    assert _parent_norm_native_validate(data, preparation) == preparation
    assert len(observed) == 1 and observed[0] == preparation and data == before
    assert native._OPERATION_PINS is legacy_cache and native._BOUND_NORM_OPERATION_PINS is bound_cache
    manifest = preparation.to_dict()
    assert len(preparation.files) == 7 and len(manifest["expected_modules"]) == 4
    assert len(manifest["conditional_theorems"]) == 1
    with pytest.raises(ValueError, match="nine"):
        native.preparation_sha256(preparation)


@pytest.mark.parametrize("damage", ["preparation_pin", "correspondence_pin", "request_pin",
                                    "wrong_profile", "nine_files"])
def test_parent_norm_native_independent_preflight_refuses_before_operation_owners(
        parent_norm_native_base, monkeypatch, damage):
    original, preparation = parent_norm_native_base
    data = deepcopy(original)
    kwargs = _parent_norm_native_arguments(data, preparation)
    if damage == "preparation_pin":
        kwargs["expected_preparation_sha256"] = "0" * 64
    elif damage == "correspondence_pin":
        kwargs["expected_correspondence_sha256"] = "0" * 64
    elif damage == "request_pin":
        kwargs["correspondence_inputs"]["expected_mapping_request_sha256"] = "0" * 64
    elif damage == "wrong_profile":
        manifest = preparation.to_dict()
        manifest["profile"] = preparer.PROFILE
        preparation = reseal_manifest(preparation, manifest)
        kwargs["expected_preparation_sha256"] = sha(canonical({
            "manifest": preparation.to_dict(), "files": [list(row) for row in preparation.files]}))
    else:
        files = dict(preparation.files) | {"ExtraA.txt": "not a parent norm input\n",
                                          "ExtraB.txt": "not a parent norm input\n"}
        preparation = replace(preparation, files=tuple(sorted(files.items())))
        # Repair the complete outer commitment through the unchanged nine-file
        # helper; the new native profile must still reject this forged shape.
        kwargs["expected_preparation_sha256"] = native.preparation_sha256(preparation)
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid parent norm reached operation owners")
    monkeypatch.setattr(native, "_owners", forbidden)
    with pytest.raises(ValueError):
        native.validate_parent_norm_native_v1(preparation, data["correspondence"], **kwargs)


@pytest.mark.parametrize("timeout", [True, 61], ids=["boolean", "above60"])
def test_parent_norm_native_timeout_preflight_precedes_replay_and_toolchain(
        parent_norm_native_base, monkeypatch, tmp_path, timeout):
    data, preparation = parent_norm_native_base
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid parent norm timeout reached execution owners")
    monkeypatch.setattr(native, "_owners", forbidden)
    with pytest.raises(ValueError):
        _parent_norm_native_build(data, preparation, tmp_path / "unused-lake",
                                  tmp_path / "not-created", timeout_seconds=timeout)
    assert not (tmp_path / "not-created").exists()


def test_parent_norm_native_synthetic_handoff_preserves_four_modules_seven_files_one_identity(
        parent_norm_native_base, synthetic_compiler, tmp_path):
    data, preparation = parent_norm_native_base
    before = deepcopy(data)
    executable, calls = synthetic_compiler(preparation)
    output = tmp_path / "parent-norm-synthetic"
    receipt = _parent_norm_native_build(data, preparation, executable, output)
    manifest = preparation.to_dict()
    assert len(calls) == 1 and receipt["build_passed"] is True
    assert receipt["schema"] == native.PARENT_NORM_BUILD_SCHEMA
    assert receipt["profile"] == native.PARENT_NORM_NATIVE_PROFILE
    assert receipt["preservation_kind"] == "definitional_alias_identity_only"
    assert receipt["correspondence_sha256"] == data["expected_correspondence_sha256"]
    assert receipt["parent_source_binding_sha256"] == manifest["parent_source_binding_sha256"]
    assert receipt["original_input_commitment_sha256"] == manifest["original_input_commitment_sha256"]
    assert len(receipt["compiled_modules"]) == len(receipt["artifact_sha256"]) == 4
    assert len(receipt["executed_project_sha256"]) == 7
    assert receipt["conditional_theorems"] == manifest["conditional_theorems"]
    assert receipt["theorem_axiom_dependencies"] == {manifest["conditional_theorems"][0]: []}
    assert receipt["original_preparation_build_eligible"] is False
    assert receipt["post_run_validation_passed"] is True and receipt["original_preparation_unchanged"] is True
    assert receipt["review_blockers"] == manifest["review_blockers"]
    assert receipt["theorem_assumptions"] == manifest["theorem_assumptions"]
    _parent_norm_no_promotion(receipt)
    _parent_norm_native_project_readback(output, preparation)
    for name, text in preparation.files:
        assert (output / "executed-inputs" / name).read_bytes() == text.encode()
    assert json.loads((output / "build-receipt.json").read_bytes()) == receipt
    assert native.parent_norm_compilation_receipt_sha256(receipt) == sha(canonical(receipt))
    assert data == before


@pytest.mark.parametrize("damage", ["missing_module", "changed_source", "missing_axiom"])
def test_parent_norm_native_requires_complete_outputs_and_exact_identity_observation(
        parent_norm_native_base, synthetic_compiler, tmp_path, damage):
    data, preparation = parent_norm_native_base
    options = {}
    if damage == "missing_module":
        options["output_edit"] = lambda outputs, artifacts, sources: outputs.pop(artifacts[-1])
    elif damage == "changed_source":
        options["output_edit"] = lambda outputs, artifacts, sources: outputs.__setitem__(sources[0], b"changed source")
    else:
        options["stdout"] = ""
    executable, calls = synthetic_compiler(preparation, **options)
    output = tmp_path / "parent-norm-refused-output"
    receipt = _parent_norm_native_build(data, preparation, executable, output)
    assert len(calls) == 1 and receipt["build_passed"] is False
    assert receipt["lean_compilation_verified"] is False and receipt["conditional_proofs_verified"] is False
    _parent_norm_no_promotion(receipt)
    _parent_norm_native_project_readback(output, preparation)
    assert json.loads((output / "build-receipt.json").read_bytes()) == receipt


@pytest.mark.parametrize("damage", ["physical_parent", "caller"])
def test_parent_norm_native_postrunner_drift_retains_frozen_unqualified_failure(
        parent_norm_native_base, synthetic_compiler, tmp_path, damage):
    original, baseline = parent_norm_native_base
    data, preparation = (_parent_norm_native_new(tmp_path / "originals")
                         if damage == "physical_parent" else (deepcopy(original), baseline))
    def changed():
        if damage == "physical_parent":
            path = _FIXTURE._parent_norm_parent_path(data)
            path.write_bytes(path.read_bytes() + b" changed after genuine runner return")
        else:
            data["correspondence"]["training_mask"] = False
    executable, calls = synthetic_compiler(preparation, after=changed)
    output = tmp_path / "postrunner-refusal"
    with pytest.raises(ValueError):
        _parent_norm_native_build(data, preparation, executable, output)
    assert len(calls) == 1
    _parent_norm_native_project_readback(output, preparation)
    receipt = json.loads((output / "build-receipt.json").read_bytes())
    assert receipt["build_passed"] is False and receipt["post_run_validation_passed"] is False
    assert receipt["lean_compilation_verified"] is False and receipt["conditional_proofs_verified"] is False
    _parent_norm_no_promotion(receipt)


@pytest.mark.parametrize("return_index", [0, 1], ids=["opening", "closing"])
def test_parent_norm_native_actual_lake_returns_keep_exact_raw_storage_through_final_check(
        parent_norm_native_base, synthetic_compiler, tmp_path, monkeypatch, return_index):
    original, preparation = parent_norm_native_base
    data = deepcopy(original)
    executable, calls = synthetic_compiler(preparation)
    genuine = preparer.validate_parent_norm_corpus_v1
    actual, observed = [], []
    def returned(*args, **kwargs):
        result = genuine(*args, **kwargs)
        actual.append(result)
        return result
    serialized = native._parent_norm_native_serialized_fence
    def changed(receipt, expected_wire):
        result = serialized(receipt, expected_wire)
        if not observed:
            assert len(actual) == 2
            observed.append("genuine native receipt serialization completed")
            # Mutate the actual returned frozen object's raw storage, rather
            # than a detached to_dict copy or a semantically normalized value.
            target = actual[return_index]
            object.__setattr__(target, "manifest_json", target.manifest_json + " ")
        return result
    monkeypatch.setattr(preparer, "validate_parent_norm_corpus_v1", returned)
    monkeypatch.setattr(native, "_parent_norm_native_serialized_fence", changed)
    output = tmp_path / "held-lake-return-refusal"
    with pytest.raises(ValueError):
        _parent_norm_native_build(data, preparation, executable, output)
    assert len(calls) == 1 and len(actual) == 2
    assert observed == ["genuine native receipt serialization completed"]
    _parent_norm_native_project_readback(output, preparation)


@pytest.mark.parametrize("damage", ["physical_parent", "producer", "receipt"])
def test_parent_norm_native_late_genuine_persistence_drift_refuses_success_without_rollback(
        parent_norm_native_base, synthetic_compiler, tmp_path, monkeypatch, damage):
    original, baseline = parent_norm_native_base
    data, preparation = (_parent_norm_native_new(tmp_path / "originals")
                         if damage == "physical_parent" else (deepcopy(original), baseline))
    producer = None
    if damage == "producer":
        producer = tmp_path / "copied_parent_norm_native_owner.py"
        producer.write_bytes(Path(native.__file__).read_bytes())
        monkeypatch.setattr(native, "__file__", str(producer))
        monkeypatch.setattr(native, "_SELF_PIN", sha(producer.read_bytes()))
        monkeypatch.setattr(native, "_PARENT_NORM_OPERATION_PINS", None)
    executable, calls = synthetic_compiler(preparation)
    genuine = native._persist_build
    observed = []
    def changed(checked, output, owners, artifacts, executed_sources, logs, receipt, **kwargs):
        result = genuine(checked, output, owners, artifacts, executed_sources, logs, receipt, **kwargs)
        observed.append("genuine native persistence completed")
        if damage == "physical_parent":
            path = _FIXTURE._parent_norm_parent_path(data)
            path.write_bytes(path.read_bytes() + b" changed after exact native readback")
        elif damage == "producer":
            producer.write_bytes(producer.read_bytes() + b"\n# native producer changed after persistence\n")
        else:
            receipt["preservation_kind"] = "unsupported norm truth promotion"
        return result
    monkeypatch.setattr(native, "_persist_build", changed)
    output = tmp_path / "late-persistence-refusal"
    with pytest.raises(ValueError):
        _parent_norm_native_build(data, preparation, executable, output)
    assert len(calls) == 1 and observed == ["genuine native persistence completed"]
    _parent_norm_native_project_readback(output, preparation)
    # The already written observation is retained. Its existence cannot replace
    # the failed closing operation or grant current-source/corpus authority.
    saved = json.loads((output / "build-receipt.json").read_bytes())
    assert saved["preservation_kind"] == "definitional_alias_identity_only"
    _parent_norm_no_promotion(saved)


def test_parent_norm_native_cleanup_failure_preserves_original_owner_handle(
        parent_norm_native_base, synthetic_compiler, tmp_path, monkeypatch):
    data, preparation = parent_norm_native_base
    executable, _ = synthetic_compiler(preparation)
    handle = object()
    original = process.OwnedToolCleanupError(handle, "authored unresolved parent norm cleanup")
    def fail(self, request, *, cancellation=None):
        assert request.owned_process_observation is True
        raise original
    monkeypatch.setattr(process.BoundedToolRunner, "run", fail)
    output = tmp_path / "parent-norm-cleanup-refusal"
    with pytest.raises(process.OwnedToolCleanupError) as caught:
        _parent_norm_native_build(data, preparation, executable, output)
    assert caught.value is original and caught.value.cleanup_handle is handle
    receipt = json.loads((output / "build-receipt.json").read_bytes())
    assert receipt["build_passed"] is False and receipt["cleanup_owner_retained_on_exception"] is True
    assert receipt["cleanup_confirmed"] is False and receipt["artifact_sha256"] == {}
    for name in FALSE_AUTHORITY:
        assert receipt[name] is False, name
    assert all(value is False for value in receipt["authority"].values())
    assert type(receipt["training_mask"]) is int and receipt["training_mask"] == 0
    assert type(receipt["evaluation_gold_mask"]) is int and receipt["evaluation_gold_mask"] == 0
    _parent_norm_native_project_readback(output, preparation)


@pytest.fixture(scope="module")
def parent_norm_actual_project(bound_norm_installed_lake, tmp_path_factory):
    # The original explicit native gate/binary checks resolve before constructing
    # the one cached parent fixture. Both actual cases share this positive build.
    executable, binary_pins = bound_norm_installed_lake
    data, preparation = _parent_norm_native_cached(
        tmp_path_factory.mktemp("direct-parent-norm-native-originals", numbered=False))
    output = tmp_path_factory.mktemp("direct-parent-norm-native", numbered=False) / "positive"
    receipt = native.build_parent_norm_native_v1(preparation, data["correspondence"],
        **_parent_norm_native_arguments(data, preparation),
        lake_executable=str(executable), output_directory=output, timeout_seconds=60)
    return data, preparation, output, receipt, executable, binary_pins


def test_parent_norm_native_installed_lean_checks_only_original_norm_alias_identity(
        parent_norm_actual_project):
    data, preparation, output, receipt, executable, binary_pins = parent_norm_actual_project
    manifest = preparation.to_dict()
    assert receipt["build_passed"] is True, receipt
    assert receipt["schema"] == native.PARENT_NORM_BUILD_SCHEMA
    assert receipt["profile"] == native.PARENT_NORM_NATIVE_PROFILE
    assert receipt["preservation_kind"] == "definitional_alias_identity_only"
    assert receipt["runtime"] == "native" and receipt["native_runtime_verified"] is True
    assert type(receipt["pid"]) is int and receipt["pid"] > 0
    assert receipt["binary_sha256"] == binary_pins
    assert receipt["command"] == [str(executable), "--offline", "--no-cache", "build", "legal"]
    assert receipt["cleanup_confirmed"] is True and receipt["observed_process_scope_passed"] is True
    assert receipt["post_run_validation_passed"] is True and receipt["original_preparation_unchanged"] is True
    assert receipt["manifest_coverage_passed"] is True and receipt["executed_project_readback_passed"] is True
    assert len(receipt["compiled_modules"]) == 4 and len(receipt["executed_project_sha256"]) == 7
    assert receipt["conditional_theorems"] == manifest["conditional_theorems"]
    assert len(receipt["conditional_theorems"]) == 1
    assert receipt["theorem_axiom_dependencies"] == {manifest["conditional_theorems"][0]: []}
    assert receipt["original_preparation_build_eligible"] is False
    _parent_norm_no_promotion(receipt)
    _parent_norm_native_project_readback(output, preparation)
    for name, text in preparation.files:
        assert (output / "executed-inputs" / name).read_bytes() == text.encode("utf-8")
    for module in manifest["expected_modules"]:
        assert (output / "compiled" / (module.replace(".", "/") + ".olean")).stat().st_size > 0
    for name, pin in receipt["log_sha256"].items():
        assert sha((output / name).read_bytes()) == pin
    assert json.loads((output / "build-receipt.json").read_bytes()) == receipt
    assert native.parent_norm_compilation_receipt_sha256(receipt) == sha(canonical(receipt))


def test_parent_norm_native_installed_lean_alias_identity_does_not_prove_norm_truth(
        parent_norm_actual_project):
    data, preparation, positive_output, positive, executable, binary_pins = parent_norm_actual_project
    assert positive["build_passed"] is True and native._binary_recheck(binary_pins)
    manifest = preparation.to_dict()
    norm = manifest["native_fragments"][0]["module"]
    theorem = manifest["conditional_theorems"][0]
    preservation = theorem.rsplit(".", 1)[0]
    files = dict(preparation.files)
    root_name = "LegalCorpusParentNorm.lean"
    files[root_name] = (
        "import " + preservation + "\nnamespace LegalCorpusParentNorm\n"
        "theorem invalid_alias_implies_norm_truth {Entity Agent : Type} "
        "(i : Interpretation Entity Agent) (t : Nat) :\n"
        "    " + norm + ".formula_0 i t := by\n"
        "  have hAlias := " + theorem + " i t\n"
        "  exact hAlias\nend LegalCorpusParentNorm\n")
    unchanged = [module for module in manifest["expected_modules"] if module != "LegalCorpusParentNorm"]
    for module in unchanged:
        path = module.replace(".", "/") + ".lean"
        assert files[path] == dict(preparation.files)[path]
    forged = reseal_manifest(preparation, manifest, files)
    forged_pin = sha(canonical({"manifest": forged.to_dict(), "files": [list(row) for row in forged.files]}))
    with patch.object(native, "_installed_toolchain", side_effect=AssertionError("forged project native dispatch")):
        with pytest.raises(ValueError):
            _parent_norm_native_validate(data, forged, expected_preparation_sha256=forged_pin)
    command = tuple(positive["command"])
    request = process.ToolRunRequest(argv=command, input_files=files,
        output_paths=tuple(sorted(files)), owned_process_observation=True,
        environment={"ELAN_TOOLCHAIN": TOOLCHAIN, "LEAN_NUM_THREADS": "1"},
        limits=process.ToolRunLimits(timeout_seconds=60, cpu_seconds=60,
            resident_memory_bytes=2 * 1024**3, max_output_bytes=2 * 1024**2,
            max_input_bytes=8 * 1024**2, max_workspace_bytes=128 * 1024**2,
            max_output_files=len(files)))
    run = process.BoundedToolRunner().run(request)
    assert native._binary_recheck(binary_pins)
    assert tuple(run.command) == command and run.runtime is process.ToolRuntime.NATIVE
    assert type(run.pid) is int and run.pid > 0 and run.returncode is not None and run.returncode > 0 and not run.ok
    assert not (run.unavailable or run.timed_out or run.cancelled or run.resource_exhausted
                or run.workspace_limit_exceeded or run.output_truncated or run.error)
    assert run.workspace_cleaned and run.native_lifecycle.cleanup_confirmed
    assert native._observed_process_scope(run.native_lifecycle, run.pid, process)
    assert run.output_files == {name: body.encode("utf-8") for name, body in files.items()}
    diagnostics = run.stdout + "\n" + run.stderr
    assert "type mismatch" in diagnostics.lower() and "hAlias" in diagnostics
    assert all(word not in diagnostics.lower() for word in (
        "unknown identifier", "unknown constant", "unknown module", "sorry"))
    output = positive_output.parent / "negative-alias-is-not-norm-truth"
    output.mkdir()
    for name, text in sorted(files.items()):
        target = output / "executed-inputs" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(run.output_files[name])
        assert target.read_bytes() == text.encode()
    (output / "stdout.txt").write_bytes(run.stdout.encode())
    (output / "stderr.txt").write_bytes(run.stderr.encode())
    observation = {"schema": "authored-parent-norm-alias-not-truth-negative/v1",
        "positive_preparation_sha256": preparer.parent_norm_preparation_sha256(preparation),
        "positive_receipt_sha256": native.parent_norm_compilation_receipt_sha256(positive),
        "input_sha256": {name: sha(text.encode()) for name, text in sorted(files.items())},
        "unchanged_modules": unchanged, "command": list(run.command),
        "binary_sha256": binary_pins, "pid": run.pid, "returncode": run.returncode,
        "native_lifecycle": run.native_lifecycle.to_dict(),
        "expected_failure": "hAlias is the original norm equivalence, not a proof of the norm",
        "intended_type_mismatch_observed": True, "source_readback_passed": True,
        "authority": dict(native.AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0}
    (output / "negative-observation.json").write_bytes(canonical(observation))
    assert json.loads((output / "negative-observation.json").read_bytes()) == observation


# Explicit parent-bound definition native integration. The real parent-bound
# fixture is shared; only the tests explicitly named instrumented replace the
# upstream project validator. Such cases test native custody boundaries, never
# original source replay, native proof authority or a legal interpretation.
_PARENT_BOUND_NORM_NATIVE_HELPER = None
_PARENT_BOUND_NORM_NATIVE_BASELINE = None


def _parent_bound_norm_native_new(directory):
    global _PARENT_BOUND_NORM_NATIVE_HELPER
    if _PARENT_BOUND_NORM_NATIVE_HELPER is None:
        _PARENT_BOUND_NORM_NATIVE_HELPER = _FIXTURE.fixture_module(
            "test_legal_corpus_parent_bound_norm_lake_v1.py",
            "parent_bound_norm_native_original_fixture")
    helper = _PARENT_BOUND_NORM_NATIVE_HELPER
    conditional = helper.parent_bound_norm_helpers.__wrapped__()
    nomination = conditional.parent_bound_helpers.__wrapped__()
    inputs = nomination._parent_nomination_materialize(
        nomination.parent_nomination_helpers.__wrapped__(), Path(directory))
    companion = nomination._parent_nomination_prepare(inputs)
    original = {"inputs": inputs, "companion": companion,
                "companion_sha256": nomination.owner.norm_definition_evidence_sha256(companion)}
    producer = native._parent_bound_norm_native_preparer()
    modes = {}
    for mode in ("instance_only", "body_with_membership"):
        data = helper._parent_bound_norm_data(conditional, original, mode=mode)
        modes[mode] = (data, producer.prepare_parent_bound_norm_definition_corpus_v1(**data))
    return modes


def _parent_bound_norm_native_cached(directory):
    global _PARENT_BOUND_NORM_NATIVE_BASELINE
    if _PARENT_BOUND_NORM_NATIVE_BASELINE is None:
        _PARENT_BOUND_NORM_NATIVE_BASELINE = _parent_bound_norm_native_new(directory)
    return _PARENT_BOUND_NORM_NATIVE_BASELINE


@pytest.fixture(scope="module")
def parent_bound_norm_native_modes(tmp_path_factory):
    return _parent_bound_norm_native_cached(
        tmp_path_factory.mktemp("parent-bound-norm-native-originals", numbered=False))


def _parent_bound_norm_native_arguments(data, preparation):
    producer = native._parent_bound_norm_native_preparer()
    return {"expected_preparation_sha256":
                producer.parent_bound_norm_definition_preparation_sha256(preparation),
            "expected_bound_report_sha256": data["expected_bound_report_sha256"],
            "bound_definition_inputs": data["bound_definition_inputs"],
            "toolchain": data["toolchain"]}


def _parent_bound_norm_native_validate(data, preparation, **overrides):
    return native.validate_parent_bound_norm_definition_native_v1(
        preparation, data["bound_report"],
        **(_parent_bound_norm_native_arguments(data, preparation) | overrides))


def _parent_bound_norm_native_build(data, preparation, executable, output, **overrides):
    return native.build_parent_bound_norm_definition_native_v1(
        preparation, data["bound_report"],
        **(_parent_bound_norm_native_arguments(data, preparation) | {
            "lake_executable": str(executable), "output_directory": output,
            "timeout_seconds": 12} | overrides))


def _parent_bound_norm_native_no_promotion(receipt, *, owned_observation=True):
    if owned_observation:
        assert_no_authority(receipt)
    else:
        # No complete runner result exists on this exception branch. Retain
        # only its explicit false authorities; do not invent a lifecycle attestation.
        for name in FALSE_AUTHORITY:
            assert receipt[name] is False, name
    assert receipt["authority"] and all(value is False for value in receipt["authority"].values())
    assert receipt["selected_interpretation"] is None
    assert receipt["governing_definition_use"] is None
    assert receipt["norm_interpretation_ready"] is False
    for key in ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"):
        assert type(receipt[key]) is int and receipt[key] == 0
    for key in ("norm_truth_proved", "definition_applied_to_norm", "membership_assumption_verified",
                "governing_definition_use_verified"):
        assert receipt[key] is False
    if owned_observation:
        # The generic completed-run engine supplies this field; its unresolved
        # cleanup refusal has no complete process observation and omits it.
        assert receipt["source_to_model_equivalence_proved"] is False


def _parent_bound_norm_native_readback(output, preparation, data, *, executed_source_overrides=None):
    actual_overrides = {} if executed_source_overrides is None else dict(executed_source_overrides)
    assert set(actual_overrides) <= dict(preparation.files).keys()
    for name, text in preparation.files:
        frozen = text.encode("utf-8")
        assert (output / "project" / name).read_bytes() == frozen
        # Failed observations retain the bytes actually returned by the runner;
        # they must never be overwritten with the expected source to look valid.
        expected_actual = actual_overrides.get(name, frozen)
        assert (output / "executed-inputs" / name).read_bytes() == expected_actual
    assert (output / "project/corpus-manifest.json").read_bytes() == preparation.manifest_json.encode("utf-8")
    input_name = "bound-norm-input-bindings.json"
    stored = json.loads((output / "project" / input_name).read_bytes())
    assert canonical(stored["parent_bound_definition_report"]) == canonical(data["bound_report"])
    if input_name not in actual_overrides:
        assert (output / "executed-inputs" / input_name).read_bytes() == (output / "project" / input_name).read_bytes()


@pytest.fixture
def instrumented_parent_bound_norm_replay(monkeypatch):
    """Replace only the peer validator after real shared preparation exists.

    These returns deliberately provide NO original replay qualification. Fresh
    raw-storage copies expose actual-return/final-storage custody independently
    of the expensive genuine upstream validation exercised by separate tests.
    """
    producer = native._parent_bound_norm_native_preparer()
    calls = []

    def copied(offered, bound_report, **kwargs):
        returned = replace(offered)
        calls.append({"preparation": returned, "bound_report": bound_report, "kwargs": kwargs})
        return returned

    monkeypatch.setattr(producer, "validate_parent_bound_norm_definition_corpus_v1", copied)
    return calls


def test_parent_bound_norm_native_explicit_reader_preserves_existing_storage_defaults():
    files = tuple(("Shape" + str(i) + ".lean", "-- storage shape only\n") for i in range(9))
    shape = preparer.DefinitionUseCorpusPreparation("{}", files)
    assert len(native._preparation_document(shape)["files"]) == 9
    assert native.preparation_sha256(shape) == sha(canonical(native._preparation_document(shape)))
    seven = replace(shape, files=files[:7])
    assert len(native._parent_norm_native_document(seven)["files"]) == 7
    with pytest.raises(ValueError):
        native._preparation_document(seven)
    assert native.MAX_FILES == 9 and native.MAX_MODULES == 6
    defaults = native._parent_norm_native_persisted.__kwdefaults__
    assert defaults == {"maximum_files": 7, "maximum_modules": 4}
    assert all(type(value) is int for value in defaults.values())


def test_parent_bound_norm_native_receipt_commitment_has_separate_profile_and_mask_types():
    value = {"schema": native.PARENT_BOUND_NORM_BUILD_SCHEMA,
             "profile": native.PARENT_BOUND_NORM_NATIVE_PROFILE, "training_mask": 0}
    assert native.parent_bound_norm_definition_compilation_receipt_sha256(value) == sha(canonical(value))
    changed = value | {"training_mask": False}
    assert native.parent_bound_norm_definition_compilation_receipt_sha256(changed) != \
        native.parent_bound_norm_definition_compilation_receipt_sha256(value)
    with pytest.raises(ValueError):
        native.parent_bound_norm_definition_compilation_receipt_sha256(
            value | {"profile": native.BOUND_NORM_PROFILE})


@pytest.mark.parametrize("damage", ["preparation", "report", "request", "companion", "profile", "mask-type"])
def test_parent_bound_norm_native_independent_preflight_refuses_before_operation_owners(
        parent_bound_norm_native_modes, monkeypatch, damage):
    original, baseline = parent_bound_norm_native_modes["body_with_membership"]
    data, preparation = deepcopy(original), replace(baseline)
    kwargs = _parent_bound_norm_native_arguments(data, preparation)
    if damage == "preparation": kwargs["expected_preparation_sha256"] = "0" * 64
    elif damage == "report": kwargs["expected_bound_report_sha256"] = "0" * 64
    elif damage in ("request", "companion"):
        kwargs["bound_definition_inputs"]["expected_" + damage + "_sha256"] = "0" * 64
    elif damage == "mask-type":
        data["bound_report"]["training_mask"] = False
        kwargs["expected_bound_report_sha256"] = sha(canonical(data["bound_report"]))
    else:
        manifest = preparation.to_dict()
        manifest["profile"] = preparer.BOUND_NORM_PROFILE
        preparation = reseal_manifest(preparation, manifest)
        kwargs["expected_preparation_sha256"] = sha(canonical({
            "manifest": preparation.to_dict(), "files": [list(row) for row in preparation.files]}))
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid parent-bound native inputs reached operation owners")
    monkeypatch.setattr(native, "_owners", forbidden)
    monkeypatch.setattr(native, "_parent_bound_norm_native_preparer", forbidden)
    with pytest.raises(ValueError):
        native.validate_parent_bound_norm_definition_native_v1(
            preparation, data["bound_report"], **kwargs)


@pytest.mark.parametrize("damage", ["boolean-timeout", "above60", "input-budget"])
def test_parent_bound_norm_native_execution_bounds_refuse_without_tools_or_export(
        parent_bound_norm_native_modes, monkeypatch, tmp_path, damage):
    data, preparation = parent_bound_norm_native_modes["body_with_membership"]
    kwargs = _parent_bound_norm_native_arguments(data, preparation) | {
        "lake_executable": str(tmp_path / "unused-lake"),
        "output_directory": tmp_path / "not-created", "timeout_seconds": 12}
    if damage == "input-budget": monkeypatch.setattr(native, "MAX_INPUT_BYTES", 1)
    else: kwargs["timeout_seconds"] = True if damage == "boolean-timeout" else 61
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid parent-bound native budget reached operation owners")
    monkeypatch.setattr(native, "_owners", forbidden)
    monkeypatch.setattr(native, "_parent_bound_norm_native_preparer", forbidden)
    with pytest.raises(ValueError):
        native.build_parent_bound_norm_definition_native_v1(
            preparation, data["bound_report"], **kwargs)
    assert not kwargs["output_directory"].exists()


@pytest.mark.parametrize("mode", ["instance_only", "body_with_membership"], ids=["instance", "membership"])
def test_parent_bound_norm_native_genuine_public_validation_replays_both_modes_without_tools(
        parent_bound_norm_native_modes, monkeypatch, mode):
    data, preparation = parent_bound_norm_native_modes[mode]
    producer = native._parent_bound_norm_native_preparer()
    before = deepcopy(data)
    legacy_caches = (native._OPERATION_PINS, native._BOUND_NORM_OPERATION_PINS, native._PARENT_NORM_OPERATION_PINS)
    genuine = producer.validate_parent_bound_norm_definition_corpus_v1
    observed = []
    def validated(*args, **kwargs):
        result = genuine(*args, **kwargs)
        observed.append(result)
        return result
    def forbidden(*args, **kwargs):
        raise AssertionError("pure parent-bound native validation executed a tool")
    monkeypatch.setattr(producer, "validate_parent_bound_norm_definition_corpus_v1", validated)
    monkeypatch.setattr(native, "_installed_toolchain", forbidden)
    monkeypatch.setattr(process.BoundedToolRunner, "run", forbidden)
    assert _parent_bound_norm_native_validate(data, preparation) == preparation
    assert len(observed) == 1 and observed[0] == preparation and data == before
    assert all(now is old for now, old in zip(
        (native._OPERATION_PINS, native._BOUND_NORM_OPERATION_PINS, native._PARENT_NORM_OPERATION_PINS),
        legacy_caches, strict=True))
    manifest = preparation.to_dict()
    assert len(preparation.files) == 9 and len(manifest["expected_modules"]) == 6
    assert len(manifest["conditional_theorems"]) == (2 if mode == "instance_only" else 3)
    assert manifest["original_norm"]["source_binding"] is None
    assert manifest["original_norm"]["source_bound"] is False
    assert manifest["original_norm"]["unchanged"] is True
    assert manifest["parent_bound_definition_report_ref"]["report_sha256"] == data["expected_bound_report_sha256"]
    assert all(value is False for value in manifest["authority"].values())
    for key in ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"):
        assert type(manifest[key]) is int and manifest[key] == 0
    report = data["bound_report"]
    assert report["backend_executed"] is False and report["lean_compilation_verified"] is False
    assert all(row["kernel_checked"] is False for row in report["conditional_theorem_statements"])
    assert manifest["conditional_theorem_statements"] == report["conditional_theorem_statements"]
    assert manifest["execution_handoff"]["processes_executed"] == 0


@pytest.mark.parametrize("mode", ["instance_only", "body_with_membership"], ids=["instance", "membership"])
def test_parent_bound_norm_native_instrumented_handoff_preserves_complete_project_and_pending_meaning(
        parent_bound_norm_native_modes, instrumented_parent_bound_norm_replay,
        synthetic_compiler, tmp_path, mode):
    data, preparation = parent_bound_norm_native_modes[mode]
    before = deepcopy(data)
    executable, calls = synthetic_compiler(preparation)
    output = tmp_path / "parent-bound-synthetic"
    receipt = _parent_bound_norm_native_build(data, preparation, executable, output)
    manifest = preparation.to_dict()
    assert len(calls) == 1 and len(instrumented_parent_bound_norm_replay) == 2
    assert receipt["schema"] == native.PARENT_BOUND_NORM_BUILD_SCHEMA
    assert receipt["profile"] == native.PARENT_BOUND_NORM_NATIVE_PROFILE
    assert receipt["build_passed"] is True and receipt["conditional_proofs_verified"] is True
    assert receipt["bound_definition_report_sha256"] == data["expected_bound_report_sha256"]
    assert receipt["bound_definition_mode"] == mode
    retained_fields = ("original_norm", "occurrence_binding", "selected_link", "definition_alternative_refs",
        "nomination_inventory", "review_intake_binding", "conditional_source_binding",
        "original_parent_context_bindings", "parent_bound_definition_report_ref", "conditional_theorem_statements")
    assert receipt["retained_manifest_field_sha256"] == {name: sha(canonical(manifest[name]))
                                                        for name in retained_fields}
    assert receipt["parent_bound_definition_report_ref"] == manifest["parent_bound_definition_report_ref"]
    assert receipt["definition_alternative_refs_count"] == len(manifest["definition_alternative_refs"])
    assert receipt["nomination_inventory_count"] == len(manifest["nomination_inventory"])
    assert receipt["expected_modules"] == receipt["compiled_modules"] == manifest["expected_modules"]
    assert len(receipt["artifact_sha256"]) == 6 and len(receipt["executed_project_sha256"]) == 9
    assert receipt["theorem_axiom_dependencies"] == {name: [] for name in manifest["conditional_theorems"]}
    assert receipt["original_preparation_theorem_assumptions"] == manifest["theorem_assumptions"]
    assert receipt["original_preparation_build_eligible"] is False
    assert receipt["original_preparation_execution_handoff"] == manifest["execution_handoff"]
    assert receipt["preservation_kind"] == "definitional_alias_identity_only"
    _parent_bound_norm_native_no_promotion(receipt)
    _parent_bound_norm_native_readback(output, preparation, data)
    assert json.loads((output / "build-receipt.json").read_bytes()) == receipt
    assert native.parent_bound_norm_definition_compilation_receipt_sha256(receipt) == sha(canonical(receipt))
    assert data == before


@pytest.mark.parametrize("damage", ["missing-module", "changed-source", "missing-axiom"])
def test_parent_bound_norm_native_instrumented_outputs_cannot_replace_full_project_observations(
        parent_bound_norm_native_modes, instrumented_parent_bound_norm_replay,
        synthetic_compiler, tmp_path, damage):
    data, preparation = parent_bound_norm_native_modes["body_with_membership"]
    options, actual_source_edits = {}, {}
    if damage == "missing-module":
        options["output_edit"] = lambda outputs, artifacts, sources: outputs.pop(artifacts[-1])
    elif damage == "changed-source":
        def changed(outputs, artifacts, sources):
            actual_source_edits[sources[0]] = b"changed source"
            outputs[sources[0]] = actual_source_edits[sources[0]]
        options["output_edit"] = changed
    else: options["stdout"] = ""
    executable, calls = synthetic_compiler(preparation, **options)
    output = tmp_path / "parent-bound-incomplete"
    receipt = _parent_bound_norm_native_build(data, preparation, executable, output)
    assert len(calls) == 1 and len(instrumented_parent_bound_norm_replay) == 2
    assert receipt["build_passed"] is False and receipt["lean_compilation_verified"] is False
    assert receipt["conditional_proofs_verified"] is False
    _parent_bound_norm_native_no_promotion(receipt)
    _parent_bound_norm_native_readback(output, preparation, data,
                                      executed_source_overrides=actual_source_edits)
    for name, actual in actual_source_edits.items():
        assert receipt["executed_project_sha256"][name] == sha(actual)
    if damage == "changed-source":
        assert actual_source_edits and receipt["executed_project_readback_passed"] is False


@pytest.mark.parametrize("damage", ["caller", "detached", "binary"])
def test_parent_bound_norm_native_instrumented_postrunner_drift_retains_unqualified_observation(
        parent_bound_norm_native_modes, instrumented_parent_bound_norm_replay,
        synthetic_compiler, tmp_path, damage):
    original, baseline = parent_bound_norm_native_modes["body_with_membership"]
    data, preparation = deepcopy(original), replace(baseline)
    executable = None
    def changed():
        if damage == "caller": data["bound_report"]["training_mask"] = False
        elif damage == "detached":
            instrumented_parent_bound_norm_replay[0]["bound_report"]["training_mask"] = False
        else: executable.write_bytes(executable.read_bytes() + b" changed binary")
    executable, calls = synthetic_compiler(preparation, after=changed)
    output = tmp_path / "parent-bound-postrunner-refusal"
    with pytest.raises(ValueError):
        _parent_bound_norm_native_build(data, preparation, executable, output)
    assert len(calls) == 1
    saved = json.loads((output / "build-receipt.json").read_bytes())
    assert saved["build_passed"] is False and saved["post_run_validation_passed"] is False
    _parent_bound_norm_native_no_promotion(saved)
    _parent_bound_norm_native_readback(output, preparation, original)


@pytest.mark.parametrize("return_index", [0, 1], ids=["opening", "closing"])
def test_parent_bound_norm_native_instrumented_actual_preparer_returns_keep_raw_storage(
        parent_bound_norm_native_modes, instrumented_parent_bound_norm_replay,
        synthetic_compiler, tmp_path, monkeypatch, return_index):
    data, preparation = parent_bound_norm_native_modes["body_with_membership"]
    executable, calls = synthetic_compiler(preparation)
    serialized = native._parent_norm_native_serialized_fence
    observed = []
    def changed(receipt, expected_wire):
        result = serialized(receipt, expected_wire)
        if receipt.get("schema") == native.PARENT_BOUND_NORM_BUILD_SCHEMA and not observed:
            assert len(instrumented_parent_bound_norm_replay) == 2
            observed.append("native final serialization completed")
            target = instrumented_parent_bound_norm_replay[return_index]["preparation"]
            object.__setattr__(target, "manifest_json", target.manifest_json + " ")
        return result
    monkeypatch.setattr(native, "_parent_norm_native_serialized_fence", changed)
    output = tmp_path / "parent-bound-held-return-refusal"
    with pytest.raises(ValueError):
        _parent_bound_norm_native_build(data, preparation, executable, output)
    assert len(calls) == 1 and len(instrumented_parent_bound_norm_replay) == 2
    assert observed == ["native final serialization completed"]
    _parent_bound_norm_native_readback(output, preparation, data)


def test_parent_bound_norm_native_instrumented_actual_runner_return_is_held_through_final_encoding(
        parent_bound_norm_native_modes, instrumented_parent_bound_norm_replay,
        synthetic_compiler, tmp_path, monkeypatch):
    data, preparation = parent_bound_norm_native_modes["body_with_membership"]
    executable, calls = synthetic_compiler(preparation)
    actual = []
    run = process.BoundedToolRunner.run
    def retained(self, request, **kwargs):
        result = run(self, request, **kwargs)
        actual.append(result)
        return result
    monkeypatch.setattr(process.BoundedToolRunner, "run", retained)
    serialized = native._parent_norm_native_serialized_fence
    changed = []
    def mutate(receipt, expected_wire):
        result = serialized(receipt, expected_wire)
        if receipt.get("schema") == native.PARENT_BOUND_NORM_BUILD_SCHEMA and not changed:
            changed.append("final serialized receipt checked")
            object.__setattr__(actual[0], "stdout", actual[0].stdout + " changed actual runner return")
        return result
    monkeypatch.setattr(native, "_parent_norm_native_serialized_fence", mutate)
    with pytest.raises(ValueError):
        _parent_bound_norm_native_build(data, preparation, executable, tmp_path / "parent-bound-held-runner")
    assert len(calls) == len(actual) == 1 and changed == ["final serialized receipt checked"]


@pytest.mark.parametrize("damage", ["persisted-file", "receipt"])
def test_parent_bound_norm_native_instrumented_late_persistence_drift_refuses_without_rollback(
        parent_bound_norm_native_modes, instrumented_parent_bound_norm_replay,
        synthetic_compiler, tmp_path, monkeypatch, damage):
    data, preparation = parent_bound_norm_native_modes["body_with_membership"]
    executable, calls = synthetic_compiler(preparation)
    genuine = native._persist_build
    observed = []
    def changed(checked, output, owners, artifacts, executed_sources, logs, receipt, **kwargs):
        result = genuine(checked, output, owners, artifacts, executed_sources, logs, receipt, **kwargs)
        observed.append("original persistence completed")
        if damage == "persisted-file":
            path = output / "executed-inputs/lean-toolchain"
            path.write_bytes(path.read_bytes() + b" changed retained input")
        else: receipt["preservation_kind"] = "unsupported norm truth promotion"
        return result
    monkeypatch.setattr(native, "_persist_build", changed)
    output = tmp_path / "parent-bound-late-persistence"
    with pytest.raises(ValueError):
        _parent_bound_norm_native_build(data, preparation, executable, output)
    assert len(calls) == 1 and observed == ["original persistence completed"]
    saved = json.loads((output / "build-receipt.json").read_bytes())
    assert saved["preservation_kind"] == "definitional_alias_identity_only"
    _parent_bound_norm_native_no_promotion(saved)


def test_parent_bound_norm_native_instrumented_late_policy_drift_distinguishes_false_from_zero(
        parent_bound_norm_native_modes, instrumented_parent_bound_norm_replay,
        synthetic_compiler, tmp_path, monkeypatch):
    data, preparation = parent_bound_norm_native_modes["body_with_membership"]
    producer = native._parent_bound_norm_native_preparer()
    executable, calls = synthetic_compiler(preparation)
    serialized = native._parent_norm_native_serialized_fence
    changed = []
    assert producer.PARENT_BOUND_NORM_FALSE_FLAGS["source_bound"] is False
    def mutate(receipt, expected_wire):
        result = serialized(receipt, expected_wire)
        if receipt.get("schema") == native.PARENT_BOUND_NORM_BUILD_SCHEMA and not changed:
            changed.append("final serialized receipt checked")
            monkeypatch.setitem(producer.PARENT_BOUND_NORM_FALSE_FLAGS, "source_bound", 0)
        return result
    monkeypatch.setattr(native, "_parent_norm_native_serialized_fence", mutate)
    with pytest.raises(ValueError):
        _parent_bound_norm_native_build(data, preparation, executable, tmp_path / "parent-bound-policy-drift")
    assert len(calls) == 1 and changed == ["final serialized receipt checked"]


def test_parent_bound_norm_native_instrumented_changed_persistence_callback_is_never_called(
        parent_bound_norm_native_modes, instrumented_parent_bound_norm_replay,
        synthetic_compiler, tmp_path, monkeypatch):
    data, preparation = parent_bound_norm_native_modes["body_with_membership"]
    unexpected = []
    def forbidden(*args, **kwargs):
        unexpected.append("changed persistence callback called")
        raise AssertionError("changed persistence callback must not execute")
    executable, calls = synthetic_compiler(preparation,
        after=lambda: monkeypatch.setattr(native, "_persist_build", forbidden))
    with pytest.raises(ValueError):
        _parent_bound_norm_native_build(data, preparation, executable, tmp_path / "parent-bound-callback-drift")
    assert len(calls) == 1 and unexpected == []


def test_parent_bound_norm_native_instrumented_cleanup_error_keeps_original_owner_handle(
        parent_bound_norm_native_modes, instrumented_parent_bound_norm_replay,
        synthetic_compiler, tmp_path, monkeypatch):
    data, preparation = parent_bound_norm_native_modes["body_with_membership"]
    executable, _ = synthetic_compiler(preparation)
    handle = object()
    original = process.OwnedToolCleanupError(handle, "authored unresolved parent-bound native cleanup")
    def fail(self, request, *, cancellation=None):
        assert request.owned_process_observation is True
        raise original
    monkeypatch.setattr(process.BoundedToolRunner, "run", fail)
    output = tmp_path / "parent-bound-cleanup-refusal"
    with pytest.raises(process.OwnedToolCleanupError) as caught:
        _parent_bound_norm_native_build(data, preparation, executable, output)
    assert caught.value is original and caught.value.cleanup_handle is handle
    receipt = json.loads((output / "build-receipt.json").read_bytes())
    assert receipt["build_passed"] is False and receipt["cleanup_owner_retained_on_exception"] is True
    assert receipt["cleanup_confirmed"] is False and receipt["artifact_sha256"] == {}
    _parent_bound_norm_native_no_promotion(receipt, owned_observation=False)


@pytest.mark.parametrize("damage", ["caller", "receipt"])
def test_parent_bound_norm_native_instrumented_last_helper_return_cannot_change_terminal_custody(
        parent_bound_norm_native_modes, instrumented_parent_bound_norm_replay,
        synthetic_compiler, tmp_path, monkeypatch, damage):
    original, baseline = parent_bound_norm_native_modes["body_with_membership"]
    data, preparation = deepcopy(original), replace(baseline)
    executable, calls = synthetic_compiler(preparation)
    genuine = native._parent_norm_native_serialized_fence
    changed = []
    def mutate(receipt, expected_wire):
        result = genuine(receipt, expected_wire)
        # Target the final native operation stage, not an incidental earlier
        # helper call count. The wrapper itself is held before entry and first
        # delegates the exact genuine helper; only its return causes the drift.
        frame = sys._getframe(1)
        if (receipt.get("schema") == native.PARENT_BOUND_NORM_BUILD_SCHEMA
                and frame.f_code.co_name == "terminal"
                and Path(frame.f_code.co_filename).resolve() == Path(native.__file__).resolve()
                and not changed):
            changed.append("final terminal helper returned")
            if damage == "caller": data["bound_report"]["training_mask"] = False
            else: receipt["preservation_kind"] = "unsupported norm truth promotion"
        return result
    monkeypatch.setattr(native, "_parent_norm_native_serialized_fence", mutate)
    output = tmp_path / "parent-bound-final-helper-drift"
    with pytest.raises(ValueError):
        _parent_bound_norm_native_build(data, preparation, executable, output)
    assert len(calls) == 1 and len(instrumented_parent_bound_norm_replay) == 2
    assert changed == ["final terminal helper returned"]
    saved = json.loads((output / "build-receipt.json").read_bytes())
    assert saved["preservation_kind"] == "definitional_alias_identity_only"
    _parent_bound_norm_native_no_promotion(saved)


@pytest.fixture(scope="module")
def parent_bound_norm_native_actual_modes(bound_norm_installed_lake, tmp_path_factory):
    # Resolve the existing explicit native gate before building any source inputs.
    executable, binary_pins = bound_norm_installed_lake
    modes = _parent_bound_norm_native_cached(
        tmp_path_factory.mktemp("parent-bound-norm-actual-originals", numbered=False))
    return executable, binary_pins, modes


@pytest.mark.parametrize("mode", ["instance_only", "body_with_membership"], ids=["instance", "membership"])
def test_parent_bound_norm_native_installed_lean_builds_each_explicit_mode_with_genuine_replay(
        parent_bound_norm_native_actual_modes, tmp_path, mode):
    executable, binary_pins, modes = parent_bound_norm_native_actual_modes
    data, preparation = modes[mode]
    before = deepcopy(data)
    output = tmp_path / ("native-" + mode)
    # Every call keeps the genuine installed-toolchain probes and peer validator;
    # no validator, producer cache, runner, compiler output or source is replaced.
    receipt = native.build_parent_bound_norm_definition_native_v1(
        preparation, data["bound_report"], **_parent_bound_norm_native_arguments(data, preparation),
        lake_executable=str(executable), output_directory=output, timeout_seconds=60)
    manifest = preparation.to_dict()
    assert receipt["schema"] == native.PARENT_BOUND_NORM_BUILD_SCHEMA
    assert receipt["profile"] == native.PARENT_BOUND_NORM_NATIVE_PROFILE
    assert receipt["build_passed"] is True and receipt["lean_compilation_verified"] is True
    assert receipt["kernel_proofs_checked"] is True and receipt["conditional_proofs_verified"] is True
    assert receipt["native_runtime_verified"] is True and receipt["cleanup_confirmed"] is True
    assert receipt["binary_sha256"] == binary_pins
    assert receipt["expected_modules"] == receipt["compiled_modules"] == manifest["expected_modules"]
    assert len(receipt["compiled_modules"]) == len(receipt["artifact_sha256"]) == 6
    assert len(receipt["executed_project_sha256"]) == 9
    assert len(receipt["conditional_theorems"]) == (2 if mode == "instance_only" else 3)
    assert receipt["theorem_axiom_dependencies"] == {name: [] for name in manifest["conditional_theorems"]}
    assert receipt["bound_definition_report_sha256"] == data["expected_bound_report_sha256"]
    assert receipt["bound_definition_mode"] == mode
    assert receipt["original_preparation_build_eligible"] is False
    assert receipt["preservation_kind"] == "definitional_alias_identity_only"
    _parent_bound_norm_native_no_promotion(receipt)
    _parent_bound_norm_native_readback(output, preparation, data)
    for name, path in receipt["artifact_files"].items():
        raw = (output / path).read_bytes()
        assert raw and sha(raw) == receipt["artifact_sha256"][name]
    assert json.loads((output / "build-receipt.json").read_bytes()) == receipt
    assert data == before


# Reviewed multiunit adapter controls remain explicitly fictional. Existing
# synthetic_compiler supplies authored fake PIDs, bytes and messages; these
# tests never establish an actual native result, legal review or corpus release.
def reviewed_native_fixture_v2():
    from ipfs_datasets_py.logic.autoformal import legal_corpus_shared_lake as shared
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission_owner
    path = Path(__file__).with_name("test_legal_corpus_shared_lake.py")
    spec = importlib.util.spec_from_file_location("_reviewed_native_shared_fixture_v2", path)
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    admission_helper = helper.reviewed_preservation_fixture_helper_v2()
    case = admission_helper.reviewed_norm_fixture_v2(admission_owner)
    control = helper.reviewed_preservation_graph_fixture_v2(admission_helper, admission_owner, case)
    control["preparation"] = helper.reviewed_preservation_prepare_fixture_v2(control)
    control["shared"] = shared; control["shared_helper"] = helper
    return control


@pytest.fixture
def reviewed_native_control_v2():
    return reviewed_native_fixture_v2()


def reviewed_native_arguments_v2(control):
    return dict(expected_preservation_sha256=control["shared"].reviewed_preservation_corpus_sha256(control["preparation"]),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN, **control["kwargs"])


def reviewed_native_validate_v2(control, preparation=None, **overrides):
    return native.validate_reviewed_norm_preservation_native_v2(
        control["preparation"] if preparation is None else preparation, control["graph"], control["admission"],
        *control["args"], **(reviewed_native_arguments_v2(control) | overrides))


def reviewed_native_build_v2(control, executable, output, **overrides):
    return native.build_reviewed_norm_preservation_native_v2(control["preparation"], control["graph"],
        control["admission"], *control["args"], **(reviewed_native_arguments_v2(control) | dict(
            lake_executable=str(executable), output_directory=output, timeout_seconds=12) | overrides))


def reviewed_native_stdout_v2(preparation):
    return "\n".join("'" + name + "' does not depend on any axioms"
        for name in preparation.to_dict()["preservation_obligations"]) + "\n"


def test_reviewed_native_v2_validation_replays_real_owners_without_probing(reviewed_native_control_v2, monkeypatch):
    control = reviewed_native_control_v2
    monkeypatch.setattr(native, "_installed_toolchain", lambda *a, **k: pytest.fail("native probe during preparation validation"))
    monkeypatch.setattr(process.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("native run during preparation validation"))
    assert reviewed_native_validate_v2(control) == control["preparation"]
    assert control["admission"]["fixture_only"] and control["admission"]["provenance_kind"] == "fictional_fixture"
    assert control["admission"]["training_mask"] == control["admission"]["evaluation_gold_mask"] == 0


def test_reviewed_native_v2_authored_boundary_preserves_complete_current_project(
        reviewed_native_control_v2, synthetic_compiler, tmp_path):
    control = reviewed_native_control_v2; prepared = control["preparation"]
    executable, calls = synthetic_compiler(prepared, stdout=reviewed_native_stdout_v2(prepared))
    output = tmp_path / "authored-reviewed-preservation"
    public_pin = control["shared"].reviewed_preservation_corpus_sha256(prepared)
    result = reviewed_native_build_v2(control, executable, output)
    manifest = prepared.to_dict()
    assert len(calls) == 1
    assert result["preparation_full_canonical_sha256"] == public_pin
    assert result["preparation_manifest_sha256"] == sha(prepared.manifest_json.encode("utf-8"))
    assert result["schema"] == native.REVIEWED_PRESERVATION_BUILD_SCHEMA
    assert result["profile"] == native.REVIEWED_PRESERVATION_NATIVE_PROFILE
    assert result["build_passed"] is True  # Authored process boundary, not a real compiler.
    assert result["reviewed_graph_sha256"] == control["graph_sha"]
    assert result["reviewed_admission_sha256"] == control["admission_sha"]
    assert result["units"] == manifest["units"] and result["file_sha256"] == manifest["file_sha256"]
    assert result["conditional_theorems"] == result["preservation_obligations"] == manifest["preservation_obligations"]
    assert len(result["conditional_theorems"]) == 15 and len(result["compiled_modules"]) == 6
    assert result["theorem_axiom_dependencies"] == {name: [] for name in manifest["preservation_obligations"]}
    assert result["preservation_only"] and result["generic_lean_v3_receipt_substituted"] is False
    for flag in ("cross_unit_definition_application_proved", "statutory_meaning_proved", "release_ready",
                 "full_formal_corpus_consistency_verified"):
        assert result[flag] is False
    assert_no_authority(result)
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    assert (output / "project" / "reviewed-input-bindings.json").read_bytes() == dict(prepared.files)["reviewed-input-bindings.json"].encode()
    assert json.loads((output / "build-receipt.json").read_bytes()) == result


@pytest.mark.parametrize("damage", ["graph", "admission", "source", "assumptions", "interpretation", "dependency", "revocation"])
def test_reviewed_native_v2_current_source_and_meaning_replay_precedes_toolchain(
        reviewed_native_control_v2, monkeypatch, tmp_path, damage):
    control = dict(reviewed_native_control_v2, **{key: deepcopy(reviewed_native_control_v2[key])
        for key in ("args", "kwargs", "graph", "admission")})
    if damage == "graph": control["graph"]["scope_record"]["governing_edition"] = "fictional-other-edition"
    elif damage == "admission": control["admission"]["permitted_uses"] = []
    elif damage == "source":
        first = next(iter(control["kwargs"]["preparation_inputs"]["source_inputs"].values()))
        first["raw_bytes"] += b" fictional source change"
    elif damage == "assumptions": control["kwargs"]["preparation_inputs"]["declaration"]["assumptions"].append("fictional extra premise")
    elif damage == "interpretation": control["kwargs"]["preparation_inputs"]["declaration"]["interpretation_id"] = "fixture:other-interpretation"
    elif damage == "dependency":
        first = next(iter(control["kwargs"]["observed_artifact_sha256s"]))
        control["kwargs"]["observed_artifact_sha256s"][first] = "0" * 64
    else: control["kwargs"]["at_time_utc"] = "2099-01-01T00:00:00Z"
    monkeypatch.setattr(native, "_installed_toolchain", lambda *a, **k: pytest.fail("native probe reached before current replay"))
    with pytest.raises(ValueError):
        reviewed_native_build_v2(control, tmp_path / "unopened", tmp_path / "not-created")
    assert not (tmp_path / "not-created").exists()


@pytest.mark.parametrize("damage", ["missing_obligation", "duplicate_obligation", "foreign_obligation", "missing_module", "source_file"])
def test_reviewed_native_v2_resealed_project_cannot_select_favorable_obligations(
        reviewed_native_control_v2, monkeypatch, damage):
    control = reviewed_native_control_v2
    manifest = control["preparation"].to_dict(); files = dict(control["preparation"].files)
    if damage == "missing_obligation": manifest["preservation_obligations"].pop()
    elif damage == "duplicate_obligation": manifest["preservation_obligations"][-1] = manifest["preservation_obligations"][0]
    elif damage == "foreign_obligation": manifest["preservation_obligations"][-1] = "Foreign.unrelated"
    elif damage == "missing_module": manifest["expected_modules"].pop()
    else: files["reviewed-input-bindings.json"] += "\n"
    forged = control["shared_helper"].reviewed_preservation_reseal_fixture_v2(control["preparation"], manifest, files)
    monkeypatch.setattr(native, "_installed_toolchain", lambda *a, **k: pytest.fail("probe reached for forged project"))
    with pytest.raises(ValueError):
        reviewed_native_validate_v2(control, forged,
            expected_preservation_sha256=control["shared"].reviewed_preservation_corpus_sha256(forged))


@pytest.mark.parametrize("damage", ["missing_module", "wrong_source", "missing_report", "duplicate_report", "foreign_report", "nonempty_report"])
def test_reviewed_native_v2_authored_outputs_require_every_bound_module_source_and_obligation(
        reviewed_native_control_v2, synthetic_compiler, tmp_path, damage):
    control = reviewed_native_control_v2; prepared = control["preparation"]
    stdout = reviewed_native_stdout_v2(prepared); names = prepared.to_dict()["preservation_obligations"]
    if damage == "missing_report": stdout = "\n".join(stdout.splitlines()[:-1]) + "\n"
    elif damage == "duplicate_report": stdout += stdout.splitlines()[0] + "\n"
    elif damage == "foreign_report": stdout = stdout.replace(names[-1], "Foreign.unrelated")
    elif damage == "nonempty_report": stdout = stdout.replace("does not depend on any axioms", "depends on axioms: [sorryAx]", 1)
    def edit(outputs, artifacts, sources):
        if damage == "missing_module": outputs.pop(artifacts[-1])
        elif damage == "wrong_source": outputs["reviewed-input-bindings.json"] += b"\n"
    executable, calls = synthetic_compiler(prepared, stdout=stdout, output_edit=edit)
    result = reviewed_native_build_v2(control, executable, tmp_path / ("authored-" + damage))
    assert len(calls) == 1 and result["build_passed"] is False
    assert_no_authority(result)
    assert result["release_ready"] is False and result["full_formal_corpus_consistency_verified"] is False


@pytest.mark.parametrize("changes", [{"returncode": 1}, {"timed_out": True}, {"output_truncated": True},
                                     {"runtime": process.ToolRuntime.JVM}, {"native_lifecycle": None}])
def test_reviewed_native_v2_failed_or_unauthenticated_authored_process_stays_unqualified(
        reviewed_native_control_v2, synthetic_compiler, tmp_path, changes):
    control = reviewed_native_control_v2; prepared = control["preparation"]
    executable, calls = synthetic_compiler(prepared, stdout=reviewed_native_stdout_v2(prepared), result_changes=changes)
    result = reviewed_native_build_v2(control, executable, tmp_path / "authored-failed-native-boundary")
    assert len(calls) == 1 and result["build_passed"] is False
    assert_no_authority(result)
    assert result["release_ready"] is False


def test_reviewed_native_v2_generic_receipt_cannot_impersonate_a_project(monkeypatch):
    with patch.object(native, "_owners", side_effect=AssertionError("lazy owners reached")):
        with pytest.raises(ValueError, match="typed reviewed preservation"):
            native.validate_reviewed_norm_preservation_native_v2({"schema_version": "lean-kernel-receipt/v3", "accepted": True},
                {}, {}, {}, {}, {}, {}, expected_preservation_sha256="1" * 64,
                expected_graph_sha256="2" * 64, expected_admission_sha256="3" * 64, toolchain=TOOLCHAIN)


@pytest.mark.parametrize("timeout", [0, -1, 61, float("nan"), True])
def test_reviewed_native_v2_resource_bounds_refuse_before_lazy_owners(timeout):
    with patch.object(native, "_owners", side_effect=AssertionError("lazy owners reached")):
        with pytest.raises(ValueError):
            native.build_reviewed_norm_preservation_native_v2(None, {}, {},
                expected_preservation_sha256="1" * 64, expected_graph_sha256="2" * 64,
                expected_admission_sha256="3" * 64, toolchain=TOOLCHAIN,
                lake_executable="unopened", output_directory="unused", timeout_seconds=timeout)


def test_reviewed_native_v2_valid_other_interpretation_project_cannot_replace_readbacks(
        reviewed_native_control_v2, synthetic_compiler, tmp_path):
    control = reviewed_native_control_v2
    alternative = reviewed_native_fixture_v2()
    declaration = alternative["case"]["declaration"]
    declaration["interpretation_id"] = "fixture:explicit-alternative-interpretation"
    for use in declaration["definition_uses"]:
        use["interpretation_id"] = declaration["interpretation_id"]
    helper = alternative["shared_helper"]
    helper.reviewed_preservation_reauthorize_fixture_v2(alternative["helper"], alternative["owner"], alternative["case"])
    other = helper.reviewed_preservation_graph_fixture_v2(alternative["helper"], alternative["owner"], alternative["case"])
    other["shared"] = alternative["shared"]; other["shared_helper"] = helper
    other["preparation"] = helper.reviewed_preservation_prepare_fixture_v2(other)
    assert reviewed_native_validate_v2(other) == other["preparation"]
    assert other["preparation"] != control["preparation"]
    other_files = dict(other["preparation"].files)
    def mixup(outputs, artifacts, sources):
        # Both independently valid projects use the same theorem/module names.
        # Authored "proof success" must not replace exact project-source custody.
        assert set(other_files) == set(sources)
        outputs.update({name: text.encode("utf-8") for name, text in other_files.items()})
    prepared = control["preparation"]
    executable, calls = synthetic_compiler(prepared, stdout=reviewed_native_stdout_v2(prepared), output_edit=mixup)
    result = reviewed_native_build_v2(control, executable, tmp_path / "authored-valid-A-with-valid-B-readbacks")
    assert len(calls) == 1 and result["build_passed"] is False
    assert result["executed_project_readback_passed"] is False and result["release_ready"] is False


def test_reviewed_native_v2_late_current_evidence_mutation_retains_failed_observation(
        reviewed_native_control_v2, synthetic_compiler, tmp_path):
    control = reviewed_native_control_v2; prepared = control["preparation"]
    def change():
        control["kwargs"]["at_time_utc"] = "2099-01-01T00:00:00Z"
    executable, calls = synthetic_compiler(prepared, stdout=reviewed_native_stdout_v2(prepared), after=change)
    output = tmp_path / "authored-late-review-change"
    with pytest.raises(ValueError):
        reviewed_native_build_v2(control, executable, output)
    retained = json.loads((output / "build-receipt.json").read_bytes())
    assert len(calls) == 1 and retained["build_passed"] is False
    assert retained["post_run_validation_passed"] is False
    assert retained["post_run_custody_error"]
    assert (output / "project" / "reviewed-input-bindings.json").read_bytes() == dict(prepared.files)["reviewed-input-bindings.json"].encode()


def test_reviewed_native_v2_binary_change_and_cancellation_reuse_original_runner_boundary(
        reviewed_native_control_v2, synthetic_compiler, tmp_path):
    control = reviewed_native_control_v2; prepared = control["preparation"]
    signal = object()
    target = None
    def change_binary():
        target.write_bytes(target.read_bytes() + b" authored change")
    executable, calls = synthetic_compiler(prepared, stdout=reviewed_native_stdout_v2(prepared),
        after=change_binary, cancellation=signal)
    target = executable
    result = reviewed_native_build_v2(control, executable, tmp_path / "authored-changed-binary", cancellation=signal)
    assert len(calls) == 1 and result["build_passed"] is False
    assert result["binaries_unchanged"] is False and result["release_ready"] is False


# Pure receipt projection is deliberately weaker than historical execution
# evidence. These authored objects are not returned by a real subprocess.
def reviewed_execution_projection_fixture_v2():
    request = process.ToolRunRequest(argv=("authored-lake", "--offline", "--no-cache", "build", "legal"),
        input_files={"Main.lean": "-- explicitly authored transport fixture\n"},
        output_paths=("Main.lean", ".lake/build/lib/lean/Authored.olean"),
        environment={"ELAN_TOOLCHAIN": TOOLCHAIN, "LEAN_NUM_THREADS": "1"},
        owned_process_observation=True,
        limits=process.ToolRunLimits(timeout_seconds=12, cpu_seconds=12,
            resident_memory_bytes=2 * 1024**3, max_output_bytes=2 * 1024**2,
            max_input_bytes=8 * 1024**2, max_workspace_bytes=128 * 1024**2, max_output_files=2))
    outputs = {"Main.lean": request.input_files["Main.lean"].encode("utf-8"),
        ".lake/build/lib/lean/Authored.olean": b"\x00\xff\x80binary authored fixture\x00"}
    run = process.ToolRunResult(interface_version="authored-fixture-result/v1", runtime=process.ToolRuntime.NATIVE,
        command=request.argv, returncode=0, stdout="authored unicode \u00b5\n", stderr="", error="", elapsed_seconds=0.01,
        output_files=outputs, pid=123, native_lifecycle=lifecycle())
    logs = {"stdout.txt": run.stdout.encode("utf-8"), "stderr.txt": b"", "runner-error.txt": b""}
    projection = native._reviewed_native_execution_projection(request, run, process)
    return request, run, projection, dict(request.input_files), outputs, logs


def test_reviewed_execution_projection_losslessly_restores_binary_bytes_without_running_tools(monkeypatch):
    monkeypatch.setattr(process.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("tool execution from pure decoder"))
    request, run, projection, sources, outputs, logs = reviewed_execution_projection_fixture_v2()
    sources = {name: body.encode("utf-8") for name, body in sources.items()}
    restored_request, restored = native._reviewed_native_execution_from_projection(projection,
        sources=sources, outputs=outputs, logs=logs, process=process)
    assert restored_request.argv == request.argv
    assert restored.stdout == run.stdout and dict(restored.output_files) == outputs
    assert restored.output_files[".lake/build/lib/lean/Authored.olean"] == b"\x00\xff\x80binary authored fixture\x00"
    assert projection["result"]["interface_version"] == "authored-fixture-result/v1"
    assert native._reviewed_native_execution_projection(restored_request, restored, process) == projection
    assert set(projection) == {"schema", "invocation", "result", "raw_logs", "output_file_refs"}
    assert "accepted" not in projection and "qualified" not in projection and "build_passed" not in projection


@pytest.mark.parametrize("damage", ["extra_field", "extra_result_field", "missing_limit", "wrong_boolean",
    "wrong_command_type", "unowned", "binary_bytes", "source_bytes", "raw_log", "derived_cleanup"])
def test_reviewed_execution_projection_refuses_partial_or_malformed_transport_without_authority(damage):
    request, run, projection, sources, outputs, logs = reviewed_execution_projection_fixture_v2()
    sources = {name: body.encode("utf-8") for name, body in sources.items()}
    projection = deepcopy(projection)
    if damage == "extra_field": projection["build_passed"] = True
    elif damage == "extra_result_field": projection["result"]["trusted"] = True
    elif damage == "missing_limit": projection["invocation"]["limits"].pop("max_input_bytes")
    elif damage == "wrong_boolean": projection["result"]["cancelled"] = 0
    elif damage == "wrong_command_type": projection["result"]["command"] = [1]
    elif damage == "unowned": projection["invocation"]["owned_process_observation"] = False
    elif damage == "binary_bytes": outputs = dict(outputs, **{".lake/build/lib/lean/Authored.olean": b"different"})
    elif damage == "source_bytes": sources["Main.lean"] += b" changed"
    elif damage == "raw_log": logs["stdout.txt"] += b" changed"
    else: projection["result"]["native_lifecycle"]["cleanup_confirmed"] = False
    with pytest.raises(ValueError):
        native._reviewed_native_execution_from_projection(projection,
            sources=sources, outputs=outputs, logs=logs, process=process)


@pytest.mark.parametrize("damage", ["unknown", "parent_bool", "identity_bool", "readers", "workspace",
                                    "duplicate_identity", "containment", "derived_cleanup"])
def test_reviewed_lifecycle_decoder_preserves_closed_sampled_scope(damage):
    value = lifecycle(observed_descendants=(identity(124),)).to_dict()
    if damage == "unknown": value["approved"] = True
    elif damage == "parent_bool": value["parent"]["birth_ticks"] = True
    elif damage == "identity_bool": value["leader"]["pid"] = True
    elif damage == "readers": value["readers"]["joined"] = 3
    elif damage == "workspace": value["workspace"]["inode"] = 0
    elif damage == "duplicate_identity": value["observed_descendants"].append(deepcopy(value["observed_descendants"][0]))
    elif damage == "containment": value["kernel_containment_attested"] = True
    else: value["cleanup_confirmed"] = False
    with pytest.raises(ValueError):
        native._reviewed_native_lifecycle_from_dict(value, process)


def test_reviewed_lifecycle_decoder_retains_honest_incomplete_cleanup_without_promoting_it():
    value = lifecycle(readers_joined=1).to_dict()
    assert value["cleanup_confirmed"] is False
    restored = native._reviewed_native_lifecycle_from_dict(value, process)
    assert restored.to_dict() == value and restored.cleanup_confirmed is False
    # The live identity/group check and cleanup are separate requirements.
    assert native._observed_process_scope(restored, 123, process) is True


def test_reviewed_execution_projection_whole_bound_precedes_raw_hashing(monkeypatch):
    request, run, projection, sources, outputs, logs = reviewed_execution_projection_fixture_v2()
    sources = {name: body.encode("utf-8") for name, body in sources.items()}
    monkeypatch.setattr(native, "MAX_INPUT_BYTES", 128)
    monkeypatch.setattr(native, "_sha", lambda *a, **k: pytest.fail("raw hashing before whole-input refusal"))
    with pytest.raises(ValueError):
        native._reviewed_native_execution_from_projection(projection,
            sources=sources, outputs=outputs, logs=logs, process=process)


def test_reviewed_native_v2_projection_refusal_retains_failed_frozen_artifacts(
        reviewed_native_control_v2, synthetic_compiler, monkeypatch, tmp_path):
    control = reviewed_native_control_v2; prepared = control["preparation"]
    executable, calls = synthetic_compiler(prepared, stdout=reviewed_native_stdout_v2(prepared))
    def refuse(*args, **kwargs):
        raise ValueError("authored projection refusal")
    monkeypatch.setattr(native, "_reviewed_native_execution_projection", refuse)
    output = tmp_path / "authored-projection-refusal"
    result = reviewed_native_build_v2(control, executable, output)
    assert len(calls) == 1 and result["build_passed"] is False
    assert result["reviewed_execution_evidence"] is None
    assert result["reviewed_execution_projection_error"]["type"] == "ValueError"
    assert json.loads((output / "build-receipt.json").read_bytes()) == result
    assert (output / "stdout.txt").read_bytes() == reviewed_native_stdout_v2(prepared).encode()
    assert result["release_ready"] is False and result["cross_unit_definition_application_proved"] is False


# Regression controls for the public shared-preparer hash recipe. The fixture
# below is produced by the real preparation owner from explicitly fictional
# reviewed inputs; the synthetic runner remains authored, never native proof.
def test_reviewed_native_v2_uses_exact_public_raw_manifest_envelope(reviewed_native_control_v2):
    control = reviewed_native_control_v2
    prepared = control["preparation"]
    shared = control["shared"]
    assert type(prepared) is shared.ReviewedPreservationCorpusPreparation
    document = native._reviewed_preservation_native_document(prepared)
    assert document == {"manifest_json": prepared.manifest_json,
        "files": [[name, body] for name, body in prepared.files]}
    public_pin = shared.reviewed_preservation_corpus_sha256(prepared)
    assert native._sha(native._wire(document, native.MAX_PREPARATION_BYTES)) == public_pin
    # The previous parsed-object recipe is a different identity domain.
    parsed = {"manifest": prepared.to_dict(), "files": document["files"]}
    assert native._sha(native._wire(parsed, native.MAX_PREPARATION_BYTES)) != public_pin
    assert reviewed_native_validate_v2(control) == prepared


@pytest.mark.parametrize("damage", ["raw_manifest", "one_file"])
def test_reviewed_native_v2_raw_envelope_changes_refuse_before_owners_or_tool(
        reviewed_native_control_v2, monkeypatch, tmp_path, damage):
    control = reviewed_native_control_v2
    prepared = control["preparation"]
    if damage == "raw_manifest":
        changed = type(prepared)(prepared.manifest_json + " ", prepared.files)
        assert changed.to_dict() == prepared.to_dict()  # Same parsed semantics, different raw bytes.
    else:
        files = list(prepared.files)
        files[0] = (files[0][0], files[0][1] + "\n")
        changed = type(prepared)(prepared.manifest_json, tuple(files))
    assert control["shared"].reviewed_preservation_corpus_sha256(changed) != (
        control["shared"].reviewed_preservation_corpus_sha256(prepared))
    monkeypatch.setattr(native, "_owners", lambda: pytest.fail("lazy owners reached before raw envelope pin refusal"))
    monkeypatch.setattr(process.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("tool reached for changed raw envelope"))
    changed_control = dict(control, preparation=changed)
    output = tmp_path / ("not-created-" + damage)
    with pytest.raises(ValueError, match="independent complete reviewed preservation preparation pin differs"):
        reviewed_native_build_v2(changed_control, tmp_path / "unopened", output,
            expected_preservation_sha256=control["shared"].reviewed_preservation_corpus_sha256(prepared))
    assert not output.exists()


# Fictional persisted-replay controls extend the existing reviewed native
# fixtures. The authored compiler remains fake and no success is authenticated.
def reviewed_retained_freeze_fixture_data_v2(value):
    """Immutable authored-fixture snapshot; no validator or result cache."""
    if type(value) is dict:
        assert all(type(key) is str for key in value)
        return ("dict", tuple((key, reviewed_retained_freeze_fixture_data_v2(item))
            for key, item in value.items()))
    if type(value) is list:
        return ("list", tuple(reviewed_retained_freeze_fixture_data_v2(item) for item in value))
    if type(value) is tuple:
        return ("tuple", tuple(reviewed_retained_freeze_fixture_data_v2(item) for item in value))
    assert type(value) in (str, bytes, int, float, bool, type(None))
    return ("atom", value)


def reviewed_retained_thaw_fixture_data_v2(value):
    kind, payload = value
    if kind == "dict":
        return {key: reviewed_retained_thaw_fixture_data_v2(item) for key, item in payload}
    if kind == "list":
        return [reviewed_retained_thaw_fixture_data_v2(item) for item in payload]
    if kind == "tuple":
        return tuple(reviewed_retained_thaw_fixture_data_v2(item) for item in payload)
    assert kind == "atom" and type(payload) in (str, bytes, int, float, bool, type(None))
    return payload


@pytest.fixture(scope="module")
def reviewed_retained_packet_seed_fixture_v2(tmp_path_factory):
    """Build one fictional packet, then restore the real tool boundaries.

    Only immutable bytes/tuples and existing frozen preparations/signers are
    retained as fixture data. Source owner modules remain shared environment
    bindings; every selected test still runs the complete current replay.
    """
    directory = tmp_path_factory.mktemp("reviewed-retained-positive-seed", numbered=False)
    original_run = process.BoundedToolRunner.run
    original_toolchain = native._installed_toolchain
    with pytest.MonkeyPatch.context() as patcher:
        control = reviewed_native_fixture_v2()
        install = synthetic_compiler.__wrapped__(patcher, directory)
        executable, calls = install(control["preparation"],
            stdout=reviewed_native_stdout_v2(control["preparation"]))
        output = directory / "fictional-reviewed-retained-packet"
        receipt = reviewed_native_build_v2(control, executable, output)
        packet = tuple(sorted((str(path.relative_to(output)), path.read_bytes())
            for path in output.rglob("*") if path.is_file()))
        assert len(calls) == 1
        call_evidence = tuple(calls)
    assert process.BoundedToolRunner.run is original_run
    assert native._installed_toolchain is original_toolchain

    # Modules cannot be deep-copied. Their pinned source identities are replayed
    # normally. The preparation/signers are already frozen dataclasses; private
    # signing keys are never copied or used by the retained-replay tests.
    fixed_names = ("helper", "owner", "shared", "shared_helper", "preparation")
    environment = tuple((name, control[name]) for name in fixed_names)
    case = dict(control["case"])
    signers = tuple(case.pop("signers"))
    assert all(type(signer).__dataclass_params__.frozen for signer in signers)
    assert type(control["preparation"]).__dataclass_params__.frozen
    data = {name: value for name, value in control.items() if name not in fixed_names}
    data["case"] = case
    snapshot = reviewed_retained_freeze_fixture_data_v2({"control": data, "receipt": receipt})
    return environment, snapshot, signers, packet, call_evidence


def reviewed_retained_case_from_seed_fixture_v2(seed):
    environment, snapshot, signers, packet, call_evidence = seed
    # One deep copy covers all mutable authored inputs and the receipt. No
    # test receives the immutable positive seed's original mutable objects.
    copied = deepcopy(reviewed_retained_thaw_fixture_data_v2(snapshot))
    control = dict(environment)
    control.update(copied["control"])
    control["case"]["signers"] = list(signers)
    return control, copied["receipt"], packet, call_evidence


@pytest.fixture
def reviewed_retained_packet_fixture_v2(reviewed_retained_packet_seed_fixture_v2):
    return reviewed_retained_case_from_seed_fixture_v2(reviewed_retained_packet_seed_fixture_v2)


def reviewed_retained_replay_arguments_v2(control, receipt, packet):
    return reviewed_native_arguments_v2(control) | dict(
        expected_receipt_sha256=sha(dict(packet)["build-receipt.json"]),
        expected_packet_sha256=native.reviewed_norm_preservation_packet_sha256_v2(packet),
        expected_binary_sha256=deepcopy(receipt["binary_sha256"]),
        observation_profile="fictional-authored-observation/v1")


def reviewed_retained_reopen_v2(control, receipt, packet, **changes):
    return native.load_reviewed_norm_preservation_native_v2(packet, control["preparation"],
        control["graph"], control["admission"], *control["args"],
        **(reviewed_retained_replay_arguments_v2(control, receipt, packet) | changes))


def reviewed_retained_no_tools_v2(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("retained replay must not probe or execute a native tool")
    monkeypatch.setattr(native, "_installed_toolchain", forbidden)
    monkeypatch.setattr(process.BoundedToolRunner, "run", forbidden)


def test_reviewed_retained_replay_reopens_all_binary_sidecars_with_zero_authority(
        reviewed_retained_packet_fixture_v2, monkeypatch):
    control, receipt, packet, calls = reviewed_retained_packet_fixture_v2
    before = deepcopy((control["graph"], control["admission"], receipt, packet))
    reviewed_retained_no_tools_v2(monkeypatch)
    assert native.reviewed_norm_preservation_receipt_bytes_v2(receipt) == dict(packet)["build-receipt.json"]
    result = reviewed_retained_reopen_v2(control, receipt, packet)
    assert len(calls) == 1
    assert result["retained_observations_consistent"] is True
    assert result["current_complete_semantics_replayed"] is True
    assert result["obligations"] == control["preparation"].to_dict()["preservation_obligations"]
    assert len(result["packet_inventory"]) == len(packet)
    assert result["observation_profile"] == "fictional-authored-observation/v1"
    for name in ("original_success_authenticated", "native_execution_authenticated", "native_execution_performed",
                 "olean_kernel_rechecked", "release_ready", "Lean_admitted", "proof_checked", "backend_executed"):
        assert result[name] is False
    assert result["missing_prerequisites"] and all(v is False for v in result["authority"].values())
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    assert (control["graph"], control["admission"], receipt, packet) == before


def test_reviewed_retained_default_does_not_relabel_an_authored_interface_as_native(
        reviewed_retained_packet_fixture_v2, monkeypatch):
    control, receipt, packet, calls = reviewed_retained_packet_fixture_v2
    reviewed_retained_no_tools_v2(monkeypatch)
    with pytest.raises(ValueError):
        reviewed_retained_reopen_v2(control, receipt, packet,
            observation_profile="retained-native-observation/v1")
    assert len(calls) == 1


@pytest.mark.parametrize("damage", ["schema", "profile", "runtime", "scope", "assumptions", "graph",
    "producer", "obligation", "axiom", "toolchain", "binary", "lifecycle", "artifact_bool",
    "success_boolean", "training_bool", "elapsed_bool", "log_float"])
def test_reviewed_retained_resealed_receipt_cannot_replace_semantics_or_authenticate_success(
        reviewed_retained_packet_fixture_v2, monkeypatch, damage):
    control, receipt, packet, calls = reviewed_retained_packet_fixture_v2
    changed = deepcopy(receipt)
    if damage == "schema": changed["schema"] = "legal-corpus-parent-definition-use-native-build/v1"
    elif damage == "profile": changed["profile"] = "foreign/native/v99"
    elif damage == "runtime": changed["runtime"] = "docker"
    elif damage == "scope": changed["scope"] = "statutory truth proved"
    elif damage == "assumptions": changed["formal_assumptions"].append("fictional extra premise")
    elif damage == "graph": changed["reviewed_graph_sha256"] = "0" * 64
    elif damage == "producer": changed["producer_pins"][next(iter(changed["producer_pins"]))] = "0" * 64
    elif damage == "obligation": changed["conditional_theorems"].pop()
    elif damage == "axiom": changed["theorem_axiom_dependencies"][next(iter(changed["theorem_axiom_dependencies"]))] = ["propext"]
    elif damage == "toolchain": changed["toolchain"] = "leanprover/lean4:v0.0.0"
    elif damage == "binary": changed["binary_sha256"][next(iter(changed["binary_sha256"]))] = "0" * 64
    elif damage == "lifecycle": changed["native_lifecycle"]["parent"]["birth_ticks"] = 2
    elif damage == "artifact_bool": changed["artifact_bytes"][next(iter(changed["artifact_bytes"]))] = True
    elif damage == "success_boolean": changed["original_success_authenticated"] = True
    elif damage == "training_bool": changed["training_mask"] = False
    elif damage == "elapsed_bool": changed["elapsed_seconds"] = True
    else: changed["log_bytes"]["stderr.txt"] = 0.0
    changed = contracts.seal_record({k: v for k, v in changed.items() if k not in {"record_cid", "cid_scope"}})
    contents = dict(packet); contents["build-receipt.json"] = native._wire(changed, native.MAX_RECEIPT_BYTES)
    packet = tuple(sorted(contents.items()))
    reviewed_retained_no_tools_v2(monkeypatch)
    with pytest.raises(ValueError):
        # Both external commitments are freshly recomputed deliberately: the
        # closed replay must still refuse semantically inconsistent self-seals.
        reviewed_retained_reopen_v2(control, receipt, packet)
    assert len(calls) == 1


@pytest.mark.parametrize("damage", ["missing_binary", "foreign_file", "changed_source", "changed_manifest",
                                    "missing_log", "changed_log", "duplicate_path", "duplicate_json", "wrong_packet_pin"])
def test_reviewed_retained_packet_requires_complete_original_bytes_and_closed_transport(
        reviewed_retained_packet_fixture_v2, monkeypatch, damage):
    control, receipt, packet, calls = reviewed_retained_packet_fixture_v2
    contents = dict(packet)
    if damage == "missing_binary": del contents[next(k for k in contents if k.startswith("compiled/"))]
    elif damage == "foreign_file": contents["compiled/Foreign.olean"] = b"foreign artifact"
    elif damage == "changed_source": contents[next(k for k in contents if k.startswith("executed-inputs/"))] += b"\n--changed"
    elif damage == "changed_manifest": contents["project/corpus-manifest.json"] += b" "
    elif damage == "missing_log": del contents["stderr.txt"]
    elif damage == "changed_log": contents["stdout.txt"] += b"foreign report\n"
    elif damage == "duplicate_json": contents["build-receipt.json"] = b'{"schema":"duplicate",' + contents["build-receipt.json"][1:]
    packet = tuple(sorted(contents.items()))
    if damage == "duplicate_path": packet = packet + (packet[-1],)
    reviewed_retained_no_tools_v2(monkeypatch)
    with pytest.raises(ValueError):
        changes = {"expected_packet_sha256": "0" * 64} if damage == "wrong_packet_pin" else {}
        reviewed_retained_reopen_v2(control, receipt, packet, **changes)
    assert len(calls) == 1


@pytest.mark.parametrize("damage", ["graph", "admission", "source", "assumptions", "interpretation", "dependency", "revocation"])
def test_reviewed_retained_reopen_replays_current_source_review_and_revocation(
        reviewed_retained_packet_fixture_v2, monkeypatch, damage):
    original, receipt, packet, calls = reviewed_retained_packet_fixture_v2
    control = dict(original, **{key: deepcopy(original[key]) for key in ("args", "kwargs", "graph", "admission")})
    if damage == "graph": control["graph"]["scope_record"]["governing_edition"] = "fictional-other-edition"
    elif damage == "admission": control["admission"]["permitted_uses"] = []
    elif damage == "source": next(iter(control["kwargs"]["preparation_inputs"]["source_inputs"].values()))["raw_bytes"] += b"fictional source change"
    elif damage == "assumptions": control["kwargs"]["preparation_inputs"]["declaration"]["assumptions"].append("fictional extra premise")
    elif damage == "interpretation": control["kwargs"]["preparation_inputs"]["declaration"]["interpretation_id"] = "fixture:changed"
    elif damage == "dependency": control["kwargs"]["observed_artifact_sha256s"][next(iter(control["kwargs"]["observed_artifact_sha256s"]))] = "0" * 64
    else: control["kwargs"]["at_time_utc"] = "2099-01-01T00:00:00Z"
    reviewed_retained_no_tools_v2(monkeypatch)
    with pytest.raises(ValueError): reviewed_retained_reopen_v2(control, receipt, packet)
    assert len(calls) == 1


def test_reviewed_retained_rechecks_late_dependency_changes_after_byte_and_proof_replay(
        reviewed_retained_packet_fixture_v2, monkeypatch):
    control, receipt, packet, calls = reviewed_retained_packet_fixture_v2
    original = native._axiom_observations
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        pins = control["kwargs"]["observed_artifact_sha256s"]
        pins[next(iter(pins))] = "0" * 64
        return result
    monkeypatch.setattr(native, "_axiom_observations", changed)
    reviewed_retained_no_tools_v2(monkeypatch)
    with pytest.raises(ValueError): reviewed_retained_reopen_v2(control, receipt, packet)
    assert len(calls) == 1



def test_reviewed_retained_shared_packet_isolates_mutable_inputs_and_replays_each_copy(
        reviewed_retained_packet_seed_fixture_v2, monkeypatch):
    first, first_receipt, packet, calls = reviewed_retained_case_from_seed_fixture_v2(
        reviewed_retained_packet_seed_fixture_v2)
    second, second_receipt, second_packet, second_calls = reviewed_retained_case_from_seed_fixture_v2(
        reviewed_retained_packet_seed_fixture_v2)
    before = deepcopy((second["args"], second["kwargs"], second["graph"], second["admission"], second_receipt))
    assert all(first[name] is not second[name] for name in ("args", "kwargs", "graph", "admission", "case"))
    assert first_receipt is not second_receipt
    assert packet is second_packet and calls is second_calls and type(packet) is type(calls) is tuple
    assert len(calls) == 1
    with pytest.raises(TypeError):
        calls[0].environment["ELAN_TOOLCHAIN"] = "fixture:must-remain-immutable"
    first["args"][1]["revoked_principals"].append("fixture:cross-copy-revocation")
    first["kwargs"]["observed_artifact_sha256s"][next(iter(first["kwargs"]["observed_artifact_sha256s"]))] = "0" * 64
    first["graph"]["scope_record"]["governing_edition"] = "fixture:cross-copy-edition"
    first["admission"]["permitted_uses"] = []
    first["case"]["signers"].clear()
    first_receipt["scope"] = "fixture:cross-copy-receipt"
    assert (second["args"], second["kwargs"], second["graph"], second["admission"], second_receipt) == before
    reviewed_retained_no_tools_v2(monkeypatch)
    with pytest.raises(ValueError):
        reviewed_retained_reopen_v2(first, first_receipt, packet)
    result = reviewed_retained_reopen_v2(second, second_receipt, second_packet)
    assert result["current_complete_semantics_replayed"] is True
    assert result["original_success_authenticated"] is False
    assert result["native_execution_authenticated"] is False
    third, third_receipt, third_packet, third_calls = reviewed_retained_case_from_seed_fixture_v2(
        reviewed_retained_packet_seed_fixture_v2)
    assert (third["args"], third["kwargs"], third["graph"], third["admission"], third_receipt) == before
    assert third_packet is packet and third_calls is calls



def test_reviewed_retained_installed_lean_build_reopens_original_sidecars(
        bound_norm_installed_lake, tmp_path, monkeypatch):
    executable, binary_pins = bound_norm_installed_lake
    control = reviewed_native_fixture_v2()
    preparation = control["preparation"]
    manifest = preparation.to_dict()
    assert control["admission"]["fixture_only"] is True
    assert control["admission"]["provenance_kind"] == "fictional_fixture"
    before = deepcopy((control["graph"], control["admission"]))

    import tomllib
    library, = tomllib.loads(dict(preparation.files)["lakefile.toml"])["lean_lib"]
    assert library["name"] == "legal"
    assert library["roots"] == manifest["expected_modules"]
    assert len(library["roots"]) == len(set(library["roots"])) == 6

    output = tmp_path / "reviewed-retained-installed-lean"
    receipt = reviewed_native_build_v2(control, executable, output, timeout_seconds=60)
    # The builder persists the receipt and sidecars before returning. Preserve
    # its original files even if a native or replay assertion fails.
    receipt_raw = (output / "build-receipt.json").read_bytes()
    assert receipt["build_passed"] is receipt["kernel_proofs_checked"] is True
    assert receipt["native_runtime_verified"] is receipt["cleanup_confirmed"] is True
    assert receipt["binary_sha256"] == binary_pins
    assert receipt["expected_modules"] == receipt["compiled_modules"] == manifest["expected_modules"]
    obligations = manifest["preservation_obligations"]
    assert len(obligations) == 5 * len(manifest["units"])
    assert receipt["conditional_theorems"] == obligations
    assert receipt["theorem_axiom_dependencies"] == {name: [] for name in obligations}
    assert receipt["provenance_kind"] == "fictional_fixture"
    assert receipt["preservation_only"] is True
    assert all(receipt[name] is False for name in ("statutory_meaning_proved", "release_ready",
                                                   "cross_unit_definition_application_proved"))
    assert all(value is False for value in receipt["authority"].values())
    expected_receipt_raw = native.reviewed_norm_preservation_receipt_bytes_v2(receipt)
    assert receipt_raw == expected_receipt_raw

    packet = tuple(sorted((path.relative_to(output).as_posix(), path.read_bytes())
                          for path in output.rglob("*") if path.is_file()))
    packet_sha256 = native.reviewed_norm_preservation_packet_sha256_v2(packet)
    with monkeypatch.context() as replay_only:
        reviewed_retained_no_tools_v2(replay_only)
        replay = native.load_reviewed_norm_preservation_native_v2(
            packet, preparation, control["graph"], control["admission"], *control["args"],
            **reviewed_native_arguments_v2(control),
            expected_receipt_sha256=sha(expected_receipt_raw), expected_packet_sha256=packet_sha256,
            expected_binary_sha256=binary_pins)
    assert replay["observation_profile"] == "retained-native-observation/v1"
    assert replay["retained_observations_consistent"] is True
    assert replay["current_complete_semantics_replayed"] is True
    assert replay["obligations"] == obligations
    assert replay["packet_inventory"] == [
        {"path": name, "bytes": len(raw), "sha256": sha(raw)} for name, raw in packet]
    assert all(replay[name] is False for name in (
        "original_success_authenticated", "native_execution_authenticated", "native_execution_performed",
        "olean_kernel_rechecked", "release_ready", "Lean_admitted", "proof_checked", "backend_executed"))
    assert all(value is False for value in replay["authority"].values())
    assert replay["training_mask"] == replay["evaluation_gold_mask"] == 0
    assert (control["graph"], control["admission"]) == before


# Live reviewed-native custody extends the existing owner. These controls do
# not mint synthetic success handles. Genuine positives are opt-in through the
# existing installed-Lean fixture and retain the original on-disk packet.
def reviewed_live_success_build_v2(control, executable, output, **changes):
    return native.build_verified_reviewed_norm_preservation_native_v2(
        control["preparation"], control["graph"], control["admission"], *control["args"],
        **(reviewed_native_arguments_v2(control) | dict(lake_executable=str(executable),
            output_directory=output, timeout_seconds=60) | changes))


def reviewed_live_success_arguments_v2(control, packet, **changes):
    receipt_raw = dict(packet)["build-receipt.json"]
    receipt = json.loads(receipt_raw)
    return reviewed_native_arguments_v2(control) | dict(
        expected_receipt_sha256=sha(receipt_raw),
        expected_packet_sha256=native.reviewed_norm_preservation_packet_sha256_v2(packet),
        expected_binary_sha256=deepcopy(receipt["binary_sha256"])) | changes


def reviewed_live_success_load_v2(control, handle, packet, **changes):
    return native.load_verified_reviewed_norm_preservation_native_v2(handle, packet,
        control["preparation"], control["graph"], control["admission"], *control["args"],
        **reviewed_live_success_arguments_v2(control, packet, **changes))


def reviewed_live_success_packet_v2(output):
    return tuple(sorted((path.relative_to(output).as_posix(), path.read_bytes())
        for path in output.rglob("*") if path.is_file()))


def reviewed_live_success_copy_control_v2(control, packet):
    # Reuse the existing immutable seed codec and copy owner. Signing handles
    # and frozen preparations stay unchanged; every ordinary input is copied.
    fixed = ("helper", "owner", "shared", "shared_helper", "preparation")
    environment = tuple((name, control[name]) for name in fixed)
    case = dict(control["case"])
    signers = tuple(case.pop("signers"))
    data = {name: value for name, value in control.items() if name not in fixed}
    data["case"] = case
    snapshot = reviewed_retained_freeze_fixture_data_v2({"control": data,
        "receipt": json.loads(dict(packet)["build-receipt.json"])})
    copied, _, retained, _ = reviewed_retained_case_from_seed_fixture_v2(
        (environment, snapshot, signers, packet, ()))
    assert retained is packet
    return copied


@pytest.mark.parametrize("offered", ["none", "object", "dict", "json", "unissued", "tool-result"])
def test_reviewed_live_success_rejects_unissued_before_owners(monkeypatch, offered):
    # The None case is a genuine RED for the missing public refusal route. No
    # new class lookup occurs at collection, and no execution owner is entered.
    if offered == "none": value = None
    elif offered == "object": value = object()
    elif offered == "dict": value = {"build_passed": True, "original_success_authenticated": True}
    elif offered == "json": value = json.loads('{"build_passed":true,"native_execution_authenticated":true}')
    elif offered == "unissued": value = object.__new__(native.VerifiedReviewedPreservationNativeSuccess)
    else: value = process.ToolRunResult(interface_version="synthetic-unit-boundary/v1",
        runtime=process.ToolRuntime.NATIVE, command=("unopened",), returncode=0,
        stdout="", stderr="", elapsed_seconds=0.0, output_files={}, pid=123,
        native_lifecycle=lifecycle(), workspace_cleaned=True)
    def forbidden(*args, **kwargs):
        pytest.fail("unissued live success reached a replay or execution owner")
    monkeypatch.setattr(native, "_owners", forbidden)
    with pytest.raises(ValueError):
        native.load_verified_reviewed_norm_preservation_native_v2(value, (), None, {}, {},
            expected_preservation_sha256="1" * 64, expected_graph_sha256="2" * 64,
            expected_admission_sha256="3" * 64, expected_receipt_sha256="4" * 64,
            expected_packet_sha256="5" * 64, expected_binary_sha256={}, toolchain=TOOLCHAIN)


def test_reviewed_live_success_constructor_and_serialized_data_cannot_issue_custody():
    with pytest.raises((TypeError, ValueError)):
        native.VerifiedReviewedPreservationNativeSuccess()
    with pytest.raises((TypeError, ValueError)):
        native.VerifiedReviewedPreservationNativeSuccess(object())


@pytest.mark.parametrize("timeout", [0, -1, 61, float("nan"), True])
def test_reviewed_live_success_preserves_old_execution_bounds_before_owners(monkeypatch, timeout):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid live-success execution bound reached owners")
    monkeypatch.setattr(native, "_owners", forbidden)
    with pytest.raises(ValueError, match="finite compiler timeout"):
        native.build_verified_reviewed_norm_preservation_native_v2(None, {}, {},
            expected_preservation_sha256="1" * 64, expected_graph_sha256="2" * 64,
            expected_admission_sha256="3" * 64, toolchain=TOOLCHAIN,
            lake_executable="unopened", output_directory="unused", timeout_seconds=timeout)


@pytest.mark.parametrize("target", ["owners", "old-build", "build", "persist", "toolchain",
    "binary-recheck", "operation", "receipt-loader", "runner"])
@pytest.mark.parametrize("mutation", ["identity", "code"])
def test_reviewed_live_success_critical_callable_drift_refuses_before_build(
        reviewed_native_control_v2, monkeypatch, tmp_path, target, mutation):
    targets = {
        "owners": (native, "_owners"),
        "old-build": (native, "build_reviewed_norm_preservation_native_v2"),
        "build": (native, "_build_validated_native"),
        "persist": (native, "_persist_build"),
        "toolchain": (native, "_installed_toolchain"),
        "binary-recheck": (native, "_binary_recheck"),
        "operation": (native, "_reviewed_preservation_native_operation"),
        "receipt-loader": (native, "load_reviewed_norm_preservation_native_v2"),
        "runner": (process.BoundedToolRunner, "run"),
    }
    owner, name = targets[target]
    original = getattr(owner, name)
    def forbidden(*args, **kwargs):
        raise AssertionError("changed native callable was invoked")
    if mutation == "identity": monkeypatch.setattr(owner, name, forbidden)
    else: monkeypatch.setattr(original, "__code__", forbidden.__code__)
    output = tmp_path / ("not-created-live-" + target + "-" + mutation)
    # A distinct guard reason prevents an unrelated unopened compiler failure
    # from masquerading as successful detection of a later callable mutation.
    with pytest.raises(ValueError, match="live success callable bindings changed"):
        reviewed_live_success_build_v2(reviewed_native_control_v2, tmp_path / "unopened", output)
    assert not output.exists()


@pytest.fixture(scope="module")
def reviewed_live_success_actual_packet_v2(bound_norm_installed_lake, tmp_path_factory):
    # Exactly one new genuine build here; the second is explicit in the swap
    # test below. Reuse the original custody/environment gate unchanged.
    executable, binary_pins = bound_norm_installed_lake
    control = reviewed_native_fixture_v2()
    output = tmp_path_factory.mktemp("reviewed-live-success", numbered=False) / "original-A"
    handle = reviewed_live_success_build_v2(control, executable, output)
    packet = reviewed_live_success_packet_v2(output)
    receipt = json.loads(dict(packet)["build-receipt.json"])
    assert type(handle) is native.VerifiedReviewedPreservationNativeSuccess
    assert receipt["build_passed"] is receipt["kernel_proofs_checked"] is True
    assert receipt["binary_sha256"] == binary_pins
    return control, handle, packet, executable, binary_pins


def test_reviewed_live_success_installed_lean_joins_exact_original_packet_without_admission(
        reviewed_live_success_actual_packet_v2):
    import pickle
    import threading
    control, handle, packet, executable, binary_pins = reviewed_live_success_actual_packet_v2
    before = deepcopy((control["graph"], control["admission"]))
    result = reviewed_live_success_load_v2(control, handle, packet)
    assert result["original_success_authenticated"] is False
    assert result["live_native_success_authenticated"] is True
    assert result["native_execution_authenticated"] is True
    assert result["original_admitted_parent_custody_authenticated"] is False
    assert result["retained_receipt_sha256"] == sha(dict(packet)["build-receipt.json"])
    assert result["retained_packet_sha256"] == native.reviewed_norm_preservation_packet_sha256_v2(packet)
    assert result["current_complete_semantics_replayed"] is True
    assert result["packet_inventory"] == [
        {"path": name, "bytes": len(raw), "sha256": sha(raw)} for name, raw in packet]
    assert all(result[name] is False for name in (
        "release_ready", "Lean_admitted", "native_execution_performed", "olean_kernel_rechecked"))
    assert all(value is False for value in result["authority"].values())
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    old = native.load_reviewed_norm_preservation_native_v2(packet, control["preparation"],
        control["graph"], control["admission"], *control["args"],
        **reviewed_live_success_arguments_v2(control, packet))
    assert old["original_success_authenticated"] is old["native_execution_authenticated"] is False
    assert all(value is False for value in old["authority"].values())
    assert old["training_mask"] == old["evaluation_gold_mask"] == 0
    expected = deepcopy(result)
    result["authority"]["corpus_admission"] = True
    result["packet_inventory"].clear()
    assert reviewed_live_success_load_v2(control, handle, packet) == expected
    ordinary = json.loads(json.dumps(expected))
    with pytest.raises(ValueError): reviewed_live_success_load_v2(control, ordinary, packet)
    with pytest.raises(TypeError): pickle.dumps(handle)
    failures = []
    def foreign_reader():
        try: reviewed_live_success_load_v2(control, handle, packet)
        except BaseException as error: failures.append(error)
    worker = threading.Thread(target=foreign_reader)
    worker.start(); worker.join(timeout=5)
    assert not worker.is_alive()
    assert len(failures) == 1 and type(failures[0]) is ValueError
    assert reviewed_live_success_load_v2(control, handle, packet) == expected
    assert (control["graph"], control["admission"]) == before


def test_reviewed_live_success_installed_lean_refuses_packet_swaps_and_current_drift(
        reviewed_live_success_actual_packet_v2, tmp_path, monkeypatch):
    control, handle_a, packet_a, executable, binary_pins = reviewed_live_success_actual_packet_v2
    # A second original build over the SAME preparation isolates native-cycle
    # custody: all source/review semantics match, but the complete packet is B.
    other = reviewed_live_success_copy_control_v2(control, packet_a)
    output_b = tmp_path / "original-B"
    handle_b = reviewed_live_success_build_v2(other, executable, output_b)
    packet_b = reviewed_live_success_packet_v2(output_b)
    assert packet_b != packet_a
    assert reviewed_live_success_load_v2(other, handle_b, packet_b)["live_native_success_authenticated"] is True
    for offered_handle, offered_packet in ((handle_a, packet_b), (handle_b, packet_a)):
        # The helper deliberately rehashes the whole offered packet/receipt.
        with pytest.raises(ValueError):
            reviewed_live_success_load_v2(other, offered_handle, offered_packet)
    assert reviewed_live_success_load_v2(control, handle_a, packet_a)["live_native_success_authenticated"] is True

    alternative = reviewed_native_fixture_v2()
    declaration = alternative["case"]["declaration"]
    declaration["interpretation_id"] = "fixture:live-success-alternative-interpretation"
    for use in declaration["definition_uses"]:
        use["interpretation_id"] = declaration["interpretation_id"]
    helper = alternative["shared_helper"]
    helper.reviewed_preservation_reauthorize_fixture_v2(alternative["helper"], alternative["owner"], alternative["case"])
    different = helper.reviewed_preservation_graph_fixture_v2(alternative["helper"], alternative["owner"], alternative["case"])
    different["shared"] = alternative["shared"]; different["shared_helper"] = helper
    different["preparation"] = helper.reviewed_preservation_prepare_fixture_v2(different)
    assert reviewed_native_validate_v2(different) == different["preparation"]
    with pytest.raises(ValueError): reviewed_live_success_load_v2(different, handle_a, packet_a)

    changed = reviewed_live_success_copy_control_v2(control, packet_a)
    changed["preparation"] = replace(changed["preparation"],
        manifest_json=changed["preparation"].manifest_json + " ")
    assert changed["preparation"].to_dict() == control["preparation"].to_dict()
    with pytest.raises(ValueError): reviewed_live_success_load_v2(changed, handle_a, packet_a)

    changed = reviewed_live_success_copy_control_v2(control, packet_a)
    next(iter(changed["kwargs"]["preparation_inputs"]["source_inputs"].values()))["raw_bytes"] += b" changed literal source"
    with pytest.raises(ValueError): reviewed_live_success_load_v2(changed, handle_a, packet_a)
    changed_pins = deepcopy(binary_pins)
    changed_pins[next(iter(changed_pins))] = "0" * 64
    with pytest.raises(ValueError):
        reviewed_live_success_load_v2(control, handle_a, packet_a, expected_binary_sha256=changed_pins)

    changed = reviewed_live_success_copy_control_v2(control, packet_a)
    case = changed["case"]
    case["registry"]["keys"][0]["revoked_at_utc"] = changed["kwargs"]["at_time_utc"]
    changed["helper"].reviewed_resign_v2(case)
    changed["args"], changed["kwargs"] = changed["helper"].reviewed_assessment_arguments_v2(changed["owner"], case)
    # Registry, policy and review pins are current; the retained old admission
    # cannot conceal the now-revoked signing key.
    with pytest.raises(ValueError): reviewed_live_success_load_v2(changed, handle_a, packet_a)

    # Mutate only after the ORIGINAL retained replay has completed both its
    # current-review fences. No product callable is replaced, so a final join
    # fence must notice this actual late key revocation before returning.
    late_control = reviewed_live_success_copy_control_v2(control, packet_a)
    original_replay_code = native.load_reviewed_norm_preservation_native_v2.__code__
    previous_profile = sys.getprofile()
    revoked_after_replay = []
    def revoke_after_original_replay(frame, event, value):
        if previous_profile is not None:
            previous_profile(frame, event, value)
        if (event == "return" and frame.f_code is original_replay_code
                and type(value) is dict and not revoked_after_replay):
            revoked_after_replay.append(True)
            late_control["args"][1]["keys"][0]["revoked_at_utc"] = late_control["kwargs"]["at_time_utc"]
    try:
        sys.setprofile(revoke_after_original_replay)
        with pytest.raises(ValueError):
            reviewed_live_success_load_v2(late_control, handle_a, packet_a)
    finally:
        sys.setprofile(previous_profile)
    assert revoked_after_replay == [True]

    with monkeypatch.context() as late:
        def replaced_reader(*args, **kwargs):
            raise AssertionError("changed receipt loader was invoked")
        late.setattr(native, "load_reviewed_norm_preservation_native_v2", replaced_reader)
        with pytest.raises(ValueError, match="live success callable bindings changed"):
            reviewed_live_success_load_v2(control, handle_a, packet_a)
    assert reviewed_live_success_load_v2(control, handle_a, packet_a)["live_native_success_authenticated"] is True


@pytest.mark.parametrize("class_name", ["BoundedToolRunner", "SubprocessExecutor"])
@pytest.mark.parametrize("attribute_name", ["__getattribute__", "__getattr__"])
def test_reviewed_live_success_process_class_namespace_drift_refuses_before_build(
        reviewed_native_control_v2, monkeypatch, tmp_path, class_name, attribute_name):
    owner = getattr(process, class_name)
    method_name = "run" if class_name == "BoundedToolRunner" else "execute"
    original_method = getattr(owner, method_name)
    original_code = original_method.__code__
    def forbidden(self, name):
        raise AssertionError("changed native instance attribute lookup was invoked")
    # Adding instance lookup hooks can redirect a genuine method call while
    # leaving the class, method object and original method code unchanged.
    monkeypatch.setattr(owner, attribute_name, forbidden, raising=False)
    assert getattr(owner, method_name) is original_method
    assert original_method.__code__ is original_code
    output = tmp_path / ("not-created-live-namespace-" + class_name + "-" + attribute_name)
    with pytest.raises(ValueError, match="live success callable bindings changed"):
        reviewed_live_success_build_v2(reviewed_native_control_v2, tmp_path / "unopened", output)
    assert not output.exists()


@pytest.mark.parametrize("mutation", ["identity", "code"])
def test_reviewed_live_success_need_drift_refuses_before_original_owners(
        reviewed_native_control_v2, monkeypatch, tmp_path, mutation):
    original_need = native._need
    def untrusted_noop(*args, **kwargs):
        return None
    if mutation == "identity":
        monkeypatch.setattr(native, "_need", untrusted_noop)
    else:
        monkeypatch.setattr(original_need, "__code__", untrusted_noop.__code__)
    output = tmp_path / ("not-created-live-need-" + mutation)
    # A guard-specific refusal is essential: an unopened compiler or another
    # owner must not hide failure of the guard's own enforcement predicate.
    with pytest.raises(ValueError, match="live success callable bindings changed: independent _need"):
        reviewed_live_success_build_v2(reviewed_native_control_v2, tmp_path / "unopened", output)
    assert not output.exists()


# Explicit reviewed mixed V3 aggregate controls. The existing complete shared
# fixture owns signing/source/IR setup. Instrumented results below are authored
# boundaries, never native theorem or statutory admission evidence.
@pytest.fixture(scope="module")
def reviewed_native_seed_v3(tmp_path_factory):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_shared_lake as shared
    path = Path(__file__).with_name("test_legal_corpus_shared_lake.py")
    spec = importlib.util.spec_from_file_location("_reviewed_native_shared_fixture_v3", path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    class NativeV3FixturePaths:
        def mktemp(self, basename, *, numbered=True):
            return tmp_path_factory.mktemp("reviewed-native-v3-" + basename, numbered=numbered)
    control = helper.reviewed_preservation_control_v3.__wrapped__(NativeV3FixturePaths())
    control["shared"], control["shared_helper"] = shared, helper
    fixed = ("helper", "mixed_helper", "owner", "shared", "shared_helper", "preparation")
    environment = tuple((name, control[name]) for name in fixed)
    case = dict(control["case"])
    signers = tuple(case.pop("signers"))
    data = {name: value for name, value in control.items() if name not in fixed}
    data["case"] = case
    snapshot = reviewed_retained_freeze_fixture_data_v2({"control": data, "receipt": {}})
    return environment, snapshot, signers, (), ()


@pytest.fixture
def reviewed_native_control_v3(reviewed_native_seed_v3):
    control, _, _, _ = reviewed_retained_case_from_seed_fixture_v2(reviewed_native_seed_v3)
    return control


def reviewed_native_arguments_v3(control):
    return dict(expected_preservation_sha256=control["shared"].reviewed_preservation_corpus_sha256(control["preparation"]),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN, **control["kwargs"])


def reviewed_native_validate_v3(control, offered=None, **changes):
    return native.validate_reviewed_norm_preservation_native_v3(
        control["preparation"] if offered is None else offered, control["graph"], control["admission"],
        *control["args"], **(reviewed_native_arguments_v3(control) | changes))


def reviewed_native_build_v3(control, executable, output, **changes):
    return native.build_reviewed_norm_preservation_native_v3(control["preparation"], control["graph"],
        control["admission"], *control["args"], **(reviewed_native_arguments_v3(control) | dict(
            lake_executable=str(executable), output_directory=output, timeout_seconds=12) | changes))


def reviewed_native_reopen_v3(control, receipt, packet, **changes):
    return native.validate_reviewed_norm_preservation_native_receipt_v3(
        native.reviewed_norm_preservation_receipt_bytes_v3(receipt), control["preparation"],
        control["graph"], control["admission"], *control["args"], packet_files=packet,
        **(reviewed_native_arguments_v3(control) | dict(
            expected_receipt_sha256=sha(native.reviewed_norm_preservation_receipt_bytes_v3(receipt)),
            expected_packet_sha256=native.reviewed_norm_preservation_packet_sha256_v3(packet),
            expected_binary_sha256=receipt["binary_sha256"],
            observation_profile=native._REVIEWED_REPLAY_FICTIONAL) | changes))


def test_reviewed_native_v3_requires_explicit_domain_after_genuine_mixed_graph(
        reviewed_native_control_v3, monkeypatch):
    c = reviewed_native_control_v3
    assert c["admission"]["semantic_use_eligible"] is True
    assert c["admission"]["fixture_only"] is True
    manifest = c["preparation"].to_dict()
    assert len(c["preparation"].files) == 35 and len(manifest["expected_modules"]) == 8
    assert len(manifest["preservation_obligations"]) == 15
    monkeypatch.setattr(native, "_installed_toolchain", lambda *a, **k: pytest.fail("compiler probe during validation"))
    monkeypatch.setattr(process.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("compiler run during validation"))
    with pytest.raises(ValueError):
        native.validate_reviewed_norm_preservation_native_v2(c["preparation"], c["graph"], c["admission"],
            *c["args"], **reviewed_native_arguments_v3(c))
    assert reviewed_native_validate_v3(c) == c["preparation"]


def test_reviewed_native_v3_authored_handoff_retains_every_unit_namespace_and_capture(
        reviewed_native_control_v3, synthetic_compiler, tmp_path):
    c = reviewed_native_control_v3
    prepared = c["preparation"]
    executable, calls = synthetic_compiler(prepared, stdout=reviewed_native_stdout_v2(prepared))
    output = tmp_path / "authored-reviewed-mixed-aggregate"
    receipt = reviewed_native_build_v3(c, executable, output)
    m = prepared.to_dict()
    assert len(calls) == 1 and receipt["build_passed"] is True  # Authored boundary only.
    assert receipt["schema"] == "legal-corpus-reviewed-preservation-native-build/v3"
    assert receipt["profile"] == "replayed-reviewed-mixed-multiunit-preservation-native-build/v3"
    for key in ("units", "definition_use_record_cids", "signature_headers_by_unit", "predicate_compatibility_ledger",
                "common_module_profiles", "module_imports", "preservation_obligations", "file_sha256"):
        assert receipt[key] == m[key]
    assert "signature_header" not in receipt
    assert [x["unit_id"] for x in receipt["signature_headers_by_unit"]] == [x["unit_id"] for x in m["units"]]
    assert len({x["signature_namespace_sha256"] for x in m["units"]}) == 2
    assert receipt["conditional_theorems"] == m["preservation_obligations"]
    assert receipt["theorem_axiom_dependencies"] == {name: [] for name in m["preservation_obligations"]}
    assert len(receipt["compiled_modules"]) == 8 and len(receipt["executed_project_sha256"]) == 35
    assert all(receipt[x] is False for x in ("statutory_meaning_proved", "release_ready",
        "cross_unit_definition_application_proved", "full_formal_corpus_consistency_verified"))
    assert all(v is False for v in receipt["authority"].values())
    assert receipt["training_mask"] == receipt["evaluation_gold_mask"] == 0
    assert native.reviewed_norm_preservation_receipt_bytes_v3(receipt) == (output / "build-receipt.json").read_bytes()
    for name, text in prepared.files:
        assert (output / "project" / name).read_bytes() == (output / "executed-inputs" / name).read_bytes() == text.encode()


@pytest.mark.parametrize("pin", ["expected_preservation_sha256", "expected_graph_sha256", "expected_admission_sha256"])
def test_reviewed_native_v3_independent_commitments_precede_lazy_owners(reviewed_native_control_v3, monkeypatch, pin):
    monkeypatch.setattr(native, "_owners", lambda: pytest.fail("operation owners before independent pin refusal"))
    with pytest.raises(ValueError):
        reviewed_native_validate_v3(reviewed_native_control_v3, **{pin: "0" * 64})


@pytest.mark.parametrize("target", ["build_schema", "build_profile", "replay_schema", "replay_profile", "authority", "child_profile"])
def test_reviewed_native_v3_mutable_aliases_cannot_replace_closed_domains(reviewed_native_control_v3, monkeypatch, target):
    fields = {"build_schema": "REVIEWED_MIXED_PRESERVATION_BUILD_SCHEMA",
        "build_profile": "REVIEWED_MIXED_PRESERVATION_NATIVE_PROFILE",
        "replay_schema": "REVIEWED_MIXED_RECEIPT_REPLAY_SCHEMA", "replay_profile": "REVIEWED_MIXED_RECEIPT_REPLAY_PROFILE"}
    if target in fields:
        monkeypatch.setattr(native, fields[target], native.REVIEWED_PRESERVATION_NATIVE_PROFILE)
    elif target == "authority":
        monkeypatch.setattr(native, "AUTHORITY", dict(native.AUTHORITY, model=0))
    else:
        changed = dict(native._REVIEWED_MIXED_CHILD_DOMAINS)
        changed["authored-many-sorted-relational-deontic/v1"] = changed["authored-object-relational-deontic/v1"]
        monkeypatch.setattr(native, "_REVIEWED_MIXED_CHILD_DOMAINS", changed)
    monkeypatch.setattr(native, "_owners", lambda: pytest.fail("operation owners after closed-policy mutation"))
    with pytest.raises(ValueError):
        reviewed_native_validate_v3(reviewed_native_control_v3)


@pytest.mark.parametrize("timeout", [True, 0, -1, 61, float("nan"), float("inf")])
def test_reviewed_native_v3_original_bounds_refuse_before_operation_owners(monkeypatch, timeout):
    monkeypatch.setattr(native, "_owners", lambda: pytest.fail("operation owners before ordinary bound refusal"))
    with pytest.raises(ValueError):
        native.build_reviewed_norm_preservation_native_v3(None, {}, {}, {}, {}, {}, {},
            expected_preservation_sha256="0" * 64, expected_graph_sha256="0" * 64,
            expected_admission_sha256="0" * 64, toolchain=TOOLCHAIN, lake_executable="/unopened",
            output_directory="/uncreated", timeout_seconds=timeout)


@pytest.mark.parametrize("damage", ["unit_header", "definition_use", "predicate_role", "common_profile", "theorem", "source_file"])
def test_reviewed_native_v3_resealed_project_requires_complete_current_regeneration(
        reviewed_native_control_v3, monkeypatch, damage):
    c = reviewed_native_control_v3
    m, files = deepcopy(c["preparation"].to_dict()), dict(c["preparation"].files)
    if damage == "unit_header": m["units"][-1]["signature_header"]["signature_id"] += ":changed"
    elif damage == "definition_use": m["definition_use_record_cids"] = []
    elif damage == "predicate_role":
        ledger = next(iter(m["predicate_compatibility_ledger"].values()))
        item = next(iter(ledger["predicates"].values()))
        item["ordered_argument_roles"][0] += "_changed"
    elif damage == "common_profile": m["common_module_profiles"][0]["family"] = "forged"
    elif damage == "theorem": m["preservation_obligations"][-1] += "_forged"
    else:
        path = m["units"][-1]["instance_module"].replace(".", "/") + ".lean"
        files[path] += "\n-- changed raw source must not replace the frozen child\n"
    changed = reseal_manifest(c["preparation"], m, files)
    monkeypatch.setattr(native, "_installed_toolchain", lambda *a, **k: pytest.fail("compiler probe before full source replay"))
    with pytest.raises(ValueError):
        reviewed_native_validate_v3(c, changed,
            expected_preservation_sha256=c["shared"].reviewed_preservation_corpus_sha256(changed))


@pytest.mark.parametrize("damage", ["missing_module", "empty_module", "foreign_module", "missing_input", "changed_input"])
def test_reviewed_native_v3_requires_every_original_module_and_executed_input(
        reviewed_native_control_v3, synthetic_compiler, tmp_path, damage):
    c = reviewed_native_control_v3
    def edit(outputs, artifacts, sources):
        if damage == "missing_module": outputs.pop(artifacts[-1])
        elif damage == "empty_module": outputs[artifacts[-1]] = b""
        elif damage == "foreign_module": outputs[".lake/build/lib/lean/Foreign.olean"] = b"foreign"
        elif damage == "missing_input": outputs.pop(sources[-1])
        else: outputs[sources[-1]] += b"changed"
    executable, _ = synthetic_compiler(c["preparation"], stdout=reviewed_native_stdout_v2(c["preparation"]), output_edit=edit)
    result = reviewed_native_build_v3(c, executable, tmp_path / ("incomplete-" + damage))
    assert result["build_passed"] is False and result["proof_checked"] is False


@pytest.mark.parametrize("index", range(15))
def test_reviewed_native_v3_requires_each_exact_per_unit_axiom_report(
        reviewed_native_control_v3, synthetic_compiler, tmp_path, index):
    c = reviewed_native_control_v3
    lines = reviewed_native_stdout_v2(c["preparation"]).splitlines()
    assert len(lines) == 15
    lines.pop(index)
    executable, _ = synthetic_compiler(c["preparation"], stdout="\n".join(lines) + "\n")
    receipt = reviewed_native_build_v3(c, executable, tmp_path / ("missing-proof-" + str(index)))
    assert receipt["build_passed"] is False and receipt["axiom_observations_passed"] is False


@pytest.mark.parametrize("field", ["output_truncated", "timed_out", "cancelled", "resource_exhausted", "unavailable"])
def test_reviewed_native_v3_capture_or_resource_failure_cannot_promote_proofs(
        reviewed_native_control_v3, synthetic_compiler, tmp_path, field):
    c = reviewed_native_control_v3
    executable, _ = synthetic_compiler(c["preparation"], stdout=reviewed_native_stdout_v2(c["preparation"]),
        result_changes={field: True})
    receipt = reviewed_native_build_v3(c, executable, tmp_path / ("failed-" + field))
    assert receipt["build_passed"] is False and receipt["proof_checked"] is False


@pytest.mark.parametrize("damage", ["source_bytes", "authority_true", "authority_zero"])
def test_reviewed_native_v3_late_source_or_policy_mutation_preserves_failed_observation(
        reviewed_native_control_v3, synthetic_compiler, monkeypatch, tmp_path, damage):
    c = reviewed_native_control_v3
    def changed_after_run():
        if damage == "source_bytes":
            sources = c["kwargs"]["preparation_inputs"]["source_inputs"]
            sources[next(iter(sources))]["raw_bytes"] += b"changed"
        else:
            monkeypatch.setattr(native, "AUTHORITY", dict(native.AUTHORITY,
                model=True if damage == "authority_true" else 0))
    executable, _ = synthetic_compiler(c["preparation"], stdout=reviewed_native_stdout_v2(c["preparation"]), after=changed_after_run)
    output = tmp_path / "late-source"
    with pytest.raises(ValueError): reviewed_native_build_v3(c, executable, output)
    saved = json.loads((output / "build-receipt.json").read_bytes())
    assert saved["build_passed"] is False and saved["post_run_validation_passed"] is False
    assert all(value is False for value in saved["authority"].values())


def test_reviewed_native_v3_cleanup_refusal_preserves_same_original_owner(
        reviewed_native_control_v3, synthetic_compiler, monkeypatch, tmp_path):
    c = reviewed_native_control_v3
    executable, _ = synthetic_compiler(c["preparation"], stdout=reviewed_native_stdout_v2(c["preparation"]))
    handle = object()
    original = process.OwnedToolCleanupError(handle, "authored unresolved original ownership")
    def fail(*a, **k): raise original
    monkeypatch.setattr(process.BoundedToolRunner, "run", fail)
    output = tmp_path / "cleanup-owner"
    with pytest.raises(process.OwnedToolCleanupError) as caught:
        reviewed_native_build_v3(c, executable, output)
    assert caught.value is original and caught.value.cleanup_handle is handle
    receipt = json.loads((output / "build-receipt.json").read_bytes())
    assert receipt["profile"] == "replayed-reviewed-mixed-multiunit-preservation-native-build/v3"
    assert receipt["build_passed"] is False and receipt["cleanup_confirmed"] is False


@pytest.fixture(scope="module")
def reviewed_retained_seed_v3(reviewed_native_seed_v3, tmp_path_factory):
    control, _, _, _ = reviewed_retained_case_from_seed_fixture_v2(reviewed_native_seed_v3)
    directory = tmp_path_factory.mktemp("reviewed-mixed-retained-seed")
    with pytest.MonkeyPatch.context() as patcher:
        install = synthetic_compiler.__wrapped__(patcher, directory)
        executable, _ = install(control["preparation"], stdout=reviewed_native_stdout_v2(control["preparation"]))
        output = directory / "authored-packet"
        receipt = reviewed_native_build_v3(control, executable, output)
        packet = tuple(sorted((str(path.relative_to(output)), path.read_bytes())
            for path in output.rglob("*") if path.is_file()))
    environment, _, signers, _, _ = reviewed_native_seed_v3
    fixed = {name for name, _ in environment}
    data = {name: value for name, value in control.items() if name not in fixed}
    data["case"] = dict(data["case"])
    data["case"].pop("signers")
    snapshot = reviewed_retained_freeze_fixture_data_v2({"control": data, "receipt": receipt})
    return environment, snapshot, signers, packet, ()


@pytest.fixture
def reviewed_retained_control_v3(reviewed_retained_seed_v3):
    return reviewed_retained_case_from_seed_fixture_v2(reviewed_retained_seed_v3)


def test_reviewed_retained_v3_whole_packet_replay_keeps_zero_authority(
        reviewed_retained_control_v3, monkeypatch):
    c, receipt, packet, _ = reviewed_retained_control_v3
    monkeypatch.setattr(native, "_installed_toolchain", lambda *a, **k: pytest.fail("toolchain probe on retained replay"))
    monkeypatch.setattr(process.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("compiler on retained replay"))
    result = reviewed_native_reopen_v3(c, receipt, packet)
    assert len(packet) == 83
    assert result["retained_observations_consistent"] is result["current_complete_semantics_replayed"] is True
    assert len(result["packet_inventory"]) == len(packet) and len(result["obligations"]) == 15
    for key in ("original_success_authenticated", "native_execution_authenticated", "live_native_success_authenticated",
                "original_admitted_parent_custody_authenticated", "native_execution_performed", "olean_kernel_rechecked",
                "release_ready", "Lean_admitted"):
        assert result[key] is False
    assert all(value is False for value in result["authority"].values())
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0


def test_reviewed_retained_v3_authored_interface_cannot_be_relabelled_native(reviewed_retained_control_v3):
    c, receipt, packet, _ = reviewed_retained_control_v3
    with pytest.raises(ValueError):
        reviewed_native_reopen_v3(c, receipt, packet, observation_profile=native._REVIEWED_REPLAY_ACTUAL)
    with pytest.raises(ValueError):
        native.reviewed_norm_preservation_receipt_bytes_v2(receipt)


@pytest.mark.parametrize("damage", ["missing_module", "executed_input", "compiled_bytes", "stdout", "duplicate_path", "foreign_path"])
def test_reviewed_retained_v3_repaired_transport_cannot_replace_complete_original_packet(
        reviewed_retained_control_v3, damage):
    c, receipt, packet, _ = reviewed_retained_control_v3
    rows = list(packet)
    if damage == "missing_module": rows.pop(next(i for i, (p, _) in enumerate(rows) if p.startswith("compiled/")))
    elif damage in ("executed_input", "compiled_bytes"):
        prefix = "executed-inputs/" if damage == "executed_input" else "compiled/"
        i = next(i for i, (p, _) in enumerate(rows) if p.startswith(prefix))
        rows[i] = (rows[i][0], rows[i][1] + b"changed")
    elif damage == "stdout":
        i = next(i for i, (p, _) in enumerate(rows) if p == "stdout.txt")
        rows[i] = ("stdout.txt", rows[i][1] + b"changed")
    elif damage == "duplicate_path": rows.append(rows[0])
    else: rows.append(("foreign/raw.bin", b"unexpected complete-packet member"))
    changed = tuple(sorted(rows))
    with pytest.raises(ValueError): reviewed_native_reopen_v3(c, receipt, changed)


@pytest.mark.parametrize("damage", ["profile", "roles", "definition_use", "authority", "nonempty_axioms"])
def test_reviewed_retained_v3_resealed_receipt_cannot_replace_domain_or_subject(
        reviewed_retained_control_v3, damage):
    c, receipt, packet, _ = reviewed_retained_control_v3
    changed = deepcopy(receipt)
    if damage == "profile": changed["profile"] = native.REVIEWED_PRESERVATION_NATIVE_PROFILE
    elif damage == "roles":
        ledger = next(iter(changed["predicate_compatibility_ledger"].values()))
        next(iter(ledger["predicates"].values()))["ordered_argument_roles"][0] += "_changed"
    elif damage == "definition_use": changed["definition_use_record_cids"] = []
    elif damage == "authority": changed["authority"]["proof"] = True
    else: changed["theorem_axiom_dependencies"][changed["conditional_theorems"][-1]] = ["propext"]
    changed = contracts.seal_record({k: v for k, v in changed.items() if k not in ("record_cid", "cid_scope")})
    raw = canonical(changed)
    rows = dict(packet); rows["build-receipt.json"] = raw
    changed_packet = tuple(sorted(rows.items()))
    with pytest.raises(ValueError): reviewed_native_reopen_v3(c, changed, changed_packet)


def test_reviewed_retained_v3_current_revocation_still_blocks_reopen(reviewed_retained_control_v3):
    c, receipt, packet, _ = reviewed_retained_control_v3
    c["kwargs"]["at_time_utc"] = "2027-01-01T00:00:00Z"
    with pytest.raises(ValueError): reviewed_native_reopen_v3(c, receipt, packet)


def test_reviewed_native_v3_installed_lean_complete_mixed_aggregate_packet(
        bound_norm_installed_lake, reviewed_native_control_v3, tmp_path, monkeypatch):
    executable, binary_pins = bound_norm_installed_lake
    c = reviewed_native_control_v3
    output = tmp_path / "installed-reviewed-mixed-aggregate"
    receipt = reviewed_native_build_v3(c, executable, output, timeout_seconds=60)
    assert receipt["build_passed"] is True
    assert receipt["binary_sha256"] == binary_pins
    assert len(receipt["compiled_modules"]) == 8 and len(receipt["executed_project_sha256"]) == 35
    assert len(receipt["theorem_axiom_dependencies"]) == 15
    assert all(deps == [] for deps in receipt["theorem_axiom_dependencies"].values())
    assert all(0 < n <= 2 * 1024**2 for n in receipt["artifact_bytes"].values())
    packet = tuple(sorted((str(p.relative_to(output)), p.read_bytes()) for p in output.rglob("*") if p.is_file()))
    assert len(packet) == 83
    # The complete original packet is transported; no .olean or companion is
    # omitted merely to fit a future release artifact envelope.
    wire = preparer.encode_parent_replay_value_v1([[name, raw] for name, raw in packet],
        max_bytes=preparer.MAX_PARENT_REPLAY_BYTES)
    measurement = dict(schema="reviewed-mixed-native-complete-packet-size-observation/v1",
        complete_original_packet_retained=True, packet_files=len(packet),
        packet_logical_bytes=sum(len(raw) for _, raw in packet),
        packet_inventory_sha256=native.reviewed_norm_preservation_packet_sha256_v3(packet),
        encoded_wire_bytes=len(wire), encoded_wire_sha256=sha(wire),
        existing_release_request_bound_bytes=8 * 1024**2,
        within_existing_release_request_bound=len(wire) <= 8 * 1024**2,
        release_ready=False, original_admitted_parent_custody_authenticated=False,
        statutory_or_model_authority=False)
    (tmp_path / "complete-mixed-native-packet.wire").write_bytes(wire)
    (tmp_path / "complete-mixed-native-packet-size-observation.json").write_bytes(canonical(measurement))
    # Measure and retain the whole original packet before testing release
    # eligibility. A larger genuine result is a retained refusal, never clipped
    # output or a reason to select fewer source units/modules.
    assert len(wire) > 1_000_000
    assert measurement["within_existing_release_request_bound"], "whole actual packet exceeds existing release bound; complete bytes and size refusal retained"
    decoded = preparer.decode_parent_replay_value_v1(wire, expected_payload_sha256=sha(wire), max_bytes=8 * 1024**2)
    assert tuple(tuple(row) for row in decoded) == packet
    monkeypatch.setattr(native, "_installed_toolchain", lambda *a, **k: pytest.fail("probe during original retained reopen"))
    monkeypatch.setattr(process.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("compiler during original retained reopen"))
    replay = reviewed_native_reopen_v3(c, receipt, packet,
        observation_profile=native._REVIEWED_REPLAY_ACTUAL, expected_binary_sha256=binary_pins)
    assert replay["retained_observations_consistent"] is True and replay["release_ready"] is False
    assert replay["original_admitted_parent_custody_authenticated"] is False


def test_reviewed_live_direct_guard_replacement_refuses_before_original_toolchain(
        reviewed_native_control_v2, monkeypatch, tmp_path):
    """A source-valid V2 project must not pass a replaced live integrity gate.

    The toolchain callback below is an explicit forbidden boundary, not a
    compiler, runner result or proof. Reaching it reproduces guard bypass.
    """
    control = reviewed_native_control_v2
    assert reviewed_native_validate_v2(control) == control["preparation"]
    boundary_calls = []

    def replaced_guard(*args, **kwargs):
        return None

    def forbidden_original_toolchain(*args, **kwargs):
        boundary_calls.append("installed_toolchain")
        pytest.fail("DIRECT_LIVE_GUARD_BYPASSED: the forbidden original toolchain boundary was reached")

    monkeypatch.setattr(native, "_live_success_guard", replaced_guard)
    monkeypatch.setattr(native, "_installed_toolchain", forbidden_original_toolchain)
    output = tmp_path / "not-created-direct-live-guard"
    with pytest.raises(ValueError, match="live success callable bindings changed"):
        reviewed_live_success_build_v2(control, tmp_path / "unopened", output)
    assert boundary_calls == []
    assert not output.exists()


# Explicit live V3 controls extend the same owning file. Ordinary refusals
# never issue a capability; genuine positives use the original installed gate.
def reviewed_live_build_v3_fixture(control, executable, output, **changes):
    return native.build_verified_reviewed_norm_preservation_native_v3(
        control["preparation"], control["graph"], control["admission"], *control["args"],
        **(reviewed_native_arguments_v3(control) | dict(lake_executable=str(executable),
            output_directory=output, timeout_seconds=60) | changes))


def reviewed_live_load_v3_fixture(control, handle, packet, **changes):
    receipt = json.loads(dict(packet)["build-receipt.json"])
    return native.load_verified_reviewed_norm_preservation_native_v3(
        handle, packet, control["preparation"], control["graph"], control["admission"],
        *control["args"], **(reviewed_native_arguments_v3(control) | dict(
            expected_receipt_sha256=sha(dict(packet)["build-receipt.json"]),
            expected_packet_sha256=native.reviewed_norm_preservation_packet_sha256_v3(packet),
            expected_binary_sha256=receipt["binary_sha256"]) | changes))


def reviewed_live_mutate_callable_fixture(monkeypatch, name, mutation):
    original = getattr(native, name)

    def forbidden_callback(*args, **kwargs):
        raise AssertionError("MUTATED_LIVE_CALLBACK_WAS_INVOKED: " + name)

    def inert_code(*args, **kwargs):
        return None

    if mutation == "identity":
        monkeypatch.setattr(native, name, forbidden_callback)
    elif mutation == "code":
        # Extra unused free-variable metadata preserves the original function's
        # closure shape; the inert code must never be invoked by a valid guard.
        monkeypatch.setattr(original, "__code__", inert_code.__code__.replace(
            co_freevars=original.__code__.co_freevars))
    elif mutation == "defaults":
        monkeypatch.setattr(original, "__defaults__", ("changed-live-default",))
    else:
        assert mutation == "kwdefaults"
        monkeypatch.setattr(original, "__kwdefaults__", {"changed_live_keyword": "changed"})


def test_reviewed_live_v3_public_signatures_and_canonical_lexical_origins():
    import inspect

    for stem in ("build_verified_reviewed_norm_preservation_native_",
                 "load_verified_reviewed_norm_preservation_native_"):
        old, mixed = getattr(native, stem + "v2"), getattr(native, stem + "v3")
        assert inspect.signature(old) == inspect.signature(mixed)
        for function in (old, mixed):
            assert function.__globals__ is vars(native)
            assert function.__module__ == native.__name__
            assert function.__code__.co_filename == native.__file__
            assert function.__closure__
    states = dict(native._LIVE_NATIVE_FUNCTIONS)
    for name in ("_build_verified_reviewed_norm_preservation_native",
                 "_load_verified_reviewed_norm_preservation_native", "_live_success_domain",
                 "_live_review_components", "_live_success_guard", "_live_entry_guard",
                 "build_verified_reviewed_norm_preservation_native_v2",
                 "load_verified_reviewed_norm_preservation_native_v2",
                 "build_verified_reviewed_norm_preservation_native_v3",
                 "load_verified_reviewed_norm_preservation_native_v3"):
        current = getattr(native, name)
        assert states[name][0] is current and states[name][1] is current.__code__


@pytest.mark.parametrize("timeout", [0, -1, 61, float("nan"), True])
def test_reviewed_live_v3_invalid_timeout_precedes_original_owners(monkeypatch, timeout):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid live V3 timeout reached an owner")

    monkeypatch.setattr(native, "_owners", forbidden)
    with pytest.raises(ValueError, match="finite compiler timeout"):
        native.build_verified_reviewed_norm_preservation_native_v3(None, {}, {},
            expected_preservation_sha256="1" * 64, expected_graph_sha256="2" * 64,
            expected_admission_sha256="3" * 64, toolchain=TOOLCHAIN,
            lake_executable="unopened", output_directory="unused", timeout_seconds=timeout)


@pytest.mark.parametrize("reviewed_version", [2, 3])
@pytest.mark.parametrize("offered", ["none", "object", "dict", "json", "unissued", "boolean"])
def test_reviewed_live_domains_reject_unissued_before_original_owners(monkeypatch, reviewed_version, offered):
    values = {"none": None, "object": object(), "dict": {},
        "json": {"live_native_success_authenticated": True, "reviewed_version": reviewed_version},
        "unissued": object.__new__(native.VerifiedReviewedPreservationNativeSuccess), "boolean": True}

    def forbidden(*args, **kwargs):
        pytest.fail("unissued live handle reached an owner")

    monkeypatch.setattr(native, "_owners", forbidden)
    reader = getattr(native, "load_verified_reviewed_norm_preservation_native_v" + str(reviewed_version))
    with pytest.raises(ValueError, match="not issued by this process and native thread"):
        reader(values[offered], (), None, {}, {}, expected_receipt_sha256="1" * 64,
            expected_packet_sha256="2" * 64, expected_binary_sha256={},
            expected_preservation_sha256="3" * 64, expected_graph_sha256="4" * 64,
            expected_admission_sha256="5" * 64, toolchain=TOOLCHAIN)


@pytest.mark.parametrize("reviewed_version", [2, 3])
@pytest.mark.parametrize("target", ["guard", "entry", "both"])
@pytest.mark.parametrize("mutation", ["identity", "code", "defaults", "kwdefaults"])
def test_reviewed_live_public_builds_reach_lexical_guard_after_global_alias_mutation(
        monkeypatch, tmp_path, reviewed_version, target, mutation):
    names = {"guard": ("_live_success_guard",), "entry": ("_live_entry_guard",),
             "both": ("_live_success_guard", "_live_entry_guard")}[target]
    for name in names:
        reviewed_live_mutate_callable_fixture(monkeypatch, name, mutation)
    builder = getattr(native, "build_verified_reviewed_norm_preservation_native_v" + str(reviewed_version))
    output = tmp_path / "not-created-live-lexical-guard"
    with pytest.raises(ValueError, match="live success callable bindings changed"):
        builder(None, {}, {}, expected_preservation_sha256="1" * 64,
            expected_graph_sha256="2" * 64, expected_admission_sha256="3" * 64,
            toolchain=TOOLCHAIN, lake_executable="unopened", output_directory=output)
    assert not output.exists()


@pytest.mark.parametrize("reviewed_version", [2, 3])
@pytest.mark.parametrize("mutation", ["identity", "code", "defaults", "kwdefaults"])
def test_reviewed_live_load_checks_captured_handle_callback_before_invoking_it(
        monkeypatch, reviewed_version, mutation):
    original = native._live_handle_entry

    def forbidden_handle_callback(*args, **kwargs):
        raise AssertionError("MUTATED_HANDLE_ENTRY_WAS_INVOKED")

    if mutation == "identity":
        monkeypatch.setattr(native, "_live_handle_entry", forbidden_handle_callback)
    elif mutation == "code":
        monkeypatch.setattr(original, "__code__", forbidden_handle_callback.__code__.replace(
            co_freevars=original.__code__.co_freevars))
    else:
        reviewed_live_mutate_callable_fixture(monkeypatch, "_live_handle_entry", mutation)
    reader = getattr(native, "load_verified_reviewed_norm_preservation_native_v" + str(reviewed_version))
    with pytest.raises(ValueError, match="independent _live_handle_entry"):
        reader(None, (), None, {}, {}, expected_receipt_sha256="1" * 64,
            expected_packet_sha256="2" * 64, expected_binary_sha256={},
            expected_preservation_sha256="3" * 64, expected_graph_sha256="4" * 64,
            expected_admission_sha256="5" * 64, toolchain=TOOLCHAIN)


@pytest.mark.parametrize("name", ["_build_verified_reviewed_norm_preservation_native",
    "_load_verified_reviewed_norm_preservation_native", "_live_success_domain", "_live_review_components",
    "load_reviewed_norm_preservation_native_v3", "validate_reviewed_norm_preservation_native_v3",
    "reviewed_norm_preservation_receipt_bytes_v3", "_reviewed_mixed_preservation_receipt_binding"])
@pytest.mark.parametrize("mutation", ["identity", "code"])
def test_reviewed_live_v3_captured_set_refuses_new_core_and_retained_callback_drift(
        monkeypatch, tmp_path, name, mutation):
    reviewed_live_mutate_callable_fixture(monkeypatch, name, mutation)
    output = tmp_path / "not-created-live-v3-callback"
    with pytest.raises(ValueError, match="live success callable bindings changed"):
        native.build_verified_reviewed_norm_preservation_native_v3(None, {}, {},
            expected_preservation_sha256="1" * 64, expected_graph_sha256="2" * 64,
            expected_admission_sha256="3" * 64, toolchain=TOOLCHAIN,
            lake_executable="unopened", output_directory=output)
    assert not output.exists()


@pytest.mark.parametrize("name", ["REVIEWED_MIXED_LIVE_SUCCESS_SCHEMA", "REVIEWED_MIXED_LIVE_SUCCESS_PROFILE",
    "REVIEWED_MIXED_PRESERVATION_BUILD_SCHEMA", "REVIEWED_MIXED_PRESERVATION_NATIVE_PROFILE"])
def test_reviewed_live_v3_profile_aliases_cannot_select_the_old_domain(monkeypatch, tmp_path, name):
    old = ("legal-reviewed-native-live-success/v1" if name.endswith("SCHEMA")
           else "current-reviewed-live-native-owner-success/v1")
    monkeypatch.setattr(native, name, old)
    output = tmp_path / "not-created-live-v3-profile"
    with pytest.raises(ValueError, match="closed mixed"):
        native.build_verified_reviewed_norm_preservation_native_v3(None, {}, {},
            expected_preservation_sha256="1" * 64, expected_graph_sha256="2" * 64,
            expected_admission_sha256="3" * 64, toolchain=TOOLCHAIN,
            lake_executable="unopened", output_directory=output)
    assert not output.exists()


@pytest.mark.parametrize("policy", ["AUTHORITY", "PARENT_FALSE_FLAGS"])
@pytest.mark.parametrize("value", [True, 0])
def test_reviewed_live_v3_false_authority_policy_does_not_accept_zero_or_true(
        monkeypatch, tmp_path, policy, value):
    mapping = getattr(native, policy)
    monkeypatch.setitem(mapping, next(iter(mapping)), value)
    with pytest.raises(ValueError, match="closed false-authority policy"):
        native.build_verified_reviewed_norm_preservation_native_v3(None, {}, {},
            expected_preservation_sha256="1" * 64, expected_graph_sha256="2" * 64,
            expected_admission_sha256="3" * 64, toolchain=TOOLCHAIN,
            lake_executable="unopened", output_directory=tmp_path / "not-created-authority")


def test_reviewed_live_v3_genuine_project_cannot_issue_from_an_authored_runner(
        reviewed_native_control_v3, synthetic_compiler, tmp_path):
    control = reviewed_native_control_v3
    assert reviewed_native_validate_v3(control) == control["preparation"]
    executable, calls = synthetic_compiler(control["preparation"],
        stdout=reviewed_native_stdout_v2(control["preparation"]))
    output = tmp_path / "not-created-authored-live-v3"
    with pytest.raises(ValueError, match="live success callable bindings changed"):
        reviewed_live_build_v3_fixture(control, executable, output)
    assert calls == [] and not output.exists()


@pytest.fixture(scope="module")
def reviewed_live_actual_packet_v3(bound_norm_installed_lake, reviewed_native_seed_v3, tmp_path_factory):
    executable, binary_pins = bound_norm_installed_lake
    control, _, _, _ = reviewed_retained_case_from_seed_fixture_v2(reviewed_native_seed_v3)
    output = tmp_path_factory.mktemp("reviewed-live-v3-original", numbered=False) / "packet"
    handle = reviewed_live_build_v3_fixture(control, executable, output)
    packet = reviewed_live_success_packet_v2(output)
    receipt = json.loads(dict(packet)["build-receipt.json"])
    assert type(handle) is native.VerifiedReviewedPreservationNativeSuccess
    assert receipt["build_passed"] is receipt["kernel_proofs_checked"] is True
    assert receipt["binary_sha256"] == binary_pins
    assert len(packet) == 83 and len(receipt["compiled_modules"]) == 8
    assert len(receipt["executed_project_sha256"]) == 35
    assert len(receipt["theorem_axiom_dependencies"]) == 15
    assert all(dependencies == [] for dependencies in receipt["theorem_axiom_dependencies"].values())
    return control, handle, packet, executable, binary_pins


def test_reviewed_live_v3_installed_lean_joins_all_units_and_keeps_parent_authority_false(
        reviewed_live_actual_packet_v3):
    import pickle
    import threading

    control, handle, packet, _, _ = reviewed_live_actual_packet_v3
    result = reviewed_live_load_v3_fixture(control, handle, packet)
    manifest = control["preparation"].to_dict()
    assert result["schema"] == "legal-reviewed-native-live-success/v3"
    assert result["profile"] == "current-reviewed-mixed-live-native-owner-success/v3"
    assert result["live_native_success_authenticated"] is result["native_execution_authenticated"] is True
    assert result["retained_observations_consistent"] is result["current_complete_semantics_replayed"] is True
    for key in ("units", "definition_use_record_cids", "signature_headers_by_unit",
                "predicate_compatibility_ledger", "common_module_profiles", "module_imports",
                "preservation_obligations", "file_sha256"):
        assert result[key] == manifest[key]
    for key in ("original_success_authenticated", "original_admitted_parent_custody_authenticated",
                "native_execution_performed", "olean_kernel_rechecked", "release_ready", "Lean_admitted",
                "cross_unit_definition_application_proved", "statutory_meaning_proved"):
        assert result[key] is False
    assert all(value is False for value in result["authority"].values())
    assert type(result["training_mask"]) is type(result["evaluation_gold_mask"]) is int
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    with pytest.raises(TypeError):
        pickle.dumps(handle)
    errors = []

    def wrong_thread():
        try:
            reviewed_live_load_v3_fixture(control, handle, packet)
        except ValueError as error:
            errors.append(str(error))

    thread = threading.Thread(target=wrong_thread)
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive() and len(errors) == 1 and "not issued" in errors[0]
    assert reviewed_live_load_v3_fixture(control, handle, packet)["live_native_success_authenticated"] is True


@pytest.mark.parametrize("reviewed_version", [2, 3])
@pytest.mark.parametrize("target", ["guard", "entry", "both"])
@pytest.mark.parametrize("mutation", ["identity", "code", "defaults", "kwdefaults"])
def test_reviewed_live_installed_lean_load_uses_lexical_guards_after_both_global_aliases_change(
        request, monkeypatch, reviewed_version, target, mutation):
    fixture = ("reviewed_live_success_actual_packet_v2" if reviewed_version == 2
               else "reviewed_live_actual_packet_v3")
    control, handle, packet, _, _ = request.getfixturevalue(fixture)
    names = {"guard": ("_live_success_guard",), "entry": ("_live_entry_guard",),
             "both": ("_live_success_guard", "_live_entry_guard")}[target]
    for name in names:
        reviewed_live_mutate_callable_fixture(monkeypatch, name, mutation)
    reader = reviewed_live_success_load_v2 if reviewed_version == 2 else reviewed_live_load_v3_fixture
    with pytest.raises(ValueError, match="live success callable bindings changed"):
        reader(control, handle, packet)


@pytest.mark.parametrize("reviewed_version", [2, 3])
def test_reviewed_live_installed_lean_handles_cannot_cross_the_other_domain_before_owners(
        reviewed_live_success_actual_packet_v2, reviewed_live_actual_packet_v3,
        monkeypatch, reviewed_version):
    current = (reviewed_live_success_actual_packet_v2 if reviewed_version == 2
               else reviewed_live_actual_packet_v3)
    control, handle, packet, _, _ = current

    def forbidden(*args, **kwargs):
        pytest.fail("cross-domain handle reached an owner")

    monkeypatch.setattr(native, "_owners", forbidden)
    other = (native.load_verified_reviewed_norm_preservation_native_v3 if reviewed_version == 2
             else native.load_verified_reviewed_norm_preservation_native_v2)
    with pytest.raises(ValueError, match="not issued by this process and native thread"):
        other(handle, packet, control["preparation"], control["graph"], control["admission"],
            *control["args"], expected_receipt_sha256="1" * 64, expected_packet_sha256="2" * 64,
            expected_binary_sha256={}, expected_preservation_sha256="3" * 64,
            expected_graph_sha256="4" * 64, expected_admission_sha256="5" * 64, toolchain=TOOLCHAIN,
            **control["kwargs"])


@pytest.mark.parametrize("damage", ["packet", "graph", "current_observation"])
def test_reviewed_live_v3_installed_lean_capability_rejects_other_packet_or_current_inputs(
        reviewed_live_actual_packet_v3, reviewed_live_success_actual_packet_v2, damage):
    control, handle, packet, _, _ = reviewed_live_actual_packet_v3
    if damage == "packet":
        other_packet = reviewed_live_success_actual_packet_v2[2]
        with pytest.raises(ValueError, match="exact issued live success packet"):
            reviewed_live_load_v3_fixture(control, handle, other_packet)
    elif damage == "graph":
        changed = dict(control, graph=dict(control["graph"], record_cid="changed-live-graph"))
        with pytest.raises(ValueError, match="exact issued live success original inputs"):
            reviewed_live_load_v3_fixture(changed, handle, packet)
    else:
        changed_kwargs = dict(control["kwargs"])
        observations = dict(changed_kwargs["observed_artifact_sha256s"])
        observations[next(iter(observations))] = "0" * 64
        changed_kwargs["observed_artifact_sha256s"] = observations
        with pytest.raises(ValueError, match="exact issued live success original inputs"):
            reviewed_live_load_v3_fixture(dict(control, kwargs=changed_kwargs), handle, packet)


def test_reviewed_live_late_guard_alias_replacement_refuses_before_original_toolchain(
        reviewed_native_control_v2, monkeypatch, tmp_path):
    """Mutate after the original guard's callable loop, retaining real bytes.

    Path.read_bytes is controlled instrumentation only. No compiler, runner,
    fake ToolRunResult, source-file mutation or capability is supplied.
    """
    control = reviewed_native_control_v2
    assert reviewed_native_validate_v2(control) == control["preparation"]
    original_read_bytes = Path.read_bytes
    guard_boundary = []
    toolchain_boundary = []

    def replaced_guard(*args, **kwargs):
        return None

    def forbidden_original_toolchain(*args, **kwargs):
        toolchain_boundary.append("installed_toolchain")
        pytest.fail("LATE_LIVE_GUARD_BYPASSED: forbidden original toolchain reached after both aliases changed")

    def genuine_source_read_then_mutate(path):
        raw = original_read_bytes(path)
        caller = sys._getframe(1)
        if (not guard_boundary and path == Path(native.__file__)
                and caller.f_globals is vars(native)
                and caller.f_code.co_filename == native.__file__
                and caller.f_code.co_name == "_live_success_guard"):
            guard_boundary.append("original_guard_self_source_read_after_callable_loop")
            monkeypatch.setattr(native, "_live_success_guard", replaced_guard)
            monkeypatch.setattr(native, "_live_entry_guard", replaced_guard)
            monkeypatch.setattr(native, "_installed_toolchain", forbidden_original_toolchain)
        return raw

    monkeypatch.setattr(Path, "read_bytes", genuine_source_read_then_mutate)
    output = tmp_path / "not-created-late-live-alias"
    with pytest.raises(ValueError, match="live success callable bindings changed"):
        reviewed_live_success_build_v2(control, tmp_path / "unopened", output)
    assert guard_boundary == ["original_guard_self_source_read_after_callable_loop"]
    assert toolchain_boundary == []
    assert not output.exists()


def test_reviewed_live_captured_integrity_is_private_and_in_the_complete_callback_set():
    import inspect

    checker = native._live_integrity_checker
    state = dict(native._LIVE_NATIVE_FUNCTIONS)["_live_integrity_checker"]
    assert state[0] is checker and state[1] is checker.__code__
    assert checker.__globals__ is vars(native) and checker.__code__.co_filename == native.__file__
    for stem in ("build_verified_reviewed_norm_preservation_native_",
                 "load_verified_reviewed_norm_preservation_native_"):
        for version in (2, 3):
            public = getattr(native, stem + "v" + str(version))
            assert "_live_integrity_state" not in inspect.signature(public).parameters
    for name in ("_build_verified_reviewed_norm_preservation_native",
                 "_load_verified_reviewed_norm_preservation_native"):
        parameter = inspect.signature(getattr(native, name)).parameters["_live_integrity_state"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty


@pytest.mark.parametrize("reviewed_version", [2, 3])
def test_reviewed_live_public_build_cannot_inject_the_private_integrity_bundle(monkeypatch, tmp_path, reviewed_version):
    calls = []

    def forbidden_integrity(*args, **kwargs):
        calls.append("forged-integrity")
        raise AssertionError("public integrity callback was invoked")

    builder = getattr(native, "build_verified_reviewed_norm_preservation_native_v" + str(reviewed_version))
    with pytest.raises(ValueError, match="private live integrity hook cannot be supplied"):
        builder(None, {}, {}, expected_preservation_sha256="1" * 64,
            expected_graph_sha256="2" * 64, expected_admission_sha256="3" * 64,
            toolchain=TOOLCHAIN, lake_executable="unopened", output_directory=tmp_path / "unused",
            _live_integrity_state=(forbidden_integrity, None, None, (), ()))
    assert calls == []


@pytest.mark.parametrize("reviewed_version", [2, 3])
@pytest.mark.parametrize("mutation", ["identity", "code", "defaults", "kwdefaults"])
def test_reviewed_live_core_checks_captured_integrity_after_late_alias_mutation(
        request, monkeypatch, tmp_path, reviewed_version, mutation):
    fixture = "reviewed_native_control_v2" if reviewed_version == 2 else "reviewed_native_control_v3"
    control = request.getfixturevalue(fixture)
    validator = reviewed_native_validate_v2 if reviewed_version == 2 else reviewed_native_validate_v3
    assert validator(control) == control["preparation"]
    original_read = Path.read_bytes
    reached, tools = [], []

    def no_guard(*args, **kwargs):
        return None

    def forbidden_toolchain(*args, **kwargs):
        tools.append("installed-toolchain")
        pytest.fail("LATE_CORE_GUARD_BYPASSED: original toolchain reached after core guard mutation")

    def original_guard_read_inside_core(path):
        raw = original_read(path)
        caller = sys._getframe(1)
        frame = caller
        inside_core = False
        for _ in range(64):
            if frame is None:
                break
            if (frame.f_globals is vars(native)
                    and frame.f_code.co_name == "_build_verified_reviewed_norm_preservation_native"):
                inside_core = True
                break
            frame = frame.f_back
        if (not reached and inside_core and path == Path(native.__file__)
                and caller.f_globals is vars(native) and caller.f_code.co_name == "_live_success_guard"):
            reached.append("core-original-guard-self-read")
            for name in ("_live_success_guard", "_live_entry_guard"):
                if mutation == "identity":
                    monkeypatch.setattr(native, name, no_guard)
                else:
                    reviewed_live_mutate_callable_fixture(monkeypatch, name, mutation)
            monkeypatch.setattr(native, "_installed_toolchain", forbidden_toolchain)
        return raw

    monkeypatch.setattr(Path, "read_bytes", original_guard_read_inside_core)
    build = reviewed_live_success_build_v2 if reviewed_version == 2 else reviewed_live_build_v3_fixture
    output = tmp_path / "not-created-late-core-guard"
    with pytest.raises(ValueError, match="live success callable bindings changed"):
        build(control, tmp_path / "unopened", output)
    assert reached == ["core-original-guard-self-read"]
    assert tools == [] and not output.exists()


@pytest.mark.parametrize("reviewed_version", [2, 3])
@pytest.mark.parametrize("mutation", ["identity", "code", "defaults", "kwdefaults"])
def test_reviewed_live_installed_lean_load_checks_captured_integrity_during_replay(
        request, monkeypatch, reviewed_version, mutation):
    fixture = ("reviewed_live_success_actual_packet_v2" if reviewed_version == 2
               else "reviewed_live_actual_packet_v3")
    control, handle, packet, _, _ = request.getfixturevalue(fixture)
    original_read = Path.read_bytes
    reached = []

    def no_guard(*args, **kwargs):
        return None

    def genuine_read_then_change_replay_aliases(path):
        raw = original_read(path)
        caller = sys._getframe(1)
        frame = caller
        inside_core = False
        for _ in range(64):
            if frame is None:
                break
            if (frame.f_globals is vars(native)
                    and frame.f_code.co_name == "_load_verified_reviewed_norm_preservation_native"):
                inside_core = True
                break
            frame = frame.f_back
        if (not reached and inside_core and path == Path(native.__file__)
                and caller.f_globals is vars(native) and caller.f_code.co_name == "_live_success_guard"):
            reached.append("load-core-original-guard-self-read")
            for name in ("_live_success_guard", "_live_entry_guard"):
                if mutation == "identity":
                    monkeypatch.setattr(native, name, no_guard)
                else:
                    reviewed_live_mutate_callable_fixture(monkeypatch, name, mutation)
        return raw

    monkeypatch.setattr(Path, "read_bytes", genuine_read_then_change_replay_aliases)
    load = reviewed_live_success_load_v2 if reviewed_version == 2 else reviewed_live_load_v3_fixture
    with pytest.raises(ValueError, match="live success callable bindings changed"):
        load(control, handle, packet)
    assert reached == ["load-core-original-guard-self-read"]


@pytest.mark.parametrize("reviewed_version", [2, 3])
def test_reviewed_live_installed_lean_load_cannot_inject_private_integrity(
        request, reviewed_version):
    fixture = ("reviewed_live_success_actual_packet_v2" if reviewed_version == 2
               else "reviewed_live_actual_packet_v3")
    control, handle, packet, _, _ = request.getfixturevalue(fixture)

    def forbidden_integrity(*args, **kwargs):
        pytest.fail("forged private live-read integrity was invoked")

    load = reviewed_live_success_load_v2 if reviewed_version == 2 else reviewed_live_load_v3_fixture
    with pytest.raises(ValueError, match="private live integrity hook cannot be supplied"):
        load(control, handle, packet, _live_integrity_state=(forbidden_integrity, None, None, (), ()))


def test_reviewed_live_v3_installed_lean_late_execution_alias_drift_cannot_issue(
        bound_norm_installed_lake, reviewed_native_seed_v3, tmp_path, monkeypatch):
    executable, _ = bound_norm_installed_lake
    control, _, _, _ = reviewed_retained_case_from_seed_fixture_v2(reviewed_native_seed_v3)
    original_read = Path.read_bytes
    reached = []
    old_handles = tuple(native._LIVE_SUCCESS_HANDLES)

    def no_guard(*args, **kwargs):
        return None

    def unchanged_binary_read_then_mutate(path):
        raw = original_read(path)
        caller = sys._getframe(1)
        frame = caller
        completed_run = False
        for _ in range(64):
            if frame is None:
                break
            if frame.f_globals is vars(native) and frame.f_code.co_name == "_build_validated_native":
                run = frame.f_locals.get("run")
                completed_run = type(run) is process.ToolRunResult and run.ok is True
                break
            frame = frame.f_back
        if (not reached and completed_run and caller.f_globals is vars(native)
                and caller.f_code.co_name == "_binary_recheck"):
            reached.append("real-run-complete-binary-read")
            monkeypatch.setattr(native, "_live_success_guard", no_guard)
            monkeypatch.setattr(native, "_live_entry_guard", no_guard)
        return raw

    monkeypatch.setattr(Path, "read_bytes", unchanged_binary_read_then_mutate)
    output = tmp_path / "late-real-live-alias-refusal"
    with pytest.raises(ValueError, match="live success callable bindings changed"):
        reviewed_live_build_v3_fixture(control, executable, output)
    assert reached == ["real-run-complete-binary-read"]
    assert tuple(native._LIVE_SUCCESS_HANDLES) == old_handles


# Explicit source-use identity controls use the existing complete fictional
# admission fixtures and authored compiler interface. Authored olean bytes are
# diagnostic software evidence, never actual kernel/native proof observations.
def reviewed_source_use_native_control_data(version):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_shared_lake as shared
    if version == 2:
        c = reviewed_native_fixture_v2()
        helper, admission_owner, case = c["helper"], c["owner"], c["case"]
        helper.reviewed_repeated_permission_source_v2(case, "nonoverlapping_paragraphs")
        c["shared_helper"].reviewed_preservation_reauthorize_fixture_v2(helper, admission_owner, case)
        current = c["shared_helper"].reviewed_preservation_graph_fixture_v2(helper, admission_owner, case)
        current.update(shared=shared, shared_helper=c["shared_helper"])
    else:
        from tests.unit.logic.autoformal import test_legal_reviewed_norm_admission_v3 as fixture
        from ipfs_datasets_py.logic.autoformal import legal_reviewed_norm_admission_v3 as admission_owner
        from ipfs_datasets_py.logic.autoformal import corpus_norm_definition_adapter as graph_owner
        # The existing wrapped fixture does not use its v2_saved parameter.
        # No saved-V2 transport or filesystem-fixture qualification is claimed.
        case = fixture.mixed_base.__wrapped__(admission_owner, None)
        fixture.fixture.reviewed_repeated_permission_source_v2(case, "nonoverlapping_paragraphs")
        case["preparation"] = fixture.prepare(admission_owner, case)
        fixture.refresh_signed_reviews(case, admission_owner)
        fixture.assert_signatures_valid(case)
        args, kwargs = fixture.fixture.reviewed_assessment_arguments_v2(admission_owner, case)
        admission = admission_owner.assess_reviewed_norm_admission_v3(*args, **kwargs)
        admission_sha = admission_owner.norm_content_adjudication_sha256(admission)
        graph = graph_owner.build_reviewed_norm_graph_v3(admission, *args,
            expected_admission_sha256=admission_sha, **kwargs)
        graph_sha = graph_owner.norm_definition_graph_sha256(graph)
        assert graph_owner.validate_reviewed_norm_graph_v3(graph, admission, *args,
            expected_graph_sha256=graph_sha, expected_admission_sha256=admission_sha, **kwargs) == graph
        current = dict(helper=fixture.fixture, mixed_helper=fixture, owner=admission_owner,
            shared=shared, case=case, args=args, kwargs=kwargs, admission=admission, graph=graph,
            admission_sha=admission_sha, graph_sha=graph_sha)
    current["version"] = version
    current["preparation"] = getattr(shared, "prepare_reviewed_norm_preservation_corpus_v" + str(version))(
        current["graph"], current["admission"], *current["args"],
        expected_graph_sha256=current["graph_sha"], expected_admission_sha256=current["admission_sha"],
        toolchain=TOOLCHAIN, instance_identity_profile="reviewed-source-use/v1", **current["kwargs"])
    assert current["admission"]["fixture_only"] is True
    assert len(current["preparation"].to_dict()["units"]) == 3
    return current


def reviewed_source_use_native_arguments(c):
    return reviewed_native_arguments_v2(c) | {"instance_identity_profile": "reviewed-source-use/v1"}


def reviewed_source_use_native_api(c, stem):
    return getattr(native, stem + "_v" + str(c["version"]))


@pytest.fixture(scope="module")
def reviewed_source_use_native_seeds(tmp_path_factory):
    # Both parameter populations share one module fixture; selector ordering
    # cannot recreate an unnumbered directory. Exactly one authored packet per
    # version is retained and copied for independent current replays.
    seeds = {}
    for version in (2, 3):
        c = reviewed_source_use_native_control_data(version)
        directory = tmp_path_factory.mktemp("reviewed-source-use-native-v" + str(version), numbered=False)
        with pytest.MonkeyPatch.context() as patcher:
            install = synthetic_compiler.__wrapped__(patcher, directory)
            executable, calls = install(c["preparation"], stdout=reviewed_native_stdout_v2(c["preparation"]))
            output = directory / "authored-packet"
            receipt = reviewed_source_use_native_api(c, "build_reviewed_norm_preservation_native")(
                c["preparation"], c["graph"], c["admission"], *c["args"],
                lake_executable=str(executable), output_directory=output, timeout_seconds=12,
                **reviewed_source_use_native_arguments(c))
            packet = tuple(sorted((str(p.relative_to(output)), p.read_bytes())
                for p in output.rglob("*") if p.is_file()))
            assert len(calls) == 1
        fixed = tuple(key for key in ("helper", "mixed_helper", "owner", "shared", "shared_helper", "preparation") if key in c)
        environment = tuple((key, c[key]) for key in fixed)
        data = {key: value for key, value in c.items() if key not in fixed}
        data["case"] = dict(data["case"])
        signers = tuple(data["case"].pop("signers"))
        frozen = reviewed_retained_freeze_fixture_data_v2({"control": data, "receipt": receipt})
        seeds[version] = environment, frozen, signers, packet, tuple(calls)
    return seeds


@pytest.fixture
def reviewed_source_use_native_case(version, reviewed_source_use_native_seeds):
    return reviewed_retained_case_from_seed_fixture_v2(reviewed_source_use_native_seeds[version])


def reviewed_source_use_native_reopen(c, receipt, packet, **changes):
    formatter = reviewed_source_use_native_api(c, "reviewed_norm_preservation_receipt_bytes")
    packet_sha = reviewed_source_use_native_api(c, "reviewed_norm_preservation_packet_sha256")
    options = reviewed_source_use_native_arguments(c) | dict(
        expected_receipt_sha256=sha(dict(packet)["build-receipt.json"]),
        expected_packet_sha256=packet_sha(packet, instance_identity_profile="reviewed-source-use/v1"),
        expected_binary_sha256=receipt["binary_sha256"],
        observation_profile="fictional-authored-observation/v1")
    return reviewed_source_use_native_api(c, "validate_reviewed_norm_preservation_native_receipt")(
        formatter(receipt, instance_identity_profile="reviewed-source-use/v1"),
        c["preparation"], c["graph"], c["admission"], *c["args"], packet_files=packet,
        **(options | changes))


@pytest.mark.parametrize("version", (2, 3))
def test_reviewed_source_use_native_validation_retains_three_distinct_instances(version, reviewed_source_use_native_case):
    c, _, _, _ = reviewed_source_use_native_case
    validate = reviewed_source_use_native_api(c, "validate_reviewed_norm_preservation_native")
    assert validate(c["preparation"], c["graph"], c["admission"], *c["args"],
        **reviewed_source_use_native_arguments(c)) == c["preparation"]
    manifest = c["preparation"].to_dict()
    assert manifest["instance_identity_profile"] == "reviewed-source-use/v1"
    assert len({row["instance_module"] for row in manifest["units"]}) == 3
    assert len(set(manifest["preservation_obligations"])) == 15
    for unit in manifest["units"]:
        assert unit["source_use_binding"]["source_occurrence_cid"] == unit["source_occurrence_cid"]
        assert sha(canonical(unit["source_use_binding"])) == unit["source_use_binding_sha256"]
        assert len(unit["original_child_files"]) == 7 and len(unit["preservation_obligations"]) == 5
    defaults = reviewed_native_arguments_v2(c)
    with pytest.raises(ValueError):
        validate(c["preparation"], c["graph"], c["admission"], *c["args"], **defaults)


@pytest.mark.parametrize("version", (2, 3))
def test_reviewed_source_use_authored_build_persists_exact_obligations_and_formatter(version, reviewed_source_use_native_case):
    c, receipt, packet, calls = reviewed_source_use_native_case
    manifest = c["preparation"].to_dict()
    formatter = reviewed_source_use_native_api(c, "reviewed_norm_preservation_receipt_bytes")
    assert len(calls) == 1 and receipt["build_passed"] is True
    assert receipt["profile"].endswith("+reviewed-source-use/v1")
    assert receipt["instance_identity_profile"] == "reviewed-source-use/v1"
    assert receipt["conditional_theorems"] == manifest["preservation_obligations"]
    assert set(receipt["theorem_axiom_dependencies"]) == set(manifest["preservation_obligations"])
    assert all(value == [] for value in receipt["theorem_axiom_dependencies"].values())
    assert receipt["expected_modules"] == receipt["compiled_modules"] == manifest["expected_modules"]
    assert formatter(receipt, instance_identity_profile="reviewed-source-use/v1") == dict(packet)["build-receipt.json"]
    for name, raw in c["preparation"].files:
        assert dict(packet)["project/" + name] == dict(packet)["executed-inputs/" + name] == raw.encode()
    assert all(value is False for value in receipt["authority"].values())
    assert receipt["training_mask"] == receipt["evaluation_gold_mask"] == 0
    with pytest.raises(ValueError):
        formatter(receipt)  # Default formatting cannot relabel the selected domain.


@pytest.mark.parametrize("version", (2, 3))
def test_reviewed_source_use_retained_observations_keep_zero_live_authority(version, reviewed_source_use_native_case, monkeypatch):
    c, receipt, packet, _ = reviewed_source_use_native_case
    reviewed_retained_no_tools_v2(monkeypatch)
    result = reviewed_source_use_native_reopen(c, receipt, packet)
    assert result["profile"].endswith("+reviewed-source-use/v1")
    assert result["instance_identity_profile"] == "reviewed-source-use/v1"
    assert result["retained_observations_consistent"] is result["current_complete_semantics_replayed"] is True
    for key in ("original_success_authenticated", "native_execution_authenticated", "native_execution_performed",
                "olean_kernel_rechecked", "release_ready", "Lean_admitted"):
        assert result[key] is False
    assert result.get("live_native_success_authenticated", False) is False
    assert all(value is False for value in result["authority"].values())
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    assert len(result["obligations"]) == 15 and len(result["packet_inventory"]) == len(packet)


@pytest.mark.parametrize("version", (2, 3))
def test_reviewed_source_use_resealed_foreign_binding_cannot_replace_current_unit(version, reviewed_source_use_native_case):
    c, _, _, _ = reviewed_source_use_native_case
    validate = reviewed_source_use_native_api(c, "validate_reviewed_norm_preservation_native")
    for damage in ("binding", "digest", "selector"):
        manifest = c["preparation"].to_dict()
        if damage == "binding":
            manifest["units"][1]["source_use_binding"] = deepcopy(manifest["units"][2]["source_use_binding"])
            manifest["units"][1]["source_use_binding_sha256"] = sha(canonical(manifest["units"][1]["source_use_binding"]))
        elif damage == "digest":
            manifest["units"][1]["source_use_binding_sha256"] = "0" * 64
        else:
            manifest["instance_identity_profile"] = "reviewed-source-use/v0"
        forged = reseal_manifest(c["preparation"], manifest)
        options = reviewed_source_use_native_arguments(c) | dict(
            expected_preservation_sha256=c["shared"].reviewed_preservation_corpus_sha256(forged))
        with pytest.raises(ValueError):
            validate(forged, c["graph"], c["admission"], *c["args"], **options)


@pytest.mark.parametrize("version", (2, 3))
def test_reviewed_source_use_repaired_receipt_cannot_select_default_or_foreign_profile(version, reviewed_source_use_native_case):
    c, receipt, packet, _ = reviewed_source_use_native_case
    formatter = reviewed_source_use_native_api(c, "reviewed_norm_preservation_receipt_bytes")
    forged = deepcopy(receipt)
    forged.pop("instance_identity_profile")
    forged["profile"] = forged["profile"].removesuffix("+reviewed-source-use/v1")
    forged = contracts.seal_record({key: value for key, value in forged.items() if key not in {"record_cid", "cid_scope"}})
    with pytest.raises(ValueError):
        formatter(forged, instance_identity_profile="reviewed-source-use/v1")
    for invalid in (False, True, "reviewed-source-use/v0", ""):
        with pytest.raises(ValueError):
            formatter(receipt, instance_identity_profile=invalid)
    options = reviewed_source_use_native_arguments(c)
    options.pop("instance_identity_profile")
    options.update(expected_receipt_sha256=sha(dict(packet)["build-receipt.json"]),
        expected_packet_sha256=reviewed_source_use_native_api(c, "reviewed_norm_preservation_packet_sha256")(packet),
        expected_binary_sha256=receipt["binary_sha256"], observation_profile="fictional-authored-observation/v1")
    with pytest.raises(ValueError):
        reviewed_source_use_native_api(c, "load_reviewed_norm_preservation_native")(
            packet, c["preparation"], c["graph"], c["admission"], *c["args"], **options)


@pytest.mark.parametrize("version", (2, 3))
def test_reviewed_source_use_authored_packet_cannot_mint_a_live_capability(version, reviewed_source_use_native_case, monkeypatch):
    c, receipt, packet, _ = reviewed_source_use_native_case
    options = reviewed_source_use_native_arguments(c) | dict(
        expected_receipt_sha256=sha(dict(packet)["build-receipt.json"]),
        expected_packet_sha256=reviewed_source_use_native_api(c, "reviewed_norm_preservation_packet_sha256")(packet),
        expected_binary_sha256=receipt["binary_sha256"])
    monkeypatch.setattr(native, "_owners", lambda: pytest.fail("unissued handle reached operation owners"))
    loader = reviewed_source_use_native_api(c, "load_verified_reviewed_norm_preservation_native")
    for handle in (object(), object.__new__(native.VerifiedReviewedPreservationNativeSuccess), receipt):
        with pytest.raises(ValueError, match="not issued"):
            loader(handle, packet, c["preparation"], c["graph"], c["admission"], *c["args"], **options)
    states = dict(native._LIVE_NATIVE_FUNCTIONS)
    for name in ("_reviewed_source_use_kwargs", "_reviewed_source_use_domain", "_reviewed_source_use_manifest"):
        assert states[name][0] is getattr(native, name)
        assert states[name][1] is getattr(native, name).__code__


@pytest.mark.parametrize("version", (2, 3))
def test_reviewed_source_use_installed_lean_keeps_actual_live_and_retained_domains_separate(
        version, bound_norm_installed_lake, tmp_path):
    # The existing pinned installed-Lean fixture is the opt-in gate. Its binary
    # source pins and admitted original resource profile remain unchanged.
    executable, binary_pins = bound_norm_installed_lake
    c = reviewed_source_use_native_control_data(version)
    options = reviewed_source_use_native_arguments(c)
    output = tmp_path / "source-use-live-native"
    handle = reviewed_source_use_native_api(c, "build_verified_reviewed_norm_preservation_native")(
        c["preparation"], c["graph"], c["admission"], *c["args"],
        lake_executable=str(executable), output_directory=output, timeout_seconds=60, **options)
    packet = tuple(sorted((str(p.relative_to(output)), p.read_bytes())for p in output.rglob("*")if p.is_file()))
    receipt = json.loads(dict(packet)["build-receipt.json"])
    assert receipt["binary_sha256"] == binary_pins
    assert receipt["build_passed"] is receipt["kernel_proofs_checked"] is True
    assert receipt["conditional_theorems"] == c["preparation"].to_dict()["preservation_obligations"]
    assert len(receipt["theorem_axiom_dependencies"]) == 15
    assert all(value == [] for value in receipt["theorem_axiom_dependencies"].values())
    common = dict(expected_receipt_sha256=sha(dict(packet)["build-receipt.json"]),
        expected_packet_sha256=reviewed_source_use_native_api(c, "reviewed_norm_preservation_packet_sha256")(packet),
        expected_binary_sha256=binary_pins)
    live = reviewed_source_use_native_api(c, "load_verified_reviewed_norm_preservation_native")(
        handle, packet, c["preparation"], c["graph"], c["admission"], *c["args"], **(options | common))
    assert live["live_native_success_authenticated"] is live["native_execution_authenticated"] is True
    assert live["profile"].endswith("+reviewed-source-use/v1")
    assert live["original_admitted_parent_custody_authenticated"] is live["release_ready"] is False
    assert live["training_mask"] == live["evaluation_gold_mask"] == 0
    retained = reviewed_source_use_native_api(c, "load_reviewed_norm_preservation_native")(
        packet, c["preparation"], c["graph"], c["admission"], *c["args"],
        **(options | common | dict(observation_profile=native._REVIEWED_REPLAY_ACTUAL)))
    assert retained["retained_observations_consistent"] is True
    assert retained["native_execution_authenticated"] is retained.get("live_native_success_authenticated", False) is False
    default_options = dict(options)
    default_options.pop("instance_identity_profile")
    with pytest.raises(ValueError, match="not issued"):
        reviewed_source_use_native_api(c, "load_verified_reviewed_norm_preservation_native")(
            handle, packet, c["preparation"], c["graph"], c["admission"], *c["args"], **(default_options | common))


# Constructed-definition domain controls. Source/review fixtures are fictional;
# synthetic_compiler supplies authored metadata only, never Native proof credit.
@pytest.fixture
def reviewed_realization_native_control_v1(reviewed_native_control_v3):
    control = dict(reviewed_native_control_v3)
    control["preservation"] = control["preparation"]
    control["preparation"] = control["shared"].prepare_reviewed_definition_realization_corpus_v1(
        control["preservation"], control["graph"], control["admission"], *control["args"],
        expected_preservation_sha256=control["shared"].reviewed_preservation_corpus_sha256(control["preservation"]),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN, **control["kwargs"])
    return control


def reviewed_realization_native_arguments_v1(control):
    return dict(expected_realization_sha256=control["shared"].reviewed_preservation_corpus_sha256(control["preparation"]),
        expected_preservation_sha256=control["shared"].reviewed_preservation_corpus_sha256(control["preservation"]),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN, **control["kwargs"])


def reviewed_realization_native_validate_v1(control, **changes):
    return native.validate_reviewed_definition_realization_native_v1(control["preparation"], control["preservation"],
        control["graph"], control["admission"], *control["args"],
        **(reviewed_realization_native_arguments_v1(control) | changes))


def reviewed_realization_native_build_v1(control, executable, output, **changes):
    return native.build_reviewed_definition_realization_native_v1(control["preparation"], control["preservation"],
        control["graph"], control["admission"], *control["args"],
        **(reviewed_realization_native_arguments_v1(control) | dict(lake_executable=str(executable),
            output_directory=output, timeout_seconds=12) | changes))


def test_realization_native_validation_replays_both_envelopes_without_a_compiler(
        reviewed_realization_native_control_v1, monkeypatch):
    c = reviewed_realization_native_control_v1
    reviewed_retained_no_tools_v2(monkeypatch)
    assert reviewed_realization_native_validate_v1(c) == c["preparation"]
    m = c["preparation"].to_dict()
    assert len(m["units"]) == 3 and len(m["preservation_obligations"]) == 26
    assert len(m["realization_obligations"]) == 11 and len(m["expected_modules"]) == 10
    assert len(c["preparation"].files) == 39
    old = dict(c, preparation=c["preservation"])
    assert reviewed_native_validate_v3(old) == c["preservation"]
    with pytest.raises(ValueError):
        native.validate_reviewed_norm_preservation_native_v3(c["preparation"], c["graph"], c["admission"],
            *c["args"], **reviewed_native_arguments_v3(c))


@pytest.mark.parametrize("pin", ["expected_realization_sha256", "expected_preservation_sha256",
    "expected_graph_sha256", "expected_admission_sha256"])
def test_realization_native_malformed_independent_pins_refuse_before_owners(
        reviewed_realization_native_control_v1, monkeypatch, pin):
    monkeypatch.setattr(native, "_owners", lambda: pytest.fail("malformed pin reached operation imports"))
    with pytest.raises(ValueError, match="independent lowercase SHA256"):
        reviewed_realization_native_validate_v1(reviewed_realization_native_control_v1, **{pin: "not-a-sha256"})


def test_realization_native_authored_runner_keeps_complete_new_domain_and_empty_axiom_inventory(
        reviewed_realization_native_control_v1, synthetic_compiler, tmp_path):
    c = reviewed_realization_native_control_v1
    executable, calls = synthetic_compiler(c["preparation"], stdout=reviewed_native_stdout_v2(c["preparation"]))
    output = tmp_path / "authored-realization-packet"
    receipt = reviewed_realization_native_build_v1(c, executable, output)
    assert len(calls) == 1  # Synthetic protocol invocation, not a compiler process.
    assert receipt["schema"] == native.REVIEWED_DEFINITION_REALIZATION_BUILD_SCHEMA
    assert receipt["profile"] == native.REVIEWED_DEFINITION_REALIZATION_NATIVE_PROFILE
    assert receipt["build_passed"] is receipt["axiom_observations_passed"] is True
    assert receipt["constructed_model_only"] is True and receipt["preservation_only"] is False
    assert receipt["reviewed_preservation_sha256"] == c["shared"].reviewed_preservation_corpus_sha256(c["preservation"])
    assert receipt["conditional_theorems"] == c["preparation"].to_dict()["preservation_obligations"]
    assert len(receipt["compiled_modules"]) == 10 and len(receipt["executed_project_sha256"]) == 39
    assert len(receipt["theorem_axiom_dependencies"]) == 26
    assert all(value == [] for value in receipt["theorem_axiom_dependencies"].values())
    assert receipt["cross_unit_definition_application_proved"] is receipt["statutory_meaning_proved"] is False
    assert all(value is False for value in receipt["authority"].values())
    assert receipt["training_mask"] == receipt["evaluation_gold_mask"] == 0
    assert native.reviewed_definition_realization_receipt_bytes_v1(receipt) == (output / "build-receipt.json").read_bytes()
    with pytest.raises(ValueError):
        native.reviewed_norm_preservation_receipt_bytes_v3(receipt)


@pytest.mark.parametrize("facet", ["original", "body-source", "definition-model", "occurrence-source", "occurrence-body", "whole-child"])
def test_realization_native_requires_old_and_every_new_obligation_class(
        reviewed_realization_native_control_v1, synthetic_compiler, tmp_path, facet):
    c = reviewed_realization_native_control_v1
    lines = reviewed_native_stdout_v2(c["preparation"]).splitlines()
    marker = {"original": ".native_value_exact", "body-source": ".definition_body_source_exact",
        "definition-model": ".definition_realized", "occurrence-source": ".occurrence_1_source_exact",
        "occurrence-body": ".occurrence_2_matches_body", "whole-child": ".unit_1_preservation_under_realization"}[facet]
    index = next(i for i, line in enumerate(lines) if marker in line)
    lines.pop(index)
    executable, calls = synthetic_compiler(c["preparation"], stdout="\n".join(lines) + "\n")
    receipt = reviewed_realization_native_build_v1(c, executable, tmp_path / ("missing-realization-" + facet))
    assert len(calls) == 1 and receipt["build_passed"] is receipt["axiom_observations_passed"] is False
    assert receipt["proof_checked"] is False


@pytest.mark.parametrize("damage", ["new-module", "old-module", "source"])
def test_realization_native_requires_all_old_new_artifacts_and_exact_executed_sources(
        reviewed_realization_native_control_v1, synthetic_compiler, tmp_path, damage):
    c = reviewed_realization_native_control_v1
    def edit(outputs, artifacts, sources):
        if damage == "new-module": outputs.pop(artifacts[-2])
        elif damage == "old-module": outputs.pop(artifacts[0])
        else: outputs[sources[-1]] += b" changed exact execution input"
    executable, calls = synthetic_compiler(c["preparation"], stdout=reviewed_native_stdout_v2(c["preparation"]), output_edit=edit)
    receipt = reviewed_realization_native_build_v1(c, executable, tmp_path / ("incomplete-realization-" + damage))
    assert len(calls) == 1 and receipt["build_passed"] is receipt["proof_checked"] is False


def test_realization_retained_authored_packet_replays_without_new_execution_or_live_authority(
        reviewed_realization_native_control_v1, synthetic_compiler, monkeypatch, tmp_path):
    c = reviewed_realization_native_control_v1
    executable, calls = synthetic_compiler(c["preparation"], stdout=reviewed_native_stdout_v2(c["preparation"]))
    output = tmp_path / "authored-realization-retained"
    receipt = reviewed_realization_native_build_v1(c, executable, output)
    packet = reviewed_live_success_packet_v2(output)
    before = deepcopy((receipt, packet, c["graph"], c["admission"]))
    reviewed_retained_no_tools_v2(monkeypatch)
    options = reviewed_realization_native_arguments_v1(c) | dict(
        expected_receipt_sha256=sha(dict(packet)["build-receipt.json"]),
        expected_packet_sha256=native.reviewed_definition_realization_packet_sha256_v1(packet),
        expected_binary_sha256=receipt["binary_sha256"], observation_profile=native._REVIEWED_REPLAY_FICTIONAL)
    replay = native.load_reviewed_definition_realization_native_v1(packet, c["preparation"], c["preservation"],
        c["graph"], c["admission"], *c["args"], **options)
    assert len(calls) == 1 and replay["retained_observations_consistent"] is True
    assert replay["current_complete_semantics_replayed"] is True and replay["constructed_model_only"] is True
    assert replay["obligations"] == c["preparation"].to_dict()["preservation_obligations"]
    assert replay["native_execution_authenticated"] is replay["live_native_success_authenticated"] is False
    assert replay["native_execution_performed"] is replay["olean_kernel_rechecked"] is False
    assert all(value is False for value in replay["authority"].values())
    assert before == (receipt, packet, c["graph"], c["admission"])
    with pytest.raises(ValueError):
        native.load_reviewed_definition_realization_native_v1(packet, c["preparation"], c["preservation"],
            c["graph"], c["admission"], *c["args"], **(options | dict(observation_profile=native._REVIEWED_REPLAY_ACTUAL)))
    with pytest.raises(ValueError):
        native.load_reviewed_norm_preservation_native_v3(packet, c["preparation"], c["graph"], c["admission"],
            *c["args"], **(reviewed_native_arguments_v3(c) | dict(
                expected_receipt_sha256=sha(dict(packet)["build-receipt.json"]),
                expected_packet_sha256=native.reviewed_norm_preservation_packet_sha256_v3(packet),
                expected_binary_sha256=receipt["binary_sha256"], observation_profile=native._REVIEWED_REPLAY_FICTIONAL)))


@pytest.mark.parametrize("timeout", [0, -1, 61, float("nan"), True])
def test_realization_live_invalid_timeout_refuses_before_owners(monkeypatch, timeout):
    monkeypatch.setattr(native, "_owners", lambda: pytest.fail("invalid timeout reached owners"))
    with pytest.raises(ValueError, match="finite compiler timeout"):
        native.build_verified_reviewed_definition_realization_native_v1(None, None, {}, {},
            expected_realization_sha256="1" * 64, expected_preservation_sha256="2" * 64,
            expected_graph_sha256="3" * 64, expected_admission_sha256="4" * 64, toolchain=TOOLCHAIN,
            lake_executable="unopened", output_directory="uncreated", timeout_seconds=timeout)


@pytest.mark.parametrize("handle_kind", ["none", "dict", "object", "unissued"])
def test_realization_live_does_not_accept_caller_or_old_domain_success(monkeypatch, handle_kind):
    handles = {"none": None, "dict": {"native_execution_authenticated": True}, "object": object(),
        "unissued": object.__new__(native.VerifiedReviewedPreservationNativeSuccess)}
    monkeypatch.setattr(native, "_owners", lambda: pytest.fail("unissued handle reached owners"))
    with pytest.raises(ValueError, match="not issued by this process and native thread"):
        native.load_verified_reviewed_definition_realization_native_v1(handles[handle_kind], (), None, None, {}, {},
            expected_receipt_sha256="1" * 64, expected_packet_sha256="2" * 64, expected_binary_sha256={},
            expected_realization_sha256="3" * 64, expected_preservation_sha256="4" * 64,
            expected_graph_sha256="5" * 64, expected_admission_sha256="6" * 64, toolchain=TOOLCHAIN)


def test_realization_native_late_source_mutation_after_genuine_shared_replay_refuses(
        reviewed_realization_native_control_v1, monkeypatch):
    c = reviewed_realization_native_control_v1
    original = c["shared"].validate_reviewed_definition_realization_corpus_v1
    observed = []
    def replay_then_mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        observed.append(True)
        unit = c["case"]["declaration"]["units"][1]["unit_id"]
        c["kwargs"]["preparation_inputs"]["source_inputs"][unit]["raw_bytes"] += b" changed after genuine replay"
        return result
    monkeypatch.setattr(c["shared"], "validate_reviewed_definition_realization_corpus_v1", replay_then_mutate)
    reviewed_retained_no_tools_v2(monkeypatch)
    with pytest.raises(ValueError, match="changed"):
        reviewed_realization_native_validate_v1(c)
    assert observed


def test_realization_native_installed_lean_uses_existing_verified_owner_and_all26_obligations(
        bound_norm_installed_lake, reviewed_realization_native_control_v1, tmp_path):
    # The pre-existing admitted Native fixture owns opt-in, toolchain and resources.
    # Ordinary source runs skip here; no synthetic boundary may satisfy this case.
    executable, binary_pins = bound_norm_installed_lake
    c = reviewed_realization_native_control_v1
    output = tmp_path / "actual-original-realization"
    handle = native.build_verified_reviewed_definition_realization_native_v1(c["preparation"], c["preservation"],
        c["graph"], c["admission"], *c["args"], **(reviewed_realization_native_arguments_v1(c) | dict(
            lake_executable=str(executable), output_directory=output, timeout_seconds=60)))
    packet = reviewed_live_success_packet_v2(output)
    receipt = json.loads(dict(packet)["build-receipt.json"])
    assert receipt["binary_sha256"] == binary_pins and receipt["build_passed"] is True
    assert len(receipt["compiled_modules"]) == 10 and len(receipt["theorem_axiom_dependencies"]) == 26
    assert all(value == [] for value in receipt["theorem_axiom_dependencies"].values())
    joined = native.load_verified_reviewed_definition_realization_native_v1(handle, packet,
        c["preparation"], c["preservation"], c["graph"], c["admission"], *c["args"],
        **(reviewed_realization_native_arguments_v1(c) | dict(expected_receipt_sha256=sha(dict(packet)["build-receipt.json"]),
            expected_packet_sha256=native.reviewed_definition_realization_packet_sha256_v1(packet),
            expected_binary_sha256=binary_pins)))
    assert joined["live_native_success_authenticated"] is True and joined["constructed_model_only"] is True
    assert joined["original_admitted_parent_custody_authenticated"] is False
    assert joined["cross_unit_definition_application_proved"] is joined["statutory_meaning_proved"] is False
    assert all(value is False for value in joined["authority"].values())


# A single authored selected-mode packet feeds independent retained controls.
# The separate opt-in installed-Lean case below never consumes this seed.
def reviewed_realization_source_use_native_control_v1(original):
    c = dict(original)
    c["preservation"] = c["shared"].prepare_reviewed_norm_preservation_corpus_v3(
        c["graph"], c["admission"], *c["args"], expected_graph_sha256=c["graph_sha"],
        expected_admission_sha256=c["admission_sha"], toolchain=TOOLCHAIN,
        instance_identity_profile="reviewed-source-use/v1", **c["kwargs"])
    c["preparation"] = c["shared"].prepare_reviewed_definition_realization_corpus_v1(
        c["preservation"], c["graph"], c["admission"], *c["args"],
        expected_preservation_sha256=c["shared"].reviewed_preservation_corpus_sha256(c["preservation"]),
        expected_graph_sha256=c["graph_sha"], expected_admission_sha256=c["admission_sha"],
        toolchain=TOOLCHAIN, instance_identity_profile="reviewed-source-use/v1", **c["kwargs"])
    return c


def reviewed_realization_source_use_native_arguments_v1(c):
    return reviewed_realization_native_arguments_v1(c) | {"instance_identity_profile": "reviewed-source-use/v1"}


@pytest.fixture(scope="module")
def reviewed_realization_source_use_native_seed_v1(reviewed_native_seed_v3, tmp_path_factory):
    original, _, _, _ = reviewed_retained_case_from_seed_fixture_v2(reviewed_native_seed_v3)
    c = reviewed_realization_source_use_native_control_v1(original)
    directory = tmp_path_factory.mktemp("reviewed-realization-source-use-native-seed", numbered=False)
    with pytest.MonkeyPatch.context() as patcher:
        install = synthetic_compiler.__wrapped__(patcher, directory)
        executable, calls = install(c["preparation"], stdout=reviewed_native_stdout_v2(c["preparation"]))
        output = directory / "authored-realization-source-use"
        receipt = reviewed_realization_native_build_v1(c, executable, output,
            instance_identity_profile="reviewed-source-use/v1")
        packet = reviewed_live_success_packet_v2(output)
        assert len(calls) == 1
    fixed = ("helper", "mixed_helper", "owner", "shared", "shared_helper", "preparation", "preservation")
    environment = tuple((key, c[key]) for key in fixed)
    data = {key: value for key, value in c.items() if key not in fixed}
    data["case"] = dict(data["case"])
    signers = tuple(data["case"].pop("signers"))
    snapshot = reviewed_retained_freeze_fixture_data_v2({"control": data, "receipt": receipt})
    return environment, snapshot, signers, packet, tuple(calls)


@pytest.fixture
def reviewed_realization_source_use_native_case_v1(reviewed_realization_source_use_native_seed_v1):
    return reviewed_retained_case_from_seed_fixture_v2(reviewed_realization_source_use_native_seed_v1)


def reviewed_realization_source_use_native_replay_options_v1(c, receipt, packet):
    return reviewed_realization_source_use_native_arguments_v1(c) | dict(
        expected_receipt_sha256=sha(dict(packet)["build-receipt.json"]),
        expected_packet_sha256=native.reviewed_definition_realization_packet_sha256_v1(packet,
            instance_identity_profile="reviewed-source-use/v1"), expected_binary_sha256=receipt["binary_sha256"])


def test_realization_source_use_authored_packet_keeps_all26_obligations_and_closed_original_bindings(
        reviewed_realization_source_use_native_case_v1):
    c, receipt, packet, calls = reviewed_realization_source_use_native_case_v1
    manifest = c["preparation"].to_dict()
    assert len(calls) == 1 and receipt["build_passed"] is True
    assert receipt["profile"] == native.REVIEWED_DEFINITION_REALIZATION_NATIVE_PROFILE + "+reviewed-source-use/v1"
    assert receipt["instance_identity_profile"] == manifest["instance_identity_profile"] == "reviewed-source-use/v1"
    assert receipt["conditional_theorems"] == manifest["preservation_obligations"]
    assert len(receipt["compiled_modules"]) == 10 and len(receipt["executed_project_sha256"]) == 39
    assert len(receipt["theorem_axiom_dependencies"]) == 26
    assert all(value == [] for value in receipt["theorem_axiom_dependencies"].values())
    assert manifest["units"] == manifest["upstream_manifest"]["units"] == c["preservation"].to_dict()["units"]
    assert len({row["instance_module"] for row in manifest["units"]}) == 3
    for unit in manifest["units"]:
        assert sha(canonical(unit["source_use_binding"])) == unit["source_use_binding_sha256"]
        assert len(unit["original_child_files"]) == 7 and len(unit["preservation_obligations"]) == 5
    assert native.reviewed_definition_realization_receipt_bytes_v1(receipt,
        instance_identity_profile="reviewed-source-use/v1") == dict(packet)["build-receipt.json"]
    for name, raw in c["preparation"].files:
        assert dict(packet)["project/" + name] == dict(packet)["executed-inputs/" + name] == raw.encode()
    assert all(value is False for value in receipt["authority"].values())
    assert receipt["cross_unit_definition_application_proved"] is receipt["statutory_meaning_proved"] is False
    assert receipt["training_mask"] == receipt["evaluation_gold_mask"] == 0


def test_realization_source_use_retained_packet_has_no_live_authority_and_cannot_cross_mode(
        reviewed_realization_source_use_native_case_v1, monkeypatch):
    c, receipt, packet, calls = reviewed_realization_source_use_native_case_v1
    before = deepcopy((receipt, packet, c["graph"], c["admission"]))
    reviewed_retained_no_tools_v2(monkeypatch)
    options = reviewed_realization_source_use_native_replay_options_v1(c, receipt, packet)
    replay = native.load_reviewed_definition_realization_native_v1(packet, c["preparation"], c["preservation"],
        c["graph"], c["admission"], *c["args"],
        **(options | dict(observation_profile=native._REVIEWED_REPLAY_FICTIONAL)))
    assert replay["profile"].endswith("+reviewed-source-use/v1")
    assert replay["instance_identity_profile"] == "reviewed-source-use/v1"
    assert replay["retained_observations_consistent"] is replay["current_complete_semantics_replayed"] is True
    assert replay["obligations"] == c["preparation"].to_dict()["preservation_obligations"]
    assert len(replay["obligations"]) == 26
    for key in ("native_execution_authenticated", "live_native_success_authenticated", "native_execution_performed",
                "olean_kernel_rechecked", "original_success_authenticated", "release_ready"):
        assert replay.get(key, False) is False
    assert all(value is False for value in replay["authority"].values())
    assert replay["training_mask"] == replay["evaluation_gold_mask"] == 0
    assert len(calls) == 1 and before == (receipt, packet, c["graph"], c["admission"])
    with pytest.raises(ValueError):
        native.reviewed_definition_realization_receipt_bytes_v1(receipt)
    default_options = dict(options)
    default_options.pop("instance_identity_profile")
    with pytest.raises(ValueError):
        native.load_reviewed_definition_realization_native_v1(packet, c["preparation"], c["preservation"],
            c["graph"], c["admission"], *c["args"],
            **(default_options | dict(observation_profile=native._REVIEWED_REPLAY_FICTIONAL)))
    forged = deepcopy(receipt)
    forged.pop("instance_identity_profile")
    forged["profile"] = native.REVIEWED_DEFINITION_REALIZATION_NATIVE_PROFILE
    forged = contracts.seal_record({key: value for key, value in forged.items() if key not in {"record_cid", "cid_scope"}})
    with pytest.raises(ValueError):
        native.reviewed_definition_realization_receipt_bytes_v1(forged, instance_identity_profile="reviewed-source-use/v1")


def test_realization_source_use_installed_lean_keeps_actual_live_and_retained_all26_separate(
        bound_norm_installed_lake, reviewed_native_control_v3, tmp_path):
    # Only the existing independently pinned installed-Lean fixture admits this
    # actual process. Authored packets above cannot satisfy its live handle.
    executable, binary_pins = bound_norm_installed_lake
    c = reviewed_realization_source_use_native_control_v1(reviewed_native_control_v3)
    options = reviewed_realization_source_use_native_arguments_v1(c)
    output = tmp_path / "actual-realization-source-use"
    handle = native.build_verified_reviewed_definition_realization_native_v1(c["preparation"], c["preservation"],
        c["graph"], c["admission"], *c["args"],
        **(options | dict(lake_executable=str(executable), output_directory=output, timeout_seconds=60)))
    packet = reviewed_live_success_packet_v2(output)
    receipt = json.loads(dict(packet)["build-receipt.json"])
    assert receipt["binary_sha256"] == binary_pins and receipt["build_passed"] is True
    assert receipt["profile"] == native.REVIEWED_DEFINITION_REALIZATION_NATIVE_PROFILE + "+reviewed-source-use/v1"
    assert receipt["instance_identity_profile"] == "reviewed-source-use/v1"
    assert len(receipt["compiled_modules"]) == 10 and len(receipt["theorem_axiom_dependencies"]) == 26
    assert receipt["conditional_theorems"] == c["preparation"].to_dict()["preservation_obligations"]
    assert all(value == [] for value in receipt["theorem_axiom_dependencies"].values())
    common = reviewed_realization_source_use_native_replay_options_v1(c, receipt, packet)
    live = native.load_verified_reviewed_definition_realization_native_v1(handle, packet,
        c["preparation"], c["preservation"], c["graph"], c["admission"], *c["args"], **common)
    assert live["live_native_success_authenticated"] is live["native_execution_authenticated"] is True
    retained = native.load_reviewed_definition_realization_native_v1(packet, c["preparation"], c["preservation"],
        c["graph"], c["admission"], *c["args"], **(common | dict(observation_profile=native._REVIEWED_REPLAY_ACTUAL)))
    assert retained["retained_observations_consistent"] is True
    assert retained["native_execution_authenticated"] is retained.get("live_native_success_authenticated", False) is False
    assert retained["obligations"] == live["obligations"] == receipt["conditional_theorems"]
    for result in (live, retained):
        assert result["cross_unit_definition_application_proved"] is result["statutory_meaning_proved"] is False
        assert result["release_ready"] is result["original_admitted_parent_custody_authenticated"] is False
        assert not any(result["authority"].values())
        assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    default_options = dict(common)
    default_options.pop("instance_identity_profile")
    with pytest.raises(ValueError, match="not issued"):
        native.load_verified_reviewed_definition_realization_native_v1(handle, packet,
            c["preparation"], c["preservation"], c["graph"], c["admission"], *c["args"], **default_options)


# Authored packet controls exercise the existing wire/replay boundary only.
# Their synthetic runner supplies no installed Lean or statutory proof credit.
def reviewed_whole_norm_native_options_v1(c):
    identity = c["whole_norm_identity_profile"]
    return reviewed_realization_native_arguments_v1(c) | {
        "definition_application_profile": "whole-norm-definition-expansion/v1"} | (
        {} if identity is None else {"instance_identity_profile": identity})


@pytest.fixture(scope="module", params=[None, "reviewed-source-use/v1"], ids=["default", "source-use"])
def reviewed_whole_norm_native_seed_v1(reviewed_native_seed_v3, tmp_path_factory, request):
    c, _, _, _ = reviewed_retained_case_from_seed_fixture_v2(reviewed_native_seed_v3)
    c["whole_norm_identity_profile"] = request.param
    identity = {} if request.param is None else {"instance_identity_profile": request.param}
    c["preservation"] = c["preparation"] if request.param is None else \
        c["shared"].prepare_reviewed_norm_preservation_corpus_v3(c["graph"], c["admission"],
            *c["args"], expected_graph_sha256=c["graph_sha"], expected_admission_sha256=c["admission_sha"],
            toolchain=TOOLCHAIN, **identity, **c["kwargs"])
    c["preparation"] = c["shared"].prepare_reviewed_definition_realization_corpus_v1(
        c["preservation"], c["graph"], c["admission"], *c["args"],
        expected_preservation_sha256=c["shared"].reviewed_preservation_corpus_sha256(c["preservation"]),
        expected_graph_sha256=c["graph_sha"], expected_admission_sha256=c["admission_sha"],
        toolchain=TOOLCHAIN, definition_application_profile="whole-norm-definition-expansion/v1",
        **identity, **c["kwargs"])
    directory = tmp_path_factory.mktemp("reviewed-whole-norm-native-" + ("default" if request.param is None else "source-use"), numbered=False)
    with pytest.MonkeyPatch.context() as patcher:
        install = synthetic_compiler.__wrapped__(patcher, directory)
        executable, calls = install(c["preparation"], stdout=reviewed_native_stdout_v2(c["preparation"]))
        output = directory / "authored-whole-norm"
        receipt = reviewed_realization_native_build_v1(c, executable, output,
            **{key: value for key, value in reviewed_whole_norm_native_options_v1(c).items()
               if key in {"instance_identity_profile", "definition_application_profile"}})
        packet = reviewed_live_success_packet_v2(output)
        assert len(calls) == 1
    fixed = ("helper", "mixed_helper", "owner", "shared", "shared_helper", "preparation", "preservation")
    environment = tuple((key, c[key]) for key in fixed)
    data = {key: value for key, value in c.items() if key not in fixed}
    data["case"] = dict(data["case"])
    signers = tuple(data["case"].pop("signers"))
    snapshot = reviewed_retained_freeze_fixture_data_v2({"control": data, "receipt": receipt})
    return environment, snapshot, signers, packet, tuple(calls)


@pytest.fixture
def reviewed_whole_norm_native_case_v1(reviewed_whole_norm_native_seed_v1):
    return reviewed_retained_case_from_seed_fixture_v2(reviewed_whole_norm_native_seed_v1)


def reviewed_whole_norm_native_reopen_v1(c, receipt, packet, **changes):
    identity = {} if c["whole_norm_identity_profile"] is None else {
        "instance_identity_profile": c["whole_norm_identity_profile"]}
    selected = {"definition_application_profile": "whole-norm-definition-expansion/v1"}
    options = reviewed_whole_norm_native_options_v1(c) | dict(
        expected_receipt_sha256=sha(dict(packet)["build-receipt.json"]),
        expected_packet_sha256=native.reviewed_definition_realization_packet_sha256_v1(packet, **identity, **selected),
        expected_binary_sha256=receipt["binary_sha256"], observation_profile=native._REVIEWED_REPLAY_FICTIONAL)
    return native.load_reviewed_definition_realization_native_v1(packet, c["preparation"], c["preservation"],
        c["graph"], c["admission"], *c["args"], **(options | changes))


def test_whole_norm_native_authored_packet_keeps_all30_and_complete_application_witnesses(
        reviewed_whole_norm_native_case_v1):
    c, receipt, packet, calls = reviewed_whole_norm_native_case_v1
    manifest = c["preparation"].to_dict()
    options = {key: value for key, value in reviewed_whole_norm_native_options_v1(c).items()
        if key in {"instance_identity_profile", "definition_application_profile"}}
    assert len(calls) == 1 and receipt["build_passed"] is True
    assert len(receipt["compiled_modules"]) == 10 and len(receipt["executed_project_sha256"]) == 39
    assert len(manifest["realization_obligations"]) == 15
    assert receipt["conditional_theorems"] == manifest["preservation_obligations"]
    assert len(receipt["theorem_axiom_dependencies"]) == len(receipt["conditional_theorems"]) == 30
    assert set(receipt["theorem_axiom_dependencies"]) == set(manifest["preservation_obligations"])
    assert all(value == [] for value in receipt["theorem_axiom_dependencies"].values())
    for key in ("definition_application_profile", "definition_applications", "definition_application_obligations"):
        assert receipt[key] == manifest[key]
    assert len(receipt["definition_applications"]) == 2 and len(receipt["definition_application_obligations"]) == 4
    assert receipt["constructed_model_only"] is False
    assert receipt["cross_unit_definition_application_proved"] is receipt["statutory_meaning_proved"] is False
    assert not any(receipt["authority"].values())
    assert receipt["training_mask"] == receipt["evaluation_gold_mask"] == 0
    assert native.reviewed_definition_realization_receipt_bytes_v1(receipt, **options) == dict(packet)["build-receipt.json"]
    for name, body in c["preparation"].files:
        assert dict(packet)["project/" + name] == dict(packet)["executed-inputs/" + name] == body.encode()


def test_whole_norm_native_retained_replay_has_no_live_authority_and_refuses_mode_crossing(
        reviewed_whole_norm_native_case_v1, monkeypatch):
    c, receipt, packet, calls = reviewed_whole_norm_native_case_v1
    before = deepcopy((receipt, packet, c["graph"], c["admission"]))
    reviewed_retained_no_tools_v2(monkeypatch)
    replay = reviewed_whole_norm_native_reopen_v1(c, receipt, packet)
    assert replay["retained_observations_consistent"] is replay["current_complete_semantics_replayed"] is True
    assert replay["constructed_model_only"] is False and len(replay["obligations"]) == 30
    for key in ("native_execution_authenticated", "live_native_success_authenticated", "native_execution_performed",
            "olean_kernel_rechecked", "original_success_authenticated", "release_ready"):
        assert replay.get(key, False) is False
    assert replay["definition_applications"] == receipt["definition_applications"]
    assert not any(replay["authority"].values())
    assert replay["training_mask"] == replay["evaluation_gold_mask"] == 0
    with pytest.raises(ValueError):
        reviewed_whole_norm_native_reopen_v1(c, receipt, packet, definition_application_profile=None)
    wrong_identity = "reviewed-source-use/v1" if c["whole_norm_identity_profile"] is None else None
    with pytest.raises(ValueError):
        reviewed_whole_norm_native_reopen_v1(c, receipt, packet, instance_identity_profile=wrong_identity)
    assert len(calls) == 1 and before == (receipt, packet, c["graph"], c["admission"])


@pytest.mark.parametrize("damage", ["scope-binding", "application-obligation"])
def test_whole_norm_native_resealed_witness_or_obligation_cannot_replace_current_replay(
        reviewed_whole_norm_native_case_v1, monkeypatch, damage):
    c, receipt, packet, calls = reviewed_whole_norm_native_case_v1
    changed = deepcopy(receipt)
    if damage == "scope-binding":
        row = changed["definition_applications"][0]
        row["scope_record_cid"] = row["interpretation_record_cid"]
        assert row != receipt["definition_applications"][0]
    else:
        changed["definition_application_obligations"] = list(reversed(changed["definition_application_obligations"]))
        assert changed["definition_application_obligations"] != receipt["definition_application_obligations"]
    changed = contracts.seal_record({key: value for key, value in changed.items() if key not in {"record_cid", "cid_scope"}})
    raw = canonical(changed)
    rows = dict(packet); rows["build-receipt.json"] = raw
    changed_packet = tuple(sorted(rows.items()))
    assert sha(raw) != sha(dict(packet)["build-receipt.json"])
    identity = {} if c["whole_norm_identity_profile"] is None else {"instance_identity_profile": c["whole_norm_identity_profile"]}
    application = {"definition_application_profile": "whole-norm-definition-expansion/v1"}
    assert native.reviewed_definition_realization_packet_sha256_v1(changed_packet, **identity, **application) != \
        native.reviewed_definition_realization_packet_sha256_v1(packet, **identity, **application)
    reviewed_retained_no_tools_v2(monkeypatch)
    with pytest.raises(ValueError):
        reviewed_whole_norm_native_reopen_v1(c, changed, changed_packet)
    assert len(calls) == 1


# The existing installed toolchain fixture is the only execution admission here.
# Fictional reviewed source inputs do not acquire statutory or training authority.
@pytest.mark.parametrize("instance_identity_profile,definition_body", [
    (None, "negated-body"), ("reviewed-source-use/v1", "repeated-body")],
    ids=["default", "source-use"])
def test_whole_norm_definition_application_installed_lean_checks_all30_and_original_models(
        bound_norm_installed_lake, reviewed_native_control_v3, tmp_path,
        instance_identity_profile, definition_body):
    executable, binary_pins = bound_norm_installed_lake
    c = dict(reviewed_native_control_v3)
    c = c["shared_helper"].reviewed_definition_realization_fresh_case(c, definition_body)
    identity = {} if instance_identity_profile is None else {
        "instance_identity_profile": instance_identity_profile}
    application = {"definition_application_profile": "whole-norm-definition-expansion/v1"}
    c["preservation"] = c["preparation"] if instance_identity_profile is None else \
        c["shared"].prepare_reviewed_norm_preservation_corpus_v3(c["graph"], c["admission"],
            *c["args"], expected_graph_sha256=c["graph_sha"], expected_admission_sha256=c["admission_sha"],
            toolchain=TOOLCHAIN, **identity, **c["kwargs"])
    c["preparation"] = c["shared"].prepare_reviewed_definition_realization_corpus_v1(
        c["preservation"], c["graph"], c["admission"], *c["args"],
        expected_preservation_sha256=c["shared"].reviewed_preservation_corpus_sha256(c["preservation"]),
        expected_graph_sha256=c["graph_sha"], expected_admission_sha256=c["admission_sha"],
        toolchain=TOOLCHAIN, **identity, **application, **c["kwargs"])
    options = reviewed_realization_native_arguments_v1(c) | identity | application
    manifest = c["preparation"].to_dict()
    assert manifest["selection"]["body_typed_node"]["kind"] == (
        "not" if definition_body == "negated-body" else "and")
    assert len(manifest["preservation_obligations"]) == 30
    assert len(manifest["definition_application_obligations"]) == 4
    assert len(manifest["definition_applications"]) == 2
    assert manifest["upstream_manifest"] == c["preservation"].to_dict()
    for row in manifest["definition_applications"]:
        assert row["original_typed_expression"] != row["expanded_typed_expression"]
        assert row["target_typed_paths"]
    output = tmp_path / "actual-whole-norm-definition-application"
    handle = native.build_verified_reviewed_definition_realization_native_v1(
        c["preparation"], c["preservation"], c["graph"], c["admission"], *c["args"],
        **(options | dict(lake_executable=str(executable), output_directory=output, timeout_seconds=60)))
    packet = reviewed_live_success_packet_v2(output)
    bodies = dict(packet)
    receipt = json.loads(bodies["build-receipt.json"])
    assert receipt["binary_sha256"] == binary_pins and receipt["build_passed"] is True
    expected_profile = native.REVIEWED_DEFINITION_REALIZATION_NATIVE_PROFILE + \
        ("" if instance_identity_profile is None else "+" + instance_identity_profile) + \
        "+whole-norm-definition-expansion/v1"
    assert receipt["profile"] == expected_profile
    assert receipt["definition_application_profile"] == application["definition_application_profile"]
    assert receipt["definition_applications"] == manifest["definition_applications"]
    assert receipt["definition_application_obligations"] == manifest["definition_application_obligations"]
    assert receipt["conditional_theorems"] == manifest["preservation_obligations"]
    assert sorted(receipt["compiled_modules"]) == sorted(manifest["expected_modules"])
    assert len(receipt["compiled_modules"]) == 10
    assert len(receipt["executed_project_sha256"]) == len(c["preparation"].files) == 39
    assert set(receipt["theorem_axiom_dependencies"]) == set(manifest["preservation_obligations"])
    assert len(receipt["theorem_axiom_dependencies"]) == 30
    assert all(dependencies == [] for dependencies in receipt["theorem_axiom_dependencies"].values())
    for name, body in c["preparation"].files:
        assert bodies["project/" + name] == bodies["executed-inputs/" + name] == body.encode("utf-8")
    common = options | dict(expected_receipt_sha256=sha(bodies["build-receipt.json"]),
        expected_packet_sha256=native.reviewed_definition_realization_packet_sha256_v1(packet,
            **identity, **application), expected_binary_sha256=binary_pins)
    live = native.load_verified_reviewed_definition_realization_native_v1(handle, packet,
        c["preparation"], c["preservation"], c["graph"], c["admission"], *c["args"], **common)
    retained = native.load_reviewed_definition_realization_native_v1(packet,
        c["preparation"], c["preservation"], c["graph"], c["admission"], *c["args"],
        **(common | dict(observation_profile=native._REVIEWED_REPLAY_ACTUAL)))
    assert live["live_native_success_authenticated"] is live["native_execution_authenticated"] is True
    assert retained["retained_observations_consistent"] is True
    assert retained["native_execution_authenticated"] is retained.get("live_native_success_authenticated", False) is False
    for result in (receipt, live, retained):
        assert result["constructed_model_only"] is False
        assert result["cross_unit_definition_application_proved"] is result["statutory_meaning_proved"] is False
        assert result["installed_toolchain_verified"] is False
        assert not any(result["authority"].values())
        assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    assert live["obligations"] == retained["obligations"] == manifest["preservation_obligations"]
    omitted = dict(common)
    omitted.pop("definition_application_profile")
    wrong_identity = dict(common, instance_identity_profile=(
        "reviewed-source-use/v1" if instance_identity_profile is None else None))
    for rejected in (omitted, wrong_identity):
        with pytest.raises(ValueError):
            native.load_verified_reviewed_definition_realization_native_v1(handle, packet,
                c["preparation"], c["preservation"], c["graph"], c["admission"], *c["args"], **rejected)

    if instance_identity_profile == "reviewed-source-use/v1":
        # Actual Native receipt bindings stay in this build-bearing test.
        assert receipt["reviewed_admission_sha256"] == manifest["reviewed_admission_sha256"] == c["admission_sha"]
        assert receipt["reviewed_graph_sha256"] == manifest["reviewed_graph_sha256"] == c["graph_sha"]
        assert retained["admission_sha256"] == c["admission_sha"]
        assert retained["graph_sha256"] == c["graph_sha"]
        assert receipt["declaration_sha256"] == manifest["declaration_sha256"] == c["admission"]["declaration_sha256"]
        assert receipt["statutory_meaning_proved"] is False and not any(receipt["authority"].values())
        reviewed_whole_norm_consumer_checks_v3(c)


@pytest.mark.parametrize("instance_identity_profile", [None, "reviewed-source-use/v1"], ids=["default", "source-use"])
def test_whole_norm_native_same_process_default_application_default_keeps_complete_pin_domains(
        reviewed_native_control_v3, monkeypatch, instance_identity_profile):
    # Exercise both transitions through current complete replay in one process.
    # Never clear either owner-pin latch or use an injected Native executor.
    c = dict(reviewed_native_control_v3)
    identity = {} if instance_identity_profile is None else {"instance_identity_profile": instance_identity_profile}
    c["preservation"] = c["preparation"] if instance_identity_profile is None else \
        c["shared"].prepare_reviewed_norm_preservation_corpus_v3(c["graph"], c["admission"],
            *c["args"], expected_graph_sha256=c["graph_sha"], expected_admission_sha256=c["admission_sha"],
            toolchain=TOOLCHAIN, **identity, **c["kwargs"])
    preparations = {}
    for label, application in (("legacy", {}), ("whole", {"definition_application_profile": "whole-norm-definition-expansion/v1"})):
        preparations[label] = c["shared"].prepare_reviewed_definition_realization_corpus_v1(
            c["preservation"], c["graph"], c["admission"], *c["args"],
            expected_preservation_sha256=c["shared"].reviewed_preservation_corpus_sha256(c["preservation"]),
            expected_graph_sha256=c["graph_sha"], expected_admission_sha256=c["admission_sha"],
            toolchain=TOOLCHAIN, **identity, **application, **c["kwargs"])
    reviewed_retained_no_tools_v2(monkeypatch)
    for label in ("legacy", "whole", "legacy", "whole", "legacy"):
        current = dict(c, preparation=preparations[label])
        selected = {} if label == "legacy" else {"definition_application_profile": "whole-norm-definition-expansion/v1"}
        assert reviewed_realization_native_validate_v1(current, **identity, **selected) == preparations[label]
        manifest = preparations[label].to_dict()
        assert len(manifest["preservation_obligations"]) == (26 if label == "legacy" else 30)
        producers = native._reviewed_definition_realization_native_pins(native._owners(), manifest, **identity, **selected)
        algebra = str(Path(c["shared"].__file__).resolve().parents[1] / "syntax_core" / "algebra.py")
        if label == "whole":
            assert producers[algebra] == sha(Path(algebra).read_bytes())


# Capture-only helper diagnostics reuse a fresh authenticated V3 native packet.
# Nonempty dependencies are diagnostic results and are never accepted proof.
def test_whole_norm_definition_application_installed_lean_reports_exact_helper_axiom_dependencies(
        reviewed_live_actual_packet_v3, tmp_path):
    import re

    control, handle, packet, executable, binary_pins = reviewed_live_actual_packet_v3
    before = reviewed_live_load_v3_fixture(control, handle, packet)
    assert before["live_native_success_authenticated"] is True
    packet_files = dict(packet)
    original_packet_hashes = {name: sha(body) for name, body in packet}
    receipt = json.loads(packet_files["build-receipt.json"])
    assert receipt["build_passed"] is receipt["kernel_proofs_checked"] is True
    assert receipt["binary_sha256"] == binary_pins
    assert len(receipt["compiled_modules"]) == len(receipt["artifact_files"]) == 8
    assert len(receipt["theorem_axiom_dependencies"]) == 15
    assert all(value == [] for value in receipt["theorem_axiom_dependencies"].values())
    assert native._binary_recheck(binary_pins)

    helper_names = (
        "sourceObjectDefinitionBody", "instantiateObjectDefinitionBody",
        "objectDefinitionExpansionAt", "applyObjectDefinitionExpansions",
        "restrictObjectAtoms", "instantiateMixedDefinitionBody",
        "mixedDefinitionExpansionAt", "applyMixedDefinitionExpansions",
    )
    shared_owner = Path(control["shared"].__file__)
    shared_owner_sha = sha(shared_owner.read_bytes())
    production_code = control["shared"]._reviewed_definition_application_lean_helpers(True)
    production_object_code = control["shared"]._reviewed_definition_application_lean_helpers(False)
    production_sha = sha(production_code.encode("utf-8"))
    production_object_sha = sha(production_object_code.encode("utf-8"))
    scoped_false = "set_option backward.match.sparseCases false in\n"
    scoped_true = "set_option backward.match.sparseCases true in\n"
    assert len(scoped_false.encode("utf-8")) == 47
    assert production_code.count(scoped_false) == 8
    assert production_object_code.count(scoped_false) == 4
    assert len(production_code.encode("utf-8")) == 9252
    assert production_sha == "0acbce1b53803bf160f08c8b3494af2456d3b9522391ffddd43d9832068a40c2"
    assert len(production_object_code.encode("utf-8")) == 4385
    assert production_object_sha == "3507ce36646598c32e9b803c89443fbebc32021cf47cd34d9c819d09df6ddcca"
    old_helper_body = production_code.replace(scoped_false, "")
    old_object_body = production_object_code.replace(scoped_false, "")
    old_helper_sha = sha(old_helper_body.encode("utf-8"))
    old_object_sha = sha(old_object_body.encode("utf-8"))
    assert len(old_helper_body.encode("utf-8")) == 8876
    assert old_helper_sha == "a0ade7f443547638b33dda20ce3c106acd861dfe147061a798732ee476da7065"
    assert len(old_object_body.encode("utf-8")) == 4197
    assert old_object_sha == "53127db1c4e0f998682063e587168d9e9d0fae916dbe127cdbca296aa3e7ca0d"
    assert production_code.startswith(production_object_code)
    assert not re.search(r"(?m)^set_option ", old_helper_body + old_object_body)
    assert production_code == re.sub(r"(?m)^def ", scoped_false + "def ", old_helper_body)
    assert production_object_code == re.sub(r"(?m)^def ", scoped_false + "def ", old_object_body)
    assert tuple(re.findall(r"^def ([A-Za-z0-9_]+)", old_helper_body, re.M)) == helper_names
    assert tuple(re.findall(r"^def ([A-Za-z0-9_]+)", old_object_body, re.M)) == helper_names[:4]
    # Reproduce the old body under explicit sparse=True on each declaration.
    # Both option settings are local to a definition, including its matchers.
    control_code, control_prefixes = re.subn(r"(?m)^def ", scoped_true + "def ", old_helper_body)
    assert control_prefixes == control_code.count(scoped_true) == 8
    assert control_code.replace(scoped_true, "") == old_helper_body
    assert len(control_code.encode("utf-8")) == 9244
    control_sha = sha(control_code.encode("utf-8"))
    assert control_sha == "04fcbd41c23f118f6c174cb56b29e2b79e2d77ab6bf3aef83f93e75e46380905"
    assert tuple(re.findall(r"^def ([A-Za-z0-9_]+)", production_code, re.M)) == helper_names
    assert tuple(re.findall(r"^def ([A-Za-z0-9_]+)", control_code, re.M)) == helper_names
    namespace = "LegalDefinitionApplicationHelperDiagnostics"
    production_namespace = "LegalDefinitionApplicationHelperProductionNonSparse"
    begin_marker = "__LEGAL_DEFINITION_APPLICATION_BASELINE_BODY_BEGIN__"
    end_marker = "__LEGAL_DEFINITION_APPLICATION_BASELINE_BODY_END__"
    leaf_constants = (
        "instBEqOfDecidableEq", "instDecidableEqString", "List.instBEq",
        "instDecidableEqBool", "Bool.and", "ite",
        "LegalDefinitionApplicationHelperDiagnostics.sourceObjectDefinitionBody.match_1",
    )
    leaf_markers = {name: {
        "begin": "__LEGAL_DEFINITION_APPLICATION_LEAF_" + str(index) + "_BEGIN__",
        "end": "__LEGAL_DEFINITION_APPLICATION_LEAF_" + str(index) + "_END__",
    } for index, name in enumerate(leaf_constants)}
    expected = tuple(namespace + "." + name for name in helper_names)
    production_expected = tuple(production_namespace + "." + name for name in helper_names)
    all_expected = set(expected + production_expected + leaf_constants)
    assert len(all_expected) == 23
    diagnostic_name = "DefinitionApplicationHelperAxioms.lean"
    diagnostic = (
        "import LegalRelationalAstPreservation.Semantics\n"
        "import LegalMixedRelationalAstPreservation.Semantics\n"
        "namespace " + namespace + "\n" + control_code + "\n"
        + "\n".join("#print axioms " + name for name in helper_names)
        + '\n#check "' + begin_marker + '"\n'
        + "set_option pp.all true in\n#print sourceObjectDefinitionBody\n"
        + '#check "' + end_marker + '"\n'
        + "".join('#check "' + leaf_markers[name]["begin"] + '"\n'
            + "set_option pp.all true in\n#print " + name + "\n"
            + '#check "' + leaf_markers[name]["end"] + '"\n'
            + "#print axioms " + name + "\n" for name in leaf_constants)
        + "end " + namespace + "\n"
        + "namespace " + production_namespace + "\n" + production_code + "\n"
        + "\n".join("#print axioms " + name for name in helper_names)
        + "\nend " + production_namespace + "\n"
    ).encode("utf-8")
    files = {diagnostic_name: diagnostic}
    for original_name, copied_name in receipt["artifact_files"].items():
        assert original_name.startswith(".lake/build/lib/lean/")
        assert copied_name == "compiled/" + original_name.removeprefix(".lake/build/lib/lean/")
        assert copied_name not in files and copied_name in packet_files
        body = packet_files[copied_name]
        assert type(body) is bytes and len(body) == receipt["artifact_bytes"][original_name]
        assert sha(body) == receipt["artifact_sha256"][original_name]
        files[copied_name] = body
    assert len(files) == 9 and sum(map(len, files.values())) <= 8 * 1024**2
    assert max(map(len, files.values())) <= 2 * 1024**2
    lean = executable.parent / "lean"
    assert lean.is_file() and not lean.is_symlink() and str(lean) in binary_pins
    assert sha(lean.read_bytes()) == binary_pins[str(lean)]
    command = (str(lean), diagnostic_name)
    environment = {"ELAN_TOOLCHAIN": TOOLCHAIN, "LEAN_NUM_THREADS": "1", "LEAN_PATH": "compiled"}
    request = process.ToolRunRequest(
        argv=command, input_files=files, output_paths=tuple(sorted(files)),
        environment=environment, owned_process_observation=True,
        limits=process.ToolRunLimits(
            timeout_seconds=60, cpu_seconds=60, resident_memory_bytes=1536 * 1024**2,
            max_input_bytes=8 * 1024**2, max_workspace_bytes=8 * 1024**2,
            max_output_bytes=2 * 1024**2, max_output_files=len(files)))
    run = process.BoundedToolRunner(workspace_root=tmp_path).run(request)
    output = tmp_path / "definition-application-helper-diagnostic"
    output.mkdir()
    (output / diagnostic_name).write_bytes(diagnostic)
    (output / "stdout.txt").write_bytes(run.stdout.encode("utf-8"))
    (output / "stderr.txt").write_bytes(run.stderr.encode("utf-8"))

    observations = {}
    axiom_lines = []
    parse_errors = []
    stdout_lines = run.stdout.splitlines()
    for line in stdout_lines:
        if not re.search(r"\b(?:axiom|axioms|sorry|sorryAx)\b", line):
            continue
        axiom_lines.append(line)
        match = re.search(
            r"'([A-Za-z0-9_.]+)' (does not depend on any axioms|depends on axioms: \[([^\]]*)\])$",
            line)
        if match is None or match.group(1) not in all_expected:
            parse_errors.append("unexpected axiom report: " + line)
            continue
        name = match.group(1)
        if name in observations:
            parse_errors.append("duplicate axiom report: " + name)
            continue
        if match.group(2) == "does not depend on any axioms":
            dependencies = []
        else:
            dependencies = [value.strip() for value in match.group(3).split(",")]
            if (not dependencies or not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", value)
                    for value in dependencies) or len(set(dependencies)) != len(dependencies)):
                parse_errors.append("malformed dependency inventory: " + line)
        observations[name] = dependencies
    control_reports = {name: observations[name] for name in expected if name in observations}
    production_reports = {name: observations[name] for name in production_expected if name in observations}
    leaf_reports = {name: observations[name] for name in leaf_constants if name in observations}
    leaf_bodies = {}
    leaf_body_complete = {}
    leaf_marker_observations = {}
    for name in leaf_constants:
        markers = leaf_markers[name]
        starts = [index for index, line in enumerate(stdout_lines)
            if re.search('"' + re.escape(markers["begin"]) + r'"\s*:\s*String\s*$', line)]
        ends = [index for index, line in enumerate(stdout_lines)
            if re.search('"' + re.escape(markers["end"]) + r'"\s*:\s*String\s*$', line)]
        bounded_capture = len(starts) == len(ends) == 1 and starts[0] < ends[0]
        body = "\n".join(stdout_lines[starts[0] + 1:ends[0]]) + "\n" if bounded_capture else ""
        leaf_bodies[name] = body
        leaf_body_complete[name] = bounded_capture and bool(body.strip()) and "⋯" not in body
        leaf_marker_observations[name] = {**markers, "begin_count": len(starts), "end_count": len(ends)}
    begin_lines = [index for index, line in enumerate(stdout_lines)
        if re.search('"' + re.escape(begin_marker) + r'"\s*:\s*String\s*$', line)]
    end_lines = [index for index, line in enumerate(stdout_lines)
        if re.search('"' + re.escape(end_marker) + r'"\s*:\s*String\s*$', line)]
    complete_control_capture = len(begin_lines) == len(end_lines) == 1 and begin_lines[0] < end_lines[0]
    elaborated_control_body = ("\n".join(stdout_lines[begin_lines[0] + 1:end_lines[0]]) + "\n"
        if complete_control_capture else "")
    control_expected_reports = {name: ([] if name.endswith(".restrictObjectAtoms") else ["propext"])
        for name in expected}
    observation = {
        "schema": "legal-definition-application-helper-axiom-diagnostic/v4",
        "diagnostic_only": True,
        "comparison_profile": "declaration-scoped-sparse-control-vs-production-nonsparse/v1",
        "shared_owner": {"path": str(shared_owner), "sha256": shared_owner_sha},
        "control_namespace": namespace,
        "control_sparse_cases_option": True,
        "control_option_scope": "each helper declaration only",
        "control_old_helper_body_sha256": old_helper_sha,
        "control_old_helper_body_bytes": len(old_helper_body.encode("utf-8")),
        "control_old_object_body_sha256": old_object_sha,
        "control_helper_source_sha256": control_sha,
        "control_helper_source_bytes": len(control_code.encode("utf-8")),
        "control_helper_source_utf8": control_code,
        "control_decl_scoped_option_count": control_prefixes,
        "control_helper_reports": control_reports,
        "control_expected_helper_reports": control_expected_reports,
        "control_nonempty_helper_reports": [name for name in expected if control_reports.get(name)],
        "complete_exact_control_helper_reports_captured": set(control_reports) == set(expected) and not parse_errors,
        "production_namespace": production_namespace,
        "production_sparse_cases_option": False,
        "production_option_scope": "each helper declaration only",
        "production_helper_source_sha256": production_sha,
        "production_helper_source_bytes": len(production_code.encode("utf-8")),
        "production_helper_source_utf8": production_code,
        "production_object_helper_source_sha256": production_object_sha,
        "production_object_helper_source_bytes": len(production_object_code.encode("utf-8")),
        "production_mixed_decl_scoped_option_count": production_code.count(scoped_false),
        "production_object_decl_scoped_option_count": production_object_code.count(scoped_false),
        "production_strip_options_matches_old_exact_body": True,
        "production_helper_reports": production_reports,
        "production_nonempty_helper_reports": [name for name in production_expected if production_reports.get(name)],
        "complete_exact_production_helper_reports_captured": set(production_reports) == set(production_expected) and not parse_errors,
        "production_empty_helper_axioms_observed": set(production_reports) == set(production_expected) and all(value == [] for value in production_reports.values()),
        "diagnostic_source_sha256": sha(diagnostic),
        "baseline_V3_receipt_sha256": sha(packet_files["build-receipt.json"]),
        "baseline_V3_packet_sha256": native.reviewed_norm_preservation_packet_sha256_v3(packet),
        "baseline_V3_modules": receipt["compiled_modules"],
        "baseline_V3_named_empty_axiom_reports": 15,
        "input_sha256": {name: sha(body) for name, body in sorted(files.items())},
        "executed_input_sha256": {name: sha(body) for name, body in sorted(run.output_files.items())},
        "all_input_bytes_read_back_exactly": run.output_files == files,
        "command": list(run.command), "environment": environment,
        "binary_sha256": binary_pins, "pid": run.pid, "returncode": run.returncode,
        "native_lifecycle": run.native_lifecycle.to_dict() if run.native_lifecycle is not None else None,
        "workspace_cleaned": run.workspace_cleaned,
        "whole_norm_source_exactness_qualified": False,
        "whole_norm_native_success_authenticated": False,
        "helper_diagnostics_are_accepted_proof": False,
        "statutory_meaning_proved": False, "release_ready": False,
        "authority": dict(native.AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        "observed_control_leaf_constants": list(leaf_constants),
        "control_leaf_axiom_reports": leaf_reports,
        "complete_exact_control_leaf_reports_captured": set(leaf_reports) == set(leaf_constants) and not parse_errors,
        "expected_control_report_count": 8,
        "expected_production_report_count": 8,
        "expected_control_leaf_report_count": 7,
        "expected_total_report_count": 23,
        "elaborated_control_leaf_constant_bodies": leaf_bodies,
        "elaborated_control_leaf_constant_body_sha256": {name: sha(body.encode("utf-8")) for name, body in leaf_bodies.items()},
        "elaborated_control_leaf_constant_body_complete": leaf_body_complete,
        "elaborated_control_leaf_constant_body_markers": leaf_marker_observations,
        "complete_elaborated_control_leaf_bodies_captured": all(leaf_body_complete.values()),
        "complete_exact_all_axiom_reports_captured": len(axiom_lines) == 23 and set(observations) == all_expected and not parse_errors,
        "axiom_report_parse_errors": parse_errors,
        "complete_elaborated_control_body_captured": complete_control_capture and bool(elaborated_control_body.strip()) and "⋯" not in elaborated_control_body,
        "elaborated_control_body_markers": {"begin": begin_marker, "end": end_marker,
            "begin_count": len(begin_lines), "end_count": len(end_lines)},
        "elaborated_control_sourceObjectDefinitionBody": elaborated_control_body,
        "elaborated_control_body_sha256": sha(elaborated_control_body.encode("utf-8")),
        "helper_regression_is_whole_norm_proof_or_Product_release": False,
    }
    (output / "diagnostic-observation.json").write_bytes(canonical(observation))
    assert json.loads((output / "diagnostic-observation.json").read_bytes()) == observation
    assert native._binary_recheck(binary_pins)
    assert tuple(run.command) == command and run.runtime is process.ToolRuntime.NATIVE
    assert type(run.pid) is int and run.pid > 0 and run.returncode == 0 and run.ok
    assert not (run.unavailable or run.timed_out or run.cancelled or run.resource_exhausted
                or run.workspace_limit_exceeded or run.output_truncated or run.error)
    assert run.workspace_cleaned and run.native_lifecycle is not None
    assert native._observed_process_scope(run.native_lifecycle, run.pid, process)
    assert run.output_files == files
    assert sha(shared_owner.read_bytes()) == shared_owner_sha
    assert {name: sha(body) for name, body in packet} == original_packet_hashes
    assert reviewed_live_load_v3_fixture(control, handle, packet)["live_native_success_authenticated"] is True
    assert observation["complete_exact_control_helper_reports_captured"] is True
    assert observation["complete_exact_production_helper_reports_captured"] is True
    assert observation["complete_exact_control_leaf_reports_captured"] is True
    assert observation["complete_exact_all_axiom_reports_captured"] is True
    assert observation["complete_elaborated_control_body_captured"] is True
    assert observation["complete_elaborated_control_leaf_bodies_captured"] is True
    assert not re.search(r"\b(?:axiom|axioms|sorry|sorryAx)\b", run.stderr)
    assert all(value is False for value in observation["authority"].values())
    assert control_reports == control_expected_reports
    assert observation["production_empty_helper_axioms_observed"] is True
    assert all(value == [] for value in production_reports.values())


# This is an additional fixture trust route, not a Product toolchain profile.
# The outer fixture supplies this fixed published release checksum; environment
# variables supply paths only. Local AArch64 discovery above retains its pins.
_BOUND_NORM_AMD64_RELEASE_ARCHIVE_SHA256 = "47bf4bbd78f70c2e9670598ab7124d92b6efb7330ff33e5fbb4030f6fd72e4e4"
_BOUND_NORM_AMD64_RELEASE_ROOT = "lean-4.34.1-linux"


def _bound_norm_archive_native_witness(executable, archive, *, expected_archive_sha256,
                                       _decoder=None):
    """Match fixed-release members to installed siblings without extracting.

    Only fictional tests override the internal expected digest/decoder. The
    outer fixture always passes the fixed release digest and no decoder. Version
    provenance is that authenticated release/root, not an invented ELF version
    string or a new subprocess. Later Native owner observations stay separate.
    """
    import contextlib
    import posixpath
    import stat
    import tarfile

    def need(value, message):
        if not value:
            raise ValueError("archive-backed Lean witness: " + message)

    def identity(info):
        return tuple(getattr(info, key) for key in (
            "st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink",
            "st_size", "st_mtime_ns", "st_ctime_ns"))

    def open_regular(stack, path, maximum):
        need(path.is_absolute() and path.resolve(strict=True) == path,
             "canonical absolute regular path required")
        info = path.lstat()
        need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
             and 0 < info.st_size <= maximum, "regular file byte bound")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            stream = os.fdopen(fd, "rb")
        except BaseException:
            # Construction may already have consumed/closed the descriptor.
            # Cleanup must not replace the original failure with EBADF.
            with contextlib.suppress(OSError):
                os.close(fd)
            raise
        try:
            stream = stack.enter_context(stream)
        except BaseException:
            # ExitStack registers ownership only after successful __enter__.
            with contextlib.suppress(OSError):
                stream.close()
            raise
        need(identity(os.fstat(stream.fileno())) == identity(info), "opening race")
        return stream, identity(info)

    class LimitedReader:
        def __init__(self, stream):
            self.stream = stream
            self.total = 0

        def read(self, size):
            need(type(size) is int and 0 <= size <= 1024**2, "decoder read bound")
            value = self.stream.read(size)
            need(type(value) is bytes and len(value) <= size, "decoder byte stream")
            self.total += len(value)
            need(self.total <= 4 * 1024**3, "uncompressed archive byte bound")
            return value

    try:
        executable, archive = Path(executable), Path(archive)
        need(type(expected_archive_sha256) is str
             and len(expected_archive_sha256) == 64
             and set(expected_archive_sha256) <= set("0123456789abcdef"), "digest shape")
        root = _BOUND_NORM_AMD64_RELEASE_ROOT
        need(TOOLCHAIN == "leanprover/lean4:v4.34.1", "fixed release version")
        need(executable.name == "lake" and executable.parent.name == "bin"
             and executable.parent.parent.name == "leanprover--lean4---v4.34.1"
             and executable.parent.parent.parent.name == "toolchains"
             and executable.parent.parent.parent.parent.name == ".elan",
             "fixed release sibling/version path")
        installed_paths = {"lake": executable, "lean": executable.parent / "lean"}
        need(archive not in installed_paths.values(), "archive is not an executable")
        with contextlib.ExitStack() as stack:
            source, source_identity = open_regular(stack, archive, 1024**3)
            installed = {}
            for name, path in installed_paths.items():
                stream, snapshot = open_regular(stack, path, 64 * 1024**2)
                need(path.stat().st_mode & 0o111, "installed executable mode")
                header = stream.read(64)
                need(len(header) == 64 and header[:4] == b"\x7fELF"
                     and header[4:7] == b"\x02\x01\x01"
                     and int.from_bytes(header[16:18], "little") in (2, 3)
                     and int.from_bytes(header[18:20], "little") == 62
                     and int.from_bytes(header[20:24], "little") == 1,
                     "ELF64 little-endian AMD64 version-one header required")
                stream.seek(0)
                installed[name] = (path, stream, snapshot)
            digest = hashlib.sha256()
            first = None
            remaining = source_identity[6]
            while remaining:
                piece = source.read(min(remaining, 1024**2))
                need(piece, "compressed archive truncated while hashing")
                if first is None:
                    first = piece[:4]
                digest.update(piece)
                remaining -= len(piece)
            need(source.read(1) == b"", "compressed archive grew while hashing")
            need(first == b"\x28\xb5\x2f\xfd", "zstd frame required")
            need(digest.hexdigest() == expected_archive_sha256, "compressed archive SHA256")
            need(identity(os.fstat(source.fileno())) == source_identity
                 and identity(archive.lstat()) == source_identity, "archive changed before decoding")
            source.seek(0)
            if _decoder is None:
                # Python3.12 needs this explicitly pinned CI dependency. Never
                # install it or fall back to an unowned process from a fixture.
                import zstandard
                decoder = lambda stream: zstandard.ZstdDecompressor().stream_reader(
                    stream, read_across_frames=True, closefd=False)
            else:
                decoder = _decoder
            decoded = stack.enter_context(decoder(source))
            reader = LimitedReader(decoded)
            seen, found, member_count = set(), {}, 0
            with tarfile.open(fileobj=reader, mode="r|", ignore_zeros=True) as members:
                for member in members:
                    member_count += 1
                    need(member_count <= 100000, "archive member count")
                    name = member.name
                    need(type(name) is str and "\x00" not in name
                         and len(name.encode("utf-8")) <= 4096, "member name")
                    normalized = posixpath.normpath(name)
                    need(not name.startswith("/") and name.rstrip("/") == normalized
                         and normalized != "." and (normalized == root or normalized.startswith(root + "/")),
                         "unsafe or wrong-version member path")
                    need(normalized not in seen, "duplicate archive member")
                    seen.add(normalized)
                    need(member.isfile() or member.isdir() or member.issym() or member.islnk(),
                         "unsafe special archive member")
                    if member.issym() or member.islnk():
                        link = member.linkname
                        need(type(link) is str and "\x00" not in link
                             and not link.startswith("/"), "unsafe archive link")
                        destination = posixpath.normpath(
                            posixpath.join(posixpath.dirname(normalized), link)
                            if member.issym() else link)
                        need(destination == root or destination.startswith(root + "/"),
                             "escaping archive link")
                    basename = normalized.removeprefix(root + "/bin/")
                    if normalized not in (root + "/bin/lake", root + "/bin/lean"):
                        continue
                    need(member.isfile() and 64 <= member.size <= 64 * 1024**2,
                         "binary member must be regular and bounded")
                    path, installed_stream, snapshot = installed[basename]
                    need(member.size == snapshot[6], "installed/member size differs")
                    archive_stream = members.extractfile(member)
                    need(archive_stream is not None, "binary member readback")
                    binary_digest = hashlib.sha256()
                    with archive_stream:
                        remaining = member.size
                        while remaining:
                            piece = archive_stream.read(min(remaining, 1024**2))
                            need(piece and piece == installed_stream.read(len(piece)),
                                 "installed bytes differ from authenticated member")
                            binary_digest.update(piece)
                            remaining -= len(piece)
                    need(installed_stream.read(1) == b"", "installed executable grew")
                    found[basename] = binary_digest.hexdigest()
            need(set(found) == {"lake", "lean"}, "both exact binary members required")
            for path, stream, snapshot in installed.values():
                need(identity(os.fstat(stream.fileno())) == snapshot
                     and identity(path.lstat()) == snapshot, "installed executable changed")
            need(identity(os.fstat(source.fileno())) == source_identity
                 and identity(archive.lstat()) == source_identity, "archive changed during decoding")
            return executable, {str(path): found[name] for name, path in installed_paths.items()}
    except Exception as error:
        if isinstance(error, ValueError) and str(error).startswith("archive-backed Lean witness:"):
            raise
        raise ValueError("archive-backed Lean witness: invalid or unavailable archive/decoder") from error


def _bound_norm_fictional_archive_case(tmp_path, *, entries=None):
    """Small authored tar transport; this is never an official release witness."""
    import io
    import tarfile

    root = _BOUND_NORM_AMD64_RELEASE_ROOT
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    header[16:18], header[18:20], header[20:24] = (2).to_bytes(2, "little"), (62).to_bytes(2, "little"), (1).to_bytes(4, "little")
    bodies = {"lake": bytes(header) + b"fictional lake\n", "lean": bytes(header) + b"fictional lean\n"}
    executable = tmp_path / ".elan" / "toolchains" / "leanprover--lean4---v4.34.1" / "bin" / "lake"
    executable.parent.mkdir(parents=True)
    for name, body in bodies.items():
        path = executable.parent / name
        path.write_bytes(body)
        path.chmod(0o755)
    if entries is None:
        entries = [(root + "/bin/" + name, body, "file", "") for name, body in bodies.items()]
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as output:
        for name, body, kind, link in entries:
            info = tarfile.TarInfo(name)
            info.size = len(body) if kind == "file" else 0
            if kind == "symlink":
                info.type, info.linkname = tarfile.SYMTYPE, link
            if kind == "hardlink":
                info.type, info.linkname = tarfile.LNKTYPE, link
            output.addfile(info, io.BytesIO(body) if kind == "file" else None)
    archive = tmp_path / "fictional.tar.zst"
    archive.write_bytes(b"\x28\xb5\x2f\xfd" + buffer.getvalue())
    def decode(stream):
        return io.BytesIO(stream.read()[4:])
    return executable, archive, sha(archive.read_bytes()), decode, bodies


def test_bound_norm_archive_witness_matches_both_authenticated_fictional_members(tmp_path):
    executable, archive, digest, decode, bodies = _bound_norm_fictional_archive_case(tmp_path)
    observed, pins = _bound_norm_archive_native_witness(
        executable, archive, expected_archive_sha256=digest, _decoder=decode)
    assert observed == executable
    assert pins == {str(executable.parent / name): sha(body) for name, body in bodies.items()}
    assert digest != _BOUND_NORM_AMD64_RELEASE_ARCHIVE_SHA256


@pytest.mark.parametrize("damage", ["missing-archive", "wrong-digest", "malformed-tar",
    "changed-installed", "missing-sibling", "symlink-sibling", "wrong-architecture",
    "wrong-ELF-version", "wrong-release-path", "duplicate-member", "missing-member",
    "traversal-member", "absolute-member", "wrong-release-member", "symlink-binary",
    "escaping-link", "archive-race"])
def test_bound_norm_archive_witness_refuses_fictional_attacks_before_native_execution(tmp_path, damage):
    import io
    import os
    import stat

    owned_link = None
    link_identity_fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid",
        "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")

    executable, archive, digest, decode, bodies = _bound_norm_fictional_archive_case(tmp_path)
    root = _BOUND_NORM_AMD64_RELEASE_ROOT
    if damage == "missing-archive":
        archive.unlink()
    elif damage == "wrong-digest":
        digest = "0" * 64
    elif damage == "malformed-tar":
        archive.write_bytes(b"\x28\xb5\x2f\xfdnot a tar")
        digest = sha(archive.read_bytes())
    elif damage == "changed-installed":
        executable.write_bytes(bodies["lake"][:-1] + b"!")
    elif damage == "missing-sibling":
        (executable.parent / "lean").unlink()
    elif damage == "symlink-sibling":
        sibling = executable.parent / "lean"
        alternate = tmp_path / "other-lean"
        sibling.rename(alternate)
        sibling.symlink_to(alternate)
        info = sibling.lstat()
        assert stat.S_ISLNK(info.st_mode)
        owned_link = (sibling, {key: getattr(info, key) for key in link_identity_fields},
                      os.readlink(sibling), os.fspath(alternate))
    elif damage in ("wrong-architecture", "wrong-ELF-version"):
        changed = bytearray(bodies["lake"])
        changed[18:20] = (183).to_bytes(2, "little") if damage == "wrong-architecture" else changed[18:20]
        if damage == "wrong-ELF-version":
            changed[6] = 2
        executable.write_bytes(changed)
    elif damage == "wrong-release-path":
        changed_root = executable.parent.parent.with_name("leanprover--lean4---v4.34.0")
        executable.parent.parent.rename(changed_root)
        executable = changed_root / "bin" / "lake"
    elif damage == "archive-race":
        def decode(stream):
            original = stream.read()[4:]
            archive.write_bytes(archive.read_bytes() + b"changed")
            return io.BytesIO(original)
    else:
        entries = [(root + "/bin/" + name, body, "file", "") for name, body in bodies.items()]
        if damage == "duplicate-member":
            entries.append(entries[0])
        elif damage == "missing-member":
            entries.pop()
        elif damage == "traversal-member":
            entries.append((root + "/../escaped", b"x", "file", ""))
        elif damage == "absolute-member":
            entries.append(("/escaped", b"x", "file", ""))
        elif damage == "wrong-release-member":
            entries.append(("lean-4.34.0-linux/bin/lake", b"x", "file", ""))
        elif damage == "symlink-binary":
            entries[0] = (root + "/bin/lake", b"", "symlink", "lean")
        elif damage == "escaping-link":
            entries.append((root + "/lib/escape", b"", "symlink", "../../outside"))
        # Rebuild only the small authored archive; preserve installed preimages.
        generated = tmp_path / "replacement"
        generated.mkdir()
        _, replacement, _, _, _ = _bound_norm_fictional_archive_case(generated, entries=entries)
        archive.write_bytes(replacement.read_bytes())
        digest = sha(archive.read_bytes())
    try:
        with pytest.raises(ValueError, match="archive-backed Lean witness"):
            _bound_norm_archive_native_witness(executable, archive,
                expected_archive_sha256=digest, _decoder=decode)
    finally:
        if owned_link is not None:
            link, identity, contents, expected = owned_link
            current = link.lstat()
            assert stat.S_ISLNK(current.st_mode)
            assert {key: getattr(current, key) for key in link_identity_fields} == identity
            assert os.readlink(link) == contents == expected
            link.unlink()


def test_bound_norm_archive_digest_refusal_precedes_any_decoder_call(tmp_path):
    executable, archive, _, _, _ = _bound_norm_fictional_archive_case(tmp_path)
    calls = []
    def forbidden(stream):
        calls.append(True)
        raise AssertionError("must not decode unauthenticated bytes")
    with pytest.raises(ValueError, match="compressed archive SHA256"):
        _bound_norm_archive_native_witness(executable, archive,
            expected_archive_sha256="0" * 64, _decoder=forbidden)
    assert calls == []


def test_bound_norm_archive_outer_fixture_never_accepts_environment_hash_override(tmp_path, monkeypatch):
    executable, archive, authored_digest, _, _ = _bound_norm_fictional_archive_case(tmp_path)
    monkeypatch.setenv("IPFS_DATASETS_BOUND_NORM_NATIVE_LAKE", str(executable))
    monkeypatch.setenv("IPFS_DATASETS_BOUND_NORM_NATIVE_ARCHIVE", str(archive))
    monkeypatch.setenv("IPFS_DATASETS_BOUND_NORM_NATIVE_ARCHIVE_SHA256", authored_digest)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert authored_digest != _BOUND_NORM_AMD64_RELEASE_ARCHIVE_SHA256
    # Exercise the real public fixture and verifier: env self-hash must not
    # bypass the fixed release digest, even when the decoder is unavailable.
    with pytest.raises(ValueError, match="compressed archive SHA256"):
        bound_norm_installed_lake.__wrapped__()



def test_bound_norm_archive_hash_read_is_bounded_during_fictional_growth(tmp_path, monkeypatch):
    executable, archive, digest, _, _ = _bound_norm_fictional_archive_case(tmp_path)
    initial_size, archive_inode = archive.stat().st_size, archive.stat().st_ino
    original_fdopen, requests, decoder_calls = os.fdopen, [], []

    class GrowingFile:
        def __init__(self, stream):
            self.stream = stream
            self.grown = False

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, size=-1):
            requests.append(size)
            value = self.stream.read(size)
            if not self.grown:
                self.grown = True
                with archive.open("ab") as append:
                    append.write(b"fictional concurrent growth")
            return value

    def wrapped(fd, *args, **kwargs):
        source = original_fdopen(fd, *args, **kwargs)
        return GrowingFile(source) if os.fstat(fd).st_ino == archive_inode else source

    def forbidden_decoder(source):
        decoder_calls.append(True)
        raise AssertionError("growth must refuse before decoding")

    monkeypatch.setattr(os, "fdopen", wrapped)
    with pytest.raises(ValueError, match="compressed archive grew while hashing"):
        _bound_norm_archive_native_witness(executable, archive,
            expected_archive_sha256=digest, _decoder=forbidden_decoder)
    assert requests == [initial_size, 1]
    assert decoder_calls == []



def test_bound_norm_archive_fdopen_failure_closes_owned_descriptor(tmp_path, monkeypatch):
    import errno

    executable, archive, digest, _, _ = _bound_norm_fictional_archive_case(tmp_path)
    original_open, descriptors, decoder_calls = os.open, [], []

    def tracked_open(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        descriptors.append(fd)
        return fd

    def failed_fdopen(fd, *args, **kwargs):
        raise OSError("fictional fdopen constructor failure")

    def forbidden_decoder(source):
        decoder_calls.append(True)
        raise AssertionError("constructor failure must refuse before decoder")

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "fdopen", failed_fdopen)
    with pytest.raises(ValueError, match="invalid or unavailable archive/decoder") as failure:
        _bound_norm_archive_native_witness(executable, archive,
            expected_archive_sha256=digest, _decoder=forbidden_decoder)
    assert str(failure.value.__cause__) == "fictional fdopen constructor failure"
    assert len(descriptors) == 1 and decoder_calls == []
    with pytest.raises(OSError) as closed:
        os.fstat(descriptors[0])
    assert closed.value.errno == errno.EBADF


def test_bound_norm_archive_enter_context_failure_closes_created_stream(tmp_path, monkeypatch):
    import errno

    executable, archive, digest, _, _ = _bound_norm_fictional_archive_case(tmp_path)
    original_fdopen, observations, decoder_calls = os.fdopen, [], []

    class FailedEntry:
        def __init__(self, source, fd):
            self.source, self.fd = source, fd
            self.close_calls, self.exit_calls = 0, 0

        def __enter__(self):
            raise OSError("fictional stream entry failure")

        def __exit__(self, *args):
            self.exit_calls += 1
            self.close()

        def close(self):
            self.close_calls += 1
            self.source.close()

    def failed_entry_fdopen(fd, *args, **kwargs):
        wrapper = FailedEntry(original_fdopen(fd, *args, **kwargs), fd)
        observations.append(wrapper)
        return wrapper

    def forbidden_decoder(source):
        decoder_calls.append(True)
        raise AssertionError("entry failure must refuse before decoder")

    monkeypatch.setattr(os, "fdopen", failed_entry_fdopen)
    with pytest.raises(ValueError, match="invalid or unavailable archive/decoder") as failure:
        _bound_norm_archive_native_witness(executable, archive,
            expected_archive_sha256=digest, _decoder=forbidden_decoder)
    assert str(failure.value.__cause__) == "fictional stream entry failure"
    assert len(observations) == 1 and decoder_calls == []
    observed = observations[0]
    assert observed.close_calls == 1 and observed.exit_calls == 0 and observed.source.closed
    with pytest.raises(OSError) as closed:
        os.fstat(observed.fd)
    assert closed.value.errno == errno.EBADF


def reviewed_whole_norm_consumer_case_v3(control, *, rows=None):
    """Existing consumer sidecars over this exact original signed fixture only."""
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_span_consumer_binding as fixture
    consumer = fixture.owner
    assert "training" in control["admission"]["permitted_uses"]
    assert "training" in control["case"]["declaration"]["permitted_uses"]
    assert len(control["args"]) == 4
    if rows is None:
        rows = [{"id": "reviewed:" + unit["unit_id"], "unit_id": unit["unit_id"],
            "source_text": unit["source_text"], "canonical_ir": deepcopy(unit["canonical_ir"])}
            for unit in control["admission"]["units"]]
    # Reuse only the actual split/exposure/digest sidecars.  The generic helper's
    # legacy eligibility records are neither forwarded nor treated as reviews.
    rows, sidecars = fixture.case(rows=rows, operation="training", partition="train")
    options = {name: sidecars[name] for name in ("expected_rows_sha256", "split_manifest",
        "expected_split_manifest_sha256", "exposure_records", "expected_exposure_sha256", "operation")}
    replay = dict(zip(("preparation", "registry", "policy", "reviews"), control["args"]), **control["kwargs"])
    options.update(admission_inputs=replay,
        expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(replay),
        allow_fictional_fixture=True)
    return consumer, fixture, rows, options


def reviewed_whole_norm_consumer_checks_v3(c):
    """Same-unit engineering callback checks; no Native handle or build required."""
    consumer, consumer_fixture, rows, consumer_options = reviewed_whole_norm_consumer_case_v3(c)
    units = c["admission"]["units"]
    declarations = c["case"]["declaration"]["units"]
    identifiers = [unit["unit_id"] for unit in units]
    assert len(identifiers) == len(set(identifiers)) == 3
    assert [unit["unit_id"] for unit in declarations] == identifiers
    assert [row["unit_id"] for row in rows] == identifiers
    assert c["graph"]["counts"]["units"] == len(c["graph"]["unit_records"]) == len(rows)
    assert len(c["graph"]["ast_records"]) == len(rows)
    assert [json.loads(row["ast_json"]) for row in c["graph"]["ast_records"]] == [
        row["canonical_ir"] for row in rows]
    full_fields = {"profile", "typed_expression", "argument_roles", "assumptions",
        "governing_context", "interpretation_id", "source_binding", "definition_uses", "cross_references"}
    for row, unit, declared in zip(rows, units, declarations, strict=True):
        assert set(row["canonical_ir"]) == full_fields
        assert row["source_text"] == unit["source_text"]
        assert row["canonical_ir"] == unit["canonical_ir"]
        assert row["canonical_ir"]["source_binding"]["source_version_cid"] == declared["source_version"]["record_cid"]
        assert row["canonical_ir"]["source_binding"]["occurrence_cid"] == declared["occurrence"]["record_cid"]
    replay = consumer_options["admission_inputs"]
    assert replay["preparation"] is c["args"][0]
    assert replay["preparation"] is not c["preparation"]
    replay_sha = consumer.reviewed_admission_inputs_sha256(replay)
    original_admission_sha = c["owner"].norm_content_adjudication_sha256(c["admission"])
    assert original_admission_sha == c["admission_sha"]
    assert c["admission"]["fixture_only"] is True
    assert c["admission"]["provenance_kind"] == "fictional_fixture"
    assert c["admission"]["training_mask"] == c["admission"]["evaluation_gold_mask"] == 0

    # A different admitted complete target, with fresh outer commitments,
    # cannot be attached to this unchanged unit/source and signed replay.
    wrong_rows = deepcopy(rows)
    wrong_rows[0]["canonical_ir"] = deepcopy(rows[1]["canonical_ir"])
    assert wrong_rows[0]["canonical_ir"] != rows[0]["canonical_ir"]
    _, _, wrong_rows, wrong_options = reviewed_whole_norm_consumer_case_v3(c, rows=wrong_rows)
    assert wrong_rows[0]["unit_id"] == rows[0]["unit_id"]
    assert wrong_rows[0]["source_text"] == rows[0]["source_text"]
    assert wrong_options["expected_rows_sha256"] == consumer_fixture.digest(wrong_rows)
    assert wrong_options["expected_exposure_sha256"] == consumer_fixture.digest(wrong_options["exposure_records"])
    assert wrong_options["expected_admission_inputs_sha256"] == replay_sha
    rejected_calls = []
    with pytest.raises(consumer.SourceSpanConsumerBindingError, match="complete row target differs from reviewed typed target"):
        wrong_binding = consumer.prepare_reviewed_source_span_consumer_binding_v3(wrong_rows, **wrong_options)
        consumer.consume_reviewed_source_span_binding_v3(wrong_binding, wrong_rows,
            **consumer_fixture.reviewed_validation_inputs(wrong_options), consumer=rejected_calls.append)
    assert rejected_calls == []
    assert consumer.reviewed_admission_inputs_sha256(replay) == replay_sha

    binding = consumer.prepare_reviewed_source_span_consumer_binding_v3(rows, **consumer_options)
    bound_receipt = binding.receipt()
    assert bound_receipt["schema"] == consumer.REVIEWED_V3_SCHEMA
    assert bound_receipt["profile"] == consumer.REVIEWED_V3_PROFILE
    assert bound_receipt["status"] == "ready" and bound_receipt["semantic_admission_replayed"] is True
    assert bound_receipt["row_count"] == bound_receipt["ready_row_count"] == len(units)
    assert bound_receipt["blocked_row_count"] == bound_receipt["rows_discarded"] == 0
    assert bound_receipt["declaration_sha256"] == c["admission"]["declaration_sha256"]
    assert bound_receipt["admission_inputs_sha256"] == replay_sha
    assert bound_receipt["training_mask"] == bound_receipt["evaluation_gold_mask"] == 0
    assert all(bound_receipt[key] is False for key in (
        "proof_authority", "lean_corpus_authority", "corpus_admitted", "training_executed"))
    calls, sentinel = [], object()
    def inspect_complete_same_units(detached):
        assert detached is not rows and detached == rows
        assert [row["unit_id"] for row in detached] == identifiers
        for offered, original in zip(detached, rows, strict=True):
            assert offered is not original
            assert offered["canonical_ir"] is not original["canonical_ir"]
            assert set(offered["canonical_ir"]) == full_fields
        calls.append(deepcopy(detached))
        return sentinel
    assert consumer.consume_reviewed_source_span_binding_v3(binding, rows,
        **consumer_fixture.reviewed_validation_inputs(consumer_options), consumer=inspect_complete_same_units) is sentinel
    assert calls == [rows]
    assert consumer.validate_reviewed_source_span_consumer_binding_v3(binding, rows,
        **consumer_fixture.reviewed_validation_inputs(consumer_options)) == bound_receipt == binding.receipt()
    assert consumer.reviewed_admission_inputs_sha256(replay) == replay_sha
    assert c["owner"].norm_content_adjudication_sha256(c["admission"]) == original_admission_sha


def test_whole_norm_source_use_preparation_reaches_current_consumer_without_native_execution(
        reviewed_native_control_v3):
    """Pure source-use preparation and consumer custody; no installed-Lake fixture."""
    c = dict(reviewed_native_control_v3)
    c = c["shared_helper"].reviewed_definition_realization_fresh_case(c, "repeated-body")
    identity = {"instance_identity_profile": "reviewed-source-use/v1"}
    application = {"definition_application_profile": "whole-norm-definition-expansion/v1"}
    c["preservation"] = c["shared"].prepare_reviewed_norm_preservation_corpus_v3(
        c["graph"], c["admission"], *c["args"], expected_graph_sha256=c["graph_sha"],
        expected_admission_sha256=c["admission_sha"], toolchain=TOOLCHAIN, **identity, **c["kwargs"])
    c["preparation"] = c["shared"].prepare_reviewed_definition_realization_corpus_v1(
        c["preservation"], c["graph"], c["admission"], *c["args"],
        expected_preservation_sha256=c["shared"].reviewed_preservation_corpus_sha256(c["preservation"]),
        expected_graph_sha256=c["graph_sha"], expected_admission_sha256=c["admission_sha"],
        toolchain=TOOLCHAIN, **identity, **application, **c["kwargs"])
    manifest = c["preparation"].to_dict()
    assert manifest["selection"]["body_typed_node"]["kind"] == "and"
    assert len(manifest["preservation_obligations"]) == 30
    assert len(manifest["definition_application_obligations"]) == 4
    assert len(manifest["definition_applications"]) == 2
    assert manifest["upstream_manifest"] == c["preservation"].to_dict()
    for row in manifest["definition_applications"]:
        assert row["original_typed_expression"] != row["expanded_typed_expression"]
        assert row["target_typed_paths"]
    assert manifest["preparation_only"] is True
    assert manifest["proof_status"] == manifest["lean_compilation_status"] == "not_executed"
    assert manifest["training_mask"] == manifest["evaluation_gold_mask"] == 0
    assert manifest["semantic_use_eligible"] is False and not any(manifest["authority"].values())
    reviewed_whole_norm_consumer_checks_v3(c)


# PhysicalV2 is an additive domain. These ordinary tests prepare and replay
# authored fictional data only; the opt-in installed case below is separate.
@pytest.fixture(scope="module")
def reviewed_physical_realization_native_control_v2(tmp_path_factory):
    path = Path(__file__).with_name("test_corpus_release_cli.py")
    spec = importlib.util.spec_from_file_location("_physical_realization_native_release_fixture_v2", path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    directory = tmp_path_factory.mktemp("physical-realization-native-v2")
    material = helper._direct_physical_source_material(directory / "material", reviewed_version=3)
    return helper.reviewed_physical_whole_norm_control_v2(material)


def reviewed_physical_realization_native_options_v2(c):
    return dict(c["physical_options"], expected_realization_sha256=c["realization_sha"])


def test_reviewed_physical_realization_native_replays_both_envelopes_and_same_unit_consumer(
        reviewed_physical_realization_native_control_v2):
    c = reviewed_physical_realization_native_control_v2
    options = reviewed_physical_realization_native_options_v2(c)
    checked = native.validate_reviewed_physical_definition_realization_native_v2(
        c["preparation"], c["preservation"], c["graph"], c["admission"], *c["args"], **options)
    assert checked == c["preparation"]
    manifest, upstream = checked.to_dict(), c["preservation"].to_dict()
    assert manifest["schema"] == "legal-reviewed-physical-definition-realization-preparation/v2"
    assert manifest["profile"] == "reviewed-source-use-whole-norm-definition-physical-evidence-realization/v2"
    assert manifest["upstream_manifest"] == upstream
    assert set(upstream["preservation_obligations"]) < set(manifest["preservation_obligations"])
    assert manifest["physical_context"]["physical_request_sha256"] == c["physical_request_sha256"]
    assert manifest["physical_bridge_version"] == 2
    assert manifest["training_mask"] == manifest["evaluation_gold_mask"] == 0
    assert manifest["preparation_only"] is True and manifest["lean_compilation_status"] == "not_executed"
    assert all(value is False for value in manifest["authority"].values())
    # The existing fresh wrong-target zero-callback control and exactly one
    # detached same-unit consumer run on the ORIGINAL signed replay, not Lean.
    reviewed_whole_norm_consumer_checks_v3(c)


@pytest.mark.parametrize("name,value", [("instance_identity_profile", None),
    ("definition_application_profile", None), ("instance_identity_profile", "borrowed-source-use")])
def test_reviewed_physical_realization_native_refuses_profile_downgrade_before_execution(
        reviewed_physical_realization_native_control_v2, name, value):
    c = reviewed_physical_realization_native_control_v2
    options = reviewed_physical_realization_native_options_v2(c); options[name] = value
    with pytest.raises(ValueError):
        native.validate_reviewed_physical_definition_realization_native_v2(
            c["preparation"], c["preservation"], c["graph"], c["admission"], *c["args"], **options)


def test_reviewed_physical_realization_native_refuses_complete_plain_project_in_physical_domain(
        reviewed_physical_realization_native_control_v2, reviewed_native_control_v3):
    c = reviewed_physical_realization_native_control_v2
    shared = c["shared"]
    # The old plain domain intentionally excludes physical external dependencies.
    # Build its positive baseline from the existing genuine nonphysical fixture;
    # never strip or re-sign the physical component's declaration to fit it.
    plain_control = dict(reviewed_native_control_v3)
    plain_control = plain_control["shared_helper"].reviewed_definition_realization_fresh_case(
        plain_control, "repeated-body")
    profiles = dict(instance_identity_profile="reviewed-source-use/v1",
        definition_application_profile="whole-norm-definition-expansion/v1")
    plain_control["preservation"] = shared.prepare_reviewed_norm_preservation_corpus_v3(
        plain_control["graph"], plain_control["admission"], *plain_control["args"],
        expected_graph_sha256=plain_control["graph_sha"],
        expected_admission_sha256=plain_control["admission_sha"], toolchain=TOOLCHAIN,
        instance_identity_profile=profiles["instance_identity_profile"], **plain_control["kwargs"])
    plain_control["preparation"] = shared.prepare_reviewed_definition_realization_corpus_v1(
        plain_control["preservation"], plain_control["graph"], plain_control["admission"], *plain_control["args"],
        expected_preservation_sha256=shared.reviewed_preservation_corpus_sha256(plain_control["preservation"]),
        expected_graph_sha256=plain_control["graph_sha"],
        expected_admission_sha256=plain_control["admission_sha"], toolchain=TOOLCHAIN,
        **profiles, **plain_control["kwargs"])
    plain = plain_control["preparation"]
    assert native.validate_reviewed_definition_realization_native_v1(
        plain, plain_control["preservation"], plain_control["graph"], plain_control["admission"],
        *plain_control["args"], **reviewed_realization_native_arguments_v1(plain_control), **profiles) == plain
    assert plain.to_dict()["schema"] == "legal-reviewed-definition-realization-preparation/v1"
    assert plain.to_dict()["reviewed_admission_sha256"] == plain_control["admission_sha"]
    assert plain_control["admission_sha"] != c["admission_sha"]
    # A complete, positively replayed plain project still cannot replace the
    # physical component's current source-bound whole-norm regeneration.
    options = reviewed_physical_realization_native_options_v2(c)
    options["expected_realization_sha256"] = shared.reviewed_preservation_corpus_sha256(plain)
    with pytest.raises(ValueError,
            match="realization differs from complete current source and preservation regeneration"):
        native.validate_reviewed_physical_definition_realization_native_v2(
            plain, c["preservation"], c["graph"], c["admission"], *c["args"], **options)
    assert shared.reviewed_preservation_corpus_sha256(c["preparation"]) == c["realization_sha"]


@pytest.mark.parametrize("mutation", ["physical_bytes", "physical_pin", "upstream_pin"])
def test_reviewed_physical_realization_native_refuses_crossed_original_input_pins(
        reviewed_physical_realization_native_control_v2, mutation):
    c = reviewed_physical_realization_native_control_v2
    options = reviewed_physical_realization_native_options_v2(c)
    if mutation == "physical_bytes":
        options["physical_request_raw"] += b" "
    else:
        options["expected_physical_request_sha256" if mutation == "physical_pin" else "expected_preservation_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        native.validate_reviewed_physical_definition_realization_native_v2(
            c["preparation"], c["preservation"], c["graph"], c["admission"], *c["args"], **options)


def test_reviewed_physical_realization_unissued_handle_precedes_owner_lookup(
        reviewed_physical_realization_native_control_v2, monkeypatch):
    c = reviewed_physical_realization_native_control_v2
    calls = []
    with monkeypatch.context() as patch:
        patch.setattr(native, "_owners", lambda: calls.append(True))
        with pytest.raises(ValueError, match="not issued by this process and native thread"):
            native.load_verified_reviewed_physical_definition_realization_native_v2(
                object(), (), c["preparation"], c["preservation"], c["graph"], c["admission"], *c["args"],
                expected_receipt_sha256="0" * 64, expected_packet_sha256="0" * 64,
                expected_binary_sha256={}, **reviewed_physical_realization_native_options_v2(c))
    assert calls == []


def test_reviewed_physical_retained_byte_envelope_keeps_legacy_packet_contract_separate():
    # Opaque bytes are shape-only; this test supplies no valid receipt, proof,
    # compiler observation, current review or success handle.
    block = b"x" * (8 * 1024**2)
    packet = [("compiled/one.olean", block), ("compiled/two.olean", block)]
    assert len(native._reviewed_physical_retained_packet_v2(packet)[0]) == 2
    assert native._reviewed_retained_packet(packet)[0] == dict(packet)
    legacy_only = [("compiled/legacy.olean", block + b"x")]
    assert native._reviewed_retained_packet(legacy_only)[0] == dict(legacy_only)
    with pytest.raises(ValueError, match="packet byte envelope"):
        native._reviewed_physical_retained_packet_v2(legacy_only)
    too_many = [("compiled/part" + str(i) + ".olean", block) for i in range(7)]
    with pytest.raises(ValueError, match="packet byte envelope"):
        native._reviewed_physical_retained_packet_v2(too_many)


def test_reviewed_physical_definition_realization_installed_native_uses_one_original_live_factory(
        bound_norm_installed_lake, reviewed_physical_realization_native_control_v2, tmp_path):
    # The installed fixture owns the explicit Native opt-in; ordinary selections
    # of the other tests never request/probe/build an installed toolchain.
    executable, binary_pins = bound_norm_installed_lake
    c = reviewed_physical_realization_native_control_v2
    options = reviewed_physical_realization_native_options_v2(c)
    output = tmp_path / "actual-physical-whole-norm-definition-realization"
    handle = native.build_verified_reviewed_physical_definition_realization_native_v2(
        c["preparation"], c["preservation"], c["graph"], c["admission"], *c["args"],
        **options, lake_executable=str(executable), output_directory=output, timeout_seconds=60)
    packet = reviewed_live_success_packet_v2(output)
    receipt = json.loads(dict(packet)["build-receipt.json"])
    result = native.load_verified_reviewed_physical_definition_realization_native_v2(
        handle, packet, c["preparation"], c["preservation"], c["graph"], c["admission"], *c["args"],
        **options, expected_receipt_sha256=hashlib.sha256(dict(packet)["build-receipt.json"]).hexdigest(),
        expected_packet_sha256=native.reviewed_physical_definition_realization_packet_sha256_v2(packet),
        expected_binary_sha256=binary_pins)
    assert receipt["binary_sha256"] == binary_pins
    assert result["live_native_success_authenticated"] is result["native_execution_authenticated"] is True
    assert result["original_admitted_parent_custody_authenticated"] is result["original_success_authenticated"] is False
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    assert all(value is False for value in result["authority"].values())
    assert receipt["physical_context"] == c["preparation"].to_dict()["physical_context"]
    assert len(receipt["conditional_theorems"]) == len(c["preparation"].to_dict()["preservation_obligations"])
    reviewed_whole_norm_consumer_checks_v3(c)


def test_physical_native_workspace_and_file_caps_keep_exact_declared_compiler_argv():
    """Evaluate ACTUAL production DTO expressions; never probe/launch a tool."""
    import ast
    import inspect
    import textwrap
    import sys
    if sys.platform != "linux":
        pytest.skip("Linux prlimit argv contract only; no foreign-platform qualification")
    process = native._owners()[3]
    try:
        prlimit_path = process._linux_prlimit_path()
    except process.ToolProcessError:
        pytest.skip("owner-selected Linux prlimit helper unavailable")
    argv = ("/pinned-argument-only/lake", "--offline", "--no-cache", "build", "legal")

    def production_limits(function, bindings):
        tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "process" and node.func.attr == "ToolRunLimits"]
        assert len(calls) == 1
        expression = calls[0]
        # Only the real DTO construction and its ordinary len(path-population)
        # call run; no surrounding preparer, installed-toolchain or runner code.
        assert not expression.args and all(keyword.arg is not None for keyword in expression.keywords)
        for call in (node for node in ast.walk(expression) if isinstance(node, ast.Call)):
            assert call is expression or isinstance(call.func, ast.Name) and call.func.id == "len"
        namespace = {"__builtins__": {}, "process": process, "len": len,
            "MAX_CAPTURE_BYTES": native.MAX_CAPTURE_BYTES, "MAX_PROJECT_BYTES": native.MAX_PROJECT_BYTES,
            "MAX_RECORD_BYTES": native.MAX_RECORD_BYTES, **bindings}
        return eval(compile(ast.Expression(expression), "<actual-native-limit-constructor-only>", "eval"), namespace)

    selected = production_limits(native._build_validated_native,
        {"physical_realization": True, "timeout_seconds": 60, "output_paths": ("diagnostic-only",)})
    legacy = production_limits(native._build_validated_native,
        {"physical_realization": False, "timeout_seconds": 60, "output_paths": ("diagnostic-only",)})
    expected = [prlimit_path, "--core=0:0", "--fsize=134217728:134217728", "--cpu=60:60", "--", *argv]
    assert selected.max_file_bytes == 128 * 1024**2
    assert selected.max_workspace_bytes == 256 * 1024**2
    assert legacy.max_file_bytes is None and legacy.max_workspace_bytes == 128 * 1024**2
    assert process._linux_resource_argv(argv, selected) == expected
    assert process._linux_resource_argv(argv, legacy) == expected
    for version in (3, 4, 5):
        retained = production_limits(native._validate_reviewed_native_retained_domain,
            {"reviewed_version": version, "timeout": 60, "outputs": {"diagnostic-only": b""}})
        assert retained == (selected if version == 5 else legacy)
        assert process._linux_resource_argv(argv, retained) == expected


def test_planned_physical_invocation_and_observation_keep_measurements_separate():
    from ipfs_datasets_py.logic.ir_core import protocols

    sources = {"Realization.lean": "theorem example : True := True.intro\n"}
    module = "Realization"
    theorem = module + ".example"
    context = {"proposition_utf8_sha256": hashlib.sha256(b"True").hexdigest()}
    request = protocols.BackendRequest(
        request_id="authored-invocation-contract", claim_id="authored-claim", declaration_id=theorem,
        claim_digest="1" * 64, obligation_id="authored-obligation", obligation_digest="2" * 64,
        assumption_ids=(), logic_family="lean4", query_kind=protocols.QueryKind.THEOREM_PROOF,
        requested_backend_id="legal-corpus-v4-physical-project-kernel@1",
        payload={
            "schema": "legal-corpus-v4-planned-physical-whole-norm-request/v1",
            "encoding": "lean4-physical-project-proposition-source/v1",
            "context": context, "context_sha256": "3" * 64,
            "project": {
                "target": "legal", "toolchain": TOOLCHAIN, "expected_modules": [module],
                "files": [{"path": path, "bytes": len(body.encode()),
                           "sha256": hashlib.sha256(body.encode()).hexdigest()}
                          for path, body in sources.items()],
            },
        })
    planner, snapshots = native._physical_planned_request_modules()
    for snapshot in snapshots:
        native._live_check_module_bindings(snapshot)
    with patch.object(planner, "prepare_reviewed_physical_whole_norm_kernel_request_v2",
                      lambda *args, **kwargs: (None, request)):
        with pytest.raises(ValueError, match="live success callable bindings changed: source origin"):
            native._physical_planned_request_modules()

    plan = native._physical_whole_norm_request_wire(request, request.digest)
    assert native._physical_whole_norm_request_wire(None, None) is None
    for candidate, pin in ((request, "0" * 64), (request.to_dict(), request.digest)):
        with pytest.raises(ValueError, match="exact independently pinned"):
            native._physical_whole_norm_request_wire(candidate, pin)
    invocation = process.ToolRunRequest(
        argv=("/unused/lake", "--offline", "--no-cache", "build", "legal"),
        input_files=sources, output_paths=(".lake/build/lib/lean/Realization.olean", *sources),
        environment={"ELAN_TOOLCHAIN": TOOLCHAIN})
    native._check_physical_planned_invocation(plan, invocation)
    for change in (
        {"input_files": {"Realization.lean": sources["Realization.lean"] + "\n"}},
        {"output_paths": ("Realization.lean",)},
        {"argv": invocation.argv[:-1] + ("other",)},
        {"environment": {"ELAN_TOOLCHAIN": "different"}},
    ):
        with pytest.raises(ValueError, match="differs from original native invocation"):
            native._check_physical_planned_invocation(plan, replace(invocation, **change))

    # Authored result checks the projection only. No original handle is minted.
    limits = process.ToolRunLimits(resident_memory_bytes=2 * 1024**3)
    raw = process.ToolRunResult("authored-boundary/v1", process.ToolRuntime.NATIVE, invocation.argv, 0, "", "", 1.25, {})
    empty = {"current_bytes": None, "peak_sampled_bytes": None, "cap_bytes": None}
    assert native._physical_sampled_rss(raw, process) == empty
    observation = process._tool_resource_observation(
        limits, dispatched=True, returncode=0, rss_current_bytes=2000, rss_peak_sampled_bytes=4000)
    rss = native._physical_sampled_rss(replace(raw, resource_observation=observation), process)
    assert rss == {"current_bytes": 2000, "peak_sampled_bytes": 4000, "cap_bytes": 2 * 1024**3}
    receipt = {
        "build_passed": True, "conditional_kernel_status": "checked_under_explicit_hypotheses",
        "conditional_theorems": [theorem], "theorem_axiom_dependencies": {theorem: []},
        "reviewed_execution_evidence": {
            "result": {"elapsed_seconds": 1.25},
            "output_file_refs": {"source": {"bytes": 110}, "artifact": {"bytes": 20}},
            "raw_logs": {"stdout": {"bytes": 12}},
        },
    }
    pins = {"expected_receipt_sha256": "4" * 64, "expected_packet_sha256": "5" * 64}
    projected = native._physical_planned_success_observation(plan, receipt, native._wire(rss, native.MAX_RECORD_BYTES), **pins)
    assert projected["request_sha256"] == request.digest
    assert projected["obligation_digest"] == request.obligation_digest and projected["declaration"] == theorem
    assert projected["scope"] == "original_whole_project_build"
    assert projected["original_result_observation"] == {
        "elapsed_seconds": 1.25, "output_file_bytes": 130, "raw_log_bytes": 12, "rss": rss,
        "exact_aggregate_peak_memory_bytes": None, "verified_steps": None,
    }
    assert projected["request_bounds_qualified"] is projected["proof_receipt_issued"] is False
    for changes in ({"conditional_theorems": [theorem + "_sibling"]},
                    {"theorem_axiom_dependencies": {theorem: ["authored-axiom"]}}):
        with pytest.raises(ValueError, match="original conditional theorem and axiom"):
            native._physical_planned_success_observation(plan, receipt | changes, native._wire(rss, native.MAX_RECORD_BYTES), **pins)


def test_reviewed_physical_native_binds_planned_request_to_original_live_handle(
        bound_norm_installed_lake, reviewed_physical_realization_native_control_v2, tmp_path):
    from datetime import datetime, timedelta

    from ipfs_datasets_py.logic.autoformal import (
        legal_corpus_definition_use_preservation_kernel_requests_v2 as planner,
        legal_release_coordinator_v1 as release,
    )
    from ipfs_datasets_py.logic.ir_core import protocols

    executable, binary_pins = bound_norm_installed_lake
    c = reviewed_physical_realization_native_control_v2
    options = reviewed_physical_realization_native_options_v2(c)
    inputs = (c["preparation"], c["preservation"], c["graph"], c["admission"], *c["args"])
    manifest = c["preparation"].to_dict()
    target = next(row for row in manifest["theorem_bindings"]
                  if row["binding"]["kind"] == "whole_norm_definition_expansion")
    claim, request = planner.prepare_reviewed_physical_whole_norm_kernel_request_v2(
        *inputs, expected_theorem=target["theorem"], expected_unit_id=target["binding"]["unit_id"],
        bounds=protocols.ExecutionBounds(timeout_ms=60_000, max_memory_bytes=2 * 1024**3,
            max_output_bytes=4 * 1024**2), **options)
    output = tmp_path / "original-request-bound-physical-build"
    native_arguments = dict(**options, lake_executable=str(executable), timeout_seconds=60)
    with pytest.raises(ValueError, match="exact independently pinned planned"):
        native.build_verified_reviewed_physical_definition_realization_native_v2(
            *inputs, **native_arguments, output_directory=output, planned_request=request,
            expected_planned_request_sha256="0" * 64)
    assert not output.exists()
    handle = native.build_verified_reviewed_physical_definition_realization_native_v2(
        *inputs, **native_arguments, output_directory=output, planned_request=request,
        expected_planned_request_sha256=request.digest)
    packet = reviewed_live_success_packet_v2(output)
    receipt_raw = dict(packet)["build-receipt.json"]
    receipt = json.loads(receipt_raw)
    pins = dict(expected_receipt_sha256=hashlib.sha256(receipt_raw).hexdigest(),
        expected_packet_sha256=native.reviewed_physical_definition_realization_packet_sha256_v2(packet),
        expected_binary_sha256=binary_pins)
    alternative = replace(request, request_id=request.request_id + "-other")
    for changes in ({}, {"planned_request": alternative, "expected_planned_request_sha256": alternative.digest}):
        with pytest.raises(ValueError, match="exact issued live success original inputs"):
            native.load_verified_reviewed_physical_definition_realization_native_v2(
                handle, packet, *inputs, **options, **pins, **changes)
    assert "planned_whole_norm_observation" not in receipt
    opened = native.load_verified_reviewed_physical_definition_realization_native_v2(
        handle, packet, *inputs, **options, **pins, planned_request=request,
        expected_planned_request_sha256=request.digest)
    result = opened["planned_whole_norm_observation"]
    assert opened["live_native_success_authenticated"] and opened["native_execution_authenticated"]
    assert result["request_sha256"] == request.digest and result["claim_digest"] == claim.digest
    assert result["declaration"] == target["theorem"] and result["axiom_dependencies"] == []
    assert result["premise_remains_quantified"] and result["checked_under_explicit_hypotheses"]
    assert result["retained_receipt_sha256"] == pins["expected_receipt_sha256"]
    measured = result["original_result_observation"]
    assert measured["elapsed_seconds"] == receipt["elapsed_seconds"] > 0
    assert measured["output_file_bytes"] >= sum(receipt["artifact_bytes"].values()) > 0
    assert measured["raw_log_bytes"] == sum(receipt["log_bytes"].values())
    assert measured["verified_steps"] is measured["exact_aggregate_peak_memory_bytes"] is None
    assert not result["qualified_request_execution"] and not result["proof_receipt_issued"]
    assert all(authority is False for authority in opened["authority"].values())

    historical_review = c["kwargs"]
    later = datetime.fromisoformat(historical_review["at_time_utc"]) + timedelta(seconds=1)
    current_review = {
        "registry_sha256": historical_review["expected_registry_sha256"],
        "policy_sha256": historical_review["expected_policy_sha256"],
        "at_time_utc": later.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "observed_artifact_sha256s": deepcopy(historical_review["observed_artifact_sha256s"]),
        "observed_pins": deepcopy(historical_review["observed_pins"]),
    }
    checked_native = {
        "handle": handle,
        "packet_files": packet,
        "realization": c["preparation"],
        **pins,
        "expected_realization_sha256": c["realization_sha"],
        "planned_request": request,
        "expected_planned_request_sha256": request.digest,
    }

    closed = release.validate_uscode_release_closure_v4(
        c["physical_request_raw"], expected_request_sha256=c["physical_request_sha256"],
        current_review=current_review, include_declared_eligibility=True,
        checked_native=checked_native,
    )
    checked = closed["checked_native_observation"]
    review = closed["current_review_observation"]
    assert review["at_time_utc"] == current_review["at_time_utc"]
    assert checked["live_result_cid"] == opened["record_cid"]
    assert checked["current_review_observation_cid"] == review["record_cid"]
    assert checked["planned_request_sha256"] == result["request_sha256"] == request.digest
    assert checked["physical_request_sha256"] == closed["request_sha256"] == c["physical_request_sha256"]
    assert checked["graph_sha256"] == closed["graph_sha256"] == c["graph_sha"]
    assert checked["admission_sha256"] == closed["admission_sha256"] == c["admission_sha"]
    assert checked["unit"] == request.to_dict()["payload"]["context"]["unit"]
    assert checked["declaration"] == result["declaration"] == target["theorem"]
    assert checked["checked_under_explicit_hypotheses"] is True
    assert checked["native_execution_authenticated"] is True
    assert checked["proof_receipt_issued"] is checked["qualified_request_execution"] is False
    assert contracts.seal_record({
        key: value for key, value in checked.items() if key not in {"record_cid", "cid_scope"}
    }) == checked

    evidence = closed["declared_eligibility_evidence"]
    assert evidence["checked_native_observation"] == checked
    assert evidence["current_review_observation"] == review
    assert evidence["retained_native"] is None
    assert closed["declared_qualification"]["dimensions"]["proof"]["status"] == "pending"
    assert closed["declared_eligibility"]["views"]["reviewed_graph"]["declared_eligible"] is True
    assert closed["declared_eligibility"]["views"]["checked_lean"]["declared_eligible"] is False
    assert closed["original_native_parent_custody_verified"] is False
    assert closed["admitted"] is closed["proof_verified"] is False
    assert all(closed[mask] == 0 for mask in (
        "admission_mask", "release_mask", "gold_mask", "training_mask", "evaluation_gold_mask",
    ))

    changed_review = dict(current_review, policy_sha256=hashlib.sha256(b"different policy").hexdigest())
    with pytest.raises(ValueError, match="current review trust pins differ"):
        release.validate_uscode_release_closure_v4(
            c["physical_request_raw"], expected_request_sha256=c["physical_request_sha256"],
            current_review=changed_review, include_declared_eligibility=True,
            checked_native=checked_native,
        )


def test_physical_whole_project_output_accounting_seals_exact_utf8_and_packet_bytes():
    from ipfs_datasets_py.logic.autoformal import (
        legal_corpus_definition_use_preservation_kernel_requests_v2 as planner,
    )

    proposition = "∀ (x : Nat), x = x"
    packet = {
        "Realization.lean": b"same content",
        "source-readback/Realization.lean": b"same content",
        "logs/stdout": b"pass\n",
        "build-receipt.json": b"{}",
    }
    packet_bytes = sum(map(len, packet.values()))

    def open_record(limit):
        request = {
            "payload": {
                "resource_profile": planner.PHYSICAL_WHOLE_PROJECT_RESOURCE_PROFILE,
                "proposition_source": proposition,
            },
            "bounds": {"max_output_bytes": limit},
        }
        payload = {
            "schema": "authored-physical-accounting-check/v1",
            "planned_whole_norm_observation": {
                "qualified_request_execution": False,
                "request_bounds_qualified": False,
                "backend_attempt_created": False,
                "proof_receipt_issued": False,
            },
        }
        result = native._seal_physical_whole_project_observation(payload, packet, request, contracts)
        assert contracts.validate_record(result, schema=payload["schema"],
                                         fields=("planned_whole_norm_observation",)) == result
        observation = result["planned_whole_norm_observation"]
        encoded = contracts.canonical_dag_json_bytes(result)
        assert observation["proposition_source"] == proposition and proposition.encode() in encoded
        assert all(observation[key] is False for key in (
            "qualified_request_execution", "request_bounds_qualified",
            "backend_attempt_created", "proof_receipt_issued",
        ))
        assert observation["output_accounting"] == {
            "profile": request["payload"]["resource_profile"],
            "retained_packet_member_count": len(packet),
            "retained_packet_bytes": packet_bytes,
            "canonical_live_result_bytes": len(encoded),
            "total_bytes": packet_bytes + len(encoded),
            "requested_limit_bytes": limit,
            "within_requested_limit": packet_bytes + len(encoded) <= limit,
            "full_elaborated_type_payload_available": False,
        }
        return observation["output_accounting"]

    result = open_record(4096)
    assert result["within_requested_limit"]
    exact = result["total_bytes"]
    if len(str(exact)) < len(str(result["requested_limit_bytes"])):
        exact -= len(str(result["requested_limit_bytes"])) - len(str(exact))
    result = open_record(exact)
    assert result["total_bytes"] == exact and result["within_requested_limit"]
    result = open_record(exact - 1)
    assert result["total_bytes"] > result["requested_limit_bytes"]
    assert not result["within_requested_limit"]


@pytest.mark.parametrize("use_whole_project", [False, True], ids=["legacy", "whole-project"])
def test_physical_whole_project_request_only_widens_explicit_output_annotation(
        reviewed_physical_realization_native_control_v2, use_whole_project):
    from ipfs_datasets_py.logic.autoformal import (
        legal_corpus_definition_use_preservation_kernel_requests_v2 as planner,
    )
    from ipfs_datasets_py.logic.ir_core import protocols

    c = reviewed_physical_realization_native_control_v2
    options = reviewed_physical_realization_native_options_v2(c)
    inputs = (c["preparation"], c["preservation"], c["graph"], c["admission"], *c["args"])
    target = next(row for row in c["preparation"].to_dict()["theorem_bindings"]
                  if row["binding"]["kind"] == "whole_norm_definition_expansion")

    def plan(limit, **profile):
        return planner.prepare_reviewed_physical_whole_norm_kernel_request_v2(
            *inputs, expected_theorem=target["theorem"], expected_unit_id=target["binding"]["unit_id"],
            bounds=protocols.ExecutionBounds(max_output_bytes=limit), **options, **profile)

    four_mib = 4 * 1024**2
    with pytest.raises(ValueError, match="bounded proposed execution annotations"):
        plan(four_mib + 1)
    if use_whole_project:
        profile = planner.PHYSICAL_WHOLE_PROJECT_RESOURCE_PROFILE
        with pytest.raises(ValueError, match="exact physical whole-project resource profile"):
            plan(four_mib, resource_profile="unrecognized/v1")
        with pytest.raises(ValueError, match="bounded proposed execution annotations"):
            plan(49 * 1024**2 + 1, resource_profile=profile)
        limit = 8 * 1024**2
        claim, request = plan(limit, resource_profile=profile)
    else:
        limit = four_mib
        claim, request = plan(limit)
    wire = request.to_dict()
    payload = wire["payload"]
    assert wire["bounds"]["max_output_bytes"] == limit
    assert wire["claim_digest"] == claim.digest
    assert wire["obligation_digest"] == claim.obligations[0].digest
    assert wire["declaration_id"] == target["theorem"]
    assert all(value is False for value in payload["authority"].values())
    assert payload["dispatch_qualified"] is payload["execution_profile_qualified"] is False
    assert payload["training_mask"] == payload["evaluation_gold_mask"] == 0
    binding = native._physical_whole_norm_request_wire(request, request.digest)
    assert native._parse(binding[1], native.MAX_RECORD_BYTES) == wire

    identity = {"context_sha256": payload["context_sha256"], "bounds": wire["bounds"]}
    if use_whole_project:
        assert payload["schema"] == "legal-corpus-v4-planned-physical-whole-norm-request/v2"
        assert payload["resource_profile"] == profile
        identity["resource_profile"] = profile
        output = payload["resource_policy"]["output_bytes"]
        assert output["accounting_profile"] == profile
        assert output["plan_ceiling_bytes"] == 49 * 1024**2
        assert output["per_file_or_stream_ceiling_is_an_aggregate_bound"] is False
        assert output["full_elaborated_type_payload_available"] is False
        wrong_profile = dict(payload)
        wrong_profile.pop("resource_profile")
    else:
        assert payload["schema"] == "legal-corpus-v4-planned-physical-whole-norm-request/v1"
        assert "resource_profile" not in payload
        assert payload["resource_policy"] == planner.RESOURCE_POLICY
        wrong_profile = {**payload, "resource_profile": "physical-whole-project-output/v1"}
    assert request.request_id == "planned_physical_whole_norm:" + hashlib.sha256(
        contracts.canonical_dag_json_bytes(identity)).hexdigest()
    forged = replace(request, payload=wrong_profile)
    with pytest.raises(ValueError, match="planned physical whole-norm request profile"):
        native._physical_whole_norm_request_wire(forged, forged.digest)
