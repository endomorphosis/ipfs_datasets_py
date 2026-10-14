"""Source-only global dependency equivalence across unchanged inventory slices.

These controls never import or execute the captured target code. The named
32-entry slices only place an unchanged caller and its dependency on opposite
sides of an inventory boundary; they do not claim a resumable worker, model,
proof execution, admission or native scan qualification.
"""

from dataclasses import replace

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index import python_analysis
from ipfs_datasets_py.logic.software_contracts.semantic_index import scanner as scanner_module
from ipfs_datasets_py.logic.software_contracts.semantic_index.delta import diff_repository_states
from ipfs_datasets_py.logic.software_contracts.semantic_index.invalidation import calculate_invalidation
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import RelationType
from ipfs_datasets_py.logic.software_contracts.semantic_index.python_analysis import PythonSemanticAnalyzer
from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import RepositoryScanner
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import RepositorySnapshot, SnapshotEntry
from ipfs_datasets_py.logic.software_contracts.semantic_index.symbol_graph import build_symbol_graph

import pytest


REPOSITORY_ID = "repo:scanner-cross-inventory-cold-equivalence"


def _scan(sources, previous=None, scanner=None):
    raw = {path: source.encode("utf-8") for path, source in sources.items()}
    entries = tuple(
        SnapshotEntry(path, "python", len(value), cid_for_bytes(value), captured_bytes=value)
        for path, value in sorted(raw.items())
    )
    snapshot = RepositorySnapshot(REPOSITORY_ID, entries, "filesystem", 65536, 128)
    owner = scanner or RepositoryScanner(repository_id=REPOSITORY_ID)
    return owner.scan_snapshot(snapshot, raw, previous_state=previous)


def _symbols(state):
    return {item.qualified_name: item for item in state.symbols}


def _calls(state, qualified_name):
    source_id = _symbols(state)[qualified_name].stable_id
    return tuple(edge for edge in state.edges
                 if edge.source_id == source_id and edge.relation == RelationType.CALLS.value)


def _assert_cold_equivalent(previous, current_sources, *, namespace=None):
    warm = _scan(current_sources, previous, RepositoryScanner(repository_id=REPOSITORY_ID, namespace=namespace))
    cold = _scan(current_sources, scanner=RepositoryScanner(repository_id=REPOSITORY_ID, namespace=namespace))
    # Compare the complete committed graph, not a local source-version subset.
    assert warm.to_dict() == cold.to_dict()
    assert warm.state_cid == cold.state_cid
    warm_delta = diff_repository_states(previous, warm)
    cold_delta = diff_repository_states(previous, cold)
    assert warm_delta.to_dict() == cold_delta.to_dict()
    warm_plan = calculate_invalidation(previous, warm, warm_delta)
    cold_plan = calculate_invalidation(previous, cold, cold_delta)
    assert warm_plan.to_dict() == cold_plan.to_dict()
    # A fresh owner consuming a durable-state roundtrip must make the same
    # decision. This is object rehydration, not a native database restart.
    rehydrated = type(previous).from_dict(previous.to_dict())
    assert _scan(current_sources, rehydrated,
                 RepositoryScanner(repository_id=REPOSITORY_ID, namespace=namespace)).to_dict() == cold.to_dict()
    return warm, cold, cold_delta, cold_plan


def _ambiguous_sources(*, pytest_alias=False):
    caller = "tests/test_consumer.py" if pytest_alias else "consumer.py"
    name = "test_alias" if pytest_alias else "consume"
    body = "assert chosen(1) == 1" if pytest_alias else "return chosen(value)"
    parameters = "" if pytest_alias else "value"
    return {
        caller: "from shared import helper as chosen\n\ndef " + name + "(" + parameters + "):\n    " + body + "\n",
        "left/shared.py": "def helper(value):\n    return value\n",
        "right/shared.py": "def helper(value):\n    return value + 1\n",
    }


@pytest.mark.parametrize("pytest_alias", [False, True])
def test_identical_snapshot_preserves_finite_may_fanout_and_complete_cold_root(pytest_alias):
    sources = _ambiguous_sources(pytest_alias=pytest_alias)
    previous = _scan(sources)
    name = "tests.test_consumer.test_alias" if pytest_alias else "consumer.consume"
    calls = _calls(previous, name)
    assert len(calls) == 2
    assert {edge.metadata.get("resolution") for edge in calls} == {"finite_may"}
    assert {edge.metadata.get("candidate_count") for edge in calls} == {2}
    current, _, delta, plan = _assert_cold_equivalent(previous, sources)
    assert _calls(current, name) == calls
    assert delta.added_edge_ids == delta.deleted_edge_ids == ()
    assert plan.obligations == ()


