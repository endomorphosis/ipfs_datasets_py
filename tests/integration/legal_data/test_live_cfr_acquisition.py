"""Integration tests: live eCFR + annual CFR authority acquisition (PATLAW-128).

Recorded integration covers:

* pagination
* point-in-time lookup
* annual edition rollover
* changed / removed sections
* missing granules
* conflicting text

Every provision carries source CID, source span, effective interval, and
**separate** authority / authentication status.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    IdentityRole,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.live_cfr_source_processor import (
    FIXTURE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    AuthenticationStatus,
    AuthorityStatus,
    EffectiveInterval,
    EditionDiscovery,
    LiveCfrAcquisitionReport,
    LiveCfrProvision,
    LiveCfrSourceProcessor,
    ProvisionChangeKind,
    SnapshotCaseKind,
    admit_recorded_bytes,
    build_live_cfr_recipe,
    build_recorded_acquisition_outcome,
    default_fixture_dir,
    source_cid_for_sha256,
    write_default_fixtures,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_contracts_v2 import (
    AcquisitionOutcomeKind,
    MissingAcquisitionOutcomeError,
)


# tests/integration/legal_data/this_file.py → parents[2] == tests/
_REPO_FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "legal_data"
    / "patent_authorities"
    / "live"
)


def _fixture_dir() -> Path:
    candidate = default_fixture_dir()
    if (candidate / "cfr_recipe.json").is_file():
        return candidate
    if (_REPO_FIXTURE_DIR / "cfr_recipe.json").is_file():
        return _REPO_FIXTURE_DIR
    write_default_fixtures(_REPO_FIXTURE_DIR)
    return _REPO_FIXTURE_DIR


@pytest.fixture(scope="module")
def fixture_dir() -> Path:
    return _fixture_dir()


@pytest.fixture(scope="module")
def processor(fixture_dir: Path) -> LiveCfrSourceProcessor:
    return LiveCfrSourceProcessor(fixture_dir=fixture_dir)


@pytest.fixture(scope="module")
def report(processor: LiveCfrSourceProcessor) -> LiveCfrAcquisitionReport:
    return processor.acquire_from_recipe()


@pytest.fixture(scope="module")
def recipe(fixture_dir: Path) -> dict:
    path = fixture_dir / "cfr_recipe.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# Recipe compactness and schema
# ---------------------------------------------------------------------------


def test_recipe_is_compact_versioned_and_covers_required_cases(recipe: dict):
    assert recipe["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert recipe["fixture_id"] == "live-cfr-title37-acquisition"
    assert recipe["title"] == "37"
    cases = recipe["cases"]
    for kind in SnapshotCaseKind:
        assert kind.value in cases, f"missing case {kind.value}"
    expected = recipe["expected"]
    assert set(expected["required_cases"]) == {k.value for k in SnapshotCaseKind}
    # Compact recipe: cases + catalog + nested snapshots — not bulk golden dumps
    # of full per-case envelopes with duplicated parser output.
    assert "edition_catalog" in recipe
    assert "latest_editions" in recipe["edition_catalog"]
    for disc in recipe["edition_catalog"]["latest_editions"]:
        assert "latest" not in str(disc.get("package_id", "")).lower()
        assert "latest" not in str(disc.get("edition", "")).lower()
        assert "latest" not in str(disc.get("year", "")).lower()


def test_report_status_and_case_coverage(report: LiveCfrAcquisitionReport):
    assert report.schema_version == SCHEMA_VERSION
    assert report.title == "37"
    # Overall reflects conflict from conflicting_text case.
    assert report.status in {"conflict", "inconclusive", "partial", "resolved"}
    assert set(report.cases) == {k.value for k in SnapshotCaseKind}
    assert len(report.provisions) >= 1
    assert report.discoveries


# ---------------------------------------------------------------------------
# Every provision: source CID / span / effective interval + dual status
# ---------------------------------------------------------------------------


def test_every_provision_has_source_cid_span_interval_and_dual_status(
    report: LiveCfrAcquisitionReport,
):
    assert report.provisions
    for prov in report.provisions:
        assert isinstance(prov, LiveCfrProvision)
        assert prov.source_cid
        assert prov.source_cid.startswith("baf") or prov.source_cid.startswith("sha256:")
        assert prov.source_span is not None
        assert isinstance(prov.source_span.start, int)
        assert isinstance(prov.source_span.end, int)
        assert prov.source_span.end >= prov.source_span.start
        assert isinstance(prov.effective_interval, EffectiveInterval)
        assert isinstance(prov.authority_status, AuthorityStatus)
        assert isinstance(prov.authentication_status, AuthenticationStatus)
        # Fields are independently populated (not collapsed into one tier field).
        payload = prov.to_dict()
        assert "authority_status" in payload
        assert "authentication_status" in payload
        assert payload["authority_status"] != payload.get("authority_tier")
        assert "source_cid" in payload
        assert "source_span" in payload
        assert "effective_interval" in payload


def test_authority_and_authentication_remain_independent(
    report: LiveCfrAcquisitionReport,
):
    """eCFR provisions are unofficial with not_applicable auth; annual verified."""

    ecfr_like = [
        p
        for p in report.provisions
        if p.authority_status is AuthorityStatus.UNOFFICIAL_CURRENT
    ]
    official = [
        p
        for p in report.provisions
        if p.authority_status is AuthorityStatus.OFFICIAL_BASE
        and p.authentication_status is AuthenticationStatus.VERIFIED
    ]
    assert ecfr_like, "expected at least one unofficial eCFR provision"
    for p in ecfr_like:
        # eCFR editorial text is never authenticated annual print.
        assert p.authentication_status in {
            AuthenticationStatus.NOT_APPLICABLE,
            AuthenticationStatus.UNVERIFIED,
        }
        assert p.provider == "ecfr"
    assert official, "expected at least one official verified annual provision"
    for p in official:
        assert p.provider == "govinfo"
        assert p.package_id
        assert "latest" not in p.package_id.lower()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_pagination_case(report: LiveCfrAcquisitionReport, recipe: dict):
    case = report.get_case(SnapshotCaseKind.PAGINATION)
    assert case.status == "resolved"
    assert len(case.pagination_pages) == 2
    assert case.pagination_pages[0].page == 1
    assert case.pagination_pages[0].next_page_token == "page-2"
    assert case.pagination_pages[1].page == 2
    assert case.pagination_pages[1].next_page_token is None
    assert case.metadata["item_count"] == recipe["expected"]["pagination_item_count"]
    assert case.metadata["page_count"] == 2
    # Acquisition outcomes carry pagination metadata and are parser-admissible.
    assert case.acquisition_outcomes
    for outcome in case.acquisition_outcomes:
        assert outcome["kind"] == AcquisitionOutcomeKind.FETCHED.value
        assert outcome["receipt"]["content"] is not None
        assert "pagination" in outcome["receipt"]
    # Provisions discovered via pagination retain provenance.
    assert len(case.provisions) == 5
    sections = {p.section for p in case.provisions}
    assert sections == {"1.56", "1.97", "1.98", "41.50", "42.100"}


def test_pagination_cycle_rejected(processor: LiveCfrSourceProcessor):
    with pytest.raises(Exception, match="pagination cycle|page must"):
        processor.replay_pagination(
            [
                {
                    "page": 1,
                    "page_size": 10,
                    "items": ["1.56"],
                    "next_page_token": "tok-a",
                    "total_items": 20,
                },
                {
                    "page": 2,
                    "page_size": 10,
                    "items": ["1.97"],
                    "next_page_token": "tok-a",  # cycle
                    "total_items": 20,
                },
            ]
        )


# ---------------------------------------------------------------------------
# Point-in-time lookup
# ---------------------------------------------------------------------------


def test_point_in_time_lookup(report: LiveCfrAcquisitionReport, recipe: dict):
    case = report.get_case(SnapshotCaseKind.POINT_IN_TIME)
    assert case.status == "resolved"
    assert case.as_of == date(2020, 1, 1)
    assert case.as_of.isoformat() == recipe["expected"]["point_in_time_as_of"]
    assert case.metadata["up_to_date_as_of"] == "2020-01-01"
    assert case.metadata["version_id"] == "ecfr-title-37-as-of-2020-01-01"
    assert "latest" not in (case.metadata["version_id"] or "").lower()
    assert case.provisions
    for prov in case.provisions:
        assert prov.authority_status is AuthorityStatus.UNOFFICIAL_CURRENT
        assert prov.authentication_status is AuthenticationStatus.NOT_APPLICABLE
        assert prov.version_id == "ecfr-title-37-as-of-2020-01-01"
        assert prov.metadata.get("is_current_snapshot") is False
        assert prov.metadata.get("point_in_time_as_of") == "2020-01-01"
        assert prov.source_cid
        assert prov.source_span is not None


def test_point_in_time_rejects_hard_coded_latest(processor: LiveCfrSourceProcessor):
    from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
        HardCodedLatestEditionError,
    )

    with pytest.raises(HardCodedLatestEditionError):
        # Force latest through discover path / edition field.
        EditionDiscovery(
            package_id="latest",
            year="2024",
        )


# ---------------------------------------------------------------------------
# Annual edition rollover
# ---------------------------------------------------------------------------


def test_annual_edition_rollover(report: LiveCfrAcquisitionReport, recipe: dict):
    case = report.get_case(SnapshotCaseKind.ANNUAL_EDITION_ROLLOVER)
    assert case.status == "resolved"
    assert case.as_of == date(2024, 8, 1)
    assert (
        case.metadata["selected_package_id"]
        == recipe["expected"]["rollover_selected_package_id"]
    )
    assert case.metadata["selected_year"] == "2024"
    assert case.metadata["prior_year"] == "2023"
    assert case.metadata["prior_package_id"] == "CFR-2023-title37"
    # Discoveries are concrete.
    years = {d.year for d in case.discoveries}
    assert years == {"2023", "2024"}
    for disc in case.discoveries:
        assert "latest" not in disc.package_id.lower()
        assert "latest" not in (disc.edition or "").lower()
    # Selected edition provisions are official-base with verified auth.
    selected = [
        p
        for p in case.provisions
        if p.package_id == "CFR-2024-title37"
        and p.authority_status is AuthorityStatus.OFFICIAL_BASE
    ]
    assert selected
    for p in selected:
        assert p.authentication_status is AuthenticationStatus.VERIFIED
        assert p.effective_interval.start is not None
    # Prior edition provisions have closed intervals at 2024-07-01.
    prior = [p for p in case.provisions if p.package_id == "CFR-2023-title37"]
    assert prior
    for p in prior:
        assert p.effective_interval.end == date(2024, 7, 1)


def test_select_edition_for_as_of_before_and_after_rollover(
    processor: LiveCfrSourceProcessor, report: LiveCfrAcquisitionReport
):
    discoveries = list(report.discoveries)
    early = processor.select_edition_for_as_of(date(2023, 8, 1), discoveries)
    assert early.package_id == "CFR-2023-title37"
    late = processor.select_edition_for_as_of(date(2024, 8, 1), discoveries)
    assert late.package_id == "CFR-2024-title37"


# ---------------------------------------------------------------------------
# Changed / removed sections
# ---------------------------------------------------------------------------


def test_changed_and_removed_sections(report: LiveCfrAcquisitionReport, recipe: dict):
    case = report.get_case(SnapshotCaseKind.CHANGED_REMOVED_SECTIONS)
    assert case.status == "resolved"
    by_section = {p.section: p for p in case.provisions}
    changed_sec = recipe["expected"]["changed_section"]
    removed_sec = recipe["expected"]["removed_section"]
    assert changed_sec in by_section
    assert removed_sec in by_section
    assert by_section[changed_sec].change_kind is ProvisionChangeKind.CHANGED
    assert by_section[removed_sec].change_kind is ProvisionChangeKind.REMOVED
    assert by_section[removed_sec].authority_status is AuthorityStatus.REMOVED
    # Added section 1.98 present.
    assert "1.98" in by_section
    assert by_section["1.98"].change_kind is ProvisionChangeKind.ADDED
    # Unchanged 1.97 may be present.
    if "1.97" in by_section:
        assert by_section["1.97"].change_kind is ProvisionChangeKind.UNCHANGED
    assert case.metadata["changed"] >= 1
    assert case.metadata["removed"] >= 1
    assert case.metadata["added"] >= 1
    for p in case.provisions:
        assert p.source_cid
        assert p.source_span is not None
        assert p.effective_interval is not None
        assert p.authority_status is not None
        assert p.authentication_status is not None


# ---------------------------------------------------------------------------
# Missing granules
# ---------------------------------------------------------------------------


def test_missing_granules_yield_inconclusive(report: LiveCfrAcquisitionReport):
    case = report.get_case(SnapshotCaseKind.MISSING_GRANULES)
    assert case.status == "inconclusive"
    assert case.missing_granules
    assert any("41-50" in g or "41.50" in g for g in case.missing_granules)
    missing_provisions = [
        p
        for p in case.provisions
        if p.authentication_status is AuthenticationStatus.MISSING_GRANULE
    ]
    assert missing_provisions
    for p in missing_provisions:
        assert p.change_kind is ProvisionChangeKind.MISSING
        # Missing granule is not treated as success/verified.
        assert p.authentication_status is not AuthenticationStatus.VERIFIED
        assert p.source_cid
        assert p.source_span is not None
        # Authority stays unknown or official base only when partial text exists;
        # authentication is independently missing_granule.
        assert p.authentication_status is AuthenticationStatus.MISSING_GRANULE


# ---------------------------------------------------------------------------
# Conflicting text
# ---------------------------------------------------------------------------


def test_conflicting_text_ecfr_vs_annual(report: LiveCfrAcquisitionReport, recipe: dict):
    case = report.get_case(SnapshotCaseKind.CONFLICTING_TEXT)
    assert case.status == "conflict"
    assert case.conflicts
    conflict_sec = recipe["expected"]["conflict_section"]
    assert any(c.section == conflict_sec for c in case.conflicts)
    conflict = next(c for c in case.conflicts if c.section == conflict_sec)
    assert conflict.ecfr_excerpt
    assert conflict.annual_excerpt
    assert conflict.ecfr_source_cid
    assert conflict.annual_source_cid
    assert conflict.ecfr_source_cid != conflict.annual_source_cid

    # Dual provisions: official annual with conflict auth; eCFR unofficial.
    annual_conflict = [
        p
        for p in case.provisions
        if p.section == conflict_sec
        and p.authority_status is AuthorityStatus.OFFICIAL_BASE
        and p.authentication_status is AuthenticationStatus.CONFLICT
    ]
    ecfr_conflict = [
        p
        for p in case.provisions
        if p.section == conflict_sec
        and p.authority_status is AuthorityStatus.UNOFFICIAL_CURRENT
    ]
    assert annual_conflict
    assert ecfr_conflict
    # eCFR never becomes authenticated annual print.
    for p in ecfr_conflict:
        assert p.authentication_status is AuthenticationStatus.NOT_APPLICABLE
        assert p.provider == "ecfr"
        assert "unofficial" in str(p.metadata.get("presentation_label", "")).lower()


# ---------------------------------------------------------------------------
# Recorded bytes feed existing parsers via acquisition outcome gate
# ---------------------------------------------------------------------------


def test_recorded_bytes_require_acquisition_outcome():
    body = json.dumps({"page": 1, "items": ["1.56"]})
    envelope = admit_recorded_bytes(
        endpoint="https://www.ecfr.gov/api/versioner/v1/structure/2024-07-01/title-37.json",
        body=body,
        parser_name="ecfr_structure_page",
        page_index=1,
    )
    assert envelope.body is not None
    assert envelope.acquisition.kind is AcquisitionOutcomeKind.FETCHED
    assert envelope.acquisition.receipt.content is not None
    assert envelope.parser_name == "ecfr_structure_page"

    with pytest.raises(MissingAcquisitionOutcomeError):
        from ipfs_datasets_py.processors.legal_data.patent_authority_contracts_v2 import (
            ParserInputEnvelope,
        )

        ParserInputEnvelope.admit(None)  # type: ignore[arg-type]


def test_ecfr_not_impersonating_official_annual(report: LiveCfrAcquisitionReport):
    for prov in report.provisions:
        if prov.provider == "ecfr":
            assert prov.authority_status is not AuthorityStatus.OFFICIAL_BASE
            assert prov.authentication_status is not AuthenticationStatus.VERIFIED
        if prov.authority_status is AuthorityStatus.OFFICIAL_BASE:
            assert prov.provider == "govinfo"
            assert prov.package_id is not None
            assert prov.package_id.startswith("CFR-")


def test_canonical_report_roundtrip(report: LiveCfrAcquisitionReport):
    first = report.to_canonical_json()
    payload = json.loads(first)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert list(payload.keys()) == sorted(payload.keys())
    # Cases keys sorted in serialization via to_dict.
    assert list(payload["cases"].keys()) == sorted(payload["cases"].keys())


def test_build_recipe_generator_matches_on_disk(fixture_dir: Path):
    generated = build_live_cfr_recipe()
    on_disk = json.loads((fixture_dir / "cfr_recipe.json").read_text(encoding="utf-8"))
    assert generated["schema_version"] == on_disk["schema_version"]
    assert generated["fixture_id"] == on_disk["fixture_id"]
    assert set(generated["cases"]) == set(on_disk["cases"])
    assert set(generated["expected"]["required_cases"]) == set(
        on_disk["expected"]["required_cases"]
    )


def test_source_cid_stable_for_digest():
    digest = "a" * 64
    cid1 = source_cid_for_sha256(digest)
    cid2 = source_cid_for_sha256(digest)
    assert cid1 == cid2
    assert cid1.startswith("baf")


def test_live_fetch_without_transport_fails_closed(processor: LiveCfrSourceProcessor):
    from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.live_cfr_source_processor import (
        LiveCfrError,
    )

    with pytest.raises(LiveCfrError, match="PatentSourceTransport"):
        processor.fetch_live(
            "https://www.ecfr.gov/api/versioner/v1/structure/2024-07-01/title-37.json",
            parser_name="ecfr_structure",
        )
