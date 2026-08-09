"""Unit tests for the exact all-title release catalog (USCIR-005).

Acceptance:

* Fixture acquisition is deterministic.
* Title completeness is explicit.
* Resume does not redownload verified packages.
* Every accepted package binds checksum and release point.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.uscode_release_catalog import (
    CANONICAL_USCODE_TITLES,
    CURRENTNESS_DISCLAIMER,
    DEFAULT_APPROVED_RELEASE_POINT,
    DEFAULT_CATALOG_APPROVED_BY,
    DEFAULT_FIXTURE_ID,
    EXPECTED_TITLE_COUNT,
    FIXTURE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    CatalogAcquisitionMode,
    CatalogAcquisitionResult,
    CatalogCompletenessError,
    CatalogFixtureSchemaError,
    HardCodedLatestEditionError,
    MissingApprovedReleaseError,
    PackageDisposition,
    TitlePackageAcquisition,
    UnapprovedProposedReleaseError,
    UscodeReleaseCatalog,
    build_completeness_report,
    build_default_catalog_fixture_payload,
    default_catalog_fixture_path,
    expand_catalog_fixture,
    expected_title_package_sha256,
    load_catalog_fixture,
    load_catalog_fixture_payload,
    ushouse_releasepoint_zip_url,
)
from ipfs_datasets_py.processors.legal_data.uscode_source_policy import (
    ExclusionKind,
    ReleasePointRole,
    TitleExclusion,
    TitlePackageStatus,
    TitleResumeReceipt,
    VerificationResult,
    require_approved_exact as policy_require_approved_exact,
)

# tests/unit/processors/legal_scrapers/this_file.py → tests/
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "uscode_release_catalog.json"
)


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return load_catalog_fixture_payload(_FIXTURE_PATH)


@pytest.fixture(scope="module")
def fixture_state(fixture_payload: dict) -> dict:
    return expand_catalog_fixture(fixture_payload)


@pytest.fixture
def catalog(tmp_path: Path) -> UscodeReleaseCatalog:
    return UscodeReleaseCatalog(
        fixture_path=_FIXTURE_PATH,
        checkpoint_dir=tmp_path / "checkpoints",
    )


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_catalog_fixture_is_present_and_compact():
    assert _FIXTURE_PATH.is_file()
    assert default_catalog_fixture_path().name == "uscode_release_catalog.json"
    size = _FIXTURE_PATH.stat().st_size
    assert size < 32_000
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert payload["expected_title_count"] == EXPECTED_TITLE_COUNT
    assert "generators" in payload
    # Recipe form: not 53 fully expanded inline envelopes.
    assert len(payload.get("packages") or {}) < 5
    assert len(payload.get("resume_receipts") or {}) < 5
    assert len(payload.get("expected_packages") or {}) < 5


def test_default_payload_matches_on_disk_recipe():
    built = build_default_catalog_fixture_payload()
    on_disk = load_catalog_fixture_payload(_FIXTURE_PATH)
    assert built["schema_version"] == on_disk["schema_version"]
    assert built["expected_title_count"] == on_disk["expected_title_count"]
    assert built["approved_release"]["release_point"] == on_disk["approved_release"]["release_point"]
    assert built["proposed_release"]["role"] == ReleasePointRole.PROPOSED_LATEST.value
    assert on_disk["proposed_release"]["role"] == ReleasePointRole.PROPOSED_LATEST.value
    assert built["approved_release"]["role"] == ReleasePointRole.APPROVED_EXACT.value
    assert on_disk["approved_release"]["role"] == ReleasePointRole.APPROVED_EXACT.value
    assert built["fixture_id"] == DEFAULT_FIXTURE_ID
    assert on_disk["fixture_id"] == DEFAULT_FIXTURE_ID


def test_fixture_expands_to_all_53_titles(fixture_state: dict):
    assert fixture_state["expected_title_count"] == EXPECTED_TITLE_COUNT
    assert set(fixture_state["expected_packages"]) == set(CANONICAL_USCODE_TITLES)
    assert set(fixture_state["packages"]) == set(CANONICAL_USCODE_TITLES)
    assert set(fixture_state["resume_receipts"]) == set(CANONICAL_USCODE_TITLES)
    assert "53" not in fixture_state["packages"]


def test_malformed_fixture_schema_rejected():
    with pytest.raises(CatalogFixtureSchemaError):
        expand_catalog_fixture({"schema_version": "not-a-real-schema"})


# ---------------------------------------------------------------------------
# Resolve one approved release + enumerate packages
# ---------------------------------------------------------------------------


def test_resolves_one_approved_release_from_fixture(catalog: UscodeReleaseCatalog):
    approved = catalog.resolve_approved_release(from_fixture=True)
    assert approved.role is ReleasePointRole.APPROVED_EXACT
    assert approved.release_point == DEFAULT_APPROVED_RELEASE_POINT
    assert approved.approved_by == DEFAULT_CATALOG_APPROVED_BY
    assert "latest" not in approved.release_point.lower()

    # Proposed-latest is recorded but not admissible as final provenance alone.
    assert catalog.policy.proposed_release is not None
    assert catalog.policy.proposed_release.role is ReleasePointRole.PROPOSED_LATEST
    with pytest.raises(UnapprovedProposedReleaseError):
        policy_require_approved_exact(catalog.policy.proposed_release)


def test_hard_coded_latest_rejected(catalog: UscodeReleaseCatalog):
    with pytest.raises(HardCodedLatestEditionError):
        catalog.resolve_approved_release(release_point="latest")
    with pytest.raises(HardCodedLatestEditionError):
        catalog.propose_latest_from_discovery(release_point="latest")


def test_enumerate_all_expected_title_packages(catalog: UscodeReleaseCatalog):
    catalog.resolve_approved_release(from_fixture=True)
    specs = catalog.enumerate_expected_packages(from_fixture=True)
    assert len(specs) == EXPECTED_TITLE_COUNT
    assert set(specs) == set(CANONICAL_USCODE_TITLES)
    for title, spec in specs.items():
        assert spec.title == title
        assert spec.release_point == DEFAULT_APPROVED_RELEASE_POINT
        assert spec.expected_sha256 == expected_title_package_sha256(
            release_point=DEFAULT_APPROVED_RELEASE_POINT, title=title
        )
        assert spec.source_url == ushouse_releasepoint_zip_url(
            congress="118", release="45", title=title, format_kind="xml"
        )


def test_missing_approved_release_fails_closed(catalog: UscodeReleaseCatalog):
    with pytest.raises(MissingApprovedReleaseError):
        catalog.enumerate_expected_packages(from_fixture=False)


# ---------------------------------------------------------------------------
# Deterministic fixture acquisition
# ---------------------------------------------------------------------------


def test_fixture_acquisition_is_deterministic(catalog: UscodeReleaseCatalog, tmp_path: Path):
    result1 = catalog.acquire_from_fixture()
    # Fresh catalog, same fixture → identical digests and package bindings.
    catalog2 = UscodeReleaseCatalog(
        fixture_path=_FIXTURE_PATH,
        checkpoint_dir=tmp_path / "checkpoints2",
    )
    result2 = catalog2.acquire_from_fixture()

    assert result1.mode is CatalogAcquisitionMode.FIXTURE
    assert result1.result_digest() == result2.result_digest()
    assert result1.approved_release.release_point == result2.approved_release.release_point
    assert len(result1.packages) == EXPECTED_TITLE_COUNT
    assert result1.download_count == EXPECTED_TITLE_COUNT
    assert result1.skip_count == 0

    # Round-trip result serialization is stable.
    again = CatalogAcquisitionResult.from_dict(result1.to_dict())
    assert again.result_digest() == result1.result_digest()


def test_every_accepted_package_binds_checksum_and_release_point(
    catalog: UscodeReleaseCatalog,
):
    result = catalog.acquire_from_fixture()
    catalog.assert_accepted_packages_bound(result.packages)

    for title in CANONICAL_USCODE_TITLES:
        pkg = result.packages[title]
        assert pkg.disposition is PackageDisposition.ACCEPTED
        assert pkg.release_point == DEFAULT_APPROVED_RELEASE_POINT
        assert pkg.content_sha256 is not None
        assert len(pkg.content_sha256) == 64
        assert pkg.content_sha256 == expected_title_package_sha256(
            release_point=DEFAULT_APPROVED_RELEASE_POINT, title=title
        )
        assert pkg.package_id == DEFAULT_APPROVED_RELEASE_POINT
        assert pkg.verification is VerificationResult.VERIFIED
        assert pkg.status is TitlePackageStatus.VERIFIED
        assert pkg.provenance is not None
        assert pkg.provenance.content_sha256 == pkg.content_sha256
        assert pkg.provenance.release_point == pkg.release_point
        assert pkg.resume_receipt is not None
        assert pkg.resume_receipt.content_sha256 == pkg.content_sha256
        assert pkg.resume_receipt.release_point == pkg.release_point


def test_fixture_carries_currentness_disclaimer(catalog: UscodeReleaseCatalog):
    result = catalog.acquire_from_fixture()
    assert result.currentness_disclaimer == CURRENTNESS_DISCLAIMER
    assert "not a claim" in result.currentness_disclaimer.lower()
    assert "official source" in result.currentness_disclaimer.lower()


def test_acquire_single_title_from_fixture(catalog: UscodeReleaseCatalog):
    pkg = catalog.acquire_title_from_fixture("35")
    assert pkg.title == "35"
    assert pkg.disposition is PackageDisposition.ACCEPTED
    assert pkg.release_point == DEFAULT_APPROVED_RELEASE_POINT
    assert pkg.content_sha256 == expected_title_package_sha256(
        release_point=DEFAULT_APPROVED_RELEASE_POINT, title="35"
    )


# ---------------------------------------------------------------------------
# Title completeness is explicit
# ---------------------------------------------------------------------------


def test_title_completeness_is_explicit_and_complete(catalog: UscodeReleaseCatalog):
    result = catalog.acquire_from_fixture()
    report = result.completeness
    assert report.expected_count == EXPECTED_TITLE_COUNT
    assert report.is_complete is True
    assert report.missing_titles == ()
    assert report.failed_titles == ()
    assert set(report.accepted_titles) == set(CANONICAL_USCODE_TITLES)
    assert report.excluded_titles == ()
    assert len(report.present_titles) == EXPECTED_TITLE_COUNT

    missing_report = catalog.report_missing_and_excluded()
    assert missing_report["missing"] == ()
    assert missing_report["excluded"] == ()


def test_completeness_reports_missing_titles_explicitly():
    packages = {
        "1": TitlePackageAcquisition(
            title="1",
            disposition=PackageDisposition.ACCEPTED,
            release_point=DEFAULT_APPROVED_RELEASE_POINT,
            content_sha256=expected_title_package_sha256(
                release_point=DEFAULT_APPROVED_RELEASE_POINT, title="1"
            ),
            status=TitlePackageStatus.VERIFIED,
            verification=VerificationResult.VERIFIED,
        ),
        "2": TitlePackageAcquisition(
            title="2",
            disposition=PackageDisposition.MISSING,
            release_point=None,
            content_sha256=None,
            status=TitlePackageStatus.FAILED,
            verification=VerificationResult.MISSING,
        ),
    }
    report = build_completeness_report(
        packages, expected_titles=("1", "2", "3")
    )
    assert report.is_complete is False
    assert report.missing_titles == ("2", "3")
    assert report.accepted_titles == ("1",)
    assert "2" not in report.present_titles or "2" in report.missing_titles


def test_completeness_reports_excluded_packages():
    excl = TitleExclusion(
        kind=ExclusionKind.PACKAGE_UNAVAILABLE,
        title="10",
        reason="package temporarily unavailable at this release point",
    )
    packages = {
        "10": TitlePackageAcquisition(
            title="10",
            disposition=PackageDisposition.EXCLUDED,
            release_point=DEFAULT_APPROVED_RELEASE_POINT,
            content_sha256=expected_title_package_sha256(
                release_point=DEFAULT_APPROVED_RELEASE_POINT, title="10"
            ),
            status=TitlePackageStatus.EXCLUDED,
            verification=VerificationResult.MISSING,
            exclusion=excl,
        ),
        "11": TitlePackageAcquisition(
            title="11",
            disposition=PackageDisposition.ACCEPTED,
            release_point=DEFAULT_APPROVED_RELEASE_POINT,
            content_sha256=expected_title_package_sha256(
                release_point=DEFAULT_APPROVED_RELEASE_POINT, title="11"
            ),
            status=TitlePackageStatus.VERIFIED,
            verification=VerificationResult.VERIFIED,
        ),
    }
    report = build_completeness_report(packages, expected_titles=("10", "11"))
    assert report.is_complete is True
    assert report.excluded_titles == ("10",)
    assert report.accepted_titles == ("11",)
    assert report.missing_titles == ()


def test_require_complete_raises_on_incomplete(tmp_path: Path):
    # Build a fixture recipe with an explicit missing title.
    payload = build_default_catalog_fixture_payload(missing_titles=["42"])
    fixture_path = tmp_path / "partial_catalog.json"
    fixture_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    catalog = UscodeReleaseCatalog(
        fixture_path=fixture_path,
        checkpoint_dir=tmp_path / "ck",
    )
    result = catalog.acquire_from_fixture(require_complete=False)
    assert result.completeness.is_complete is False
    assert "42" in result.completeness.missing_titles
    assert result.packages["42"].disposition is PackageDisposition.MISSING

    with pytest.raises(CatalogCompletenessError):
        catalog.acquire_from_fixture(require_complete=True)


def test_excluded_package_recipe_is_reported(tmp_path: Path):
    payload = build_default_catalog_fixture_payload(
        excluded_titles={
            "7": {
                "kind": ExclusionKind.PACKAGE_UNAVAILABLE.value,
                "reason": "package unavailable at sealed release point",
            }
        }
    )
    fixture_path = tmp_path / "excluded_catalog.json"
    fixture_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    catalog = UscodeReleaseCatalog(
        fixture_path=fixture_path,
        checkpoint_dir=tmp_path / "ck",
    )
    result = catalog.acquire_from_fixture()
    assert result.packages["7"].disposition is PackageDisposition.EXCLUDED
    assert result.packages["7"].exclusion is not None
    assert "7" in result.completeness.excluded_titles
    # Completeness still holds: excluded is an explicit account of the title.
    assert result.completeness.is_complete is True
    missing = catalog.report_missing_and_excluded()
    assert missing["excluded"] == ("7",)
    assert missing["missing"] == ()


# ---------------------------------------------------------------------------
# Resume does not redownload verified packages
# ---------------------------------------------------------------------------


def test_resume_does_not_redownload_verified_packages(
    catalog: UscodeReleaseCatalog, tmp_path: Path
):
    first = catalog.acquire_from_fixture()
    assert first.download_count == EXPECTED_TITLE_COUNT
    assert first.skip_count == 0

    # On-disk checksums match every verified package.
    on_disk = {
        title: pkg.content_sha256
        for title, pkg in first.packages.items()
        if pkg.content_sha256
    }
    resumed = catalog.resume(prior=first, on_disk_checksums=on_disk)
    assert resumed.mode is CatalogAcquisitionMode.RESUME
    assert resumed.skip_count == EXPECTED_TITLE_COUNT
    assert resumed.download_count == 0
    for title in CANONICAL_USCODE_TITLES:
        pkg = resumed.packages[title]
        assert pkg.disposition is PackageDisposition.SKIPPED_VERIFIED
        assert pkg.redownloaded is False
        assert pkg.release_point == DEFAULT_APPROVED_RELEASE_POINT
        assert pkg.content_sha256 == expected_title_package_sha256(
            release_point=DEFAULT_APPROVED_RELEASE_POINT, title=title
        )


def test_resume_from_checkpoint_file(catalog: UscodeReleaseCatalog):
    first = catalog.acquire_from_fixture()
    ck_path = catalog.checkpoint_receipts(first)
    assert ck_path.is_file()

    catalog2 = UscodeReleaseCatalog(
        fixture_path=_FIXTURE_PATH,
        checkpoint_dir=catalog.checkpoint_dir,
    )
    resumed = catalog2.resume(checkpoint_path=ck_path)
    assert resumed.skip_count == EXPECTED_TITLE_COUNT
    assert resumed.download_count == 0
    assert resumed.completeness.is_complete is True


def test_resume_trusted_checkpoint_without_on_disk_hash(catalog: UscodeReleaseCatalog):
    first = catalog.acquire_from_fixture()
    # No on_disk_checksums → trusted verified receipts still skip redownload.
    resumed = catalog.resume(prior=first)
    assert resumed.skip_count == EXPECTED_TITLE_COUNT
    assert resumed.download_count == 0


def test_resume_checksum_mismatch_forces_redownload(catalog: UscodeReleaseCatalog):
    first = catalog.acquire_from_fixture()
    bad_disk = {title: "0" * 64 for title in CANONICAL_USCODE_TITLES}
    resumed = catalog.resume(prior=first, on_disk_checksums=bad_disk)
    # Checksum mismatch prevents skip; packages are redownloaded from fixture.
    assert resumed.download_count == EXPECTED_TITLE_COUNT
    assert resumed.skip_count == 0
    for title in ("1", "26", "35", "54"):
        pkg = resumed.packages[title]
        assert pkg.disposition is PackageDisposition.ACCEPTED
        assert pkg.redownloaded is True
        assert pkg.content_sha256 == expected_title_package_sha256(
            release_point=DEFAULT_APPROVED_RELEASE_POINT, title=title
        )


def test_pending_receipt_is_redownloaded_on_resume(tmp_path: Path):
    # Craft a prior result with one pending (unverified) package.
    catalog = UscodeReleaseCatalog(
        fixture_path=_FIXTURE_PATH,
        checkpoint_dir=tmp_path / "ck",
    )
    first = catalog.acquire_from_fixture()
    # Mutate title 1 into a pending receipt scenario via a synthetic prior.
    pending_pkg = first.packages["1"]
    pending_receipt = TitleResumeReceipt(
        title="1",
        release_point=pending_pkg.release_point,
        package_id=pending_pkg.package_id,
        content_sha256=pending_pkg.content_sha256,
        status=TitlePackageStatus.PENDING,
        verification=VerificationResult.UNVERIFIED,
        source_url=pending_pkg.source_url,
        acquired_at="2024-09-20T12:05:00Z",
        checkpoint_seq=1,
    )
    packages = dict(first.packages)
    packages["1"] = TitlePackageAcquisition(
        title="1",
        disposition=PackageDisposition.REDOWNLOAD,
        release_point=pending_pkg.release_point,
        content_sha256=pending_pkg.content_sha256,
        package_id=pending_pkg.package_id,
        source_url=pending_pkg.source_url,
        status=TitlePackageStatus.PENDING,
        verification=VerificationResult.UNVERIFIED,
        provenance=pending_pkg.provenance,
        resume_receipt=pending_receipt,
        redownloaded=False,
        notes="pending acquisition",
    )
    receipts = dict(first.resume_receipts)
    receipts["1"] = pending_receipt
    prior = CatalogAcquisitionResult(
        approved_release=first.approved_release,
        packages=packages,
        completeness=build_completeness_report(
            packages, expected_titles=CANONICAL_USCODE_TITLES
        ),
        mode=CatalogAcquisitionMode.FIXTURE,
        resume_receipts=receipts,
        proposed_release=first.proposed_release,
        expected_packages=first.expected_packages,
        fixture_id=first.fixture_id,
        download_count=first.download_count - 1,
        skip_count=0,
    )
    resumed = catalog.resume(prior=prior)
    # Title 1 was not verified → redownloaded; others skipped.
    assert resumed.packages["1"].disposition is PackageDisposition.ACCEPTED
    assert resumed.packages["1"].redownloaded is True
    assert resumed.skip_count == EXPECTED_TITLE_COUNT - 1
    assert resumed.download_count == 1


# ---------------------------------------------------------------------------
# Checkpoint integrity + manifest projection
# ---------------------------------------------------------------------------


def test_checkpoint_is_atomic_and_loadable(catalog: UscodeReleaseCatalog):
    result = catalog.acquire_from_fixture()
    path = catalog.checkpoint_receipts(result)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["result_digest"] == result.result_digest()
    assert len(payload["resume_receipts"]) == EXPECTED_TITLE_COUNT

    loaded = catalog.load_checkpoint(path)
    assert loaded.approved_release.release_point == result.approved_release.release_point
    assert loaded.completeness.is_complete is True
    assert len(loaded.packages) == EXPECTED_TITLE_COUNT


def test_result_projects_to_all_title_manifest(catalog: UscodeReleaseCatalog):
    result = catalog.acquire_from_fixture()
    manifest = result.to_manifest()
    assert manifest.approved_release.release_point == DEFAULT_APPROVED_RELEASE_POINT
    assert manifest.title_count == EXPECTED_TITLE_COUNT
    assert set(manifest.verified_titles) == set(CANONICAL_USCODE_TITLES)
    assert len(manifest.resume_receipts) == EXPECTED_TITLE_COUNT
    for title in CANONICAL_USCODE_TITLES:
        assert manifest.titles[title].content_sha256 == expected_title_package_sha256(
            release_point=DEFAULT_APPROVED_RELEASE_POINT, title=title
        )


def test_resume_receipts_are_deterministic(fixture_state: dict):
    digests = []
    for title in sorted(fixture_state["resume_receipts"]):
        receipt = fixture_state["resume_receipts"][title]
        assert receipt.receipt_digest
        digests.append(receipt.receipt_digest)
    assert len(set(digests)) == EXPECTED_TITLE_COUNT


def test_accepted_package_without_checksum_rejected():
    with pytest.raises(Exception):
        TitlePackageAcquisition(
            title="1",
            disposition=PackageDisposition.ACCEPTED,
            release_point=DEFAULT_APPROVED_RELEASE_POINT,
            content_sha256=None,
            status=TitlePackageStatus.VERIFIED,
            verification=VerificationResult.VERIFIED,
        )


def test_load_catalog_fixture_helper():
    state = load_catalog_fixture(_FIXTURE_PATH)
    assert state["fixture_id"] == DEFAULT_FIXTURE_ID
    assert state["approved_release"].release_point == DEFAULT_APPROVED_RELEASE_POINT