@pytest.mark.parametrize("pytest_alias", [False, True])
@pytest.mark.parametrize("remaining", ["one", "none"])
def test_unchanged_import_alias_reresolves_after_other_inventory_paths_disappear(pytest_alias, remaining):
    sources = _ambiguous_sources(pytest_alias=pytest_alias)
    previous = _scan(sources)
    current_sources = dict(sources)
    del current_sources["right/shared.py"]
    if remaining == "none":
        del current_sources["left/shared.py"]
    name = "tests.test_consumer.test_alias" if pytest_alias else "consumer.consume"
    cold = _scan(current_sources)
    cold_calls = _calls(cold, name)
    assert len(cold_calls) == 1
    assert cold_calls[0].metadata.get("resolution") == ("definite" if remaining == "one" else "unresolved")
    if remaining == "none":
        assert cold_calls[0].target_id == "lexical:shared.helper"
    warm, _, delta, plan = _assert_cold_equivalent(previous, current_sources)
    assert _calls(warm, name) == cold_calls
    assert delta.deleted_edge_ids
    assert plan.obligations


@pytest.mark.parametrize("change", ["delete", "rename"])
def test_unchanged_first_slice_caller_does_not_retain_last_slice_deleted_dependency(change):
    sources = {
        "a_caller.py": "from z_api import service\n\ndef caller(value):\n    return service(value)\n",
        "z_api.py": "def service(value):\n    return value + 1\n",
        **{f"m_padding_{index:03d}.py": f"def pad_{index}():\n    return {index}\n" for index in range(35)},
    }
    paths = sorted(sources)
    assert paths.index("a_caller.py") < 32 <= paths.index("z_api.py")
    previous = _scan(sources)
    old_service = _symbols(previous)["z_api.service"].stable_id
    assert any(edge.target_id == old_service for edge in _calls(previous, "a_caller.caller"))
    current_sources = dict(sources)
    removed = current_sources.pop("z_api.py")
    if change == "rename":
        current_sources["z_renamed.py"] = removed
    cold = _scan(current_sources)
    # A unique renamed tail may remain a conservative candidate under this
    # resolver. Its exact cold output, rather than Python runtime semantics,
    # is the authority for this structural scanner profile.
    assert all(edge.target_id != old_service for edge in _calls(cold, "a_caller.caller"))
    _, _, delta, plan = _assert_cold_equivalent(previous, current_sources)
    assert old_service in delta.deleted_symbol_ids
    assert any(obligation.reason_code == "deleted_symbol_dependency" for obligation in plan.obligations)


@pytest.mark.parametrize("start_protocol", [False, True])
def test_unchanged_inheritor_rebuilds_protocol_derived_edges_in_both_directions(start_protocol):
    def base(protocol):
        return ("from typing import Protocol\n\nclass Service(Protocol):\n    pass\n" if protocol
                else "class Service:\n    pass\n")

    sources = {
        "protocols.py": base(start_protocol),
        "client.py": "from protocols import Service\n\nclass Impl(Service):\n    pass\n",
    }
    previous = _scan(sources)
    current_sources = {**sources, "protocols.py": base(not start_protocol)}
    cold = _scan(current_sources)
    impl = _symbols(cold)["client.Impl"].stable_id
    derived = tuple(edge for edge in cold.edges if edge.source_id == impl
                    and edge.extraction_method == "static-protocol-inheritance")
    assert bool(derived) is (not start_protocol)
    warm, _, _, plan = _assert_cold_equivalent(previous, current_sources)
    assert tuple(edge for edge in warm.edges if edge.source_id == impl
                 and edge.extraction_method == "static-protocol-inheritance") == derived
    assert plan.obligations


def test_pytest_fixture_context_rebuild_preserves_unified_test_identity_and_cold_graph():
    sources = {
        "tests/conftest.py": "import pytest\n\n@pytest.fixture\ndef token():\n    return 1\n",
        "tests/test_token.py": "def test_token(token):\n    assert token == 1\n",
        "stable.py": "def keep():\n    return 1\n",
    }
    previous = _scan(sources)
    current_sources = {**sources, "tests/conftest.py":
        "import pytest\n\n@pytest.fixture(scope='session')\ndef token():\n    return 2\n"}
    warm, _, _, plan = _assert_cold_equivalent(previous, current_sources)
    tests = tuple(item for item in warm.symbols if item.qualified_name == "tests.test_token.test_token")
    assert len(tests) == 1 and tests[0].kind == "test"
    assert _symbols(warm)["stable.keep"] is _symbols(previous)["stable.keep"]
    assert any(obligation.reason_code == "stale_test_receipt" for obligation in plan.obligations)


@pytest.mark.parametrize("field", ["confidence", "metadata"])
def test_prior_auxiliary_pytest_record_fields_cannot_replace_fresh_frontend_output(field):
    sources = {"tests/test_value.py": "def test_value():\n    assert 1 == 1\n"}
    previous = _scan(sources)
    original = _symbols(previous)["tests.test_value.test_value"]
    if field == "confidence":
        changed = replace(original, confidence="opaque")
    else:
        changed = replace(original, metadata={**original.metadata, "prior_only_note": "not fresh frontend output"})
    # These auxiliary fields are committed in the state but do not enter the
    # symbol semantic version. Matching the three reuse-key IDs is not enough.
    assert (changed.stable_id, changed.source_cid, changed.version_cid) == (
        original.stable_id, original.source_cid, original.version_cid)
    prior = replace(previous, symbols=tuple(changed if item is original else item for item in previous.symbols))
    warm, cold, _, _ = _assert_cold_equivalent(prior, sources)
    assert _symbols(warm)[original.qualified_name] == _symbols(cold)[original.qualified_name] == original


