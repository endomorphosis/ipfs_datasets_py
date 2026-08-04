"""Unit tests for portfolio automation helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    FORBIDDEN_OPERATOR_CAPABILITIES,
    ForbiddenOperatorCapabilityError,
    PortfolioMatter,
    PortfolioSeed,
    assert_operator_capability,
    build_export_manifest_from_folder,
    build_import_authorization,
    confirm_ownership,
    discover_public_by_inventor,
    drop_matters,
    inventorf_phrase_query,
    keep_only_matters,
    merge_matters,
    save_portfolio_seed,
    load_portfolio_seed,
    write_export_package_sidecar,
)


def test_inventor_query_phrase() -> None:
    q = inventorf_phrase_query('Benjamin Barber')
    assert 'inventorNameText:"Benjamin Barber"' in q


def test_forbidden_capability() -> None:
    with pytest.raises(ForbiddenOperatorCapabilityError):
        assert_operator_capability("store_credentials_or_cookies")
    assert "unattended_patent_center_scrape" in FORBIDDEN_OPERATOR_CAPABILITIES


def test_merge_and_confirm(tmp_path: Path) -> None:
    a = PortfolioMatter(application_number="18654466", title="A", ownership="candidate_unconfirmed")
    b = PortfolioMatter(application_number="18654466", title="", ownership="confirmed_operator")
    c = PortfolioMatter(application_number="11290627", title="C")
    merged = merge_matters([a], [b, c])
    assert len(merged) == 2
    by_app = {m.application_number: m for m in merged}
    assert by_app["18654466"].ownership == "confirmed_operator"
    assert by_app["18654466"].title == "A"

    seed = PortfolioSeed(tenant_id="t1", matters=merged)
    seed = confirm_ownership(seed, ["11290627"])
    assert any(
        m.application_number == "11290627" and m.ownership == "confirmed_operator"
        for m in seed.matters
    )
    path = save_portfolio_seed(seed, tmp_path / "seed.json")
    loaded = load_portfolio_seed(path)
    assert loaded.tenant_id == "t1"
    assert len(loaded.matters) == 2


def test_build_manifest_and_sidecar(tmp_path: Path) -> None:
    (tmp_path / "package").mkdir()
    doc = tmp_path / "package" / "office_action.pdf"
    doc.write_bytes(b"%PDF-1.4 synthetic test bytes")
    ack = tmp_path / "package" / "acknowledgement_receipt.txt"
    ack.write_text("EAR synthetic\n", encoding="utf-8")

    manifest = build_export_manifest_from_folder(
        tmp_path,
        application_number="16000001",
    )
    assert len(manifest.entries) == 2
    roles = {e.labels.get("role") for e in manifest.entries}
    assert "office_action" in roles or "document" in roles
    assert any(e.expected_sha256 for e in manifest.entries)

    paths = write_export_package_sidecar(
        tmp_path,
        application_number="16000001",
        tenant_id="tenant-test",
        authorizing_user="operator:test",
    )
    assert paths["manifest"].is_file()
    assert paths["authorization"].is_file()
    auth = json.loads(paths["authorization"].read_text(encoding="utf-8"))
    assert auth["tenant_id"] == "tenant-test"
    assert "password" not in json.dumps(auth).lower()


def test_import_authorization_rejects_secret_user() -> None:
    with pytest.raises(Exception):
        build_import_authorization(
            tenant_id="t1",
            import_root="/tmp/x",
            authorizing_user="user password=sekrit",
        )


def test_drop_and_keep_only() -> None:
    seed = PortfolioSeed(
        tenant_id="t1",
        matters=[
            PortfolioMatter(application_number="111"),
            PortfolioMatter(application_number="222"),
            PortfolioMatter(application_number="333"),
        ],
    )
    seed, dropped = drop_matters(seed, ["222"])
    assert dropped == ["222"]
    assert [m.application_number for m in seed.matters] == ["111", "333"]

    seed, removed = keep_only_matters(seed, ["111", "999"])
    assert "333" in removed
    apps = {m.application_number: m for m in seed.matters}
    assert set(apps) == {"111", "999"}
    assert apps["111"].ownership == "confirmed_operator"
    assert apps["999"].ownership == "confirmed_operator"


def test_document_sync_skips_candidates_when_confirmed_only(tmp_path: Path) -> None:
    from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
        sync_public_documents_batch,
    )

    seed = PortfolioSeed(
        tenant_id="t1",
        matters=[
            PortfolioMatter(
                application_number="18654466",
                ownership="candidate_unconfirmed",
            )
        ],
    )

    class _NoClient:
        def get_documents(self, *a, **k):  # pragma: no cover
            raise AssertionError("should not call client for candidates-only seed")

    report = sync_public_documents_batch(
        seed,
        client=_NoClient(),
        documents_root=tmp_path / "docs",
        confirmed_only=True,
    )
    assert report["matter_count"] == 0
    assert report["success_count"] == 0
    assert report["results"] == []


def test_discover_with_mock_http() -> None:
    sample = {
        "count": 1,
        "patentFileWrapperDataBag": [
            {
                "applicationNumberText": "18654466",
                "applicationMetaData": {
                    "inventionTitle": "Example",
                    "filingDate": "2024-05-03",
                    "applicationStatusDescriptionText": "Patented Case",
                    "inventorBag": [
                        {"inventorNameText": "Benjamin Barber"},
                    ],
                    "applicantBag": [
                        {"applicantNameText": "Example Co"},
                    ],
                },
            }
        ],
    }

    def fake_post(url: str, headers: dict, body: bytes):
        assert "X-API-KEY" in headers
        assert headers["X-API-KEY"] == "test-key"
        return 200, sample

    matters = discover_public_by_inventor(
        "Benjamin Barber",
        api_key="test-key",
        http_post=fake_post,
    )
    assert len(matters) == 1
    assert matters[0].application_number == "18654466"
    assert matters[0].ownership == "candidate_unconfirmed"
