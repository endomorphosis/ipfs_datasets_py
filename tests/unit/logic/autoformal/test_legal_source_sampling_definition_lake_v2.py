"""Source-bound V2 Lake preparation and explicitly synthetic process controls.

Preparation tests use the real source sampler, custody, definition compiler and
corpus companion. The build receipt controls replace only installed-toolchain
discovery and the bounded process runner. Their fake artifacts cannot qualify a
native Lean build, a statutory interpretation, a human review or training gold.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import (
    legal_source_sampling_definition_lake_v2 as lake,
)
from ipfs_datasets_py.logic.backends import process


_SPEC = importlib.util.spec_from_file_location(
    "_source_bound_v2_lake_fictional_fixture",
    Path(__file__).with_name("test_legal_source_sampling_definition_binding_v2.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)

TOOLCHAIN = "leanprover/lean4:v4.34.1"


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(canonical(value))


def reseal(value):
    return contracts.seal_record({
        key: item for key, item in value.items()
        if key not in {"record_cid", "cid_scope"}
    })


def replay(case, responses=()):
    return {
        "expected_request_sha256": sha(case["request_raw"]),
        "expected_bundle_sha256": digest(case["bundle"]),
        "expected_response_sha256s": [digest(row) for row in responses],
        **case["replay"],
    }


def prepare(case, result, *, responses=(), **overrides):
    arguments = {
        "expected_binding_sha256": digest(result),
        "toolchain": TOOLCHAIN,
        **replay(case, responses),
        **overrides,
    }
    return lake.prepare_definition_lake_v2(
        result, case["request_raw"], case["bundle"], list(responses),
        case["raw"], **arguments,
    )


def validate(preparation, case, result, *, responses=(), **overrides):
    arguments = {
        "expected_preparation_sha256": lake.preparation_sha256(preparation),
        "expected_binding_sha256": digest(result),
        "toolchain": TOOLCHAIN,
        **replay(case, responses),
        **overrides,
    }
    return lake.validate_definition_lake_v2(
        preparation, result, case["request_raw"], case["bundle"],
        list(responses), case["raw"], **arguments,
    )


def build(preparation, case, result, *, executable, output, responses=(), **overrides):
    arguments = {
        "expected_preparation_sha256": lake.preparation_sha256(preparation),
        "expected_binding_sha256": digest(result),
        "toolchain": TOOLCHAIN,
        "lake_executable": str(executable),
        "output_directory": output,
        **replay(case, responses),
        **overrides,
    }
    return lake.build_definition_lake_v2(
        preparation, result, case["request_raw"], case["bundle"],
        list(responses), case["raw"], **arguments,
    )


@pytest.fixture(scope="module", params=("fol", "tdfol"))
def source_case(request):
    case = _FIXTURE.prepared(family=request.param)
    result = _FIXTURE.prepare(case)
    return case, result, prepare(case, result)


def forged_preparation(preparation, *, files=None, mutate_manifest=None):
    manifest = preparation.to_dict()
    final_files = dict(preparation.files) if files is None else files
    manifest["file_sha256"] = {
        name: sha(body.encode("utf-8")) for name, body in sorted(final_files.items())
    }
    if mutate_manifest is not None:
        mutate_manifest(manifest)
    return replace(
        preparation,
        files=tuple(sorted(final_files.items())),
        manifest_json=canonical(reseal(manifest)).decode("utf-8"),
    )


def test_public_import_loads_only_stdlib_and_no_operation_owner():
    script = r"""
import importlib.util, json, sys
blocked = ('ipfs_datasets_py', 'torch', 'transformers', 'tensorflow', 'numpy', 'multiformats', 'cbor2', 'cryptography', 'requests', 'pyarrow')
attempts = []
class DenyProduction:
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == prefix or fullname.startswith(prefix + '.') for prefix in blocked):
            attempts.append(fullname)
            raise AssertionError('Operation owner reached during public import')
        return None
sys.meta_path.insert(0, DenyProduction())
spec = importlib.util.spec_from_file_location('_v2_lake_cold_import', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert not attempts
for name in ('DefinitionLakePreparation', 'prepare_definition_lake_v2', 'preparation_sha256', 'validate_definition_lake_v2', 'build_definition_lake_v2'):
    assert hasattr(module, name), name
assert not any(any(name == prefix or name.startswith(prefix + '.') for prefix in blocked) for name in sys.modules)
print(json.dumps({'production_import_attempts': attempts}))
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script, lake.__file__],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"production_import_attempts": []}


