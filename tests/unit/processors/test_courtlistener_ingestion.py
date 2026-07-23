from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Dict

from ipfs_datasets_py.processors.legal_data import (
    COURTLISTENER_RECAP_FETCH_REQUEST_TYPES,
    CourtListenerIngestionError,
    attach_available_courtlistener_recap_evidence_to_docket,
    attach_public_courtlistener_filing_pdfs_to_docket,
    build_courtlistener_recap_fetch_payload,
    build_packaged_docket_acquisition_plan,
    build_packaged_docket_recap_fetch_preflight,
    execute_packaged_docket_acquisition_plan,
    extract_courtlistener_public_filing_pdf_texts,
    fetch_courtlistener_docket,
    fetch_pacer_document_with_browser,
    fetch_random_courtlistener_docket,
    find_rich_courtlistener_docket,
    get_courtlistener_recap_fetch_request,
    probe_courtlistener_public_filing_pdfs,
    probe_courtlistener_document_acquisition_target,
    resolve_pacer_password,
    resolve_pacer_username,
    sample_random_courtlistener_dockets_batch,
    submit_courtlistener_recap_fetch_request,
    submit_packaged_docket_recap_fetch_requests,
)
from ipfs_datasets_py.processors.legal_scrapers.shared_fetch_cache import SharedFetchCache


class _MockResponse:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200, content: bytes | None = None) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.content = content or b""

    def json(self) -> Dict[str, Any]:
        return self._payload


class _MockThrottleRequests:
    def get(self, url: str, headers=None, timeout: int = 30):  # noqa: ANN001
        return _MockResponse({"detail": "Request was throttled. Expected available in 2515 seconds."}, status_code=429)


class _MockRequests:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(self, url: str, headers=None, timeout: int = 30):  # noqa: ANN001
        self.calls.append(url)
        if url.endswith("/dockets/12345/"):
            return _MockResponse(
                {
                    "id": 12345,
                    "case_name": "Doe v. Acme Housing",
                    "court": "ord",
                    "court_name": "U.S. District Court",
                    "docket_number": "3:26-cv-00001",
                    "date_filed": "2026-01-02",
                    "absolute_url": "/docket/12345/doe-v-acme-housing/",
                }
            )
        if "docket-entries/?docket=12345" in url:
            return _MockResponse(
                {
                    "count": 1,
                    "next": None,
                    "results": [
                        {
                            "id": 44,
                            "entry_number": "12",
                            "date_filed": "2026-01-10",
                            "description": "Motion for preliminary injunction",
                            "absolute_url": "/recap/gov.uscourts.ord.1.12.0/",
                        }
                    ],
                }
            )
        if "parties/?docket=12345" in url:
            return _MockResponse(
                {
                    "count": 2,
                    "next": None,
                    "results": [
                        {"id": 1, "name": "Jane Doe", "party_types": [{"name": "Plaintiff"}]},
                        {"id": 2, "name": "Acme Housing", "party_types": [{"name": "Defendant"}]},
                    ],
                }
            )
        if "recap-documents/?docket_entry__docket=12345" in url:
            return _MockResponse(
                {
                    "count": 1,
                    "next": None,
                    "results": [
                        {
                            "id": 987,
                            "document_number": "12-1",
                            "description": "Declaration of Jane Doe",
                            "date_filed": "2026-01-10",
                            "plain_text": "",
                            "document_type": "declaration",
                            "filepath_local": "/pdf/987/declaration.pdf",
                        }
                    ],
                }
            )
        if url.endswith("/recap-documents/987/"):
            return _MockResponse(
                {
                    "id": 987,
                    "document_number": "12-1",
                    "description": "Declaration of Jane Doe",
                    "date_filed": "2026-01-10",
                    "plain_text": "I declare under penalty of perjury that the lockout occurred on January 5.",
                    "document_type": "declaration",
                    "filepath_local": "/pdf/987/declaration.pdf",
                }
            )
        if url.endswith("/pdf/987/declaration.pdf"):
            return _MockResponse({}, content=b"%PDF-1.4 mock pdf bytes")
        raise AssertionError(f"Unexpected URL: {url}")


