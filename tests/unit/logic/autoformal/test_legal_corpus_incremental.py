"""Incremental custody controls and explicitly admitted installed-Lean cases.

The authored controls use fake compilers. Separate opt-in FOL/TDFOL cases use
the genuine source/review owners and installed Lean on fictional declarations;
neither route supplies reviewed statutory meaning or training authority.
"""

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


# These controls exercise only the parent incremental coordinator. The public
# parent validator and compiler observations are authored substitutes. The real
# provenance helper extracts facts from explicitly authored sealed child files.
# These controls do
# not qualify original source replay, Lean execution, statutory meaning, or any
# training/convergence claim; those require their separately owned evidence.
class AuthoredParentIncrementalCompiler(AuthoredCompiler):
    """Synthetic module artifacts and axiom text; never executes Lean."""

    def __init__(self, directory):
        super().__init__(directory)
        self.axiom_damage = None
        self.cleanup_error = None
        self.cleanup_error_after_calls = 1

    def run(self, runner, request, **kwargs):
        from dataclasses import replace

        assert request.owned_process_observation is True
        source_path = request.argv[-1]
        artifact_path = request.argv[request.argv.index("-o") + 1]
        captures = {path: (raw.encode() if isinstance(raw, str) else raw)
                    for path, raw in request.input_files.items() if not path.endswith("/.keep")}
        assert source_path in captures
        assert all(path == source_path or path.startswith("compiled/") and path.endswith(".olean")
                   for path in captures)
        assert set(request.output_paths) == {artifact_path, *captures}
        result = super().run(runner, replace(request, output_paths=(artifact_path,)), **kwargs)
        result = replace(result, output_files={**result.output_files, **captures})
        self.calls[-1]["captured_paths"] = sorted(captures)
        if self.cleanup_error is not None and len(self.calls) >= self.cleanup_error_after_calls:
            raise self.cleanup_error
        module = self.calls[-1]["module"]
        path = module.replace(".", "/") + ".lean"
        source = request.input_files[path]
        if isinstance(source, bytes):
            source = source.decode()
        names = [module + "." + name for name in re.findall(r"^theorem ([A-Za-z0-9_]+)", source, re.M)]
        stdout = "".join("'" + name + "' does not depend on any axioms\n" for name in names)
        stderr = result.stderr
        if names and self.axiom_damage == "duplicate":
            stdout += "'" + names[0] + "' does not depend on any axioms\n"
        elif names and self.axiom_damage == "stderr_claim":
            stderr, stdout = stdout, ""
        # Authored typed lifecycle shape exercises coordinator validation only;
        # PID 123 and birth tick 1 are synthetic, with no process launched.
        lifecycle = native.process.NativeToolLifecycleObservation(
            parent_pid=os.getpid(), parent_birth_ticks=1,
            leader=native.process.NativeProcessIdentity(
                pid=123, birth_ticks=1, parent_pid=os.getpid(), process_group_id=123, session_id=123),
            observed_descendants=(), leader_reaped=True, descendant_tracking_complete=True,
            group_scan_complete=True, remaining_group_members=(), remaining_tracked_descendants=(),
            readers_started=2, readers_joined=2, stdin_writer_started=0, stdin_writer_joined=0,
            workspace_device=1, workspace_inode=1, workspace_removed=True,
        )
        return replace(result, stdout=stdout, stderr=stderr, native_lifecycle=lifecycle)


def authored_parent_incremental_preparation(*, changed_shared_donor=False,
                                           rename_shared_donor=False, negative_lookup_revision=0):
    """A synthetic three-component DAG, independent of source autoformalization.

    Two components share the same exact donor module. The third has its own
    donor and consumer. Stable names isolate dependency invalidation when the
    first donor's source changes, without making a source-owner validity claim.
    """
    prelude = "LegalCorpusParent.Prelude"
    identities = {}
    identity_records = {}

    def authored_module(role, label):
        record = contracts.seal_record({
            "schema": "authored-parent-role-identity/v1", "role": role, "label": label,
        })
        identity = record["record_cid"]
        module = "LegalCorpusParent." + role.title() + sha(identity.encode())
        identities[module] = identity
        identity_records[module] = record
        return module

    definitions = [
        authored_module("definition", "SharedDonorV2" if rename_shared_donor else "SharedDonor"),
        authored_module("definition", "ConsumerA"),
        authored_module("definition", "ConsumerB"),
        authored_module("definition", "IndependentDonor"),
        authored_module("definition", "IndependentConsumer"),
    ]
    aliases = [authored_module("alias", label) for label in ["A", "B", "Independent"]]
    joints = [authored_module("joint", label) for label in ["A", "B", "Independent"]]
    pairs = [(definitions[0], definitions[1]), (definitions[0], definitions[2]), (definitions[3], definitions[4])]
    imports = {prelude: []}
    files = {prelude.replace(".", "/") + ".lean": "-- Authored coordinator fixture; no Lean execution.\n"}
    for module in definitions:
        imports[module] = [prelude]
        body = "false" if changed_shared_donor and module == definitions[0] else "true"
        files[module.replace(".", "/") + ".lean"] = (
            "import " + prelude + "\nnamespace " + module + "\ndef interpreted : Bool := " + body + "\nend " + module + "\n"
        )
    components = []
    population = []
    for ordinal, (alias, joint, pair) in enumerate(zip(aliases, joints, pairs)):
        imports[alias] = list(pair)
        imports[joint] = [*pair, alias]
        for module, names in [(alias, ["consumer_predicate_iff_donor_body"]),
                              (joint, ["joint_of_components", "joint_matches_original"])]:
            files[module.replace(".", "/") + ".lean"] = (
                "".join("import " + imported + "\n" for imported in imports[module])
                + "namespace " + module + "\n"
                + "".join("theorem " + name + " : True := by trivial\n" for name in names)
                + "end " + module + "\n"
            )
        component_cid = identities[joint]
        original_definitions = [
            {"role": role, "candidate_pin": {"candidate_cid": identities[module]},
             "authored_source_region": {"module": module},
             "authored_interpretation_sha256": sha(files[module.replace(".", "/") + ".lean"].encode())}
            for role, module in zip(["donor", "consumer"], pair)
        ]
        revision = negative_lookup_revision if ordinal < 2 else 0
        binding = contracts.seal_record({
            "schema": "authored-parent-original-input-binding/v1",
            "original_input_commitment_sha256": sha(wire({
                "ordinal": ordinal, "definitions": original_definitions,
                "negative_lookup_revision": revision,
            })),
            "authored_query_partitions": [{"status": "unavailable", "results": [], "revision": revision}],
        })
        child = contracts.seal_record({
            "schema": "authored-parent-retained-child/v1",
            "native_fragments": [
                {"role": role, "module": module,
                 "native": {"schema": "authored-native-fragment/v1", "module": module,
                            "source_sha256": sha(files[module.replace(".", "/") + ".lean"].encode())}}
                for role, module in zip(["donor", "consumer", "alias", "joint"], [*pair, alias, joint])
            ],
            "review_source_binding": {
                "original_definitions": original_definitions,
                "binding_record": identity_records[alias],
                "alias_record": contracts.seal_record({"schema": "authored-parent-alias/v1", "ordinal": ordinal}),
                "scope_binding": contracts.seal_record({"schema": "authored-parent-scope/v1", "ordinal": ordinal}),
            },
            "review_intake_binding": {"component_pin": {"component_cid": component_cid}},
            "review_dependency_manifest": {"authored_negative_lookup_revision": revision},
        })
        child_path, binding_path = f"parent-component-{ordinal:04d}.json", f"parent-input-bindings-{ordinal:04d}.json"
        files[child_path] = canonical_dag_json_bytes(child).decode()
        files[binding_path] = canonical_dag_json_bytes(binding).decode()
        component = {
            "ordinal": ordinal, "component_cid": component_cid,
            "manifest_file": child_path, "manifest_sha256": sha(files[child_path].encode()),
            "input_bindings_file": binding_path, "input_bindings_sha256": sha(files[binding_path].encode()),
            "conditional_theorems": [alias + ".consumer_predicate_iff_donor_body",
                                     joint + ".joint_of_components", joint + ".joint_matches_original"],
            "review_evidence": {"status": "pending", "blockers": ["authored_synthetic_no_review"],
                                "prerequisites_satisfied_under_selected_trust": False},
            "synthetic_negative_lookup_revision": negative_lookup_revision if ordinal < 2 else 0,
        }
        components.append(component)
        population.append({"component_cid": component_cid, "assessment_file_sha256": sha(wire(component))})
    imports["LegalCorpusParent"] = sorted(joints)
    files["LegalCorpusParent.lean"] = "".join("import " + module + "\n" for module in sorted(joints))
    files["lakefile.toml"] = 'name = "authored_parent_incremental"\n'
    files["lean-toolchain"] = TOOLCHAIN + "\n"
    ordered = [prelude, *definitions, *aliases, *joints, "LegalCorpusParent"]
    manifest = contracts.seal_record({
        "schema": shared.PARENT_SCHEMA, "profile": shared.PARENT_PROFILE, "toolchain": TOOLCHAIN,
        "population": population, "components": components, "expected_modules": ordered,
        "module_imports": imports,
        "module_bindings": [{"module": module, "module_path": module.replace(".", "/") + ".lean",
                             "synthetic_identity": identities[module],
                             "module_sha256": sha(files[module.replace(".", "/") + ".lean"].encode()),
                             "contributors": [row["ordinal"] for row in components
                                              if module in pairs[row["ordinal"]]
                                              or module in [aliases[row["ordinal"]], joints[row["ordinal"]]]]}
                            for module in ordered if module not in [prelude, "LegalCorpusParent"]],
        "definition_modules": [], "file_sha256": {path: sha(body.encode()) for path, body in files.items()},
        "input_commitment_sha256": sha(wire({"synthetic_population": population,
                                             "changed_shared_donor": changed_shared_donor,
                                             "renamed_shared_donor": rename_shared_donor,
                                             "negative_lookup_revision": negative_lookup_revision})),
        "producer_pins": shared._parent_shared_pins(),
        "native_producer_pins": shared.parent_owner._owners()[0].producer_pins(), "preparation_only": True,
        "lean_compilation_status": "not_run", "proof_status": "pending",
        "theorem_assumptions": ["Synthetic coordinator fixture; no reviewed source or native proof."],
        "child_file_policy": {}, **shared.PARENT_FALSE_FLAGS,
    })
    preparation = shared.ParentSharedCorpusPreparation(
        canonical_dag_json_bytes(manifest).decode(), tuple(sorted(files.items()))
    )
    inputs = [{"synthetic_component_ordinal": row["ordinal"]} for row in components]
    return inputs, preparation, {
        "shared_donor": definitions[0], "affected_aliases": aliases[:2], "affected_joints": joints[:2],
        "unrelated": {prelude, definitions[3], definitions[4], aliases[2], joints[2]},
        "unchanged_consumers": {definitions[1], definitions[2]},
    }


@pytest.fixture
def authored_parent_incremental_runtime(monkeypatch, tmp_path):
    """No original parent source replay or actual compiler is invoked here."""
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_native_v2 as parent_native
    from ipfs_datasets_py.logic.autoformal import legal_corpus_incremental as incremental

    compiler = AuthoredParentIncrementalCompiler(tmp_path)
    control = {"incremental": incremental, "parent_native": parent_native,
               "compiler": compiler, "directory": tmp_path, "replays": [],
               "fail_replay_at": None, "failure_kind": None, "mutation_target": None}

    def synthetic_public_replay(preparation, *, component_inputs, expected_population,
                                expected_preparation_sha256, toolchain):
        control["replays"].append({"pin": expected_preparation_sha256,
                                    "population": deepcopy(expected_population)})
        assert toolchain == TOOLCHAIN
        assert expected_preparation_sha256 == parent_native.parent_shared_preparation_sha256(preparation)
        assert expected_population == preparation.to_dict()["population"]
        assert len(component_inputs) == len(expected_population) == 3
        if len(control["replays"]) == control["fail_replay_at"]:
            if control["mutation_target"] is not None:
                assert preparation is control["mutation_target"], "closing replay must use the original caller"
                files = list(preparation.files)
                path, body = files[0]
                files[0] = (path, body + "-- Authored caller mutation during closing refusal.\n")
                object.__setattr__(preparation, "files", tuple(files))
            raise ValueError("authored warm " + control["failure_kind"] + " replay refusal")
        return preparation

    monkeypatch.setattr(parent_native, "validate_parent_shared_definition_use_native_v1", synthetic_public_replay)
    monkeypatch.setattr(native.shared, "_installed_toolchain", compiler.installed)
    monkeypatch.setattr(incremental, "_toolchain_closure", compiler.closure)
    monkeypatch.setattr(native.process.BoundedToolRunner, "run",
                        lambda runner, request, **kwargs: compiler.run(runner, request, **kwargs))
    return control


def build_authored_parent_incremental(control, inputs, preparation, name, *, previous=None, **options):
    arguments = {
        "component_inputs": inputs, "expected_population": preparation.to_dict()["population"],
        "expected_preparation_sha256": control["parent_native"].parent_shared_preparation_sha256(preparation),
        "toolchain": TOOLCHAIN, "lake_executable": str(control["compiler"].lake),
        "operation_timeout_seconds": 3600,
        "output_directory": control["directory"] / name,
    }
    if previous is not None:
        old_receipt, old_directory = previous
        raw = (old_directory / "cache.json").read_bytes()
        arguments.update(previous_cache_raw=raw, expected_previous_cache_sha256=sha(raw),
                         previous_artifacts={module: (old_directory / path).read_bytes()
                                             for module, path in old_receipt["artifact_files"].items()})
    arguments.update(options)
    result = control["incremental"].build_incremental_parent_shared_corpus_v1(preparation, **arguments)
    return result, control["directory"] / name


def test_authored_parent_incremental_cold_and_warm_zero_compile_preserve_conditional_scope(
    authored_parent_incremental_runtime,
):
    control = authored_parent_incremental_runtime
    inputs, preparation, _ = authored_parent_incremental_preparation()
    cold = build_authored_parent_incremental(control, inputs, preparation, "parent-cold")
    expected = set(preparation.to_dict()["expected_modules"])
    assert cold[0]["build_passed"] is True
    assert set(cold[0]["compiled_modules"]) == expected and cold[0]["reused_modules"] == []
    assert len(control["compiler"].calls) == len(expected) == 13
    assert len(control["replays"]) >= 2
    replays_before, calls_before = len(control["replays"]), len(control["compiler"].calls)
    warm = build_authored_parent_incremental(control, inputs, preparation, "parent-warm", previous=cold)
    assert warm[0]["build_passed"] is True
    assert warm[0]["compiled_modules"] == [] and set(warm[0]["reused_modules"]) == expected
    assert warm[0]["module_compile_invocations"] == 0 and warm[0]["backend_executed"] is False
    assert len(control["compiler"].calls) == calls_before
    assert len(control["replays"]) >= replays_before + 2
    assert artifacts(warm) == artifacts(cold)
    assert cache(warm)["profile"] != control["incremental"].PROFILE
    assert len(warm[0]["reused_theorems"]) == 9 and warm[0]["fresh_theorems"] == []
    for result in [cold, warm]:
        assert result[0]["components"] == preparation.to_dict()["components"]
        for record in [result[0], cache(result)]:
            for flag in ["source_authenticity_verified", "source_semantics_verified", "admitted",
                         "proof_authority", "training_qualified", "training_gold_qualified"]:
                assert record[flag] is False
        assert all(raw.startswith(b"authored-fake-olean-no-native-proof\0") for raw in artifacts(result).values())


def test_authored_parent_incremental_shared_donor_invalidates_both_users_and_matches_clean(
    authored_parent_incremental_runtime,
):
    control = authored_parent_incremental_runtime
    inputs, preparation, roles = authored_parent_incremental_preparation()
    cold = build_authored_parent_incremental(control, inputs, preparation, "parent-before")
    changed_inputs, changed, changed_roles = authored_parent_incremental_preparation(changed_shared_donor=True)
    assert roles == changed_roles
    before = len(control["compiler"].calls)
    partial = build_authored_parent_incremental(control, changed_inputs, changed, "parent-partial", previous=cold)
    affected = {roles["shared_donor"], *roles["affected_aliases"], *roles["affected_joints"], "LegalCorpusParent"}
    reused = roles["unrelated"] | roles["unchanged_consumers"]
    assert partial[0]["build_passed"] is True
    assert set(partial[0]["compiled_modules"]) == affected
    assert set(partial[0]["reused_modules"]) == reused
    assert {r["module"] for r in control["compiler"].calls[before:]} == affected
    assert len(partial[0]["fresh_theorems"]) == 6 and len(partial[0]["reused_theorems"]) == 3
    complete = build_authored_parent_incremental(control, changed_inputs, changed, "parent-clean")
    assert artifacts(partial) == artifacts(complete)
    assert partial[0]["artifact_root_cid"] == complete[0]["artifact_root_cid"]
    for module in reused:
        assert artifacts(partial)[module] == artifacts(cold)[module]


def test_authored_parent_incremental_content_identity_change_removes_old_donor_and_matches_clean(
    authored_parent_incremental_runtime,
):
    control = authored_parent_incremental_runtime
    inputs, preparation, original_roles = authored_parent_incremental_preparation()
    first = build_authored_parent_incremental(control, inputs, preparation, "parent-identity-before")
    changed_inputs, changed, roles = authored_parent_incremental_preparation(
        changed_shared_donor=True, rename_shared_donor=True)
    assert roles["shared_donor"] != original_roles["shared_donor"]
    partial = build_authored_parent_incremental(control, changed_inputs, changed, "parent-identity-after", previous=first)
    expected_changed = {roles["shared_donor"], *roles["affected_aliases"], *roles["affected_joints"], "LegalCorpusParent"}
    assert partial[0]["build_passed"] is True
    assert set(partial[0]["compiled_modules"]) == expected_changed
    assert set(partial[0]["reused_modules"]) == roles["unrelated"] | roles["unchanged_consumers"]
    assert original_roles["shared_donor"] not in artifacts(partial)
    assert original_roles["shared_donor"] not in {row["module"] for row in cache(partial)["module_facts"]}
    complete = build_authored_parent_incremental(control, changed_inputs, changed, "parent-identity-clean")
    assert artifacts(partial) == artifacts(complete)
    assert partial[0]["artifact_root_cid"] == complete[0]["artifact_root_cid"]


def test_authored_parent_incremental_negative_lookup_changes_bindings_without_Lean_text_change(
    authored_parent_incremental_runtime,
):
    control = authored_parent_incremental_runtime
    inputs, preparation, roles = authored_parent_incremental_preparation()
    first = build_authored_parent_incremental(control, inputs, preparation, "parent-lookup-before")
    changed_inputs, changed, changed_roles = authored_parent_incremental_preparation(negative_lookup_revision=1)
    assert changed_roles == roles
    assert {p: body for p, body in preparation.files if p.endswith(".lean")} == {
        p: body for p, body in changed.files if p.endswith(".lean")}
    partial = build_authored_parent_incremental(control, changed_inputs, changed, "parent-lookup-after", previous=first)
    affected = {*roles["affected_aliases"], *roles["affected_joints"], "LegalCorpusParent"}
    expected = set(changed.to_dict()["expected_modules"])
    assert partial[0]["build_passed"] is True
    assert set(partial[0]["compiled_modules"]) == affected
    assert set(partial[0]["reused_modules"]) == expected - affected
    prior_facts = {row["module"]: row for row in cache(first)["module_facts"]}
    current_facts = {row["module"]: row for row in cache(partial)["module_facts"]}
    for module in [*roles["affected_aliases"], *roles["affected_joints"]]:
        assert prior_facts[module]["recipe"]["provenance"]["input_binding_sha256s"] != \
            current_facts[module]["recipe"]["provenance"]["input_binding_sha256s"]
    complete = build_authored_parent_incremental(control, changed_inputs, changed, "parent-lookup-clean")
    assert artifacts(partial) == artifacts(complete)
    assert partial[0]["artifact_root_cid"] == complete[0]["artifact_root_cid"]


