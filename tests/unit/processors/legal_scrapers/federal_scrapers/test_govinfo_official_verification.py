"""Unit tests for GovInfo official verification and Public Law manifests (PATLAW-018).

Acceptance:

* Latest editions are discovered at runtime (concrete package/edition ids).
* Every examined Public Law remains in the manifest even when not patent-relevant.
* House/eCFR/FederalRegister.gov data stays cross-check-only.
* Digital authentication and printed-volume attestation are separate channels.
* Missing volumes/granules/signatures or text conflicts yield
  conflict/inconclusive/unverified rather than success.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    HardCodedLatestEditionError,
    IdentityRole,
    VerificationState,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.govinfo_client import (
    SignatureResult,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.govinfo_official_verifier import (
    FIXTURE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    DigitalAuthenticationEvidence,
    EditionDiscovery,
    FixityResult,
    FixtureSchemaError,
    FormatFixityCheck,
    GovInfoOfficialVerifier,
    HardCodedLatestError,
    InventoryKind,
    InventoryUnit,
    OfficialVerificationReport,
    PrintAttestationResult,
    PrintedVolumeAttestation,
    TextConflictFinding,
    UnitVerificationResult,
    VerificationOutcome,
    build_govinfo_official_inventory_recipe,
    check_format_fixity,
    content_sha256,
    default_fixture_dir,
    digital_and_print_are_separate,
    discover_latest_editions_from_catalog,
    govinfo_cfr_package_id,
    govinfo_uscode_package_id,
    normalize_package_id,
    normalize_year,
    outcome_to_verification_state,
    write_default_fixtures,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.public_law_change_processor import (
    CrossCheckMasqueradeError,
    CrossCheckRole,
    CrossCheckView,
    PublicLawChangeProcessor,
    PublicLawManifest,
    PublicLawRecord,
    ResolutionStatus as PlResolutionStatus,
    assert_cross_check_only,
    build_public_laws_fixture_recipe,
    classify_patent_relevance,
    default_fixture_dir as pl_default_fixture_dir,
    govinfo_plaw_package_id,
    parse_public_law_number,
    stable_public_law_identity,
    write_default_fixtures as write_pl_fixtures,
)

# tests/unit/processors/legal_scrapers/federal_scrapers/this_file.py
# parents[4] == tests/
_REPO_FIXTURE_DIR = (
    Path(__file__).resolve().parents[4]
    / "fixtures"
    / "legal_data"
    / "patent_authorities"
    / "public_laws"
)


def _fixture_dir() -> Path:
    candidate = default_fixture_dir()
    if (candidate / "govinfo_official_inventory_recipe.json").is_file():
        return candidate
    if (_REPO_FIXTURE_DIR / "govinfo_official_inventory_recipe.json").is_file():
        return _REPO_FIXTURE_DIR
    write_default_fixtures(_REPO_FIXTURE_DIR)
    return _REPO_FIXTURE_DIR


@pytest.fixture(scope="module")
def fixture_dir() -> Path:
    return _fixture_dir()


@pytest.fixture
def verifier(fixture_dir: Path) -> GovInfoOfficialVerifier:
    return GovInfoOfficialVerifier(fixture_dir=fixture_dir)


@pytest.fixture
def pl_processor(fixture_dir: Path) -> PublicLawChangeProcessor:
    return PublicLawChangeProcessor(fixture_dir=fixture_dir)


@pytest.fixture
def report(verifier: GovInfoOfficialVerifier) -> OfficialVerificationReport:
    return verifier.verify_from_fixture()


@pytest.fixture
def pl_acquisition(pl_processor: PublicLawChangeProcessor):
    return pl_processor.acquire_from_fixture()


# ---------------------------------------------------------------------------
# Latest editions discovered at runtime
# ---------------------------------------------------------------------------


def test_latest_editions_discovered_at_runtime(verifier: GovInfoOfficialVerifier):
    discoveries = verifier.discover_latest_editions()
    assert discoveries
    for disc in discoveries:
        assert isinstance(disc, EditionDiscovery)
        assert disc.package_id
        assert disc.edition
        assert "latest" not in disc.package_id.lower()
        assert "latest" not in disc.edition.lower()
        if disc.year is not None:
            assert "latest" not in disc.year.lower()
            assert disc.year.isdigit()


def test_discovered_editions_are_concrete_not_token(report: OfficialVerificationReport):
    assert report.discoveries
    collections = {d.collection for d in report.discoveries}
    assert "CFR" in collections
    assert "USCODE" in collections
    # Title 37 CFR package is concrete.
    cfr = next(d for d in report.discoveries if d.collection == "CFR")
    assert cfr.title == "37"
    assert cfr.package_id.startswith("CFR-")
    assert "title37" in cfr.package_id.lower()
    # Title 35 US Code package is concrete.
    usc = next(d for d in report.discoveries if d.collection == "USCODE")
    assert usc.title == "35"
    assert usc.package_id.startswith("USCODE-")


def test_hard_coded_latest_rejected_in_discovery():
    with pytest.raises((HardCodedLatestEditionError, HardCodedLatestError)):
        discover_latest_editions_from_catalog(
            {
                "latest_editions": [
                    {
                        "collection": "CFR",
                        "title": "37",
                        "package_id": "latest",
                        "edition": "latest",
                    }
                ]
            }
        )
    with pytest.raises((HardCodedLatestEditionError, HardCodedLatestError)):
        normalize_package_id("latest")
    with pytest.raises((HardCodedLatestEditionError, HardCodedLatestError)):
        normalize_year("latest")
    with pytest.raises((HardCodedLatestEditionError, HardCodedLatestError)):
        govinfo_cfr_package_id(year="latest", title="37")


def test_inventory_covers_title37_title35_plaw_and_fr(report: OfficialVerificationReport):
    kinds = {r.unit.kind for r in report.unit_results}
    assert InventoryKind.CFR_VOLUME in kinds
    assert InventoryKind.USCODE_EDITION in kinds
    assert InventoryKind.PUBLIC_LAW in kinds
    assert (
        InventoryKind.FR_DAILY_PACKAGE in kinds or InventoryKind.FR_GRANULE in kinds
    )
    # At least one Title 37 volume and one Title 35 edition in inventory.
    assert any(
        r.unit.kind is InventoryKind.CFR_VOLUME and r.unit.title == "37"
        for r in report.unit_results
    )
    assert any(
        r.unit.kind is InventoryKind.USCODE_EDITION and r.unit.title == "35"
        for r in report.unit_results
    )


# ---------------------------------------------------------------------------
# Public Law full examination manifest
# ---------------------------------------------------------------------------


def test_every_examined_public_law_remains_in_manifest(pl_acquisition):
    manifest = pl_acquisition.manifest
    assert isinstance(manifest, PublicLawManifest)
    assert manifest.total_examined >= 4
    assert manifest.patent_relevant_count >= 1
    assert manifest.non_patent_count >= 1
    # Non-patent laws are present (not filtered out).
    non_patent = pl_acquisition.list_non_patent()
    assert non_patent
    for law in non_patent:
        assert law.patent_relevant is False
        assert law.stable_id in manifest.examined
        assert law.package_id in manifest.all_package_ids()


def test_patent_relevant_and_non_patent_both_listed(pl_acquisition):
    all_laws = pl_acquisition.list_all()
    relevant = pl_acquisition.list_patent_relevant()
    non = pl_acquisition.list_non_patent()
    assert len(relevant) + len(non) == len(all_laws)
    assert {r.stable_id for r in relevant} | {r.stable_id for r in non} == {
        r.stable_id for r in all_laws
    }
    # Infrastructure IIJA must be retained despite non-patent.
    infra = pl_acquisition.manifest.get("Pub. L. 117-58")
    assert infra.patent_relevant is False
    assert "Infrastructure" in infra.title


def test_public_law_authority_is_official_change(pl_acquisition):
    for auth in pl_acquisition.authority_sources:
        assert auth.authority_tier is AuthorityTier.OFFICIAL_CHANGE
        assert auth.collection == "PLAW"
        if auth.official_artifact is not None:
            assert auth.official_artifact.role is IdentityRole.OFFICIAL_ARTIFACT
            assert auth.official_artifact.provider == "govinfo"


def test_public_law_manifest_in_verification_report(report: OfficialVerificationReport):
    assert report.public_law_manifest is not None
    man = report.public_law_manifest
    assert man.total_examined >= 4
    assert man.non_patent_count >= 1
    # Every examined PL still present after verification.
    for sid, law in man.examined.items():
        assert law.stable_id == sid
        assert isinstance(law.patent_relevant, bool)


def test_examine_public_laws_runtime_retains_non_patent(pl_processor: PublicLawChangeProcessor):
    laws = [
        {
            "congress": "118",
            "law_number": "1",
            "title": "A non-patent ceremonial law",
            "patent_relevant": False,
            "formats": {
                "pdf": {
                    "format": "pdf",
                    "artifact_sha256": content_sha256("pl118-1|pdf"),
                    "source_url": "https://www.govinfo.gov/content/pkg/PLAW-118publ1/pdf/PLAW-118publ1.pdf",
                }
            },
        },
        {
            "congress": "118",
            "law_number": "2",
            "title": "A patent fee adjustment",
            "patent_relevant": True,
            "affects_titles": ["35"],
            "formats": {
                "pdf": {
                    "format": "pdf",
                    "artifact_sha256": content_sha256("pl118-2|pdf"),
                    "source_url": "https://www.govinfo.gov/content/pkg/PLAW-118publ2/pdf/PLAW-118publ2.pdf",
                }
            },
        },
    ]
    acq = pl_processor.examine_public_laws(laws, inventory_source="runtime-test-inventory")
    assert acq.manifest.total_examined == 2
    assert acq.manifest.non_patent_count == 1
    assert acq.manifest.patent_relevant_count == 1
    assert "latest" not in (acq.manifest.inventory_source or "").lower()


# ---------------------------------------------------------------------------
# Cross-check-only: House / eCFR / FederalRegister.gov
# ---------------------------------------------------------------------------


def test_house_ecfr_frgov_are_cross_check_only(pl_acquisition):
    found_cross = False
    for law in pl_acquisition.list_all():
        for cc in law.cross_checks:
            found_cross = True
            assert cc.is_official is False
            assert cc.role is not CrossCheckRole.NONE
            if cc.derived_presentation is not None:
                assert cc.derived_presentation.role is IdentityRole.DERIVED_PRESENTATION
                assert cc.derived_presentation.provider.lower() in {
                    "ushouse",
                    "federalregister.gov",
                    "ecfr",
                    "www.ecfr.gov",
                    "www.federalregister.gov",
                    "uscode.house.gov",
                }
    assert found_cross, "fixture should include at least one cross-check view"


def test_cross_check_cannot_masquerade_as_official():
    with pytest.raises(CrossCheckMasqueradeError):
        assert_cross_check_only(
            provider="ecfr",
            role=IdentityRole.OFFICIAL_ARTIFACT,
            authority_tier=AuthorityTier.OFFICIAL_BASE,
        )
    with pytest.raises(CrossCheckMasqueradeError):
        assert_cross_check_only(
            provider="federalregister.gov",
            role=IdentityRole.OFFICIAL_ARTIFACT,
            authority_tier=AuthorityTier.OFFICIAL_CHANGE,
        )
    with pytest.raises(CrossCheckMasqueradeError):
        CrossCheckView(
            provider="ushouse",
            role=CrossCheckRole.HOUSE_CODIFICATION,
            derived_presentation={
                "provider": "ushouse",
                "source_id": "bad",
                "artifact_sha256": content_sha256("x"),
                "source_url": "https://uscode.house.gov/x",
                "role": IdentityRole.OFFICIAL_ARTIFACT.value,
            },
        )


def test_cross_check_only_units_never_success(verifier: GovInfoOfficialVerifier):
    unit = InventoryUnit(
        kind=InventoryKind.USCODE_EDITION,
        package_id="HOUSE-TITLE35-VIEW",
        collection="USCODE",
        title="35",
        edition="house-crosscheck-only",
        formats={
            "html": {
                "format": "html",
                "artifact_sha256": content_sha256("house|html"),
                "source_url": "https://uscode.house.gov/view.xhtml",
                "media_type": "text/html",
            }
        },
        expected_formats=("html",),
        metadata={"provider": "ushouse"},
    )
    result = verifier.verify_unit(unit, cross_check_only=True)
    assert result.outcome is not VerificationOutcome.SUCCESS
    assert result.cross_check_only is True
    assert result.verification_state is not VerificationState.VERIFIED


# ---------------------------------------------------------------------------
# Digital authentication vs printed-volume attestation are separate
# ---------------------------------------------------------------------------


def test_digital_and_print_channels_are_separate(report: OfficialVerificationReport):
    # Find the CFR volume with both digital valid and print attested.
    cfr_success = next(
        (
            r
            for r in report.cfr_volumes()
            if r.outcome is VerificationOutcome.SUCCESS
            and r.digital_authentication.result is SignatureResult.VALID
        ),
        None,
    )
    assert cfr_success is not None
    dig = cfr_success.digital_authentication
    prn = cfr_success.printed_attestation
    assert dig.channel == "digital_authentication"
    assert prn.channel == "printed_volume_attestation"
    assert dig.channel != prn.channel
    assert cfr_success.metadata.get("channels_separate") is True
    # Evidence refs differ when both present.
    if dig.evidence and prn.evidence_ref:
        assert dig.evidence != prn.evidence_ref


def test_digital_success_without_print_attestation_is_allowed(
    verifier: GovInfoOfficialVerifier,
):
    unit = InventoryUnit(
        kind=InventoryKind.USCODE_EDITION,
        package_id=govinfo_uscode_package_id(year=2023, title=35),
        collection="USCODE",
        title="35",
        year="2023",
        edition="govinfo-2023-title35",
        formats={
            "pdf": {
                "format": "pdf",
                "artifact_sha256": content_sha256("u|pdf"),
                "source_url": "https://www.govinfo.gov/content/pkg/USCODE-2023-title35/pdf/x.pdf",
                "observed_sha256": content_sha256("u|pdf"),
            }
        },
        expected_formats=("pdf",),
        metadata={
            "signature": {
                "result": "valid",
                "algorithm": "GPO-PAdES",
                "evidence": "digital-only-evidence",
            },
            "printed_attestation": {"result": "not_checked"},
        },
    )
    result = verifier.verify_unit(unit)
    assert result.outcome is VerificationOutcome.SUCCESS
    assert result.digital_authentication.result is SignatureResult.VALID
    assert result.printed_attestation.result is PrintAttestationResult.NOT_CHECKED
    assert result.printed_attestation.is_attested is False
    # Print not attested does not block digital success by default.
    assert result.verification_state is VerificationState.VERIFIED


def test_print_attestation_does_not_imply_digital_validity(
    verifier: GovInfoOfficialVerifier,
):
    unit = InventoryUnit(
        kind=InventoryKind.CFR_VOLUME,
        package_id="CFR-2019-title37",
        collection="CFR",
        title="37",
        year="2019",
        edition="annual-2019-title37",
        formats={
            "pdf": {
                "format": "pdf",
                "artifact_sha256": content_sha256("c|pdf"),
                "source_url": "https://www.govinfo.gov/content/pkg/CFR-2019-title37/pdf/x.pdf",
                "observed_sha256": content_sha256("c|pdf"),
            }
        },
        expected_formats=("pdf",),
        metadata={
            "signature": {"result": "missing"},
            "printed_attestation": {
                "result": "attested",
                "attestor": "operator-1",
                "evidence_ref": "print-only-evidence",
                "print_edition": "GPO-print-2019-t37",
            },
        },
    )
    result = verifier.verify_unit(unit)
    # Print attested but digital missing → not success.
    assert result.outcome is not VerificationOutcome.SUCCESS
    assert result.outcome in {
        VerificationOutcome.INCONCLUSIVE,
        VerificationOutcome.UNVERIFIED,
    }
    assert result.printed_attestation.is_attested is True
    assert result.digital_authentication.result is SignatureResult.MISSING


def test_require_print_for_success_policy(fixture_dir: Path):
    v = GovInfoOfficialVerifier(
        fixture_dir=fixture_dir,
        require_print_attestation_for_success=True,
    )
    unit = InventoryUnit(
        kind=InventoryKind.USCODE_EDITION,
        package_id="USCODE-2023-title35",
        collection="USCODE",
        title="35",
        year="2023",
        edition="govinfo-2023-title35",
        formats={
            "pdf": {
                "format": "pdf",
                "artifact_sha256": content_sha256("p|pdf"),
                "source_url": "https://www.govinfo.gov/content/pkg/USCODE-2023-title35/pdf/x.pdf",
                "observed_sha256": content_sha256("p|pdf"),
            }
        },
        expected_formats=("pdf",),
        metadata={
            "signature": {
                "result": "valid",
                "algorithm": "GPO-PAdES",
                "evidence": "dig",
            },
            "printed_attestation": {"result": "not_checked"},
        },
    )
    result = v.verify_unit(unit)
    assert result.outcome is VerificationOutcome.INCONCLUSIVE
    assert result.digital_authentication.result is SignatureResult.VALID


def test_digital_and_print_helper_separation():
    dig = DigitalAuthenticationEvidence(
        result=SignatureResult.VALID,
        evidence="digital-sig-A",
        algorithm="GPO-PAdES",
    )
    prn = PrintedVolumeAttestation(
        result=PrintAttestationResult.ATTESTED,
        attestor="desk-1",
        evidence_ref="print-page-B",
        print_edition="print-2024",
    )
    assert dig.channel != prn.channel
    assert digital_and_print_are_separate(dig, prn) is True


# ---------------------------------------------------------------------------
# Missing volumes / granules / signatures / text conflicts → non-success
# ---------------------------------------------------------------------------


def test_missing_volume_is_not_success(verifier: GovInfoOfficialVerifier, fixture_dir: Path):
    report = verifier.verify_from_fixture(fixture_dir / "govinfo_missing_volume.json")
    assert report.status is not VerificationOutcome.SUCCESS
    assert report.unit_results
    for r in report.unit_results:
        assert r.outcome is not VerificationOutcome.SUCCESS
        assert r.outcome in {
            VerificationOutcome.MISSING,
            VerificationOutcome.INCONCLUSIVE,
            VerificationOutcome.UNVERIFIED,
        }
        assert r.verification_state is not VerificationState.VERIFIED


def test_missing_granule_is_inconclusive(report: OfficialVerificationReport):
    incomplete = [
        r
        for r in report.fr_granules()
        if r.missing_granules
    ]
    # The FR-2024-06-01 package has a missing granule in the fixture.
    assert incomplete or any(
        r.unit.package_id == "FR-2024-06-01" and r.outcome is VerificationOutcome.INCONCLUSIVE
        for r in report.unit_results
    )
    for r in report.unit_results:
        if r.missing_granules:
            assert r.outcome is not VerificationOutcome.SUCCESS
            assert r.outcome is VerificationOutcome.INCONCLUSIVE
            assert r.verification_state is VerificationState.INCONCLUSIVE


def test_invalid_signature_is_conflict(report: OfficialVerificationReport):
    sig_fail = [
        r
        for r in report.unit_results
        if r.digital_authentication.result is SignatureResult.INVALID
    ]
    assert sig_fail
    for r in sig_fail:
        assert r.outcome is VerificationOutcome.CONFLICT
        assert r.verification_state is VerificationState.CONFLICT
        assert r.is_success is False


def test_text_conflict_is_conflict_not_success(report: OfficialVerificationReport):
    conflicts = [r for r in report.unit_results if r.text_conflicts]
    assert conflicts
    for r in conflicts:
        assert r.outcome is VerificationOutcome.CONFLICT
        assert r.verification_state is VerificationState.CONFLICT
        for tc in r.text_conflicts:
            assert tc.description
            if tc.cross_check_provider:
                assert tc.cross_check_provider.lower() in {
                    "ecfr",
                    "ushouse",
                    "federalregister.gov",
                    "www.ecfr.gov",
                }


def test_fixity_mismatch_is_conflict(report: OfficialVerificationReport):
    mismatches = [
        r
        for r in report.unit_results
        if any(c.result is FixityResult.MISMATCH for c in r.digital_authentication.fixity_checks)
    ]
    assert mismatches
    for r in mismatches:
        assert r.outcome is VerificationOutcome.CONFLICT
        assert r.is_success is False


def test_missing_signature_is_inconclusive(verifier: GovInfoOfficialVerifier):
    unit = InventoryUnit(
        kind=InventoryKind.CFR_VOLUME,
        package_id="CFR-2018-title37",
        collection="CFR",
        title="37",
        year="2018",
        edition="annual-2018-title37",
        formats={
            "pdf": {
                "format": "pdf",
                "artifact_sha256": content_sha256("m|pdf"),
                "source_url": "https://www.govinfo.gov/content/pkg/CFR-2018-title37/pdf/x.pdf",
                "observed_sha256": content_sha256("m|pdf"),
            }
        },
        expected_formats=("pdf",),
        metadata={"signature": {"result": "missing"}},
    )
    result = verifier.verify_unit(unit)
    assert result.outcome is VerificationOutcome.INCONCLUSIVE
    assert result.verification_state is VerificationState.INCONCLUSIVE
    assert result.outcome is not VerificationOutcome.SUCCESS


def test_aggregate_report_not_success_when_any_conflict(report: OfficialVerificationReport):
    # Full inventory includes conflict cases → overall status is not success.
    assert report.status is not VerificationOutcome.SUCCESS
    assert report.status in {
        VerificationOutcome.CONFLICT,
        VerificationOutcome.INCONCLUSIVE,
        VerificationOutcome.MISSING,
        VerificationOutcome.UNVERIFIED,
        VerificationOutcome.ERROR,
    }
    # But individual success units may still exist alongside failures.
    successes = [r for r in report.unit_results if r.outcome is VerificationOutcome.SUCCESS]
    failures = [r for r in report.unit_results if r.outcome is not VerificationOutcome.SUCCESS]
    assert successes  # happy-path units still verify
    assert failures  # failure cases present in the same report


# ---------------------------------------------------------------------------
# Fixity / source spans / format helpers
# ---------------------------------------------------------------------------


def test_check_format_fixity_match_and_mismatch():
    sha = content_sha256("payload")
    match = check_format_fixity(
        format_name="pdf",
        advertised_sha256=sha,
        observed_sha256=sha,
    )
    assert match.result is FixityResult.MATCH
    assert match.is_success is True

    bad = check_format_fixity(
        format_name="xml",
        advertised_sha256=sha,
        observed_sha256=content_sha256("other"),
    )
    assert bad.result is FixityResult.MISMATCH
    assert bad.is_conflict is True


def test_source_spans_on_verified_units(report: OfficialVerificationReport):
    with_spans = [r for r in report.unit_results if r.source_spans]
    assert with_spans
    for r in with_spans:
        for span in r.source_spans:
            assert span.start >= 0
            assert span.end >= span.start


def test_pdf_xml_mods_premis_fixity_checked_on_cfr(report: OfficialVerificationReport):
    cfr = next(
        r
        for r in report.cfr_volumes()
        if r.unit.package_id.startswith("CFR-2024-title37")
        and r.outcome is VerificationOutcome.SUCCESS
    )
    formats_checked = {c.format for c in cfr.digital_authentication.fixity_checks}
    for fmt in ("pdf", "xml", "mods", "premis"):
        assert fmt in formats_checked
        check = next(c for c in cfr.digital_authentication.fixity_checks if c.format == fmt)
        assert check.result is FixityResult.MATCH


def test_outcome_to_verification_state_mapping():
    assert outcome_to_verification_state(VerificationOutcome.SUCCESS) is VerificationState.VERIFIED
    assert outcome_to_verification_state(VerificationOutcome.CONFLICT) is VerificationState.CONFLICT
    assert (
        outcome_to_verification_state(VerificationOutcome.INCONCLUSIVE)
        is VerificationState.INCONCLUSIVE
    )
    assert (
        outcome_to_verification_state(VerificationOutcome.UNVERIFIED)
        is VerificationState.UNVERIFIED
    )


# ---------------------------------------------------------------------------
# Success path cannot be constructed with conflicts / missing pieces
# ---------------------------------------------------------------------------


def test_unit_result_rejects_success_with_text_conflict():
    unit = InventoryUnit(
        kind=InventoryKind.CFR_VOLUME,
        package_id="CFR-2024-title37",
        collection="CFR",
        title="37",
        edition="annual-2024",
        year="2024",
    )
    dig = DigitalAuthenticationEvidence(
        result=SignatureResult.VALID,
        algorithm="GPO-PAdES",
        evidence="ok",
        fixity_checks=(
            FormatFixityCheck(
                format="pdf",
                result=FixityResult.MATCH,
                advertised_sha256=content_sha256("a"),
                observed_sha256=content_sha256("a"),
            ),
        ),
    )
    with pytest.raises(Exception):
        UnitVerificationResult(
            unit=unit,
            outcome=VerificationOutcome.SUCCESS,
            verification_state=VerificationState.VERIFIED,
            digital_authentication=dig,
            printed_attestation=PrintedVolumeAttestation.not_checked(),
            text_conflicts=(
                TextConflictFinding(description="should block success"),
            ),
        )


def test_unit_result_rejects_success_without_valid_digital():
    unit = InventoryUnit(
        kind=InventoryKind.CFR_VOLUME,
        package_id="CFR-2024-title37",
        collection="CFR",
        title="37",
        edition="annual-2024",
        year="2024",
    )
    dig = DigitalAuthenticationEvidence(result=SignatureResult.MISSING)
    with pytest.raises(Exception):
        UnitVerificationResult(
            unit=unit,
            outcome=VerificationOutcome.SUCCESS,
            verification_state=VerificationState.VERIFIED,
            digital_authentication=dig,
            printed_attestation=PrintedVolumeAttestation(
                result=PrintAttestationResult.ATTESTED,
                attestor="x",
                evidence_ref="print",
                print_edition="print-ed",
            ),
        )


# ---------------------------------------------------------------------------
# Public Law helpers
# ---------------------------------------------------------------------------


def test_parse_public_law_number_forms():
    cite, congress, law = parse_public_law_number("Pub. L. 112-29")
    assert cite == "Pub. L. 112-29"
    assert congress == "112"
    assert law == "29"
    cite2, c2, l2 = parse_public_law_number("PLAW-118publ45")
    assert c2 == "118" and l2 == "45"
    assert stable_public_law_identity(congress=112, law_number=29) == "plaw:us:112:29"
    with pytest.raises((HardCodedLatestEditionError, Exception)):
        parse_public_law_number("latest")


def test_classify_patent_relevance():
    assert classify_patent_relevance(title="America Invents Act", text_excerpt="patent reform")
    assert classify_patent_relevance(affects_titles=["35"])
    assert not classify_patent_relevance(
        title="Infrastructure Investment and Jobs Act",
        text_excerpt="highways and transit",
        explicit=False,
    )
    assert classify_patent_relevance(title="whatever", explicit=True)


def test_public_law_record_roundtrip():
    pkg = govinfo_plaw_package_id(congress=112, law_number=29)
    rec = PublicLawRecord(
        congress="112",
        law_number="29",
        title="Leahy-Smith America Invents Act",
        citation="Pub. L. 112-29",
        package_id=pkg,
        stable_id=stable_public_law_identity(congress=112, law_number=29),
        patent_relevant=True,
        formats={
            "pdf": {
                "format": "pdf",
                "artifact_sha256": content_sha256("rt|pdf"),
                "source_url": f"https://www.govinfo.gov/content/pkg/{pkg}/pdf/{pkg}.pdf",
            }
        },
    )
    data = rec.to_dict()
    restored = PublicLawRecord.from_dict(data)
    assert restored.package_id == rec.package_id
    assert restored.patent_relevant is True
    assert restored.stable_id == rec.stable_id


# ---------------------------------------------------------------------------
# Fixture generators / schema
# ---------------------------------------------------------------------------


def test_fixture_recipe_generators_are_compact():
    pl = build_public_laws_fixture_recipe()
    assert pl["schema_version"]
    assert len(pl["public_laws"]) >= 4
    inv = build_govinfo_official_inventory_recipe()
    assert inv["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert inv["edition_catalog"]["latest_editions"]
    assert inv["inventory"]


def test_write_default_fixtures(tmp_path: Path):
    root = write_default_fixtures(tmp_path)
    assert (root / "govinfo_official_inventory_recipe.json").is_file()
    assert (root / "public_laws_recipe.json").is_file()
    assert (root / "govinfo_missing_volume.json").is_file()
    # Re-load works
    v = GovInfoOfficialVerifier(fixture_dir=root)
    report = v.verify_from_fixture()
    assert report.unit_results
    assert report.discoveries


def test_schema_versions_exported():
    assert SCHEMA_VERSION.startswith("govinfo-official")
    assert FIXTURE_SCHEMA_VERSION.startswith("govinfo-official")


def test_missing_public_laws_fixture_is_unknown(pl_processor: PublicLawChangeProcessor, fixture_dir: Path):
    acq = pl_processor.acquire_from_fixture(fixture_dir / "public_laws_missing.json")
    assert acq.status is PlResolutionStatus.UNKNOWN
    assert acq.manifest.total_examined == 0


def test_report_to_dict_is_serializable(report: OfficialVerificationReport):
    payload = report.to_dict()
    text = json.dumps(payload)
    assert "digital_authentication" in text
    assert "printed_attestation" in text
    assert "schema_version" in payload
    # Round-trip JSON load
    loaded = json.loads(text)
    assert loaded["status"] == report.status.value


def test_print_conflict_forces_conflict_outcome(verifier: GovInfoOfficialVerifier):
    unit = InventoryUnit(
        kind=InventoryKind.CFR_VOLUME,
        package_id="CFR-2017-title37",
        collection="CFR",
        title="37",
        year="2017",
        edition="annual-2017-title37",
        formats={
            "pdf": {
                "format": "pdf",
                "artifact_sha256": content_sha256("pc|pdf"),
                "source_url": "https://www.govinfo.gov/content/pkg/CFR-2017-title37/pdf/x.pdf",
                "observed_sha256": content_sha256("pc|pdf"),
            }
        },
        expected_formats=("pdf",),
        metadata={
            "signature": {
                "result": "valid",
                "algorithm": "GPO-PAdES",
                "evidence": "dig-ok",
            },
            "printed_attestation": {
                "result": "conflict",
                "attestor": "desk",
                "evidence_ref": "print-conflict",
                "print_edition": "print-2017",
                "notes": "Print page does not match bound volume.",
            },
        },
    )
    result = verifier.verify_unit(unit)
    assert result.outcome is VerificationOutcome.CONFLICT
    assert result.printed_attestation.result is PrintAttestationResult.CONFLICT
    assert result.digital_authentication.result is SignatureResult.VALID
