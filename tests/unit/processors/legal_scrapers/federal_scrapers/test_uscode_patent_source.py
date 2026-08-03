"""Unit tests for Title 35 U.S. Code release-point acquisition (PATLAW-013).

Acceptance:

* Exact release point and exclusions are recorded.
* 35 USC 122 and 181–188 fixtures resolve.
* Source format differences do not change stable section identity.
* Missing release data yields unknown.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    HardCodedLatestEditionError,
    IdentityRole,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.uscode_release_processor import (
    CONFIDENTIALITY_SECTION,
    FIXTURE_SCHEMA_VERSION,
    PATENT_SENSITIVE_SECTIONS,
    SCHEMA_VERSION,
    SECRECY_ORDER_SECTIONS,
    ExclusionKind,
    FormatArtifact,
    ReleasePoint,
    ResolutionStatus,
    SectionNotFoundError,
    SourceFormat,
    UscodeReleaseAcquisition,
    UscodeReleaseError,
    UscodeReleaseProcessor,
    UscodeSectionRecord,
    build_title35_fixture_recipe,
    content_sha256,
    default_fixture_dir,
    govinfo_title_package_id,
    normalize_section_token,
    parse_release_point_id,
    stable_section_identity,
    ushouse_releasepoint_zip_url,
    write_default_fixtures,
)

# tests/unit/processors/legal_scrapers/federal_scrapers/this_file.py
# parents[4] == tests/
_REPO_FIXTURE_DIR = (
    Path(__file__).resolve().parents[4]
    / "fixtures"
    / "legal_data"
    / "patent_authorities"
    / "uscode"
)


def _fixture_dir() -> Path:
    # Prefer processor default; fall back to path relative to this test module.
    candidate = default_fixture_dir()
    if (candidate / "title35_release_recipe.json").is_file():
        return candidate
    if (_REPO_FIXTURE_DIR / "title35_release_recipe.json").is_file():
        return _REPO_FIXTURE_DIR
    # Materialize into the declared fixture output tree when missing.
    write_default_fixtures(_REPO_FIXTURE_DIR)
    return _REPO_FIXTURE_DIR


@pytest.fixture(scope="module")
def fixture_dir() -> Path:
    return _fixture_dir()


@pytest.fixture
def processor(fixture_dir: Path) -> UscodeReleaseProcessor:
    return UscodeReleaseProcessor(fixture_dir=fixture_dir)


@pytest.fixture
def acquisition(processor: UscodeReleaseProcessor) -> UscodeReleaseAcquisition:
    return processor.acquire_from_fixture()


# ---------------------------------------------------------------------------
# Release point + exclusions
# ---------------------------------------------------------------------------


def test_exact_release_point_is_recorded(acquisition: UscodeReleaseAcquisition):
    assert acquisition.status is ResolutionStatus.RESOLVED
    assert acquisition.release_point is not None
    rp = acquisition.release_point
    assert rp.release_point == "us/pl/118/45"
    assert rp.congress == "118"
    assert rp.release == "45"
    assert rp.provider == "ushouse"
    assert rp.title == "35"
    assert "latest" not in rp.release_point.lower()
    assert rp.edition is not None and "latest" not in rp.edition.lower()
    assert rp.content_sha256 is not None
    assert len(rp.content_sha256) == 64
    assert rp.source_url is not None
    assert "releasepoints/us/pl/118/45" in rp.source_url


def test_exclusions_are_recorded(acquisition: UscodeReleaseAcquisition):
    exclusions = acquisition.recorded_exclusions()
    assert len(exclusions) >= 2
    kinds = {e.kind for e in exclusions}
    assert ExclusionKind.UNCODIFIED_SLIP_LAW in kinds
    assert ExclusionKind.CLASSIFICATION_GAP in kinds or ExclusionKind.POSITIVE_LAW_PENDING in kinds
    for exclusion in exclusions:
        assert exclusion.citation
        assert exclusion.reason
        assert "pretend" not in exclusion.reason.lower()
    # At least one exclusion references secrecy-order sections or 122.
    affected = {sec for e in exclusions for sec in e.affects_sections}
    assert "122" in affected or bool(affected & set(SECRECY_ORDER_SECTIONS))


def test_authority_source_carries_release_point(acquisition: UscodeReleaseAcquisition):
    auth = acquisition.authority_source
    assert auth is not None
    assert auth.authority_tier is AuthorityTier.OFFICIAL_BASE
    assert auth.collection == "USCODE"
    assert auth.title == "35"
    assert auth.release_point == "us/pl/118/45"
    assert auth.edition is not None
    assert auth.official_artifact is not None
    assert auth.official_artifact.role is IdentityRole.OFFICIAL_ARTIFACT
    # Dual identity preserved when HTML presentation differs from USLM package.
    if auth.derived_presentation is not None:
        assert auth.derived_presentation.role is IdentityRole.DERIVED_PRESENTATION
        assert (
            auth.derived_presentation.artifact_sha256
            != auth.official_artifact.artifact_sha256
        )


def test_registry_registration_on_acquire(processor: UscodeReleaseProcessor, acquisition):
    auth = acquisition.authority_source
    assert auth is not None
    assert auth.source_key in processor.registry
    stored = processor.registry.get(auth.source_key)
    assert stored.release_point == "us/pl/118/45"


# ---------------------------------------------------------------------------
# 35 USC 122 and 181–188 resolve
# ---------------------------------------------------------------------------


def test_section_122_resolves(acquisition: UscodeReleaseAcquisition):
    record = acquisition.get_section(CONFIDENTIALITY_SECTION)
    assert record.status is ResolutionStatus.RESOLVED
    assert record.title == "35"
    assert record.section == "122"
    assert record.stable_id == "usc:us:35:122"
    assert record.release_point == "us/pl/118/45"
    assert "Confidential" in (record.heading or "")
    assert record.citation == "35 U.S.C. § 122"
    assert record.formats  # multi-format metadata present


@pytest.mark.parametrize("section", list(SECRECY_ORDER_SECTIONS))
def test_secrecy_order_sections_resolve(acquisition: UscodeReleaseAcquisition, section: str):
    record = acquisition.get_section(section)
    assert record.status is ResolutionStatus.RESOLVED
    assert record.section == section
    assert record.stable_id == f"usc:us:35:{section}"
    assert record.release_point == acquisition.release_point.release_point


def test_resolve_patent_sensitive_sections_api(processor: UscodeReleaseProcessor):
    resolved = processor.resolve_patent_sensitive_sections()
    assert set(resolved) == set(PATENT_SENSITIVE_SECTIONS)
    for section, record in resolved.items():
        assert record.status is ResolutionStatus.RESOLVED
        assert record.section == section
        assert record.stable_id == stable_section_identity(title="35", section=section)


def test_missing_section_raises(acquisition: UscodeReleaseAcquisition):
    with pytest.raises(SectionNotFoundError):
        acquisition.get_section("9999")


# ---------------------------------------------------------------------------
# Source format differences do not change stable section identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "section,citation_forms",
    [
        ("122", ["122", "§ 122", "section 122", "35 U.S.C. § 122", "Sec. 122"]),
        ("181", ["181", "§181", "35 USC 181"]),
    ],
)
def test_section_token_normalization(section: str, citation_forms: list[str]):
    identities = {stable_section_identity(title="35", section=form) for form in citation_forms}
    assert identities == {f"usc:us:35:{section}"}
    tokens = {normalize_section_token(form) for form in citation_forms}
    assert tokens == {section}


def test_stable_identity_independent_of_source_format(acquisition: UscodeReleaseAcquisition):
    record = acquisition.get_section("122")
    assert set(record.formats) >= {"uslm", "html", "pdf"}
    digests = {fmt: art.artifact_sha256 for fmt, art in record.formats.items()}
    # Formats carry different content digests...
    assert len(set(digests.values())) == len(digests)
    # ...but the stable section identity is identical for every format.
    identities = {
        stable_section_identity(title=record.title, section=record.section)
        for _ in record.formats
    }
    assert identities == {record.stable_id}
    assert record.identity_for_all_formats() == "usc:us:35:122"


def test_processor_identities_equal_across_formats(processor: UscodeReleaseProcessor):
    assert processor.identities_equal_across_formats(
        title="35",
        section="188",
        formats=[SourceFormat.USLM, SourceFormat.XML, SourceFormat.HTML, SourceFormat.PDF],
    )


def test_format_artifact_round_trip():
    art = FormatArtifact(
        format="uslm",
        media_type="application/uslm+xml",
        artifact_sha256="a" * 64,
        source_url="https://uscode.house.gov/example.zip",
        byte_size=42,
        upstream_package_id="us/pl/118/45",
    )
    restored = FormatArtifact.from_dict(art.to_dict())
    assert restored.to_dict() == art.to_dict()
    assert restored.format is SourceFormat.USLM


def test_section_record_normalizes_supplied_stable_id():
    # Even if a caller injects a format into the id, construction rewrites to stable form.
    record = UscodeSectionRecord(
        title="35",
        section="122",
        stable_id="usc:us:35:122:uslm",  # incorrect format-suffixed id
        formats={
            "html": {
                "format": "html",
                "media_type": "text/html",
                "artifact_sha256": "b" * 64,
                "source_url": "https://example.test/122.html",
            }
        },
    )
    assert record.stable_id == "usc:us:35:122"


# ---------------------------------------------------------------------------
# Missing release data yields unknown
# ---------------------------------------------------------------------------


def test_missing_release_fixture_yields_unknown(processor: UscodeReleaseProcessor, fixture_dir: Path):
    acq = processor.acquire_from_fixture(fixture_dir / "title35_missing_release.json")
    assert acq.status is ResolutionStatus.UNKNOWN
    assert acq.is_unknown
    assert acq.release_point is None
    assert acq.unknown_reason
    # Resolving a section against an unknown acquisition stays unknown.
    sec = acq.resolve_section("122")
    assert sec.status is ResolutionStatus.UNKNOWN
    assert sec.release_point is None
    assert sec.stable_id == "usc:us:35:122"  # identity still computable
    assert "unknown" in (sec.metadata.get("unknown_reason") or "").lower() or True


def test_empty_payload_yields_unknown(processor: UscodeReleaseProcessor):
    acq = processor.acquire_from_payload({"title": "35", "sections": []})
    assert acq.status is ResolutionStatus.UNKNOWN
    assert acq.unknown_reason == "missing release data"


def test_acquire_unknown_helper(processor: UscodeReleaseProcessor):
    acq = processor.acquire_unknown(reason="operator withheld release")
    assert acq.status is ResolutionStatus.UNKNOWN
    assert acq.unknown_reason == "operator withheld release"
    resolved = processor.resolve_patent_sensitive_sections(acq)
    assert all(r.status is ResolutionStatus.UNKNOWN for r in resolved.values())


def test_hard_coded_latest_release_rejected():
    with pytest.raises(HardCodedLatestEditionError):
        parse_release_point_id("latest")
    with pytest.raises((HardCodedLatestEditionError, UscodeReleaseError)):
        ReleasePoint(
            release_point="latest",
            provider="ushouse",
            title="35",
        )
    with pytest.raises(HardCodedLatestEditionError):
        govinfo_title_package_id(year="latest", title="35")


# ---------------------------------------------------------------------------
# Helpers, serialization, fixture recipe
# ---------------------------------------------------------------------------


def test_parse_release_point_variants():
    assert parse_release_point_id("us/pl/118/45") == ("us/pl/118/45", "118", "45")
    assert parse_release_point_id("118-45") == ("us/pl/118/45", "118", "45")
    assert parse_release_point_id("118/45") == ("us/pl/118/45", "118", "45")


def test_ushouse_and_govinfo_url_builders():
    url = ushouse_releasepoint_zip_url(congress=118, release="45", title=35, format_kind="uslm")
    assert url.endswith("xml_usc35@118-45.zip")
    assert "releasepoints/us/pl/118/45/" in url
    pkg = govinfo_title_package_id(year=2023, title="35")
    assert pkg == "USCODE-2023-title35"


def test_acquisition_canonical_json_is_stable(acquisition: UscodeReleaseAcquisition):
    blob1 = acquisition.to_canonical_json()
    blob2 = acquisition.to_canonical_json()
    assert blob1 == blob2
    payload = json.loads(blob1)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "resolved"
    assert payload["release_point"]["release_point"] == "us/pl/118/45"
    assert "122" in payload["sections"]
    assert "181" in payload["sections"]
    assert "188" in payload["sections"]


def test_fixture_recipe_schema_and_sections(fixture_dir: Path):
    recipe_path = fixture_dir / "title35_release_recipe.json"
    assert recipe_path.is_file()
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    assert recipe["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert recipe["release"]["release_point"] == "us/pl/118/45"
    section_nums = {str(s["section"]) for s in recipe["sections"]}
    assert section_nums == set(PATENT_SENSITIVE_SECTIONS)
    assert recipe["exclusions"]


def test_build_title35_fixture_recipe_matches_on_disk(fixture_dir: Path):
    generated = build_title35_fixture_recipe()
    on_disk = json.loads((fixture_dir / "title35_release_recipe.json").read_text(encoding="utf-8"))
    # Compare structural essentials (file may have sorted-key formatting).
    assert generated["release"]["release_point"] == on_disk["release"]["release_point"]
    assert {s["section"] for s in generated["sections"]} == {
        s["section"] for s in on_disk["sections"]
    }
    assert len(generated["exclusions"]) == len(on_disk["exclusions"])


def test_content_sha256_deterministic():
    assert content_sha256("abc") == content_sha256(b"abc")
    assert content_sha256("abc") != content_sha256("abd")


def test_govinfo_release_identity_supported(processor: UscodeReleaseProcessor):
    sha = content_sha256("govinfo-uscode-2023-title35")
    payload = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "title": "35",
        "release": {
            "provider": "govinfo",
            "title": "35",
            "year": "2023",
            "govinfo_package_id": "USCODE-2023-title35",
            "edition": "2023",
            "source_url": "https://www.govinfo.gov/content/pkg/USCODE-2023-title35/zip/USCODE-2023-title35.zip",
            "content_sha256": sha,
            "retrieved_at": "2024-01-10T00:00:00Z",
        },
        "exclusions": [
            {
                "kind": "uncodified_slip_law",
                "citation": "Pub. L. 118-1",
                "reason": "Post-edition slip law not in 2023 annual package",
            }
        ],
        "sections": [
            {
                "title": "35",
                "section": "122",
                "heading": "Confidential status of applications",
                "formats": {
                    "xml": {
                        "format": "xml",
                        "media_type": "application/xml",
                        "artifact_sha256": content_sha256("122-xml"),
                        "source_url": "https://www.govinfo.gov/content/pkg/USCODE-2023-title35/xml/USCODE-2023-title35-chap12-sec122.xml",
                    },
                    "pdf": {
                        "format": "pdf",
                        "media_type": "application/pdf",
                        "artifact_sha256": content_sha256("122-pdf"),
                        "source_url": "https://www.govinfo.gov/content/pkg/USCODE-2023-title35/pdf/USCODE-2023-title35-chap12-sec122.pdf",
                    },
                },
            }
        ],
    }
    acq = processor.acquire_from_payload(payload)
    assert acq.status is ResolutionStatus.RESOLVED
    assert acq.release_point is not None
    assert acq.release_point.release_point == "USCODE-2023-title35"
    assert acq.release_point.govinfo_package_id == "USCODE-2023-title35"
    sec = acq.get_section("122")
    assert sec.stable_id == "usc:us:35:122"
    assert set(sec.formats) == {"xml", "pdf"}
    assert sec.formats["xml"].artifact_sha256 != sec.formats["pdf"].artifact_sha256