def test_authored_parent_incremental_failed_donor_drops_stale_users_but_retains_independent_branch(
    authored_parent_incremental_runtime,
):
    control = authored_parent_incremental_runtime
    inputs, preparation, roles = authored_parent_incremental_preparation()
    first = build_authored_parent_incremental(control, inputs, preparation, "parent-failure-before")
    changed_inputs, changed, _ = authored_parent_incremental_preparation(changed_shared_donor=True)
    control["compiler"].fail_module = roles["shared_donor"]
    before = len(control["compiler"].calls)
    failed = build_authored_parent_incremental(control, changed_inputs, changed, "parent-failure-after", previous=first)
    affected = {roles["shared_donor"], *roles["affected_aliases"], *roles["affected_joints"], "LegalCorpusParent"}
    called = {row["module"] for row in control["compiler"].calls[before:]}
    assert roles["shared_donor"] in called and not ((affected - {roles["shared_donor"]}) & called)
    assert failed[0]["build_passed"] is False and failed[0]["lean_compilation_verified"] is False
    assert cache(failed)["qualified"] is False
    assert not (affected & set(artifacts(failed)))
    assert roles["unrelated"] <= set(artifacts(failed))
    for module in roles["unrelated"]:
        assert artifacts(failed)[module] == artifacts(first)[module]


@pytest.mark.parametrize("changed", ["compiler", "library"])
def test_authored_parent_incremental_toolchain_closure_change_rebuilds_every_module(
    authored_parent_incremental_runtime, changed,
):
    control = authored_parent_incremental_runtime
    inputs, preparation, _ = authored_parent_incremental_preparation()
    first = build_authored_parent_incremental(control, inputs, preparation, "parent-first")
    if changed == "compiler":
        control["compiler"].lean.write_bytes(b"\x7fELF-authored-parent-compiler-v2")
    else:
        control["compiler"].library_salt = "authored-parent-library-v2"
    before = len(control["compiler"].calls)
    second = build_authored_parent_incremental(control, inputs, preparation, "parent-new-toolchain", previous=first)
    assert second[0]["build_passed"] is True and second[0]["reused_modules"] == []
    assert set(second[0]["compiled_modules"]) == set(preparation.to_dict()["expected_modules"])
    assert len(control["compiler"].calls) - before == 13
    assert second[0]["reused_theorems"] == [] and len(second[0]["fresh_theorems"]) == 9


@pytest.mark.parametrize("damage", ["cross_profile", "wrong_pin", "missing_artifact", "resealed_imports", "claimed_authority"])
def test_authored_parent_incremental_prior_cache_refuses_profile_pin_and_fact_forgery(
    authored_parent_incremental_runtime, damage,
):
    control = authored_parent_incremental_runtime
    inputs, preparation, _ = authored_parent_incremental_preparation()
    first = build_authored_parent_incremental(control, inputs, preparation, "parent-cache-before")
    saved = deepcopy(cache(first))
    offered_artifacts = artifacts(first)
    if damage == "cross_profile":
        saved["profile"] = control["incremental"].PROFILE
    elif damage == "missing_artifact":
        offered_artifacts.pop(next(iter(offered_artifacts)))
    elif damage == "resealed_imports":
        next(row for row in saved["module_facts"] if row["imports"])["imports"] = []
    elif damage == "claimed_authority":
        saved["admitted"] = True
    raw = canonical_dag_json_bytes(reseal(saved))
    pin = "0" * 64 if damage == "wrong_pin" else sha(raw)
    before = len(control["compiler"].calls)
    with pytest.raises((ValueError, TypeError)):
        build_authored_parent_incremental(control, inputs, preparation, "parent-cache-refused",
                                         previous_cache_raw=raw, expected_previous_cache_sha256=pin,
                                         previous_artifacts=offered_artifacts)
    assert len(control["compiler"].calls) == before


@pytest.mark.parametrize(
    "failure_kind,fence",
    [("physical", "opening"), ("review", "opening"), ("physical", "closing"), ("review", "closing")],
    ids=["opening-physical", "opening-review", "closing-physical", "closing-review"],
)
def test_authored_parent_incremental_warm_cache_still_obeys_full_public_replay_refusal(
    authored_parent_incremental_runtime, failure_kind, fence,
):
    control = authored_parent_incremental_runtime
    inputs, preparation, _ = authored_parent_incremental_preparation()
    first = build_authored_parent_incremental(control, inputs, preparation, "parent-replay-before")
    before = len(control["compiler"].calls)
    replay_before = len(control["replays"])
    before_files, before_manifest = dict(preparation.files), preparation.to_dict()
    control["fail_replay_at"] = replay_before + (1 if fence == "opening" else 2)
    control["failure_kind"] = failure_kind
    if (failure_kind, fence) == ("physical", "closing"):
        control["mutation_target"] = preparation
    try:
        refused = build_authored_parent_incremental(control, inputs, preparation, "parent-replay-refused", previous=first)
    except ValueError as error:
        assert fence == "opening"
        assert "authored warm " + failure_kind + " replay refusal" in str(error)
    else:
        assert fence == "closing"
        assert refused[0]["build_passed"] is False
        assert refused[0]["lean_compilation_verified"] is False
        assert cache(refused)["qualified"] is False
        assert failure_kind in str(refused[0]["post_run_validation_error"])
        if failure_kind == "physical":
            assert dict(preparation.files) != before_files
            for path, body in before_files.items():
                assert (refused[1] / "project" / path).read_text() == body
            assert json.loads((refused[1] / "project/corpus-manifest.json").read_bytes()) == before_manifest
    assert len(control["compiler"].calls) == before
    assert len(control["replays"]) == control["fail_replay_at"]


@pytest.mark.parametrize("damage", ["duplicate", "stderr_claim"])
def test_authored_parent_incremental_requires_exact_stdout_axiom_observations(
    authored_parent_incremental_runtime, damage,
):
    control = authored_parent_incremental_runtime
    inputs, preparation, roles = authored_parent_incremental_preparation()
    control["compiler"].axiom_damage = damage
    result = build_authored_parent_incremental(control, inputs, preparation, "parent-bad-axiom")
    called = {r["module"] for r in control["compiler"].calls}
    assert result[0]["build_passed"] is False
    assert result[0]["lean_compilation_verified"] is False
    assert cache(result)["qualified"] is False
    assert "LegalCorpusParent" not in called
    assert not (set(roles["affected_joints"]) & called)
    assert result[0]["fresh_theorems"] == []


def test_authored_parent_incremental_cleanup_error_retains_original_handle_and_stops_dispatch(
    authored_parent_incremental_runtime, monkeypatch,
):
    control = authored_parent_incremental_runtime
    inputs, preparation, _ = authored_parent_incremental_preparation()
    handle = object()  # Authored handle identity only; no actual live native process.
    original = native.process.OwnedToolCleanupError(handle, "authored parent cleanup unresolved")
    control["compiler"].cleanup_error = original
    control["compiler"].cleanup_error_after_calls = 2
    original_framework_run = control["incremental"]._run

    def framework_shutdown_error_after_real_callbacks(*args, **kwargs):
        original_framework_run(*args, **kwargs)
        raise RuntimeError("authored secondary framework shutdown failure")

    monkeypatch.setattr(control["incremental"], "_run", framework_shutdown_error_after_real_callbacks)
    with pytest.raises(native.process.OwnedToolCleanupError) as caught:
        build_authored_parent_incremental(control, inputs, preparation, "parent-unresolved-cleanup")
    assert caught.value is original and caught.value.cleanup_handle is handle
    assert len(control["compiler"].calls) == 2
    assert control["compiler"].calls[0]["module"] == "LegalCorpusParent.Prelude"
    assert control["compiler"].calls[1]["module"].startswith("LegalCorpusParent.Definition")
    assert not (control["directory"] / "parent-unresolved-cleanup/cache.json").exists()


def test_authored_parent_incremental_retained_artifact_drift_refuses_cache_and_receipt_publication(
    authored_parent_incremental_runtime, monkeypatch,
):
    control = authored_parent_incremental_runtime
    inputs, preparation, _ = authored_parent_incremental_preparation()
    original_write = shared._write_compiled
    mutated_paths = []

    def write_then_mutate_retained_artifact(directory, artifact_bytes):
        original_write(directory, artifact_bytes)
        assert len(artifact_bytes) == 13
        path = directory / next(iter(artifact_bytes))
        path.write_bytes(path.read_bytes() + b"authored retained artifact drift")
        mutated_paths.append(path)

    monkeypatch.setattr(shared, "_write_compiled", write_then_mutate_retained_artifact)
    with pytest.raises(ValueError):
        build_authored_parent_incremental(control, inputs, preparation, "parent-publication-refused")
    assert len(mutated_paths) == 1 and mutated_paths[0].is_file()
    assert len(control["compiler"].calls) == 13
    output = control["directory"] / "parent-publication-refused"
    assert not (output / "cache.json").exists()
    assert not (output / "build-receipt.json").exists()


@pytest.fixture(scope="module")
def installed_incremental_parent_lake():
    # Preserve the existing explicit binary opt-in before expensive source
    # construction. No validator, probe, closure or compiler is substituted.
    spec = importlib.util.spec_from_file_location(
        "installed_incremental_parent_native_fixture",
        Path(__file__).with_name("test_plaintext_definition_use_native.py"),
    )
    assert spec is not None and spec.loader is not None
    support = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(support)
    executable, pins = support.installed_parent_lake.__wrapped__()
    return support.shared_native_support.__wrapped__(), executable, pins


def pending_incremental_parent_example(support, path, family, *, donor_body_op=None):
    path.mkdir(parents=True, exist_ok=True)
    example = support.shared_fixture.parent_shared_family_examples(
        path, family, donor_body_op=donor_body_op)
    for index, case in enumerate(example["cases"]):
        signed = case["signed"]
        signed["registry"]["mode"] = signed["policy"]["mode"] = "unavailable"
        signed["registry"]["keys"], signed["reviews"], signed["evidence"] = [], [], {}
        example["support"].signing.refresh(signed)
        example["cases"][index] = example["lake"].refresh_assessment(
            example["support"], signed)
    return example


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_parent_incremental_installed_lean_cold_warm_affected_matches_clean(
        installed_incremental_parent_lake, tmp_path, family):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_incremental as incremental

    support, executable, binary_pins = installed_incremental_parent_lake
    source = tmp_path / "originals"
    original = pending_incremental_parent_example(support, source, family)
    source_bytes = {str(path.relative_to(source)): path.read_bytes()
                    for path in source.rglob("*") if path.is_file()}
    assert source_bytes
    changed = pending_incremental_parent_example(support, source, family, donor_body_op="any")
    assert source_bytes == {str(path.relative_to(source)): path.read_bytes()
                            for path in source.rglob("*") if path.is_file()}
    independent = pending_incremental_parent_example(
        support, tmp_path / "independent-originals", family)
    original_cases = [*original["cases"], independent["cases"][0]]
    changed_cases = [*changed["cases"], independent["cases"][0]]
    # A different interpretation preserves both original physical consumers.
    for first, second in zip(original["cases"], changed["cases"]):
        before = first["signed"]["component"]["case"]
        after = second["signed"]["component"]["case"]
        assert before["consumer"] == after["consumer"]
        assert before["donor"]["candidate"]["source_version"] == after["donor"]["candidate"]["source_version"]
        assert before["donor"]["candidate"]["ast_record"] != after["donor"]["candidate"]["ast_record"]
    arguments = support.shared_fixture.parent_shared_arguments(original_cases)
    changed_arguments = support.shared_fixture.parent_shared_arguments(changed_cases)
    preparation = shared.prepare_parent_shared_definition_use_corpus_v1(**arguments)
    changed_preparation = shared.prepare_parent_shared_definition_use_corpus_v1(**changed_arguments)
    manifest, changed_manifest = preparation.to_dict(), changed_preparation.to_dict()
    assert len(manifest["components"]) == len(changed_manifest["components"]) == 3
    assert len(manifest["expected_modules"]) == len(changed_manifest["expected_modules"]) == 13
    definition = support.shared_fixture.parent_shared_definition
    old_donor = definition(manifest, 0, "donor")["module"]
    new_donor = definition(changed_manifest, 0, "donor")["module"]
    assert old_donor == definition(manifest, 1, "donor")["module"]
    assert new_donor == definition(changed_manifest, 1, "donor")["module"]
    assert old_donor != new_donor and old_donor not in changed_manifest["expected_modules"]
    isolated_joint = manifest["components"][2]["joint_module"]
    isolated = {isolated_joint, *manifest["module_imports"][isolated_joint]}
    assert len(isolated) == 4
    consumers = {definition(manifest, index, "consumer")["module"] for index in (0, 1)}
    assert len(consumers) == 2 and not isolated & (consumers | {old_donor, new_donor})
    expected_reused = {"LegalCorpusParent.Prelude", *consumers, *isolated}
    assert len(expected_reused) == 7
    original_inputs = deepcopy(arguments), deepcopy(changed_arguments)
    original_projects = preparation.manifest_json, preparation.files, changed_preparation.manifest_json, changed_preparation.files
    physical = {path: path.read_bytes() for root in (source, tmp_path / "independent-originals")
                for path in root.rglob("*") if path.is_file()}

    def run(name, offered, inputs, *, previous=None):
        output = tmp_path / name
        previous_inputs = {}
        if previous is not None:
            raw = (previous[1] / "cache.json").read_bytes()
            previous_inputs = dict(previous_cache_raw=raw,
                expected_previous_cache_sha256=sha(raw), previous_artifacts=artifacts(previous))
        receipt = incremental.build_incremental_parent_shared_corpus_v1(offered,
            **inputs, expected_preparation_sha256=incremental._parent_native().parent_shared_preparation_sha256(offered),
            lake_executable=str(executable), output_directory=output, timeout_seconds=60,
            operation_timeout_seconds=3600, **previous_inputs)
        assert receipt["build_passed"] is receipt["lean_compilation_verified"] is True
        assert receipt["framework_successful"] is True and receipt["post_run_validation_error"] is None
        current = offered.to_dict()
        assert receipt["population"] == current["population"] and receipt["components"] == current["components"]
        assert len(receipt["components"]) == 3 and len(receipt["artifact_sha256"]) == 13
        assert set(receipt["compiled_modules"]) | set(receipt["reused_modules"]) == set(current["expected_modules"])
        assert not set(receipt["compiled_modules"]) & set(receipt["reused_modules"])
        for component in receipt["components"]:
            assert component["review_evidence"]["status"] == "pending"
            assert component["review_evidence"]["blockers"]
            assert component["review_evidence"]["prerequisites_satisfied_under_selected_trust"] is False
            assert component["theorem_assumptions"]
        for flag in incremental._parent_flags():
            assert receipt[flag] is False
        saved = cache((receipt, output))
        assert saved["qualified"] is True and saved["profile"] == incremental.PARENT_PROFILE
        contract = saved["execution_contract"]
        assert contract["binary_sha256"] == binary_pins
        assert contract["toolchain_closure"]["file_count"] > 0
        assert contract["toolchain_closure"]["file_bytes"] > 0
        assert set(receipt["version_probes"]) == {"lake", "lean"}
        for binary, probe in receipt["version_probes"].items():
            assert probe["command"] == [str(executable.parent / binary), "--version"]
            assert probe["returncode"] == 0 and "4.34.1" in probe["stdout"]
        observed_raw = (output / "module-executions.jsonl").read_bytes()
        assert sha(observed_raw) == receipt["execution_observations"]["sha256"]
        assert len(observed_raw) == receipt["execution_observations"]["bytes"]
        observations = [json.loads(line) for line in observed_raw.splitlines()]
        assert [row["module"] for row in observations] == receipt["compiled_modules"]
        assert len(observations) == receipt["module_compile_invocations"]
        for row in observations:
            assert row["runtime"] == "native" and row["returncode"] == 0 and row["pid"] > 0
            assert row["command"][0] == str(executable.parent / "lean")
            assert row["workspace_cleaned"] is True and not row["error"]
            assert row["native_lifecycle"]["cleanup_confirmed"] is True
            assert row["native_lifecycle"]["kernel_containment_attested"] is False
        for row in saved["module_facts"]:
            assert row["output"]["kernel_checked"] is True
            assert row["output"]["execution_evidence"]["native_lifecycle"]["cleanup_confirmed"] is True
        for module, raw in artifacts((receipt, output)).items():
            assert raw and sha(raw) == receipt["artifact_sha256"][module]
            assert not raw.startswith(b"authored-fake-")
        assert json.loads((output / "build-receipt.json").read_bytes()) == receipt
        assert (output / "project/corpus-manifest.json").read_bytes() == offered.manifest_json.encode()
        for filename, body in offered.files:
            assert (output / "project" / filename).read_bytes() == body.encode()
        expected_files = ({"project/" + filename for filename, _ in offered.files}
            | {"project/corpus-manifest.json"} | set(receipt["artifact_files"].values())
            | {"cache.json", "toolchain-closure.jsonl", "module-executions.jsonl", "build-receipt.json"})
        assert {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()} == expected_files
        assert not any(path.is_symlink() for path in output.rglob("*"))
        assert all(path.read_bytes() == raw for path, raw in physical.items())
        return receipt, output

    cold = run("installed-parent-cold", preparation, arguments)
    assert len(cold[0]["compiled_modules"]) == 13 and cold[0]["reused_modules"] == []
    assert len(cold[0]["fresh_theorems"]) == 9 and cold[0]["reused_theorems"] == []
    warm = run("installed-parent-warm", preparation, arguments, previous=cold)
    assert warm[0]["compiled_modules"] == warm[0]["fresh_theorems"] == []
    assert warm[0]["module_compile_invocations"] == 0 and warm[0]["backend_executed"] is False
    assert set(warm[0]["reused_modules"]) == set(manifest["expected_modules"])
    assert len(warm[0]["reused_theorems"]) == 9
    assert artifacts(warm) == artifacts(cold)
    affected = run("installed-parent-affected", changed_preparation, changed_arguments, previous=warm)
    assert set(affected[0]["reused_modules"]) == expected_reused
    assert set(affected[0]["compiled_modules"]) == set(changed_manifest["expected_modules"]) - expected_reused
    assert len(affected[0]["compiled_modules"]) == 6
    assert len(affected[0]["fresh_theorems"]) == 6 and len(affected[0]["reused_theorems"]) == 3
    assert old_donor not in artifacts(affected)
    for module in expected_reused:
        assert artifacts(affected)[module] == artifacts(cold)[module]
    clean = run("installed-parent-clean", changed_preparation, changed_arguments)
    assert len(clean[0]["compiled_modules"]) == 13 and clean[0]["reused_modules"] == []
    assert len(clean[0]["fresh_theorems"]) == 9 and clean[0]["reused_theorems"] == []
    assert artifacts(affected) == artifacts(clean)
    assert affected[0]["artifact_root_cid"] == clean[0]["artifact_root_cid"]
    assert original_inputs == (arguments, changed_arguments)
    assert original_projects == (preparation.manifest_json, preparation.files,
                                 changed_preparation.manifest_json, changed_preparation.files)
    # Every stage retains separate original receipts; this test does not merge
    # reused theorem observations into a fresh-proof count or legal authority.


