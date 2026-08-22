"""Tests for US Code GovInfo API + archive ZIP source adaptation."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any, Dict, List

from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers import us_code_scraper as usc


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: Any = None,
        content: bytes = b"",
        headers: Dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.headers = headers or {}
        self.raw = io.BytesIO(content)

    def json(self) -> Any:
        if self._payload is not None:
            return self._payload
        return json.loads(self.content.decode("utf-8"))

    def iter_content(self, chunk_size: int = 1024):
        yield self.content


class _FakeSession:
    def __init__(self, mapping: Dict[str, _FakeResponse]) -> None:
        self.mapping = mapping
        self.calls: List[str] = []

    def get(self, url: str, *args: Any, **kwargs: Any) -> _FakeResponse:
        self.calls.append(str(url))
        for prefix, response in self.mapping.items():
            if str(url).startswith(prefix) or prefix in str(url):
                return response
        return _FakeResponse(status_code=404, content=b"missing")


def _minimal_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "ok")
    return buffer.getvalue()


def test_govinfo_api_zip_link_reads_vaquill_style_summary() -> None:
    session = _FakeSession(
        {
            "https://api.govinfo.gov/packages/USCODE-2024-title42/summary": _FakeResponse(
                payload={
                    "title": "THE PUBLIC HEALTH AND WELFARE",
                    "download": {
                        "zipLink": "https://api.govinfo.gov/packages/USCODE-2024-title42/zip"
                    },
                }
            )
        }
    )
    link = usc._govinfo_api_zip_link(session, year=2024, title_num="42")
    assert link == "https://api.govinfo.gov/packages/USCODE-2024-title42/zip"


def test_official_candidates_include_content_then_api_ziplink() -> None:
    session = _FakeSession(
        {
            "https://api.govinfo.gov/packages/USCODE-2024-title1/summary": _FakeResponse(
                payload={"download": {"zipLink": "https://example.test/title-1.zip"}}
            )
        }
    )
    candidates = usc.iter_official_title_zip_candidates(session, year=2024, title_num="1")
    assert candidates[0]["source"] == "govinfo-content-zip"
    assert candidates[0]["url"].endswith("USCODE-2024-title1.zip")
    assert candidates[1]["source"] == "govinfo-api-ziplink"
    assert candidates[1]["url"] == "https://example.test/title-1.zip"
    assert all(item["authority"] == "official" for item in candidates)


def test_wayback_cdx_prefers_zip_mimetype() -> None:
    session = _FakeSession(
        {
            "https://web.archive.org/cdx/search/cdx": _FakeResponse(
                payload=[
                    ["timestamp", "original", "mimetype"],
                    [
                        "20240101000000",
                        "https://www.govinfo.gov/content/pkg/USCODE-2024-title1/zip/USCODE-2024-title1.zip",
                        "text/html",
                    ],
                    [
                        "20240202000000",
                        "https://www.govinfo.gov/content/pkg/USCODE-2024-title1/zip/USCODE-2024-title1.zip",
                        "application/zip",
                    ],
                ]
            )
        }
    )
    url = usc._wayback_cdx_zip_url(
        session,
        "https://www.govinfo.gov/content/pkg/USCODE-2024-title1/zip/USCODE-2024-title1.zip",
    )
    assert url is not None
    assert url.startswith("https://web.archive.org/web/20240202000000id_/")
    assert url.endswith("USCODE-2024-title1.zip")


def test_download_title_zip_uses_api_ziplink_after_content_404(tmp_path) -> None:
    zip_bytes = _minimal_zip_bytes()
    session = _FakeSession(
        {
            "https://www.govinfo.gov/content/pkg/USCODE-2024-title1/zip/": _FakeResponse(
                status_code=404, content=b"missing"
            ),
            "https://api.govinfo.gov/packages/USCODE-2024-title1/summary": _FakeResponse(
                payload={"download": {"zipLink": "https://example.test/official-title-1.zip"}}
            ),
            "https://example.test/official-title-1.zip": _FakeResponse(content=zip_bytes),
        }
    )
    result = usc._download_title_zip(
        session,
        year=2024,
        title_num="1",
        cache_dir=tmp_path,
        force_download=True,
        max_attempts=1,
        include_official=True,
        include_recovery=False,
    )
    assert result["source"] == "govinfo-api-ziplink"
    assert result["source_authority_class"] == "official"
    assert usc._is_valid_zip_file(result["zip_path"])


def test_recovery_zip_is_labeled_recovery_not_official(tmp_path) -> None:
    zip_bytes = _minimal_zip_bytes()
    original = usc._govinfo_zip_url(2024, "1")
    session = _FakeSession(
        {
            "https://web.archive.org/cdx/search/cdx": _FakeResponse(
                payload=[
                    ["timestamp", "original", "mimetype"],
                    ["20240303000000", original, "application/zip"],
                ]
            ),
            "https://web.archive.org/web/20240303000000id_/": _FakeResponse(content=zip_bytes),
        }
    )
    result = usc._download_title_zip(
        session,
        year=2024,
        title_num="1",
        cache_dir=tmp_path,
        force_download=True,
        max_attempts=1,
        include_official=False,
        include_recovery=True,
    )
    assert result["source"] == "wayback-cdx"
    assert result["source_authority_class"] == "recovery"
    assert usc._source_authority_class(result["source"]) != "official"


def test_archive_is_is_not_a_zip_package_source() -> None:
    assert "archive_is" not in usc.RECOVERY_ZIP_SOURCES
    assert "archive.is" not in str(usc.RECOVERY_ZIP_SOURCES)


def test_mods_metadata_enriches_section_heading(tmp_path) -> None:
    mods = b"""<?xml version="1.0"?>
    <mods:mods xmlns:mods="http://www.loc.gov/mods/v3"
               xmlns:xlink="http://www.w3.org/1999/xlink">
      <mods:relatedItem ID="id-USCODE-2024-title1-chap1-sec1">
        <mods:titleInfo>
          <mods:title>Words denoting number, gender, and so forth</mods:title>
          <mods:partName>Sec. 1</mods:partName>
        </mods:titleInfo>
        <mods:relatedItem xlink:href="https://www.govinfo.gov/content/pkg/USCODE-2024-title1/pdf/USCODE-2024-title1-chap1-sec1.pdf"/>
      </mods:relatedItem>
    </mods:mods>
    """
    html = (
        "<html><body><h1>Sec. 1</h1>"
        "<p>In determining the meaning of any Act of Congress, unless the context indicates otherwise.</p>"
        "</body></html>"
    )
    zip_path = tmp_path / "USCODE-2024-title1.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("USCODE-2024-title1/mods.xml", mods)
        archive.writestr(
            "USCODE-2024-title1/html/USCODE-2024-title1-chap1-sec1.htm",
            html,
        )
    sections = usc._extract_sections_from_zip(
        zip_path,
        year=2024,
        title_num="1",
        title_name="General Provisions",
        include_metadata=True,
    )
    assert sections
    assert sections[0]["heading"].startswith("Words denoting number")
    assert sections[0]["pdf_url"].endswith(".pdf")
    assert sections[0]["granule_id"] == "USCODE-2024-title1-chap1-sec1"