@pytest.mark.parametrize("value", ["main", "leanprover/lean4:latest", "leanprover/lean4:v4.34.1\n", None, True])
def test_nonexact_toolchain_refuses_before_operation_owners(source_case, value):
    case, result, _ = source_case
    with patch.object(lake, "_owners", side_effect=AssertionError("operation owners reached")):
        with pytest.raises(ValueError):
            prepare(case, result, toolchain=value)


@pytest.mark.parametrize("value", ["0" * 64, "A" * 64, "short", None, True])
def test_independent_binding_commitment_refuses_before_operation_owners(source_case, value):
    case, result, _ = source_case
    with patch.object(lake, "_owners", side_effect=AssertionError("operation owners reached")):
        with pytest.raises(ValueError):
            prepare(case, result, expected_binding_sha256=value)


@pytest.mark.parametrize("value", ["0" * 64, "A" * 64, "short", None, True])
def test_independent_preparation_commitment_refuses_before_operation_owners(source_case, value):
    case, result, preparation = source_case
    with patch.object(lake, "_owners", side_effect=AssertionError("operation owners reached")):
        with pytest.raises(ValueError):
            validate(preparation, case, result, expected_preparation_sha256=value)


def test_exact_closed_project_retains_native_formula_and_complete_source_binding(source_case):
    case, result, preparation = source_case
    manifest, files = preparation.to_dict(), dict(preparation.files)
    modules = manifest["expected_modules"]
    assert manifest["schema"] == "legal-source-sampling-definition-lake-preparation/v2"
    assert manifest["family"] == case["request"]["family"]
    assert manifest["declaration_id"] == case["request"]["declaration"]["declaration_id"]
    assert manifest["binding_full_canonical_sha256"] == digest(result)
    assert manifest["candidate_full_canonical_sha256"] == digest(result["candidate"])
    assert manifest["population_full_canonical_sha256"] == digest(result["population"])
    assert manifest["source_binding"] == result["binding"]
    assert manifest["review_status"] == result["binding"]["status"] == "pending"
    assert len(modules) == len(set(modules)) == 3
    assert modules[0] == "LegalSourceDefinitionV2.Prelude"
    assert modules[1].startswith("LegalSourceDefinitionV2.Definition")
    assert modules[-1] == "LegalSourceDefinitionV2"
    paths = {module.replace(".", "/") + ".lean" for module in modules}
    assert set(files) == paths | {"lakefile.toml", "lean-toolchain", "v2-input-bindings.json"}
    assert len(preparation.files) == len(files) == 6
    assert manifest["file_sha256"] == {
        name: sha(body.encode("utf-8")) for name, body in files.items()
    }
    module_path = modules[1].replace(".", "/") + ".lean"
    assert files[module_path] == (
        "import LegalSourceDefinitionV2.Prelude\nnamespace " + modules[1] + "\n"
        + result["definition_report"]["lean_body"] + "\nend " + modules[1] + "\n"
    )
    assert files["LegalSourceDefinitionV2.lean"] == "import " + modules[1] + "\n"
    assert manifest["module_imports"] == {
        modules[0]: [], modules[1]: [modules[0]], modules[2]: [modules[1]],
    }
    assert files["v2-input-bindings.json"] == canonical(result["binding"]).decode("utf-8") + "\n"
    assert 'name = "legal"' in files["lakefile.toml"]
    assert 'roots = ["LegalSourceDefinitionV2"]' in files["lakefile.toml"]
    assert files["lean-toolchain"] == TOOLCHAIN + "\n"
    report = result["definition_report"]
    assert manifest["native_ast_sha256"] == digest(report["native_ast"])
    assert manifest["native_fragment_sha256"] == digest(report["native"])
    assert manifest["lean_body_sha256"] == sha(report["lean_body"].encode("utf-8"))
    assert report["native"]["exact_native_ast_roundtrip"] is True
    assert "∀ v0 : Entity" in files[module_path]
    assert all(row["state"] == "pending" for row in result["population"]["subjects"])
    assert validate(preparation, case, result) == preparation