# These two incremental-specific refusal controls use genuine original-source
# and signed-review owners. Only compiler/probe/library observations are
# authored substitutes. They add no actual Lean or statutory-meaning result.
@pytest.fixture(scope="module")
def genuine_parent_incremental_refusal_setup(tmp_path_factory):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_native_v2 as parent_native
    from ipfs_datasets_py.logic.autoformal import legal_corpus_incremental as incremental

    def forbidden_subprocess(*args, **kwargs):
        pytest.fail("genuine replay refusal controls cannot execute a native process or compiler")

    with pytest.MonkeyPatch.context() as patches:
        patches.setattr(subprocess, "run", forbidden_subprocess)
        patches.setattr(subprocess, "Popen", forbidden_subprocess)
        directory = tmp_path_factory.mktemp("genuine-parent-incremental-refusals", numbered=False)
        originals = directory / "originals"
        originals.mkdir()
        lake = _FIXTURE_MODULE.parent_shared_fixture_module()
        support = lake.support.__wrapped__()
        data = lake.make_data(support, originals, family="fol")
        arguments = _FIXTURE_MODULE.parent_shared_arguments([data])
        preparation = shared.prepare_parent_shared_definition_use_corpus_v1(**arguments)
        manifest = preparation.to_dict()
        assert len(manifest["components"]) == 1 and len(manifest["expected_modules"]) == 6
        assert data["assessment"]["review_prerequisites_satisfied_under_selected_trust"] is True
        assert data["assessment"]["evidence_assessment_status"] == "authenticated"
        # The real signatures are freshly generated test credentials, not supplied
        # human identities or a legal endorsement of these fictional declarations.
        assert data["review_inputs"]["registry"]["mode"] == "external_pinned_trust"
        assert len(data["review_inputs"]["reviews"]) == len(data["review_inputs"]["registry"]["keys"]) == 2
        compiler = AuthoredParentIncrementalCompiler(directory)
        installed_calls = []

        def authored_installed(*args, **kwargs):
            installed_calls.append(True)
            return compiler.installed(*args, **kwargs)
        patches.setattr(native.shared, "_installed_toolchain", authored_installed)
        patches.setattr(incremental, "_toolchain_closure", compiler.closure)
        patches.setattr(native.process.BoundedToolRunner, "run",
                        lambda runner, request, **kwargs: compiler.run(runner, request, **kwargs))
        output = directory / "authored-cold-cache-genuine-sources"
        receipt = incremental.build_incremental_parent_shared_corpus_v1(preparation,
            **arguments, expected_preparation_sha256=parent_native.parent_shared_preparation_sha256(preparation),
            lake_executable=str(compiler.lake), output_directory=output,
            timeout_seconds=60, operation_timeout_seconds=3600)
        baseline = receipt, output
        assert receipt["build_passed"] is True and cache(baseline)["qualified"] is True
        assert len(compiler.calls) == receipt["module_compile_invocations"] == 6
        assert len(installed_calls) == 1
        assert all(raw.startswith(b"authored-fake-olean-no-native-proof\0") for raw in artifacts(baseline).values())
        assert receipt["components"] == manifest["components"]
        for record in (receipt, cache(baseline)):
            assert all(record[key] is False for key in incremental._parent_flags())
        control = {"incremental": incremental, "parent_native": parent_native,
            "directory": directory, "originals": originals, "lake": lake, "support": support,
            "data": data, "arguments": arguments, "preparation": preparation,
            "compiler": compiler, "installed_calls": installed_calls, "baseline": baseline,
            "lake_executable": str(compiler.lake),
            "runtime_counts": lambda: (len(compiler.calls), len(installed_calls)),
            "expected_warm_runtime_delta": (0, 1),
            "authored_installed": authored_installed, "forbidden_subprocess": forbidden_subprocess}
    # The expensive module-cached cold data outlives this context. Its fake
    # process hooks do not: later installed-Lean tests must see genuine owners.
    return control


@pytest.fixture
def genuine_parent_incremental_refusal_runtime(genuine_parent_incremental_refusal_setup, monkeypatch):
    control = genuine_parent_incremental_refusal_setup
    compiler = control["compiler"]
    monkeypatch.setattr(subprocess, "run", control["forbidden_subprocess"])
    monkeypatch.setattr(subprocess, "Popen", control["forbidden_subprocess"])
    monkeypatch.setattr(native.shared, "_installed_toolchain", control["authored_installed"])
    monkeypatch.setattr(control["incremental"], "_toolchain_closure", compiler.closure)
    monkeypatch.setattr(native.process.BoundedToolRunner, "run",
                        lambda runner, request, **kwargs: compiler.run(runner, request, **kwargs))
    return control


def genuine_parent_refusal_warm_arguments(control, *, component_inputs=None):
    previous_raw = (control["baseline"][1] / "cache.json").read_bytes()
    inputs = dict(control["arguments"])
    if component_inputs is not None:
        inputs["component_inputs"] = component_inputs
    return dict(inputs,
        expected_preparation_sha256=control["parent_native"].parent_shared_preparation_sha256(control["preparation"]),
        lake_executable=control["lake_executable"], timeout_seconds=60, operation_timeout_seconds=3600,
        previous_cache_raw=previous_raw, expected_previous_cache_sha256=sha(previous_raw),
        previous_artifacts=artifacts(control["baseline"]))


def assert_parent_incremental_physical_drift_warm_refusal(control, monkeypatch):
    preparation, arguments = control["preparation"], control["arguments"]
    descriptor = arguments["component_inputs"][0]["review_inputs"]["use_inputs"][
        "donor_evidence_inputs"]["parent_inputs"]["replay_inputs"][
        "parent_text_views_inputs"]["parent_descriptor"]
    physical = Path(descriptor["local_path"])
    assert physical.is_relative_to(control["originals"]) and not physical.is_symlink()
    original_bytes = physical.read_bytes()
    assert original_bytes and sha(original_bytes) == descriptor["sha256"]
    frozen_files, frozen_manifest = tuple(preparation.files), preparation.manifest_json
    before_inputs = deepcopy(arguments)
    before_counts = control["runtime_counts"]()
    baseline_raw = (control["baseline"][1] / "cache.json").read_bytes()
    baseline_artifacts = artifacts(control["baseline"])
    original_validate = control["parent_native"].validate_parent_shared_definition_use_native_v1
    real_calls, mutated = [], []

    def observe_real_validation(offered, **kwargs):
        entry = {"offered_is_original": offered is preparation, "passed": False}
        real_calls.append(entry)
        if len(real_calls) == 2:
            # Opening replay and the framework's warm reuse have completed.
            # Change the actual file immediately before genuine closing replay;
            # every original source pin and the saved assessment stays intact.
            physical.write_bytes(original_bytes + b"\nchanged isolated incremental closing source")
            mutated.append(True)
        result = original_validate(offered, **kwargs)
        entry["passed"] = True
        return result

    monkeypatch.setattr(control["parent_native"], "validate_parent_shared_definition_use_native_v1",
                        observe_real_validation)
    output = control["directory"] / "warm-real-physical-closing-refusal"
    try:
        receipt = control["incremental"].build_incremental_parent_shared_corpus_v1(preparation,
            **genuine_parent_refusal_warm_arguments(control), output_directory=output)
        result = receipt, output
        assert real_calls == [{"offered_is_original": True, "passed": True},
                              {"offered_is_original": True, "passed": False}]
        assert mutated == [True] and physical.read_bytes() != original_bytes
        assert control["runtime_counts"]() == tuple(
            value + delta for value, delta in zip(
                before_counts, control["expected_warm_runtime_delta"], strict=True))
        assert receipt["module_compile_invocations"] == 0 and receipt["compiled_modules"] == []
        assert receipt["backend_executed"] is False and receipt["fresh_theorems"] == []
        assert set(receipt["reused_modules"]) == set(preparation.to_dict()["expected_modules"])
        assert len(receipt["reused_theorems"]) == 3
        assert receipt["build_passed"] is receipt["lean_compilation_verified"] is cache(result)["qualified"] is False
        assert receipt["post_run_validation_error"] is not None
        assert receipt["framework_successful"] is True
        assert artifacts(result) == baseline_artifacts
        assert {row["module"]: row["output"] for row in cache(result)["module_facts"]} == {
            row["module"]: row["output"] for row in cache(control["baseline"])["module_facts"]}
        assert (control["baseline"][1] / "cache.json").read_bytes() == baseline_raw
        assert artifacts(control["baseline"]) == baseline_artifacts
        if "binary_pins" in control:
            assert cache(result)["execution_contract"]["binary_sha256"] == control["binary_pins"]
            assert set(receipt["version_probes"]) == {"lake", "lean"}
            for binary, probe in receipt["version_probes"].items():
                assert probe["command"] == [str(Path(control["lake_executable"]).parent / binary), "--version"]
                assert probe["returncode"] == 0 and "4.34.1" in probe["stdout"]
        assert (output / "project/corpus-manifest.json").read_bytes() == frozen_manifest.encode()
        for name, text in frozen_files:
            assert (output / "project" / name).read_bytes() == text.encode()
        assert (output / "module-executions.jsonl").read_bytes() == b""
        assert arguments == before_inputs
        assert preparation.manifest_json == frozen_manifest and preparation.files == frozen_files
        for record in (receipt, cache(result)):
            assert all(record[key] is False for key in control["incremental"]._parent_flags())
    finally:
        physical.write_bytes(original_bytes)
    assert physical.read_bytes() == original_bytes


def assert_parent_incremental_resigned_revocation_warm_refusal(control, monkeypatch):
    lake, support = control["lake"], control["support"]
    original_data = control["data"]
    signed = deepcopy(original_data["signed"])
    old_reviews = deepcopy(signed["reviews"])
    signed["registry"]["keys"][0]["revoked_at_utc"] = support.signing.NOW
    # The existing real signing owner refreshes registry/policy bindings and
    # re-signs each claim. Invalidating old cache cannot rely on fake signatures.
    support.signing.refresh(signed)
    assert all(before["signature"] != after["signature"]
               for before, after in zip(old_reviews, signed["reviews"], strict=True))
    revoked_inputs = lake.review_arguments(support, signed)
    original_component = control["arguments"]["component_inputs"][0]
    offered_component = dict(original_component, review_inputs=revoked_inputs)
    assert offered_component["assessment_raw"] == original_data["assessment_raw"]
    assert offered_component["expected_assessment_file_sha256"] == original_data["expected_assessment_file_sha256"]
    before_counts = control["runtime_counts"]()
    baseline_raw = (control["baseline"][1] / "cache.json").read_bytes()
    baseline_artifacts = artifacts(control["baseline"])
    original_validate = control["parent_native"].validate_parent_shared_definition_use_native_v1
    original_review_validate = lake.review.validate_parent_definition_use_review_assessment_v1
    real_calls, review_calls = [], []

    def observe_real_validation(offered, **kwargs):
        real_calls.append(offered is control["preparation"])
        return original_validate(offered, **kwargs)

    def observe_real_review(report, *args, **kwargs):
        review_calls.append({"assessment_sha256": report["assessment_sha256"],
            "revoked_at_utc": kwargs["registry"]["keys"][0]["revoked_at_utc"]})
        return original_review_validate(report, *args, **kwargs)

    monkeypatch.setattr(control["parent_native"], "validate_parent_shared_definition_use_native_v1",
                        observe_real_validation)
    monkeypatch.setattr(lake.review, "validate_parent_definition_use_review_assessment_v1", observe_real_review)
    output = control["directory"] / "warm-real-resigned-revocation-refusal"
    with pytest.raises(ValueError, match="combined-use review assessment differs from exact regeneration"):
        control["incremental"].build_incremental_parent_shared_corpus_v1(control["preparation"],
            **genuine_parent_refusal_warm_arguments(control, component_inputs=[offered_component]),
            output_directory=output)
    assert real_calls == [True]
    assert review_calls == [{"assessment_sha256": original_data["assessment"]["assessment_sha256"],
                            "revoked_at_utc": support.signing.NOW}]
    assert control["runtime_counts"]() == before_counts
    assert not output.exists()
    assert (control["baseline"][1] / "cache.json").read_bytes() == baseline_raw
    assert artifacts(control["baseline"]) == baseline_artifacts
    current = lake.refresh_assessment(support, signed)
    assert current["assessment"]["evidence_assessment_status"] == "rejected"
    assert current["assessment"]["review_prerequisites_satisfied_under_selected_trust"] is False
    assert all(row["signature_status"] == "valid" for row in current["assessment"]["reviews"])
    assert any("key_revoked" in row["blockers"] for row in current["assessment"]["reviews"])
    assert original_data["signed"]["registry"]["keys"][0]["revoked_at_utc"] is None
    assert control["arguments"]["component_inputs"][0]["review_inputs"]["registry"]["keys"][0]["revoked_at_utc"] is None



def test_parent_incremental_genuine_physical_drift_on_warm_closing_refuses_and_retains_frozen_project(
        genuine_parent_incremental_refusal_runtime, monkeypatch):
    assert_parent_incremental_physical_drift_warm_refusal(
        genuine_parent_incremental_refusal_runtime, monkeypatch)


def test_parent_incremental_genuine_resigned_revocation_refuses_warm_opening_before_dispatch(
        genuine_parent_incremental_refusal_runtime, monkeypatch):
    assert_parent_incremental_resigned_revocation_warm_refusal(
        genuine_parent_incremental_refusal_runtime, monkeypatch)


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_parent_incremental_installed_lean_warm_refusals_preserve_cold_native_evidence(
        installed_incremental_parent_lake, tmp_path, monkeypatch, family):
    """One real six-module cold; genuine warm refusals add no fresh proofs."""
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_native_v2 as parent_native
    from ipfs_datasets_py.logic.autoformal import legal_corpus_incremental as incremental

    # The existing exact-binary opt-in fixture resolves before source creation.
    fixture_support, executable, binary_pins = installed_incremental_parent_lake
    lake = fixture_support.shared_fixture.parent_shared_fixture_module()
    support = lake.support.__wrapped__()
    originals = tmp_path / "originals"
    originals.mkdir()
    data = lake.make_data(support, originals, family=family)
    arguments = fixture_support.shared_fixture.parent_shared_arguments([data])
    preparation = shared.prepare_parent_shared_definition_use_corpus_v1(**arguments)
    manifest = preparation.to_dict()
    assert len(manifest["components"]) == 1 and len(manifest["expected_modules"]) == 6
    assert data["assessment"]["evidence_assessment_status"] == "authenticated"
    assert data["assessment"]["review_prerequisites_satisfied_under_selected_trust"] is True
    assert data["review_inputs"]["registry"]["mode"] == "external_pinned_trust"
    assert len(data["review_inputs"]["reviews"]) == len(data["review_inputs"]["registry"]["keys"]) == 2
    # These are genuine test signatures on fictional declarations, not legal
    # endorsement, source-to-model equivalence, training or convergence evidence.
    before_inputs = deepcopy(arguments)
    before_preparation = preparation.manifest_json, preparation.files
    physical = {path: path.read_bytes() for path in originals.rglob("*") if path.is_file()}
    assert physical and all(physical.values()) and not any(path.is_symlink() for path in physical)
    observed = []
    original_run = native.process.BoundedToolRunner.run

    def observe_real_native_run(runner, request, **kwargs):
        # Forward the exact runner, request and options to the original native
        # owner; no probe/compiler result or lifecycle observation is authored.
        entry = {"command": tuple(request.argv), "completed": False}
        observed.append(entry)
        result = original_run(runner, request, **kwargs)
        entry["completed"] = True
        return result

    monkeypatch.setattr(native.process.BoundedToolRunner, "run", observe_real_native_run)

    def runtime_counts():
        return (sum(len(row["command"]) > 1 and row["command"][1] == "-o" for row in observed),
                sum(row["command"][-1] == "--version" for row in observed))

    output = tmp_path / "installed-parent-cold-for-warm-refusals"
    receipt = incremental.build_incremental_parent_shared_corpus_v1(preparation,
        **arguments, expected_preparation_sha256=parent_native.parent_shared_preparation_sha256(preparation),
        lake_executable=str(executable), output_directory=output,
        timeout_seconds=60, operation_timeout_seconds=3600)
    baseline = receipt, output
    saved = cache(baseline)
    assert receipt["build_passed"] is receipt["lean_compilation_verified"] is True
    assert receipt["framework_successful"] is saved["qualified"] is True
    assert receipt["post_run_validation_error"] is None and saved["profile"] == incremental.PARENT_PROFILE
    assert runtime_counts() == (6, 2) and len(observed) == 8 and all(row["completed"] for row in observed)
    assert set(receipt["compiled_modules"]) == set(manifest["expected_modules"])
    assert receipt["module_compile_invocations"] == 6 and receipt["reused_modules"] == []
    assert len(receipt["fresh_theorems"]) == 3 and receipt["reused_theorems"] == []
    assert receipt["components"] == manifest["components"] and receipt["population"] == manifest["population"]
    assert receipt["components"][0]["review_evidence"]["status"] == "authenticated"
    assert receipt["components"][0]["review_evidence"]["prerequisites_satisfied_under_selected_trust"] is True
    assert receipt["components"][0]["theorem_assumptions"]
    assert saved["execution_contract"]["binary_sha256"] == binary_pins
    assert saved["execution_contract"]["toolchain_closure"]["file_count"] > 0
    assert saved["execution_contract"]["toolchain_closure"]["file_bytes"] > 0
    assert set(receipt["version_probes"]) == {"lake", "lean"}
    for binary, probe in receipt["version_probes"].items():
        assert probe["command"] == [str(executable.parent / binary), "--version"]
        assert probe["returncode"] == 0 and "4.34.1" in probe["stdout"]
    observed_raw = (output / "module-executions.jsonl").read_bytes()
    assert sha(observed_raw) == receipt["execution_observations"]["sha256"]
    assert len(observed_raw) == receipt["execution_observations"]["bytes"]
    observations = [json.loads(line) for line in observed_raw.splitlines()]
    assert [row["module"] for row in observations] == receipt["compiled_modules"]
    assert len(observations) == 6
    for row in observations:
        assert row["runtime"] == "native" and row["returncode"] == 0 and row["pid"] > 0
        assert row["command"][0] == str(executable.parent / "lean")
        assert row["workspace_cleaned"] is True and not row["error"]
        assert row["native_lifecycle"]["cleanup_confirmed"] is True
        assert row["native_lifecycle"]["kernel_containment_attested"] is False
    theorem_dependencies = {}
    for row in saved["module_facts"]:
        assert row["output"]["kernel_checked"] is True
        evidence = row["output"]["execution_evidence"]
        assert evidence["native_lifecycle"]["cleanup_confirmed"] is True
        assert evidence["runtime"] == "native" and evidence["pid"] > 0
        assert evidence["source_readback_sha256"] == row["recipe"]["source_sha256"]
        theorem_dependencies.update(row["output"]["theorem_axiom_dependencies"])
    assert theorem_dependencies == {name: [] for name in receipt["fresh_theorems"]}
    assert len(theorem_dependencies) == 3
    for module, raw in artifacts(baseline).items():
        assert raw and sha(raw) == receipt["artifact_sha256"][module]
        assert not raw.startswith(b"authored-fake-")
    assert json.loads((output / "build-receipt.json").read_bytes()) == receipt
    assert (output / "project/corpus-manifest.json").read_bytes() == preparation.manifest_json.encode()
    for filename, body in preparation.files:
        assert (output / "project" / filename).read_bytes() == body.encode()
    assert not any(path.is_symlink() for path in output.rglob("*"))
    for record in (receipt, saved):
        assert all(record[key] is False for key in incremental._parent_flags())
    assert all(path.read_bytes() == raw for path, raw in physical.items())
    control = {"incremental": incremental, "parent_native": parent_native,
        "directory": tmp_path, "originals": originals, "lake": lake, "support": support,
        "data": data, "arguments": arguments, "preparation": preparation,
        "baseline": baseline, "lake_executable": str(executable), "binary_pins": binary_pins,
        "runtime_counts": runtime_counts, "expected_warm_runtime_delta": (0, 2)}
    # Each helper keeps using the qualified real cold cache; the failed closing
    # cache is retained as negative evidence and never offered as a new baseline.
    with monkeypatch.context() as patches:
        assert_parent_incremental_physical_drift_warm_refusal(control, patches)
    assert runtime_counts() == (6, 4) and len(observed) == 10 and all(row["completed"] for row in observed)
    assert all(path.read_bytes() == raw for path, raw in physical.items())
    with monkeypatch.context() as patches:
        assert_parent_incremental_resigned_revocation_warm_refusal(control, patches)
    assert runtime_counts() == (6, 4) and len(observed) == 10
    assert arguments == before_inputs
    assert (preparation.manifest_json, preparation.files) == before_preparation
    assert all(path.read_bytes() == raw for path, raw in physical.items())


