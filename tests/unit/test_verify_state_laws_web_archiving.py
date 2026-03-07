from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "ops" / "legal_data" / "verify_state_laws_web_archiving.py"
    spec = importlib.util.spec_from_file_location("verify_state_laws_web_archiving", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_norm_url_prefers_http_for_wayback() -> None:
    module = _load_module()

    url = "https://web.archive.org/web/20250124114611/https:///www.gencourt.state.nh.us/rsa/html/NHTOC/NHTOC-I.htm"

    assert module._norm_url(url) == "http://web.archive.org/web/20250124114611/https://www.gencourt.state.nh.us/rsa/html/NHTOC/NHTOC-I.htm"


def test_build_wayback_candidates_include_http_and_https_variants_for_live_url() -> None:
    module = _load_module()

    candidates = module.build_wayback_candidates("https://example.gov/code/section-1")

    assert candidates[:3] == [
        "http://web.archive.org/web/0/https://example.gov/code/section-1",
        "http://web.archive.org/web/2/https://example.gov/code/section-1",
        "http://web.archive.org/web/*/https://example.gov/code/section-1",
    ]
    assert "https://web.archive.org/web/0/https://example.gov/code/section-1" in candidates


def test_build_wayback_candidates_include_transport_fallback_for_archived_url() -> None:
    module = _load_module()

    archived = "https://web.archive.org/web/20170215063144/http:///iga.in.gov/static-documents/0/0/5/2/005284ae/TITLE6_AR1.1_ch15.pdf"
    candidates = module.build_wayback_candidates(archived)

    assert candidates == [
        "http://web.archive.org/web/20170215063144/http://iga.in.gov/static-documents/0/0/5/2/005284ae/TITLE6_AR1.1_ch15.pdf",
        "https://web.archive.org/web/20170215063144/http://iga.in.gov/static-documents/0/0/5/2/005284ae/TITLE6_AR1.1_ch15.pdf",
    ]