def test_preparation_does_not_probe_toolchain_launch_backend_or_grant_authority(source_case, monkeypatch):
    case, result, _ = source_case
    from ipfs_datasets_py.logic.autoformal import legal_pilot_lake as toolchain

    def forbidden(*args, **kwargs):
        raise AssertionError("preparation must not execute a backend or toolchain probe")

    monkeypatch.setattr(toolchain, "_installed_toolchain", forbidden)
    monkeypatch.setattr(process.BoundedToolRunner, "run", forbidden)
    preparation = prepare(case, result)
    manifest = preparation.to_dict()
    assert manifest["preparation_only"] is True
    assert all(value is False for value in manifest["authority"].values())
    for key in ("backend_executed", "lean_compilation_verified", "source_semantics_verified", "admitted", "training_qualified", "proof_authority"):
        assert manifest[key] is False
    assert type(manifest["training_mask"]) is int and manifest["training_mask"] == 0
    assert type(manifest["evaluation_gold_mask"]) is int and manifest["evaluation_gold_mask"] == 0
    assert validate(preparation, case, result) == preparation


@pytest.mark.parametrize(
    "field", ["expected_request_sha256", "expected_bundle_sha256", "expected_raw_sha256", "expected_sampling_report_sha256", "expected_descriptor_sha256"]
)
def test_each_original_input_commitment_refuses_before_rendering_or_process_owners(source_case, field):
    case, result, _ = source_case
    with patch.object(lake, "_owners", side_effect=AssertionError("rendering/process owners reached")):
        with pytest.raises(ValueError):
            prepare(case, result, **{field: "0" * 64})


@pytest.mark.parametrize("damage", ["ast", "source_role", "population", "authority", "mask"])
def test_resealed_binding_companions_cannot_enter_preparation(source_case, damage):
    case, original, _ = source_case
    result = deepcopy(original)
    if damage == "ast":
        report = result["definition_report"]
        report["native_ast"]["formula"]["operator"]["value"] = "→"
        report["report_sha256"] = digest({
            key: value for key, value in report.items() if key != "report_sha256"
        })
    elif damage == "source_role":
        result["binding"]["source_role_bindings"].pop()
    elif damage == "population":
        result["population"]["subjects"].pop()
        result["population"] = reseal(result["population"])
    elif damage == "authority":
        result["binding"]["authority"]["source_semantics_verified"] = True
    else:
        result["binding"]["training_mask"] = 1
    result["binding"] = reseal(result["binding"])
    with pytest.raises(ValueError):
        prepare(case, result)


@pytest.mark.parametrize(
    "damage", ["formula", "axiom", "sorry", "missing_definition", "missing_prelude", "drop_import", "extra_file", "changed_prelude"]
)
def test_resealed_project_cannot_omit_or_replace_compiled_source(source_case, damage):
    case, result, original = source_case
    files = dict(original.files)
    module = original.to_dict()["expected_modules"][1]
    path = module.replace(".", "/") + ".lean"
    if damage == "formula":
        files[path] = "def formula_0 : Prop := True\n"
    elif damage == "axiom":
        files[path] += "axiom invented : False\n"
    elif damage == "sorry":
        files[path] += "theorem invented : False := by sorry\n"
    elif damage == "missing_definition":
        del files[path]
    elif damage == "missing_prelude":
        del files["LegalSourceDefinitionV2/Prelude.lean"]
    elif damage == "drop_import":
        files["LegalSourceDefinitionV2.lean"] = "-- removed required import\n"
    elif damage == "extra_file":
        files["../escaped.lean"] = "def escaped : Prop := True\n"
    else:
        files["LegalSourceDefinitionV2/Prelude.lean"] += "axiom invented : False\n"
    forged = forged_preparation(original, files=files)
    with pytest.raises(ValueError):
        validate(forged, case, result)


@pytest.mark.parametrize(
    "damage", ["native_ast", "source_roles", "population", "review_status", "module_coverage", "authority", "mask", "unknown_field"]
)
def test_resealed_manifest_cannot_rewrite_source_review_AST_or_authority(source_case, damage):
    case, result, original = source_case

    def mutate(manifest):
        if damage == "native_ast":
            manifest["native_ast_sha256"] = "0" * 64
        elif damage == "source_roles":
            metadata = manifest["source_binding"]
            metadata["source_role_bindings"].pop()
            manifest["source_binding"] = reseal(metadata)
        elif damage == "population":
            metadata = manifest["source_binding"]
            metadata["population_ref"]["sha256"] = "0" * 64
            manifest["source_binding"] = reseal(metadata)
        elif damage == "review_status":
            manifest["review_status"] = "declarations_recorded"
        elif damage == "module_coverage":
            manifest["expected_modules"].pop(1)
        elif damage == "authority":
            manifest["authority"]["proof_authority"] = True
        elif damage == "mask":
            manifest["evaluation_gold_mask"] = 1
        else:
            manifest["ignored"] = "must refuse"

    forged = forged_preparation(original, mutate_manifest=mutate)
    with pytest.raises(ValueError):
        validate(forged, case, result)


