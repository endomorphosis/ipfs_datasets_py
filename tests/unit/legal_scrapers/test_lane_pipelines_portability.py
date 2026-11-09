"""Portability, secret-hygiene and behaviour checks for the lane pipelines integrated on 2026-11-08
(county / municipal / case-law / courts / state-laws / regs-EO / US city-code collectors under
hub_integrated/world_law_pipeline/scrapers). Offline only: no network, nothing written outside tmp_path."""
from __future__ import annotations

import ast
import os
import re
import site
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRAPERS = REPO / "ipfs_datasets_py/processors/legal_scrapers/hub_integrated/world_law_pipeline/scrapers"
LANE_DIRS = [
    SCRAPERS / "counties/lanes",
    SCRAPERS / "municipal_lanes",
    SCRAPERS / "caselaw/pipeline",
    SCRAPERS / "courts/lanes",
    SCRAPERS / "states/lanes",
]
LANE_FILES = sorted(p for d in LANE_DIRS for p in d.rglob("*.py")) + [
    SCRAPERS / "national/us/collect_eo_federal_register.py",
    SCRAPERS / "national/us/collect_ecfr_appendices.py",
]
PIPELINE = SCRAPERS / "caselaw/pipeline"
HEADER_COMMENT = "# Harvested collector path injection. Do not collect from /workspace."
SECRET_VALUE = re.compile(
    r"hf_[A-Za-z0-9]{30,}|ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
    r"|AKIA[0-9A-Z]{16}|xox[abpr]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{32,}|-----BEGIN [A-Z ]*PRIVATE KEY-----\s*\n[A-Za-z0-9+/=]{20,}"
)


def test_lane_inventory_present():
    assert len(LANE_FILES) >= 90
    for p in LANE_FILES:
        assert p.is_file(), p
    for lane in ("counties/lanes/gb", "counties/lanes/ke", "counties/lanes/us", "counties/lanes/us_city_codes",
                 "municipal_lanes/za/prov", "municipal_lanes/za/mun", "municipal_lanes/na", "municipal_lanes/jo_ps",
                 "caselaw/pipeline", "courts/lanes", "states/lanes"):
        assert any((SCRAPERS / lane).glob("*.py")), lane


@pytest.mark.parametrize("path", LANE_FILES, ids=lambda p: str(p.relative_to(SCRAPERS)))
def test_parses_and_has_no_hardcoded_workspace(path):
    src = path.read_text(encoding="utf-8")
    ast.parse(src, filename=str(path))
    leftovers = [ln for ln in src.splitlines() if "/workspace" in ln and ln.strip() != HEADER_COMMENT]
    assert not leftovers, leftovers[:3]


@pytest.mark.parametrize("path", LANE_FILES, ids=lambda p: str(p.relative_to(SCRAPERS)))
def test_no_embedded_credentials(path):
    hits = SECRET_VALUE.findall(path.read_text(encoding="utf-8"))
    assert not hits, f"{len(hits)} credential-like value(s)"


def test_sibling_imports_resolve_within_lane():
    """Every bare `import x` / `from x import` of a local helper must have x.py in the same directory."""
    local_helpers = {"polite", "packlib", "robots_guard", "wb", "caselaw_schema", "cl_common", "court_matcher",
                     "r6_rules", "collect_ps_molg", "collect_ke_samburu_muni", "stage_za_prov", "plan_za_prov",
                     "plan_za_metro", "pii_scan_za_prov", "pii_scan_za_metro", "bounds_za_prov", "bounds_za_metro",
                     "job1_cjeu"}
    missing = []
    for p in LANE_FILES:
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for n in names:
                if n in local_helpers and not (p.parent / f"{n}.py").exists():
                    missing.append(f"{p.relative_to(SCRAPERS)} -> {n}")
    assert not missing, missing


def _run(code: str, env_extra: dict[str, str], cwd: Path) -> str:
    env = {k: v for k, v in os.environ.items()
           if k not in ("IPFS_DATASETS_LEGAL_WORKSPACE", "IPFS_DATASETS_LEGAL_CORPORA_ROOT", "WORLD_LAW_ROOT")}
    env.setdefault("PYTHONUSERBASE", site.getuserbase())  # keep user site-packages when HOME is overridden
    env.update(env_extra)
    out = subprocess.run([sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout.strip()


def test_env_overrides_paths(tmp_path):
    pytest.importorskip("pyarrow"); pytest.importorskip("requests")
    ws, corp, world = tmp_path / "ws", tmp_path / "corp", tmp_path / "world"
    got = _run("import cl_common as c; print(c.OUT); print(c._CORPORA); print(c._WORLD)",
               {"IPFS_DATASETS_LEGAL_WORKSPACE": str(ws), "IPFS_DATASETS_LEGAL_CORPORA_ROOT": str(corp),
                "WORLD_LAW_ROOT": str(world), "HOME": str(tmp_path / "home")}, PIPELINE).splitlines()
    assert got == [f"{ws}/case_law/out", str(corp), str(world)]
    assert not ws.exists(), "importing must not create the workspace"


def test_default_paths_live_under_home(tmp_path):
    pytest.importorskip("pyarrow"); pytest.importorskip("requests")
    home = tmp_path / "home"
    got = _run("import cl_common as c; print(c.OUT); print(c._CORPORA)", {"HOME": str(home)}, PIPELINE).splitlines()
    assert got == [f"{home}/.ipfs_datasets/legal_workspace/case_law/out", f"{home}/.ipfs_datasets/legal_corpora"]


def test_court_matcher_fixture_paths():
    out = subprocess.run([sys.executable, "fixtures_court_paths.py"], cwd=PIPELINE, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert "court path fixtures ok" in out.stdout


def test_caselaw_schema_contracts():
    pa = pytest.importorskip("pyarrow")
    sys.path.insert(0, str(PIPELINE))
    try:
        import caselaw_schema as cs
    finally:
        sys.path.remove(str(PIPELINE))
    assert cs.SCHEMA_VERSION == "caselaw-raw/v0"
    assert cs.S == pa.string()  # pinned: string columns are pa.string(), never large_string
    assert cs.clean_label("  Hoge   Raad ") == "Hoge Raad"
    assert cs.clean_label("n/a") is None and cs.clean_label("undefined") is None
    text, n = cs.redact_emails("contact clerk@court.example.org or x \uff20 y")
    assert n == 1 and "clerk@court.example.org" not in text and cs.EMAIL_TOKEN in text
    assert cs.RE_ID.match("wc1:decision:" + "0" * 24) and not cs.RE_ID.match("wc1:decision:xyz")
    assert cs.RE_ECLI.match("ECLI:NL:HR:2020:1234")