# Reviewed V3 integration uses the existing complete fictional source/review/
# graph fixture and unchanged child witnesses. Only compiler process observations
# below are authored. No test calls a real Lean executable or model.
@pytest.fixture(scope="module")
def reviewed_incremental_component_v3(tmp_path_factory):
    class FixtureTempNamespace:
        def mktemp(self, basename, numbered=True):
            return tmp_path_factory.mktemp("reviewed-incremental-v3-" + basename, numbered=numbered)
    control = _FIXTURE_MODULE.reviewed_preservation_graph_fixture_v3(FixtureTempNamespace())
    control["preparation"] = _FIXTURE_MODULE.reviewed_preservation_prepare_fixture_v3(control)
    return control


def test_reviewed_incremental_v3_requires_explicit_consumer_after_complete_mixed_project(
        reviewed_incremental_component_v3):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_incremental as incremental
    control = reviewed_incremental_component_v3
    control["mixed_helper"].assert_signatures_valid(control["case"])
    assert control["admission"]["fixture_only"] is True
    assert control["admission"]["semantic_use_eligible"] is True
    assert control["graph"]["schema"] == "legal-corpus-reviewed-norm-candidate-graph/v3"
    assert len(control["preparation"].to_dict()["units"]) == 3
    assert len(control["preparation"].to_dict()["preservation_obligations"]) == 15
    assert _FIXTURE_MODULE.reviewed_preservation_validate_fixture_v3(control) == control["preparation"]
    assert callable(getattr(incremental, "build_incremental_reviewed_preservation_corpus_v3", None)), (
        "reviewed mixed aggregate has no explicit incremental compiler consumer")


@pytest.fixture
def reviewed_incremental_runtime_v3(monkeypatch, tmp_path):
    from ipfs_datasets_py.logic.autoformal import legal_corpus_incremental as incremental
    compiler = AuthoredParentIncrementalCompiler(tmp_path)
    monkeypatch.setattr(native.shared, "_installed_toolchain", compiler.installed)
    monkeypatch.setattr(incremental, "_toolchain_closure", compiler.closure)
    monkeypatch.setattr(native.process.BoundedToolRunner, "run",
        lambda runner, request, **kwargs: compiler.run(runner, request, **kwargs))
    return {"incremental": incremental, "compiler": compiler, "directory": tmp_path}


def build_reviewed_incremental_v3(runtime, control, name, *, previous=None, **overrides):
    arguments = dict(expected_preservation_sha256=shared.reviewed_preservation_corpus_sha256(control["preparation"]),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN, lake_executable=str(runtime["compiler"].lake),
        output_directory=runtime["directory"] / name,
        **control["kwargs"])
    if previous is not None:
        raw = (previous[1] / "cache.json").read_bytes()
        arguments.update(previous_cache_raw=raw, expected_previous_cache_sha256=sha(raw),
            previous_artifacts=artifacts(previous))
    arguments.update(overrides)
    receipt = runtime["incremental"].build_incremental_reviewed_preservation_corpus_v3(
        control["preparation"], control["graph"], control["admission"], *control["args"], **arguments)
    return receipt, runtime["directory"] / name


def reviewed_incremental_nodes_v3(node):
    yield node
    for child in node["arguments"]:
        yield from reviewed_incremental_nodes_v3(child)
    if node.get("extension") is not None:
        for child in node["extension"]["children"]:
            yield from reviewed_incremental_nodes_v3(child)


def reviewed_incremental_refresh_request_v3(control, case, ordinal, request):
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
    from ipfs_datasets_py.logic.syntax_core import ast
    helper = control["mixed_helper"]
    unit = case["declaration"]["units"][ordinal]
    request["expression"] = ast.TypedExpression.from_dict(dict(request["expression"], content_digest="")).to_dict()
    raw = helper.fixture.wire(request)
    mixed = unit["relational_profile"] == relational.MIXED_PROFILE
    report = (relational.prepare_mixed_relational_norm_v1 if mixed else relational.prepare_relational_norm_v1)(
        raw, expected_request_sha256=sha(raw))
    unit["relational_request_sha256"] = sha(raw)
    occurrence = unit["occurrence"]
    unit["coverage"] = [{"typed_path": row["typed_path"], **{key: occurrence[key] for key in (
        "start_char", "end_char", "start_utf8", "end_utf8")}} for row in report["structural_mapping"]]
    pin = (relational.mixed_relational_norm_report_sha256 if mixed else relational.relational_norm_report_sha256)(report)
    case["relational_inputs"][unit["unit_id"]] = {"request_raw": raw, "report": report, "expected_report_sha256": pin}
    for use in case["declaration"]["definition_uses"]:
        if use["use_unit_id"] != unit["unit_id"]:
            continue
        paths = []
        for mapping in report["structural_mapping"]:
            node = report["typed_expression"]
            for token in mapping["typed_path"].split("/")[1:]:
                node = node[int(token)] if type(node) is list else node[token]
            if type(node) is dict and node.get("kind") == "predicate" and node.get("symbol") == use["defined_predicate"]:
                paths.append(mapping["typed_path"])
        assert paths, "The complete governing-definition use must survive a mutation."
        use["target_typed_paths"] = paths


def reviewed_incremental_changed_component_v3(control, facet):
    """Explicit fictional correction; retain every complete source and re-review it.

    Re-signing happens only with the fixture's declared invented principals.
    These controls test invalidation, not legal acceptability of the correction.
    """
    from ipfs_datasets_py.logic.syntax_core import ast
    helper, owner = control["mixed_helper"], control["owner"]
    case = helper.cloned(control["case"])
    ordinal = 0 if facet == "definition" else 1 if facet == "exception" else 2
    unit = case["declaration"]["units"][ordinal]
    request = json.loads(case["relational_inputs"][unit["unit_id"]]["request_raw"])
    root = request["expression"]["root"]
    if facet == "definition":
        equivalence = next(node for node in reviewed_incremental_nodes_v3(root) if node["kind"] == "iff")
        # A corrected definition still states a universally bound equivalence.
        # Negate only its complete fictional RHS; keep every original subtree.
        fresh_id = "fixture:incremental-definition-rhs-negation"
        assert fresh_id not in {node["node_id"] for node in reviewed_incremental_nodes_v3(root)}
        equivalence["arguments"][1] = ast.mk_not(
            fresh_id, ast.LogicNode.from_dict(equivalence["arguments"][1])).to_dict()
    elif facet == "role":
        row = next(row for row in request["argument_roles"] if row["symbol"] == "InspectsRegisterAt")
        row["roles"][0] = "reviewing_officer"
    elif facet == "scope":
        assert root["kind"] == "forall"
        root["kind"] = "exists"
    elif facet == "exception":
        guarded = next(node for node in reviewed_incremental_nodes_v3(root)
            if node["kind"] == "implies" and node["arguments"][0]["kind"] == "not")
        replacement = deepcopy(guarded["arguments"][1])
        guarded.clear(); guarded.update(replacement)
    elif facet == "sort":
        # Change the event carrier while keeping the governing officer Object.
        # The original three sort declarations and every source clause survive.
        def alter(value):
            if type(value) is dict:
                if value.get("name") == "EventFrame" and "kind" in value:
                    value["name"] = "TimeFrame"
                else:
                    for item in value.values(): alter(item)
            elif type(value) is list:
                for item in value: alter(item)
        alter(root)
        alter(request["expression"]["signature"]["symbols"])
    else:
        assert facet in ("cardinality-three", "cardinality-two")
        from ipfs_datasets_py.logic.syntax_core import signatures
        bound = 3 if facet == "cardinality-three" else 2
        obj = signatures.LogicSort("Object")
        serial = iter(range(10000))
        def nid(): return "fixture:incremental-count:" + str(next(serial))
        variables = ["counted_officer_" + str(i) for i in range(bound + 1)]
        def variable(name): return ast.mk_variable(nid(), name, obj)
        members = [ast.mk_predicate(nid(), "CoveredOfficer", [variable(name)]) for name in variables]
        equalities = [ast.mk_equality(nid(), variable(left), variable(right))
            for i, left in enumerate(variables) for right in variables[i + 1:]]
        cap = ast.mk_implies(nid(), ast.mk_and(nid(), *members), ast.mk_or(nid(), *equalities))
        for name in reversed(variables): cap = ast.mk_forall(nid(), [ast.Binder(name, obj)], cap)
        request["expression"]["root"] = ast.mk_and(nid(), ast.LogicNode.from_dict(root), cap).to_dict()
    reviewed_incremental_refresh_request_v3(control, case, ordinal, request)
    case["preparation"] = helper.prepare(owner, case)
    helper.refresh_signed_reviews(case, owner)
    helper.assert_signatures_valid(case)
    args, kwargs = helper.fixture.reviewed_assessment_arguments_v2(owner, case)
    admission = owner.assess_reviewed_norm_admission_v3(*args, **kwargs)
    assert admission["semantic_use_eligible"] is True and admission["fixture_only"] is True
    admission_sha = owner.norm_content_adjudication_sha256(admission)
    graph = control["helper"].owner.build_reviewed_norm_graph_v3(admission, *args,
        expected_admission_sha256=admission_sha, **kwargs)
    changed = dict(control, case=case, args=args, kwargs=kwargs, admission=admission, graph=graph,
        admission_sha=admission_sha, graph_sha=control["helper"].owner.norm_definition_graph_sha256(graph))
    changed["preparation"] = _FIXTURE_MODULE.reviewed_preservation_prepare_fixture_v3(changed)
    assert [row["source_version"] for row in case["declaration"]["units"]] == [
        row["source_version"] for row in control["case"]["declaration"]["units"]]
    return changed


def test_reviewed_incremental_v3_cold_warm_zero_compile_keep_complete_current_review(
        reviewed_incremental_runtime_v3, reviewed_incremental_component_v3):
    runtime, control = reviewed_incremental_runtime_v3, reviewed_incremental_component_v3
    cold = build_reviewed_incremental_v3(runtime, control, "reviewed-cold")
    calls = len(runtime["compiler"].calls)
    warm = build_reviewed_incremental_v3(runtime, control, "reviewed-warm", previous=cold)
    assert cold[0]["build_passed"] is warm[0]["build_passed"] is True
    assert len(cold[0]["compiled_modules"]) == calls == 8
    assert len(cold[0]["fresh_theorems"]) == 15
    assert warm[0]["compiled_modules"] == warm[0]["fresh_theorems"] == []
    assert len(warm[0]["reused_modules"]) == 8 and len(warm[0]["reused_theorems"]) == 15
    assert len(runtime["compiler"].calls) == calls
    assert artifacts(cold) == artifacts(warm)
    assert warm[0]["units"] == control["preparation"].to_dict()["units"]
    assert warm[0]["definition_use_record_cids"] == control["preparation"].to_dict()["definition_use_record_cids"]
    assert warm[0]["reviewed_graph_sha256"] == control["graph_sha"]
    assert warm[0]["reviewed_admission_sha256"] == control["admission_sha"]
    assert warm[0]["fresh_proof_for_reused_modules"] is False
    assert warm[0]["composition_obligations_checked"] is False
    assert warm[0]["statutory_meaning_proved"] is warm[0]["release_ready"] is False
    assert not any(warm[0]["authority"].values())
    assert warm[0]["training_mask"] == warm[0]["evaluation_gold_mask"] == 0
    assert cache(warm)["schema"] == runtime["incremental"].REVIEWED_CACHE_SCHEMA
    assert all(raw.startswith(b"authored-fake-olean-no-native-proof\0") for raw in artifacts(warm).values())


@pytest.mark.parametrize("facet", ["definition", "role", "scope", "exception", "sort", "cardinality-two"])
def test_reviewed_incremental_v3_corrected_complete_meaning_invalidates_and_matches_clean(
        reviewed_incremental_runtime_v3, reviewed_incremental_component_v3, facet):
    runtime, control = reviewed_incremental_runtime_v3, reviewed_incremental_component_v3
    if facet == "cardinality-two":
        control = reviewed_incremental_changed_component_v3(control, "cardinality-three")
    changed = reviewed_incremental_changed_component_v3(reviewed_incremental_component_v3, facet)
    cold = build_reviewed_incremental_v3(runtime, control, "semantic-cold")
    updated = build_reviewed_incremental_v3(runtime, changed, "semantic-updated", previous=cold)
    clean = build_reviewed_incremental_v3(runtime, changed, "semantic-clean")
    assert updated[0]["build_passed"] is clean[0]["build_passed"] is True
    assert updated[0]["compiled_modules"], "No semantic correction can retain the entire old artifact set."
    assert artifacts(updated) == artifacts(clean)
    assert updated[0]["artifact_root_cid"] == clean[0]["artifact_root_cid"]
    old_units = control["preparation"].to_dict()["units"]
    new_units = changed["preparation"].to_dict()["units"]
    old_instances = {row["unit_id"]: row["instance_module"] for row in old_units}
    assert set(updated[0]["reused_modules"]) <= {module for module in cold[0]["expected_modules"]
        if module in clean[0]["expected_modules"]}
    assert not (set(cold[0]["expected_modules"]) - set(clean[0]["expected_modules"])) & set(artifacts(updated))
    assert updated[0]["units"] == new_units
    if facet == "definition":
        # Every declared governing use retains its donor in the native recipe,
        # even though independent preservation witnesses import only semantics.
        saved = cache(updated)
        for row in saved["module_facts"]:
            provenance = row["recipe"]["reviewed_provenance"]
            if provenance["role"] == "instance" and provenance["contributors"][0]["kind"] == "norm":
                assert old_units[0]["unit_id"] in {unit["unit_id"] for unit in provenance["dependency_units"]}
                assert row["module"] in updated[0]["compiled_modules"]
        assert old_instances[old_units[0]["unit_id"]] not in artifacts(updated)
    if facet == "role":
        assert old_units[2]["relational_request_sha256"] != new_units[2]["relational_request_sha256"]
        assert old_units[2]["instance_module"] != new_units[2]["instance_module"]
    assert len(updated[0]["fresh_theorems"]) + len(updated[0]["reused_theorems"]) == 15


@pytest.mark.parametrize("changed", ["compiler", "library"])
def test_reviewed_incremental_v3_toolchain_contract_change_rebuilds_every_module(
        reviewed_incremental_runtime_v3, reviewed_incremental_component_v3, changed):
    runtime, control = reviewed_incremental_runtime_v3, reviewed_incremental_component_v3
    cold = build_reviewed_incremental_v3(runtime, control, "toolchain-cold")
    if changed == "compiler": runtime["compiler"].lean.write_bytes(b"authored-fresh-compiler-v2")
    else: runtime["compiler"].library_salt = "authored-fresh-library-v2"
    updated = build_reviewed_incremental_v3(runtime, control, "toolchain-updated", previous=cold)
    assert updated[0]["build_passed"] is True
    assert updated[0]["reused_modules"] == []
    assert set(updated[0]["compiled_modules"]) == set(control["preparation"].to_dict()["expected_modules"])


@pytest.mark.parametrize("when", ["opening", "closing"])
def test_reviewed_incremental_v3_warm_rechecks_genuine_resigned_revocation(
        reviewed_incremental_runtime_v3, reviewed_incremental_component_v3, monkeypatch, when):
    runtime, original = reviewed_incremental_runtime_v3, reviewed_incremental_component_v3
    cold = build_reviewed_incremental_v3(runtime, original, "revocation-cold")
    helper = original["mixed_helper"]
    case = helper.cloned(original["case"])
    args, kwargs = helper.fixture.reviewed_assessment_arguments_v2(original["owner"], case)
    control = dict(original, case=case, args=args, kwargs=kwargs)
    # Preserve genuine detached signatures and change only the currently trusted
    # registry generation. A warm cache is never current review authorization.
    def revoke():
        case["registry"]["revocation_generation"] += 1
        case["registry"]["keys"][0]["revoked_at_utc"] = helper.fixture.EVALUATED
        helper.fixture.reviewed_resign_v2(case)
        helper.assert_signatures_valid(case)
        control["args"], control["kwargs"] = helper.fixture.reviewed_assessment_arguments_v2(original["owner"], case)
    before = len(runtime["compiler"].calls)
    if when == "opening":
        revoke()
        with pytest.raises(ValueError): build_reviewed_incremental_v3(runtime, control, "revoked-opening", previous=cold)
        assert not (runtime["directory"] / "revoked-opening").exists()
    else:
        original_replay = runtime["incremental"]._reviewed_replay
        count = []
        def replay(preparation, inputs, pin, toolchain):
            count.append(True)
            if len(count) == 2:
                revoke()
                inputs["args"], inputs["kwargs"] = control["args"], control["kwargs"]
            return original_replay(preparation, inputs, pin, toolchain)
        monkeypatch.setattr(runtime["incremental"], "_reviewed_replay", replay)
        result = build_reviewed_incremental_v3(runtime, control, "revoked-closing", previous=cold)
        assert result[0]["build_passed"] is False
        assert result[0]["post_run_validation_error"] is not None
        assert cache(result)["qualified"] is False
        assert (result[1] / "project").is_dir()
        assert artifacts(result) == artifacts(cold)
    assert len(runtime["compiler"].calls) == before


@pytest.mark.parametrize("damage", ["profile", "artifact", "provenance", "axiom-report", "population"])
def test_reviewed_incremental_v3_prior_cache_never_substitutes_changed_proof_or_population(
        reviewed_incremental_runtime_v3, reviewed_incremental_component_v3, damage):
    runtime, control = reviewed_incremental_runtime_v3, reviewed_incremental_component_v3
    cold = build_reviewed_incremental_v3(runtime, control, "prior-cold")
    saved, raw_artifacts = cache(cold), artifacts(cold)
    if damage == "profile": saved["profile"] = runtime["incremental"].PARENT_PROFILE
    elif damage == "artifact": raw_artifacts[next(iter(raw_artifacts))] += b" changed"
    elif damage == "provenance": saved["module_facts"][-2]["recipe"]["reviewed_provenance"]["contributors"][0]["complete_ir_sha256"] = "f" * 64
    elif damage == "axiom-report":
        row = next(row for row in saved["module_facts"] if row["output"]["theorem_axiom_dependencies"])
        row["output"]["execution_evidence"]["stdout"] += row["output"]["execution_evidence"]["stdout"].splitlines()[0] + "\n"
    else: saved["module_facts"].pop()
    raw = canonical_dag_json_bytes(reseal(saved))
    before = len(runtime["compiler"].calls)
    with pytest.raises(ValueError):
        build_reviewed_incremental_v3(runtime, control, "prior-refused", previous_cache_raw=raw,
            expected_previous_cache_sha256=sha(raw), previous_artifacts=raw_artifacts)
    assert len(runtime["compiler"].calls) == before
    assert not (runtime["directory"] / "prior-refused").exists()


@pytest.mark.parametrize("damage", ["duplicate", "stderr_claim"])
def test_reviewed_incremental_v3_each_five_theorem_report_is_exact_not_an_unrelated_success(
        reviewed_incremental_runtime_v3, reviewed_incremental_component_v3, damage):
    runtime = reviewed_incremental_runtime_v3
    runtime["compiler"].axiom_damage = damage
    result = build_reviewed_incremental_v3(runtime, reviewed_incremental_component_v3, "axioms-refused")
    assert result[0]["build_passed"] is False
    assert cache(result)["qualified"] is False
    assert result[0]["framework_successful"] is False


@pytest.mark.parametrize("pin", ["expected_preservation_sha256", "expected_graph_sha256", "expected_admission_sha256"])
def test_reviewed_incremental_v3_independent_current_pins_refuse_before_compiler(
        reviewed_incremental_runtime_v3, reviewed_incremental_component_v3, pin):
    runtime = reviewed_incremental_runtime_v3
    with pytest.raises(ValueError):
        build_reviewed_incremental_v3(runtime, reviewed_incremental_component_v3, "pins-refused", **{pin: "f" * 64})
    assert runtime["compiler"].calls == []
    assert not (runtime["directory"] / "pins-refused").exists()