@pytest.mark.parametrize(
    "failure",
    [
        None, "missing_nonfirst_module", "empty_module", "extra_output",
        "changed_executed_source", "wrong_target", "no_process", "binary_changed",
        "error_exit", "sorry_warning", "timed_out", "cancelled", "truncated",
        "unavailable", "resource_exhausted", "workspace_limit", "workspace_unclean",
        "runner_error", "missing_lifecycle", "live_descendant", "unjoined_reader",
        "unremoved_workspace", "wrong_runtime",
    ],
)
def test_explicitly_synthetic_process_receipt_requires_exact_execution_and_artifacts(
    source_case, monkeypatch, tmp_path, failure
):
    """Fake process artifacts test receipt refusal; they are no Lean evidence."""
    case, result, preparation = source_case
    executable = tmp_path / "lake"
    executable.write_bytes(b"explicitly-synthetic-test-binary-not-a-compiler")
    binary_sha = sha(executable.read_bytes())
    monkeypatch.setattr(
        lake, "_installed_toolchain",
        lambda *args, **kwargs: (executable, {str(executable): binary_sha}, {}),
    )
    calls = []
    token = process.CancellationToken()
    expected_modules = preparation.to_dict()["expected_modules"]
    artifact_paths = tuple(
        ".lake/build/lib/lean/" + module.replace(".", "/") + ".olean"
        for module in expected_modules
    )

    def synthetic_run(self, request, *, cancellation=None, **kwargs):
        calls.append(request)
        assert cancellation is token
        assert request.argv == (str(executable), "--offline", "--no-cache", "build", "legal")
        assert request.environment["ELAN_TOOLCHAIN"] == TOOLCHAIN
        assert request.limits.timeout_seconds == 12
        assert request.owned_process_observation is True
        assert request.output_paths == artifact_paths + tuple(sorted(dict(preparation.files)))
        assert dict(request.input_files) == dict(preparation.files)
        outputs = {path: b"explicitly-synthetic-not-a-Lean-artifact" for path in artifact_paths}
        outputs.update({
            name: body.encode("utf-8") if isinstance(body, str) else body
            for name, body in request.input_files.items()
        })
        if failure == "missing_nonfirst_module":
            outputs.pop(artifact_paths[1])
        elif failure == "empty_module":
            outputs[artifact_paths[1]] = b""
        elif failure == "extra_output":
            outputs["unrequested-output.bin"] = b"unexpected"
        elif failure == "changed_executed_source":
            module_path = expected_modules[1].replace(".", "/") + ".lean"
            outputs[module_path] = b"def formula_0 : Prop := True\n"
        elif failure == "binary_changed":
            executable.write_bytes(b"different synthetic binary")
        # All identities and observations here are explicitly synthetic. The
        # real dataclass exercises its cleanup predicate without a live child.
        identity = process.NativeProcessIdentity(
            pid=123, birth_ticks=1, parent_pid=2, process_group_id=123, session_id=123,
        )
        lifecycle = process.NativeToolLifecycleObservation(
            parent_pid=2, parent_birth_ticks=1, leader=identity,
            observed_descendants=(), leader_reaped=True,
            descendant_tracking_complete=True, group_scan_complete=True,
            remaining_group_members=(),
            remaining_tracked_descendants=(identity,) if failure == "live_descendant" else (),
            readers_started=2, readers_joined=1 if failure == "unjoined_reader" else 2,
            stdin_writer_started=0, stdin_writer_joined=0,
            workspace_device=1, workspace_inode=1,
            workspace_removed=failure != "unremoved_workspace",
        )
        return process.ToolRunResult(
            interface_version="explicitly-synthetic-process-control/v1",
            runtime=process.ToolRuntime.JVM if failure == "wrong_runtime" else process.ToolRuntime.NATIVE,
            command=(*request.argv[:-1], "Legal") if failure == "wrong_target" else request.argv,
            returncode=1 if failure == "error_exit" else 0,
            stdout="warning: sorryAx" if failure == "sorry_warning" else "",
            stderr="", elapsed_seconds=0.01, output_files=outputs,
            pid=None if failure == "no_process" else 123,
            timed_out=failure == "timed_out", cancelled=failure == "cancelled",
            unavailable=failure == "unavailable",
            resource_exhausted=failure == "resource_exhausted",
            output_truncated=failure == "truncated",
            workspace_limit_exceeded=failure == "workspace_limit",
            workspace_cleaned=failure != "workspace_unclean",
            process_tree_terminated=False,
            error="explicit synthetic runner failure" if failure == "runner_error" else "",
            native_lifecycle=None if failure == "missing_lifecycle" else lifecycle,
        )

    monkeypatch.setattr(process.BoundedToolRunner, "run", synthetic_run)
    output = tmp_path / "project-and-receipt"
    receipt = build(
        preparation, case, result, executable=executable, output=output,
        cancellation=token, timeout_seconds=12,
    )
    assert len(calls) == 1
    assert receipt["build_passed"] is (failure is None)
    assert receipt["backend_executed"] is (failure != "no_process")
    assert receipt["native_runtime_verified"] is (
        failure not in {"no_process", "wrong_runtime", "unavailable"}
    )
    assert receipt["lean_compilation_verified"] is (failure is None)
    assert receipt["executed_project_readback_passed"] is (failure != "changed_executed_source")
    assert receipt["binaries_unchanged"] is (failure != "binary_changed")
    assert receipt["workspace_cleaned"] is (failure != "workspace_unclean")
    assert receipt["cancelled"] is (failure == "cancelled")
    assert receipt["process_tree_terminated"] is False
    assert receipt["cleanup_confirmed"] is (
        failure not in {"no_process", "missing_lifecycle", "live_descendant", "unjoined_reader", "unremoved_workspace"}
    )
    assert not set(receipt["artifact_sha256"]) - set(artifact_paths)
    assert receipt["post_run_validation_passed"] is True
    for key in ("source_semantics_verified", "source_authenticity_verified", "independently_reviewed", "admitted", "training_qualified", "proof_authority"):
        assert receipt[key] is False
    assert receipt["training_mask"] == receipt["evaluation_gold_mask"] == 0
    assert output.is_dir()
    assert (output / "build-receipt.json").is_file()
    for name, expected in receipt["log_sha256"].items():
        retained = (output / name).read_bytes()
        assert sha(retained) == expected
        assert len(retained) == receipt["log_bytes"][name]


