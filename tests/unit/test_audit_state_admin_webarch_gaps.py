from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module():
	repo_root = Path(__file__).resolve().parents[2]
	script_path = repo_root / "scripts" / "ops" / "legal_data" / "audit_state_admin_webarch_gaps.py"
	spec = importlib.util.spec_from_file_location("audit_state_admin_webarch_gaps", script_path)
	assert spec and spec.loader
	module = importlib.util.module_from_spec(spec)
	sys.modules[spec.name] = module
	spec.loader.exec_module(module)
	return module


def test_build_live_audit_api_prefers_live_methods() -> None:
	module = _load_module()

	api = module._build_live_audit_api()
	config = api.scraper.config

	assert config.common_crawl_hf_remote_meta is True
	assert [method.value for method in config.preferred_methods[:3]] == [
		"common_crawl",
		"playwright",
		"beautifulsoup",
	]


def test_page_row_marks_cloudflare_challenge_as_blocked() -> None:
	module = _load_module()

	row = module._page_row(
		state_code="AZ",
		corpus_urls=set(),
		page={
			"url": "https://apps.azsos.gov/public_services/",
			"success": True,
			"document": {
				"title": "Attention Required! | Cloudflare",
				"text": "Just a moment... Checking your browser before accessing azsos.gov.",
				"html": "<html><title>Attention Required! | Cloudflare</title><body>Just a moment...</body></html>",
			},
			"errors": [],
		},
	)

	assert row["success"] is True
	assert row["usable_success"] is False
	assert row["blocked_or_transport_error"] is True
	assert row["blocked_by_challenge_page"] is True
	assert row["substantive_admin"] is False


def test_page_row_keeps_substantive_page_usable_when_html_contains_js_shell_text() -> None:
	module = _load_module()

	row = module._page_row(
		state_code="IN",
		corpus_urls=set(),
		page={
			"url": "https://iar.iga.in.gov/code/current",
			"success": True,
			"document": {
				"title": "Indiana Administrative Code | IARP",
				"text": "Indiana Administrative Code\nTITLE 10 Office of Attorney General\nARTICLE 1 Unclaimed Property\nRule 1. Definitions and authority.",
				"html": "<html><body><noscript>You need to enable JavaScript to run this app.</noscript></body></html>",
			},
			"errors": [],
		},
	)

	assert row["success"] is True
	assert row["usable_success"] is True
	assert row["blocked_or_transport_error"] is False
	assert row["blocked_by_challenge_page"] is False


def test_audit_state_treats_only_blocked_successes_as_transport_failures(monkeypatch) -> None:
	module = _load_module()

	class _FakeAPI:
		def agentic_discover_and_fetch(self, **_kwargs):
			return {
				"visited_count": 1,
				"results": [
					{
						"url": "https://apps.azsos.gov/public_services/",
						"success": True,
						"document": {
							"title": "Request Rejected",
							"text": "Your request has been rejected. Contact the administrator.",
							"html": "<html><title>Request Rejected</title></html>",
						},
						"errors": [],
					}
				],
			}

	monkeypatch.setattr(module, "_build_live_audit_api", lambda: _FakeAPI())

	row = module._audit_state(
		state_code="AZ",
		corpus_rows=[],
		local_jsonld_rows=0,
		max_seeds=2,
		max_pages=2,
		max_hops=1,
	)

	assert row["probe_success_count"] == 1
	assert row["probe_usable_success_count"] == 0
	assert row["probe_blocked_count"] == 1
	assert row["gap_category"] == "blocked_or_transport_failures"


def test_audit_state_preserves_has_substantive_signal_when_corpus_is_already_populated(monkeypatch) -> None:
	module = _load_module()

	class _FakeAPI:
		def agentic_discover_and_fetch(self, **_kwargs):
			return {
				"visited_count": 1,
				"results": [
					{
						"url": "https://iar.iga.in.gov/code/current",
						"success": True,
						"document": {
							"title": "Indiana Administrative Code | IARP",
							"text": "Indiana Administrative Code\nTITLE 10 Office of Attorney General\nARTICLE 1 Unclaimed Property",
							"html": "<html><body>Indiana Administrative Code</body></html>",
						},
						"errors": [],
					}
				],
			}

	monkeypatch.setattr(module, "_build_live_audit_api", lambda: _FakeAPI())

	row = module._audit_state(
		state_code="IN",
		corpus_rows=[
			{
				"state_code": "IN",
				"url": "https://iar.iga.in.gov/code/current/10/1",
				"title": "Indiana Administrative Code",
				"text": (
					"Indiana Administrative Code TITLE 10 Office of Attorney General ARTICLE 1 Rule 1. "
					"Definitions and authority. Authority: IC 4-22-2. History: Filed Jan 1, 2024, 12:00 p.m.; "
					"effective Feb 1, 2024. This rule governs unclaimed property administration and reporting requirements."
				),
			}
		],
		local_jsonld_rows=1,
		max_seeds=2,
		max_pages=2,
		max_hops=0,
	)

	assert row["probe_usable_success_count"] == 1
	assert row["corpus_substantive_rows"] == 1
	assert row["gap_category"] == "has_substantive_signal"
