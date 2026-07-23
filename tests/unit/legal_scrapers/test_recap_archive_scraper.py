from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.legal_scrapers import recap_archive_scraper as recap_mod


class _MockResponse:
    def __init__(self, payload, status_code: int = 200, text: str = "ok") -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


@pytest.mark.anyio
async def test_get_recap_document_uses_api_token_from_environment(monkeypatch):
    captured = {"calls": []}

    def _fake_get(url, headers=None, timeout=30):  # noqa: ANN001
        captured["calls"].append({"url": url, "headers": dict(headers or {})})
        return _MockResponse(
            {
                "docket": "123",
                "case_name": "Doe v. Acme",
                "court": "ca9",
                "document_type": "opinion",
                "date_filed": "2026-01-01",
                "page_count": 3,
                "filepath_local": "/recap/doc.pdf",
                "plain_text": "opinion text",
                "description": "Opinion",
                "document_number": "10",
            }
        )

    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "token-from-env")
    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=_fake_get, exceptions=SimpleNamespace(Timeout=RuntimeError, RequestException=RuntimeError)))

    result = await recap_mod.get_recap_document("123")

    assert result["status"] == "success"
    assert captured["calls"][0]["headers"]["Authorization"] == "Token token-from-env"
    assert captured["calls"][0]["url"].endswith("/recap-documents/123/")


@pytest.mark.anyio
async def test_get_recap_document_backfills_case_and_court_from_docket(monkeypatch):
    calls = []

    def _fake_get(url, headers=None, timeout=30):  # noqa: ANN001
        calls.append((url, dict(headers or {})))
        if url.endswith('/recap-documents/11099071/'):
            return _MockResponse(
                {
                    "docket": None,
                    "absolute_url": "/docket/4521892/4808/old-carco-llc-fka-chrysler-llc/",
                    "case_name": None,
                    "court": None,
                    "document_type": 1,
                    "date_filed": None,
                    "page_count": None,
                    "filepath_local": None,
                    "plain_text": "",
                    "description": "Affidavit",
                    "document_number": "4808",
                    "pacer_doc_id": "126012781351",
                }
            )
        if url.endswith('/dockets/4521892/'):
            return _MockResponse(
                {
                    "id": 4521892,
                    "case_name": "Old Carco LLC, (f/k/a Chrysler LLC)",
                    "court": "https://www.courtlistener.com/api/rest/v3/courts/nysb/",
                    "court_id": "nysb",
                    "docket_number": "09-50002",
                    "date_filed": "2009-04-30",
                    "absolute_url": "/docket/4521892/old-carco-llc-fka-chrysler-llc/",
                }
            )
        if url.endswith('/courts/nysb/'):
            return _MockResponse(
                {
                    "id": "nysb",
                    "short_name": "S.D. New York",
                    "full_name": "United States Bankruptcy Court, S.D. New York",
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "token-from-env")
    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=_fake_get, exceptions=SimpleNamespace(Timeout=RuntimeError, RequestException=RuntimeError)))

    result = await recap_mod.get_recap_document("11099071")

    assert result["status"] == "success"
    assert result["document"]["docket_id"] == "4521892"
    assert result["document"]["case_name"] == "Old Carco LLC, (f/k/a Chrysler LLC)"
    assert result["document"]["court"] == "United States Bankruptcy Court, S.D. New York"
    assert result["document"]["date_filed"] == "2009-04-30"
    assert result["document"]["metadata"]["docket_number"] == "09-50002"
    assert result["document"]["metadata"]["court_id"] == "nysb"
    assert len(calls) == 3
    for _, headers in calls:
        assert headers["Authorization"] == "Token token-from-env"


@pytest.mark.anyio
async def test_scrape_recap_archive_threads_api_token_and_uses_package_scraping_state(monkeypatch):
    search_calls = []
    detail_calls = []

    async def _fake_search_recap_documents(**kwargs):
        search_calls.append(dict(kwargs))
        return {
            "status": "success",
            "documents": [
                {
                    "id": "doc-1",
                    "case_name": "Doe v. Acme",
                    "court": "ca9",
                    "description": "Opinion",
                }
            ],
            "count": 1,
        }

    async def _fake_get_recap_document(document_id, include_text=True, include_metadata=True, api_token=None):
        detail_calls.append(
            {
                "document_id": document_id,
                "include_text": include_text,
                "include_metadata": include_metadata,
                "api_token": api_token,
            }
        )
        return {
            "status": "success",
            "document": {
                "id": document_id,
                "text": "Detailed opinion text",
                "metadata": {"document_number": "10"},
            },
        }

    monkeypatch.setattr(recap_mod, "search_recap_documents", _fake_search_recap_documents)
    monkeypatch.setattr(recap_mod, "get_recap_document", _fake_get_recap_document)
    monkeypatch.setattr(recap_mod.time, "sleep", lambda _: None)

    result = await recap_mod.scrape_recap_archive(
        courts=["ca9"],
        document_types=["opinion"],
        filed_after="2026-01-01",
        filed_before="2026-01-31",
        include_text=True,
        include_metadata=True,
        rate_limit_delay=0.0,
        max_documents=1,
        job_id="unit_recap_job",
        api_token="explicit-token",
    )

    assert result["status"] == "success"
    assert result["metadata"]["documents_count"] == 1
    assert result["metadata"]["api_token_configured"] is True
    assert search_calls[0]["api_token"] == "explicit-token"
    assert detail_calls[0]["api_token"] == "explicit-token"
    assert result["data"][0]["text"] == "Detailed opinion text"