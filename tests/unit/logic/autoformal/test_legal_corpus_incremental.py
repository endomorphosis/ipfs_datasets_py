"""Independently pinned incremental corpus custody; authored fake compiler only."""

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
from copy import deepcopy
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_definition_norm_adapter as adapter
from ipfs_datasets_py.logic.autoformal import legal_corpus_shared_lake as shared
from ipfs_datasets_py.logic.autoformal import legal_source_definition_norm_bridge as bridge
from ipfs_datasets_py.logic.autoformal import legal_source_definition_norm_lake as native
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "authored_shared_definition_fixture_for_incremental",
    Path(__file__).with_name("test_legal_corpus_shared_lake.py"),
)
assert _FIXTURE_SPEC is not None and _FIXTURE_SPEC.loader is not None
_FIXTURE_MODULE = importlib.util.module_from_spec(_FIXTURE_SPEC)
_FIXTURE_SPEC.loader.exec_module(_FIXTURE_MODULE)

TOOLCHAIN = "leanprover/lean4:v4.34.1"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()


def changed_definition(case):
    """Change only an explicit caller interpretation, retaining exact source bytes."""
    original_inputs = case[0]
    request = json.loads(original_inputs["request_raw"])
    declaration = request["definition_request"]["declaration"]
    assert declaration["body"]["op"] == "any"
    declaration["body"]["op"] = "all"
    definition = bridge.definitions.prepare_definition(request["definition_request"])
    request["norm_declaration"]["definition_head_symbol"] = definition["native_ast"]["formula"][
        "left"
    ]["name"]
    report = bridge.prepare_definition_norm(request)
    request_raw, report_raw = wire(request), wire(report)
    raw_html = original_inputs["raw_html"]
    extracted_sha = sha(request["definition_request"]["document"]["document_text"].encode())
    candidate = adapter.adapt_definition_norm_bytes(
        report_raw,
        expected_report_sha256=sha(report_raw),
        request_raw=request_raw,
        expected_request_sha256=sha(request_raw),
        raw_html=raw_html,
        expected_raw_sha256=sha(raw_html),
        expected_extracted_sha256=extracted_sha,
    )
    candidate_raw = canonical_dag_json_bytes(candidate)
    inputs = dict(
        candidate_raw=candidate_raw,
        report_raw=report_raw,
        request_raw=request_raw,
        raw_html=raw_html,
    )
    pins = dict(
        candidate_sha256=sha(candidate_raw),
        candidate_cid=candidate["record_cid"],
        graph_cid=candidate["graph"]["record_cid"],
        request_sha256=sha(request_raw),
        report_sha256=sha(report_raw),
        raw_sha256=sha(raw_html),
        extracted_sha256=extracted_sha,
    )
    return inputs, pins, candidate, report


def prepare(cases):
    return shared.prepare_shared_definition_corpus(
        [case[0] for case in cases],
        expected_population=[case[1] for case in cases],
        toolchain=TOOLCHAIN,
    )


@pytest.fixture(scope="module")
def independent_definitions():
    # Different editions establish independent source identities. A caller's
    # revised A interpretation cannot silently change B's physical source.
    first = _FIXTURE_MODULE.candidate("O", edition=2024, norm_id="independent-A")
    second = _FIXTURE_MODULE.candidate("P", edition=2025, norm_id="independent-B")
    changed_first = changed_definition(first)
    original = [first, second]
    changed = [changed_first, second]
    assert first[2]["source_version"]["record_cid"] != second[2]["source_version"]["record_cid"]
    assert first[0]["raw_html"] == changed_first[0]["raw_html"]
    assert first[2]["source_version"] == changed_first[2]["source_version"]
    assert (
        first[2]["definition_record"]["native_ast"]
        != changed_first[2]["definition_record"]["native_ast"]
    )
    return original, prepare(original), changed, prepare(changed)


