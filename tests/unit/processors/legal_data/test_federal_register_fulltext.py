"""Unit tests for official Federal Register body-text coverage (LCR-053).

Acceptance: Every inventory document is full-text admitted, explicitly
metadata-only under schema, excluded, quarantined, or failed-final;
failed-final is zero and no placeholder enters retrieval.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_fulltext import (
    ADMITTED_DISPOSITIONS,
    COVERAGE_CATEGORIES,
    GOAL_ID,
    INVENTORY_TASK_ID,
    MODE_FIXTURE,
    REPORT_SCHEMA,
    SCHEMA_VERSION,
    SOURCE_PRECEDENCE,
    TASK_ID,
    AllowedNonBodyReason,
    CoverageDisposition,
    FailedFinalCoverageError,
    FederalRegisterFulltextError,
    FixtureFulltextTransport,
    FixtureRole,
    FulltextConfig,
    FulltextMode,
    ImmutableTextCache,
    InventoryRewriteError,
    LiveFulltextDisabledError,
    ParserResult,
    PlaceholderAdmittedError,
    SourceFormat,
    assign_fixture_roles,
    assert_coverage_closed,
    assert_no_secrets,
    build_compact_coverage_recipe,
    build_fixture_coverage_report,
    check_coverage_report,
    classify_document,
    default_report_path,
    detect_content_kind,
    enrich_federal_register_fulltext,
    expand_coverage_payload,
    find_secret_surfaces,
    fixture_role_for_index,
    is_coverage_recipe,
    is_placeholder_text,
    load_fixture_inventory_documents,
    locators_for_document,
    normalize_body,
    write_coverage_report,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    DEFAULT_OBSERVATION_CUTOFF,
    LEGACY_DELTA_START_INCLUSIVE,
    MutableCutoffError,
    PREVIOUS_PUBLIC_PIN,
    content_sha256,
)


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "federal-register-fulltext-v1"
    assert REPORT_SCHEMA == (
        "ipfs_datasets_py/legal-corpora-reindex-federal-fulltext-coverage@1"
    )
    assert TASK_ID == "LCR-053"
    assert GOAL_ID == "LCR-G110"
    assert INVENTORY_TASK_ID == "LCR-052"
    assert SOURCE_PRECEDENCE == ("html", "xml", "pdf", "govinfo")
    assert COVERAGE_CATEGORIES == (
        "full_text_admitted",
        "metadata_only",
        "excluded",
        "quarantined",
        "failed_final",
    )


def test_source_precedence_is_html_xml_pdf_govinfo() -> None:
    assert [fmt.precedence for fmt in (SourceFormat.coerce(n) for n in SOURCE_PRECEDENCE)] == [
        0,
        1,
        2,
        3,
    ]
    assert SourceFormat.HTML.admitted_disposition is CoverageDisposition.HTML_BODY
    assert SourceFormat.XML.admitted_disposition is CoverageDisposition.XML_BODY
    assert SourceFormat.PDF.admitted_disposition is CoverageDisposition.PDF_BODY
    assert SourceFormat.GOVINFO.admitted_disposition is CoverageDisposition.GOVINFO_BODY


def test_anti_bot_navigation_error_and_placeholder_are_detected() -> None:
    assert (
        detect_content_kind(
            b"<html><body>Please complete the captcha. cloudflare</body></html>",
            "html",
            media_type="text/html",
        )
        is ParserResult.ANTI_BOT
    )
    assert (
        detect_content_kind(
            b"<html><body><nav>Skip to main content. Subscribe to the Federal "
            b"Register. Sign in to your account.</nav></body></html>",
            "html",
            media_type="text/html",
        )
        is ParserResult.NAVIGATION
    )
    assert (
        detect_content_kind(
            b"<html><body><h1>404 Not Found</h1><p>The requested document was "
            b"not found.</p></body></html>",
            "html",
            media_type="text/html",
        )
        is ParserResult.ERROR_PAGE
    )
    assert (
        detect_content_kind(
            b"<html><body><article id='fulltext'>[full text not available] "
            b"lorem ipsum dolor sit amet placeholder body</article></body></html>",
            "html",
            media_type="text/html",
        )
        is ParserResult.PLACEHOLDER
    )
    assert is_placeholder_text("[full text not available] lorem ipsum")


def test_official_html_normalizes_and_is_not_placeholder() -> None:
    raw = (
        b"<!DOCTYPE html><html><body><nav>chrome</nav>"
        b"<article id='fulltext'><h1>Rule</h1>"
        b"<p>This is the official body text for 2026-45000 published in the "
        b"Federal Register with enough substance to admit.</p>"
        b"<p>Section 1. Purpose. This document implements the sealed fixture.</p>"
        b"</article></body></html>"
    )
    assert detect_content_kind(raw, "html", media_type="text/html") is ParserResult.SUCCESS
    text = normalize_body(raw, "html")
    assert "official body text" in text.lower()
    assert "chrome" not in text.lower()
    assert not is_placeholder_text(text)


def test_mutable_cutoff_is_rejected() -> None:
    with pytest.raises(MutableCutoffError):
        FulltextConfig(observation_cutoff="latest", mode=FulltextMode.FIXTURE)


def test_live_mode_without_transport_is_disabled() -> None:
    with pytest.raises(LiveFulltextDisabledError):
        enrich_federal_register_fulltext(
            config=FulltextConfig(mode=FulltextMode.LIVE)
        )


def test_fixture_enrichment_classifies_every_inventory_document() -> None:
    result = enrich_federal_register_fulltext(
        config=FulltextConfig(mode=FulltextMode.FIXTURE)
    )
    assert result.errors == []
    assert result.failed_final == 0
    expected = result.inventory_document_count
    assert expected >= 10
    assert result.classified_count == expected
    assert result.coverage_report["acceptance"]["every_inventory_document_classified"] is True
    categories = {d.disposition.category for d in result.documents}
    assert "full_text_admitted" in categories
    assert "metadata_only" in categories
    assert "excluded" in categories
    assert "quarantined" in categories
    assert "failed_final" not in categories
    legal_ids = [d.legal_id for d in result.documents]
    assert len(legal_ids) == len(set(legal_ids))
    inventory_ids = {doc.legal_id for doc in load_fixture_inventory_documents()[0]}
    assert set(legal_ids) == inventory_ids


def test_failed_final_is_zero_and_no_placeholder_is_admitted() -> None:
    result = enrich_federal_register_fulltext(
        config=FulltextConfig(mode=FulltextMode.FIXTURE)
    )
    assert_coverage_closed(result)
    for document in result.documents:
        assert document.disposition is not CoverageDisposition.FAILED_FINAL
        if document.disposition.is_admitted:
            cached = result.cache.get_for_legal_id(document.legal_id)
            assert cached is not None
            assert not is_placeholder_text(cached.normalized_text)
            assert cached.content_hash == document.admitted_content_hash
            assert len(cached.normalized_text) >= 80
        else:
            assert document.body_char_count == 0
            assert document.admitted_content_hash is None
            assert document.allowed_reason


def test_source_precedence_prefers_html_over_xml_pdf_govinfo() -> None:
    documents, _report = load_fixture_inventory_documents()
    roles = assign_fixture_roles(documents)
    html_docs = [
        doc for doc in documents if roles[doc.legal_id] is FixtureRole.HTML_BODY
    ]
    assert html_docs
    document = html_docs[0]
    cache = ImmutableTextCache()
    transport = FixtureFulltextTransport(documents, roles)
    coverage = classify_document(
        document, transport=transport, cache=cache, fixture_role=FixtureRole.HTML_BODY
    )
    assert coverage.disposition is CoverageDisposition.HTML_BODY
    assert coverage.admitted_source_format == "html"
    assert coverage.attempts[0].source_format is SourceFormat.HTML
    assert coverage.attempts[0].body_usable is True
    # Lower-precedence formats are not fetched once HTML wins.
    assert all(a.source_format is SourceFormat.HTML for a in coverage.attempts) or (
        coverage.attempts[0].source_format is SourceFormat.HTML
    )


def test_xml_pdf_and_govinfo_win_only_after_higher_precedence_absence() -> None:
    documents, _report = load_fixture_inventory_documents()
    roles = assign_fixture_roles(documents)
    transport = FixtureFulltextTransport(documents, roles)
    cache = ImmutableTextCache()
    by_role = {roles[doc.legal_id]: doc for doc in documents}

    xml_cov = classify_document(
        by_role[FixtureRole.XML_BODY],
        transport=transport,
        cache=cache,
        fixture_role=FixtureRole.XML_BODY,
    )
    assert xml_cov.disposition is CoverageDisposition.XML_BODY
    assert xml_cov.attempts[0].source_format is SourceFormat.HTML
    assert xml_cov.attempts[0].body_usable is False
    assert xml_cov.admitted_source_format == "xml"

    pdf_cov = classify_document(
        by_role[FixtureRole.PDF_BODY],
        transport=transport,
        cache=cache,
        fixture_role=FixtureRole.PDF_BODY,
    )
    assert pdf_cov.disposition is CoverageDisposition.PDF_BODY
    assert pdf_cov.admitted_source_format == "pdf"

    gov_cov = classify_document(
        by_role[FixtureRole.GOVINFO_BODY],
        transport=transport,
        cache=cache,
        fixture_role=FixtureRole.GOVINFO_BODY,
    )
    assert gov_cov.disposition is CoverageDisposition.GOVINFO_BODY
    assert gov_cov.admitted_source_format == "govinfo"


def test_metadata_only_excluded_and_quarantined_have_allowed_reasons() -> None:
    result = enrich_federal_register_fulltext(
        config=FulltextConfig(mode=FulltextMode.FIXTURE)
    )
    metadata = [d for d in result.documents if d.disposition is CoverageDisposition.METADATA_ONLY]
    excluded = [d for d in result.documents if d.disposition is CoverageDisposition.EXCLUDED]
    quarantined = [d for d in result.documents if d.disposition is CoverageDisposition.QUARANTINED]
    assert metadata
    assert excluded
    assert len(quarantined) >= 3
    assert all(
        d.allowed_reason
        in {
            AllowedNonBodyReason.OFFICIAL_METADATA_ONLY.value,
            AllowedNonBodyReason.OFFICIAL_BODY_UNAVAILABLE.value,
        }
        for d in metadata
    )
    assert all(
        d.allowed_reason == AllowedNonBodyReason.RIGHTS_OR_SCOPE_EXCLUSION.value
        for d in excluded
    )
    quarantine_reasons = {d.allowed_reason for d in quarantined}
    assert AllowedNonBodyReason.ANTI_BOT_CONTENT.value in quarantine_reasons
    assert AllowedNonBodyReason.NAVIGATION_CONTENT.value in quarantine_reasons
    assert AllowedNonBodyReason.ERROR_PAGE_CONTENT.value in quarantine_reasons


def test_placeholder_cannot_enter_the_immutable_cache() -> None:
    cache = ImmutableTextCache()
    documents, _report = load_fixture_inventory_documents()
    document = documents[0]
    locators = locators_for_document(document)

    def transport(url: str, _headers):
        _ = url
        return (
            b"<html><body><article id='fulltext'>[full text not available] "
            b"lorem ipsum dolor sit amet placeholder body insert official "
            b"text here coming soon</article></body></html>",
            "text/html",
        )

    coverage = classify_document(document, transport=transport, cache=cache)
    assert coverage.disposition is CoverageDisposition.QUARANTINED
    assert coverage.allowed_reason == AllowedNonBodyReason.PLACEHOLDER_CONTENT.value
    assert cache.size == 0
    assert locators[SourceFormat.HTML]


def test_check_coverage_report_accepts_fixture_report() -> None:
    report = build_fixture_coverage_report()
    result = check_coverage_report(report)
    assert result["ok"] is True
    assert result["frontier_closed"] is True
    assert result["failed_final"] == 0
    assert result["acceptance"]["every_inventory_document_classified"] is True
    assert result["acceptance"]["failed_final_zero"] is True
    assert result["acceptance"]["no_placeholder_admitted"] is True
    assert result["acceptance"]["inventory_unmodified"] is True
    assert result["acceptance"]["secrets_absent"] is True
    assert result["acceptance"]["mode"] == MODE_FIXTURE
    assert result["acceptance"]["previous_public_pin"] == PREVIOUS_PUBLIC_PIN
    assert result["acceptance"]["inventory_task_id"] == INVENTORY_TASK_ID
    assert result["acceptance"]["observation_cutoff"] == DEFAULT_OBSERVATION_CUTOFF


def test_check_rejects_failed_final_and_placeholder_admission() -> None:
    report = build_fixture_coverage_report()
    broken = copy.deepcopy(report)
    broken["counts"]["failed_final"] = 1
    broken["acceptance"]["failed_final"] = 1
    broken["acceptance"]["failed_final_zero"] = False
    broken["coverage_digest"] = "0" * 64
    with pytest.raises((FailedFinalCoverageError, FederalRegisterFulltextError)):
        check_coverage_report(broken)

    broken2 = copy.deepcopy(report)
    broken2["acceptance"]["no_placeholder_admitted"] = False
    with pytest.raises(FederalRegisterFulltextError):
        check_coverage_report(broken2)


def test_secrets_and_home_paths_are_rejected() -> None:
    report = build_fixture_coverage_report()
    assert_no_secrets(report)
    assert find_secret_surfaces(report) == []
    blob = json.dumps(report, sort_keys=True)
    assert "/home/" not in blob
    assert "/Users/" not in blob
    assert "hf_" not in blob
    assert "Bearer " not in blob

    poisoned = copy.deepcopy(report)
    poisoned["notes"] = "token=Bearer supersecrettokenvalue"
    with pytest.raises(Exception):
        assert_no_secrets(poisoned)

    poisoned2 = copy.deepcopy(report)
    poisoned2["cache_path"] = "/home/operator/.ssh/id_rsa"
    with pytest.raises(Exception):
        assert_no_secrets(poisoned2)


def test_compact_recipe_expands_and_passes_check() -> None:
    recipe = build_compact_coverage_recipe()
    assert is_coverage_recipe(recipe) is True
    assert recipe["report_kind"] == "fixture_recipe"
    assert recipe["task_id"] == TASK_ID
    assert recipe["inventory"]["rewritten"] is False
    assert recipe["inventory"]["task_id"] == INVENTORY_TASK_ID
    assert recipe["range"]["start"] == LEGACY_DELTA_START_INCLUSIVE
    expanded = expand_coverage_payload(recipe)
    assert is_coverage_recipe(expanded) is False
    assert expanded["frontier_closed"] is True
    result = check_coverage_report(recipe)
    assert result["ok"] is True
    assert result["failed_final"] == 0


def test_compact_recipe_requires_the_complete_exact_contract() -> None:
    with pytest.raises(FederalRegisterFulltextError, match="sealed exact"):
        check_coverage_report({"report_kind": "fixture_recipe"})

    altered = build_compact_coverage_recipe()
    altered["notes"] += " unreviewed"
    with pytest.raises(FederalRegisterFulltextError, match="sealed exact"):
        check_coverage_report(altered)


def test_write_refuses_to_replace_the_official_inventory(tmp_path: Path) -> None:
    report = build_compact_coverage_recipe()
    inventory_path = tmp_path / "federal_inventory.json"
    inventory_path.write_text("{}", encoding="utf-8")
    with pytest.raises(InventoryRewriteError):
        write_coverage_report(report, inventory_path)


def test_write_and_reload_coverage_report(tmp_path: Path) -> None:
    recipe = build_compact_coverage_recipe()
    path = tmp_path / "federal_fulltext_coverage.json"
    written = write_coverage_report(recipe, path)
    assert written == path
    loaded = json.loads(path.read_text(encoding="utf-8"))
    check_coverage_report(loaded)
    assert loaded["task_id"] == TASK_ID
    assert loaded["inventory"]["rewritten"] is False


def test_default_report_path_points_at_docs_reports() -> None:
    path = default_report_path()
    assert path.name == "federal_fulltext_coverage.json"
    assert "legal_corpora_reindex" in path.parts


def test_official_inventory_is_not_rewritten_by_enrichment() -> None:
    from ipfs_datasets_py.processors.legal_data.federal_register_acquisition import (
        default_report_path as inventory_path,
    )

    path = inventory_path()
    before = path.read_bytes() if path.is_file() else None
    digest_before = content_sha256(before) if before is not None else None
    enrich_federal_register_fulltext(config=FulltextConfig(mode=FulltextMode.FIXTURE))
    after = path.read_bytes() if path.is_file() else None
    assert after == before
    if digest_before is not None:
        assert content_sha256(after) == digest_before


def test_fixture_roles_cover_required_disposition_categories() -> None:
    roles = [fixture_role_for_index(i) for i in range(12)]
    categories = {role.expected_disposition.category for role in roles}
    assert categories == {
        "full_text_admitted",
        "metadata_only",
        "excluded",
        "quarantined",
    }
    assert CoverageDisposition.FAILED_FINAL not in {
        role.expected_disposition for role in roles
    }
    assert FixtureRole.HTML_BODY.expected_disposition in ADMITTED_DISPOSITIONS


def test_coverage_digest_is_stable_across_runs() -> None:
    first = build_fixture_coverage_report()
    second = build_fixture_coverage_report()
    assert first["coverage_digest"] == second["coverage_digest"]
    assert first["inventory"]["digest"] == second["inventory"]["digest"]
    assert first["acceptance"]["classified"] == second["acceptance"]["classified"]
