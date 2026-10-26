"""Parent native custody controls and explicit opt-in installed Lean checks.

The original 19 controls use genuine parent input owners and synthetic compiler
observations; they establish no actual native result. Two separate opt-in cases
use installed Lean 4.34.1 on authored fictional inputs with unavailable trust and
pending review. Neither route establishes statutory meaning or human review.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as preparer
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_native_v2 as native
from ipfs_datasets_py.logic.backends import process


def helper(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    lake = helper("test_plaintext_definition_use_lake.py", "parent_native_existing_lake_fixture")
    official = helper("test_legal_corpus_definition_use_native_v2.py", "parent_native_synthetic_compiler_fixture")
    assert official.native is native and official.preparer is preparer
    return SimpleNamespace(lake=lake, official=official,
        support=lake.support.__wrapped__(),
        originals=tmp_path_factory.mktemp("parent-native-originals", numbered=False))


def family_data(fixtures, family="fol", *, directory=None):
    path = fixtures.originals / family if directory is None else directory
    path.mkdir(parents=True, exist_ok=True)
    data = fixtures.lake.make_data(fixtures.support, path, family=family)
    return data, preparer.prepare_parent_definition_use_corpus_v1(
        **fixtures.lake.arguments(data))


@pytest.fixture(scope="module")
def base(fixtures):
    return family_data(fixtures)


@pytest.fixture
def synthetic_compiler(fixtures, monkeypatch, tmp_path):
    return fixtures.official.synthetic_compiler.__wrapped__(monkeypatch, tmp_path)


def arguments(data, preparation):
    return dict(expected_preparation_sha256=native.preparation_sha256(preparation),
        expected_assessment_file_sha256=data["expected_assessment_file_sha256"],
        review_inputs=data["review_inputs"], toolchain=data["toolchain"])


def validate(data, preparation, **overrides):
    return native.validate_parent_definition_use_native_v1(preparation, data["assessment_raw"],
        **(arguments(data, preparation) | overrides))


def build(data, preparation, executable, output, **overrides):
    return native.build_parent_definition_use_native_v1(preparation, data["assessment_raw"],
        **(arguments(data, preparation) | dict(lake_executable=str(executable),
            output_directory=output, timeout_seconds=12) | overrides))


def assert_no_authority(fixtures, receipt):
    for flag in (*fixtures.official.FALSE_AUTHORITY, "governing_scope_verified",
                 "governing_edition_verified", "contributor_completeness_verified",
                 "source_region_roles_verified"):
        assert receipt[flag] is False, flag
    assert all(value is False for value in receipt["authority"].values())
    assert receipt["training_mask"] == receipt["evaluation_gold_mask"] == 0
    assert type(receipt["training_mask"]) is type(receipt["evaluation_gold_mask"]) is int


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_parent_native_path_replays_complete_preparation_and_retains_conditional_custody(
        fixtures, base, synthetic_compiler, tmp_path, monkeypatch, family):
    data, preparation = base if family == "fol" else family_data(fixtures, family)
    before, original_manifest = deepcopy(data), preparation.manifest_json
    original = preparer.validate_parent_definition_use_corpus_v1
    replays = []
    def observed(value, assessment_raw, **kwargs):
        replays.append((value.manifest_json, assessment_raw, deepcopy(kwargs["review_inputs"])))
        return original(value, assessment_raw, **kwargs)
    monkeypatch.setattr(preparer, "validate_parent_definition_use_corpus_v1", observed)
    token = process.CancellationToken()
    executable, calls = synthetic_compiler(preparation, cancellation=token)
    output = tmp_path / "synthetic-parent-project"
    receipt = build(data, preparation, executable, output, cancellation=token)
    manifest = preparation.to_dict()
    assert len(calls) == 1 and len(replays) >= 2
    assert all(row == (original_manifest, data["assessment_raw"], data["review_inputs"]) for row in replays)
    assert receipt["schema"] == native.PARENT_BUILD_SCHEMA != native.BUILD_SCHEMA
    assert receipt["profile"] == native.PARENT_PROFILE != native.PROFILE
    assert receipt["preparation_full_canonical_sha256"] == native.preparation_sha256(preparation)
    assert receipt["assessment_file_sha256"] == data["expected_assessment_file_sha256"]
    assert receipt["review_intake_binding"] == manifest["review_intake_binding"]
    assert receipt["review_intake_binding"]["original_input_commitment_sha256"] == manifest[
        "review_intake_binding"]["original_input_commitment_sha256"]
    assert all(name.startswith("LegalCorpusParent") for name in manifest["expected_modules"])
    assert "parent-input-bindings.json" in dict(preparation.files)
    assert receipt["build_passed"] is receipt["post_run_validation_passed"] is True
    assert receipt["manifest_coverage_passed"] is receipt["executed_project_readback_passed"] is True
    assert receipt["cleanup_confirmed"] is receipt["observed_process_scope_passed"] is True
    assert receipt["expected_modules"] == receipt["compiled_modules"] == manifest["expected_modules"]
    assert len(receipt["artifact_sha256"]) == 6 and len(receipt["executed_project_sha256"]) == 9
    assert receipt["theorem_axiom_dependencies"] == {name: [] for name in manifest["conditional_theorems"]}
    assert receipt["original_preparation_theorem_assumptions"] == manifest["theorem_assumptions"]
    assert receipt["review_evidence_status"] == manifest["review_evidence_status"]
    assert receipt["review_blockers"] == manifest["review_blockers"]
    assert receipt["original_preparation_build_eligible"] is False
    assert receipt["ownership_is_sampled"] is True and receipt["kernel_containment_attested"] is False
    assert manifest["review_source_binding"]["alias_record"]["assumed_not_proved"] is True
    for field in ("original_definitions", "contexts", "context_slot_ids", "binding_record", "scope_binding"):
        assert manifest["review_source_binding"][field] == data["review_inputs"]["subject"]["native_binding"][field]
    for name, text in preparation.files:
        assert (output / "project" / name).read_bytes() == text.encode("utf-8")
        assert (output / "executed-inputs" / name).read_bytes() == text.encode("utf-8")
    assert (output / "project/corpus-manifest.json").read_bytes() == original_manifest.encode("utf-8")
    assert json.loads((output / "build-receipt.json").read_bytes()) == receipt
    assert native.parent_compilation_receipt_sha256(receipt) == fixtures.official.sha(fixtures.official.canonical(receipt))
    with pytest.raises(ValueError):
        native.compilation_receipt_sha256(receipt)
    assert_no_authority(fixtures, receipt)
    assert data == before and preparation.manifest_json == original_manifest


@pytest.mark.parametrize("direction", ["parent_to_official", "official_to_parent"])
def test_fixed_native_profiles_refuse_cross_profile_before_toolchain_or_execution(
        fixtures, base, monkeypatch, tmp_path, direction):
    if direction == "parent_to_official":
        data, preparation = base
        function = native.build_definition_use_native_v2
    else:
        data, preparation = fixtures.official.original_data()
        function = native.build_parent_definition_use_native_v1
    def no_operation(*args, **kwargs):
        pytest.fail("cross-profile input reached a toolchain or execution owner")
    monkeypatch.setattr(native, "_installed_toolchain", no_operation)
    monkeypatch.setattr(process.BoundedToolRunner, "run", no_operation)
    output = tmp_path / "must-not-export"
    with pytest.raises(ValueError):
        function(preparation, data["assessment_raw"], **arguments(data, preparation),
            lake_executable=str(tmp_path / "never-executed"), output_directory=output, timeout_seconds=12)
    assert not output.exists()


def damage_original(data, damage):
    inputs = data["review_inputs"]
    if damage == "source_pin":
        inputs["use_inputs"]["donor_evidence_inputs"]["expected_candidate_pin"]["source_binding_sha256"] = "0" * 64
    elif damage == "ordered_context":
        endpoint = inputs["use_inputs"]["consumer_evidence_inputs"]
        endpoint["context_inputs"].reverse()
        endpoint["expected_context_population"].reverse()
    else:
        identity = next(iter(inputs["observed_artifact_sha256s"]))
        inputs["observed_artifact_sha256s"][identity] = "0" * 64


@pytest.mark.parametrize("damage", ["source_pin", "ordered_context", "dependency_observation"])
def test_complete_parent_inputs_refuse_before_native_dispatch(base, monkeypatch, tmp_path, damage):
    original, preparation = base
    data = deepcopy(original)
    damage_original(data, damage)
    def no_operation(*args, **kwargs):
        pytest.fail("original parent custody failure reached native dispatch")
    monkeypatch.setattr(native, "_installed_toolchain", no_operation)
    monkeypatch.setattr(process.BoundedToolRunner, "run", no_operation)
    output = tmp_path / "must-not-export"
    with pytest.raises(ValueError):
        build(data, preparation, tmp_path / "never-executed", output)
    assert not output.exists()


@pytest.mark.parametrize("damage", ["ordered_context", "dependency_observation"])
def test_complete_parent_inputs_are_replayed_after_synthetic_runner(
        fixtures, base, synthetic_compiler, tmp_path, damage):
    original, preparation = base
    data = deepcopy(original)
    executable, calls = synthetic_compiler(preparation, after=lambda: damage_original(data, damage))
    receipt = build(data, preparation, executable, tmp_path / "post-run-refusal")
    assert len(calls) == 1
    assert receipt["post_run_validation_passed"] is False
    assert receipt["build_passed"] is receipt["conditional_proofs_verified"] is False
    assert receipt["post_run_validation_error"] is not None
    assert_no_authority(fixtures, receipt)


def test_physical_parent_changed_after_synthetic_runner_invalidates_saved_custody(
        fixtures, synthetic_compiler, tmp_path):
    data, preparation = family_data(fixtures, directory=tmp_path / "originals")
    descriptor = data["review_inputs"]["use_inputs"]["donor_evidence_inputs"]["parent_inputs"][
        "replay_inputs"]["parent_text_views_inputs"]["parent_descriptor"]
    path = Path(descriptor["local_path"])
    def mutate():
        path.write_bytes(path.read_bytes() + b"\nchanged isolated native-test source")
    executable, _ = synthetic_compiler(preparation, after=mutate)
    receipt = build(data, preparation, executable, tmp_path / "physical-parent-refusal")
    assert receipt["post_run_validation_passed"] is False
    assert receipt["build_passed"] is receipt["conditional_proofs_verified"] is False
    assert_no_authority(fixtures, receipt)


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_parent_pending_and_rejected_reviews_remain_blocked_after_synthetic_build(
        fixtures, base, synthetic_compiler, tmp_path, status):
    # Copy the genuinely prepared fictional fixture. Its actual signing owner
    # creates pending/rejected assessments; no caller-positive is substituted.
    original, _ = base
    signed = deepcopy(original["signed"])
    if status == "pending":
        signed["registry"]["mode"] = signed["policy"]["mode"] = "unavailable"
        signed["registry"]["keys"] = []
        signed["reviews"] = []
        fixtures.support.signing.refresh(signed)
    else:
        signed["reviews"][0]["interpretation"]["rationale"] += " unsigned synthetic mutation"
    data = fixtures.lake.refresh_assessment(fixtures.support, signed)
    preparation = preparer.prepare_parent_definition_use_corpus_v1(
        **fixtures.lake.arguments(data))
    expected = json.loads(data["assessment_raw"])
    executable, _ = synthetic_compiler(preparation)
    receipt = build(data, preparation, executable, tmp_path / "blocked-parent-review")
    assert receipt["build_passed"] is True
    assert receipt["review_evidence_status"] == expected["evidence_assessment_status"] == status
    assert receipt["review_blockers"] == expected["blockers"] and receipt["review_blockers"]
    assert receipt["review_prerequisites_satisfied_under_selected_trust"] is False
    assert receipt["original_preparation_build_eligible"] is False
    assert_no_authority(fixtures, receipt)


def test_parent_cleanup_failure_retains_original_exception_handle_and_false_authority(
        fixtures, base, synthetic_compiler, monkeypatch, tmp_path):
    data, preparation = base
    executable, _ = synthetic_compiler(preparation)
    handle = object()
    original = process.OwnedToolCleanupError(handle, "synthetic parent cleanup remains unresolved")
    def fail(self, request, *, cancellation=None):
        assert request.owned_process_observation is True
        raise original
    monkeypatch.setattr(process.BoundedToolRunner, "run", fail)
    output = tmp_path / "retained-cleanup-refusal"
    with pytest.raises(process.OwnedToolCleanupError) as caught:
        build(data, preparation, executable, output)
    assert caught.value is original and caught.value.cleanup_handle is handle
    receipt = json.loads((output / "build-receipt.json").read_bytes())
    assert receipt["schema"] == native.PARENT_BUILD_SCHEMA
    assert receipt["profile"] == native.PARENT_PROFILE
    assert receipt["status"] == "owned_native_cleanup_unresolved"
    assert receipt["cleanup_owner_retained_on_exception"] is True
    assert receipt["cleanup_confirmed"] is receipt["build_passed"] is False
    assert receipt["conditional_proofs_verified"] is False and receipt["artifact_sha256"] == {}
    assert_no_authority(fixtures, receipt)
    for name, text in preparation.files:
        assert (output / "project" / name).read_bytes() == text.encode("utf-8")


@pytest.mark.parametrize("damage", ["missing_module"])
def test_parent_native_output_population_and_exact_executed_sources_remain_required(
        fixtures, base, synthetic_compiler, tmp_path, damage):
    data, preparation = base
    def edit(outputs, artifacts, sources):
        if damage == "missing_module":
            outputs.pop(artifacts[-1])
        elif damage == "changed_source":
            outputs[sources[-1]] = b"synthetic source substitution"
        else:
            outputs["unexpected.olean"] = b"synthetic unrequested artifact"
    executable, _ = synthetic_compiler(preparation, output_edit=edit)
    receipt = build(data, preparation, executable, tmp_path / "output-refusal")
    assert receipt["build_passed"] is receipt["conditional_proofs_verified"] is False
    if damage == "changed_source":
        assert receipt["executed_project_readback_passed"] is False
    else:
        assert receipt["manifest_coverage_passed"] is False
    assert_no_authority(fixtures, receipt)


@pytest.mark.parametrize("damage", ["missing_observation"])
def test_parent_native_requires_each_exact_empty_axiom_observation(
        fixtures, base, synthetic_compiler, tmp_path, damage):
    data, preparation = base
    lines = fixtures.official.axiom_stdout(preparation).splitlines()
    if damage == "missing_observation":
        lines.pop()
    else:
        theorem = preparation.to_dict()["conditional_theorems"][-1]
        lines[-1] = "'" + theorem + "' depends on axioms: [Classical.choice]"
    executable, _ = synthetic_compiler(preparation, stdout="\n".join(lines) + "\n")
    receipt = build(data, preparation, executable, tmp_path / "axiom-refusal")
    assert receipt["axiom_observations_passed"] is False
    assert receipt["build_passed"] is receipt["conditional_proofs_verified"] is False
    assert_no_authority(fixtures, receipt)


@pytest.mark.parametrize("damage", ["unjoined_reader"])
def test_parent_native_requires_owned_complete_lifecycle_observations(
        fixtures, base, synthetic_compiler, tmp_path, damage):
    data, preparation = base
    if damage == "unjoined_reader":
        observation = fixtures.official.lifecycle(readers_joined=1)
    else:
        observation = fixtures.official.lifecycle(leader=fixtures.official.identity(process_group_id=124))
    executable, _ = synthetic_compiler(preparation, result_changes={"native_lifecycle": observation})
    receipt = build(data, preparation, executable, tmp_path / "lifecycle-refusal")
    assert receipt["build_passed"] is receipt["conditional_proofs_verified"] is False
    assert receipt["cleanup_confirmed" if damage == "unjoined_reader" else "observed_process_scope_passed"] is False
    assert_no_authority(fixtures, receipt)


@pytest.mark.parametrize("field", ["expected_preparation_sha256", "expected_assessment_file_sha256"])
def test_parent_native_independent_pins_refuse_before_lazy_operation_dispatch(base, monkeypatch, field):
    data, preparation = base
    def no_owner():
        pytest.fail("independent pin mismatch reached lazy operation owners")
    monkeypatch.setattr(native, "_owners", no_owner)
    with pytest.raises(ValueError):
        validate(data, preparation, **{field: "0" * 64})


def test_parent_public_import_is_stdlib_only_and_does_not_dispatch():
    import subprocess
    import sys
    code = r"""