class AuthoredCompiler:
    """Deterministic test artifact bytes, never a Lean/kernel implementation."""

    def __init__(self, directory):
        self.lake = directory / "lake"
        self.lean = directory / "lean"
        self.lake.write_bytes(b"\x7fELF-authored-fake-lake-no-native-execution")
        self.lean.write_bytes(b"\x7fELF-authored-fake-lean-no-native-execution")
        self.calls = []
        self.library_salt = "authored-library-v1"
        self.fail_module = None

    def installed(self, *args):
        return (
            self.lake,
            {str(p): sha(p.read_bytes()) for p in (self.lake, self.lean)},
            {"fixture": "authored fake toolchain; no version probe"},
        )

    def closure(self, *args):
        raw = wire({"authored_library": self.library_salt}) + b"\n"
        return contracts.seal_record(
            {
                "schema": "authored-fake-native-library-closure/v1",
                "sha256": sha(raw),
                "bytes": len(raw),
                "file_count": 1,
            }
        ), raw

    def run(self, runner, request, **kwargs):
        assert request.argv[0] == str(self.lean)
        assert len(request.output_paths) == 1
        output_path = request.output_paths[0]
        assert output_path.startswith("compiled/") and output_path.endswith(".olean")
        module = output_path.removeprefix("compiled/").removesuffix(".olean").replace("/", ".")
        source_path = module.replace(".", "/") + ".lean"

        def raw(value):
            return value.encode() if isinstance(value, str) else value

        source = raw(request.input_files[source_path])
        imports = re.findall(r"^import ([A-Za-z0-9_.]+)$", source.decode(), re.MULTILINE)
        imported = {
            name: sha(raw(request.input_files["compiled/" + name.replace(".", "/") + ".olean"]))
            for name in imports
        }
        assert request.environment["LEAN_PATH"] == "compiled"
        assert request.limits.timeout_seconds <= 60
        # The runner applies this capture limit to binary artifacts too.
        # Every individually permitted .olean must fit without clipping.
        assert request.limits.max_output_bytes >= 4 * 1024**2
        self.calls.append({"module": module, "source_sha256": sha(source), "imports": imported})
        failed = module == self.fail_module
        body = b"authored-fake-olean-no-native-proof\0" + wire(
            {
                "module": module,
                "source_sha256": sha(source),
                "import_artifact_sha256": imported,
                "compiler_sha256": sha(self.lean.read_bytes()),
                "library": self.library_salt,
            }
        )
        stdout = (
            "'" + module + ".consequence_of_definition' does not depend on any axioms\n"
            if "theorem consequence_of_definition" in source.decode() and not failed
            else ""
        )
        return native.process.ToolRunResult(
            interface_version="authored-fake-incremental-compiler/v1",
            runtime=native.process.ToolRuntime.NATIVE,
            command=request.argv,
            returncode=1 if failed else 0,
            stdout=stdout,
            stderr="authored deliberate type failure" if failed else "",
            elapsed_seconds=0.01,
            pid=123,
            output_files={} if failed else {output_path: body},
            workspace_cleaned=True,
            process_tree_terminated=False,
        )


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_incremental as incremental

    compiler = AuthoredCompiler(tmp_path)
    monkeypatch.setattr(native.shared, "_installed_toolchain", compiler.installed)
    monkeypatch.setattr(incremental, "_toolchain_closure", compiler.closure)
    monkeypatch.setattr(
        native.process.BoundedToolRunner,
        "run",
        lambda runner, request, **kwargs: compiler.run(runner, request, **kwargs),
    )
    return incremental, compiler, tmp_path


def build(runtime, cases, preparation, name, *, previous=None, **options):
    incremental, compiler, directory = runtime
    arguments = dict(
        candidate_inputs=[case[0] for case in cases],
        expected_population=[case[1] for case in cases],
        toolchain=TOOLCHAIN,
        lake_executable=str(compiler.lake),
        output_directory=directory / name,
    )
    if previous is not None:
        old_receipt, old_directory = previous
        raw = (old_directory / "cache.json").read_bytes()
        arguments.update(
            previous_cache_raw=raw,
            expected_previous_cache_sha256=sha(raw),
            previous_artifacts={
                module: (old_directory / path).read_bytes()
                for module, path in old_receipt["artifact_files"].items()
            },
        )
    arguments.update(options)
    receipt = incremental.build_incremental_shared_corpus(preparation, **arguments)
    return receipt, directory / name


def artifacts(result):
    receipt, directory = result
    return {
        module: (directory / path).read_bytes()
        for module, path in receipt["artifact_files"].items()
    }


def cache(result):
    return json.loads((result[1] / "cache.json").read_bytes())