@pytest.mark.parametrize("previous_namespace,current_namespace", [
    (None, "custom"), ("custom", None), ("custom", "other"),
])
def test_changed_namespace_reanalyzes_source_local_records(previous_namespace, current_namespace):
    sources = {"pkg/local.py": "def target():\n    return 1\n\ndef caller():\n    return target()\n"}
    previous = _scan(sources, scanner=RepositoryScanner(
        repository_id=REPOSITORY_ID, namespace=previous_namespace))
    warm, cold, delta, _ = _assert_cold_equivalent(previous, sources, namespace=current_namespace)
    assert {item.namespace for item in cold.symbols} == {current_namespace or "pkg"}
    assert _symbols(warm)["pkg.local.caller"].stable_id != _symbols(previous)["pkg.local.caller"].stable_id
    assert delta.added_symbol_ids and delta.deleted_symbol_ids


@pytest.mark.parametrize("field", ["extractor_name", "extractor_version"])
def test_source_local_records_from_a_different_frontend_identity_are_not_reused(field):
    path = "local.py"
    sources = {path: "def target():\n    return 1\n\ndef caller():\n    return target()\n"}
    previous = _scan(sources)
    options = {field: "different-frontend"}
    # Author a real raw frontend analysis under another advertised extractor
    # identity; no producer function/class/global is monkeypatched.
    analysis = PythonSemanticAnalyzer(repository_id=REPOSITORY_ID, **options).analyze(sources[path], path)
    graph = build_symbol_graph(analysis.symbol_records, previous.artifacts, analysis.edges)
    prior = replace(previous, symbols=graph.symbols, edges=graph.edges)
    assert {getattr(item, field) for item in prior.symbols} == {options[field]}
    warm, cold, _, _ = _assert_cold_equivalent(prior, sources)
    assert _symbols(warm)["local.caller"] == _symbols(cold)["local.caller"]
    assert getattr(_symbols(warm)["local.caller"], field) != options[field]


def test_current_frontend_edge_version_change_reanalyzes_same_local_calls(monkeypatch):
    sources = {"local.py": "def target():\n    return 1\n\ndef caller():\n    return target()\n"}
    previous = _scan(sources)
    assert _calls(previous, "local.caller")
    original_version = python_analysis.EXTRACTOR_VERSION
    replacement_version = original_version + ".changed"
    # The visitor's edge version is a distinct identity from analyzer symbol
    # extractor defaults. Change only that public frontend identity and let
    # actual extraction build the new cold records; restore automatically.
    monkeypatch.setattr(python_analysis, "EXTRACTOR_VERSION", replacement_version)
    warm, cold, delta, _ = _assert_cold_equivalent(previous, sources)
    assert {edge.extractor_version for edge in _calls(warm, "local.caller")} == {replacement_version}
    assert {edge.extractor_version for edge in _calls(cold, "local.caller")} == {replacement_version}
    assert delta.added_edge_ids and delta.deleted_edge_ids


@pytest.mark.parametrize("changed_frontend", [False, True])
def test_opaque_python_diagnostics_reanalyze_without_unbound_frontend_reuse(monkeypatch, changed_frontend):
    sources = {"broken.py": "def broken(:\n"}
    previous = _scan(sources)
    opaque = tuple(item for item in previous.artifacts if item.kind == "python-analysis")
    assert len(opaque) == 1 and opaque[0].metadata["diagnostics"]
    calls = []

    class ObservedFrontend(PythonSemanticAnalyzer):
        def __init__(self, **options):
            if changed_frontend:
                options.update(extractor_name="changed-diagnostic-frontend", extractor_version="99")
            super().__init__(**options)

        def analyze(self, source, path):
            calls.append(path)
            result = super().analyze(source, path)
            if changed_frontend:
                # Explicit frontend protocol double: only its advertised
                # identity and diagnostic vocabulary change. No target code
                # executes, and no native producer qualification is claimed.
                return replace(result, diagnostics=tuple("changed:" + item for item in result.diagnostics))
            return result

    monkeypatch.setattr(scanner_module, "PythonSemanticAnalyzer", ObservedFrontend)
    warm, cold, _, _ = _assert_cold_equivalent(previous, sources)
    assert calls == ["broken.py"] * 3  # warm, cold, durable-state roundtrip
    new_opaque = tuple(item for item in warm.artifacts if item.kind == "python-analysis")
    assert new_opaque == tuple(item for item in cold.artifacts if item.kind == "python-analysis")
    assert (new_opaque[0].metadata["diagnostics"] != opaque[0].metadata["diagnostics"]) is changed_frontend