@pytest.mark.parametrize("namespaces,total_units,supported", [(2, 6, True), (2, 7, False), (2, 8, False), (1, 8, True)])
def test_reviewed_incremental_v3_uses_exact_upstream_module_boundary_without_dropping_units(
        reviewed_incremental_runtime_v3, reviewed_incremental_component_v3, namespaces, total_units, supported):
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
    original = reviewed_incremental_component_v3
    control = _FIXTURE_MODULE.reviewed_preservation_capacity_control_v3(original, total_units)
    if namespaces == 1:
        helper, owner, case = control["mixed_helper"], control["owner"], control["case"]
        unit = case["declaration"]["units"][2]
        source_unit = case["declaration"]["units"][1]
        request = json.loads(case["relational_inputs"][source_unit["unit_id"]]["request_raw"])
        request["expression"]["expression_id"] += ":independent-object-use"
        unit["relational_profile"] = relational.PROFILE
        reviewed_incremental_refresh_request_v3(control, case, 2, request)
        case["preparation"] = helper.prepare(owner, case)
        helper.refresh_signed_reviews(case, owner)
        helper.assert_signatures_valid(case)
        args, kwargs = helper.fixture.reviewed_assessment_arguments_v2(owner, case)
        admission = owner.assess_reviewed_norm_admission_v3(*args, **kwargs)
        assert admission["semantic_use_eligible"] is True
        admission_sha = owner.norm_content_adjudication_sha256(admission)
        graph = control["helper"].owner.build_reviewed_norm_graph_v3(admission, *args,
            expected_admission_sha256=admission_sha, **kwargs)
        control.update(args=args, kwargs=kwargs, admission=admission, admission_sha=admission_sha,
            graph=graph, graph_sha=control["helper"].owner.norm_definition_graph_sha256(graph))
    assert len(control["case"]["declaration"]["units"]) == total_units
    snapshot = control["owner"].norm._snapshot({"args": list(control["args"]), "kwargs": control["kwargs"]})[1]
    expected_modules = 2 * namespaces + total_units + 1
    assert supported == (expected_modules <= shared.MAX_REVIEWED_PRESERVATION_MODULES)
    if not supported:
        with pytest.raises(ValueError, match="capacity"):
            _FIXTURE_MODULE.reviewed_preservation_prepare_fixture_v3(control)
        assert reviewed_incremental_runtime_v3["compiler"].calls == []
    else:
        control["preparation"] = _FIXTURE_MODULE.reviewed_preservation_prepare_fixture_v3(control)
        assert len(control["preparation"].to_dict()["expected_modules"]) == expected_modules == 11
        result = build_reviewed_incremental_v3(reviewed_incremental_runtime_v3, control, "exact-boundary")
        assert result[0]["build_passed"] is True
        assert len(result[0]["compiled_modules"]) == expected_modules
        assert len(result[0]["units"]) == total_units
        assert len(result[0]["fresh_theorems"]) == 5 * total_units
    assert snapshot == control["owner"].norm._snapshot({"args": list(control["args"]), "kwargs": control["kwargs"]})[1]


@pytest.mark.parametrize("where,damage", [
    ("contributors", "extra"), ("contributors", "ordinal-alias"), ("contributors", "header-extra"),
    ("contributors", "companion-extra"), ("contributors", "missing-companion"),
    ("dependency_units", "extra"), ("dependency_units", "parent-type"), ("dependency_units", "obligations")])
def test_reviewed_incremental_v3_complete_unit_contract_survives_self_resealed_cache_metadata(
        reviewed_incremental_runtime_v3, reviewed_incremental_component_v3, where, damage):
    from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json
    runtime = reviewed_incremental_runtime_v3
    control = reviewed_incremental_component_v3
    cold = build_reviewed_incremental_v3(runtime, control, "contract-cold")
    saved = cache(cold)
    fact = next(row for row in saved["module_facts"]
        if row["recipe"]["reviewed_provenance"]["role"] == "instance"
        and row["recipe"]["reviewed_provenance"][where])
    row = fact["recipe"]["reviewed_provenance"][where][0]
    if damage == "extra": row["ignored-unreviewed-field"] = "must be rejected"
    elif damage == "ordinal-alias": row["ordinal"] = bool(row["ordinal"])
    elif damage == "header-extra": row["signature_header"]["unreviewed-carrier"] = "Invented"
    elif damage == "companion-extra": row["original_child_files"][0]["unreviewed"] = True
    elif damage == "missing-companion": row["original_child_files"].pop()
    elif damage == "parent-type": row["parent_unit_ids"] = "not a list"
    else: row["preservation_obligations"].pop()
    # Updating the native recipe CID and outer record does not approve extra or
    # malformed unit metadata. Original byte artifacts and reports remain exact.
    fact["output"]["recipe_cid"] = cid_for_dag_json(fact["recipe"])
    raw = canonical_dag_json_bytes(reseal(saved))
    before = len(runtime["compiler"].calls)
    with pytest.raises(ValueError):
        build_reviewed_incremental_v3(runtime, control, "contract-refused", previous_cache_raw=raw,
            expected_previous_cache_sha256=sha(raw), previous_artifacts=artifacts(cold))
    assert len(runtime["compiler"].calls) == before
    assert not (runtime["directory"] / "contract-refused").exists()


def test_reviewed_incremental_v4_receipt_keeps_opening_pinned_assumptions_after_late_caller_mutation(
        reviewed_incremental_runtime_v3, reviewed_incremental_component_v3, monkeypatch):
    runtime, control = reviewed_incremental_runtime_v3, reviewed_incremental_component_v3
    cold = build_reviewed_incremental_v3(runtime, control, "assumptions-snapshot-cold")
    incremental = runtime["incremental"]
    original_admission = deepcopy(control["admission"])
    assumptions = deepcopy(original_admission["formal_assumptions"])
    original_pins = incremental._owner_pins
    calls = []
    def mutate_after_closing_replay(*args, **kwargs):
        pins = original_pins(*args, **kwargs)
        if kwargs.get("reviewed"):
            calls.append(True)
            if len(calls) == 2:
                control["admission"]["formal_assumptions"] = [*assumptions, "Unreviewed post-replay caller mutation."]
        return pins
    monkeypatch.setattr(incremental, "_owner_pins", mutate_after_closing_replay)
    try:
        warm = build_reviewed_incremental_v3(runtime, control, "assumptions-snapshot-warm", previous=cold)
        assert len(calls) == 2
        assert control["owner"].norm_content_adjudication_sha256(control["admission"]) != control["admission_sha"]
        assert warm[0]["build_passed"] is cache(warm)["qualified"] is True
        assert warm[0]["reviewed_admission_sha256"] == control["admission_sha"]
        assert warm[0]["formal_assumptions"] == assumptions
        assert warm[0]["formal_assumptions"] != control["admission"]["formal_assumptions"]
        assert warm[0]["compiled_modules"] == [] and artifacts(warm) == artifacts(cold)
        assert warm[0]["fresh_proof_for_reused_modules"] is False
    finally:
        control["admission"].clear(); control["admission"].update(original_admission)


def test_reviewed_incremental_v4_recipes_keep_the_validated_graph_during_temporary_caller_mutation(
        reviewed_incremental_runtime_v3, reviewed_incremental_component_v3, monkeypatch):
    runtime, control = reviewed_incremental_runtime_v3, reviewed_incremental_component_v3
    cold = build_reviewed_incremental_v3(runtime, control, "graph-snapshot-cold")
    incremental = runtime["incremental"]
    graph = control["graph"]; original_graph = deepcopy(graph)
    edge = graph["definition_use_records"][0]
    alternative = next(row["unit_id"] for row in control["preparation"].to_dict()["units"]
        if row["unit_id"] not in (edge["definition_unit_id"], edge["use_unit_id"]))
    original_pins, original_replay = incremental._owner_pins, incremental._reviewed_replay
    pins_seen, replays_seen, mutation_seen = [], [], []
    def mutate_after_opening_snapshot(*args, **kwargs):
        pins = original_pins(*args, **kwargs)
        if kwargs.get("reviewed"):
            pins_seen.append(True)
            if len(pins_seen) == 1:
                edge["definition_unit_id"] = alternative
                mutation_seen.append(control["helper"].owner.norm_definition_graph_sha256(graph))
        return pins
    def restore_before_fresh_closing_review(*args, **kwargs):
        replays_seen.append(True)
        if len(replays_seen) == 2:
            graph.clear(); graph.update(deepcopy(original_graph))
        return original_replay(*args, **kwargs)
    monkeypatch.setattr(incremental, "_owner_pins", mutate_after_opening_snapshot)
    monkeypatch.setattr(incremental, "_reviewed_replay", restore_before_fresh_closing_review)
    try:
        warm = build_reviewed_incremental_v3(runtime, control, "graph-snapshot-warm", previous=cold)
        assert len(pins_seen) == len(replays_seen) == 2
        assert len(mutation_seen) == 1 and mutation_seen[0] != control["graph_sha"]
        assert graph == original_graph
        assert warm[0]["build_passed"] is cache(warm)["qualified"] is True
        assert warm[0]["reviewed_graph_sha256"] == control["graph_sha"]
        assert warm[0]["compiled_modules"] == [] and artifacts(warm) == artifacts(cold)
        assert {row["module"]: row["recipe"] for row in cache(warm)["module_facts"]} == {
            row["module"]: row["recipe"] for row in cache(cold)["module_facts"]}
    finally:
        graph.clear(); graph.update(original_graph)


@pytest.mark.parametrize("subject", ["graph", "admission"])
def test_reviewed_incremental_v4_detached_snapshot_must_match_independent_current_pins(
        reviewed_incremental_runtime_v3, reviewed_incremental_component_v3, monkeypatch, subject):
    runtime, control = reviewed_incremental_runtime_v3, reviewed_incremental_component_v3
    incremental = runtime["incremental"]
    original = deepcopy(control[subject]); original_replay = incremental._reviewed_replay; calls = []
    def mutate_after_validated_opening(*args, **kwargs):
        prepared = original_replay(*args, **kwargs)
        calls.append(True)
        if len(calls) == 1:
            if subject == "graph": control["graph"]["definition_use_records"][0]["definition_unit_id"] += ":changed"
            else: control["admission"]["formal_assumptions"].append("Unreviewed opening mutation.")
        return prepared
    monkeypatch.setattr(incremental, "_reviewed_replay", mutate_after_validated_opening)
    try:
        with pytest.raises(ValueError, match="opening reviewed execution snapshot differs"):
            build_reviewed_incremental_v3(runtime, control, "opening-snapshot-refused")
        assert calls == [True] and runtime["compiler"].calls == []
        assert not (runtime["directory"] / "opening-snapshot-refused").exists()
    finally:
        control[subject].clear(); control[subject].update(original)


# Source-use identity is an explicit technical reuse domain. All compiler
# observations here remain authored fixture data, never native/legal evidence.
def reviewed_incremental_source_use_control_v1(original, mutation="nonoverlapping_paragraphs"):
    helper, owner = original["mixed_helper"], original["owner"]
    case = helper.cloned(original["case"])
    first, second = helper.fixture.reviewed_repeated_permission_source_v2(case, mutation)
    assert case["relational_inputs"][first["unit_id"]] == case["relational_inputs"][second["unit_id"]]
    assert first["occurrence"]["record_cid"] != second["occurrence"]["record_cid"]
    assert first["occurrence"]["end_char"] < second["occurrence"]["start_char"]
    case["preparation"] = helper.prepare(owner, case)
    helper.refresh_signed_reviews(case, owner)
    helper.assert_signatures_valid(case)
    args, kwargs = helper.fixture.reviewed_assessment_arguments_v2(owner, case)
    admission = owner.assess_reviewed_norm_admission_v3(*args, **kwargs)
    assert admission["fixture_only"] is admission["semantic_use_eligible"] is True
    admission_sha = owner.norm_content_adjudication_sha256(admission)
    graph_owner = original["helper"].owner
    graph = graph_owner.build_reviewed_norm_graph_v3(admission, *args,
        expected_admission_sha256=admission_sha, **kwargs)
    graph_sha = graph_owner.norm_definition_graph_sha256(graph)
    preparation = shared.prepare_reviewed_norm_preservation_corpus_v3(graph, admission, *args,
        expected_graph_sha256=graph_sha, expected_admission_sha256=admission_sha,
        toolchain=TOOLCHAIN, instance_identity_profile="reviewed-source-use/v1", **kwargs)
    manifest = preparation.to_dict()
    assert manifest["instance_identity_profile"] == "reviewed-source-use/v1"
    assert len(manifest["units"]) == len({row["instance_module"] for row in manifest["units"]}) == 3
    assert len(manifest["preservation_obligations"]) == len(set(manifest["preservation_obligations"])) == 15
    assert all(len(row["original_child_files"]) == 7 and len(row["preservation_obligations"]) == 5
        for row in manifest["units"])
    return dict(original, case=case, args=args, kwargs=kwargs, admission=admission,
        admission_sha=admission_sha, graph=graph, graph_sha=graph_sha, preparation=preparation)


@pytest.fixture(scope="module")
def reviewed_incremental_source_use_component_v1(reviewed_incremental_component_v3):
    return reviewed_incremental_source_use_control_v1(reviewed_incremental_component_v3)


def build_reviewed_incremental_source_use_v1(runtime, control, name, **kwargs):
    return build_reviewed_incremental_v3(runtime, control, name,
        instance_identity_profile="reviewed-source-use/v1", **kwargs)


def test_reviewed_source_use_incremental_cold_warm_preserves_every_physical_unit(
        reviewed_incremental_runtime_v3, reviewed_incremental_source_use_component_v1):
    runtime, control = reviewed_incremental_runtime_v3, reviewed_incremental_source_use_component_v1
    cold = build_reviewed_incremental_source_use_v1(runtime, control, "source-use-cold")
    calls = len(runtime["compiler"].calls)
    warm = build_reviewed_incremental_source_use_v1(runtime, control, "source-use-warm", previous=cold)
    assert cold[0]["build_passed"] is warm[0]["build_passed"] is True
    assert calls == len(control["preparation"].to_dict()["expected_modules"]) == 8
    assert len(runtime["compiler"].calls) == calls
    assert warm[0]["compiled_modules"] == warm[0]["fresh_theorems"] == []
    assert len(warm[0]["reused_modules"]) == 8 and len(warm[0]["reused_theorems"]) == 15
    assert artifacts(cold) == artifacts(warm)
    assert warm[0]["units"] == control["preparation"].to_dict()["units"]
    assert warm[0]["instance_identity_profile"] == "reviewed-source-use/v1"
    assert cache(warm)["profile"] == runtime["incremental"].REVIEWED_PROFILE + "+reviewed-source-use/v1"
    assert cache(warm)["execution_contract"]["profile"] == cache(warm)["profile"]
    assert warm[0]["fresh_proof_for_reused_modules"] is False
    assert warm[0]["composition_obligations_checked"] is False
    assert warm[0]["original_success_authenticated"] is warm[0]["live_native_success_authenticated"] is False
    assert warm[0]["statutory_meaning_proved"] is warm[0]["release_ready"] is False
    assert not any(warm[0]["authority"].values())
    assert warm[0]["training_mask"] == warm[0]["evaluation_gold_mask"] == 0
    assert all(raw.startswith(b"authored-fake-olean-no-native-proof\0") for raw in artifacts(warm).values())


@pytest.mark.parametrize("selector", [None, "", True, "reviewed-source-use/v2"])
def test_reviewed_source_use_incremental_requires_explicit_exact_selector(
        reviewed_incremental_runtime_v3, reviewed_incremental_source_use_component_v1, selector):
    runtime = reviewed_incremental_runtime_v3
    with pytest.raises(ValueError):
        build_reviewed_incremental_v3(runtime, reviewed_incremental_source_use_component_v1,
            "source-use-selector-refused", instance_identity_profile=selector)
    assert runtime["compiler"].calls == []
    assert not (runtime["directory"] / "source-use-selector-refused").exists()


@pytest.mark.parametrize("direction", ["old-to-bound", "bound-to-old"])
def test_reviewed_source_use_incremental_caches_cannot_cross_identity_domains(
        reviewed_incremental_runtime_v3, reviewed_incremental_component_v3,
        reviewed_incremental_source_use_component_v1, direction):
    runtime = reviewed_incremental_runtime_v3
    old = build_reviewed_incremental_v3(runtime, reviewed_incremental_component_v3, "legacy-domain-positive")
    bound = build_reviewed_incremental_source_use_v1(runtime,
        reviewed_incremental_source_use_component_v1, "bound-domain-positive")
    assert old[0]["build_passed"] is bound[0]["build_passed"] is True
    before = len(runtime["compiler"].calls)
    control, previous, selected = ((reviewed_incremental_source_use_component_v1, old, "reviewed-source-use/v1")
        if direction == "old-to-bound" else (reviewed_incremental_component_v3, bound, None))
    with pytest.raises(ValueError, match="qualified technical cache|profile"):
        build_reviewed_incremental_v3(runtime, control, "cross-domain-refused", previous=previous,
            instance_identity_profile=selected)
    assert len(runtime["compiler"].calls) == before
    assert not (runtime["directory"] / "cross-domain-refused").exists()


@pytest.fixture(scope="module")
def reviewed_incremental_source_use_cold_seed_v1(tmp_path_factory, reviewed_incremental_source_use_component_v1):
    """One authored healthy cold build; each adversarial case copies its cache and artifact mapping."""
    directory = tmp_path_factory.mktemp("reviewed-incremental-source-use-cold-seed", numbered=False)
    with pytest.MonkeyPatch.context() as monkeypatch:
        runtime = reviewed_incremental_runtime_v3.__wrapped__(monkeypatch, directory)
        cold = build_reviewed_incremental_source_use_v1(
            runtime, reviewed_incremental_source_use_component_v1, "binding-positive")
        assert cold[0]["build_passed"] is True
        yield {"runtime": runtime, "cache": cache(cold), "artifacts": artifacts(cold)}


@pytest.mark.parametrize("damage", ["missing-binding", "binding-digest", "foreign-binding", "extra-binding-key",
    "old-child-profile", "missing-companion", "missing-obligation"])
def test_reviewed_source_use_incremental_prior_provenance_cannot_be_resealed_into_another_unit(
        reviewed_incremental_source_use_cold_seed_v1, reviewed_incremental_source_use_component_v1, damage):
    seed, control = reviewed_incremental_source_use_cold_seed_v1, reviewed_incremental_source_use_component_v1
    runtime = seed["runtime"]
    saved, raw_artifacts = deepcopy(seed["cache"]), dict(seed["artifacts"])
    fact = next(row for row in saved["module_facts"]
        if row["recipe"]["reviewed_provenance"]["role"] == "instance")
    unit = fact["recipe"]["reviewed_provenance"]["contributors"][0]
    if damage == "missing-binding": unit.pop("source_use_binding")
    elif damage == "binding-digest": unit["source_use_binding_sha256"] = "f" * 64
    elif damage == "foreign-binding":
        unit["source_use_binding"]["unit_id"] += ":other-physical-unit"
        unit["source_use_binding_sha256"] = sha(canonical_dag_json_bytes(unit["source_use_binding"]))
    elif damage == "extra-binding-key":
        unit["source_use_binding"]["unreviewed"] = "not-an-identity-input"
        unit["source_use_binding_sha256"] = sha(canonical_dag_json_bytes(unit["source_use_binding"]))
    elif damage == "old-child-profile": unit["child_preservation_profile"] = unit["child_preservation_profile"].split("+", 1)[0]
    elif damage == "missing-companion": unit["original_child_files"].pop()
    else: unit["preservation_obligations"].pop()
    fact["output"]["recipe_cid"] = runtime["incremental"].cid_for_dag_json(fact["recipe"])
    raw = canonical_dag_json_bytes(reseal(saved))
    before = len(runtime["compiler"].calls)
    with pytest.raises(ValueError):
        build_reviewed_incremental_source_use_v1(runtime, control, "binding-refused",
            previous_cache_raw=raw, expected_previous_cache_sha256=sha(raw), previous_artifacts=raw_artifacts)
    assert len(runtime["compiler"].calls) == before
    assert not (runtime["directory"] / "binding-refused").exists()