def test_public_incremental_import_does_not_initialize_framework_backend_or_models():
    script = """
import json
import sys
from ipfs_datasets_py.logic.autoformal import legal_corpus_incremental
forbidden = [name for name in sys.modules if name.startswith((
    'torch', 'transformers', 'sentence_transformers',
    'ipfs_datasets_py.logic.integration.reasoning',
    'ipfs_datasets_py.logic.backends.process',
    'ipfs_datasets_py.logic.autoformal.legal_source_definition_norm_lake',
))]
print(json.dumps(forbidden))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[4],
        env=dict(os.environ, IPFS_DATASETS_PY_MINIMAL_IMPORTS="1"),
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    assert json.loads(result.stdout) == []


def test_pre_cancelled_build_refuses_before_toolchain_probes_or_compilation(
    runtime,
    independent_definitions,
    monkeypatch,
):
    cases, preparation, _, _ = independent_definitions
    cancelled = threading.Event()
    cancelled.set()

    def no_probe(*args):
        pytest.fail("pre-cancelled execution reached a toolchain probe")

    monkeypatch.setattr(native.shared, "_installed_toolchain", no_probe)
    with pytest.raises(ValueError):
        build(runtime, cases, preparation, "cancelled", cancellation=cancelled)
    assert runtime[1].calls == []


def reseal(record):
    return contracts.seal_record(
        {key: value for key, value in record.items() if key not in {"record_cid", "cid_scope"}}
    )


def test_full_compile_retains_exact_population_all_artifacts_and_unreviewed_authority(
    runtime,
    independent_definitions,
):
    cases, preparation, _, _ = independent_definitions
    result = build(runtime, cases, preparation, "full")
    receipt, directory = result
    manifest = preparation.to_dict()
    assert receipt["build_passed"] is True
    assert receipt["lean_compilation_verified"] is True
    assert set(receipt["compiled_modules"]) == set(manifest["expected_modules"])
    assert receipt["reused_modules"] == []
    assert len(receipt["fresh_theorems"]) == len(manifest["norm_bindings"]) == 2
    assert receipt["reused_theorems"] == []
    assert {call["module"] for call in runtime[1].calls} == set(manifest["expected_modules"])
    assert receipt["artifact_sha256"] == {name: sha(raw) for name, raw in artifacts(result).items()}
    raw = (directory / "cache.json").read_bytes()
    saved = cache(result)
    assert saved["qualified"] is True
    assert receipt["cache_identity"] == {
        "sha256": sha(raw),
        "record_cid": saved["record_cid"],
        "bytes": len(raw),
    }
    observation = receipt["execution_observations"]
    observed_raw = (directory / observation["path"]).read_bytes()
    assert observation["sha256"] == sha(observed_raw)
    assert observation["bytes"] == len(observed_raw)
    assert {json.loads(line)["module"] for line in observed_raw.splitlines()} == set(
        manifest["expected_modules"]
    )
    for record in (receipt, saved):
        for flag in (
            "source_authenticity_verified",
            "source_semantics_verified",
            "admitted",
            "proof_authority",
        ):
            assert record[flag] is False
    assert all(
        raw.startswith(b"authored-fake-olean-no-native-proof\0")
        for raw in artifacts(result).values()
    )


def test_no_change_requires_no_compiler_execution_and_counts_no_fresh_theorems(
    runtime,
    independent_definitions,
):
    cases, preparation, _, _ = independent_definitions
    first = build(runtime, cases, preparation, "first")
    first_call_count = len(runtime[1].calls)
    second = build(runtime, cases, preparation, "unchanged", previous=first)
    receipt = second[0]
    assert receipt["build_passed"] is True
    assert receipt["compiled_modules"] == []
    assert set(receipt["reused_modules"]) == set(preparation.to_dict()["expected_modules"])
    assert receipt["fresh_theorems"] == []
    assert receipt["backend_executed"] is False
    assert set(receipt["reused_theorems"]) == set(first[0]["fresh_theorems"])
    assert len(runtime[1].calls) == first_call_count
    assert artifacts(second) == artifacts(first)
    assert receipt["artifact_root_cid"] == first[0]["artifact_root_cid"]
    assert cache(second)["qualified"] is True
    observation = receipt["execution_observations"]
    assert (second[1] / observation["path"]).read_bytes() == b""
    assert observation["bytes"] == 0
    assert observation["sha256"] == sha(b"")


def test_changed_definition_A_rebuilds_only_its_closure_and_matches_complete_rebuild(
    runtime,
    independent_definitions,
):
    original, preparation, changed, changed_preparation = independent_definitions
    first = build(runtime, original, preparation, "first")
    old = preparation.to_dict()
    isolated_norm = old["norm_bindings"][1]
    expected_reused = {
        "LegalCorpus.Prelude",
        isolated_norm["definition_module"],
        isolated_norm["module"],
    }
    before = len(runtime[1].calls)
    partial = build(runtime, changed, changed_preparation, "changed-A", previous=first)
    receipt = partial[0]
    expected_modules = set(changed_preparation.to_dict()["expected_modules"])
    assert receipt["build_passed"] is True
    assert set(receipt["reused_modules"]) == expected_reused
    assert set(receipt["compiled_modules"]) == expected_modules - expected_reused
    assert {
        call["module"] for call in runtime[1].calls[before:]
    } == expected_modules - expected_reused
    assert receipt["reused_theorems"] == [isolated_norm["composition_theorem"]]
    assert len(receipt["fresh_theorems"]) == 1
    assert set(artifacts(partial)) == expected_modules
    for module in expected_reused:
        assert artifacts(partial)[module] == artifacts(first)[module]
    complete = build(runtime, changed, changed_preparation, "changed-A-full")
    assert artifacts(partial) == artifacts(complete)
    assert receipt["artifact_root_cid"] == complete[0]["artifact_root_cid"]


@pytest.mark.parametrize(
    "damage",
    [
        "missing_pin",
        "wrong_pin",
        "malformed_json",
        "unknown_field",
        "claimed_authority",
        "unqualified",
        "changed_artifact",
        "missing_artifact",
        "extra_artifact",
        "nonbyte_artifact",
        "oversized_artifact",
    ],
)
def test_previous_cache_and_every_artifact_require_closed_independent_pins_before_execution(
    runtime,
    independent_definitions,
    damage,
):
    cases, preparation, _, _ = independent_definitions
    first = build(runtime, cases, preparation, "first")
    raw = (first[1] / "cache.json").read_bytes()
    old_artifacts = artifacts(first)
    expected_sha = sha(raw)
    if damage == "missing_pin":
        expected_sha = None
    elif damage == "wrong_pin":
        expected_sha = "0" * 64
    elif damage == "malformed_json":
        raw = b'{"schema":'
        expected_sha = sha(raw)
    elif damage in {"unknown_field", "claimed_authority", "unqualified"}:
        saved = cache(first)
        if damage == "unknown_field":
            saved["unsupported_extra"] = "do not ignore"
        elif damage == "claimed_authority":
            saved["admitted"] = True
        else:
            saved["qualified"] = False
        raw = canonical_dag_json_bytes(reseal(saved))
        expected_sha = sha(raw)
    elif damage == "changed_artifact":
        module = next(iter(old_artifacts))
        old_artifacts[module] += b"tampered"
    elif damage == "missing_artifact":
        old_artifacts.pop(next(iter(old_artifacts)))
    elif damage == "extra_artifact":
        old_artifacts["LegalCorpus.Unexpected"] = b"unexpected"
    elif damage == "nonbyte_artifact":
        module = next(iter(old_artifacts))
        old_artifacts[module] = old_artifacts[module].decode()
    elif damage == "oversized_artifact":
        module = next(iter(old_artifacts))
        old_artifacts[module] = b"x" * (runtime[0].MAX_ARTIFACT_BYTES + 1)
    calls = len(runtime[1].calls)
    with pytest.raises((ValueError, TypeError)):
        build(
            runtime,
            cases,
            preparation,
            "refused",
            previous_cache_raw=raw,
            expected_previous_cache_sha256=expected_sha,
            previous_artifacts=old_artifacts,
        )
    assert len(runtime[1].calls) == calls


def test_complete_cached_artifact_population_has_an_aggregate_bound(
    runtime,
    independent_definitions,
    monkeypatch,
):
    cases, preparation, _, _ = independent_definitions
    first = build(runtime, cases, preparation, "first")
    monkeypatch.setattr(
        runtime[0],
        "MAX_ARTIFACT_POPULATION_BYTES",
        sum(len(raw) for raw in artifacts(first).values()) - 1,
    )
    before = len(runtime[1].calls)
    with pytest.raises((ValueError, TypeError)):
        build(runtime, cases, preparation, "refused", previous=first)
    assert len(runtime[1].calls) == before


@pytest.mark.parametrize(
    "damage",
    [
        "recipe",
        "imports",
        "dependency_output",
        "artifact_size",
        "kernel_checked",
        "theorem_evidence",
        "artifact_root",
        "duplicate_module",
        "contract",
    ],
)
def test_resealed_cached_facts_cannot_bypass_source_dependency_or_qualification_checks(
    runtime,
    independent_definitions,
    damage,
):
    cases, preparation, _, _ = independent_definitions
    first = build(runtime, cases, preparation, "first")
    saved = deepcopy(cache(first))
    facts = saved["module_facts"]
    dependent = next(row for row in facts if row["imports"])
    theorem = next(row for row in facts if row["output"]["theorem_axiom_dependencies"])
    if damage == "recipe":
        dependent["recipe"]["source_sha256"] = "0" * 64
    elif damage == "imports":
        dependent["imports"] = []
    elif damage == "dependency_output":
        imported = next(iter(dependent["output"]["import_artifact_sha256"]))
        dependent["output"]["import_artifact_sha256"][imported] = "0" * 64
    elif damage == "artifact_size":
        dependent["output"]["artifact_bytes"] += 1
    elif damage == "kernel_checked":
        dependent["output"]["kernel_checked"] = False
    elif damage == "theorem_evidence":
        theorem["output"]["theorem_axiom_dependencies"] = {}
    elif damage == "artifact_root":
        saved["artifact_root_cid"] = contracts.seal_record({"schema": "authored-other-root/v1"})[
            "record_cid"
        ]
    elif damage == "duplicate_module":
        facts.append(deepcopy(facts[0]))
    elif damage == "contract":
        saved["execution_contract"]["environment"]["LEAN_NUM_THREADS"] = "2"
        saved["execution_contract"] = reseal(saved["execution_contract"])
    raw = canonical_dag_json_bytes(reseal(saved))
    before = len(runtime[1].calls)
    with pytest.raises((ValueError, TypeError)):
        build(
            runtime,
            cases,
            preparation,
            "refused",
            previous_cache_raw=raw,
            expected_previous_cache_sha256=sha(raw),
            previous_artifacts=artifacts(first),
        )
    assert len(runtime[1].calls) == before


@pytest.mark.parametrize("changed", ["compiler", "library"])
def test_changed_compiler_or_native_library_closure_invalidates_every_module(
    runtime,
    independent_definitions,
    changed,
):
    cases, preparation, _, _ = independent_definitions
    first = build(runtime, cases, preparation, "first")
    if changed == "compiler":
        runtime[1].lean.write_bytes(b"\x7fELF-authored-changed-fake-compiler")
    else:
        runtime[1].library_salt = "authored-library-v2"
    before = len(runtime[1].calls)
    second = build(runtime, cases, preparation, "new-toolchain", previous=first)
    assert second[0]["build_passed"] is True
    assert set(second[0]["compiled_modules"]) == set(preparation.to_dict()["expected_modules"])
    assert second[0]["reused_modules"] == []
    assert second[0]["reused_theorems"] == []
    assert len(second[0]["fresh_theorems"]) == 2
    assert len(runtime[1].calls) - before == len(preparation.to_dict()["expected_modules"])
    assert all(artifacts(first)[module] != raw for module, raw in artifacts(second).items())


def test_failed_changed_definition_blocks_its_norm_and_root_without_resurrecting_cached_outputs(
    runtime,
    independent_definitions,
):
    original, preparation, changed, changed_preparation = independent_definitions
    first = build(runtime, original, preparation, "first")
    changed_manifest = changed_preparation.to_dict()
    affected_norm = changed_manifest["norm_bindings"][0]
    runtime[1].fail_module = affected_norm["definition_module"]
    before = len(runtime[1].calls)
    failed = build(runtime, changed, changed_preparation, "failed-A", previous=first)
    receipt = failed[0]
    called = {row["module"] for row in runtime[1].calls[before:]}
    assert affected_norm["definition_module"] in called
    assert affected_norm["module"] not in called
    assert "LegalCorpus" not in called
    assert receipt["build_passed"] is False
    assert receipt["lean_compilation_verified"] is False
    assert receipt["framework_successful"] is False
    assert any(
        item["code"] == "incremental_pass_dependency_failed"
        for item in receipt["framework_diagnostics"]
    )
    assert cache(failed)["qualified"] is False
    assert affected_norm["composition_theorem"] not in receipt["fresh_theorems"]
    assert affected_norm["composition_theorem"] not in receipt["reused_theorems"]
    assert affected_norm["module"] not in artifacts(failed)
    assert "LegalCorpus" not in artifacts(failed)
    assert set(artifacts(failed)) <= set(changed_manifest["expected_modules"])
    runtime[1].fail_module = None
    calls = len(runtime[1].calls)
    with pytest.raises((ValueError, TypeError)):
        build(runtime, changed, changed_preparation, "failed-cache-refused", previous=failed)
    assert len(runtime[1].calls) == calls
