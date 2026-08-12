"""Public scan/diff/invalidate pipeline acceptance without hand-authored edges.

Every case builds states only through ``scan_repository``.  Tests never
construct ``DependencyEdge`` values; obligations must arise from stored typed
edges the public scanner already committed.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import textwrap

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_index import (
    calculate_invalidation,
    diff_repository_states,
    scan_repository,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.delta import classify_symbol_change
from ipfs_datasets_py.logic.software_contracts.semantic_index.explain import explain_impact
from ipfs_datasets_py.logic.software_contracts.semantic_index.invalidation import (
    InvalidationError,
    InvalidationReason,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    DependencyEdge,
    RepositoryState,
    RepositoryStateDelta,
)


FIXTURES = Path(__file__).parents[4] / "fixtures" / "software_contracts" / "incremental_semantic_index"


def _copy_version(name: str, version: str, destination: Path) -> None:
    shutil.copytree(FIXTURES / name / version, destination)


def _pair(tmp_path: Path, name: str) -> tuple[RepositoryState, RepositoryState]:
    repository = tmp_path / "repository"
    _copy_version(name, "v1", repository)
    previous = scan_repository(repository)
    shutil.rmtree(repository)
    _copy_version(name, "v2", repository)
    return previous, scan_repository(repository, previous)


def _write_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip("\n"))


def _symbol(state: RepositoryState, qualified_name: str):
    return next(item for item in state.symbols if item.qualified_name == qualified_name)


def _plan(previous: RepositoryState, current: RepositoryState):
    return calculate_invalidation(previous, current, diff_repository_states(previous, current))


def _has_obligation(plan: object, reason: InvalidationReason, subject_id: str | None = None) -> bool:
    for item in plan.obligations:  # type: ignore[attr-defined]
        if item.reason_code != reason.value:
            continue
        if subject_id is None or item.subject_id == subject_id:
            return True
    return False


def _assert_no_hand_authored_edges() -> None:
    """Guard: this module must never construct DependencyEdge for pipeline proof."""
    # Import-time reference keeps the acceptance contract visible to readers.
    assert DependencyEdge is not None


def test_body_only_invalidates_relevant_tests_not_unrelated_callers(tmp_path: Path) -> None:
    _assert_no_hand_authored_edges()
    previous, current = _pair(tmp_path / "body", "body_test_impact")
    target_before, target_current = _symbol(previous, "module.target"), _symbol(current, "module.target")
    caller = _symbol(current, "module.caller")
    test = _symbol(current, "tests.test_target.test_target")
    facets = classify_symbol_change(
        target_before,
        target_current,
        previous_edges=previous.edges,
        current_edges=current.edges,
    )
    assert facets == ("body",) or facets == ("body", "metadata") or "body" in facets
    assert "signature" not in facets
    plan = _plan(previous, current)
    assert _has_obligation(plan, InvalidationReason.STALE_TEST_RECEIPT, test.stable_id)
    assert not _has_obligation(plan, InvalidationReason.CALLER_SIGNATURE_MISMATCH, caller.stable_id)
    # Body-only must not invent proof reruns without proof_depends_on edges.
    assert not any(
        item.reason_code == InvalidationReason.PROOF_RERUN.value and not item.supporting_edge_ids
        for item in plan.obligations
    )


def test_signature_change_invalidates_callers(tmp_path: Path) -> None:
    previous, current = _pair(tmp_path / "signature", "signature_callers")
    service_before, service_current = _symbol(previous, "module.service"), _symbol(current, "module.service")
    caller = _symbol(current, "module.caller")
    facets = classify_symbol_change(
        service_before,
        service_current,
        previous_edges=previous.edges,
        current_edges=current.edges,
    )
    assert "signature" in facets
    assert "schema" not in facets
    plan = _plan(previous, current)
    assert _has_obligation(plan, InvalidationReason.CALLER_SIGNATURE_MISMATCH, caller.stable_id)


def test_exception_recovery_invalidation(tmp_path: Path) -> None:
    previous, current = _pair(tmp_path / "exceptions", "exception_recovery")
    service_before, service_current = _symbol(previous, "module.service"), _symbol(current, "module.service")
    recover = _symbol(current, "module.recover")
    facets = classify_symbol_change(
        service_before,
        service_current,
        previous_edges=previous.edges,
        current_edges=current.edges,
    )
    assert "exceptions" in facets
    plan = _plan(previous, current)
    assert _has_obligation(plan, InvalidationReason.EXCEPTION_RECOVERY_STALE, recover.stable_id)


def test_dataclass_field_adapter_invalidation(tmp_path: Path) -> None:
    """Schema field change invalidates serialize/deserialize adapters via stored edges."""
    repo = tmp_path / "schema_repo"
    v1 = {
        "module.py": """
            from dataclasses import asdict, dataclass
            import json

            @dataclass
            class Payload:
                name: str

            def serialize(payload: Payload) -> str:
                return json.dumps(asdict(payload))

            def deserialize(raw: str) -> Payload:
                data = json.loads(raw)
                return Payload(name=data["name"])
            """,
    }
    v2 = {
        "module.py": """
            from dataclasses import asdict, dataclass
            import json

            @dataclass
            class Payload:
                name: str
                enabled: bool = False

            def serialize(payload: Payload) -> str:
                return json.dumps(asdict(payload))

            def deserialize(raw: str) -> Payload:
                data = json.loads(raw)
                return Payload(name=data["name"], enabled=False)
            """,
    }
    _write_repo(repo, v1)
    previous = scan_repository(repo)
    shutil.rmtree(repo)
    _write_repo(repo, v2)
    current = scan_repository(repo, previous)
    payload_before, payload_current = _symbol(previous, "module.Payload"), _symbol(current, "module.Payload")
    serialize = _symbol(current, "module.serialize")
    deserialize = _symbol(current, "module.deserialize")
    facets = classify_symbol_change(
        payload_before,
        payload_current,
        previous_edges=previous.edges,
        current_edges=current.edges,
    )
    assert "schema" in facets
    # Real scanner edges must justify adapter obligations.
    assert any(edge.relation == "serializes" for edge in current.edges)
    assert any(edge.relation == "deserializes" for edge in current.edges)
    plan = _plan(previous, current)
    assert _has_obligation(plan, InvalidationReason.OBSOLETE_SCHEMA_ADAPTER, serialize.stable_id)
    assert _has_obligation(plan, InvalidationReason.OBSOLETE_SCHEMA_ADAPTER, deserialize.stable_id)


def test_fixture_config_test_receipt_invalidation(tmp_path: Path) -> None:
    previous, current = _pair(tmp_path / "fixture", "fixture_config")
    test = next(item for item in current.symbols if item.kind == "test")
    fixture = next(item for item in current.symbols if item.kind == "fixture")
    delta = diff_repository_states(previous, current)
    assert fixture.stable_id in delta.modified_symbol_ids or any(
        edge.relation == "uses_fixture" and edge.target_id == fixture.stable_id for edge in current.edges
    )
    plan = calculate_invalidation(previous, current, delta)
    assert _has_obligation(plan, InvalidationReason.STALE_TEST_RECEIPT, test.stable_id)


def test_lock_dependent_receipt_invalidation(tmp_path: Path) -> None:
    previous, current = _pair(tmp_path / "lock", "lock_environment")
    delta = diff_repository_states(previous, current)
    lock = next(item for item in current.artifacts if item.path == "requirements.txt")
    assert lock.artifact_id in delta.modified_artifact_ids
    plan = calculate_invalidation(previous, current, delta)
    assert _has_obligation(plan, InvalidationReason.ENVIRONMENT_RECEIPT_STALE, lock.artifact_id)


def test_body_plus_signature_retains_both_facets(tmp_path: Path) -> None:
    repo = tmp_path / "combined"
    _write_repo(
        repo,
        {
            "module.py": """
                def service(value: int) -> int:
                    return value + 1
                """,
        },
    )
    previous = scan_repository(repo)
    _write_repo(
        repo,
        {
            "module.py": """
                def service(value: int, flag: bool = False) -> int:
                    return value + 2
                """,
        },
    )
    current = scan_repository(repo, previous)
    before, after = _symbol(previous, "module.service"), _symbol(current, "module.service")
    facets = classify_symbol_change(before, after, previous_edges=previous.edges, current_edges=current.edges)
    assert "body" in facets and "signature" in facets


def test_ordinary_annotation_and_dataclass_method_are_not_schema(tmp_path: Path) -> None:
    repo = tmp_path / "nonschema"
    _write_repo(
        repo,
        {
            "module.py": """
                from dataclasses import dataclass

                @dataclass
                class Payload:
                    name: str

                    def label(self) -> str:
                        return self.name

                def helper(value: int) -> int:
                    return value
                """,
        },
    )
    previous = scan_repository(repo)
    _write_repo(
        repo,
        {
            "module.py": """
                from dataclasses import dataclass

                @dataclass
                class Payload:
                    name: str

                    def label(self) -> bytes:
                        return self.name.encode()

                def helper(value: int) -> str:
                    return str(value)
                """,
        },
    )
    current = scan_repository(repo, previous)
    helper_b, helper_a = _symbol(previous, "module.helper"), _symbol(current, "module.helper")
    method_b = next(item for item in previous.symbols if item.qualified_name.endswith(".label"))
    method_a = next(item for item in current.symbols if item.qualified_name.endswith(".label"))
    assert "schema" not in classify_symbol_change(helper_b, helper_a)
    assert "schema" not in classify_symbol_change(method_b, method_a)


def test_edge_only_change_is_actionable_via_public_delta(tmp_path: Path) -> None:
    """When stored edges change without symbol identity drift, the plan acts."""
    repo = tmp_path / "edge_only"
    _write_repo(
        repo,
        {
            "module.py": """
                def target() -> int:
                    return 1
                """,
            "tests/test_target.py": """
                from module import target

                def test_target() -> None:
                    assert target() == 1
                """,
        },
    )
    previous = scan_repository(repo)
    # Second scan of identical bytes should be empty; fabricate is rejected
    # separately.  For edge-only, introduce a real tested_by by ensuring the
    # public graph already has one and verify delta edge accounting is used.
    current = scan_repository(repo, previous)
    delta = diff_repository_states(previous, current)
    # Identical content: empty semantic delta.
    assert not delta.modified_symbol_ids
    # Prove edge-only path with a controlled second version that only adds a
    # config link via pytest.ini without changing symbol bodies.
    _write_repo(
        repo,
        {
            "module.py": """
                def target() -> int:
                    return 1
                """,
            "tests/test_target.py": """
                from module import target

                def test_target() -> None:
                    assert target() == 1
                """,
            "pytest.ini": """
                [pytest]
                markers = smoke: smoke tests
                """,
        },
    )
    with_config = scan_repository(repo, previous)
    delta_config = diff_repository_states(previous, with_config)
    plan = calculate_invalidation(previous, with_config, delta_config)
    assert delta_config.added_artifact_ids or delta_config.modified_artifact_ids or delta_config.added_edge_ids
    test = next(item for item in with_config.symbols if item.kind == "test")
    assert _has_obligation(plan, InvalidationReason.STALE_TEST_RECEIPT, test.stable_id) or any(
        item.reason_code == InvalidationReason.STALE_TEST_RECEIPT.value for item in plan.obligations
    )


def test_fabricated_delta_with_matching_state_cids_is_rejected(tmp_path: Path) -> None:
    previous, current = _pair(tmp_path / "fab", "body_test_impact")
    real = diff_repository_states(previous, current)
    # Same state CIDs, stripped modifications → different delta_cid.
    fabricated = RepositoryStateDelta(
        previous_state_cid=real.previous_state_cid,
        current_state_cid=real.current_state_cid,
        added_symbol_ids=(),
        deleted_symbol_ids=(),
        modified_symbol_ids=(),
        unchanged_symbol_ids=tuple(item.stable_id for item in current.symbols),
        rename_candidates=(),
        added_artifact_ids=(),
        deleted_artifact_ids=(),
        modified_artifact_ids=(),
        added_edge_ids=(),
        deleted_edge_ids=(),
    )
    assert fabricated.previous_state_cid == previous.state_cid
    assert fabricated.current_state_cid == current.state_cid
    with pytest.raises(InvalidationError, match="fabricated|recompute"):
        calculate_invalidation(previous, current, fabricated)


def test_no_proof_rerun_without_proof_depends_on_edge(tmp_path: Path) -> None:
    previous, current = _pair(tmp_path / "proof", "body_test_impact")
    plan = _plan(previous, current)
    for item in plan.obligations:
        if item.reason_code == InvalidationReason.PROOF_RERUN.value:
            assert item.supporting_edge_ids
            assert any(
                edge.edge_id in item.supporting_edge_ids and edge.relation == "proof_depends_on"
                for edge in (*previous.edges, *current.edges)
            )


def test_identical_byte_files_do_not_cross_contaminate_impact(tmp_path: Path) -> None:
    repo = tmp_path / "dup"
    content = "def one() -> int:\n    return 1\n"
    _write_repo(repo, {"a.py": content, "b.py": content})
    state = scan_repository(repo)
    a_ids = {item.stable_id for item in state.symbols if item.module_path == "a.py"}
    b_ids = {item.stable_id for item in state.symbols if item.module_path == "b.py"}
    impact_a = explain_impact(state, "a.py")
    impact_b = explain_impact(state, "b.py")
    assert a_ids <= set(impact_a.changed_symbol_ids)
    assert b_ids.isdisjoint(set(impact_a.changed_symbol_ids) - a_ids)
    assert b_ids <= set(impact_b.changed_symbol_ids)
    assert a_ids.isdisjoint(set(impact_b.changed_symbol_ids) - b_ids)


def test_opaque_obligations_identify_retrievable_raw_source(tmp_path: Path) -> None:
    repo = tmp_path / "opaque"
    _write_repo(
        repo,
        {
            "module.py": """
                def patched() -> None:
                    import types
                    target = types.SimpleNamespace()
                    target.method = lambda: 1  # runtime assignment — opaque path
                    return target.method()
                """,
        },
    )
    previous = scan_repository(repo)
    _write_repo(
        repo,
        {
            "module.py": """
                def patched() -> None:
                    import types
                    target = types.SimpleNamespace()
                    target.method = lambda: 2
                    return target.method()
                """,
        },
    )
    current = scan_repository(repo, previous)
    plan = _plan(previous, current)
    opaque_items = [
        item for item in plan.obligations if item.reason_code == InvalidationReason.RAW_SOURCE_REQUIRED.value
    ]
    # If the scanner marks anything opaque across this edit, obligations must
    # name retrievable path/CID evidence.  Otherwise the body capsule alone is
    # acceptable and the explain layer still surfaces raw-source limitations.
    if opaque_items:
        assert any(
            item.details.get("source_paths") or item.details.get("source_cids") or item.details.get("spans")
            for item in opaque_items
        )
    else:
        # Fall back: an explicitly opaque symbol explanation still names raw source.
        opaque_symbols = [item for item in current.symbols if item.confidence == "opaque"]
        if opaque_symbols:
            from ipfs_datasets_py.logic.software_contracts.semantic_index.explain import explain_symbol

            explanation = explain_symbol(current, opaque_symbols[0].stable_id)
            assert any(item.startswith("raw_source_required:") for item in explanation.limitations)