def test_reviewed_source_use_incremental_changed_physical_identity_matches_clean_build(
        reviewed_incremental_runtime_v3, reviewed_incremental_component_v3,
        reviewed_incremental_source_use_component_v1):
    runtime, original = reviewed_incremental_runtime_v3, reviewed_incremental_source_use_component_v1
    changed = reviewed_incremental_source_use_control_v1(reviewed_incremental_component_v3,
        "nonoverlapping_paragraphs_different_source_id")
    cold = build_reviewed_incremental_source_use_v1(runtime, original, "physical-cold")
    updated = build_reviewed_incremental_source_use_v1(runtime, changed, "physical-updated", previous=cold)
    clean = build_reviewed_incremental_source_use_v1(runtime, changed, "physical-clean")
    assert updated[0]["build_passed"] is clean[0]["build_passed"] is True
    assert updated[0]["compiled_modules"]
    assert artifacts(updated) == artifacts(clean)
    assert updated[0]["artifact_root_cid"] == clean[0]["artifact_root_cid"]
    assert len(updated[0]["fresh_theorems"]) + len(updated[0]["reused_theorems"]) == 15
    old_units = original["preparation"].to_dict()["units"]
    new_units = changed["preparation"].to_dict()["units"]
    assert any(a["source_use_binding_sha256"] != b["source_use_binding_sha256"]
        for a, b in zip(old_units, new_units))
    assert updated[0]["units"] == new_units and len(new_units) == 3
    assert not (set(cold[0]["expected_modules"]) - set(clean[0]["expected_modules"])) & set(artifacts(updated))


@pytest.mark.parametrize("when", ["opening", "closing"])
def test_reviewed_source_use_incremental_warm_replays_current_signed_revocation(
        reviewed_incremental_runtime_v3, reviewed_incremental_source_use_component_v1, monkeypatch, when):
    runtime, original = reviewed_incremental_runtime_v3, reviewed_incremental_source_use_component_v1
    cold = build_reviewed_incremental_source_use_v1(runtime, original, "source-use-revocation-positive")
    helper = original["mixed_helper"]
    case = helper.cloned(original["case"])
    args, kwargs = helper.fixture.reviewed_assessment_arguments_v2(original["owner"], case)
    control = dict(original, case=case, args=args, kwargs=kwargs)
    def revoke():
        case["registry"]["revocation_generation"] += 1
        case["registry"]["keys"][0]["revoked_at_utc"] = helper.fixture.EVALUATED
        helper.fixture.reviewed_resign_v2(case)
        helper.assert_signatures_valid(case)
        control["args"], control["kwargs"] = helper.fixture.reviewed_assessment_arguments_v2(original["owner"], case)
    before = len(runtime["compiler"].calls)
    if when == "opening":
        revoke()
        with pytest.raises(ValueError):
            build_reviewed_incremental_source_use_v1(runtime, control, "source-use-revoked-opening", previous=cold)
        assert not (runtime["directory"] / "source-use-revoked-opening").exists()
    else:
        original_replay = runtime["incremental"]._reviewed_replay
        calls = []
        def replay(preparation, inputs, pin, toolchain):
            calls.append(True)
            if len(calls) == 2:
                revoke()
                inputs["args"], inputs["kwargs"] = control["args"], control["kwargs"]
            return original_replay(preparation, inputs, pin, toolchain)
        monkeypatch.setattr(runtime["incremental"], "_reviewed_replay", replay)
        failed = build_reviewed_incremental_source_use_v1(runtime, control, "source-use-revoked-closing", previous=cold)
        assert failed[0]["build_passed"] is False and failed[0]["post_run_validation_error"] is not None
        assert cache(failed)["qualified"] is False
        assert artifacts(failed) == artifacts(cold)
    assert len(runtime["compiler"].calls) == before


def test_reviewed_source_use_incremental_selector_mutation_after_replay_refuses_before_execution(
        reviewed_incremental_runtime_v3, reviewed_incremental_source_use_component_v1, monkeypatch):
    runtime, control = reviewed_incremental_runtime_v3, reviewed_incremental_source_use_component_v1
    replay = runtime["incremental"]._reviewed_replay
    def mutate(preparation, inputs, pin, toolchain):
        result = replay(preparation, inputs, pin, toolchain)
        inputs["instance_identity_profile"] = None
        return result
    monkeypatch.setattr(runtime["incremental"], "_reviewed_replay", mutate)
    with pytest.raises(ValueError, match="identity snapshot|identity selection"):
        build_reviewed_incremental_source_use_v1(runtime, control, "source-use-selector-mutated")
    assert runtime["compiler"].calls == []
    assert not (runtime["directory"] / "source-use-selector-mutated").exists()


# The following controls are fictional signed-source/software fixtures. The
# existing AuthoredParentIncrementalCompiler supplies synthetic bytes/lifecycle
# and axiom strings; none of these controls executes Lean or authenticates a
# Native process, proof, legal interpretation, or reviewed statutory corpus.
@pytest.fixture(scope="module")
def reviewed_incremental_realization_v1(reviewed_incremental_component_v3):
    control = dict(reviewed_incremental_component_v3)
    control["realization"] = shared.prepare_reviewed_definition_realization_corpus_v1(
        control["preparation"], control["graph"], control["admission"], *control["args"],
        expected_preservation_sha256=shared.reviewed_preservation_corpus_sha256(control["preparation"]),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN, **control["kwargs"])
    return control


def build_reviewed_incremental_realization_v1(runtime, control, name, *, previous=None, **overrides):
    arguments = dict(expected_realization_sha256=shared.reviewed_preservation_corpus_sha256(control["realization"]),
        expected_preservation_sha256=shared.reviewed_preservation_corpus_sha256(control["preparation"]),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN, lake_executable=str(runtime["compiler"].lake),
        output_directory=runtime["directory"] / name, **control["kwargs"])
    if previous is not None:
        raw = (previous[1] / "cache.json").read_bytes()
        arguments.update(previous_cache_raw=raw, expected_previous_cache_sha256=sha(raw),
            previous_artifacts=artifacts(previous))
    arguments.update(overrides)
    receipt = runtime["incremental"].build_incremental_reviewed_definition_realization_corpus_v1(
        control["realization"], control["preparation"], control["graph"], control["admission"],
        *control["args"], **arguments)
    return receipt, runtime["directory"] / name


def test_reviewed_incremental_realization_v1_preserves_all_old_children_and_cold_warm_complete_obligations(
        reviewed_incremental_runtime_v3, reviewed_incremental_realization_v1):
    runtime, control = reviewed_incremental_runtime_v3, reviewed_incremental_realization_v1
    old = build_reviewed_incremental_v3(runtime, control, "old-independent-v3")
    cold = build_reviewed_incremental_realization_v1(runtime, control, "realization-cold")
    calls = len(runtime["compiler"].calls)
    warm = build_reviewed_incremental_realization_v1(runtime, control, "realization-warm", previous=cold)
    original, complete = control["preparation"].to_dict(), control["realization"].to_dict()
    assert old[0]["build_passed"] is cold[0]["build_passed"] is warm[0]["build_passed"] is True
    assert original["expected_modules"] == complete["expected_modules"][:-2]
    assert len(original["expected_modules"]) == len(old[0]["compiled_modules"]) == 8
    assert len(cold[0]["compiled_modules"]) == len(warm[0]["reused_modules"]) == 10
    assert len(cold[0]["fresh_theorems"]) == len(warm[0]["reused_theorems"]) == 26
    assert sorted(cold[0]["fresh_theorems"]) == sorted(complete["preservation_obligations"])
    assert warm[0]["reused_theorems"] == cold[0]["fresh_theorems"]
    assert warm[0]["compiled_modules"] == warm[0]["fresh_theorems"] == []
    assert len(runtime["compiler"].calls) == calls
    assert artifacts(cold) == artifacts(warm)
    assert {name: artifacts(cold)[name] for name in original["expected_modules"]} == artifacts(old)
    assert warm[0]["reviewed_preservation_sha256"] == shared.reviewed_preservation_corpus_sha256(control["preparation"])
    assert warm[0]["expected_preparation_sha256"] == shared.reviewed_preservation_corpus_sha256(control["realization"])
    assert warm[0]["reviewed_graph_sha256"] == control["graph_sha"]
    assert warm[0]["reviewed_admission_sha256"] == control["admission_sha"]
    saved = cache(warm)
    assert saved["schema"] == runtime["incremental"].REALIZATION_CACHE_SCHEMA
    assert saved["execution_contract"]["schema"] == runtime["incremental"].REALIZATION_CONTRACT_SCHEMA
    assert saved["profile"] == runtime["incremental"].REALIZATION_PROFILE != cache(old)["profile"]
    for row in saved["module_facts"]:
        provenance = row["recipe"]["realization_provenance"]
        binding = provenance["realization_binding"]
        assert "reviewed_provenance" not in row["recipe"]
        assert binding["units"] == original["units"]
        assert binding["selection"] == complete["selection"]
        assert binding["original_file_sha256"] == original["file_sha256"]
        assert binding["producer_pins"] == complete["producer_pins"]
        assert binding["native_producer_pins"] == complete["native_producer_pins"]
    assert all(raw.startswith(b"authored-fake-olean-no-native-proof\0") for raw in artifacts(warm).values())
    assert warm[0]["constructed_model_obligations_checked"] is True
    assert warm[0]["composition_obligations_checked"] is False
    assert warm[0]["fresh_proof_for_reused_modules"] is False
    assert warm[0]["live_native_success_authenticated"] is warm[0]["original_success_authenticated"] is False
    assert warm[0]["statutory_meaning_proved"] is warm[0]["release_ready"] is False
    assert not any(warm[0]["authority"].values())
    assert warm[0]["training_mask"] == warm[0]["evaluation_gold_mask"] == 0


@pytest.mark.parametrize("pin", ["expected_realization_sha256", "expected_preservation_sha256",
    "expected_graph_sha256", "expected_admission_sha256"])
def test_reviewed_incremental_realization_v1_every_independent_pin_refuses_before_toolchain(
        reviewed_incremental_runtime_v3, reviewed_incremental_realization_v1, pin):
    runtime = reviewed_incremental_runtime_v3
    with pytest.raises(ValueError):
        build_reviewed_incremental_realization_v1(runtime, reviewed_incremental_realization_v1,
            "realization-pin-refused", **{pin: "f" * 64})
    assert runtime["compiler"].calls == []
    assert not (runtime["directory"] / "realization-pin-refused").exists()


@pytest.mark.parametrize("direction", ["v3-to-realization", "realization-to-v3"])
def test_reviewed_incremental_realization_v1_never_retags_prior_cache_domains(
        reviewed_incremental_runtime_v3, reviewed_incremental_realization_v1, direction):
    runtime, control = reviewed_incremental_runtime_v3, reviewed_incremental_realization_v1
    if direction == "v3-to-realization":
        first = build_reviewed_incremental_v3(runtime, control, "v3-domain-original")
        builder = build_reviewed_incremental_realization_v1
    else:
        first = build_reviewed_incremental_realization_v1(runtime, control, "realization-domain-original")
        builder = build_reviewed_incremental_v3
    before = len(runtime["compiler"].calls)
    with pytest.raises(ValueError):
        builder(runtime, control, "wrong-domain-refused", previous=first)
    assert len(runtime["compiler"].calls) == before
    assert not (runtime["directory"] / "wrong-domain-refused").exists()


@pytest.mark.parametrize("facet", ["definition", "role", "sort"])
def test_reviewed_incremental_realization_v1_genuine_corrected_meaning_invalidates_complete_binding(
        reviewed_incremental_runtime_v3, reviewed_incremental_realization_v1, facet):
    runtime, control = reviewed_incremental_runtime_v3, reviewed_incremental_realization_v1
    cold = build_reviewed_incremental_realization_v1(runtime, control, "realization-correction-cold")
    changed = reviewed_incremental_changed_component_v3(control, facet)
    changed["realization"] = shared.prepare_reviewed_definition_realization_corpus_v1(
        changed["preparation"], changed["graph"], changed["admission"], *changed["args"],
        expected_preservation_sha256=shared.reviewed_preservation_corpus_sha256(changed["preparation"]),
        expected_graph_sha256=changed["graph_sha"], expected_admission_sha256=changed["admission_sha"],
        toolchain=TOOLCHAIN, **changed["kwargs"])
    updated = build_reviewed_incremental_realization_v1(runtime, changed, "realization-correction-updated", previous=cold)
    clean = build_reviewed_incremental_realization_v1(runtime, changed, "realization-correction-clean")
    assert updated[0]["build_passed"] is clean[0]["build_passed"] is True
    assert updated[0]["reused_modules"] == []  # full current source/review binding invalidates conservatively
    assert artifacts(updated) == artifacts(clean)
    assert updated[0]["artifact_root_cid"] == clean[0]["artifact_root_cid"]
    assert len(updated[0]["fresh_theorems"]) == 26
    before_binding = cache(cold)["module_facts"][0]["recipe"]["realization_provenance"]["realization_binding"]
    after_binding = cache(updated)["module_facts"][0]["recipe"]["realization_provenance"]["realization_binding"]
    assert before_binding["preservation_sha256"] != after_binding["preservation_sha256"]
    assert before_binding["admission_sha256"] != after_binding["admission_sha256"]
    if facet == "definition":
        assert before_binding["selection"]["body_typed_sha256"] != after_binding["selection"]["body_typed_sha256"]
    assert not (set(cold[0]["expected_modules"]) - set(clean[0]["expected_modules"])) & set(artifacts(updated))


@pytest.mark.parametrize("change", ["compiler", "library"])
def test_reviewed_incremental_realization_v1_compiler_or_library_change_invalidates_all_artifacts(
        reviewed_incremental_runtime_v3, reviewed_incremental_realization_v1, change):
    runtime, control = reviewed_incremental_runtime_v3, reviewed_incremental_realization_v1
    cold = build_reviewed_incremental_realization_v1(runtime, control, "realization-toolchain-cold")
    if change == "compiler":
        runtime["compiler"].lean.write_bytes(b"authored-changed-compiler-no-native")
    else:
        runtime["compiler"].library_salt = "authored-changed-library-no-native"
    updated = build_reviewed_incremental_realization_v1(runtime, control, "realization-toolchain-updated", previous=cold)
    assert updated[0]["build_passed"] is True
    assert updated[0]["reused_modules"] == []
    assert sorted(updated[0]["compiled_modules"]) == sorted(control["realization"].to_dict()["expected_modules"])


@pytest.mark.parametrize("damage", ["missing-binding", "extra-binding-field", "body-digest", "source-occurrence",
    "ordered-role", "unit-ordinal", "original-file-pin", "producer-pin", "missing-occurrence"])
def test_reviewed_incremental_realization_v1_self_resealed_cache_cannot_remove_or_forge_complete_binding(
        reviewed_incremental_runtime_v3, reviewed_incremental_realization_v1, damage):
    from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json
    runtime, control = reviewed_incremental_runtime_v3, reviewed_incremental_realization_v1
    cold = build_reviewed_incremental_realization_v1(runtime, control, "realization-provenance-cold")
    saved = cache(cold)
    fact = saved["module_facts"][-2]
    provenance = fact["recipe"]["realization_provenance"]
    binding = provenance["realization_binding"]
    if damage == "missing-binding":
        del provenance["realization_binding"]
    elif damage == "extra-binding-field":
        binding["unreviewed_identity_alias"] = "must refuse"
    elif damage == "body-digest":
        binding["selection"]["body_typed_sha256"] = "a" * 64
        binding["selection_sha256"] = sha(canonical_dag_json_bytes(binding["selection"]))
    elif damage == "source-occurrence":
        binding["selection"]["occurrences"][0]["source_occurrence_cid"] = binding["units"][0]["source_occurrence_cid"]
        binding["selection_sha256"] = sha(canonical_dag_json_bytes(binding["selection"]))
    elif damage == "ordered-role":
        binding["selection"]["occurrences"][0]["ordered_roles"] = ["supervisor"]
        binding["selection_sha256"] = sha(canonical_dag_json_bytes(binding["selection"]))
    elif damage == "unit-ordinal":
        binding["units"][0]["ordinal"] = False
    elif damage == "original-file-pin":
        binding["original_file_sha256"][next(iter(binding["original_file_sha256"]))] = "wrong"
    elif damage == "producer-pin":
        binding["producer_pins"][next(iter(binding["producer_pins"]))] = "wrong"
    else:
        binding["selection"]["occurrences"].pop()
        binding["selection_sha256"] = sha(canonical_dag_json_bytes(binding["selection"]))
    fact["output"]["recipe_cid"] = cid_for_dag_json(fact["recipe"])
    raw = canonical_dag_json_bytes(reseal(saved))
    before = len(runtime["compiler"].calls)
    with pytest.raises(ValueError):
        build_reviewed_incremental_realization_v1(runtime, control, "realization-provenance-refused",
            previous_cache_raw=raw, expected_previous_cache_sha256=sha(raw), previous_artifacts=artifacts(cold))
    assert len(runtime["compiler"].calls) == before
    assert not (runtime["directory"] / "realization-provenance-refused").exists()


@pytest.mark.parametrize("damage", ["duplicate", "stderr_claim"])
def test_reviewed_incremental_realization_v1_requires_exact_native_observation_for_new_theorems(
        reviewed_incremental_runtime_v3, reviewed_incremental_realization_v1, monkeypatch, damage):
    runtime, control = reviewed_incremental_runtime_v3, reviewed_incremental_realization_v1
    compiler = runtime["compiler"]
    original_run = compiler.run
    model = control["realization"].to_dict()["expected_modules"][-2]
    model_path = model.replace(".", "/") + ".lean"
    assert model.startswith("LegalReviewedDefinitionRealization.Instance")
    assert len(re.findall(r"^theorem ([A-Za-z0-9_]+)",
        dict(control["realization"].files)[model_path], re.M)) == 11
    selected = []
    def damage_only_new_model(runner, request, **kwargs):
        previous = compiler.axiom_damage
        if request.argv[-1] == model_path:
            selected.append(model)
            compiler.axiom_damage = damage
        try:
            return original_run(runner, request, **kwargs)
        finally:
            compiler.axiom_damage = previous
    monkeypatch.setattr(native.process.BoundedToolRunner, "run", damage_only_new_model)
    result = build_reviewed_incremental_realization_v1(runtime, control, "realization-observation-refused")
    assert selected == [model]
    assert compiler.calls[-1]["module"] == model
    assert set(control["preparation"].to_dict()["preservation_obligations"]) <= set(result[0]["fresh_theorems"])
    assert result[0]["build_passed"] is False
    assert cache(result)["qualified"] is False
    assert result[0]["constructed_model_obligations_checked"] is False
    assert result[0]["live_native_success_authenticated"] is False


@pytest.mark.parametrize("subject", ["graph", "admission"])
def test_reviewed_incremental_realization_v1_late_retention_callback_cannot_publish_changed_current_inputs(
        reviewed_incremental_runtime_v3, reviewed_incremental_realization_v1, monkeypatch, subject):
    runtime, original = reviewed_incremental_runtime_v3, reviewed_incremental_realization_v1
    control = dict(original, graph=deepcopy(original["graph"]), admission=deepcopy(original["admission"]))
    original_write = shared._write_compiled
    seen = []
    def change_after_retained_write(*args, **kwargs):
        result = original_write(*args, **kwargs)
        seen.append(True)
        if subject == "admission":
            control["admission"]["formal_assumptions"].append("Unreviewed late caller assumption.")
        else:
            control["graph"]["definition_use_records"][0]["use_unit_id"] += ":unreviewed"
        return result
    monkeypatch.setattr(shared, "_write_compiled", change_after_retained_write)
    with pytest.raises(ValueError):
        build_reviewed_incremental_realization_v1(runtime, control, "realization-late-input-refused")
    assert seen == [True]
    assert not (runtime["directory"] / "realization-late-input-refused" / "build-receipt.json").exists()


@pytest.mark.parametrize("field", ["MAX_REVIEWED_PRESERVATION_FILES", "MAX_REVIEWED_PRESERVATION_MODULES",
    "MAX_REVIEWED_PRESERVATION_OBLIGATIONS"])