@pytest.mark.parametrize("timeout", [True, 0, -1, 61, float("nan"), float("inf")])
def test_invalid_process_bound_refuses_without_probe_process_or_export(source_case, tmp_path, timeout):
    case, result, preparation = source_case
    output = tmp_path / "must-not-exist"
    with patch.object(lake, "_installed_toolchain", side_effect=AssertionError("probe reached")):
        with patch.object(process.BoundedToolRunner, "run", side_effect=AssertionError("process reached")):
            with pytest.raises(ValueError):
                build(
                    preparation, case, result, executable=tmp_path / "lake", output=output,
                    timeout_seconds=timeout,
                )
    assert not output.exists()


def test_existing_output_directory_is_not_overwritten_or_used_for_native_execution(source_case, tmp_path):
    case, result, preparation = source_case
    output = tmp_path / "existing"
    output.mkdir()
    original = output / "retained-evidence.txt"
    original.write_bytes(b"retain exactly")
    with patch.object(lake, "_installed_toolchain", side_effect=AssertionError("probe reached")):
        with patch.object(process.BoundedToolRunner, "run", side_effect=AssertionError("process reached")):
            with pytest.raises(ValueError):
                build(preparation, case, result, executable=tmp_path / "lake", output=output)
    assert original.read_bytes() == b"retain exactly"
    assert list(output.iterdir()) == [original]


def test_split_scope_parent_and_unselected_population_survive_preparation():
    case = _FIXTURE.prepared_with_split_scope()
    result = _FIXTURE.prepare(case)
    preparation = prepare(case, result)
    metadata = preparation.to_dict()["source_binding"]
    required_parents = [
        row for row in metadata["required_subjects"]
        if row["subject_ref"]["kind"] == "withheld_context"
    ]
    assert len(required_parents) == 1
    assert required_parents[0]["state"] == "pending"
    assert set(required_parents[0]["roles"]) == {"scope_block", "scope_literal"}
    all_parents = [
        row for row in result["population"]["subjects"]
        if row["subject_ref"]["kind"] == "withheld_context"
    ]
    assert len(all_parents) == 2
    assert metadata == result["binding"]
    assert metadata["population_ref"]["sha256"] == digest(result["population"])
    assert validate(preparation, case, result) == preparation