class _MockRecapFetchRequests:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.gets: list[str] = []

    def post(self, url: str, headers=None, json=None, timeout: int = 30):  # noqa: ANN001
        self.posts.append(
            {
                "url": url,
                "headers": dict(headers or {}),
                "json": dict(json or {}),
                "timeout": timeout,
            }
        )
        return _MockResponse(
            {
                "id": 321,
                "status": 1,
                "request_type": int((json or {}).get("request_type") or 0),
                "docket_number": (json or {}).get("docket_number"),
                "court": (json or {}).get("court"),
            },
            status_code=201,
        )

    def get(self, url: str, headers=None, timeout: int = 30):  # noqa: ANN001
        self.gets.append(url)
        if url.endswith("/recap-fetch/321/"):
            return _MockResponse(
                {
                    "id": 321,
                    "status": 2,
                    "request_type": 1,
                    "message": "Processed successfully.",
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")


class _MockCourtUrlRequests(_MockRequests):
    def get(self, url: str, headers=None, timeout: int = 30):  # noqa: ANN001
        if url.endswith("/dockets/12345/"):
            return _MockResponse(
                {
                    "id": 12345,
                    "case_name": "Doe v. Acme Housing",
                    "court": "https://www.courtlistener.com/api/rest/v4/courts/ord/",
                    "court_id": "ord",
                    "court_name": "U.S. District Court",
                    "docket_number": "3:26-cv-00001",
                    "pacer_case_id": "123456",
                    "date_filed": "2026-01-02",
                    "absolute_url": "/docket/12345/doe-v-acme-housing/",
                }
            )
        return super().get(url, headers=headers, timeout=timeout)


class _MockRequestsNoPlainText(_MockRequests):
    def get(self, url: str, headers=None, timeout: int = 30):  # noqa: ANN001
        if url.endswith("/recap-documents/987/"):
            return _MockResponse(
                {
                    "id": 987,
                    "document_number": "12-1",
                    "description": "Declaration of Jane Doe",
                    "date_filed": "2026-01-10",
                    "plain_text": "",
                    "document_type": "declaration",
                    "filepath_local": "/pdf/987/declaration.pdf",
                }
            )
        return super().get(url, headers=headers, timeout=timeout)


class _MockRandomRequests(_MockRequests):
    def get(self, url: str, headers=None, timeout: int = 30):  # noqa: ANN001
        if "dockets/?page=1" in url:
            return _MockResponse({"results": [{"id": 99998}, {"id": 99999}]})
        if "dockets/?page=2" in url:
            return _MockResponse({"results": []})
        if "docket-entries/?docket=99998" in url:
            return _MockResponse({"count": 0, "next": None, "results": []})
        if "recap-documents/?docket_entry__docket=99998" in url:
            return _MockResponse({"count": 0, "next": None, "results": []})
        if url.endswith("/dockets/99999/"):
            return _MockResponse(
                {
                    "id": 99999,
                    "case_name": "Random Case",
                    "court": "rnd",
                    "court_name": "Random Court",
                    "docket_number": "9:26-cv-99999",
                    "date_filed": "2026-01-02",
                    "absolute_url": "/docket/99999/random-case/",
                }
            )
        if url.endswith("/dockets/99998/"):
            return _MockResponse(
                {
                    "id": 99998,
                    "case_name": "Too Small",
                    "court": "rnd",
                    "court_name": "Random Court",
                    "docket_number": "9:26-cv-99998",
                    "date_filed": "2026-01-01",
                    "absolute_url": "/docket/99998/too-small/",
                }
            )
        if "docket-entries/?docket=99999" in url or "parties/?docket=99999" in url or "recap-documents/?docket_entry__docket=99999" in url:
            if "docket-entries/?docket=99999" in url:
                return _MockResponse(
                    {
                        "count": 3,
                        "next": None,
                        "results": [
                            {"id": 1, "entry_number": "1", "date_filed": "2026-01-02", "description": "Complaint"},
                            {"id": 2, "entry_number": "2", "date_filed": "2026-01-03", "description": "Motion"},
                        ],
                    }
                )
            if "recap-documents/?docket_entry__docket=99999" in url:
                return _MockResponse(
                    {
                        "count": 2,
                        "next": None,
                        "results": [
                            {
                                "id": 9001,
                                "document_number": "1-1",
                                "description": "Complaint attachment",
                                "date_filed": "2026-01-02",
                                "plain_text": "Plaintiff must do something.",
                                "document_type": "complaint",
                            }
                        ],
                    }
                )
            return _MockResponse({"count": 0, "next": None, "results": []})
        return super().get(url, headers=headers, timeout=timeout)


class _MockListingThrottleRequests(_MockRequests):
    def get(self, url: str, headers=None, timeout: int = 30):  # noqa: ANN001
        if "dockets/?page=" in url:
            return _MockResponse({"detail": "Request was throttled. Expected available in 2515 seconds."}, status_code=429)
        return super().get(url, headers=headers, timeout=timeout)


def test_fetch_courtlistener_docket_normalizes_docket_and_recap_documents() -> None:
    payload = fetch_courtlistener_docket("12345", requests_module=_MockRequests())

    assert payload["source_type"] == "courtlistener"
    assert payload["docket_id"] == "12345"
    assert payload["case_name"] == "Doe v. Acme Housing"
    assert payload["court"] == "ord"
    assert len(payload["documents"]) == 3
    assert payload["documents"][0]["title"] == "CourtListener docket summary"
    assert payload["documents"][1]["document_type"] == "courtlistener_docket_entry"
    assert payload["documents"][2]["title"] == "Declaration of Jane Doe"
    assert "penalty of perjury" in payload["documents"][2]["text"]
    assert payload["documents"][2]["metadata"]["text_extraction"]["source"] == "courtlistener_plain_text"
    assert payload["documents"][1]["metadata"]["text_extraction"]["source"] == "courtlistener_entry_metadata"
    assert payload["plaintiff_docket"][0]["title"] == "Jane Doe"
    assert payload["defendant_docket"][0]["title"] == "Acme Housing"


def test_fetch_courtlistener_docket_prefers_court_id_over_court_url(tmp_path: Path) -> None:
    fetch_cache = SharedFetchCache(cache_dir=str(tmp_path / "courtlistener_cache"), enable_ipfs_mirroring=False)
    payload = fetch_courtlistener_docket(
        "12345",
        requests_module=_MockCourtUrlRequests(),
        shared_fetch_cache=fetch_cache,
    )

    assert payload["court"] == "ord"
    assert payload["metadata"]["court_id"] == "ord"
    assert payload["metadata"]["docket_number"] == "3:26-cv-00001"
    assert payload["metadata"]["pacer_case_id"] == "123456"


def test_fetch_courtlistener_docket_accepts_full_url_identifier() -> None:
    payload = fetch_courtlistener_docket(
        "https://www.courtlistener.com/api/rest/v3/dockets/12345/",
        requests_module=_MockRequests(),
        include_recap_documents=False,
    )

    assert payload["docket_id"] == "12345"
    assert len(payload["documents"]) == 2


def test_fetch_courtlistener_docket_attempts_pdf_text_backfill(monkeypatch) -> None:
    requests_module = _MockRequestsNoPlainText()

    def _fake_extract_text(_: bytes) -> tuple[str, str]:
        return ("Extracted from PDF fallback text", "pdf_text")

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion._extract_text_from_pdf_bytes",
        _fake_extract_text,
    )

    payload = fetch_courtlistener_docket("12345", requests_module=requests_module)

    recap_document = payload["documents"][2]
    assert recap_document["text"] == "Extracted from PDF fallback text"
    assert recap_document["metadata"]["text_extraction"]["source"] == "pdf_text"


def test_fetch_courtlistener_docket_can_attach_rendered_page_summary(monkeypatch) -> None:
    def _fake_rendered_summary(url: str) -> Dict[str, Any]:
        return {
            "url": url,
            "row_count": 2,
            "rows": [
                {
                    "document_number": "1",
                    "date_filed": "Apr 11, 2026",
                    "kind": "Main Document",
                    "title": "Voluntary petition chapter 7 (attorney filer)",
                    "pacer_available": True,
                }
            ],
            "contains_pacer_purchase_links": True,
            "body_text_preview": "Document Number",
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion._fetch_rendered_courtlistener_docket_summary",
        _fake_rendered_summary,
    )

    payload = fetch_courtlistener_docket(
        "12345",
        requests_module=_MockRequests(),
        include_recap_documents=False,
        enable_rendered_page_enrichment=True,
    )

    rendered = payload["metadata"]["rendered_docket_page"]
    assert rendered["row_count"] == 2
    assert rendered["contains_pacer_purchase_links"] is True
    assert rendered["rows"][0]["document_number"] == "1"
    rendered_docs = [item for item in payload["documents"] if item.get("document_type") == "courtlistener_rendered_docket_row"]
    assert len(rendered_docs) == 1
    assert rendered_docs[0]["document_number"] == "1"
    assert rendered_docs[0]["metadata"]["acquisition_candidates"][0]["pacer_available"] is True


def test_fetch_courtlistener_docket_reuses_shared_fetch_cache(monkeypatch, tmp_path: Path) -> None:
    requests_module = _MockRequestsNoPlainText()
    fetch_cache = SharedFetchCache(cache_dir=str(tmp_path / "courtlistener_cache"), enable_ipfs_mirroring=False)

    def _fake_extract_text(_: bytes) -> tuple[str, str]:
        return ("Extracted from PDF fallback text", "pdf_text")

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion._extract_text_from_pdf_bytes",
        _fake_extract_text,
    )

    first_payload = fetch_courtlistener_docket(
        "12345",
        requests_module=requests_module,
        shared_fetch_cache=fetch_cache,
    )
    first_call_count = len(requests_module.calls)

    second_payload = fetch_courtlistener_docket(
        "12345",
        requests_module=requests_module,
        shared_fetch_cache=fetch_cache,
    )

    assert len(requests_module.calls) == first_call_count
    assert first_payload["documents"][2]["text"] == second_payload["documents"][2]["text"]
    assert second_payload["documents"][2]["metadata"]["text_extraction"]["source"] == "pdf_text"