def test_reviewed_incremental_realization_v1_cannot_raise_shared_support_bounds(
        reviewed_incremental_runtime_v3, reviewed_incremental_realization_v1, monkeypatch, field):
    runtime = reviewed_incremental_runtime_v3
    monkeypatch.setattr(shared, field, getattr(shared, field) + 1)
    with pytest.raises(ValueError):
        build_reviewed_incremental_realization_v1(runtime, reviewed_incremental_realization_v1,
            "realization-bound-refused")
    assert runtime["compiler"].calls == []
    assert not (runtime["directory"] / "realization-bound-refused").exists()


# Two healthy authored seeds (default and explicit selected mode) are built
# once. Mutants copy caches/artifact mappings and never repeat a cold compile.
@pytest.fixture(scope="module")
def reviewed_incremental_realization_source_use_v1(reviewed_incremental_component_v3):
    control = dict(reviewed_incremental_component_v3)
    control["preparation"] = _FIXTURE_MODULE.reviewed_source_use_prepare_fixture(control, 3)
    assert _FIXTURE_MODULE.reviewed_source_use_validate_fixture(control, 3, control["preparation"]) == control["preparation"]
    control["realization"] = shared.prepare_reviewed_definition_realization_corpus_v1(
        control["preparation"], control["graph"], control["admission"], *control["args"],
        expected_preservation_sha256=shared.reviewed_preservation_corpus_sha256(control["preparation"]),
        expected_graph_sha256=control["graph_sha"], expected_admission_sha256=control["admission_sha"],
        toolchain=TOOLCHAIN, instance_identity_profile="reviewed-source-use/v1", **control["kwargs"])
    return control


@pytest.fixture(scope="module")
def reviewed_incremental_realization_source_use_cold_seed_v1(tmp_path_factory,
        reviewed_incremental_realization_v1, reviewed_incremental_realization_source_use_v1):
    directory = tmp_path_factory.mktemp("reviewed-realization-source-use-incremental-seed", numbered=False)
    with pytest.MonkeyPatch.context() as patcher:
        runtime = reviewed_incremental_runtime_v3.__wrapped__(patcher, directory)
        seeds = {}
        for label, control, selector in (("default", reviewed_incremental_realization_v1, None),
                ("selected", reviewed_incremental_realization_source_use_v1, "reviewed-source-use/v1")):
            before = len(runtime["compiler"].calls)
            cold = build_reviewed_incremental_realization_v1(runtime, control, label + "-healthy-cold",
                instance_identity_profile=selector)
            assert cold[0]["build_passed"] is True
            assert len(runtime["compiler"].calls) - before == len(cold[0]["compiled_modules"]) == 10
            seeds[label] = dict(cold=cold, cache=cache(cold), artifacts=artifacts(cold))
        yield dict(runtime=runtime, seeds=seeds)


def test_reviewed_realization_source_use_incremental_cold10_warm0_preserves_every_binding_and_all26(
        reviewed_incremental_realization_source_use_cold_seed_v1, reviewed_incremental_realization_source_use_v1):
    seed, control = reviewed_incremental_realization_source_use_cold_seed_v1, reviewed_incremental_realization_source_use_v1
    runtime, cold = seed["runtime"], seed["seeds"]["selected"]
    before = len(runtime["compiler"].calls)
    raw = canonical_dag_json_bytes(deepcopy(cold["cache"]))
    warm = build_reviewed_incremental_realization_v1(runtime, control, "selected-warm-positive",
        instance_identity_profile="reviewed-source-use/v1", previous_cache_raw=raw,
        expected_previous_cache_sha256=sha(raw), previous_artifacts=dict(cold["artifacts"]))
    assert warm[0]["build_passed"] is True and len(runtime["compiler"].calls) == before
    assert warm[0]["compiled_modules"] == warm[0]["fresh_theorems"] == []
    assert len(warm[0]["reused_modules"]) == 10 and len(warm[0]["reused_theorems"]) == 26
    assert sorted(warm[0]["reused_theorems"]) == sorted(control["realization"].to_dict()["preservation_obligations"])
    assert artifacts(warm) == cold["artifacts"]
    saved = cache(warm)
    assert saved["profile"] == runtime["incremental"].REALIZATION_PROFILE + "+reviewed-source-use/v1"
    assert saved["execution_contract"]["profile"] == saved["profile"]
    assert warm[0]["instance_identity_profile"] == "reviewed-source-use/v1"
    units = control["preparation"].to_dict()["units"]
    by_id, seen = {row["unit_id"]: row for row in units}, set()
    for fact in saved["module_facts"]:
        assert fact["recipe"]["contract_cid"] == saved["execution_contract"]["record_cid"]
        provenance = fact["recipe"]["realization_provenance"]
        assert "reviewed_provenance" not in fact["recipe"]
        binding = provenance["realization_binding"]
        assert binding["instance_identity_profile"] == "reviewed-source-use/v1"
        assert binding["units"] == units
        for contributor in provenance["contributors"] + provenance["dependency_units"]:
            expected = by_id[contributor["unit_id"]]
            assert contributor["source_use_binding"] == expected["source_use_binding"]
            assert contributor["source_use_binding_sha256"] == expected["source_use_binding_sha256"]
            assert sha(canonical_dag_json_bytes(contributor["source_use_binding"])) == contributor["source_use_binding_sha256"]
            seen.add(contributor["unit_id"])
    assert seen == set(by_id) and len(seen) == 3
    assert warm[0]["fresh_proof_for_reused_modules"] is False
    assert warm[0]["live_native_success_authenticated"] is warm[0]["original_success_authenticated"] is False
    assert warm[0]["cross_unit_definition_application_proved"] is warm[0]["statutory_meaning_proved"] is False
    assert not any(warm[0]["authority"].values())
    assert warm[0]["training_mask"] == warm[0]["evaluation_gold_mask"] == 0
    assert all(raw.startswith(b"authored-fake-olean-no-native-proof\0") for raw in artifacts(warm).values())


@pytest.mark.parametrize("direction", ["default-to-selected", "selected-to-default"])
def test_reviewed_realization_incremental_caches_cannot_cross_explicit_identity_domains(
        reviewed_incremental_realization_source_use_cold_seed_v1, reviewed_incremental_realization_v1,
        reviewed_incremental_realization_source_use_v1, direction):
    seed = reviewed_incremental_realization_source_use_cold_seed_v1
    runtime = seed["runtime"]
    if direction == "default-to-selected":
        offered, control, selector = seed["seeds"]["default"], reviewed_incremental_realization_source_use_v1, "reviewed-source-use/v1"
    else:
        offered, control, selector = seed["seeds"]["selected"], reviewed_incremental_realization_v1, None
    raw = canonical_dag_json_bytes(deepcopy(offered["cache"]))
    before = len(runtime["compiler"].calls)
    output = "realization-cross-mode-" + direction
    with pytest.raises(ValueError):
        build_reviewed_incremental_realization_v1(runtime, control, output,
            instance_identity_profile=selector, previous_cache_raw=raw,
            expected_previous_cache_sha256=sha(raw), previous_artifacts=dict(offered["artifacts"]))
    assert len(runtime["compiler"].calls) == before
    assert not (runtime["directory"] / output).exists()


@pytest.mark.parametrize("damage", ["selector", "contributor-binding", "contributor-digest"])
def test_reviewed_realization_source_use_incremental_resealed_cache_cannot_change_current_binding(
        reviewed_incremental_realization_source_use_cold_seed_v1, reviewed_incremental_realization_source_use_v1, damage):
    seed, control = reviewed_incremental_realization_source_use_cold_seed_v1, reviewed_incremental_realization_source_use_v1
    runtime, cold = seed["runtime"], seed["seeds"]["selected"]
    saved = deepcopy(cold["cache"])
    fact = next(row for row in saved["module_facts"] if row["recipe"]["realization_provenance"]["role"] == "instance")
    provenance = fact["recipe"]["realization_provenance"]
    if damage == "selector":
        provenance["realization_binding"]["instance_identity_profile"] = "reviewed-source-use/v2"
    else:
        unit = provenance["contributors"][0]
        if damage == "contributor-binding":
            unit["source_use_binding"]["unit_id"] += ":other-physical-source"
            unit["source_use_binding_sha256"] = sha(canonical_dag_json_bytes(unit["source_use_binding"]))
        else: unit["source_use_binding_sha256"] = "f" * 64
    fact["output"]["recipe_cid"] = runtime["incremental"].cid_for_dag_json(fact["recipe"])
    raw = canonical_dag_json_bytes(reseal(saved))
    before = len(runtime["compiler"].calls)
    output = "realization-selected-binding-refused-" + damage
    with pytest.raises(ValueError):
        build_reviewed_incremental_realization_v1(runtime, control, output,
            instance_identity_profile="reviewed-source-use/v1", previous_cache_raw=raw,
            expected_previous_cache_sha256=sha(raw), previous_artifacts=dict(cold["artifacts"]))
    assert len(runtime["compiler"].calls) == before
    assert not (runtime["directory"] / output).exists()


# Four authored cache domains reuse the existing fake compiler and signed
# fictional source fixture. These observations are not Lean or legal proof.
@pytest.fixture(scope="module")
def reviewed_incremental_whole_norm_cold_seeds_v1(
        reviewed_incremental_realization_source_use_cold_seed_v1,
        reviewed_incremental_realization_v1, reviewed_incremental_realization_source_use_v1):
    prior = reviewed_incremental_realization_source_use_cold_seed_v1
    runtime = prior["runtime"]
    domains = {}
    for label, control, identity in (("default", reviewed_incremental_realization_v1, None),
            ("source-use", reviewed_incremental_realization_source_use_v1, "reviewed-source-use/v1")):
        legacy = prior["seeds"]["default" if identity is None else "selected"]
        assert legacy["cold"][0]["build_passed"] is True
        assert len(legacy["cold"][0]["fresh_theorems"]) == 26
        assert len(legacy["cold"][0]["compiled_modules"]) == 10
        domains["legacy-" + label] = {**legacy, "control": control,
            "identity": identity, "application": None}
        selected = dict(control)
        identity_keywords = {} if identity is None else {"instance_identity_profile": identity}
        selected["realization"] = shared.prepare_reviewed_definition_realization_corpus_v1(
            selected["preparation"], selected["graph"], selected["admission"], *selected["args"],
            expected_preservation_sha256=shared.reviewed_preservation_corpus_sha256(selected["preparation"]),
            expected_graph_sha256=selected["graph_sha"], expected_admission_sha256=selected["admission_sha"],
            toolchain=TOOLCHAIN, definition_application_profile="whole-norm-definition-expansion/v1",
            **identity_keywords, **selected["kwargs"])
        before = len(runtime["compiler"].calls)
        cold = build_reviewed_incremental_realization_v1(runtime, selected, "whole-norm-" + label + "-healthy-cold",
            definition_application_profile="whole-norm-definition-expansion/v1", **identity_keywords)
        assert cold[0]["build_passed"] is True
        assert len(runtime["compiler"].calls) - before == len(cold[0]["compiled_modules"]) == 10
        assert len(cold[0]["fresh_theorems"]) == 30
        domains["whole-" + label] = dict(cold=cold, cache=cache(cold), artifacts=artifacts(cold),
            control=selected, identity=identity, application="whole-norm-definition-expansion/v1")
    assert len({row["cache"]["profile"] for row in domains.values()}) == 4
    return dict(runtime=runtime, domains=domains)


@pytest.mark.parametrize("domain", ["whole-default", "whole-source-use"])
def test_reviewed_whole_norm_incremental_cold10_warm0_preserves_all30_and_actual_contract(
        reviewed_incremental_whole_norm_cold_seeds_v1, domain):
    seed = reviewed_incremental_whole_norm_cold_seeds_v1
    runtime, selected = seed["runtime"], seed["domains"][domain]
    control = selected["control"]
    complete = control["realization"].to_dict()
    legacy = seed["domains"]["legacy-" + ("default" if selected["identity"] is None else "source-use")]
    original = legacy["control"]["realization"].to_dict()
    assert complete["upstream_manifest"] == original["upstream_manifest"]
    assert complete["units"] == original["units"]
    assert complete["selection"] == original["selection"]
    assert len(complete["expected_modules"]) == 10 and len(control["realization"].files) == 39
    assert len(complete["preservation_obligations"]) == 30
    assert len(complete["realization_obligations"]) == 15
    assert len(complete["definition_application_obligations"]) == 4
    assert len(complete["definition_applications"]) == 2
    assert complete["preservation_obligations"][:15] == original["preservation_obligations"][:15]
    before = len(runtime["compiler"].calls)
    raw = canonical_dag_json_bytes(deepcopy(selected["cache"]))
    assert len(raw) <= contracts.MAX_RECORD_BYTES == 1024 * 1024
    identity_keywords = {} if selected["identity"] is None else {"instance_identity_profile": selected["identity"]}
    warm = build_reviewed_incremental_realization_v1(runtime, control, domain + "-warm-positive",
        definition_application_profile="whole-norm-definition-expansion/v1", **identity_keywords,
        previous_cache_raw=raw, expected_previous_cache_sha256=sha(raw), previous_artifacts=dict(selected["artifacts"]))
    assert warm[0]["build_passed"] is True and len(runtime["compiler"].calls) == before
    assert warm[0]["compiled_modules"] == warm[0]["fresh_theorems"] == []
    assert len(warm[0]["reused_modules"]) == 10 and len(warm[0]["reused_theorems"]) == 30
    assert sorted(warm[0]["reused_theorems"]) == sorted(complete["preservation_obligations"])
    assert artifacts(warm) == selected["artifacts"]
    saved = cache(warm)
    suffix = (("+reviewed-source-use/v1" if selected["identity"] is not None else "")
        + "+whole-norm-definition-expansion/v1+interned-application-binding/v1")
    assert saved["profile"] == runtime["incremental"].REALIZATION_PROFILE + suffix
    assert saved["execution_contract"]["profile"] == saved["profile"]
    expected_binding = {
        "preparation_sha256": shared.reviewed_preservation_corpus_sha256(control["realization"]),
        "preservation_sha256": complete["reviewed_preservation_sha256"],
        "graph_sha256": complete["reviewed_graph_sha256"],
        "admission_sha256": complete["reviewed_admission_sha256"],
        "input_commitment_sha256": complete["input_commitment_sha256"],
        "declaration_sha256": complete["declaration_sha256"],
        "selection": complete["selection"],
        "selection_sha256": sha(canonical_dag_json_bytes(complete["selection"])),
        "units": complete["units"],
        "original_file_sha256": complete["upstream_manifest"]["file_sha256"],
        "producer_pins": complete["producer_pins"],
        "native_producer_pins": complete["native_producer_pins"],
        "definition_application_profile": "whole-norm-definition-expansion/v1",
        "definition_applications": complete["definition_applications"],
        "definition_application_obligations": complete["definition_application_obligations"],
        **identity_keywords,
    }
    expected_record = contracts.seal_record({
        "schema": "legal-corpus-reviewed-definition-application-binding/v1", "binding": expected_binding})
    for saved_cache, directory in ((selected["cache"], selected["cold"][1]), (saved, warm[1])):
        assert len((directory / "cache.json").read_bytes()) <= contracts.MAX_RECORD_BYTES
        assert saved_cache["execution_contract"]["realization_binding"] == expected_record
        assert canonical_dag_json_bytes(saved_cache).count(canonical_dag_json_bytes(expected_binding)) == 1
        assert len(saved_cache["module_facts"]) == 10
        for fact in saved_cache["module_facts"]:
            assert fact["recipe"]["contract_cid"] == saved_cache["execution_contract"]["record_cid"]
            provenance = fact["recipe"]["realization_provenance"]
            assert set(provenance) == {"module", "role", "contributors", "dependency_units",
                "dependency_record_cids", "realization_binding_cid"}
            assert provenance["realization_binding_cid"] == expected_record["record_cid"]
            assert "realization_binding" not in provenance
    binding = expected_record["binding"]
    if selected["identity"] is None:
        assert "instance_identity_profile" not in binding
    else:
        assert binding["instance_identity_profile"] == selected["identity"]
        assert binding["selection"]["source_use_bindings"] == complete["selection"]["source_use_bindings"]
    assert "realization_binding" not in legacy["cache"]["execution_contract"]
    assert all("realization_binding" in fact["recipe"]["realization_provenance"]
        and "realization_binding_cid" not in fact["recipe"]["realization_provenance"]
        for fact in legacy["cache"]["module_facts"])
    assert warm[0]["definition_applications"] == complete["definition_applications"]
    assert warm[0]["definition_application_obligations"] == complete["definition_application_obligations"]
    assert warm[0]["constructed_model_only"] is False
    assert warm[0]["cross_unit_definition_application_proved"] is False
    assert warm[0]["fresh_proof_for_reused_modules"] is False
    assert warm[0]["live_native_success_authenticated"] is warm[0]["original_success_authenticated"] is False
    assert not any(warm[0]["authority"].values())
    assert warm[0]["training_mask"] == warm[0]["evaluation_gold_mask"] == 0
    assert all(body.startswith(b"authored-fake-olean-no-native-proof\0") for body in artifacts(warm).values())


@pytest.mark.parametrize("source,target", [
    ("legacy-default", "whole-default"), ("whole-default", "legacy-default"),
    ("legacy-source-use", "whole-source-use"), ("whole-source-use", "legacy-source-use"),
    ("whole-default", "whole-source-use"), ("whole-source-use", "whole-default")])
def test_reviewed_whole_norm_incremental_cache_cannot_cross_explicit_domains(
        reviewed_incremental_whole_norm_cold_seeds_v1, source, target):
    seed = reviewed_incremental_whole_norm_cold_seeds_v1
    runtime = seed["runtime"]
    offered, selected = seed["domains"][source], seed["domains"][target]
    raw = canonical_dag_json_bytes(deepcopy(offered["cache"]))
    keywords = {}
    if selected["identity"] is not None:
        keywords["instance_identity_profile"] = selected["identity"]
    if selected["application"] is not None:
        keywords["definition_application_profile"] = selected["application"]
    before = len(runtime["compiler"].calls)
    output = "whole-norm-cross-domain-" + source + "-to-" + target
    with pytest.raises(ValueError):
        build_reviewed_incremental_realization_v1(runtime, selected["control"], output,
            previous_cache_raw=raw, expected_previous_cache_sha256=sha(raw),
            previous_artifacts=dict(offered["artifacts"]), **keywords)
    assert len(runtime["compiler"].calls) == before
    assert not (runtime["directory"] / output).exists()


@pytest.mark.parametrize("damage", ["selector", "missing-application", "typed-content-digest",
    "target-path", "obligation-order", "contract-cid"])
def test_reviewed_whole_norm_incremental_resealed_cache_cannot_forge_application_or_contract(
        reviewed_incremental_whole_norm_cold_seeds_v1, damage):
    seed = reviewed_incremental_whole_norm_cold_seeds_v1
    runtime, selected = seed["runtime"], seed["domains"]["whole-source-use"]
    saved = deepcopy(selected["cache"])
    fact = saved["module_facts"][-2]
    contract = saved["execution_contract"]
    binding_record = contract["realization_binding"]
    binding = binding_record["binding"]
    if damage == "selector":
        binding["definition_application_profile"] = "whole-norm-definition-expansion/v2"
    elif damage == "missing-application":
        binding["definition_applications"].pop()
    elif damage == "typed-content-digest":
        row = binding["definition_applications"][0]
        expression = json.loads(row["expanded_typed_expression"])
        expression["content_digest"] = "a" * 64
        row["expanded_typed_expression"] = canonical_dag_json_bytes(expression).decode("utf-8")
        row["expanded_typed_expression_sha256"] = sha(row["expanded_typed_expression"].encode("utf-8"))
    elif damage == "target-path":
        binding["definition_applications"][0]["target_typed_paths"][0] += "/extension/children/0"
    elif damage == "obligation-order":
        binding["definition_application_obligations"].reverse()
    if damage != "contract-cid":
        contract["realization_binding"] = reseal(binding_record)
        saved["execution_contract"] = reseal(contract)
        for row in saved["module_facts"]:
            row["recipe"]["realization_provenance"]["realization_binding_cid"] = contract["realization_binding"]["record_cid"]
            row["recipe"]["contract_cid"] = saved["execution_contract"]["record_cid"]
        assert all(row["recipe"]["realization_provenance"]["realization_binding_cid"]
            == contract["realization_binding"]["record_cid"] for row in saved["module_facts"])
    else:
        fact["recipe"]["contract_cid"] = runtime["incremental"].cid_for_dag_json({"other": "execution-contract"})
    for row in saved["module_facts"]:
        row["output"]["recipe_cid"] = runtime["incremental"].cid_for_dag_json(row["recipe"])
    raw = canonical_dag_json_bytes(reseal(saved))
    assert len(raw) <= contracts.MAX_RECORD_BYTES
    assert sha(raw) != sha(canonical_dag_json_bytes(selected["cache"]))
    before = len(runtime["compiler"].calls)
    output = "whole-norm-resealed-refused-" + damage
    with pytest.raises(ValueError):
        build_reviewed_incremental_realization_v1(runtime, selected["control"], output,
            definition_application_profile="whole-norm-definition-expansion/v1",
            instance_identity_profile="reviewed-source-use/v1", previous_cache_raw=raw,
            expected_previous_cache_sha256=sha(raw), previous_artifacts=dict(selected["artifacts"]))
    assert len(runtime["compiler"].calls) == before
    assert not (runtime["directory"] / output).exists()

