"""Per-statute and per-term Lean files define identities without admitting."""
from __future__ import annotations

from pathlib import Path

from ipfs_datasets_py.logic.autoformal.lean_units import (
    render_statute_lean,
    render_term_lean,
    statute_fingerprint,
    statute_lean_unit,
    term_fingerprint,
    term_lean_unit,
)
from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache


def _ok_check(source: str) -> dict:
    assert "import " not in source
    assert "sorry" not in source
    assert "theorem statuteDefined" in source or "theorem termDefined" in source
    return {"lake_ok": True, "error": "", "admitted": False, "formalized": False}


def test_statute_lean_defines_identity_and_clause_locks() -> None:
    source = render_statute_lean(
        "usc:us:5:552",
        [
            {
                "source_span_id": "s1",
                "source_sha256": "abc",
                "rule": {"modality": "obligation", "actor": "Agency", "action": "make", "object": "records"},
            }
        ],
    )
    assert f"def statuteFingerprint : Nat := {statute_fingerprint('usc:us:5:552')}" in source
    assert "theorem statuteDefined" in source
    assert "theorem clauseDefined0" in source
    assert "theorem normBoundary0" in source
    assert "sorry" not in source
    assert "admit" not in source.split()


def test_term_lean_defines_kind_value_and_using_statutes() -> None:
    source = render_term_lean("actor", "Agency", statute_ids=["usc:us:5:552", "usc:us:18:1001"])
    assert f"def termFingerprint : Nat := {term_fingerprint('actor', 'Agency')}" in source
    assert "theorem termDefined" in source
    assert "def statuteCount : Nat := 2" in source
    assert "theorem usedStatuteDefined0" in source
    assert "sorry" not in source


def test_cache_stores_statute_and_term_lean(tmp_path: Path) -> None:
    cache = SpanCache(tmp_path / "cache.duckdb")
    cache.apply_census(
        {
            "rows": [
                {
                    "agrees": True,
                    "decompiled": "Agency must make records available.",
                    "legal_id": "usc:us:5:552",
                    "rule": {"modality": "obligation", "actor": "Agency", "action": "make", "object": "records"},
                    "source_span_id": "s1",
                    "text": "Each agency shall make records available.",
                }
            ]
        },
        path_hashes={"ipfs_datasets_py/logic/deontic/utils/deontic_parser.py": "aaa"},
    )
    receipt = cache.build_lean_units(check=_ok_check, verify=True)
    assert receipt["statute_count"] == 1
    assert receipt["term_count"] >= 1
    assert receipt["statutes"][0]["legal_id"] == "usc:us:5:552"
    assert receipt["statutes"][0]["lake_ok"] is True
    assert receipt["admitted"] is False
    actors = [item for item in receipt["terms"] if item["kind"] == "actor"]
    assert actors[0]["value"] == "Agency"
    assert actors[0]["statute_count"] == 1
    again = cache.build_lean_units(check=_ok_check, verify=True)
    assert again["statutes"][0]["lake_ok"] is True
    cache.close()


def test_clause_overflow_keeps_twenty_four_and_records_the_rest() -> None:
    clauses = [
        {
            "source_span_id": f"s{index}",
            "source_sha256": "abc",
            "rule": {"modality": "obligation", "actor": "Agency", "action": "make", "object": "records"},
        }
        for index in range(25)
    ]
    unit = statute_lean_unit("usc:us:5:552", clauses)
    assert unit["overflow_ids"] == ["s24"]
    assert unit["kind"] == "lean_unit_overflow"
    assert unit["count"] == 24
    assert "def clauseCount : Nat := 24" in unit["lean"]
    assert "clauseFingerprint24" not in unit["lean"]
    assert unit["admitted"] is False and unit["formalized"] is False


def test_term_overflow_keeps_sixteen_statutes_and_records_the_rest() -> None:
    statutes = [f"usc:us:1:{index}" for index in range(17)]
    unit = term_lean_unit("actor", "Agency", statute_ids=statutes, term_id="term-actor")
    assert unit["overflow_ids"] == ["usc:us:1:16"]
    assert unit["overflow_kind"] == "lean_unit_overflow"
    assert unit["count"] == 16
    assert "def statuteCount : Nat := 16" in unit["lean"]
    assert "usedStatute16" not in unit["lean"]
    assert unit["admitted"] is False and unit["formalized"] is False
