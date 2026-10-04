"""The connected Lean law package. Fixtures only. A build is not an admit."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal.lake_probe import MAX_SOURCE, pattern_from_rule
from ipfs_datasets_py.logic.autoformal.law_package import (
    LawPackageError,
    assemble_law_package,
    lake_build_law,
    pack_section_files,
    upload_law_package,
    write_law_package,
)
from ipfs_datasets_py.logic.autoformal.lean_units import statute_fingerprint, term_fingerprint
from ipfs_datasets_py.logic.autoformal.meta_ontology import normalize_lookup


os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")

_FORBIDDEN = __import__("re").compile(r"\b(?:sorry|admit|axiom)\b")


def _term_id(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}\n{value}".encode()).hexdigest()


def _write(path: Path, rows: list[dict], schema: pa.Schema) -> None:
    if rows:
        table = pa.Table.from_pylist(rows, schema=schema)
    else:
        table = pa.table({field.name: pa.array([], type=field.type) for field in schema}, schema=schema)
    pq.write_table(table, path)


def _string_schema(names: list[str], *, bools: list[str] | None = None) -> pa.Schema:
    fields = [(name, pa.bool_() if name in set(bools or []) else pa.string()) for name in names]
    return pa.schema(fields)


def _occurrence(**fields: str) -> dict:
    row = {
        "act": "", "admitted": False, "category": "", "definition_targets": "[]",
        "document_id": "", "document_label": "", "entity_id": "", "formalized": False,
        "formula": "", "gap_span_ids": "[]", "hit_kind": "", "kind": "", "legal_id": "",
        "modality": "", "normalized": "", "object": "", "open_stitch_slots": "[]",
        "participant": "", "reasons": "[]", "section_label": "", "span_id": "",
        "state": "", "surface": "", "term_id": "",
    }
    row.update(fields)
    row["admitted"] = False
    row["formalized"] = False
    return row


def _term(kind: str, value: str) -> dict:
    return {
        "admitted": False,
        "category": "",
        "formalized": False,
        "kind": kind,
        "overflow": False,
        "statute_ids": json.dumps(["usc:us:1:1"]),
        "term_id": _term_id(kind, value),
        "value": value,
    }


def _span(legal_id: str, span_id: str, status: str, text: str, rule: dict) -> dict:
    return {
        "legal_id": legal_id,
        "rule_json": json.dumps(rule),
        "source_sha256": span_id,
        "source_span_id": span_id,
        "source_text": text,
        "status": status,
        "term_rows_json": "[]",
    }


def _build(tmp_path: Path) -> dict:
    stitch = tmp_path / "stitch"
    stitch.mkdir()
    logic = stitch / "kg-logic-index.parquet"
    logic.write_bytes(b"logic-index-bytes")
    terms = [
        _term("actor", "The President"),
        _term("actor", "the president"),
        _term("action", "theft"),
        _term("action", "steal"),
        _term("actor", "A person"),
        _term("object", "signature"),
        _term("action", "publish"),
        _term("object", "notice"),
        _term("decompiled", "decompiled habeas text"),
    ]
    _write(stitch / "term-index.parquet", terms, _string_schema(
        ["admitted", "category", "formalized", "kind", "overflow", "statute_ids", "term_id", "value"],
        bools=["admitted", "formalized", "overflow"],
    ))
    _write(stitch / "section-neighborhoods.parquet", [{
        "admitted": False,
        "definition_targets": json.dumps(["usc:us:1:8", "usc:us:1:9"]),
        "entity_id": "doc1:section:1",
        "formalized": False,
        "gap_span_ids": json.dumps(["span-gap"]),
        "open_stitch_slots": json.dumps(["stitch:span-open:actor"]),
        "reasons": json.dumps(["unresolved_citation"]),
        "sealed_span_ids": json.dumps(["span-theft", "span-president", "span-open", "span-habeas"]),
        "source_hashes": "[]",
        "span_legal_id": "usc:us:1:1",
    }], _string_schema(
        ["admitted", "definition_targets", "entity_id", "formalized", "gap_span_ids",
         "open_stitch_slots", "reasons", "sealed_span_ids", "source_hashes", "span_legal_id"],
        bools=["admitted", "formalized"],
    ))
    _write(stitch / "inconsistencies.parquet", [{
        "admitted": False,
        "entity_id": "doc2:section:2",
        "evidence": "pending",
        "formalized": False,
        "inconsistency_id": "inc-pending",
        "kind": "section_not_ready",
        "overflow_ids": "[]",
        "span_id": "span-pending",
        "term_id": "",
    }], _string_schema(
        ["admitted", "entity_id", "evidence", "formalized", "inconsistency_id", "kind",
         "overflow_ids", "span_id", "term_id"],
        bools=["admitted", "formalized"],
    ))
    _write(stitch / "lean-units.parquet", [], _string_schema(
        ["admitted", "formalized", "lake_error", "lake_ok", "lean_source", "unit_id", "unit_kind"],
        bools=["admitted", "formalized", "lake_ok"],
    ))
    _write(stitch / "logic-occurrences.parquet", [
        _occurrence(
            document_id="doc1", document_label="First document", entity_id="doc1:section:1",
            hit_kind="mention", legal_id="usc:us:1:1", normalized="habeas corpus",
            section_label="1", span_id="span-habeas", surface="habeas corpus",
        ),
        _occurrence(
            document_id="doc1", document_label="First document", entity_id="doc1:section:1",
            hit_kind="label", legal_id="usc:us:1:1", section_label="1", surface="1",
        ),
        _occurrence(
            document_id="doc2", document_label="Second document", entity_id="doc2:section:2",
            hit_kind="label", legal_id="usc:us:2:2", reasons=json.dumps(["section_not_ready"]),
            section_label="2", surface="2",
        ),
    ], _string_schema(
        ["act", "admitted", "category", "definition_targets", "document_id", "document_label",
         "entity_id", "formalized", "formula", "gap_span_ids", "hit_kind", "kind", "legal_id",
         "modality", "normalized", "object", "open_stitch_slots", "participant", "reasons",
         "section_label", "span_id", "state", "surface", "term_id"],
        bools=["admitted", "formalized"],
    ))
    spans = tmp_path / "sealed-spans.parquet"
    _write(spans, [
        _span("usc:us:1:1", "span-theft", "sealed", "A person shall not commit theft of a signature.",
              {"actor": "A person", "action": "theft", "object": "signature", "modality": "prohibition"}),
        _span("usc:us:1:1", "span-president", "sealed", "The President shall publish notice.",
              {"actor": "The President", "action": "publish", "object": "notice", "modality": "obligation"}),
        _span("usc:us:1:1", "span-open", "sealed", "Notice shall be published.",
              {"actor": "", "action": "publish", "object": "notice", "modality": "obligation"}),
        _span("usc:us:1:1", "span-habeas", "sealed", "The court shall grant habeas corpus.",
              {"actor": "The court", "action": "grant", "object": "the writ", "modality": "obligation"}),
        _span("usc:us:1:1", "span-gap", "gap", "", {}),
        _span("usc:us:2:2", "span-pending", "pending", "This section is not ready.", {}),
    ], _string_schema(
        ["legal_id", "rule_json", "source_sha256", "source_span_id", "source_text", "status", "term_rows_json"],
    ))
    assembled = assemble_law_package(stitch, spans)
    return {
        "assembled": assembled,
        "files": assembled["files"],
        "logic": logic,
        "logic_bytes": logic.read_bytes(),
        "manifest": assembled["manifest"],
        "spans": spans,
        "stitch": stitch,
    }


def _script():
    path = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/publish_uscode_lean_for_law.py"
    spec = importlib.util.spec_from_file_location("_publish_uscode_lean_for_law", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _joined(files: dict[str, str], prefix: str = "") -> str:
    return "\n".join(source for path, source in sorted(files.items()) if path.startswith(prefix))


def _law_sources(files: dict[str, str]) -> list[str]:
    return [source for path, source in files.items() if path.startswith("Law/") and path.endswith(".lean")]


@pytest.fixture
def law(tmp_path: Path) -> dict:
    return _build(tmp_path)


def test_president_is_one_participant_and_theft_is_not_steal(law: dict) -> None:
    files = law["files"]
    text = _joined(files, "Law/Term/")
    assert text.count("def participant_president :") == 1
    assert text.count("def act_theft :") == 1
    assert text.count("def act_steal :") == 1
    theft_path = next(path for path, source in files.items() if "def act_theft :" in source)
    steal_path = next(path for path, source in files.items() if "def act_steal :" in source)
    assert theft_path != steal_path
    pairs = [
        ("The President", _term_id("actor", "The President")),
        ("the president", _term_id("actor", "the president")),
    ]
    winner = min(pairs, key=lambda item: item[1])[0]
    expected = term_fingerprint("actor", winner)
    assert f"def participant_president_fingerprint : Nat := {expected}" in text
    assert term_fingerprint("action", "theft") != term_fingerprint("action", "steal")
    assert f"def act_theft_fingerprint : Nat := {term_fingerprint('action', 'theft')}" in text
    assert f"def act_steal_fingerprint : Nat := {term_fingerprint('action', 'steal')}" in text
    assert "decompiled habeas text" not in _joined(files, "Law/")
    president_ids = {item[1] for item in pairs}
    assert any(all(term_id in row["term_id"] for term_id in president_ids) for row in law["manifest"])
    assert normalize_lookup("The President") == normalize_lookup("the president") == "president"


def test_theft_section_names_shared_terms_and_locks_the_same_fingerprints(law: dict) -> None:
    files = law["files"]
    section = _joined(files, "Law/Title/T1/S1")
    theft_path = next(path for path, source in files.items() if "def act_theft :" in source)
    person_path = next(path for path, source in files.items() if "def participant_person :" in source)
    signature_path = next(path for path, source in files.items() if "def object_signature :" in source)

    def module_name(path: str) -> str:
        return ".".join(Path(path).with_suffix("").parts)

    assert f"import {module_name(theft_path)}" in section
    assert f"import {module_name(person_path)}" in section
    assert f"import {module_name(signature_path)}" in section
    assert "Law.Term.Act.act_theft" in section
    assert "Law.Term.Participant.participant_person" in section
    assert "Law.Term.Object.object_signature" in section
    assert f"def statuteFingerprint : Nat := {statute_fingerprint('usc:us:1:1')}" in section
    pattern = pattern_from_rule({
        "action": "theft", "actor": "A person", "modality": "prohibition", "object": "signature",
    })
    assert pattern is not None
    assert any(
        line.startswith("def normFingerprint") and str(pattern["fingerprint"]) in line
        for line in section.splitlines()
    )
    assert all(not line.startswith("import Law.Title") for line in section.splitlines())


def test_citations_stop_at_two_hops_and_unresolved_is_not_an_import(law: dict) -> None:
    files = law["files"]
    cite = _joined(files, "Law/Cite/")
    assert "import Law.Title.T1.S1" in cite
    assert "import Law.Title.T1.S8" in cite
    assert "import Law.Title.T1.S9" in cite
    assert "Law.Title.T9" not in cite
    assert "usc:us:9:9" not in _joined(files)
    assert "Law.Title.T1.S1.usedStatute0 = Law.Title.T1.S8.statuteFingerprint" in cite
    assert "Law.Title.T1.S1.usedStatute1 = Law.Title.T1.S9.statuteFingerprint" in cite
    assert f"def statuteFingerprint : Nat := {statute_fingerprint('usc:us:1:8')}" in files["Law/Title/T1/S8.lean"]
    assert f"def statuteFingerprint : Nat := {statute_fingerprint('usc:us:1:9')}" in files["Law/Title/T1/S9.lean"]
    section = _joined(files, "Law/Title/T1/S1")
    assert 'def unresolvedCitation : String := "unresolved_citation"' in section
    assert all("unresolved" not in line for line in section.splitlines() if line.startswith("import "))
    assert "import Law.Cite" not in _joined(files)


def test_habeas_is_a_mention_and_an_open_actor_is_a_slot(law: dict) -> None:
    files = law["files"]
    section = _joined(files, "Law/Title/T1/S1")
    whole = _joined(files, "Law/")
    assert "def mention_habeas_corpus" in section
    assert "Law.Term.Act.act_habeas" not in whole
    assert "Law.Term.Act.habeas_corpus" not in whole
    assert "stitch:span-open:actor" in section
    assert "def clause_span_open" not in section
    assert "Law/Title/T2/S2.lean" not in files
    assert not any(path.startswith("Law/Title/T2/") for path in files)
    assert any(
        row["reason"] == "section_not_ready" and row["legal_id"] == "usc:us:2:2" and "span-pending" in row["term_id"]
        for row in law["manifest"]
    )


def test_document_imports_its_one_ready_section(law: dict) -> None:
    files = law["files"]
    document = files["Law/Document/doc1.lean"]
    assert "import Law.Title.T1.S1" in document
    assert f"def documentFingerprint : Nat := {statute_fingerprint('usc:us:1:1')}" in document
    assert "Law.Title.T1.S1.statuteFingerprint" in document
    assert "Law/Document/doc2.lean" not in files
    assert not any("doc2" in path for path in files)


def test_generated_law_has_no_forbidden_tokens_or_outside_imports(law: dict) -> None:
    files = law["files"]
    assert files["lean-toolchain"] == "leanprover/lean4:v4.26.0\n"
    assert "Mathlib" not in files["lakefile.lean"]
    assert "import Lake" in files["lakefile.lean"]
    assert "require" not in files["lakefile.lean"]
    for path, source in files.items():
        if not path.startswith("Law/"):
            continue
        assert _FORBIDDEN.search(source) is None
        for line in source.splitlines():
            if line.startswith("import "):
                assert line.split()[1].startswith("Law.")
    assert all(row["admitted"] is False and row["formalized"] is False and row["lake_ok"] is False for row in law["manifest"])
    assert all(row["lake_error"] == "lake_not_run" for row in law["manifest"])


def test_long_section_is_sharded_under_the_source_cap() -> None:
    from ipfs_datasets_py.logic.autoformal.law_package import law_module

    info = law_module("usc:us:1:1")
    section = {
        **info,
        "codifies": "",
        "fingerprint": statute_fingerprint("usc:us:1:1"),
        "gaps": [],
        "header": True,
        "mentions": [],
        "slots": [],
        "unresolved": False,
        "used": [],
        "used_only": False,
    }
    clauses = []
    for index in range(80):
        clauses.append({
            "act": "Law.Term.Act.act_theft",
            "fingerprint": 1000 + index,
            "imports": ["Law.Term.Act.H2d.S00", "Law.Term.Participant.H38.S00"],
            "modality": 0,
            "name": f"clause_span_{index}",
            "norm_index": index,
            "object_ref": "",
            "participant": "Law.Term.Participant.participant_person",
            "span_id": f"span-{index}",
            "state_ref": "",
        })
    packed = pack_section_files(section, clauses)
    assert len(packed) >= 2
    assert packed[0][0] == "Law/Title/T1/S1.lean"
    assert any(path.endswith("/C00.lean") for path, _, _, _ in packed)
    assert all(len(source.encode("utf-8")) <= MAX_SOURCE for _, _, source, _ in packed)


def test_writer_refuses_protected_names(tmp_path: Path) -> None:
    with pytest.raises(LawPackageError, match="sealed-spans"):
        write_law_package(tmp_path / "out", {"files": {"sealed-spans.parquet": "x"}, "manifest": []})


def test_repeated_manifest_hash_is_not_uploaded(law: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "pkg"
    write_law_package(out, law["assembled"])
    digest = hashlib.sha256((out / "autoformal/law/manifest.parquet").read_bytes()).hexdigest()
    stamp = out / "autoformal/law/manifest.sha256"
    stamp.write_text(digest + "\n", encoding="utf-8")

    def refuse(name, *args, **kwargs):
        if str(name).startswith("huggingface"):
            raise AssertionError("upload attempted")
        return original(name, *args, **kwargs)

    original = __import__("builtins").__import__
    monkeypatch.setattr("builtins.__import__", refuse)
    result = upload_law_package(out)
    assert result["uploaded"] is False
    assert result["skipped"] is True
    assert result["admitted"] is False
    assert result["formalized"] is False


def test_lake_cap_does_not_start_a_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    law_dir = tmp_path / "Law"
    law_dir.mkdir()
    for index in range(65):
        (law_dir / f"M{index}.lean").write_text("def x : Nat := 0\n", encoding="utf-8")

    def refuse(*_args, **_kwargs):
        raise AssertionError("lake started")

    monkeypatch.setattr(subprocess, "run", refuse)
    result = lake_build_law(tmp_path)
    assert result["lake_ok"] is False
    assert result["lake_error"] == "lake_module_cap"
    assert result["formalized"] is False
    assert result["admitted"] is False


def test_default_script_does_not_call_lake_or_upload(law: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    script = _script()

    def refuse(*_args, **_kwargs):
        raise AssertionError("side effect")

    monkeypatch.setattr(script, "upload_law_package", refuse)
    monkeypatch.setattr(script, "lake_build_law", refuse)
    out = tmp_path / "lean-out"
    before = law["logic_bytes"]
    code = script.main([
        "--stitch-dir", str(law["stitch"]),
        "--spans", str(law["spans"]),
        "--out", str(out),
    ])
    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["admitted"] is False
    assert report["formalized"] is False
    assert report["uploaded"] is False
    assert report["lake_ok"] is False
    assert law["logic"].read_bytes() == before
    assert not (out / "kg-logic-index.parquet").exists()
    assert not (out / "sealed-spans.parquet").exists()
    manifest = pq.read_table(out / "autoformal/law/manifest.parquet").to_pylist()
    assert manifest
    assert all(row["admitted"] is False and row["formalized"] is False and row["lake_ok"] is False for row in manifest)
    assert (out / "lean-toolchain").read_text(encoding="utf-8") == "leanprover/lean4:v4.26.0\n"
    assert any(row["reason"] == "section_not_ready" and row["legal_id"] == "usc:us:2:2" for row in manifest)