@pytest.mark.parametrize("damage", ["missing-table", "extra-table-key", "changed-table-cid",
    "missing-reference", "foreign-reference", "extra-inline-binding", "uninterned-profile"])
def test_reviewed_whole_norm_incremental_interned_binding_refuses_resealed_wire_damage(
        reviewed_incremental_whole_norm_cold_seeds_v1, damage):
    seed = reviewed_incremental_whole_norm_cold_seeds_v1
    runtime, selected = seed["runtime"], seed["domains"]["whole-source-use"]
    saved = deepcopy(selected["cache"])
    contract = saved["execution_contract"]
    table = contract["realization_binding"]
    fact = saved["module_facts"][-2]
    provenance = fact["recipe"]["realization_provenance"]
    if damage == "missing-table":
        del contract["realization_binding"]
    elif damage == "extra-table-key":
        table["unexpected_binding"] = True
        contract["realization_binding"] = reseal(table)
    elif damage == "changed-table-cid":
        table["record_cid"] = runtime["incremental"].cid_for_dag_json({"other": "sealed-realization-binding"})
    elif damage == "missing-reference":
        del provenance["realization_binding_cid"]
    elif damage == "foreign-reference":
        provenance["realization_binding_cid"] = runtime["incremental"].cid_for_dag_json({"other": "binding-reference"})
    elif damage == "extra-inline-binding":
        provenance["realization_binding"] = deepcopy(table["binding"])
    else:
        suffix = "+interned-application-binding/v1"
        assert saved["profile"].endswith(suffix) and contract["profile"].endswith(suffix)
        saved["profile"] = saved["profile"][:-len(suffix)]
        contract["profile"] = contract["profile"][:-len(suffix)]
    saved["execution_contract"] = reseal(contract)
    for row in saved["module_facts"]:
        row["recipe"]["contract_cid"] = saved["execution_contract"]["record_cid"]
        if damage in {"extra-table-key", "changed-table-cid"}:
            row["recipe"]["realization_provenance"]["realization_binding_cid"] = contract["realization_binding"]["record_cid"]
        row["output"]["recipe_cid"] = runtime["incremental"].cid_for_dag_json(row["recipe"])
    raw = canonical_dag_json_bytes(reseal(saved))
    assert len(raw) <= contracts.MAX_RECORD_BYTES
    assert sha(raw) != sha(canonical_dag_json_bytes(selected["cache"]))
    before = len(runtime["compiler"].calls)
    output = "whole-norm-interned-wire-refused-" + damage
    with pytest.raises(ValueError):
        build_reviewed_incremental_realization_v1(runtime, selected["control"], output,
            definition_application_profile="whole-norm-definition-expansion/v1",
            instance_identity_profile="reviewed-source-use/v1", previous_cache_raw=raw,
            expected_previous_cache_sha256=sha(raw), previous_artifacts=dict(selected["artifacts"]))
    assert len(runtime["compiler"].calls) == before
    assert not (runtime["directory"] / output).exists()



@pytest.mark.parametrize("family", ["fol"])
def test_parent_incremental_installed_lean_failed_donor_evicts_descendants(
        installed_incremental_parent_lake, tmp_path, monkeypatch, family):
    """An actual compiler diagnostic evicts the cold dependents of an authored donor."""
    from dataclasses import asdict, replace

    from ipfs_datasets_py.logic.autoformal import legal_corpus_incremental as incremental

    support, executable, binary_pins = installed_incremental_parent_lake
    fixture = support.shared_fixture
    originals = tmp_path / "originals"
    independent_originals = tmp_path / "independent-originals"
    originals.mkdir()
    independent_originals.mkdir()
    original = fixture.parent_shared_family_examples(originals, family)["cases"][0]
    physical = {path: path.read_bytes() for path in originals.rglob("*") if path.is_file()}
    assert physical
    changed = fixture.parent_shared_family_examples(
        originals, family, donor_body_op="any")["cases"][0]
    assert physical == {path: path.read_bytes() for path in originals.rglob("*") if path.is_file()}
    independent = fixture.parent_shared_family_examples(independent_originals, family)["cases"][0]
    physical.update({path: path.read_bytes() for path in independent_originals.rglob("*")
                     if path.is_file()})
    for case in (original, changed, independent):
        assert case["assessment"]["evidence_assessment_status"] == "authenticated"
        assert case["review_inputs"]["registry"]["mode"] == "external_pinned_trust"

    original_inputs = fixture.parent_shared_arguments([original, independent])
    changed_inputs = fixture.parent_shared_arguments([changed, independent])
    preparation = shared.prepare_parent_shared_definition_use_corpus_v1(**original_inputs)
    changed_preparation = shared.prepare_parent_shared_definition_use_corpus_v1(**changed_inputs)
    prior_manifest, current_manifest = preparation.to_dict(), changed_preparation.to_dict()
    old_donor = fixture.parent_shared_definition(prior_manifest, 0, "donor")["module"]
    new_donor = fixture.parent_shared_definition(current_manifest, 0, "donor")["module"]
    assert old_donor != new_donor
    independent_joint = prior_manifest["components"][1]["joint_module"]
    assert current_manifest["components"][1]["joint_module"] == independent_joint
    independent_modules = {independent_joint, *prior_manifest["module_imports"][independent_joint]}

    def affected(manifest, donor):
        modules = {donor}
        while frontier := {module for module, imports in manifest["module_imports"].items()
                           if module not in modules and modules.intersection(imports)}:
            modules.update(frontier)
        return modules

    prior_affected = affected(prior_manifest, old_donor)
    current_affected = affected(current_manifest, new_donor)
    stable_descendants = (prior_affected & current_affected) - {old_donor, new_donor}
    stable_root = "LegalCorpusParent"
    assert stable_root in stable_descendants
    assert not (independent_modules & (prior_affected | current_affected))

    parent_native = incremental._parent_native()

    def build(prepared, inputs, output, **previous):
        return incremental.build_incremental_parent_shared_corpus_v1(
            prepared, **inputs,
            expected_preparation_sha256=parent_native.parent_shared_preparation_sha256(prepared),
            lake_executable=str(executable), output_directory=output,
            timeout_seconds=60, operation_timeout_seconds=3600, **previous)

    cold_path = tmp_path / "failed-donor-cold"
    cold = build(preparation, original_inputs, cold_path), cold_path
    cold_artifacts = artifacts(cold)
    cold_cache_raw = (cold_path / "cache.json").read_bytes()
    assert cold[0]["build_passed"] is cold[0]["lean_compilation_verified"] is True
    assert cache(cold)["qualified"] is True
    assert set(cold_artifacts) == set(prior_manifest["expected_modules"])
    assert stable_descendants <= cold_artifacts.keys()

    lean = str(executable.parent / "lean")
    donor_source = new_donor.replace(".", "/") + ".lean"
    donor_output = "compiled/" + donor_source.removesuffix(".lean") + ".olean"
    donor_command = (lean, "-o", donor_output, donor_source)
    frozen_donor_source = dict(changed_preparation.files)[donor_source].encode()
    marker = "lir15IntentionalUnknownForFailedDonor"
    diagnostic_tail = ("\n#check " + marker + "\n").encode()
    diagnostic_line = frozen_donor_source.count(b"\n") + 2
    diagnostic_pattern = re.compile(
        rf"^(?:[^:\r\n]+/)?{re.escape(donor_source)}:{diagnostic_line}:[0-9]+:"
        r"[ \t]*error(?:\([^)\r\n]+\))?:[ \t]*(?:\r?\n[ \t]*)?"
        rf"unknown (?:identifier|constant)[ \t]+[`'\u2018\u201c]?{re.escape(marker)}\b",
        re.MULTILINE | re.IGNORECASE,
    )
    launched_modules, fault_results = [], []
    original_run = native.process.BoundedToolRunner.run

    def observe_and_fault_one_input(runner, request, **kwargs):
        command = tuple(request.argv)
        if command[:2] == (lean, "-o"):
            launched_modules.append(command[3])
        if command != donor_command:
            return original_run(runner, request, **kwargs)

        # Change only the isolated compiler input, after genuine preparation replay.
        original_input = request.input_files[donor_source]
        assert (original_input.encode() if isinstance(original_input, str) else original_input) == frozen_donor_source
        assert marker.encode() not in frozen_donor_source and request.owned_process_observation is True
        faulted_raw = frozen_donor_source + diagnostic_tail
        faulted_request = replace(request, input_files=dict(request.input_files) | {donor_source: faulted_raw})
        faulted_name = "intentional-lean-failure-input.lean.DATA"
        (tmp_path / faulted_name).write_bytes(faulted_raw)
        (tmp_path / "intentional-lean-failure-request.json").write_bytes(wire({
            "kind": "deliberate_test_only_native_input_fault",
            "owner_preparation_sha256": parent_native.parent_shared_preparation_sha256(changed_preparation),
            "module": new_donor,
            "source_path": donor_source,
            "original_source_sha256": sha(frozen_donor_source),
            "diagnostic_line_1_based": diagnostic_line,
            "faulted_input_file": faulted_name,
            "faulted_source_sha256": sha(faulted_raw),
            "source_bytes_match_frozen_preparation": False,
            "argv": faulted_request.argv,
            "runtime": faulted_request.runtime.value,
            "owned_process_observation": faulted_request.owned_process_observation,
            "requested_outputs": faulted_request.output_paths,
            "environment": dict(faulted_request.environment),
            "limits": asdict(faulted_request.limits),
            "inputs": {path: sha(body.encode() if isinstance(body, str) else body)
                       for path, body in faulted_request.input_files.items()},
        }))
        result = original_run(runner, faulted_request, **kwargs)
        fault_results.append((faulted_raw, result))
        return result

    failed_path = tmp_path / "failed-donor-affected"
    with monkeypatch.context() as patch:
        patch.setattr(native.process.BoundedToolRunner, "run", observe_and_fault_one_input)
        receipt = build(changed_preparation, changed_inputs, failed_path,
                        previous_cache_raw=cold_cache_raw,
                        expected_previous_cache_sha256=sha(cold_cache_raw),
                        previous_artifacts=cold_artifacts)

    assert launched_modules == [donor_source] and len(fault_results) == 1
    faulted_raw, native_failure = fault_results[0]
    assert native_failure.runtime is native.process.ToolRuntime.NATIVE
    assert native_failure.command == donor_command
    assert native_failure.pid > 0 and native_failure.returncode > 0
    assert native_failure.termination_reason == "nonzero_exit"
    assert any(diagnostic_pattern.search(stream) for stream in (native_failure.stdout, native_failure.stderr))
    assert native_failure.output_files[donor_source] == faulted_raw
    assert native_failure.workspace_cleaned
    lifecycle = native_failure.native_lifecycle
    assert isinstance(lifecycle, native.process.NativeToolLifecycleObservation)
    assert lifecycle.cleanup_confirmed
    assert parent_native._observed_process_scope(lifecycle, native_failure.pid, native.process)
    assert not any((native_failure.timed_out, native_failure.cancelled, native_failure.unavailable,
                    native_failure.resource_exhausted, native_failure.output_truncated,
                    native_failure.workspace_limit_exceeded))

    failed = receipt, failed_path
    failed_cache = cache(failed)
    failed_artifacts = artifacts(failed)
    assert receipt["previous_cache_cid"] == cache(cold)["record_cid"]
    assert receipt["framework_successful"] is receipt["build_passed"] is False
    assert receipt["lean_compilation_verified"] is failed_cache["qualified"] is False
    assert receipt["post_run_validation_error"] is None
    assert receipt["compiled_modules"] == [new_donor] and receipt["module_compile_invocations"] == 1
    assert receipt["fresh_theorems"] == []
    assert not ((prior_affected | current_affected) & failed_artifacts.keys())
    assert independent_modules <= set(receipt["reused_modules"])
    assert {module: failed_artifacts[module] for module in independent_modules} == {
        module: cold_artifacts[module] for module in independent_modules}
    failed_facts = {fact["module"]: fact for fact in failed_cache["module_facts"]}
    assert all(failed_facts[module]["output"] is None for module in current_affected)
    assert all(receipt[flag] is failed_cache[flag] is False for flag in incremental._parent_flags())
    assert failed_cache["execution_contract"]["binary_sha256"] == binary_pins
    assert failed_cache["execution_contract"] == cache(cold)["execution_contract"]
    observation_raw = (failed_path / "module-executions.jsonl").read_bytes()
    observations = [json.loads(line) for line in observation_raw.splitlines()]
    assert sha(observation_raw) == receipt["execution_observations"]["sha256"]
    assert len(observations) == 1
    observation = observations[0]
    assert (observation["module"], observation["pid"], observation["returncode"]) == (
        new_donor, native_failure.pid, native_failure.returncode)
    assert observation["runtime"] == native_failure.runtime.value
    assert observation["command"] == list(native_failure.command)
    assert observation["stdout"] == native_failure.stdout and observation["stderr"] == native_failure.stderr
    assert observation["termination_reason"] == native_failure.termination_reason
    assert observation["workspace_cleaned"] is native_failure.workspace_cleaned
    assert observation["native_lifecycle"] == lifecycle.to_dict()
    assert observation["output_files"][donor_source] == {
        "bytes": len(faulted_raw), "sha256": sha(faulted_raw),
    }
    published_source = (failed_path / "project" / donor_source).read_bytes()
    assert published_source == frozen_donor_source
    assert published_source != faulted_raw
    assert (cold_path / "cache.json").read_bytes() == cold_cache_raw
    assert artifacts(cold) == cold_artifacts
    assert all(path.read_bytes() == body for path, body in physical.items())


def test_source_edition_only_change_splits_shared_definition_cache_and_matches_clean(runtime):
    """Authored source editions; real replay owners and the existing fake compiler.

    This exercises source-version invalidation without revising either authored
    interpretation. It supplies no installed-Lean or statutory-review evidence.
    """
    first = _FIXTURE_MODULE.candidate("O", edition=2024, norm_id="versioned-A")
    next_version = _FIXTURE_MODULE.candidate("O", edition=2025, norm_id="versioned-A")
    unchanged = _FIXTURE_MODULE.candidate("P", edition=2024, norm_id="retained-B")
    original_cases, changed_cases = [first, unchanged], [next_version, unchanged]

    original_request = json.loads(first[0]["request_raw"])
    changed_request = json.loads(next_version[0]["request_raw"])
    assert first[0]["raw_html"] == next_version[0]["raw_html"] == unchanged[0]["raw_html"]
    assert first[1]["raw_sha256"] == next_version[1]["raw_sha256"]
    assert first[1]["extracted_sha256"] == next_version[1]["extracted_sha256"]
    assert original_request["definition_request"]["document"]["document_text"] == \
        changed_request["definition_request"]["document"]["document_text"]
    assert original_request["definition_request"]["declaration"] == \
        changed_request["definition_request"]["declaration"]
    semantic_fields = (
        "norm_id", "profile", "interpretation_status", "paragraph_index", "source_span",
        "quantifier_span", "category_span", "modality_span", "action_span", "modality",
        "variable", "activation_scope", "modal_context",
    )
    assert {key: original_request["norm_declaration"][key] for key in semantic_fields} == \
        {key: changed_request["norm_declaration"][key] for key in semantic_fields}
    assert original_request["norm_declaration"]["edition"] == 2024
    assert changed_request["norm_declaration"]["edition"] == 2025
    assert first[2]["source_version"]["record_cid"] == unchanged[2]["source_version"]["record_cid"]
    assert first[2]["source_version"]["record_cid"] != next_version[2]["source_version"]["record_cid"]
    assert first[3]["definition"]["scope_key"] == next_version[3]["definition"]["scope_key"]
    assert first[3]["scope_key"] != next_version[3]["scope_key"]
    assert original_request["source_provenance"] == changed_request["source_provenance"] == {
        "kind": "authored_official_shape_fixture",
        "authenticity_verified": False,
        "independently_reviewed": False,
        "training_admitted": False,
    }

    original_preparation, changed_preparation = prepare(original_cases), prepare(changed_cases)
    old, current = original_preparation.to_dict(), changed_preparation.to_dict()
    assert len(old["definition_modules"]) == 1
    assert len(current["definition_modules"]) == 2
    old_first, old_second = old["norm_bindings"]
    current_first, current_second = current["norm_bindings"]
    assert old_first["definition_module"] == old_second["definition_module"]
    assert current_first["definition_module"] != old_first["definition_module"]
    for key in ("module", "definition_module", "composition_theorem"):
        assert current_second[key] == old_second[key]

    cold = build(runtime, original_cases, original_preparation, "edition-only-cold")
    cold_receipt = wire(cold[0])
    cold_cache = (cold[1] / "cache.json").read_bytes()
    cold_artifacts = artifacts(cold)
    before = len(runtime[1].calls)
    updated = build(runtime, changed_cases, changed_preparation, "edition-only-updated", previous=cold)
    expected = set(current["expected_modules"])
    retained = {"LegalCorpus.Prelude", old_second["definition_module"], old_second["module"]}
    assert updated[0]["build_passed"] is True
    assert set(updated[0]["reused_modules"]) == retained
    assert set(updated[0]["compiled_modules"]) == expected - retained
    assert {call["module"] for call in runtime[1].calls[before:]} == expected - retained
    assert len(runtime[1].calls) - before == len(expected - retained)
    assert updated[0]["reused_theorems"] == [old_second["composition_theorem"]]
    assert len(updated[0]["fresh_theorems"]) == 1
    updated_artifacts = artifacts(updated)
    assert set(updated_artifacts) == expected
    assert {row["module"] for row in cache(updated)["module_facts"]} == expected
    assert not (set(old["expected_modules"]) - expected) & set(updated_artifacts)
    for module in retained:
        assert updated_artifacts[module] == cold_artifacts[module]

    before_warm = len(runtime[1].calls)
    warm = build(runtime, changed_cases, changed_preparation, "edition-only-warm", previous=updated)
    assert warm[0]["build_passed"] is True
    assert warm[0]["compiled_modules"] == []
    assert set(warm[0]["reused_modules"]) == expected
    assert warm[0]["fresh_theorems"] == []
    assert warm[0]["backend_executed"] is False
    assert len(runtime[1].calls) == before_warm
    assert artifacts(warm) == updated_artifacts
    assert warm[0]["artifact_root_cid"] == updated[0]["artifact_root_cid"]

    clean = build(runtime, changed_cases, changed_preparation, "edition-only-clean")
    assert clean[0]["build_passed"] is True
    assert set(clean[0]["compiled_modules"]) == expected
    assert clean[0]["reused_modules"] == []
    assert artifacts(clean) == updated_artifacts
    assert clean[0]["artifact_root_cid"] == updated[0]["artifact_root_cid"]
    assert wire(cold[0]) == cold_receipt
    assert (cold[1] / "cache.json").read_bytes() == cold_cache
    assert artifacts(cold) == cold_artifacts
