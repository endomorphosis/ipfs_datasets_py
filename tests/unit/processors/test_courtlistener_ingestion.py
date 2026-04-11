from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ipfs_datasets_py.processors.legal_data import (
    fetch_courtlistener_docket,
    fetch_random_courtlistener_docket,
    find_rich_courtlistener_docket,
    sample_random_courtlistener_dockets_batch,
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
