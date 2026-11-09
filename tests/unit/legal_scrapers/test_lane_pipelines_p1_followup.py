"""Priority-1 follow-up: schema docs, GR OCR wiring, city-codes collector, world_package catalog, Africa gates."""
from __future__ import annotations

import ast
import os
import re
import runpy
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRAPERS = REPO / "ipfs_datasets_py/processors/legal_scrapers/hub_integrated/world_law_pipeline/scrapers"
HUB_LS = REPO / "ipfs_datasets_py/processors/legal_scrapers/hub_integrated/legal_scrapers"
WP = REPO / "ipfs_datasets_py/processors/legal_scrapers/hub_dataset_scripts/endomorphosis__legal_scrapers/scrapers/world_package.py"
DOCS = REPO / "ipfs_datasets_py/processors/legal_scrapers/hub_dataset_scripts/endomorphosis__legal_scrapers/docs"
PIPELINE = SCRAPERS / "caselaw/pipeline"
GR = SCRAPERS / "municipal_lanes/gr"
CITY = SCRAPERS / "counties/lanes/us_city_codes"
AFRICA = SCRAPERS / "packaging/africa_me"
SECRET = re.compile(
    r"(?<![A-Za-z0-9_])(hf_[A-Za-z0-9]{30,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16})"
)
HEADER = "# Harvested collector path injection. Do not collect from /workspace."

P1_FILES = (
    list((PIPELINE / "docs").glob("*.md"))
    + list(GR.glob("*.py"))
    + [CITY / n for n in ("collect.py", "build.py", "probe.py")]
    + list(AFRICA.glob("*.py"))
    + [WP, PIPELINE / "gen_schema_doc.py"]
    + list(DOCS.glob("*.md"))
)


def test_p1_inventory():
    assert (PIPELINE / "docs" / "schema_caselaw_v0.md").is_file()
    assert (PIPELINE / "docs" / "schema_caselaw_v6.md").is_file()
    assert (PIPELINE / "docs" / "doc_v6_head.md").is_file()
    assert (GR / "fetch45.py").is_file() and (GR / "ocr45.py").is_file() and (GR / "build_ocr_rows.py").is_file()
    assert (CITY / "collect.py").is_file() and not (CITY / "t.py").exists()
    assert (AFRICA / "build_pack.py").is_file() and (AFRICA / "check_gates.py").is_file()
    assert (AFRICA / "quality_filters_b2.py").is_file() and (AFRICA / "domains.py").is_file()
    assert WP.is_file() and (DOCS / "README_legal_scrapers.md").is_file()
    assert not (DOCS / "NORMALIZER_STATUS.md").exists()


@pytest.mark.parametrize("path", [p for p in P1_FILES if p.suffix == ".py"], ids=lambda p: str(p.relative_to(REPO)))
def test_p1_py_parses_no_workspace_no_secrets(path: Path):
    src = path.read_text(encoding="utf-8")
    ast.parse(src, filename=str(path))
    leftovers = [ln for ln in src.splitlines() if "/workspace" in ln and HEADER not in ln]
    assert not leftovers, leftovers[:3]
    assert not any("/home/box" in ln for ln in src.splitlines())
    assert not SECRET.search(src)


def test_gen_schema_doc_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("pyarrow")
    # Run against package docs; write into a copy under tmp by pointing CASE_LAW_ROOT away but
    # package docs/ takes precedence for reads AND writes when present. Snapshot v6 then restore.
    v6 = PIPELINE / "docs" / "schema_caselaw_v6.md"
    before = v6.read_text(encoding="utf-8")
    monkeypatch.chdir(PIPELINE)
    monkeypatch.syspath_prepend(str(PIPELINE))
    # execute main
    ns = runpy.run_path(str(PIPELINE / "gen_schema_doc.py"), run_name="not_main")
    out = ns["main"]()
    assert out.is_file() and out.stat().st_size > 1000
    text = out.read_text(encoding="utf-8")
    assert "## Tables" in text and "`id`" in text and "decision" in text
    # schema version pin still present in module
    import caselaw_schema as cs
    assert cs.SCHEMA_VERSION == "caselaw-raw/v0"
    # restore prior committed docs content if regenerator rewrote in place
    if out == v6:
        v6.write_text(before, encoding="utf-8")


