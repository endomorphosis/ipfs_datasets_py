"""Unit tests for Title 37 CFR current/historical acquisition (PATLAW-012).

Acceptance:

* Current and historical fixtures replay.
* eCFR is labeled unofficial presentation.
* Annual official artifact identity remains separate.
* Pagination / retry / 429 / schema failures are typed.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    HardCodedLatestEditionError,
    IdentityRole,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.ecfr_crosscheck_processor import (
    DEFAULT_CROSSCHECK_SECTIONS,
    DUTY_OF_DISCLOSURE_SECTION,
    FIXTURE_SCHEMA_VERSION as ECFR_FIXTURE_SCHEMA,
    SCHEMA_VERSION as ECFR_SCHEMA,
    EcfrCrosscheckAcquisition,
    EcfrCrosscheckError,
    EcfrCrosscheckProcessor,
    EcfrPaginationError,
    EcfrRateLimitError,
    EcfrRetryExhaustedError,
    EcfrSchemaError,
    EcfrSectionRecord,
    EcfrVersionPoint,
    FailureKind,
    FixtureSchemaError as EcfrFixtureSchemaError,
    ResolutionStatus as EcfrResolutionStatus,
    SectionNotFoundError as EcfrSectionNotFoundError,
    TypedFailure,
    build_ecfr_current_fixture_recipe,
    build_ecfr_historical_fixture_recipe,
    content_sha256 as ecfr_content_sha256,
    default_fixture_dir as ecfr_default_fixture_dir,
    ecfr_full_xml_url,
    ecfr_title_structure_url,
    normalize_section_token,
    stable_section_identity,
    version_identity,
    write_default_fixtures as write_ecfr_fixtures,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.cfr_annual_processor import (
    FIXTURE_SCHEMA_VERSION as ANNUAL_FIXTURE_SCHEMA,
    SCHEMA_VERSION as ANNUAL_SCHEMA,
    AnnualPackage,
    CfrAnnualAcquisition,
    CfrAnnualError,
    CfrAnnualProcessor,
    CfrPaginationError,
    CfrRateLimitError,
    CfrRetryExhaustedError,
    CfrSchemaError,
    CfrSectionRecord,
    FormatArtifact,
    MissingPackageError,
    ResolutionStatus as AnnualResolutionStatus,
    SectionNotFoundError as AnnualSectionNotFoundError,
    SourceFormat,
    build_cfr_annual_fixture_recipe,
    content_sha256 as annual_content_sha256,
    default_fixture_dir as annual_default_fixture_dir,
    govinfo_cfr_package_id,
    parse_govinfo_cfr_package_id,
    write_default_fixtures as write_annual_fixtures,
)

# tests/unit/processors/legal_scrapers/federal_scrapers/this_file.py
# parents[4] == tests/
_REPO_FIXTURE_DIR = (
    Path(__file__).resolve().parents[4]
    / "fixtures"
    / "legal_data"
    / "patent_authorities"
    / "cfr"
)


def _fixture_dir() -> Path:
    candidate = ecfr_default_fixture_dir()
    if (candidate / "ecfr_current_recipe.json").is_file() and (
        candidate / "cfr_annual_recipe.json"
    ).is_file():
        return candidate
    if (_REPO_FIXTURE_DIR / "ecfr_current_recipe.json").is_file() and (
        _REPO_FIXTURE_DIR / "cfr_annual_recipe.json"
    ).is_file():
        return _REPO_FIXTURE_DIR
    write_annual_fixtures(_REPO_FIXTURE_DIR)
    return _REPO_FIXTURE_DIR


@pytest.fixture(scope="module")
def fixture_dir() -> Path:
    return _fixture_dir()


@pytest.fixture
def ecfr_processor(fixture_dir: Path) -> EcfrCrosscheckProcessor:
    return EcfrCrosscheckProcessor(fixture_dir=fixture_dir)


@pytest.fixture
def annual_processor(fixture_dir: Path) -> CfrAnnualProcessor:
    return CfrAnnualProcessor(fixture_dir=fixture_dir)


@pytest.fixture
def current_acquisition(ecfr_processor: EcfrCrosscheckProcessor) -> EcfrCrosscheckAcquisition:
    return ecfr_processor.acquire_from_fixture()


@pytest.fixture
def historical_acquisition(
    ecfr_processor: EcfrCrosscheckProcessor, fixture_dir: Path
) -> EcfrCrosscheckAcquisition:
    return ecfr_processor.acquire_from_fixture(fixture_dir / "ecfr_historical_recipe.json")


@pytest.fixture
def annual_acquisition(annual_processor: CfrAnnualProcessor) -> CfrAnnualAcquisition:
    return annual_processor.acquire_from_fixture()


# ---------------------------------------------------------------------------
# Current and historical fixtures replay
# ---------------------------------------------------------------------------


def test_current_fixture_replays(current_acquisition: EcfrCrosscheckAcquisition):
    assert current_acquisition.status is EcfrResolutionStatus.RESOLVED
    assert current_acquisition.version is not None
    assert current_acquisition.version.up_to_date_as_of == date(2024, 7, 1)
    assert current_acquisition.version.is_current_snapshot is True
    assert current_acquisition.version.content_sha256
    assert len(current_acquisition.version.content_sha256) == 64
    assert "structure" in current_acquisition.packages
    assert "full_xml" in current_acquisition.packages
    assert current_acquisition.packages["full_xml"].content_kind.value == "full_xml"
    assert date(2024, 7, 1) in current_acquisition.version_history
    # Patent-relevant sections resolve.
    for sec in DEFAULT_CROSSCHECK_SECTIONS:
        record = current_acquisition.get_section(sec)
        assert record.status is EcfrResolutionStatus.RESOLVED
        assert record.stable_id == f"cfr:us:37:{sec}"
        assert record.up_to_date_as_of == date(2024, 7, 1)
        assert record.content_sha256
    duty = current_acquisition.get_section(DUTY_OF_DISCLOSURE_SECTION)
    assert duty.amendment is not None
    assert duty.amendment.effective_date is not None
    assert duty.heading and "disclose" in duty.heading.lower()


def test_historical_fixture_replays(historical_acquisition: EcfrCrosscheckAcquisition):
    assert historical_acquisition.status is EcfrResolutionStatus.RESOLVED
    assert historical_acquisition.version is not None
    assert historical_acquisition.version.up_to_date_as_of == date(2020, 1, 1)
    assert historical_acquisition.version.is_current_snapshot is False
    assert historical_acquisition.version.version_id == "ecfr-title-37-as-of-2020-01-01"
    # Historical reconstruction is not the current snapshot.
    assert historical_acquisition.up_to_date_as_of == date(2020, 1, 1)
    record = historical_acquisition.get_section("1.56")
    assert record.status is EcfrResolutionStatus.RESOLVED
    assert record.up_to_date_as_of == date(2020, 1, 1)
    assert "historical" in (record.text_excerpt or "").lower() or record.text_excerpt
    assert date(2020, 1, 1) in historical_acquisition.version_history


def test_current_and_historical_have_distinct_identities(
    current_acquisition: EcfrCrosscheckAcquisition,
    historical_acquisition: EcfrCrosscheckAcquisition,
):
    assert current_acquisition.version is not None
    assert historical_acquisition.version is not None
    assert (
        current_acquisition.version.content_sha256
        != historical_acquisition.version.content_sha256
    )
    assert (
        current_acquisition.version.version_id != historical_acquisition.version.version_id
    )
    cur_sec = current_acquisition.get_section("1.56")
    hist_sec = historical_acquisition.get_section("1.56")
    # Stable citation identity is the same; content digests differ by as-of date.
    assert cur_sec.stable_id == hist_sec.stable_id == "cfr:us:37:1.56"
    assert cur_sec.content_sha256 != hist_sec.content_sha256


def test_annual_fixture_replays(annual_acquisition: CfrAnnualAcquisition):
    assert annual_acquisition.status is AnnualResolutionStatus.RESOLVED
    assert annual_acquisition.package is not None
    pkg = annual_acquisition.package
    assert pkg.year == "2024"
    assert pkg.package_id == "CFR-2024-title37"
    assert pkg.edition == "annual-2024"
    assert "latest" not in pkg.edition.lower()
    assert "latest" not in pkg.package_id.lower()
    assert pkg.content_sha256 and len(pkg.content_sha256) == 64
    assert set(pkg.formats) >= {"xml", "pdf"}
    for sec in DEFAULT_CROSSCHECK_SECTIONS:
        record = annual_acquisition.get_section(sec)
        assert record.status is AnnualResolutionStatus.RESOLVED
        assert record.stable_id == f"cfr:us:37:{sec}"
        assert record.package_id == "CFR-2024-title37"
        assert record.year == "2024"
        assert set(record.formats) >= {"xml", "pdf"}
        # Format digests differ; stable identity does not.
        digests = {a.artifact_sha256 for a in record.formats.values()}
        assert len(digests) == len(record.formats)
        assert record.identity_for_all_formats() == f"cfr:us:37:{sec}"


def test_registry_registration_on_acquire(
    ecfr_processor: EcfrCrosscheckProcessor,
    annual_processor: CfrAnnualProcessor,
    current_acquisition: EcfrCrosscheckAcquisition,
    annual_acquisition: CfrAnnualAcquisition,
):
    ecfr_auth = current_acquisition.authority_source
    annual_auth = annual_acquisition.authority_source
    assert ecfr_auth is not None and annual_auth is not None
    assert ecfr_auth.source_key in ecfr_processor.registry
    assert annual_auth.source_key in annual_processor.registry
    assert ecfr_processor.registry.get(ecfr_auth.source_key).authority_tier is (
        AuthorityTier.UNOFFICIAL_CURRENT
    )
    assert annual_processor.registry.get(annual_auth.source_key).authority_tier is (
        AuthorityTier.OFFICIAL_BASE
    )


# ---------------------------------------------------------------------------
# eCFR is labeled unofficial presentation
# ---------------------------------------------------------------------------


def test_ecfr_labeled_unofficial_presentation(current_acquisition: EcfrCrosscheckAcquisition):
    assert current_acquisition.is_unofficial is True
    assert "unofficial" in current_acquisition.presentation_label.lower()
    auth = current_acquisition.authority_source
    assert auth is not None
    assert auth.authority_tier is AuthorityTier.UNOFFICIAL_CURRENT
    # Official artifact must NOT be set for eCFR-only presentation.
    assert auth.official_artifact is None
    assert auth.derived_presentation is not None
    assert auth.derived_presentation.role is IdentityRole.DERIVED_PRESENTATION
    notes = (auth.notes or "") + (current_acquisition.notes or "")
    assert "unofficial" in notes.lower()
    assert auth.metadata.get("presentation_label") == "unofficial presentation" or (
        "unofficial" in str(auth.metadata.get("presentation_label", "")).lower()
    )


def test_ecfr_does_not_impersonate_official_annual(
    current_acquisition: EcfrCrosscheckAcquisition,
    annual_acquisition: CfrAnnualAcquisition,
):
    ecfr_auth = current_acquisition.authority_source
    annual_auth = annual_acquisition.authority_source
    assert ecfr_auth is not None and annual_auth is not None
    assert ecfr_auth.authority_tier is not AuthorityTier.OFFICIAL_BASE
    assert annual_auth.authority_tier is AuthorityTier.OFFICIAL_BASE
    assert ecfr_auth.collection == "eCFR"
    assert annual_auth.collection == "CFR"
    assert ecfr_auth.source_key != annual_auth.source_key


# ---------------------------------------------------------------------------
# Annual official artifact identity remains separate
# ---------------------------------------------------------------------------


def test_annual_official_identity_separate_from_ecfr(
    annual_acquisition: CfrAnnualAcquisition,
    current_acquisition: EcfrCrosscheckAcquisition,
):
    assert annual_acquisition.identities_remain_separate() is True
    auth = annual_acquisition.authority_source
    assert auth is not None
    assert auth.official_artifact is not None
    assert auth.official_artifact.role is IdentityRole.OFFICIAL_ARTIFACT
    # Dual identity present with distinct digests.
    assert auth.derived_presentation is not None
    assert auth.derived_presentation.role is IdentityRole.DERIVED_PRESENTATION
    assert (
        auth.official_artifact.artifact_sha256
        != auth.derived_presentation.artifact_sha256
    )
    # Cross-module: eCFR package sha differs from annual package sha.
    assert current_acquisition.version is not None
    assert annual_acquisition.package is not None
    assert (
        current_acquisition.version.content_sha256
        != annual_acquisition.package.content_sha256
    )
    assert annual_acquisition.ecfr_presentation_sha256 is not None
    assert (
        annual_acquisition.ecfr_presentation_sha256
        != annual_acquisition.package.content_sha256
    )


def test_annual_without_ecfr_presentation_still_official(fixture_dir: Path):
    recipe = build_cfr_annual_fixture_recipe(include_ecfr_presentation=False)
    processor = CfrAnnualProcessor(fixture_dir=fixture_dir)
    acq = processor.acquire_from_payload(recipe)
    assert acq.status is AnnualResolutionStatus.RESOLVED
    auth = acq.authority_source
    assert auth is not None
    assert auth.official_artifact is not None
    assert auth.derived_presentation is None
    assert auth.authority_tier is AuthorityTier.OFFICIAL_BASE
    assert acq.identities_remain_separate() is True


def test_identical_ecfr_and_official_sha_rejected(annual_processor: CfrAnnualProcessor):
    package_sha = annual_content_sha256("collision-test-package")
    payload = {
        "schema_version": ANNUAL_FIXTURE_SCHEMA,
        "title": "37",
        "package": {
            "provider": "govinfo",
            "year": "2023",
            "title": "37",
            "package_id": "CFR-2023-title37",
            "content_sha256": package_sha,
            "source_url": "https://www.govinfo.gov/content/pkg/CFR-2023-title37/xml/CFR-2023-title37.xml",
            "formats": {
                "xml": {
                    "format": "xml",
                    "media_type": "application/xml",
                    "artifact_sha256": package_sha,
                    "source_url": "https://www.govinfo.gov/content/pkg/CFR-2023-title37/xml/CFR-2023-title37.xml",
                    "upstream_package_id": "CFR-2023-title37",
                }
            },
        },
        "sections": [],
        # Same digest as official — must fail closed.
        "ecfr_presentation": {
            "provider": "ecfr",
            "source_id": "ecfr:bad",
            "artifact_sha256": package_sha,
            "source_url": "https://www.ecfr.gov/current/title-37",
            "media_type": "application/xml",
        },
    }
    with pytest.raises(CfrAnnualError, match="separate"):
        annual_processor.acquire_from_payload(payload)


# ---------------------------------------------------------------------------
# Pagination / retry / 429 / schema failures are typed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,exc_type",
    [
        (FailureKind.PAGINATION, EcfrPaginationError),
        (FailureKind.RETRY_EXHAUSTED, EcfrRetryExhaustedError),
        (FailureKind.RATE_LIMIT_429, EcfrRateLimitError),
        (FailureKind.SCHEMA, EcfrSchemaError),
    ],
)
def test_ecfr_typed_failures_raise(
    ecfr_processor: EcfrCrosscheckProcessor,
    fixture_dir: Path,
    kind: FailureKind,
    exc_type: type,
):
    path = fixture_dir / f"ecfr_failure_{kind.value}.json"
    assert path.is_file()
    # Replay without raising keeps acquisition usable and records failure.
    acq = ecfr_processor.acquire_from_fixture(path, raise_recorded_failures=False)
    assert acq.failures
    assert acq.failures[0].kind is kind
    # Raising surfaces the typed exception.
    with pytest.raises(exc_type):
        ecfr_processor.acquire_from_fixture(path, raise_recorded_failures=True)
    with pytest.raises(exc_type):
        ecfr_processor.raise_typed_failure(kind)


def test_ecfr_classify_http_429(ecfr_processor: EcfrCrosscheckProcessor):
    failure = ecfr_processor.classify_http_failure(
        response_status=429, retry_after=12.5, attempts=2
    )
    assert failure.kind is FailureKind.RATE_LIMIT_429
    assert failure.response_status == 429
    assert failure.retry_after == 12.5
    with pytest.raises(EcfrRateLimitError) as exc_info:
        failure.raise_error()
    assert exc_info.value.response_status == 429
    assert exc_info.value.retry_after == 12.5


def test_ecfr_classify_retry_exhausted(ecfr_processor: EcfrCrosscheckProcessor):
    failure = ecfr_processor.classify_http_failure(
        response_status=503,
        attempts=ecfr_processor.retry_cache_policy.max_attempts,
    )
    assert failure.kind is FailureKind.RETRY_EXHAUSTED
    with pytest.raises(EcfrRetryExhaustedError):
        failure.raise_error()


def test_ecfr_pagination_validation(ecfr_processor: EcfrCrosscheckProcessor):
    ecfr_processor.validate_pagination(page=1, page_size=100, total_items=250)
    with pytest.raises(EcfrPaginationError):
        ecfr_processor.validate_pagination(page=0, page_size=100)
    with pytest.raises(EcfrPaginationError):
        ecfr_processor.validate_pagination(page=5, page_size=100, total_items=100)
    with pytest.raises(EcfrPaginationError):
        ecfr_processor.validate_pagination(
            page=2,
            page_size=50,
            next_page_token="tok-a",
            seen_tokens=["tok-a"],
        )


def test_ecfr_schema_validation(ecfr_processor: EcfrCrosscheckProcessor):
    ok = ecfr_processor.validate_api_schema(
        {"meta": {}, "data": []}, required_keys=("meta", "data")
    )
    assert "meta" in ok
    with pytest.raises(EcfrSchemaError):
        ecfr_processor.validate_api_schema({"data": []}, required_keys=("meta", "data"))
    with pytest.raises(EcfrSchemaError):
        ecfr_processor.validate_api_schema(["not", "a", "map"], required_keys=("meta",))


@pytest.mark.parametrize(
    "kind,exc_type",
    [
        (FailureKind.PAGINATION, CfrPaginationError),
        (FailureKind.RETRY_EXHAUSTED, CfrRetryExhaustedError),
        (FailureKind.RATE_LIMIT_429, CfrRateLimitError),
        (FailureKind.SCHEMA, CfrSchemaError),
    ],
)
def test_annual_typed_failures_raise(
    annual_processor: CfrAnnualProcessor, kind: FailureKind, exc_type: type
):
    with pytest.raises(exc_type):
        annual_processor.raise_typed_failure(kind)
    failure = annual_processor.classify_http_failure(
        response_status=429 if kind is FailureKind.RATE_LIMIT_429 else 503,
        attempts=(
            annual_processor.retry_cache_policy.max_attempts
            if kind is FailureKind.RETRY_EXHAUSTED
            else 1
        ),
        page=-1 if kind is FailureKind.PAGINATION else None,
        message=f"test {kind.value}",
    )
    # For schema, craft explicitly.
    if kind is FailureKind.SCHEMA:
        failure = TypedFailure(kind=FailureKind.SCHEMA, message="schema boom")
    if kind is FailureKind.PAGINATION:
        # classify with page=-1 yields pagination
        assert failure.kind is FailureKind.PAGINATION
    with pytest.raises(exc_type):
        annual_processor.raise_typed_failure(failure)


def test_annual_pagination_and_schema(annual_processor: CfrAnnualProcessor):
    annual_processor.validate_pagination(page=1, page_size=20, total_items=40)
    with pytest.raises(CfrPaginationError):
        annual_processor.validate_pagination(page=0, page_size=20)
    with pytest.raises(CfrSchemaError):
        annual_processor.validate_api_schema({}, required_keys=("packages",))


# ---------------------------------------------------------------------------
# Missing data / hard-coded latest / helpers
# ---------------------------------------------------------------------------


def test_missing_ecfr_version_yields_unknown(
    ecfr_processor: EcfrCrosscheckProcessor, fixture_dir: Path
):
    acq = ecfr_processor.acquire_from_fixture(fixture_dir / "ecfr_missing_version.json")
    assert acq.status is EcfrResolutionStatus.UNKNOWN
    assert acq.is_unknown
    assert acq.version is None
    sec = acq.resolve_section("1.56")
    assert sec.status is EcfrResolutionStatus.UNKNOWN
    assert sec.stable_id == "cfr:us:37:1.56"


def test_missing_annual_package_yields_unknown(
    annual_processor: CfrAnnualProcessor, fixture_dir: Path
):
    acq = annual_processor.acquire_from_fixture(
        fixture_dir / "cfr_annual_missing_package.json"
    )
    assert acq.status is AnnualResolutionStatus.UNKNOWN
    assert acq.is_unknown
    assert acq.package is None
    sec = acq.resolve_section("1.56")
    assert sec.status is AnnualResolutionStatus.UNKNOWN
    assert sec.stable_id == "cfr:us:37:1.56"


def test_hard_coded_latest_rejected():
    # Concrete version identity is fine.
    assert version_identity(title="37", up_to_date_as_of=date(2024, 1, 1)) == (
        "ecfr-title-37-as-of-2024-01-01"
    )
    # Hard-coded "latest" tokens are rejected.
    with pytest.raises(HardCodedLatestEditionError):
        EcfrVersionPoint(up_to_date_as_of="latest", title="37")  # type: ignore[arg-type]
    with pytest.raises(HardCodedLatestEditionError):
        govinfo_cfr_package_id(year="latest", title="37")
    with pytest.raises((HardCodedLatestEditionError, MissingPackageError, CfrAnnualError)):
        AnnualPackage(year="latest", title="37")


def test_section_token_normalization():
    forms = ["1.56", "§ 1.56", "37 CFR 1.56", "section 1.56", "37 C.F.R. § 1.56"]
    tokens = {normalize_section_token(f) for f in forms}
    assert tokens == {"1.56"}
    identities = {stable_section_identity(title="37", section=f) for f in forms}
    assert identities == {"cfr:us:37:1.56"}


def test_missing_section_raises(
    current_acquisition: EcfrCrosscheckAcquisition,
    annual_acquisition: CfrAnnualAcquisition,
):
    with pytest.raises(EcfrSectionNotFoundError):
        current_acquisition.get_section("99.999")
    with pytest.raises(AnnualSectionNotFoundError):
        annual_acquisition.get_section("99.999")


def test_url_builders():
    struct = ecfr_title_structure_url(title=37, date_as_of="2024-07-01")
    assert struct.endswith("structure/2024-07-01/title-37.json")
    full = ecfr_full_xml_url(title="37", date_as_of=date(2024, 7, 1))
    assert full.endswith("full/2024-07-01/title-37.xml")
    pid = govinfo_cfr_package_id(year=2024, title="37")
    assert pid == "CFR-2024-title37"
    assert parse_govinfo_cfr_package_id(pid) == ("CFR-2024-title37", "2024", "37")


def test_canonical_json_stable(
    current_acquisition: EcfrCrosscheckAcquisition,
    annual_acquisition: CfrAnnualAcquisition,
):
    assert current_acquisition.to_canonical_json() == current_acquisition.to_canonical_json()
    assert annual_acquisition.to_canonical_json() == annual_acquisition.to_canonical_json()
    ecfr_payload = json.loads(current_acquisition.to_canonical_json())
    annual_payload = json.loads(annual_acquisition.to_canonical_json())
    assert ecfr_payload["schema_version"] == ECFR_SCHEMA
    assert annual_payload["schema_version"] == ANNUAL_SCHEMA
    assert ecfr_payload["status"] == "resolved"
    assert annual_payload["status"] == "resolved"
    assert "1.56" in ecfr_payload["sections"]
    assert "1.56" in annual_payload["sections"]


def test_fixture_recipes_on_disk(fixture_dir: Path):
    current = json.loads((fixture_dir / "ecfr_current_recipe.json").read_text(encoding="utf-8"))
    historical = json.loads(
        (fixture_dir / "ecfr_historical_recipe.json").read_text(encoding="utf-8")
    )
    annual = json.loads((fixture_dir / "cfr_annual_recipe.json").read_text(encoding="utf-8"))
    assert current["schema_version"] == ECFR_FIXTURE_SCHEMA
    assert historical["schema_version"] == ECFR_FIXTURE_SCHEMA
    assert annual["schema_version"] == ANNUAL_FIXTURE_SCHEMA
    assert current["version"]["is_current_snapshot"] is True
    assert historical["version"]["is_current_snapshot"] is False
    assert annual["package"]["package_id"] == "CFR-2024-title37"
    assert "unofficial" in current["presentation_label"].lower()
    assert annual.get("ecfr_presentation_sha256")
    assert annual["ecfr_presentation_sha256"] != annual["package"]["content_sha256"]


def test_build_recipes_match_essentials(fixture_dir: Path):
    gen_cur = build_ecfr_current_fixture_recipe()
    gen_hist = build_ecfr_historical_fixture_recipe()
    gen_ann = build_cfr_annual_fixture_recipe()
    on_cur = json.loads((fixture_dir / "ecfr_current_recipe.json").read_text(encoding="utf-8"))
    on_hist = json.loads(
        (fixture_dir / "ecfr_historical_recipe.json").read_text(encoding="utf-8")
    )
    on_ann = json.loads((fixture_dir / "cfr_annual_recipe.json").read_text(encoding="utf-8"))
    assert gen_cur["version"]["up_to_date_as_of"] == on_cur["version"]["up_to_date_as_of"]
    assert gen_hist["version"]["up_to_date_as_of"] == on_hist["version"]["up_to_date_as_of"]
    assert gen_ann["package"]["package_id"] == on_ann["package"]["package_id"]
    assert {s["section"] for s in gen_cur["sections"]} == {
        s["section"] for s in on_cur["sections"]
    }


def test_format_artifact_round_trip():
    art = FormatArtifact(
        format="xml",
        media_type="application/xml",
        artifact_sha256="a" * 64,
        source_url="https://www.govinfo.gov/content/pkg/CFR-2024-title37/xml/CFR-2024-title37.xml",
        byte_size=42,
        upstream_package_id="CFR-2024-title37",
    )
    restored = FormatArtifact.from_dict(art.to_dict())
    assert restored.to_dict() == art.to_dict()
    assert restored.format is SourceFormat.XML
    assert restored.role is IdentityRole.OFFICIAL_ARTIFACT


def test_resolve_crosscheck_and_patent_apis(
    ecfr_processor: EcfrCrosscheckProcessor,
    annual_processor: CfrAnnualProcessor,
):
    ecfr_resolved = ecfr_processor.resolve_crosscheck_sections()
    annual_resolved = annual_processor.resolve_patent_sections()
    assert set(ecfr_resolved) == set(DEFAULT_CROSSCHECK_SECTIONS)
    assert set(annual_resolved) == set(DEFAULT_CROSSCHECK_SECTIONS)
    for sec, record in ecfr_resolved.items():
        assert record.status is EcfrResolutionStatus.RESOLVED
        assert record.stable_id == stable_section_identity(title="37", section=sec)
    for sec, record in annual_resolved.items():
        assert record.status is AnnualResolutionStatus.RESOLVED
        assert isinstance(record, CfrSectionRecord)


def test_content_sha256_deterministic():
    assert ecfr_content_sha256("abc") == annual_content_sha256(b"abc")
    assert ecfr_content_sha256("abc") != ecfr_content_sha256("abd")


def test_unsupported_ecfr_fixture_schema(ecfr_processor: EcfrCrosscheckProcessor, tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"schema_version": "totally-other-v1", "title": "37"}),
        encoding="utf-8",
    )
    with pytest.raises(EcfrFixtureSchemaError):
        ecfr_processor.load_fixture_package(bad)


def test_section_record_rewrites_stable_id():
    record = EcfrSectionRecord(
        title="37",
        section="1.56",
        stable_id="cfr:us:37:1.56:xml",  # incorrect format-suffixed id
        content_sha256="b" * 64,
        source_url="https://www.ecfr.gov/current/title-37/section-1.56",
    )
    assert record.stable_id == "cfr:us:37:1.56"