def test_identical_html_for_another_edition_cannot_reuse_a_prepared_project():
    first = _FIXTURE.prepared(edition=2024)
    second = _FIXTURE.prepared(edition=2025)
    assert first["raw"] == second["raw"]
    first_result, second_result = _FIXTURE.prepare(first), _FIXTURE.prepare(second)
    original = prepare(first, first_result)
    changed = prepare(second, second_result)
    assert original != changed
    assert (
        original.to_dict()["source_binding"]["source_identity"]
        != changed.to_dict()["source_binding"]["source_identity"]
    )
    with pytest.raises(ValueError):
        validate(original, second, second_result)


@pytest.mark.parametrize("damage", ["duplicate_key", "nonfinite", "mutable_request", "mutable_source", "oversize_request"])
def test_malformed_original_bytes_refuse_before_rendering_or_process_owners(source_case, damage):
    case, result, _ = source_case
    offered = dict(case)
    if damage == "duplicate_key":
        offered["request_raw"] = b'{"family":"fol","family":"tdfol"}'
    elif damage == "nonfinite":
        offered["request_raw"] = b'{"value":NaN}'
    elif damage == "mutable_request":
        offered["request_raw"] = bytearray(case["request_raw"])
    elif damage == "mutable_source":
        offered["raw"] = bytearray(case["raw"])
    else:
        offered["request_raw"] = b" " * (1024 * 1024 + 1)
    with patch.object(lake, "_owners", side_effect=AssertionError("rendering/process owners reached")):
        with pytest.raises(ValueError):
            prepare(offered, result)


@pytest.mark.parametrize("damage", ["wrong_count", "boolean_count", "unknown_replay", "missing_response_pin"])
def test_closed_replay_inputs_and_original_population_bounds_refuse_before_owners(source_case, damage):
    case, result, _ = source_case
    overrides = {
        "wrong_count": {"expected_raw_bytes": len(case["raw"]) + 1},
        "boolean_count": {"expected_raw_bytes": True},
        "unknown_replay": {"unrecognized_replay_owner": None},
        "missing_response_pin": {"expected_response_sha256s": ["0" * 64]},
    }[damage]
    with patch.object(lake, "_owners", side_effect=AssertionError("rendering/process owners reached")):
        with pytest.raises(ValueError):
            prepare(case, result, **overrides)


def test_unresolved_owned_cleanup_preserves_custody_and_an_unqualified_receipt(
    source_case, monkeypatch, tmp_path
):
    """A synthetic exception sentinel tests handle identity, with no live child."""
    case, result, preparation = source_case
    executable = tmp_path / "synthetic-lake"
    executable.write_bytes(b"synthetic-custody-control-not-a-compiler")
    binary_sha = sha(executable.read_bytes())
    monkeypatch.setattr(
        lake, "_installed_toolchain",
        lambda *args, **kwargs: (executable, {str(executable): binary_sha}, {}),
    )
    handle = object()
    original = process.OwnedToolCleanupError(handle, "synthetic unresolved cleanup sentinel")

    def refuse(self, request, *, cancellation=None):
        assert request.owned_process_observation is True
        raise original

    monkeypatch.setattr(process.BoundedToolRunner, "run", refuse)
    output = tmp_path / "retained-cleanup-refusal"
    with pytest.raises(process.OwnedToolCleanupError) as caught:
        build(preparation, case, result, executable=executable, output=output)
    assert caught.value is original
    assert caught.value.cleanup_handle is handle
    receipt = json.loads((output / "build-receipt.json").read_bytes())
    assert receipt["status"] == "owned_native_cleanup_unresolved"
    assert receipt["cleanup_owner_retained_on_exception"] is True
    assert receipt["cleanup_confirmed"] is False
    assert receipt["build_passed"] is False
    assert receipt["backend_executed"] is False
    assert receipt["lean_compilation_verified"] is False
    assert receipt["artifact_sha256"] == {}
    assert all(value is False for value in receipt["authority"].values())
    assert receipt["training_mask"] == receipt["evaluation_gold_mask"] == 0
    for name, body in preparation.files:
        assert (output / "project" / name).read_bytes() == body.encode("utf-8")