def test_world_package_catalog_and_min_text(monkeypatch, tmp_path):
    pytest.importorskip("pandas")
    src = WP.read_text(encoding="utf-8")
    assert "MIN_PACKAGE_TEXT" in src
    assert "Harvested collector path injection" in src
    # load module without executing uploads: exec META + helpers only
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(tmp_path / "corp"))
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(tmp_path / "col"))
    monkeypatch.setenv("MIN_PACKAGE_TEXT", "50")
    # import via runpy but stop before network — just compile-eval META
    tree = ast.parse(src)
    meta_assign = next(n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "META" for t in n.targets))
    ns: dict = {}
    exec(compile(ast.Module(body=[meta_assign], type_ignores=[]), str(WP), "exec"), ns)
    meta = ns["META"]
    assert len(meta) >= 50
    assert "gh" in meta and "zw" in meta and "al" in meta
    # instruments_to_frames respects MIN_PACKAGE_TEXT without network
    sys.path.insert(0, str(WP.parent))
    try:
        # Build a tiny fake instruments dir
        corp = tmp_path / "corp" / "zz" / "instruments"
        corp.mkdir(parents=True)
        import json
        (corp / "zz-short.json").write_text(json.dumps({"id": "a", "text": "x" * 10, "documents": []}), encoding="utf-8")
        (corp / "zz-long.json").write_text(json.dumps({"id": "b", "title": "T", "text": "y" * 60, "documents": [], "country": "zz"}), encoding="utf-8")
        import world_package as wp
        monkeypatch.setattr(wp, "ROOT", tmp_path / "corp")
        laws, arts = wp.instruments_to_frames("zz")
        assert list(laws["id"]) == ["b"]
    finally:
        sys.path.remove(str(WP.parent))


def test_africa_quality_filters_offline():
    sys.path.insert(0, str(AFRICA))
    try:
        import quality_filters_b2 as qf
    finally:
        sys.path.remove(str(AFRICA))
    assert qf.reject({"title": "Press release from ministry", "text": "for immediate release " * 20})
    assert not qf.reject({"title": "Law No. 12 of 2020 on Customs", "text": ("Article 1. " * 50)})


def test_africa_domains_merge():
    sys.path.insert(0, str(AFRICA))
    try:
        import domains
        import domains_b2
    finally:
        sys.path.remove(str(AFRICA))
    assert "GH" in domains.C and "NG" in domains_b2.C
    assert set(domains.C).issubset(set(domains_b2.C))


def test_gr_helpers_resolvable():
    helpers = HUB_LS / "municipal"
    assert (helpers / "gr_common.py").is_file()
    assert (helpers / "gr_fixes.py").is_file()
    assert (helpers / "schema.py").is_file()
    # fetch45 inserts helpers path
    src = (GR / "fetch45.py").read_text(encoding="utf-8")
    assert "_MUNI_HELPERS" in src
    sys.path.insert(0, str(helpers))
    try:
        import gr_common  # noqa: F401
        import gr_fixes  # noqa: F401
        import schema as mschema
        assert hasattr(mschema, "MUNICIPAL_LAWS_SCHEMA")
    finally:
        sys.path.remove(str(helpers))


def test_city_collect_env_root(tmp_path, monkeypatch):
    monkeypatch.setenv("US_CITY_CODES_ROOT", str(tmp_path / "cities"))
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_WORKSPACE", str(tmp_path / "ws"))
    # import-time only needs optional deps; collect imports bs4/pyarrow/requests
    pytest.importorskip("bs4")
    pytest.importorskip("pyarrow")
    pytest.importorskip("requests")
    sys.path.insert(0, str(CITY))
    try:
        import collect
    finally:
        sys.path.remove(str(CITY))
    assert collect.BASE == str(tmp_path / "cities")
    ok, _, _ = collect.resources_ok()
    assert isinstance(ok, bool)
    assert "municode.com" in collect.GATED


def test_docs_curated_not_live_status():
    names = {p.name for p in DOCS.glob("*")}
    assert "README_legal_scrapers.md" in names
    assert "WORLD_COVERAGE_AUDIT.md" in names
    assert "NORMALIZER_STATUS.md" not in names
