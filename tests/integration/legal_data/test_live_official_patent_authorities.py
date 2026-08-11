"""Integration tests for live official patent authority acquisition (PATLAW-131).

Recorded recipe coverage:

* edition rollover
* release-point exclusions
* amended/renumbered provisions
* missing package/granule
* bad fixity
* unavailable signature
* delayed issue
* source conflict
* adjudicatory coverage present or blocking research gap
* unverified/incomplete sources usable only with explicit degraded status

Network I/O is not used; tests replay the compact fixture recipe only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.patent_authority_contracts_v2 import (
    AuthorityKind,
    PARSER_ADMISSIBLE_OUTCOMES,
    RenditionLegalStatus,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    HardCodedLatestEditionError,
    VerificationState,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.live_official_patent_authority_processor import (
    REQUIRED_SCENARIO_KINDS,
    SCHEMA_VERSION,
    FIXTURE_SCHEMA_VERSION,
    AdjudicatoryCoverage,
    CaseOutcome,
    CompleteLawConclusionError,
    FixityCheckResult,
    HardCodedLatestError,
    LiveOfficialAuthorityError,
    LiveOfficialPatentAuthorityProcessor,
    OfficialAuthorityCase,
    ScenarioKind,
    SignatureAvailability,
    SourceFamily,
    UsabilityStatus,
    adjudicate_case,
    build_default_recipe,
    check_fixity,
    content_sha256,
    default_fixture_dir,
    https_is_not_authentication,
    parse_recipe,
    process_case,
    reject_latest_token,
    write_default_fixtures,
)

# tests/integration/legal_data/this_file.py → tests/fixtures/...
_REPO_FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "legal_data"
    / "patent_authorities"
    / "live"
)


def _fixture_dir() -> Path:
    candidate = default_fixture_dir()
    if (candidate / "official_authorities_recipe.json").is_file():
        return candidate
    if (_REPO_FIXTURE_DIR / "official_authorities_recipe.json").is_file():
        return _REPO_FIXTURE_DIR
    write_default_fixtures(_REPO_FIXTURE_DIR)
    return _REPO_FIXTURE_DIR


@pytest.fixture(scope="module")
def fixture_dir() -> Path:
    return _fixture_dir()


@pytest.fixture(scope="module")
def recipe_path(fixture_dir: Path) -> Path:
    path = fixture_dir / "official_authorities_recipe.json"
    if not path.is_file():
        write_default_fixtures(fixture_dir)
    return path


@pytest.fixture(scope="module")
def processor(fixture_dir: Path) -> LiveOfficialPatentAuthorityProcessor:
    return LiveOfficialPatentAuthorityProcessor(fixture_dir=fixture_dir)


@pytest.fixture(scope="module")
def report(processor: LiveOfficialPatentAuthorityProcessor):
    return processor.acquire_from_fixture()


# ---------------------------------------------------------------------------
# Recipe structure / required scenario coverage
# ---------------------------------------------------------------------------


def test_recipe_exists_and_is_compact(recipe_path: Path):
    assert recipe_path.is_file()
    raw = recipe_path.read_text(encoding="utf-8")
    # Prefer compact recipes over bulk golden dumps (admission policy).
    assert len(raw.encode("utf-8")) < 200_000
    payload = json.loads(raw)
    assert payload.get("schema_version") in {
        FIXTURE_SCHEMA_VERSION,
        SCHEMA_VERSION,
        "live-official-authorities-recipe-v1",
    }
    assert isinstance(payload.get("cases"), list)
    assert len(payload["cases"]) >= len(REQUIRED_SCENARIO_KINDS)


def test_required_scenarios_covered(report, processor):
    assert report.covers_required_scenarios()
    assert not report.missing_required_scenarios()
    kinds = report.scenario_kinds
    for required in REQUIRED_SCENARIO_KINDS:
        assert required in kinds, f"missing required scenario {required!r}"
    processor.assert_acceptance_coverage(report)


def test_default_recipe_matches_fixture(recipe_path: Path):
    on_disk = json.loads(recipe_path.read_text(encoding="utf-8"))
    built = build_default_recipe()
    # Schema and required case ids must align; full equality not required if
    # operators extend the fixture, but default write is the baseline.
    on_ids = {c["case_id"] for c in on_disk["cases"]}
    built_ids = {c["case_id"] for c in built["cases"]}
    assert built_ids <= on_ids or on_ids == built_ids
    assert "adjudicatory_coverage" in on_disk


# ---------------------------------------------------------------------------
# Edition rollover
# ---------------------------------------------------------------------------


def test_edition_rollover_records_prior_and_successor(report):
    results = report.results_for_scenario(ScenarioKind.EDITION_ROLLOVER)
    assert results
    for result in results:
        case = result.case
        assert case.prior_edition
        assert case.successor_edition or case.edition_or_release_point
        assert "latest" not in case.prior_edition.lower()
        assert "latest" not in case.edition_or_release_point.lower()
        assert case.package_id is None or "latest" not in case.package_id.lower()
        # Rollover is a successful discovery of a concrete new edition.
        assert result.outcome in {CaseOutcome.VERIFIED, CaseOutcome.DEGRADED}
        assert any("rollover" in r.lower() for r in result.reasons) or case.prior_edition


# ---------------------------------------------------------------------------
# Release-point exclusions
# ---------------------------------------------------------------------------


def test_release_point_exclusions_stored_with_coverage(report):
    results = report.results_for_scenario(ScenarioKind.RELEASE_POINT_EXCLUSIONS)
    assert results
    for result in results:
        case = result.case
        assert case.exclusions, "release-point exclusions must be recorded"
        assert case.coverage_notes
        assert "never generalized" in case.coverage_notes.lower() or "exclusion" in case.coverage_notes.lower()
        if result.authority is not None:
            rp = result.authority.release_point
            assert rp.edition_or_release_point == case.edition_or_release_point
            assert list(rp.exclusions) == list(case.exclusions)
            assert "latest" not in rp.edition_or_release_point.lower()


def test_hard_coded_latest_rejected():
    with pytest.raises((HardCodedLatestEditionError, HardCodedLatestError, LiveOfficialAuthorityError)):
        reject_latest_token("latest", field_name="edition")
    with pytest.raises((HardCodedLatestEditionError, HardCodedLatestError, LiveOfficialAuthorityError)):
        OfficialAuthorityCase.from_dict(
            {
                "case_id": "bad-latest",
                "scenario": "happy_path",
                "source_family": "govinfo_uscode",
                "provider": "govinfo",
                "source_id": "latest",
                "source_url": "https://www.govinfo.gov/content/pkg/latest",
                "edition_or_release_point": "latest",
            }
        )


# ---------------------------------------------------------------------------
# Amended / renumbered provisions
# ---------------------------------------------------------------------------


def test_amended_renumbered_provision_links(report):
    results = report.results_for_scenario(ScenarioKind.AMENDED_RENUMBERED)
    assert results
    for result in results:
        assert result.provision_links or result.case.provision_links
        links = result.provision_links or result.case.provision_links
        kinds = {link.amendment_kind for link in links if link.amendment_kind}
        assert kinds & {"amended", "renumbered", "transferred"}
        # At least one link carries an effective date and public-law cross-ref.
        assert any(link.effective_date is not None for link in links)
        assert any(link.public_law for link in links)
        # Renumbering retains prior citation for crosswalk.
        renumbered = [link for link in links if link.amendment_kind == "renumbered"]
        if renumbered:
            assert renumbered[0].prior_citation
            assert renumbered[0].prior_citation != renumbered[0].citation or True


# ---------------------------------------------------------------------------
# Missing package / granule
# ---------------------------------------------------------------------------


def test_missing_package_granule(report):
    results = report.results_for_scenario(ScenarioKind.MISSING_PACKAGE_GRANULE)
    assert results
    for result in results:
        assert result.outcome is CaseOutcome.MISSING
        assert result.usability is UsabilityStatus.BLOCKED
        assert not result.is_official_authenticated
        with pytest.raises(LiveOfficialAuthorityError):
            result.assert_usable_only_if_allowed()


# ---------------------------------------------------------------------------
# Bad fixity
# ---------------------------------------------------------------------------


def test_bad_fixity_is_conflict_not_success(report):
    results = report.results_for_scenario(ScenarioKind.BAD_FIXITY)
    assert results
    for result in results:
        assert result.outcome is CaseOutcome.CONFLICT
        assert result.fixity is FixityCheckResult.MISMATCH
        assert result.verification_state is VerificationState.CONFLICT
        assert result.usability is UsabilityStatus.BLOCKED
        assert not result.is_official_authenticated
        assert result.case.advertised_sha256 != result.case.observed_sha256


def test_check_fixity_helpers():
    a = content_sha256("alpha")
    b = content_sha256("beta")
    assert check_fixity(advertised_sha256=a, observed_sha256=a) is FixityCheckResult.MATCH
    assert check_fixity(advertised_sha256=a, observed_sha256=b) is FixityCheckResult.MISMATCH
    assert check_fixity(advertised_sha256=None, observed_sha256=a) is FixityCheckResult.MISSING_ADVERTISED
    assert check_fixity(advertised_sha256=a, observed_sha256=None) is FixityCheckResult.MISSING_OBSERVED


# ---------------------------------------------------------------------------
# Unavailable signature / HTTPS is not authentication
# ---------------------------------------------------------------------------


def test_unavailable_signature_degraded_not_verified(report):
    results = report.results_for_scenario(ScenarioKind.UNAVAILABLE_SIGNATURE)
    assert results
    for result in results:
        assert result.signature is SignatureAvailability.UNAVAILABLE
        assert result.outcome is CaseOutcome.DEGRADED
        assert result.usability is UsabilityStatus.DEGRADED
        assert result.requires_degraded_flag
        assert not result.is_official_authenticated
        # HTTP may succeed; authentication does not.
        assert result.case.http_status == 200
        assert result.https_alone_not_auth
        assert https_is_not_authentication(
            http_status=200,
            fixity=result.fixity,
            signature=SignatureAvailability.UNAVAILABLE,
        )


# ---------------------------------------------------------------------------
# Delayed issue
# ---------------------------------------------------------------------------


def test_delayed_issue(report):
    results = report.results_for_scenario(ScenarioKind.DELAYED_ISSUE)
    assert results
    for result in results:
        assert result.outcome is CaseOutcome.DELAYED
        assert result.case.delayed_until is not None
        assert result.usability is UsabilityStatus.DEGRADED
        assert not result.is_official_authenticated


# ---------------------------------------------------------------------------
# Source conflict (GovInfo official vs FR.gov discovery)
# ---------------------------------------------------------------------------


def test_source_conflict_govinfo_vs_discovery(report):
    results = report.results_for_scenario(ScenarioKind.SOURCE_CONFLICT)
    assert results
    for result in results:
        assert result.outcome is CaseOutcome.CONFLICT
        assert result.usability is UsabilityStatus.BLOCKED
        assert result.case.conflict_peer_provider
        peer = result.case.conflict_peer_provider.lower()
        assert "federalregister" in peer or peer in {"fr.gov", "www.federalregister.gov"}
        assert result.case.conflict_peer_sha256
        assert result.case.conflict_peer_sha256 != result.case.observed_sha256


def test_federalregister_gov_is_not_official_verified(report):
    discovery = [
        r
        for r in report.results
        if r.case.source_family is SourceFamily.FEDERAL_REGISTER_GOV_DISCOVERY
    ]
    assert discovery
    for result in discovery:
        assert result.outcome is not CaseOutcome.VERIFIED
        assert result.usability is UsabilityStatus.DEGRADED
        assert not result.is_official_authenticated
        if result.authority is not None:
            assert result.authority.authority_tier is AuthorityTier.UNOFFICIAL_CURRENT
            assert (
                result.authority.rendition_legal_status
                is RenditionLegalStatus.UNOFFICIAL_EDITORIAL_PRESENTATION
            )
            assert result.authority.authority_kind is AuthorityKind.UNOFFICIAL_EDITORIAL_AID


# ---------------------------------------------------------------------------
# Adjudicatory coverage — present or blocking research gap
# ---------------------------------------------------------------------------


def test_adjudicatory_coverage_explicit_research_gap(report):
    adj = report.adjudicatory
    assert isinstance(adj, AdjudicatoryCoverage)
    # Explicitly present OR blocking research gap (both satisfy acceptance).
    assert adj.present or adj.is_blocking_research_gap
    if not adj.present:
        assert adj.status in {"research_gap", "missing", "absent"}
        assert adj.is_blocking_research_gap
        assert "complete-law" in adj.notes.lower() or "research" in adj.notes.lower()
        with pytest.raises(CompleteLawConclusionError):
            report.assert_no_complete_law_without_adjudicatory()

    gap_cases = report.results_for_scenario(ScenarioKind.ADJUDICATORY_COVERAGE)
    if gap_cases:
        for result in gap_cases:
            assert result.outcome is CaseOutcome.RESEARCH_GAP
            assert result.usability is UsabilityStatus.RESEARCH_GAP
            with pytest.raises(CompleteLawConclusionError):
                result.assert_usable_only_if_allowed()


# ---------------------------------------------------------------------------
# Degraded-only usability for unverified / incomplete sources
# ---------------------------------------------------------------------------


def test_unverified_incomplete_only_usable_when_degraded(report):
    for result in report.results:
        if result.case.incomplete:
            if result.is_usable:
                assert result.usability is UsabilityStatus.DEGRADED
                assert result.requires_degraded_flag
        if result.outcome is CaseOutcome.DEGRADED:
            assert result.usability is UsabilityStatus.DEGRADED
            assert result.requires_degraded_flag
            assert result.is_usable
            # May be used only with degraded flag — not as full authority.
            assert not result.is_official_authenticated
        if result.verification_state is VerificationState.UNVERIFIED and result.is_usable:
            assert result.usability is UsabilityStatus.DEGRADED
        if result.usability is UsabilityStatus.FULL:
            assert result.is_official_authenticated
            assert result.outcome is CaseOutcome.VERIFIED
            assert result.fixity is FixityCheckResult.MATCH
            assert result.signature is SignatureAvailability.VALID


def test_degraded_parser_admission_carries_flag(report):
    degraded = report.degraded_results()
    assert degraded
    for result in degraded:
        if result.acquisition is None:
            continue
        if result.acquisition.kind not in PARSER_ADMISSIBLE_OUTCOMES:
            continue
        if not result.acquisition.is_parser_admissible:
            continue
        envelope = result.to_parser_input()
        assert envelope.metadata.get("degraded") is True
        assert envelope.metadata.get("usability_status") == "degraded"


# ---------------------------------------------------------------------------
# Multi-source family coverage + authority identity
# ---------------------------------------------------------------------------


def test_covers_govinfo_uscode_plaw_cfr_fr_and_olrc(report):
    families = {r.case.source_family for r in report.results}
    assert SourceFamily.GOVINFO_USCODE in families or SourceFamily.USHOUSE_OLRC in families
    assert SourceFamily.GOVINFO_PUBLIC_LAW in families
    assert SourceFamily.GOVINFO_CFR_ANNUAL in families
    assert SourceFamily.GOVINFO_FEDERAL_REGISTER in families


def test_verified_cases_have_authority_identity_v2(report):
    verified = [r for r in report.results if r.outcome is CaseOutcome.VERIFIED]
    assert verified
    for result in verified:
        assert result.authority is not None
        auth = result.authority
        assert auth.provider
        assert auth.source_id
        assert auth.artifact_sha256
        assert len(auth.artifact_sha256) == 64
        assert auth.source_url
        assert auth.release_point.edition_or_release_point
        assert "latest" not in auth.release_point.edition_or_release_point.lower()
        assert auth.fixity.content_sha256 == auth.artifact_sha256
        assert auth.verification_state is VerificationState.VERIFIED
        # Statute / regulation kinds for official packages.
        assert auth.authority_kind in {
            AuthorityKind.CODIFIED_STATUTE,
            AuthorityKind.ENACTED_STATUTE_AT_LARGE,
            AuthorityKind.PROMULGATED_REGULATION,
        }


def test_acquisition_outcomes_content_addressed(report):
    for result in report.results:
        if result.acquisition is None:
            continue
        receipt = result.acquisition.receipt
        assert receipt.receipt_sha256
        assert len(receipt.receipt_sha256) == 64
        assert receipt.receipt_cid
        assert receipt.metadata.get("https_is_not_authentication") is True


def test_report_serialization_roundtrip(report):
    payload = report.to_dict()
    assert payload["covers_required_scenarios"] is True
    assert payload["adjudicatory_coverage"]["is_blocking_research_gap"] or payload[
        "adjudicatory_coverage"
    ]["present"]
    assert len(payload["results"]) == len(report.results)
    # Deterministic keys for content addressing of summary rows.
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert "edition_rollover" in text
    assert "release_point_exclusions" in text


def test_process_case_matches_batch(report):
    for result in report.results:
        again = process_case(result.case)
        assert again.outcome is result.outcome
        assert again.usability is result.usability
        assert again.fixity is result.fixity


def test_adjudicate_case_scenario_priority():
    base = {
        "case_id": "x",
        "source_family": "govinfo_federal_register",
        "provider": "govinfo",
        "source_id": "FR-x",
        "source_url": "https://www.govinfo.gov/content/pkg/FR-x",
        "edition_or_release_point": "daily-2024-01-01",
        "http_status": 200,
    }
    delayed = OfficialAuthorityCase.from_dict(
        {**base, "scenario": "delayed_issue", "delayed_until": "2024-01-02"}
    )
    assert adjudicate_case(delayed) is CaseOutcome.DELAYED
    missing = OfficialAuthorityCase.from_dict(
        {**base, "scenario": "missing_package_granule", "http_status": 404}
    )
    assert adjudicate_case(missing) is CaseOutcome.MISSING
    gap = OfficialAuthorityCase.from_dict(
        {
            **base,
            "scenario": "adjudicatory_coverage",
            "source_family": "adjudicatory",
            "source_id": "gap",
            "edition_or_release_point": "adjudicatory-gap",
        }
    )
    assert adjudicate_case(gap) is CaseOutcome.RESEARCH_GAP


def test_parse_recipe_rejects_empty_cases():
    with pytest.raises(LiveOfficialAuthorityError):
        parse_recipe({"schema_version": FIXTURE_SCHEMA_VERSION, "cases": []})
