"""Hermetic unit coverage for the LCR-078 live catalog builder."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data import legal_source_rights_policy as policy
from ipfs_datasets_py.processors.legal_data.legal_source_rights_policy import (
    ADMISSIBLE_CONTENT_SCOPES,
    CATALOG_PRODUCER,
    CATALOG_SCHEMA_VERSION,
    EXPECTED_FRONTIER_SIZE,
    LIVE_GOAL_ID,
    LIVE_TASK_ID,
    PROGRAM_ID,
    TARGET_DATASET_REPO_IDS,
    ContentScope,
    derive_expected_scope_frontier,
    format_utc_timestamp,
    require_live_source_evidence,
)


def _load_audit():
    path = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "ops"
        / "legal_data"
        / "audit_legal_source_rights.py"
    )
    spec = importlib.util.spec_from_file_location("lcr078_audit_live_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audit():
    return _load_audit()


def _fetch(audit, url: str, *, status: int, body: bytes, error: str | None = None):
    now = format_utc_timestamp(datetime.now(UTC) - timedelta(seconds=5))
    return audit.LiveFetchResult(
        fetch_url=url,
        status=status,
        body=body,
        request_bytes=audit._http_request_bytes(url),
        response_bytes=audit._http_response_bytes(status, body),
        observed_at=now,
        error=error,
    )


def _allowing_fetch(audit):
    def fetch(url: str):
        if url.endswith("/robots.txt"):
            return _fetch(audit, url, status=200, body=b"User-agent: *\nAllow: /\n")
        return _fetch(
            audit,
            url,
            status=200,
            body=b"<html><body>Official government source terms</body></html>",
        )

    return fetch


def test_fixture_builder_identity_is_unchanged(audit) -> None:
    payload = audit.build_fixture_catalog_payload()
    assert payload["task_id"] == "LCR-082"
    assert payload["goal_id"] == "LCR-G144"
    assert payload["evidence_mode"] == "fixture"
    assert payload["authorizing_for_publication"] is False
    assert payload["schema_version"] == CATALOG_SCHEMA_VERSION
    assert audit.main(["--fixture-only", "--check"]) == 0


def test_robots_url_and_parser_cover_missing_deny_and_delay(audit) -> None:
    assert (
        audit.robots_url_for("http://www.leg.state.fl.us/Statutes/")
        == "http://www.leg.state.fl.us/robots.txt"
    )
    assert audit.interpret_robots(
        b"",
        user_agent=audit.LIVE_USER_AGENT,
        source_url="https://example.gov/code",
        http_status=404,
        error=None,
    ) == ("allowed", None)
    assert audit.interpret_robots(
        b"User-agent: *\nDisallow: /\n",
        user_agent=audit.LIVE_USER_AGENT,
        source_url="https://example.gov/code",
        http_status=200,
        error=None,
    ) == ("denied", None)
    assert audit.interpret_robots(
        b"User-agent: *\nAllow: /\n",
        user_agent=audit.LIVE_USER_AGENT,
        source_url="https://www.oscn.net/applications/oscn/Index.asp",
        http_status=201,
        error=None,
    ) == ("allowed", None)
    assert audit.interpret_robots(
        b"User-agent: *\nAllow: /\nCrawl-delay: 10\n",
        user_agent=audit.LIVE_USER_AGENT,
        source_url="https://example.gov/code",
        http_status=200,
        error=None,
    ) == ("conditional", 10)
    assert audit.interpret_robots(
        b"User-agent: *\nDisallow: /\nCrawl-Delay: 10\n",
        user_agent=audit.LIVE_USER_AGENT,
        source_url="https://leginfo.legislature.ca.gov/faces/codes.xhtml",
        http_status=200,
        error=None,
    ) == ("denied", None)
    assert audit.interpret_robots(
        b"",
        user_agent=audit.LIVE_USER_AGENT,
        source_url="https://example.gov/code",
        http_status=403,
        error=None,
    ) == ("unavailable", None)
    assert audit.interpret_robots(
        b"<html><title>Hawaii State Legislature</title><h1>404 Page Not Found</h1></html>",
        user_agent=audit.LIVE_USER_AGENT,
        source_url="https://www.capitol.hawaii.gov/hrscurrent/",
        http_status=200,
        error=None,
    ) == ("allowed", None)
    assert audit.interpret_robots(
        b"<html><title>Just a moment...</title><div id='challenge-platform'></div></html>",
        user_agent=audit.LIVE_USER_AGENT,
        source_url="https://www.capitol.hawaii.gov/hrscurrent/",
        http_status=200,
        error=None,
    ) == ("unavailable", None)
    assert audit.interpret_robots(
        b"",
        user_agent=audit.LIVE_USER_AGENT,
        source_url="https://example.gov/code",
        http_status=0,
        error="URLError",
    ) == ("unavailable", None)


def test_live_builder_seals_exact_identity_and_frontier(audit) -> None:
    payload = audit.build_live_catalog_payload(fetch_url=_allowing_fetch(audit))
    assert payload["schema_version"] == CATALOG_SCHEMA_VERSION
    assert payload["producer"] == CATALOG_PRODUCER
    assert payload["program_id"] == PROGRAM_ID
    assert (payload["task_id"], payload["goal_id"], payload["evidence_mode"]) == (
        LIVE_TASK_ID,
        LIVE_GOAL_ID,
        "live",
    )
    assert payload["authorizing_for_publication"] is True
    assert payload["target_dataset_repo_ids"] == list(TARGET_DATASET_REPO_IDS)
    assert len(payload["records"]) == EXPECTED_FRONTIER_SIZE == 57
    assert len(payload["admitted_record_ids"]) == 52
    scopes = {record["content_scope"] for record in payload["records"]}
    assert scopes == {scope.value for scope in ContentScope}
    for record in payload["records"]:
        assert record["terms"]["task_id"] == LIVE_TASK_ID
        assert record["robots"]["evidence_mode"] == "live"
        assert record["card_label_is_not_authority"] is True
        in_scope = ContentScope(record["content_scope"]) in ADMISSIBLE_CONTENT_SCOPES
        if in_scope:
            assert record["rights_disposition"] == "allowed"
            assert record["record_id"] in payload["admitted_record_ids"]
        else:
            assert record["rights_disposition"] in {"prohibited", "quarantined"}
            assert record["record_id"] not in payload["admitted_record_ids"]


def test_live_builder_separates_public_law_rights_from_denied_access(audit) -> None:
    frontier = derive_expected_scope_frontier()
    denied_url = next(
        entry.source_url
        for entry in frontier
        if entry.content_scope == ContentScope.STATUTORY_TEXT.value
    )

    def fetch(url: str):
        if url == audit.robots_url_for(denied_url):
            return _fetch(
                audit, url, status=200, body=b"User-agent: *\nDisallow: /\n"
            )
        if url.endswith("/robots.txt"):
            return _fetch(audit, url, status=200, body=b"User-agent: *\nAllow: /\n")
        return _fetch(audit, url, status=200, body=b"<html>terms</html>")

    payload = audit.build_live_catalog_payload(fetch_url=fetch)
    denied = [
        record
        for record in payload["records"]
        if record["source_url"] == denied_url
        and record["content_scope"] == "statutory_text"
    ]
    assert len(denied) == 1
    assert denied[0]["robots_access_disposition"] == "denied"
    assert denied[0]["rights_disposition"] == "allowed"
    assert denied[0]["legal_basis"] == "government_edicts_doctrine"
    assert denied[0]["permissions"] == {
        "redistribution": True,
        "derivatives": True,
        "archive": True,
    }
    assert denied[0]["record_id"] not in payload["admitted_record_ids"]
    assert payload["authorizing_for_publication"] is False


def test_denied_live_robots_become_conditional_when_wayback_has_official_page(
    audit, monkeypatch: pytest.MonkeyPatch
) -> None:
    frontier = derive_expected_scope_frontier()
    denied_url = next(
        entry.source_url
        for entry in frontier
        if entry.content_scope == ContentScope.STATUTORY_TEXT.value
    )

    def fake_get(url: str, *, extra_headers=None):
        if url == audit.robots_url_for(denied_url):
            return _fetch(audit, url, status=200, body=b"User-agent: *\nDisallow: /\n")
        if url.endswith("/robots.txt"):
            return _fetch(audit, url, status=200, body=b"User-agent: *\nAllow: /\n")
        if url.startswith("https://web.archive.org/") or url.startswith("https://archive.is/"):
            return _fetch(
                audit,
                url,
                status=200,
                body=b"<html><body>" + (b"official statute snapshot " * 12) + b"</body></html>",
            )
        return _fetch(audit, url, status=200, body=b"<html>terms</html>")

    monkeypatch.setattr(audit, "_direct_http_get", fake_get)
    payload = audit.build_live_catalog_payload()
    denied = [
        record
        for record in payload["records"]
        if record["source_url"] == denied_url
        and record["content_scope"] == "statutory_text"
    ]
    assert len(denied) == 1
    assert denied[0]["robots_access_disposition"] == "conditional"
    assert denied[0]["access_conditions"] == ["archival-fallback-only"]
    assert denied[0]["condition_evidence"][0]["condition_id"] == "archival-fallback-only"
    assert denied[0]["record_id"] in payload["admitted_record_ids"]
    assert payload["authorizing_for_publication"] is True


def test_secret_free_guard_rejects_home_paths_and_tokens(audit) -> None:
    with pytest.raises(audit.AuditError, match="home path"):
        audit._assert_secret_free({"notes": "/home/runner/secret"}, context="test")
    with pytest.raises(audit.AuditError, match="token"):
        audit._assert_secret_free({"notes": "Bearer abcdefghijklmnop"}, context="test")


def test_mocked_live_seal_authorizes_through_evaluator(
    audit, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog_path = tmp_path / "legal_source_rights_catalog.json"
    receipt_path = tmp_path / "legal_source_rights_compliance.json"
    monkeypatch.setattr(policy, "default_live_catalog_path", lambda: catalog_path)
    monkeypatch.setattr(policy, "default_live_compliance_path", lambda: receipt_path)
    monkeypatch.setattr(audit, "default_live_catalog_path", lambda: catalog_path)
    monkeypatch.setattr(audit, "default_compliance_path", lambda: receipt_path)
    monkeypatch.setattr(audit, "fetch_live_url", _allowing_fetch(audit))

    receipt = audit.seal_live_catalog_and_receipt(fetch_url=_allowing_fetch(audit))
    assert receipt["authorizing_for_publication"] is True
    assert receipt["secret_free"] is True
    assert receipt["task_id"] == LIVE_TASK_ID
    assert receipt["goal_id"] == LIVE_GOAL_ID
    assert receipt["mode"] == "live"
    assert receipt["catalog_path"] == "data/legal/legal_source_rights_catalog.json"
    assert "/home/" not in json.dumps(receipt)
    report = require_live_source_evidence()
    assert report["authorizing_for_publication"] is True
    assert report["admitted_count"] == 52
    assert report["record_count"] == 57
    checked = audit.run_live_check()
    assert checked["status"] == "passed"
    assert checked["receipt_digest_sha256"] == receipt["report_digest_sha256"]

    forged = json.loads(json.dumps(receipt))
    forged["admitted_record_ids"][0] = "ak-invented-statutory_text"
    forged.pop("report_digest_sha256")
    forged["report_digest_sha256"] = policy.sha256_json(forged)
    audit._write_pretty_json(receipt_path, forged)
    with pytest.raises(
        policy.LiveEvidenceRequiredError,
        match="current authoritative evaluation|exact-51",
    ):
        policy.require_live_source_rights_receipt(forged)


def test_challenge_html_direct_200_uses_archive_fallback(
    audit, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = "https://www.capitol.hawaii.gov/robots.txt"
    snapshot = "https://web.archive.org/web/20240101120000id_/https://www.capitol.hawaii.gov/robots.txt"
    absence = b"<html><title>Hawaii State Legislature</title><h1>404 Page Not Found</h1></html>"
    challenge = b"<html><title>Just a moment...</title><div id='challenge-platform'></div></html>"

    def fake_get(url: str, *, extra_headers=None):
        if url == original:
            return _fetch(audit, url, status=200, body=challenge)
        if "wayback/available" in url:
            payload = json.dumps(
                {
                    "archived_snapshots": {
                        "closest": {
                            "available": True,
                            "url": snapshot.replace("id_/", "/"),
                            "status": "200",
                        }
                    }
                }
            ).encode("utf-8")
            return _fetch(audit, url, status=200, body=payload)
        if url == snapshot:
            return _fetch(audit, url, status=200, body=absence)
        return _fetch(audit, url, status=404, body=b"")

    monkeypatch.setattr(audit, "_direct_http_get", fake_get)
    result = audit.fetch_live_url(original)
    assert result.status == 200
    assert result.body == absence
    assert result.notes == "archival_fallback=wayback"
    assert audit.interpret_robots(
        result.body,
        user_agent=audit.LIVE_USER_AGENT,
        source_url="https://www.capitol.hawaii.gov/hrscurrent/",
        http_status=result.status,
        error=result.error,
    ) == ("allowed", None)


def test_archival_candidate_urls_cover_wayback_archive_is_and_common_crawl(audit) -> None:
    url = "https://www.capitol.hawaii.gov/robots.txt"
    candidates = audit.archival_candidate_urls(url)
    joined = " ".join(candidates)
    assert "web.archive.org" in joined
    assert "archive.org/wayback/available" in joined
    assert "archive.is/newest/" in joined
    assert "index.commoncrawl.org" in joined
    assert "justia.com" not in joined
    assert audit.archival_candidate_urls("https://web.archive.org/web/2024/https://example.gov/") == []


def test_fetch_live_url_uses_wayback_when_direct_host_is_unavailable(
    audit, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = "https://www.capitol.hawaii.gov/robots.txt"
    snapshot = "https://web.archive.org/web/20240101120000id_/https://www.capitol.hawaii.gov/robots.txt"
    allow = b"User-agent: *\nAllow: /\n"

    def fake_get(url: str, *, extra_headers=None):
        if url == original:
            return _fetch(audit, url, status=403, body=b"blocked")
        if "wayback/available" in url:
            payload = json.dumps(
                {
                    "archived_snapshots": {
                        "closest": {
                            "available": True,
                            "url": "https://web.archive.org/web/20240101120000/https://www.capitol.hawaii.gov/robots.txt",
                            "status": "200",
                        }
                    }
                }
            ).encode("utf-8")
            return _fetch(audit, url, status=200, body=payload)
        if url == snapshot:
            result = _fetch(audit, url, status=200, body=allow)
            return result
        return _fetch(audit, url, status=404, body=b"")

    monkeypatch.setattr(audit, "_direct_http_get", fake_get)
    result = audit.fetch_live_url(original)
    assert result.status == 200
    assert result.body == allow
    assert result.notes == "archival_fallback=wayback"
    assert result.fetch_url == snapshot


def test_fetch_live_url_does_not_archive_fallback_on_live_disallow(
    audit, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = "https://leginfo.legislature.ca.gov/robots.txt"
    deny = b"User-agent: *\nDisallow: /\n"

    def fake_get(url: str, *, extra_headers=None):
        if url == original:
            return _fetch(audit, url, status=200, body=deny)
        raise AssertionError(f"archive fallback must not run for live 200: {url}")

    monkeypatch.setattr(audit, "_direct_http_get", fake_get)
    result = audit.fetch_live_url(original)
    assert result.status == 200
    assert result.body == deny
    assert audit.interpret_robots(
        result.body,
        user_agent=audit.LIVE_USER_AGENT,
        source_url="https://leginfo.legislature.ca.gov/faces/codes.xhtml",
        http_status=result.status,
        error=result.error,
    ) == ("denied", None)


def test_live_check_without_receipt_fails_closed(
    audit, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog_path = tmp_path / "legal_source_rights_catalog.json"
    receipt_path = tmp_path / "missing_receipt.json"
    monkeypatch.setattr(policy, "default_live_catalog_path", lambda: catalog_path)
    monkeypatch.setattr(policy, "default_live_compliance_path", lambda: receipt_path)
    monkeypatch.setattr(audit, "default_live_catalog_path", lambda: catalog_path)
    monkeypatch.setattr(audit, "default_compliance_path", lambda: receipt_path)
    payload = audit.build_live_catalog_payload(fetch_url=_allowing_fetch(audit))
    audit._write_pretty_json(catalog_path, payload)
    with pytest.raises(audit.AuditError, match="compliance receipt is missing"):
        audit.run_live_check()
    report = require_live_source_evidence()
    assert report["authorizing_for_publication"] is True