def test_fetch_random_courtlistener_docket_selects_from_sampled_candidates() -> None:
    payload = fetch_random_courtlistener_docket(
        seed=1,
        sample_pages=2,
        page_size=2,
        requests_module=_MockRandomRequests(),
        include_recap_documents=False,
        include_document_text=False,
        minimum_entry_count=1,
        minimum_downloaded_document_count=2,
        minimum_text_document_count=0,
    )

    assert payload["docket_id"] == "99999"
    assert payload["source_type"] == "courtlistener"
    assert len(payload["documents"]) >= 2


def test_resolve_courtlistener_api_token_reads_shared_secrets_file(monkeypatch, tmp_path: Path) -> None:
    secrets_dir = tmp_path / ".config" / "ipfs_datasets_py"
    secrets_dir.mkdir(parents=True)
    secrets_path = secrets_dir / "secrets.json"
    secrets_path.write_text('{"COURTLISTENER_API_TOKEN": "token-from-shared-secrets"}', encoding="utf-8")

    monkeypatch.delenv("COURTLISTENER_API_TOKEN", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_SECRETS_FILE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    from ipfs_datasets_py.processors.legal_data.courtlistener_ingestion import resolve_courtlistener_api_token

    assert resolve_courtlistener_api_token() == "token-from-shared-secrets"


def test_resolve_pacer_credentials_read_shared_secrets_file(monkeypatch, tmp_path: Path) -> None:
    secrets_dir = tmp_path / ".config" / "ipfs_datasets_py"
    secrets_dir.mkdir(parents=True)
    secrets_path = secrets_dir / "secrets.json"
    secrets_path.write_text(
        '{"PACER_USERNAME": "pacer-user", "PACER_PASSWORD": "pacer-pass"}',
        encoding="utf-8",
    )

    monkeypatch.delenv("PACER_USERNAME", raising=False)
    monkeypatch.delenv("PACER_PASSWORD", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_SECRETS_FILE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert resolve_pacer_username() == "pacer-user"
    assert resolve_pacer_password() == "pacer-pass"


def test_build_courtlistener_recap_fetch_payload_prefers_docket_request_for_pacer_gate() -> None:
    payload = build_courtlistener_recap_fetch_payload(
        queue_row={
            "queue_id": "q1",
            "acquisition_kind": "pacer_gate",
            "document_number": "5",
        },
        pacer_username="pacer-user",
        pacer_password="pacer-pass",
        court="akb",
        docket="73179548",
        docket_number="3-26-bk-90001",
    )

    assert payload["request_type"] == COURTLISTENER_RECAP_FETCH_REQUEST_TYPES["html_docket"]
    assert payload["court"] == "akb"
    assert payload["docket"] == 73179548
    assert payload["docket_number"] == "3-26-bk-90001"
    assert payload["de_number_start"] == 5
    assert payload["de_number_end"] == 5


def test_build_courtlistener_recap_fetch_payload_normalizes_court_url_reference() -> None:
    payload = build_courtlistener_recap_fetch_payload(
        queue_row={"acquisition_kind": "pacer_gate"},
        pacer_username="pacer-user",
        pacer_password="pacer-pass",
        court="https://www.courtlistener.com/api/rest/v4/courts/akb/",
        docket="73179548",
        docket_number="3-26-bk-90001",
    )

    assert payload["court"] == "akb"


def test_submit_and_get_courtlistener_recap_fetch_request() -> None:
    requests_module = _MockRecapFetchRequests()

    submission = submit_courtlistener_recap_fetch_request(
        queue_row={
            "queue_id": "q1",
            "acquisition_kind": "pacer_gate",
            "document_number": "2",
        },
        api_token="courtlistener-token",
        pacer_username="pacer-user",
        pacer_password="pacer-pass",
        court="akb",
        docket="73179548",
        docket_number="3-26-bk-90001",
        requests_module=requests_module,
    )

    assert submission["status"] == "submitted"
    assert submission["request_id"] == 321
    assert submission["payload_preview"]["pacer_password"] == "***"
    assert requests_module.posts[0]["headers"]["Authorization"] == "Token courtlistener-token"
    assert requests_module.posts[0]["json"]["request_type"] == 1

    status = get_courtlistener_recap_fetch_request(
        321,
        api_token="courtlistener-token",
        requests_module=requests_module,
    )
    assert status["status"] == 2
    assert requests_module.gets == ["https://www.courtlistener.com/api/rest/v4/recap-fetch/321/"]


def test_submit_packaged_docket_recap_fetch_requests_dedupes_docket_jobs(monkeypatch) -> None:
    class _FakePackager:
        def load_minimal_dataset_view(self, manifest_path):  # noqa: ANN001
            return {
                "docket_id": "73179548",
                "case_name": "Miranda Kay Crowder",
                "court": "akb",
                "documents": [
                    {
                        "document_type": "courtlistener_docket_summary",
                        "document_number": "3-26-bk-90001",
                        "metadata": {
                            "raw": {
                                "id": 73179548,
                                "court": "akb",
                                "court_name": "Bankr. D. Alaska",
                                "docket_number": "3-26-bk-90001",
                            }
                        },
                    }
                ],
                "acquisition_queue": [
                    {
                        "queue_id": "q1",
                        "filing_id": "f1",
                        "title": "Voluntary petition",
                        "acquisition_kind": "pacer_gate",
                        "ready_for_fetch": True,
                        "document_number": "1",
                    },
                    {
                        "queue_id": "q2",
                        "filing_id": "f2",
                        "title": "Certificate of credit counseling",
                        "acquisition_kind": "pacer_gate",
                        "ready_for_fetch": True,
                        "document_number": "2",
                    },
                ],
                "package_manifest": {"source_url": "https://www.courtlistener.com/docket/73179548/"},
            }

    requests_module = _MockRecapFetchRequests()
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.docket_packaging.DocketDatasetPackager",
        _FakePackager,
    )

    result = submit_packaged_docket_recap_fetch_requests(
        "/tmp/fake_manifest.json",
        api_token="courtlistener-token",
        pacer_username="pacer-user",
        pacer_password="pacer-pass",
        requests_module=requests_module,
    )

    assert result["status"] == "submitted"
    assert result["submission_count"] == 1
    assert result["context"]["docket_number"] == "3-26-bk-90001"
    posted = requests_module.posts[0]["json"]
    assert posted["court"] == "akb"
    assert posted["docket"] == 73179548
    assert posted["docket_number"] == "3-26-bk-90001"


def test_build_packaged_docket_recap_fetch_preflight_summarizes_readiness(monkeypatch) -> None:
    class _FakePackager:
        def load_minimal_dataset_view(self, manifest_path):  # noqa: ANN001
            return {
                "docket_id": "73179548",
                "case_name": "Miranda Kay Crowder",
                "court": "https://www.courtlistener.com/api/rest/v4/courts/akb/",
                "documents": [
                    {
                        "document_type": "courtlistener_docket_summary",
                        "document_number": "3-26-bk-90001",
                        "metadata": {
                            "raw": {
                                "id": 73179548,
                                "court": "https://www.courtlistener.com/api/rest/v4/courts/akb/",
                                "court_name": "Bankr. D. Alaska",
                                "docket_number": "3-26-bk-90001",
                            }
                        },
                    }
                ],
                "acquisition_queue": [
                    {
                        "queue_id": "q1",
                        "title": "Voluntary petition",
                        "document_number": "1",
                        "acquisition_kind": "pacer_gate",
                        "ready_for_fetch": True,
                    }
                ],
                "package_manifest": {"source_url": "https://www.courtlistener.com/docket/73179548/"},
            }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.docket_packaging.DocketDatasetPackager",
        _FakePackager,
    )

    preflight = build_packaged_docket_recap_fetch_preflight(
        "/tmp/fake_manifest.json",
        api_token="courtlistener-token",
        pacer_username="pacer-user",
        pacer_password="pacer-pass",
    )

    assert preflight["status"] == "ready"
    assert preflight["checks"]["has_courtlistener_api_token"] is True
    assert preflight["checks"]["has_pacer_username"] is True
    assert preflight["checks"]["has_pacer_password"] is True
    assert preflight["checks"]["has_pacer_gate_rows"] is True
    assert preflight["context"]["court"] == "akb"
    assert preflight["context"]["docket_number"] == "3-26-bk-90001"
    assert preflight["payload_preview"]["court"] == "akb"