import importlib.util,sys
blocked=('ipfs_datasets_py','torch','transformers','numpy','cryptography','pyarrow','requests')
class Deny:
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==name or fullname.startswith(name+'.') for name in blocked):
            raise AssertionError('operation owner imported: '+fullname)
sys.meta_path.insert(0,Deny())
spec=importlib.util.spec_from_file_location('_parent_native_import_contract',sys.argv[1])
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)
for name in ('preparation_sha256','validate_definition_use_native_v2',
             'build_definition_use_native_v2','compilation_receipt_sha256',
             'validate_parent_definition_use_native_v1','build_parent_definition_use_native_v1',
             'parent_compilation_receipt_sha256'):
    assert callable(getattr(module,name))
assert module.PARENT_BUILD_SCHEMA != module.BUILD_SCHEMA
assert module.PARENT_PROFILE != module.PROFILE
"""
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code, native.__file__],
        capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="module")
def installed_parent_lake():
    """Require explicit admission before constructing genuine parent inputs."""
    import hashlib
    import os

    value = os.environ.get("IPFS_DATASETS_PARENT_NATIVE_LAKE")
    if not value:
        pytest.skip("set IPFS_DATASETS_PARENT_NATIVE_LAKE for admitted installed Lean checks")
    executable = Path(value)
    expected = Path("/home/barberb/.elan/toolchains/leanprover--lean4---v4.34.1/bin/lake")
    assert executable.is_absolute() and executable == executable.resolve() == expected
    pins = {
        str(executable): "f80f50cbab5322e35bcb0bf88937e22e9d908b5e4e336e83ddfc30eb1506aacf",
        str(executable.parent / "lean"): "79fb1d26fa5a39385d59fdc48a711a14b0710ca6480271acce99b4d177cea085",
    }
    for name, digest in pins.items():
        path = Path(name)
        assert path.is_file() and not path.is_symlink()
        raw = path.read_bytes()
        assert raw.startswith(b"\x7fELF") and hashlib.sha256(raw).hexdigest() == digest
    return executable, pins


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_parent_native_installed_lean_preserves_pending_custody(
        installed_parent_lake, request, tmp_path, family):
    """One actual build and its two owner-run version probes per family."""
    import hashlib

    # Dynamic fixture lookup is deliberately after the opt-in prerequisite.
    # An ordinary suite skips both cases before expensive parent construction.
    fixtures = request.getfixturevalue("fixtures")
    executable, binary_pins = installed_parent_lake
    parent = fixtures.lake._PARENT
    signing = fixtures.support.signing
    review = parent.owner
    signatures = signing.signatures
    originals = tmp_path / "originals"
    originals.mkdir()
    component = parent.component(fixtures.support, originals, family=family)
    materialized = parent.materialize(component)
    registry = {
        "schema": signatures.REGISTRY_SCHEMA, "mode": "unavailable",
        "process_id": "fixture:parent-native-review-process", "generation": 1,
        "revocation_generation": 1, "valid_from_utc": signing.START,
        "valid_until_utc": signing.END, "keys": [], "revoked_principals": [],
    }
    policy = {
        "schema": signatures.POLICY_SCHEMA, "mode": "unavailable",
        "policy_id": "fixture:parent-native-review-policy", "process_id": registry["process_id"],
        "registry_sha256": signatures.digest(registry), "action": review.PARENT_ACTION,
        "audience": review.PARENT_AUDIENCE, "required_roles": list(signatures.ROLES),
        "valid_from_utc": signing.START, "valid_until_utc": signing.END,
        "max_review_age_seconds": 86400,
    }
    pending = dict(materialized, registry=registry, policy=policy, reviews=[], evidence={},
                   **signing.observations(materialized["manifest"]))
    data = fixtures.lake.refresh_assessment(fixtures.support, pending)
    assert data["toolchain"] == "leanprover/lean4:v4.34.1"
    assert data["assessment"]["evidence_assessment_status"] == "pending"
    assert data["assessment"]["review_prerequisites_satisfied_under_selected_trust"] is False
    assert data["assessment"]["blockers"]
    assert data["review_inputs"]["registry"]["keys"] == data["review_inputs"]["reviews"] == []
    assert data["review_inputs"]["evidence_artifacts"] == {}
    assert data["review_inputs"]["registry"]["mode"] == data["review_inputs"]["policy"]["mode"] == "unavailable"
    preparation = preparer.prepare_parent_definition_use_corpus_v1(**fixtures.lake.arguments(data))
    manifest = preparation.to_dict()
    original_data, original_preparation = deepcopy(data), deepcopy(preparation)
    source_bytes = {}
    for role in ("donor", "consumer"):
        endpoint = data["review_inputs"]["use_inputs"][role + "_evidence_inputs"]
        descriptor = endpoint["parent_inputs"]["replay_inputs"]["parent_text_views_inputs"]["parent_descriptor"]
        path = Path(descriptor["local_path"])
        assert path.is_relative_to(originals) and not path.is_symlink()
        source_bytes[path] = path.read_bytes()
    assert source_bytes and all(source_bytes.values())
    (tmp_path / "original-assessment.json").write_bytes(data["assessment_raw"])
    (tmp_path / "original-preparation-manifest.json").write_text(preparation.manifest_json, encoding="utf-8")
    output = tmp_path / "installed-parent-project"
    receipt = native.build_parent_definition_use_native_v1(
        preparation, data["assessment_raw"],
        **arguments(data, preparation), lake_executable=str(executable),
        output_directory=output, timeout_seconds=60)
    assert receipt["schema"] == native.PARENT_BUILD_SCHEMA
    assert receipt["profile"] == native.PARENT_PROFILE
    assert receipt["status"] == "conditional_native_checks_passed"
    for field in ("build_passed", "native_runtime_verified", "post_run_validation_passed",
                  "manifest_coverage_passed", "executed_project_readback_passed",
                  "original_preparation_unchanged", "binaries_unchanged",
                  "cleanup_confirmed", "observed_process_scope_passed", "workspace_cleaned",
                  "axiom_observations_passed", "conditional_proofs_verified"):
        assert receipt[field] is True, field
    for field in ("timed_out", "cancelled", "unavailable", "output_truncated",
                  "workspace_limit_exceeded", "resource_exhausted", "alias_assumption_proved",
                  "source_to_model_equivalence_proved"):
        assert receipt[field] is False, field
    assert receipt["runtime"] == "native" and receipt["returncode"] == 0
    assert type(receipt["pid"]) is int and receipt["pid"] > 0
    assert receipt["binary_sha256"] == binary_pins
    assert set(receipt["version_probes"]) == {"lake", "lean"}
    for name, probe in receipt["version_probes"].items():
        assert probe["command"] == [str(executable.parent / name), "--version"]
        assert probe["returncode"] == 0 and "4.34.1" in probe["stdout"]
    assert receipt["expected_command"] == receipt["command"] == [str(executable), "--offline", "--no-cache", "build", "legal"]
    assert receipt["expected_modules"] == receipt["compiled_modules"] == manifest["expected_modules"]
    assert len(receipt["compiled_modules"]) == len(receipt["artifact_sha256"]) == 6
    assert len(receipt["executed_project_sha256"]) == 9
    assert len(receipt["conditional_theorems"]) == 3
    assert receipt["theorem_axiom_dependencies"] == {name: [] for name in manifest["conditional_theorems"]}
    assert receipt["axiom_observation_errors"] == []
    assert receipt["conditional_kernel_status"] == "checked_under_explicit_hypotheses"
    assert receipt["review_evidence_status"] == manifest["review_evidence_status"] == "pending"
    assert receipt["review_blockers"] == manifest["review_blockers"] == data["assessment"]["blockers"]
    assert receipt["review_prerequisites_satisfied_under_selected_trust"] is False
    assert receipt["original_preparation_build_eligible"] is manifest["build_eligible"] is False
    assert receipt["review_intake_binding"] == manifest["review_intake_binding"]
    assert receipt["preparation_full_canonical_sha256"] == native.preparation_sha256(preparation)
    assert receipt["original_preparation_theorem_assumptions"] == manifest["theorem_assumptions"]
    assert receipt["original_preparation_execution_handoff"] == manifest["execution_handoff"]
    assert receipt["ownership_is_sampled"] is True and receipt["kernel_containment_attested"] is False
    lifecycle = receipt["native_lifecycle"]
    assert lifecycle["cleanup_confirmed"] is lifecycle["leader_reaped"] is True
    assert lifecycle["descendant_tracking_complete"] is lifecycle["group_scan_complete"] is True
    assert lifecycle["remaining_group_members"] == lifecycle["remaining_tracked_descendants"] == []
    assert lifecycle["observation_errors"] == [] and lifecycle["workspace"]["removed"] is True
    assert lifecycle["readers"]["started"] == lifecycle["readers"]["joined"] == 2
    assert lifecycle["stdin_writer"]["started"] == lifecycle["stdin_writer"]["joined"]
    assert receipt["post_run_validation_error"] is receipt["binary_recheck_error"] is None
    assert_no_authority(fixtures, receipt)
    execution_flags = {"backend_executed", "lean_compilation_verified", "proof_checked",
                       "kernel_proofs_checked", "conditional_proofs_verified"}
    for field in native.PARENT_FALSE_FLAGS:
        if field not in execution_flags:
            assert receipt[field] is False, field
    assert receipt["theorem_assumptions"] == [
        text for text in manifest["theorem_assumptions"]
        if text != "Modular joint equivalence is a generated definitional obligation; native kernel checking has not run."]
    assert manifest["review_source_binding"]["alias_record"]["assumed_not_proved"] is True
    assert preparation == original_preparation and data == original_data
    assert all(path.read_bytes() == raw for path, raw in source_bytes.items())
    assert json.loads((output / "build-receipt.json").read_bytes()) == receipt
    for name, text in preparation.files:
        raw = text.encode("utf-8")
        assert (output / "project" / name).read_bytes() == (output / "executed-inputs" / name).read_bytes() == raw
        assert receipt["executed_project_sha256"][name] == hashlib.sha256(raw).hexdigest()
    for name, relative in receipt["artifact_files"].items():
        raw = (output / relative).read_bytes()
        assert raw and len(raw) == receipt["artifact_bytes"][name]
        assert hashlib.sha256(raw).hexdigest() == receipt["artifact_sha256"][name]
    expected_files = ({"project/" + name for name, _ in preparation.files}
        | {"project/corpus-manifest.json"} | set(receipt["artifact_files"].values())
        | {"executed-inputs/" + name for name, _ in preparation.files}
        | {"stdout.txt", "stderr.txt", "runner-error.txt", "build-receipt.json"})
    actual_files = set()
    for path in output.rglob("*"):
        assert not path.is_symlink()
        if path.is_file():
            actual_files.add(path.relative_to(output).as_posix())
    assert actual_files == expected_files and len(actual_files) == 29


# Aggregate parent-sharing controls reuse the complete genuine parent fixtures.
# Synthetic compiler observations below exercise adapter custody only. The two
# explicit installed-Lean cases remain separate native qualifications.
@pytest.fixture(scope="module")
def shared_native_support():
    shared_fixture = helper("test_legal_corpus_shared_lake.py", "aggregate_parent_shared_source_fixture")
    official = helper("test_legal_corpus_definition_use_native_v2.py", "aggregate_parent_native_compiler_fixture")
    assert official.native is native
    return SimpleNamespace(shared_fixture=shared_fixture, shared=shared_fixture.shared, official=official)


def shared_native_example(support, path, family="fol", *, pending=False):
    path.mkdir(parents=True, exist_ok=True)
    example = support.shared_fixture.parent_shared_family_examples(path, family)
    if pending:
        for ordinal, case in enumerate(example["cases"]):
            signed = case["signed"]
            signed["registry"]["mode"] = signed["policy"]["mode"] = "unavailable"
            signed["registry"]["keys"] = []
            signed["reviews"] = []
            signed["evidence"] = {}
            example["support"].signing.refresh(signed)
            example["cases"][ordinal] = example["lake"].refresh_assessment(example["support"], signed)
    example["arguments"] = support.shared_fixture.parent_shared_arguments(example["cases"])
    example["preparation"] = support.shared.prepare_parent_shared_definition_use_corpus_v1(**example["arguments"])
    return example


@pytest.fixture(scope="module")
def shared_native_fol(shared_native_support, tmp_path_factory):
    # Lazily construct FOL once; ordinary FOL-only cohorts do not build TDFOL.
    return shared_native_example(shared_native_support,
        tmp_path_factory.mktemp("aggregate-parent-native-fol", numbered=False))


@pytest.fixture
def shared_synthetic_compiler(shared_native_support, monkeypatch, tmp_path):
    return shared_native_support.official.synthetic_compiler.__wrapped__(monkeypatch, tmp_path)


def shared_theorems(preparation):
    return list(dict.fromkeys(theorem for row in preparation.to_dict()["components"]
                             for theorem in row["conditional_theorems"]))


def shared_axiom_stdout(preparation, *, theorems=None):
    values = shared_theorems(preparation) if theorems is None else theorems
    return "\n".join("'" + name + "' does not depend on any axioms" for name in values) + "\n"


def shared_native_arguments(example, preparation=None):
    offered = example["preparation"] if preparation is None else preparation
    return dict(example["arguments"],
        expected_preparation_sha256=native.parent_shared_preparation_sha256(offered))


def build_shared_native(example, executable, output, **overrides):
    return native.build_parent_shared_definition_use_native_v1(example["preparation"],
        **(shared_native_arguments(example) | dict(lake_executable=str(executable),
            output_directory=output, timeout_seconds=12) | overrides))


def assert_shared_no_authority(support, receipt):
    for flag in (*support.official.FALSE_AUTHORITY, "governing_scope_verified",
                 "governing_edition_verified", "contributor_completeness_verified",
                 "source_region_roles_verified"):
        assert receipt[flag] is False, flag
    assert all(value is False for value in receipt["authority"].values())
    assert receipt["training_mask"] == receipt["evaluation_gold_mask"] == 0
    assert type(receipt["training_mask"]) is type(receipt["evaluation_gold_mask"]) is int


def assert_shared_native_success(support, example, receipt, output, *, modules, inputs, theorems):
    preparation = example["preparation"]
    manifest = preparation.to_dict()
    assert receipt["schema"] == native.PARENT_SHARED_BUILD_SCHEMA != native.PARENT_BUILD_SCHEMA
    assert receipt["profile"] == native.PARENT_SHARED_PROFILE != native.PARENT_PROFILE
    for flag in ("build_passed", "native_runtime_verified", "post_run_validation_passed",
                 "manifest_coverage_passed", "executed_project_readback_passed",
                 "cleanup_confirmed", "observed_process_scope_passed",
                 "original_preparation_unchanged", "binaries_unchanged",
                 "axiom_observations_passed", "conditional_proofs_verified"):
        assert receipt[flag] is True, flag
    assert receipt["preparation_full_canonical_sha256"] == native.parent_shared_preparation_sha256(preparation)
    assert receipt["expected_modules"] == receipt["compiled_modules"] == manifest["expected_modules"]
    assert len(receipt["artifact_sha256"]) == len(receipt["expected_modules"]) == modules
    assert len(receipt["executed_project_sha256"]) == len(preparation.files) == inputs
    assert receipt["population"] == manifest["population"] == example["arguments"]["expected_population"]
    assert receipt["components"] == manifest["components"]
    assert receipt["input_commitment_sha256"] == manifest["input_commitment_sha256"]
    assert receipt["conditional_theorems"] == shared_theorems(preparation)
    assert len(receipt["conditional_theorems"]) == theorems
    assert receipt["theorem_axiom_dependencies"] == {name: [] for name in shared_theorems(preparation)}
    assert receipt["theorem_contributors"] == [
        {"ordinal": row["ordinal"], "component_cid": row["component_cid"],
         "conditional_theorems": row["conditional_theorems"]}
        for row in manifest["components"]]
    assert receipt["original_preparation_theorem_assumptions"] == manifest["theorem_assumptions"]
    assert "assessment_file_sha256" not in receipt and "review_intake_binding" not in receipt
    assert "review_evidence_status" not in receipt
    assert receipt["ownership_is_sampled"] is True and receipt["kernel_containment_attested"] is False
    assert receipt["alias_assumption_proved"] is receipt["source_to_model_equivalence_proved"] is False
    assert_shared_no_authority(support, receipt)
    assert native.parent_shared_compilation_receipt_sha256(receipt) == support.official.sha(
        support.official.canonical(receipt))
    with pytest.raises(ValueError):
        native.parent_compilation_receipt_sha256(receipt)
    with pytest.raises(ValueError):
        native.compilation_receipt_sha256(receipt)
    for name, text in preparation.files:
        raw = text.encode("utf-8")
        assert (output / "project" / name).read_bytes() == raw
        assert (output / "executed-inputs" / name).read_bytes() == raw
        assert receipt["executed_project_sha256"][name] == support.official.sha(raw)
    assert (output / "project/corpus-manifest.json").read_bytes() == preparation.manifest_json.encode()
    assert json.loads((output / "build-receipt.json").read_bytes()) == receipt


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_parent_shared_native_simulated_observation_preserves_every_child_and_unique_obligation(
        shared_native_support, request, shared_synthetic_compiler,
        tmp_path, family):
    example = request.getfixturevalue("shared_native_fol") if family == "fol" else shared_native_example(
        shared_native_support, tmp_path / "tdfol-originals", family)
    original_inputs = deepcopy(example["arguments"])
    original_preparation = deepcopy(example["preparation"])
    token = process.CancellationToken()
    executable, calls = shared_synthetic_compiler(example["preparation"],
        cancellation=token, stdout=shared_axiom_stdout(example["preparation"]))
    output = tmp_path / "synthetic-shared-parent-project"
    receipt = build_shared_native(example, executable, output, cancellation=token)
    assert len(calls) == 1 and calls[0].limits.max_output_files == 24
    assert_shared_native_success(shared_native_support, example, receipt, output,
                                 modules=9, inputs=15, theorems=6)
    assert example["arguments"] == original_inputs
    assert example["preparation"] == original_preparation


def test_parent_shared_native_missing_nonfirst_joint_artifact_refuses_complete_population(
        shared_native_fol, shared_synthetic_compiler, shared_native_support, tmp_path):
    preparation = shared_native_fol["preparation"]
    second = preparation.to_dict()["components"][1]["joint_module"]
    omitted = ".lake/build/lib/lean/" + second.replace(".", "/") + ".olean"

    def edit(outputs, artifacts, sources):
        assert omitted in artifacts
        outputs.pop(omitted)

    executable, _ = shared_synthetic_compiler(preparation, output_edit=edit,
        stdout=shared_axiom_stdout(preparation))
    receipt = build_shared_native(shared_native_fol, executable, tmp_path / "missing-second-joint")
    assert receipt["manifest_coverage_passed"] is False
    assert receipt["build_passed"] is receipt["conditional_proofs_verified"] is False
    assert receipt["components"] == preparation.to_dict()["components"]
    assert_shared_no_authority(shared_native_support, receipt)


def test_parent_shared_native_changed_second_binding_readback_is_not_compilation_success(
        shared_native_fol, shared_synthetic_compiler, shared_native_support, tmp_path):
    preparation = shared_native_fol["preparation"]
    binding = preparation.to_dict()["components"][1]["input_bindings_file"]

    def edit(outputs, artifacts, sources):
        assert binding in sources
        outputs[binding] += b"\nchanged second component binding"

    executable, _ = shared_synthetic_compiler(preparation, output_edit=edit,
        stdout=shared_axiom_stdout(preparation))
    receipt = build_shared_native(shared_native_fol, executable, tmp_path / "changed-second-binding")
    assert receipt["executed_project_readback_passed"] is False
    assert receipt["build_passed"] is receipt["conditional_proofs_verified"] is False
    assert_shared_no_authority(shared_native_support, receipt)


def test_parent_shared_native_requires_second_component_unique_theorem_observation(
        shared_native_fol, shared_synthetic_compiler, shared_native_support, tmp_path):
    preparation = shared_native_fol["preparation"]
    theorems = shared_theorems(preparation)
    assert len(theorems) == 6
    executable, _ = shared_synthetic_compiler(preparation,
        stdout=shared_axiom_stdout(preparation, theorems=theorems[:-1]))
    receipt = build_shared_native(shared_native_fol, executable, tmp_path / "missing-second-theorem")
    assert receipt["axiom_observations_passed"] is False
    assert receipt["build_passed"] is receipt["conditional_proofs_verified"] is False
    assert theorems[-1] not in receipt["theorem_axiom_dependencies"]
    assert_shared_no_authority(shared_native_support, receipt)


def test_parent_shared_native_postrun_physical_change_refuses_original_custody(
        shared_native_support, shared_synthetic_compiler, tmp_path):
    example = shared_native_example(shared_native_support, tmp_path / "isolated-originals")
    item = example["arguments"]["component_inputs"][1]
    descriptor = item["review_inputs"]["use_inputs"]["consumer_evidence_inputs"]["parent_inputs"][
        "replay_inputs"]["parent_text_views_inputs"]["parent_descriptor"]
    path = Path(descriptor["local_path"])

    def mutate():
        path.write_bytes(path.read_bytes() + b"\nchanged isolated aggregate physical source")

    executable, _ = shared_synthetic_compiler(example["preparation"], after=mutate,
        stdout=shared_axiom_stdout(example["preparation"]))
    receipt = build_shared_native(example, executable, tmp_path / "physical-source-refusal")
    assert receipt["post_run_validation_passed"] is False
    assert receipt["post_run_validation_error"] is not None
    assert receipt["build_passed"] is receipt["conditional_proofs_verified"] is False
    assert_shared_no_authority(shared_native_support, receipt)


def test_parent_shared_native_cleanup_failure_keeps_original_exception_and_owner(
        shared_native_fol, shared_synthetic_compiler, shared_native_support, monkeypatch, tmp_path):
    preparation = shared_native_fol["preparation"]
    executable, _ = shared_synthetic_compiler(preparation, stdout=shared_axiom_stdout(preparation))
    handle = object()
    original = process.OwnedToolCleanupError(handle, "synthetic aggregate cleanup unresolved")

    def fail(self, request, *, cancellation=None):
        assert request.owned_process_observation is True
        raise original

    monkeypatch.setattr(process.BoundedToolRunner, "run", fail)
    output = tmp_path / "unresolved-aggregate-owner"
    with pytest.raises(process.OwnedToolCleanupError) as caught:
        build_shared_native(shared_native_fol, executable, output)
    assert caught.value is original and caught.value.cleanup_handle is handle
    receipt = json.loads((output / "build-receipt.json").read_bytes())
    assert receipt["schema"] == native.PARENT_SHARED_BUILD_SCHEMA
    assert receipt["profile"] == native.PARENT_SHARED_PROFILE
    assert receipt["status"] == "owned_native_cleanup_unresolved"
    assert receipt["cleanup_owner_retained_on_exception"] is True
    assert receipt["cleanup_confirmed"] is receipt["build_passed"] is False
    assert receipt["conditional_proofs_verified"] is False and receipt["artifact_sha256"] == {}
    assert_shared_no_authority(shared_native_support, receipt)
    for name, text in preparation.files:
        assert (output / "project" / name).read_bytes() == text.encode()


def test_parent_shared_native_single_parent_and_aggregate_profiles_refuse_before_dispatch(
        shared_native_fol, shared_native_support, monkeypatch, tmp_path):
    case = shared_native_fol["cases"][0]
    single = preparer.prepare_parent_definition_use_corpus_v1(
        **shared_native_fol["lake"].arguments(case))

    def forbidden(*args, **kwargs):
        raise AssertionError("cross-profile request reached native operation owners")

    monkeypatch.setattr(native, "_installed_toolchain", forbidden)
    monkeypatch.setattr(process.BoundedToolRunner, "run", forbidden)
    with pytest.raises(ValueError):
        native.build_parent_shared_definition_use_native_v1(single,
            **(shared_native_fol["arguments"] | {
                "expected_preparation_sha256": native.preparation_sha256(single),
                "lake_executable": str(tmp_path / "never-executed"),
                "output_directory": tmp_path / "single-as-aggregate", "timeout_seconds": 12}))
    with pytest.raises(ValueError):
        native.build_parent_definition_use_native_v1(shared_native_fol["preparation"], case["assessment_raw"],
            expected_preparation_sha256=native.parent_shared_preparation_sha256(shared_native_fol["preparation"]),
            expected_assessment_file_sha256=case["expected_assessment_file_sha256"],
            review_inputs=case["review_inputs"], toolchain=case["toolchain"],
            lake_executable=str(tmp_path / "never-executed"),
            output_directory=tmp_path / "aggregate-as-single", timeout_seconds=12)
    assert not (tmp_path / "single-as-aggregate").exists()
    assert not (tmp_path / "aggregate-as-single").exists()


def test_parent_shared_native_repeated_component_retains_two_contributors_and_unique_proofs(
        shared_native_fol, shared_native_support, shared_synthetic_compiler, tmp_path):
    example = dict(shared_native_fol)
    example["cases"] = [deepcopy(shared_native_fol["cases"][0]) for _ in range(2)]
    example["arguments"] = shared_native_support.shared_fixture.parent_shared_arguments(example["cases"])
    example["preparation"] = shared_native_support.shared.prepare_parent_shared_definition_use_corpus_v1(
        **example["arguments"])
    executable, calls = shared_synthetic_compiler(example["preparation"],
        stdout=shared_axiom_stdout(example["preparation"]))
    output = tmp_path / "repeated-component"
    receipt = build_shared_native(example, executable, output)
    assert len(calls) == 1 and calls[0].limits.max_output_files == 18
    assert_shared_native_success(shared_native_support, example, receipt, output,
                                 modules=6, inputs=12, theorems=3)
    assert len(receipt["components"]) == len(receipt["theorem_contributors"]) == 2
    assert receipt["theorem_contributors"][0]["ordinal"] == 0
    assert receipt["theorem_contributors"][1]["ordinal"] == 1
    assert receipt["theorem_contributors"][0]["component_cid"] == receipt["theorem_contributors"][1]["component_cid"]


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_parent_shared_native_installed_lean_retains_all_pending_children(
        installed_parent_lake, request, tmp_path, family):
    # The binary opt-in happens before any costly genuine parent construction.
    support = request.getfixturevalue("shared_native_support")
    executable, binary_pins = installed_parent_lake
    originals = tmp_path / "originals"
    example = shared_native_example(support, originals, family, pending=True)
    preparation = example["preparation"]
    before_inputs, before_preparation = deepcopy(example["arguments"]), deepcopy(preparation)
    source_bytes = {}
    for item in example["arguments"]["component_inputs"]:
        for role in ("donor", "consumer"):
            endpoint = item["review_inputs"]["use_inputs"][role + "_evidence_inputs"]
            descriptor = endpoint["parent_inputs"]["replay_inputs"]["parent_text_views_inputs"]["parent_descriptor"]
            path = Path(descriptor["local_path"])
            assert path.is_relative_to(originals) and not path.is_symlink()
            source_bytes[path] = path.read_bytes()
        assert item["review_inputs"]["registry"]["mode"] == item["review_inputs"]["policy"]["mode"] == "unavailable"
        assert item["review_inputs"]["registry"]["keys"] == item["review_inputs"]["reviews"] == []
        assert item["review_inputs"]["evidence_artifacts"] == {}
    assert source_bytes and all(source_bytes.values())
    output = tmp_path / "installed-shared-parent-project"
    receipt = native.build_parent_shared_definition_use_native_v1(preparation,
        **shared_native_arguments(example), lake_executable=str(executable),
        output_directory=output, timeout_seconds=60)
    assert_shared_native_success(support, example, receipt, output, modules=9, inputs=15, theorems=6)
    assert receipt["status"] == "conditional_native_checks_passed"
    assert receipt["runtime"] == "native" and receipt["returncode"] == 0
    assert type(receipt["pid"]) is int and receipt["pid"] > 0
    assert receipt["binary_sha256"] == binary_pins
    assert set(receipt["version_probes"]) == {"lake", "lean"}
    for name, probe in receipt["version_probes"].items():
        assert probe["command"] == [str(executable.parent / name), "--version"]
        assert probe["returncode"] == 0 and "4.34.1" in probe["stdout"]
    assert receipt["expected_command"] == receipt["command"] == [
        str(executable), "--offline", "--no-cache", "build", "legal"]
    assert receipt["axiom_observation_errors"] == []
    assert receipt["conditional_kernel_status"] == "checked_under_explicit_hypotheses"
    for component in receipt["components"]:
        assert component["review_evidence"]["status"] == "pending"
        assert component["review_evidence"]["blockers"]
        assert component["review_evidence"]["prerequisites_satisfied_under_selected_trust"] is False
        assert any("exact donor definition and explicit alias" in text
                   for text in component["theorem_assumptions"])
    lifecycle = receipt["native_lifecycle"]
    for flag in ("cleanup_confirmed", "leader_reaped", "descendant_tracking_complete", "group_scan_complete"):
        assert lifecycle[flag] is True
    assert lifecycle["remaining_group_members"] == lifecycle["remaining_tracked_descendants"] == []
    assert lifecycle["observation_errors"] == [] and lifecycle["workspace"]["removed"] is True
    assert lifecycle["readers"]["started"] == lifecycle["readers"]["joined"] == 2
    assert lifecycle["stdin_writer"]["started"] == lifecycle["stdin_writer"]["joined"]
    for flag in ("timed_out", "cancelled", "unavailable", "output_truncated",
                 "workspace_limit_exceeded", "resource_exhausted"):
        assert receipt[flag] is False
    assert receipt["post_run_validation_error"] is receipt["binary_recheck_error"] is None
    assert example["arguments"] == before_inputs and preparation == before_preparation
    assert all(path.read_bytes() == raw for path, raw in source_bytes.items())
    for name, relative in receipt["artifact_files"].items():
        raw = (output / relative).read_bytes()
        assert raw and len(raw) == receipt["artifact_bytes"][name]
        assert support.official.sha(raw) == receipt["artifact_sha256"][name]
    expected_files = ({"project/" + name for name, _ in preparation.files}
        | {"project/corpus-manifest.json"} | set(receipt["artifact_files"].values())
        | {"executed-inputs/" + name for name, _ in preparation.files}
        | {"stdout.txt", "stderr.txt", "runner-error.txt", "build-receipt.json"})
    actual_files = set()
    for path in output.rglob("*"):
        assert not path.is_symlink()
        if path.is_file():
            actual_files.add(path.relative_to(output).as_posix())
    assert actual_files == expected_files and len(actual_files) == 44



def test_parent_shared_native_complete_aggregate_input_bound_precedes_lazy_owners(
        shared_native_fol, monkeypatch, tmp_path):
    preparation = shared_native_fol["preparation"]
    arguments = deepcopy(shared_native_arguments(shared_native_fol))
    # Keep the real offered project and independent pin. Each child has less
    # than48MiB added, while their expanded population exceeds the shared limit.
    # No semantic claim is made for these deliberately oversized evidence bytes.
    payload = b"x" * (25 * 1024**2)
    for item in arguments["component_inputs"]:
        item["review_inputs"]["evidence_artifacts"]["fixture:aggregate-input-budget-probe"] = payload
    entered = []

    def forbidden(*args, **kwargs):
        entered.append(True)
        raise AssertionError("over-budget aggregate input reached lazy native owners")

    monkeypatch.setattr(native, "_owners", forbidden)
    monkeypatch.setattr(native, "_installed_toolchain", forbidden)
    monkeypatch.setattr(process.BoundedToolRunner, "run", forbidden)
    output = tmp_path / "over-budget-must-not-exist"
    with pytest.raises(ValueError):
        native.build_parent_shared_definition_use_native_v1(preparation, **arguments,
            lake_executable=str(tmp_path / "never-executed"), output_directory=output,
            timeout_seconds=12)
    assert entered == [] and not output.exists()
    assert "fixture:aggregate-input-budget-probe" not in shared_native_fol["arguments"][
        "component_inputs"][0]["review_inputs"]["evidence_artifacts"]


def test_parent_shared_native_changed_validated_snapshot_refuses_before_toolchain(
        shared_native_fol, monkeypatch, tmp_path):
    from dataclasses import replace

    example = dict(shared_native_fol)
    example["preparation"] = replace(shared_native_fol["preparation"])
    preparation = example["preparation"]
    original_files, original_manifest = preparation.files, preparation.manifest_json
    arguments = shared_native_arguments(example)
    original_validate = native.validate_parent_shared_definition_use_native_v1
    returned = []

    def change_returned_project(*args, **kwargs):
        checked = original_validate(*args, **kwargs)
        files = list(checked.files)
        index = next(index for index, (name, _) in enumerate(files) if name.endswith(".lean"))
        name, body = files[index]
        files[index] = (name, body + "\n-- changed after genuine aggregate validation\n")
        # Mutate the returned value after its genuine validation, preserving
        # every independently pinned caller input and the original manifest.
        object.__setattr__(checked, "files", tuple(files))
        returned.append(checked)
        return checked

    def forbidden(*args, **kwargs):
        raise AssertionError("changed validated aggregate snapshot reached a toolchain")

    monkeypatch.setattr(native, "validate_parent_shared_definition_use_native_v1", change_returned_project)
    monkeypatch.setattr(native, "_installed_toolchain", forbidden)
    monkeypatch.setattr(process.BoundedToolRunner, "run", forbidden)
    output = tmp_path / "changed-snapshot-must-not-exist"
    with pytest.raises(ValueError, match="frozen native preparation differs from independent complete pin"):
        native.build_parent_shared_definition_use_native_v1(preparation, **arguments,
            lake_executable=str(tmp_path / "never-executed"), output_directory=output,
            timeout_seconds=12)
    assert len(returned) == 1 and not output.exists()
    assert shared_native_fol["preparation"].files == original_files
    assert shared_native_fol["preparation"].manifest_json == original_manifest
