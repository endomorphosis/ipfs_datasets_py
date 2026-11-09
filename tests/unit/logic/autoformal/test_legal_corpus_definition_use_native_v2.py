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
