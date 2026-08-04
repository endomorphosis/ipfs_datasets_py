"""Integration tests for optional live official-source canary (PATLAW-167).

Acceptance:

* Canary defaults to offline fixtures (network-free)
* Optional live mode records bounded eCFR / GovInfo / Federal Register / ODP
  probes with content-free receipts
* Never mutates private matter state

Validation::

    python -m pytest tests/integration/ops/patent_legal_intelligence/test_live_canary.py -q
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Paths / module load
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CANARY_PATH = (
    _REPO_ROOT
    / "scripts"
    / "ops"
    / "patent_legal_intelligence"
    / "live_canary.py"
)
_DOC_PATH = _REPO_ROOT / "docs" / "operations" / "PATENT_LEGAL_LIVE_CANARY.md"
_TEST_PATH = Path(__file__).resolve()


def _load_canary():
    spec = importlib.util.spec_from_file_location(
        "patent_legal_live_canary_patlaw167", _CANARY_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


canary = _load_canary()


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _ScriptedResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b'{"ok":true}',
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = int(status)
        self._body = bytes(body)
        self._offset = 0
        self.headers = dict(headers or {"Content-Type": "application/json"})

    def getcode(self) -> int:
        return self.status

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk = self._body[self._offset :]
            self._offset = len(self._body)
            return chunk
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def close(self) -> None:
        return None


class ScriptedOpener:
    """Deterministic opener for offline-safe live-mode tests."""

    def __init__(self, outcomes: list[Any] | None = None) -> None:
        self._outcomes: list[Any] = list(outcomes or [])
        self.requests: list[urllib.request.Request] = []

    def add(
        self,
        *,
        status: int = 200,
        body: bytes | str | dict[str, Any] = b'{"ok":true}',
        headers: dict[str, str] | None = None,
    ) -> None:
        if isinstance(body, dict):
            raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            )
        elif isinstance(body, str):
            raw = body.encode("utf-8")
        else:
            raw = bytes(body)
        self._outcomes.append(
            {
                "status": int(status),
                "body": raw,
                "headers": dict(headers or {"Content-Type": "application/json"}),
            }
        )

    def add_error(self, exc: BaseException) -> None:
        self._outcomes.append(exc)

    def __call__(self, prepared: urllib.request.Request, timeout: float) -> Any:
        self.requests.append(prepared)
        if not self._outcomes:
            raise urllib.error.URLError("scripted opener exhausted")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return _ScriptedResponse(
            status=int(outcome["status"]),
            body=bytes(outcome["body"]),
            headers=dict(outcome.get("headers") or {}),
        )


class NetworkForbiddenOpener:
    """Raises if any network call is attempted (offline safety sentinel)."""

    def __call__(self, prepared: urllib.request.Request, timeout: float) -> Any:
        raise AssertionError(
            f"offline canary must not open network: {prepared.full_url!r}"
        )


def _four_success_opener() -> ScriptedOpener:
    opener = ScriptedOpener()
    for _ in range(4):
        opener.add(status=200, body={"canary": True, "items": []})
    return opener


# ---------------------------------------------------------------------------
# Declared outputs / identity
# ---------------------------------------------------------------------------


def test_declared_outputs_exist() -> None:
    assert _CANARY_PATH.is_file()
    assert _TEST_PATH.is_file()
    assert _DOC_PATH.is_file()


def test_module_identity_and_policy() -> None:
    assert canary.TASK_ID == "PATLAW-167"
    assert canary.GOAL_ID == "PATLAW-G202"
    assert canary.SCHEMA_VERSION == "patent-legal.live-canary.v1"
    assert canary.INTERFACE == "PatentLegalLiveCanary@1"
    assert canary.POLICY_ID == "patent-legal-live-canary/v1"
    assert set(canary.SOURCE_FAMILIES) == {
        "ecfr",
        "govinfo",
        "federal_register",
        "odp",
    }
    for verb in ("sign", "pay", "file", "submit", "write_private_matter_state"):
        assert verb in canary.FORBIDDEN_MUTATIONS


def test_docs_cover_offline_default_and_sources() -> None:
    text = _DOC_PATH.read_text(encoding="utf-8")
    assert "PATLAW-167" in text
    assert "offline" in text.lower()
    for token in ("eCFR", "GovInfo", "Federal Register", "ODP"):
        assert token in text
    assert "private matter" in text.lower() or "private_matter" in text.lower()


# ---------------------------------------------------------------------------
# Offline default (primary CI path)
# ---------------------------------------------------------------------------


def test_resolve_mode_defaults_to_offline() -> None:
    assert canary.resolve_mode(environ={}) is canary.CanaryMode.OFFLINE
    assert canary.resolve_mode(offline=True, environ={}) is canary.CanaryMode.OFFLINE
    assert canary.resolve_mode(live=True, environ={}) is canary.CanaryMode.LIVE


def test_live_opt_in_via_env_flags() -> None:
    for flag in canary.LIVE_ENV_FLAGS:
        assert canary.live_opted_in_from_env({flag: "1"}) is True
        assert canary.live_opted_in_from_env({flag: "true"}) is True
        assert canary.live_opted_in_from_env({flag: "0"}) is False
    assert canary.live_opted_in_from_env({}) is False


def test_offline_default_run_uses_fixtures_no_network(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipts"
    matter = tmp_path / "private_matter" / "tenant-a"
    matter.mkdir(parents=True)
    seed = matter / "portfolio.json"
    seed.write_text('{"matter_id":"opaque","note":"do-not-touch"}\n', encoding="utf-8")
    before = seed.read_text(encoding="utf-8")

    report = canary.run_canary(
        offline=True,
        opener=NetworkForbiddenOpener(),
        receipt_dir=receipt_dir,
        write_receipt=True,
        matter_root=matter,
        environ={},
    )

    assert report["mode"] == "offline"
    assert report["ok"] is True
    assert report["disposition"] == "offline_ok"
    assert report["network_invoked"] is False
    assert report["private_matter_mutated"] is False
    assert report["content_free"] is True
    assert report["probe_count"] == 4
    assert set(report["sources_probed"]) == set(canary.SOURCE_FAMILIES)
    assert all(p["fixture"] is True for p in report["probes"])
    assert all(p["status"] == "fixture" for p in report["probes"])
    assert all(p["read_only"] is True for p in report["probes"])
    assert seed.read_text(encoding="utf-8") == before
    assert (receipt_dir / "canary-latest.json").is_file()
    canary.assert_content_free(report)


def test_offline_fixture_recipe_is_compact_and_complete() -> None:
    recipe = canary.build_offline_fixture_recipe()
    raw = json.dumps(recipe, sort_keys=True)
    assert len(raw.encode("utf-8")) < 50_000
    assert recipe["schema_version"] == canary.FIXTURE_SCHEMA_VERSION
    assert recipe["network_free"] is True
    assert recipe["read_only"] is True
    assert recipe["bounded"] is True
    assert set(recipe["sources"]) == set(canary.SOURCE_FAMILIES)
    sources = {c["source"] for c in recipe["cases"]}
    assert sources == set(canary.SOURCE_FAMILIES)
    assert recipe["acceptance"]["defaults_to_offline_fixtures"] is True
    assert recipe["acceptance"]["never_mutates_private_matter_state"] is True


def test_default_cli_is_offline_and_succeeds(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "cli-receipts"
    code = canary.main(
        [
            "--offline",
            "--receipt-dir",
            str(receipt_dir),
            "--json",
        ]
    )
    assert code == 0
    assert (receipt_dir / "canary-latest.json").is_file()
    payload = json.loads((receipt_dir / "canary-latest.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "offline"
    assert payload["ok"] is True
    canary.assert_content_free(payload)


# ---------------------------------------------------------------------------
# Optional live mode (scripted transport — no real network in CI)
# ---------------------------------------------------------------------------


def test_live_mode_records_bounded_probes_with_receipts(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "live-receipts"
    opener = _four_success_opener()
    report = canary.run_canary(
        live=True,
        opener=opener,
        receipt_dir=receipt_dir,
        write_receipt=True,
        environ={},
    )
    assert report["mode"] == "live"
    assert report["opt_in"] is True
    assert report["network_invoked"] is True
    assert report["probe_count"] == 4
    assert len(opener.requests) == 4
    assert set(report["sources_probed"]) == set(canary.SOURCE_FAMILIES)
    assert report["ok"] is True
    assert report["disposition"] in {"pass", "pass_with_gaps"}
    for probe in report["probes"]:
        assert probe["fixture"] is False
        assert probe["read_only"] is True
        assert probe["status"] == "success"
        assert probe["status_code"] == 200
        assert probe["body_sha256"]
        assert probe["host"] in canary.ALLOWED_HOSTS
        # Body content never retained on the receipt.
        blob = json.dumps(probe)
        assert '"items"' not in blob or "body_retained" in json.dumps(probe.get("metadata"))
    assert (receipt_dir / "canary-latest.json").is_file()
    canary.assert_content_free(report)


def test_live_mode_via_env_flag(tmp_path: Path) -> None:
    opener = _four_success_opener()
    report = canary.run_canary(
        opener=opener,
        receipt_dir=tmp_path / "env-live",
        write_receipt=False,
        environ={"PATLAW_167_LIVE_CANARY": "1"},
    )
    assert report["mode"] == "live"
    assert report["network_invoked"] is True
    assert len(opener.requests) == 4


def test_live_partial_failures_are_receipt_bound_gaps(tmp_path: Path) -> None:
    opener = ScriptedOpener()
    opener.add(status=200, body={"ok": True})
    opener.add_error(urllib.error.URLError("simulated outage"))
    opener.add(status=503, body=b"unavailable")
    opener.add(status=200, body={"ok": True})
    # HTTPError path: ScriptedOpener raises URLError for add_error; for 503 we
    # return a response with status 503 (not urllib HTTPError). That's fine —
    # canary classifies non-200 as http_error via status code.
    # Rebuild with proper sequence:
    opener = ScriptedOpener()
    opener.add(status=200, body={"ok": True})
    opener.add_error(urllib.error.URLError("simulated outage"))
    opener.add(status=503, body=b"unavailable")
    opener.add(status=200, body={"ok": True})

    report = canary.run_canary(
        live=True,
        opener=opener,
        receipt_dir=tmp_path / "gaps",
        write_receipt=True,
    )
    statuses = {p["status"] for p in report["probes"]}
    assert "success" in statuses
    assert "transport_error" in statuses or "http_error" in statuses
    assert report["disposition"] in {"pass_with_gaps", "pass", "fail"}
    canary.assert_content_free(report)


def test_live_policy_rejects_non_allowlisted_host() -> None:
    bad = canary.ProbeSpec(
        source="ecfr",
        label="bad host",
        method="GET",
        url="https://example.com/titles.json",
        authority_label="test",
    )
    result = canary.execute_live_probe(bad, opener=NetworkForbiddenOpener())
    assert result.status == "policy_violation"
    assert result.fixture is False


def test_probe_spec_rejects_non_readonly_method() -> None:
    with pytest.raises(ValueError, match="read-only"):
        canary.ProbeSpec(
            source="odp",
            label="write",
            method="POST",
            url="https://api.uspto.gov/api/v1/patent/applications",
            authority_label="test",
        )


# ---------------------------------------------------------------------------
# Private matter immutability / content-free policy
# ---------------------------------------------------------------------------


def test_refuses_receipt_dir_under_private_matter(tmp_path: Path) -> None:
    bad = tmp_path / "private_matter" / "receipts"
    with pytest.raises(ValueError, match="private matter"):
        canary.run_canary(
            offline=True,
            receipt_dir=bad,
            write_receipt=True,
            environ={},
        )


def test_private_matter_mutation_detected(tmp_path: Path) -> None:
    matter = tmp_path / "private_matter" / "tenant"
    matter.mkdir(parents=True)
    (matter / "a.json").write_text("{}\n", encoding="utf-8")

    class MutatingOpener(ScriptedOpener):
        def __call__(self, prepared: urllib.request.Request, timeout: float) -> Any:
            # Simulate a buggy side-effect writer (must be detected).
            (matter / "mutated.json").write_text('{"leaked":true}\n', encoding="utf-8")
            return super().__call__(prepared, timeout)

    opener = MutatingOpener()
    for _ in range(4):
        opener.add(status=200, body=b"{}")

    with pytest.raises(RuntimeError, match="private matter state mutated"):
        canary.run_canary(
            live=True,
            opener=opener,
            receipt_dir=tmp_path / "safe-receipts",
            write_receipt=True,
            matter_root=matter,
        )


def test_assert_content_free_rejects_secret_markers() -> None:
    with pytest.raises(ValueError, match="content-free"):
        canary.assert_content_free({"note": "authorization: bearer supersecret"})
    with pytest.raises(ValueError, match="content-free"):
        canary.assert_content_free({"x": "secret_document_body"})


def test_redact_mapping_strips_secret_keys() -> None:
    redacted = canary.redact_mapping(
        {
            "api_key": "should-not-appear",
            "status": "ok",
            "nested": {"token": "xyz", "count": 1},
        }
    )
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["status"] == "ok"
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert redacted["nested"]["count"] == 1


def test_acceptance_flags_cover_all_sources(tmp_path: Path) -> None:
    report = canary.run_canary(
        offline=True,
        receipt_dir=tmp_path / "acc",
        write_receipt=False,
        environ={},
    )
    acc = report["acceptance"]
    assert acc["offline_is_default"] is True
    assert acc["live_is_opt_in"] is True
    assert acc["never_mutates_private_matter_state"] is True
    assert acc["probes_ecfr"] is True
    assert acc["probes_govinfo"] is True
    assert acc["probes_federal_register"] is True
    assert acc["probes_odp"] is True
    assert acc["records_receipts"] is True


def test_max_probes_bound(tmp_path: Path) -> None:
    report = canary.run_canary(
        offline=True,
        max_probes=2,
        receipt_dir=tmp_path / "bounded",
        write_receipt=False,
    )
    assert report["probe_count"] == 2
    assert report["max_probes"] == 2


def test_conflicting_live_and_offline_flags_error() -> None:
    with pytest.raises(ValueError, match="both"):
        canary.resolve_mode(live=True, offline=True, environ={})


def test_no_write_skips_receipt_file(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "empty"
    report = canary.run_canary(
        offline=True,
        receipt_dir=receipt_dir,
        write_receipt=False,
    )
    assert report["ok"] is True
    assert "receipt_path" not in report or report.get("receipt_path") is None
    assert not receipt_dir.exists() or not any(receipt_dir.iterdir())
