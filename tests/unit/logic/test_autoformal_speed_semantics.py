"""Semantic guards for inference speed changes. None of these checks admits Lean."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic import autoformal
from ipfs_datasets_py.logic.autoformal import tree_pin
from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CanonicalAtomVocabulary,
    CanonicalErrorCode,
    CompilerRequest,
    OperationStatus,
)


DATASETS_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = DATASETS_ROOT.parent.parent
GATES = (
    "Company A shall submit backup report within 10 days unless emergency.",
    "The agency shall not disclose records.",
    "The officer shall retain the file for at least 20 days.",
)


@pytest.fixture(scope="module")
def statement_lock():
    # Load this small rendering module without importing the entire JevOps app.
    path = WORKSPACE_ROOT / "JevOps/jevops/statement_lock.py"
    spec = importlib.util.spec_from_file_location("speed_semantics_statement_lock", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclass annotations resolve through the defining module. Match the
    # normal import protocol while still avoiding the full JevOps application.
    missing = object()
    previous = sys.modules.get(spec.name, missing)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        if previous is missing:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = previous


@pytest.fixture(scope="module")
def compiled_gates():
    session = autoformal.AutoformalSession()
    rows = []
    for index, text in enumerate(GATES):
        result = autoformal.compile_span(session, text, f"speed-gate-{index}")
        assert result["compiler_status"] == "compiled"
        row = session.rows[-1].public()
        vocabulary = session.vocabularies[row["clause_id"]]
        assert vocabulary["actors"] and vocabulary["actions"]
        assert all(isinstance(atom, str) for atoms in vocabulary.values() for atom in atoms)
        assert row["status"] == "roundtrip_ok"
        assert row["admitted"] is False
        rows.append((row, vocabulary))
    return rows


def test_workspace_tree_pin_checks_all_three_components(monkeypatch, tmp_path):
    assert tree_pin.workspace_root() == DATASETS_ROOT
    resolved = tree_pin.require_workspace_logic_tree()
    assert set(resolved) == {"compiler", "decompiler", "parser"}
    assert all(DATASETS_ROOT in Path(path).parents for path in resolved.values())

    imported = tree_pin.importlib.import_module
    outside = tmp_path / "deontic_parser.py"
    outside.write_text("# drifted parser\n", encoding="utf-8")

    def drifted_import(name):
        if name.endswith("deontic_parser"):
            return SimpleNamespace(__file__=str(outside))
        return imported(name)

    monkeypatch.setattr(tree_pin.importlib, "import_module", drifted_import)
    with pytest.raises(tree_pin.LogicTreePinError, match="parser="):
        tree_pin.require_workspace_logic_tree()


def test_deadline_and_exception_remain_nonrenderable(compiled_gates, statement_lock):
    row, vocabulary = compiled_gates[0]
    assert vocabulary["actors"] == ["Company A"]
    assert vocabulary["objects"] == ["backup report"]
    assert row["rule"]["modality"] == "O"
    assert row["rule"]["exceptions"] == ["emergency"]
    assert row["rule"]["temporal_records"] == [
        {"temporal_kind": "within_duration", "value": "10 days", "quantity": 10}
    ]
    assert "10 days" in row["decompiled"]
    assert "emergency" in row["decompiled"]
    assert statement_lock.pattern_from_rule(row["rule"]) is None
    assert statement_lock.render_lean(statement_lock.pattern_from_rule(row["rule"])) == ""


def test_prohibition_remains_negative(compiled_gates):
    row, vocabulary = compiled_gates[1]
    assert vocabulary == {
        "actors": ["agency"], "actions": ["disclose"], "objects": ["records"], "qualifiers": []
    }
    assert row["rule"]["modality"] == "F"
    assert row["decompiled"] == "Agency must not disclose records."


def test_minimum_retains_quantity_without_duplicate_temporal_text(compiled_gates, statement_lock):
    row, vocabulary = compiled_gates[2]
    assert vocabulary["objects"] == ["the file for at least 20 days"]
    assert row["rule"]["temporal_records"] == [
        {"temporal_kind": "minimum_duration", "value": "20 days", "quantity": 20}
    ]
    assert "at least 20 days" in row["decompiled"]
    assert "at least days" not in row["decompiled"]
    assert row["decompiled"].count("20 days") == 1
    pattern = statement_lock.pattern_from_rule(row["rule"])
    assert pattern == {"kind": "threshold", "fail": 19, "meet": 20}
    assert "def bound : Nat := 20" in statement_lock.render_lean(pattern)
    assert row["admitted"] is False


@pytest.mark.parametrize("quantity", [None, "20", 20.0, 0, 21])
def test_minimum_requires_matching_integer_quantity(quantity, compiled_gates, statement_lock):
    rule = deepcopy(compiled_gates[2][0]["rule"])
    rule["temporal_records"][0]["quantity"] = quantity
    assert statement_lock.pattern_from_rule(rule) is None


@pytest.mark.parametrize("text", GATES)
def test_empty_vocabulary_abstains_without_compiler_fallback(text):
    result = TypedDeonticCanonicalCompiler().compile(
        CompilerRequest(
            source_text=text,
            request_id="empty-vocabulary-speed-guard",
            atom_vocabulary=CanonicalAtomVocabulary(),
        )
    )
    assert result.status is OperationStatus.ABSTAINED
    assert result.canonical_ir is None
    assert result.error is not None
    assert result.error.code is CanonicalErrorCode.UNSUPPORTED_SEMANTICS


def test_no_parser_elements_skip_document_and_compiler(monkeypatch):
    text = "An explanatory heading with descriptive background."
    assert autoformal.vocabulary_from_clause(text) is None

    def unexpected(*_args, **_kwargs):
        pytest.fail("non-operative text reached document or compiler")

    monkeypatch.setattr(TypedDeonticCanonicalCompiler, "compile", unexpected)
    session = SimpleNamespace(open_document=unexpected, compile_clause=unexpected)
    assert autoformal.compile_span(session, text, "non-operative") == {
        "compiler_status": "abstain", "reason": "no_parser_elements", "decompiled": "", "fields": []
    }


@pytest.mark.parametrize("stored", [{}, {"actors": ["unrelated"], "actions": ["act"]}])
def test_compile_span_preserves_stored_vocabulary(stored, vocabulary_calls):
    session = autoformal.AutoformalSession()
    session.vocabularies["same-span-c0"] = deepcopy(stored)
    result = autoformal.compile_span(session, GATES[0], "same-span")
    assert session.vocabularies["same-span-c0"] == stored
    assert result["compiler_status"] == "abstain"
    assert vocabulary_calls == [GATES[0]]


@pytest.fixture
def vocabulary_calls(monkeypatch):
    calls = []
    original = autoformal.vocabulary_from_clause

    def record(text):
        calls.append(text)
        return original(text)

    monkeypatch.setattr(autoformal, "vocabulary_from_clause", record)
    return calls


def test_compile_span_extracts_vocabulary_once_for_exact_text(vocabulary_calls):
    session = autoformal.AutoformalSession()
    result = autoformal.compile_span(session, GATES[0], "exact-text")
    assert result["compiler_status"] == "compiled"
    assert vocabulary_calls == [GATES[0]]


def test_compile_span_uses_each_selected_clause_vocabulary_after_segmentation(vocabulary_calls):
    session = autoformal.AutoformalSession()
    result = autoformal.compile_span(session, GATES[1] + " " + GATES[2], "segmented")
    assert result["compiler_status"] == "compiled"
    assert len(session.rows) == 2
    assert [row.clause_id for row in session.rows] == ["segmented-c0", "segmented-c1"]
    assert [session.documents.clause("segmented", row.clause_id).text for row in session.rows] == list(GATES[1:])
    vocabularies = [session.vocabularies[row.clause_id] for row in session.rows]
    assert vocabularies == [
        {"actors": ["agency"], "actions": ["disclose"], "objects": ["records"], "qualifiers": []},
        {"actors": ["officer"], "actions": ["retain"], "objects": ["the file for at least 20 days"],
         "qualifiers": ["20 days"]},
    ]
    assert all(type(atom) is str for vocabulary in vocabularies
               for atoms in vocabulary.values() for atom in atoms)
    assert session.rows[0].rule["temporal"] == []
    assert "temporal_records" not in session.rows[0].rule
    assert session.rows[1].rule["temporal_records"] == [
        {"temporal_kind": "minimum_duration", "value": "20 days", "quantity": 20},
    ]
    assert type(session.rows[1].rule["temporal_records"][0]["quantity"]) is int
    # Neither selected clause may receive the other clause's whole-span atoms.
    for key in ("actors", "actions", "objects"):
        assert set(vocabularies[0][key]).isdisjoint(vocabularies[1][key])
    assert [row.rule["modality"] for row in session.rows] == ["F", "O"]
    assert all(row.status == "roundtrip_ok" and row.public()["admitted"] is False for row in session.rows)
    assert result["decompiled"] == (
        "Agency must not disclose records. Officer must retain the file for at least 20 days."
    )
    assert vocabulary_calls == [GATES[1] + " " + GATES[2], *GATES[1:]]