def test_probe_courtlistener_document_acquisition_target_extracts_buy_on_pacer(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_data import courtlistener_ingestion as module

    async def _fake_probe(url: str) -> Dict[str, Any]:
        return {
            "status": "success",
            "url": url,
            "title": "Document page",
            "pacer_purchase_url": "https://ecf.txnb.uscourts.gov/doc1/176051998030?caseid=541209",
            "download_url": "",
            "matching_links": [
                {
                    "text": "Buy on PACER",
                    "href": "https://ecf.txnb.uscourts.gov/doc1/176051998030?caseid=541209",
                }
            ],
        }

    monkeypatch.setattr(module, "_probe_courtlistener_document_acquisition_target_async", _fake_probe)

    result = probe_courtlistener_document_acquisition_target(
        "https://www.courtlistener.com/docket/73179548/1/miranda-kay-crowder/"
    )

    assert result["pacer_purchase_url"] == "https://ecf.txnb.uscourts.gov/doc1/176051998030?caseid=541209"
    assert result["matching_links"][0]["text"] == "Buy on PACER"


def test_build_packaged_docket_acquisition_plan_prefers_browser_probe_targets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_data import courtlistener_ingestion as module
    from ipfs_datasets_py.processors.legal_data.docket_packaging import DocketDatasetPackager

    manifest_path = tmp_path / "bundle_manifest.json"

    def _fake_load(self, path):  # noqa: ANN001
        assert str(path) == str(manifest_path)
        return {
            "acquisition_queue": [
                {
                    "queue_id": "acquisition_2",
                    "filing_id": "475536954_filing",
                    "document_id": "475536954",
                    "document_number": "1",
                    "title": "Voluntary petition chapter 7 (attorney filer)",
                    "acquisition_url": "https://www.courtlistener.com/docket/73179548/miranda-kay-crowder/",
                    "source_url": "https://www.courtlistener.com/docket/73179548/1/miranda-kay-crowder/",
                    "acquisition_kind": "pacer_gate",
                    "extractor_plan": "browser_assist_then_pdf_direct_then_ocr",
                    "pacer_available": True,
                    "text_available": False,
                    "ready_for_fetch": True,
                    "notes_json": "{\"acquisition_candidates\": [{\"document_number\": \"1\"}]}",
                }
            ]
        }

    def _fake_probe(url: str) -> Dict[str, Any]:
        assert url.endswith("/1/miranda-kay-crowder/")
        return {
            "status": "success",
            "url": url,
            "title": "Document page",
            "pacer_purchase_url": "https://ecf.txnb.uscourts.gov/doc1/176051998030?caseid=541209",
            "download_url": "",
            "matching_links": [
                {
                    "text": "Buy on PACER",
                    "href": "https://ecf.txnb.uscourts.gov/doc1/176051998030?caseid=541209",
                }
            ],
        }

    monkeypatch.setattr(DocketDatasetPackager, "load_minimal_dataset_view", _fake_load)
    monkeypatch.setattr(module, "probe_courtlistener_document_acquisition_target", _fake_probe)

    plan = build_packaged_docket_acquisition_plan(
        manifest_path,
        include_browser_probe=True,
    )

    assert plan["row_count"] == 1
    assert plan["rows"][0]["direct_target_url"] == "https://ecf.txnb.uscourts.gov/doc1/176051998030?caseid=541209"
    assert plan["rows"][0]["target_source"] == "courtlistener_document_probe"


def test_execute_packaged_docket_acquisition_plan_classifies_auth_required(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_data import courtlistener_ingestion as module

    manifest_path = tmp_path / "bundle_manifest.json"

    def _fake_plan(*args, **kwargs):  # noqa: ANN001
        return {
            "status": "success",
            "manifest_path": str(manifest_path),
            "row_count": 1,
            "ready_row_count": 1,
            "probe_enabled": True,
            "rows": [
                {
                    "queue_id": "acquisition_2",
                    "document_number": "1",
                    "title": "Voluntary petition",
                    "direct_target_url": "https://ecf.txnb.uscourts.gov/doc1/176051998030?caseid=541209",
                    "ready_for_fetch": True,
                }
            ],
        }

    class _MockAuthRequiredResponse:
        status_code = 200
        url = "https://pacer.login.uscourts.gov/csologin/login.jsf"
        headers = {"Content-Type": "text/html; charset=utf-8"}
        content = b"<html>PACER Login username password</html>"
        text = "<html>PACER Login username password</html>"

    class _MockRequests:
        def get(self, url, headers=None, timeout=30, allow_redirects=True):  # noqa: ANN001
            return _MockAuthRequiredResponse()

    monkeypatch.setattr(module, "build_packaged_docket_acquisition_plan", _fake_plan)

    result = execute_packaged_docket_acquisition_plan(
        manifest_path,
        requests_module=_MockRequests(),
    )

    assert result["row_count"] == 1
    assert result["auth_required_count"] == 1
    assert result["rows"][0]["fetch_result"]["status"] == "authentication_required"


def test_fetch_pacer_document_with_browser_classifies_account_update(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_data import courtlistener_ingestion as module

    async def _fake_fetch(*args, **kwargs):  # noqa: ANN001
        return {
            "status": "account_update_required",
            "target_url": "https://ecf.txnb.uscourts.gov/doc1/176051998030?caseid=541209",
            "final_url": "https://pacer.login.uscourts.gov/csologin/login.jsf",
            "title": "PACER: Login",
            "body_preview": "Account update required! current account access has been restricted.",
        }

    monkeypatch.setattr(module, "_fetch_pacer_document_with_browser_async", _fake_fetch)

    result = fetch_pacer_document_with_browser(
        "https://ecf.txnb.uscourts.gov/doc1/176051998030?caseid=541209",
        pacer_username="pacer-user",
        pacer_password="pacer-pass",
    )

    assert result["status"] == "account_update_required"


def test_fetch_pacer_document_with_browser_classifies_mfa_required(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_data import courtlistener_ingestion as module

    async def _fake_fetch(*args, **kwargs):  # noqa: ANN001
        return {
            "status": "mfa_required",
            "target_url": "https://ecf.txnb.uscourts.gov/doc1/176051998030?caseid=541209",
            "final_url": "https://pacer.login.uscourts.gov/csologin/login.jsf",
            "title": "PACER: Login",
            "body_preview": "Enter one-time passcode",
        }

    monkeypatch.setattr(module, "_fetch_pacer_document_with_browser_async", _fake_fetch)

    result = fetch_pacer_document_with_browser(
        "https://ecf.txnb.uscourts.gov/doc1/176051998030?caseid=541209",
        pacer_username="pacer-user",
        pacer_password="pacer-pass",
    )

    assert result["status"] == "mfa_required"


def test_extract_courtlistener_public_filing_pdf_texts_uses_probe_links(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_data import courtlistener_ingestion as module

    def _fake_probe(url: str) -> Dict[str, Any]:
        return {
            "status": "success",
            "url": url,
            "title": "Filing page",
            "pdf_links": [
                {"text": "Download PDF", "href": "https://storage.courtlistener.com/recap/example.1.0.pdf"},
                {"text": "Download PDF", "href": "https://storage.courtlistener.com/recap/example.1.1.pdf"},
            ],
        }

    def _fake_fetch(url: str, **kwargs):  # noqa: ANN001
        return {
            "url": url,
            "status_code": 200,
            "byte_count": 1234,
            "text_length": 500,
            "extraction_method": "pdf_ocr",
            "text_preview": "Sample text",
        }

    monkeypatch.setattr(module, "probe_courtlistener_public_filing_pdfs", _fake_probe)
    monkeypatch.setattr(module, "_fetch_public_pdf_text", _fake_fetch)

    result = extract_courtlistener_public_filing_pdf_texts(
        "https://www.courtlistener.com/docket/67658002/american-alliance-for-equal-rights-v-fearless-fund-management-llc-filing/",
    )

    assert result["status"] == "success"
    assert result["pdf_count"] == 2
    assert result["results"][0]["extraction_method"] == "pdf_ocr"


def test_extract_courtlistener_public_filing_pdf_texts_dedupes_duplicate_probe_links(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_data import courtlistener_ingestion as module

    def _fake_probe(url: str) -> Dict[str, Any]:
        return {
            "status": "success",
            "url": url,
            "title": "Example",
            "pdf_links": [
                {"text": "Download PDF", "href": "https://storage.courtlistener.com/recap/example.1.0.pdf"},
                {"text": "From CourtListener", "href": "https://storage.courtlistener.com/recap/example.1.0.pdf"},
                {"text": "Download PDF", "href": "https://storage.courtlistener.com/recap/example.1.1.pdf"},
            ],
        }

    calls: list[str] = []

    def _fake_fetch(url: str, **kwargs):  # noqa: ANN001
        calls.append(url)
        return {
            "url": url,
            "status_code": 200,
            "byte_count": 1234,
            "text_length": 500,
            "extraction_method": "pdf_ocr",
            "text_preview": "Sample text",
        }

    monkeypatch.setattr(module, "probe_courtlistener_public_filing_pdfs", _fake_probe)
    monkeypatch.setattr(module, "_fetch_public_pdf_text", _fake_fetch)

    result = extract_courtlistener_public_filing_pdf_texts("https://www.courtlistener.com/docket/67658002/example/")

    assert result["pdf_count"] == 2
    assert calls == [
        "https://storage.courtlistener.com/recap/example.1.0.pdf",
        "https://storage.courtlistener.com/recap/example.1.1.pdf",
    ]


def test_attach_public_courtlistener_filing_pdfs_to_docket_appends_text_documents(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_data import courtlistener_ingestion as module

    def _fake_extract(url: str, **kwargs):  # noqa: ANN001
        return {
            "status": "success",
            "filing_url": url,
            "pdf_count": 1,
            "probe": {"title": "Example Filing"},
            "results": [
                {
                    "url": "https://storage.courtlistener.com/recap/example.1.0.pdf",
                    "status_code": 200,
                    "byte_count": 1234,
                    "text_length": 500,
                    "extraction_method": "pdf_ocr",
                    "text": "Substantive extracted filing text.",
                    "text_preview": "Substantive extracted filing text.",
                }
            ],
        }

    monkeypatch.setattr(module, "extract_courtlistener_public_filing_pdf_texts", _fake_extract)

    enriched = attach_public_courtlistener_filing_pdfs_to_docket(
        {
            "docket_id": "67658002",
            "case_name": "Example",
            "documents": [],
        },
        "https://www.courtlistener.com/docket/67658002/example-filing/",
    )

    assert len(enriched["documents"]) == 1
    assert enriched["documents"][0]["document_type"] == "courtlistener_public_filing_pdf"
    assert enriched["documents"][0]["text"] == "Substantive extracted filing text."
    assert enriched["documents"][0]["document_number"] == "0"
    assert enriched["documents"][0]["text_extraction"]["source"] == "courtlistener_public_filing_pdf"
    assert enriched["documents"][0]["text_extraction"]["method"] == "pdf_ocr"
    assert enriched["documents"][0]["metadata"]["text_extraction"]["source"] == "courtlistener_public_filing_pdf"


def test_attach_available_courtlistener_recap_evidence_to_docket_appends_available_public_recap_documents(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_data import courtlistener_ingestion as module

    def _fake_fetch(url: str, **kwargs):  # noqa: ANN001
        return {
            "url": url,
            "text": "Recovered PDF text from public RECAP evidence.",
            "text_length": 45,
            "extraction_method": "pdf_ocr",
            "byte_count": 321,
        }

    monkeypatch.setattr(module, "_fetch_public_pdf_text", _fake_fetch)

    enriched = attach_available_courtlistener_recap_evidence_to_docket(
        {
            "docket_id": "67658002",
            "case_name": "Example",
            "documents": [
                {
                    "id": "entry_185",
                    "title": "USCA Clerk's Entry",
                    "document_number": "185",
                    "metadata": {
                        "raw": {
                            "recap_documents": [
                                {
                                    "id": 449096434,
                                    "document_number": "185",
                                    "is_available": True,
                                    "plain_text": "",
                                    "filepath_local": "recap/gov.uscourts.gand.318833/gov.uscourts.gand.318833.185.0_2.pdf",
                                    "filepath_ia": "",
                                    "page_count": 2,
                                }
                            ]
                        }
                    },
                }
            ],
        }
    )

    assert len(enriched["documents"]) == 2
    attached = enriched["documents"][1]
    assert attached["document_type"] == "courtlistener_public_recap_document"
    assert attached["document_number"] == "185"
    assert attached["text"] == "Recovered PDF text from public RECAP evidence."
    assert attached["text_extraction"]["source"] == "courtlistener_public_recap_document"
    assert attached["metadata"]["public_recap_document"]["recap_document_id"] == "449096434"
    assert enriched["metadata"]["public_recap_evidence_summary"]["attached_recap_document_count"] == 1


def test_fetch_random_courtlistener_docket_surfaces_listing_throttle() -> None:
    try:
        fetch_random_courtlistener_docket(
            seed=1,
            sample_pages=2,
            page_size=2,
            requests_module=_MockThrottleRequests(),
            include_recap_documents=False,
            include_document_text=False,
            request_timeout_seconds=1.0,
        )
    except CourtListenerIngestionError as exc:
        message = str(exc)
        assert "throttled" in message.lower()
        assert "429" in message or "throttled" in message.lower()
    else:  # pragma: no cover
        raise AssertionError("Expected throttled CourtListener listing to raise CourtListenerIngestionError")


def test_fetch_random_courtlistener_docket_uses_fallback_ids_when_listing_is_throttled(tmp_path: Path) -> None:
    fetch_cache = SharedFetchCache(cache_dir=str(tmp_path / "courtlistener_cache"), enable_ipfs_mirroring=False)

    payload = fetch_random_courtlistener_docket(
        seed=1,
        sample_pages=2,
        page_size=2,
        requests_module=_MockListingThrottleRequests(),
        include_recap_documents=False,
        include_document_text=False,
        minimum_entry_count=0,
        minimum_downloaded_document_count=2,
        minimum_text_document_count=0,
        shared_fetch_cache=fetch_cache,
        fallback_docket_ids=["12345"],
        strict_content_requirements=False,
    )

    assert payload["docket_id"] == "12345"
    assert payload["metadata"]["courtlistener_sampling_stage_timings"]["cached_candidate_count"] == 1.0


def test_normalize_recap_document_marks_description_only_text_as_metadata_only() -> None:
    payload = fetch_courtlistener_docket(
        "99999",
        requests_module=_MockRandomRequests(),
        include_document_text=False,
    )

    recap_document = next(item for item in payload["documents"] if str(item.get("id")) == "9001")
    assert recap_document["title"] == "Complaint attachment"
    assert recap_document["text"] == ""
    assert recap_document["metadata"]["text_extraction"]["source"] == "courtlistener_metadata_only"
    assert "metadata_text_preview" in recap_document["metadata"]["text_extraction"]


def test_find_rich_courtlistener_docket_returns_success(monkeypatch) -> None:
    attempts = []

    def _fake_random_fetch(**kwargs):  # noqa: ANN001
        attempts.append(int(kwargs.get("seed") or 0))
        return {
            "docket_id": f"docket-{kwargs.get('seed')}",
            "case_name": "Candidate",
            "documents": [{"id": "doc1", "title": "Doc", "text": "text"}],
        }

    def _fake_eval(payload):  # noqa: ANN001
        docket_id = str(payload.get("docket_id"))
        if docket_id.endswith("0"):
            return {
                "temporal_formula_count": 1,
                "proof_count": 0,
                "document_count": 1,
                "text_document_count": 1,
                "substantive_text_document_count": 1,
                "citation_count": 0,
            }
        return {
            "temporal_formula_count": 7,
            "proof_count": 9,
            "document_count": 8,
            "text_document_count": 6,
            "substantive_text_document_count": 6,
            "citation_count": 0,
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion.fetch_random_courtlistener_docket",
        _fake_random_fetch,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion._evaluate_docket_formal_richness",
        _fake_eval,
    )

    result = find_rich_courtlistener_docket(seed=0, attempts=3)

    assert result["status"] == "success"
    assert result["diagnostics"]["temporal_formula_count"] == 7
    assert attempts[:2] == [0, 1]


def test_find_rich_courtlistener_docket_can_require_citations(monkeypatch) -> None:
    attempts = []

    def _fake_random_fetch(**kwargs):  # noqa: ANN001
        attempts.append(int(kwargs.get("seed") or 0))
        return {
            "docket_id": f"docket-{kwargs.get('seed')}",
            "case_name": "Candidate",
            "documents": [{"id": "doc1", "title": "Doc", "text": "text"}],
        }

    def _fake_eval(payload):  # noqa: ANN001
        docket_id = str(payload.get("docket_id"))
        if docket_id.endswith("0"):
            return {
                "citation_count": 0,
                "substantive_text_document_count": 1,
                "temporal_formula_count": 7,
                "proof_count": 9,
                "deontic_statement_count": 1,
            }
        return {
            "citation_count": 2,
            "substantive_text_document_count": 2,
            "temporal_formula_count": 7,
            "proof_count": 9,
            "deontic_statement_count": 1,
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion.fetch_random_courtlistener_docket",
        _fake_random_fetch,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion._evaluate_docket_formal_richness",
        _fake_eval,
    )

    result = find_rich_courtlistener_docket(
        seed=0,
        attempts=3,
        minimum_citation_count=1,
        minimum_substantive_text_document_count=1,
    )

    assert result["status"] == "success"
    assert result["diagnostics"]["citation_count"] == 2
    assert attempts[:2] == [0, 1]


def test_sample_random_courtlistener_dockets_batch_collects_parallel_results(monkeypatch) -> None:
    def _fake_random_fetch(**kwargs):  # noqa: ANN001
        seed = int(kwargs.get("seed") or 0)
        if seed == 2:
            raise CourtListenerIngestionError("sample failed")
        return {
            "docket_id": f"docket-{seed}",
            "case_name": f"Case {seed}",
            "court": "rnd",
            "documents": [{"id": "doc1", "title": "Doc", "text": "text"}],
        }

    def _fake_eval(payload):  # noqa: ANN001
        docket_id = str(payload.get("docket_id") or "")
        seed = int(docket_id.rsplit("-", 1)[-1])
        return {
            "document_count": seed + 1,
            "substantive_text_document_count": 1 if seed >= 1 else 0,
            "citation_count": 2 if seed == 3 else 0,
            "temporal_formula_count": seed,
            "proof_count": seed,
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion.fetch_random_courtlistener_docket",
        _fake_random_fetch,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion._evaluate_docket_formal_richness",
        _fake_eval,
    )

    result = sample_random_courtlistener_dockets_batch(base_seed=0, batch_size=4, max_workers=2)

    assert result["status"] == "success"
    assert result["batch_size"] == 4
    assert result["success_count"] == 3
    assert result["failure_count"] == 1
    assert result["citation_bearing_count"] == 1
    assert result["substantive_text_count"] == 2
    assert result["selected"]["docket"]["docket_id"] == "docket-3"
    failed = next(item for item in result["samples"] if item["status"] == "failed")
    assert failed["seed"] == 2


def test_sample_random_courtlistener_dockets_batch_returns_partial_results_on_timeout(monkeypatch) -> None:
    def _fake_random_fetch(**kwargs):  # noqa: ANN001
        seed = int(kwargs.get("seed") or 0)
        if seed == 1:
            time.sleep(1.2)
        return {
            "docket_id": f"docket-{seed}",
            "case_name": f"Case {seed}",
            "court": "rnd",
            "documents": [{"id": "doc1", "title": "Doc", "text": "text"}],
        }

    def _fake_eval(payload):  # noqa: ANN001
        return {
            "document_count": 1,
            "substantive_text_document_count": 1,
            "citation_count": 0,
            "temporal_formula_count": 0,
            "proof_count": 0,
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion.fetch_random_courtlistener_docket",
        _fake_random_fetch,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion._evaluate_docket_formal_richness",
        _fake_eval,
    )

    result = sample_random_courtlistener_dockets_batch(
        base_seed=0,
        batch_size=2,
        max_workers=2,
        sample_timeout_seconds=1.0,
    )

    assert result["status"] == "success"
    assert result["success_count"] == 1
    assert result["failure_count"] == 1
    assert result["timed_out_count"] == 1
    timed_out = next(item for item in result["samples"] if item["status"] == "failed")
    assert timed_out["seed"] == 1
    assert "sample_timeout_after_" in str(timed_out["error"])


def test_sample_random_courtlistener_dockets_batch_can_allow_partial_fallback(monkeypatch) -> None:
    def _fake_random_fetch(**kwargs):  # noqa: ANN001
        return {
            "docket_id": "docket-partial",
            "case_name": "Partial Case",
            "court": "rnd",
            "documents": [{"id": "doc1", "title": "Summary", "text": ""}],
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion.fetch_random_courtlistener_docket",
        _fake_random_fetch,
    )

    result = sample_random_courtlistener_dockets_batch(
        base_seed=0,
        batch_size=1,
        max_workers=1,
        use_fast_diagnostics=True,
        allow_partial_fallback=True,
    )

    assert result["status"] == "success"
    assert result["success_count"] == 1
    assert result["selected"]["docket"]["docket_id"] == "docket-partial"


def test_find_rich_courtlistener_docket_can_allow_partial_fallback(monkeypatch) -> None:
    def _fake_random_fetch(**kwargs):  # noqa: ANN001
        return {
            "docket_id": "docket-partial",
            "case_name": "Partial Case",
            "documents": [{"id": "doc1", "title": "Summary", "text": ""}],
        }

    def _fake_eval(payload):  # noqa: ANN001
        return {
            "citation_count": 0,
            "substantive_text_document_count": 0,
            "temporal_formula_count": 0,
            "proof_count": 0,
            "deontic_statement_count": 0,
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion.fetch_random_courtlistener_docket",
        _fake_random_fetch,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion._evaluate_docket_formal_richness",
        _fake_eval,
    )

    result = find_rich_courtlistener_docket(
        seed=0,
        attempts=1,
        minimum_citation_count=0,
        minimum_substantive_text_document_count=0,
        minimum_temporal_formula_count=0,
        minimum_proof_count=0,
        allow_partial_fallback=True,
    )

    assert result["status"] == "success"
    assert result["docket"]["docket_id"] == "docket-partial"


def test_find_rich_courtlistener_docket_partial_fallback_prefilters_before_formal(monkeypatch) -> None:
    seen_seeds = []
    formal_calls = []

    def _fake_random_fetch(**kwargs):  # noqa: ANN001
        seed = int(kwargs.get("seed") or 0)
        seen_seeds.append(seed)
        if seed == 0:
            return {
                "docket_id": "docket-thin",
                "case_name": "Thin",
                "documents": [{"id": "doc1", "title": "Summary", "text": ""}],
            }
        return {
            "docket_id": "docket-richer",
            "case_name": "Richer",
            "documents": [{"id": "doc2", "title": "Body", "text": "A much longer body of substantive text." * 10}],
        }

    def _fake_fast_eval(payload):  # noqa: ANN001
        docket_id = str(payload.get("docket_id") or "")
        if docket_id == "docket-thin":
            return {"document_count": 1, "substantive_text_document_count": 0}
        return {"document_count": 1, "substantive_text_document_count": 1}

    def _fake_formal_eval(payload):  # noqa: ANN001
        formal_calls.append(str(payload.get("docket_id") or ""))
        return {
            "citation_count": 0,
            "substantive_text_document_count": 1,
            "temporal_formula_count": 0,
            "proof_count": 0,
            "deontic_statement_count": 0,
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion.fetch_random_courtlistener_docket",
        _fake_random_fetch,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion._evaluate_docket_fast_richness",
        _fake_fast_eval,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion._evaluate_docket_formal_richness",
        _fake_formal_eval,
    )

    result = find_rich_courtlistener_docket(
        seed=0,
        attempts=2,
        minimum_citation_count=0,
        minimum_substantive_text_document_count=0,
        minimum_temporal_formula_count=0,
        minimum_proof_count=0,
        allow_partial_fallback=True,
    )

    assert seen_seeds == [0, 1]
    assert formal_calls == ["docket-richer"]
    assert result["selection_mode"] == "fast_prefilter_partial_fallback"
    assert result["docket"]["docket_id"] == "docket-richer"


def test_find_rich_courtlistener_docket_can_use_fast_final_diagnostics(monkeypatch) -> None:
    formal_calls = []

    def _fake_random_fetch(**kwargs):  # noqa: ANN001
        return {
            "docket_id": "docket-fast",
            "case_name": "Fast",
            "documents": [{"id": "doc1", "title": "Body", "text": "Substantive body text." * 10}],
        }

    def _fake_fast_eval(payload):  # noqa: ANN001
        return {
            "docket_id": str(payload.get("docket_id") or ""),
            "document_count": 1,
            "substantive_text_document_count": 1,
            "citation_count": 0,
        }

    def _fake_formal_eval(payload):  # noqa: ANN001
        formal_calls.append(str(payload.get("docket_id") or ""))
        return {"citation_count": 99}

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion.fetch_random_courtlistener_docket",
        _fake_random_fetch,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion._evaluate_docket_fast_richness",
        _fake_fast_eval,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.courtlistener_ingestion._evaluate_docket_formal_richness",
        _fake_formal_eval,
    )

    result = find_rich_courtlistener_docket(
        seed=0,
        attempts=1,
        allow_partial_fallback=True,
        use_fast_final_diagnostics=True,
    )

    assert result["status"] == "best_effort"
    assert result["selection_mode"] == "fast_prefilter_fast_final"
    assert result["diagnostics"]["docket_id"] == "docket-fast"
    assert formal_calls == []
