"""Tests for deterministic repository-state assembly."""

from __future__ import annotations

from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import scan_repository_state


def _symbols(state):
    return {symbol.qualified_name: symbol for symbol in state.symbols}


def test_cold_and_incremental_scans_have_the_same_root(tmp_path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "sample.py").write_text("def answer(value: int) -> int:\n    return value + 1\n", encoding="utf-8")
    first = scan_repository_state(tmp_path, repository_id="repo:scanner")
    second = scan_repository_state(tmp_path, repository_id="repo:scanner", previous_state=first)
    assert first.state_cid == second.state_cid


def test_formatting_and_unrelated_edits_do_not_change_other_symbol_versions(tmp_path) -> None:
    path = tmp_path / "module.py"
    path.write_text("def stable():\n    return 1\n\ndef changed():\n    return 2\n", encoding="utf-8")
    first = scan_repository_state(tmp_path, repository_id="repo:scanner")
    path.write_text("\n\ndef stable():\n\treturn 1\n\ndef changed():\n    return 3\n", encoding="utf-8")
    second = scan_repository_state(tmp_path, repository_id="repo:scanner", previous_state=first)
    old, new = _symbols(first), _symbols(second)
    assert old["module.stable"].stable_id == new["module.stable"].stable_id
    assert old["module.stable"].version_cid == new["module.stable"].version_cid
    assert old["module.changed"].version_cid != new["module.changed"].version_cid


def test_syntax_failure_is_an_explicit_opaque_artifact(tmp_path) -> None:
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    state = scan_repository_state(tmp_path, repository_id="repo:scanner")
    artifact = next(item for item in state.artifacts if item.path == "broken.py")
    assert artifact.kind == "python-analysis"
    assert artifact.confidence == "opaque"
    assert artifact.metadata["diagnostics"]
