"""Unit tests for versioned MPEP / forms / fees / later guidance (PATLAW-015).

Acceptance:

* Guidance tier/cutoff is visible in every record.
* Later guidance can supersede inconsistent manual text without elevating
  either to law.
* Unavailable or changed documents yield explicit freshness gaps.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    HardCodedLatestEditionError,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.mpep_guidance_processor import (
    FIXTURE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    BindingElevationError,
    FreshnessGap,
    FreshnessGapKind,
    GuidanceEdition,
    GuidanceKind,
    GuidanceNotFoundError,
    GuidanceRecord,
    MissingCutoffError,
    MpepGuidanceError,
    MpepGuidanceProcessor,
    ResolutionStatus,
    SupersessionEdge,
    SupersessionRelation,
    build_mpep_guidance_fixture_recipe,
    content_sha256,
    default_fixture_dir,
    normalize_form_paragraph,
    normalize_mpep_section,
    parse_mpep_edition_revision,
    stable_guidance_identity,
    write_default_fixtures,
)

# tests/unit/processors/legal_scrapers/federal_scrapers/this_file.py
# parents[4] == tests/
_REPO_FIXTURE_DIR = (
    Path(__file__).resolve().parents[4]
    / "fixtures"
    / "legal_data"
    / "patent_authorities"
    / "guidance"
)


def _fixture_dir() -> Path:
    candidate = default_fixture_dir()
    if (candidate / "mpep_guidance_recipe.json").is_file():
        return candidate
    if (_REPO_FIXTURE_DIR / "mpep_guidance_recipe.json").is_file():
        return _REPO_FIXTURE_DIR
    write_default_fixtures(_REPO_FIXTURE_DIR)
    return _REPO_FIXTURE_DIR


@pytest.fixture(scope="module")
def fixture_dir() -> Path:
    return _fixture_dir()


@pytest.fixture
def processor(fixture_dir: Path) -> MpepGuidanceProcessor:
    return MpepGuidanceProcessor(fixture_dir=fixture_dir)


@pytest.fixture
def acquisition(processor: MpepGuidanceProcessor):
    return processor.acquire_from_fixture()


# ---------------------------------------------------------------------------
# Guidance tier / cutoff visible in every record
# ---------------------------------------------------------------------------


def test_edition_cutoff_is_recorded(acquisition):
    assert acquisition.status in (
        ResolutionStatus.RESOLVED,
        ResolutionStatus.PARTIAL,
    )
    assert acquisition.edition is not None
    ed = acquisition.edition
    assert ed.edition == "9"
    assert ed.revision == "07.2022"
    assert ed.cutoff == date(2022, 7, 1)
    assert "latest" not in ed.edition.lower()
    assert "latest" not in ed.revision.lower()
    assert ed.content_sha256 is not None
    assert len(ed.content_sha256) == 64


def test_every_record_exposes_guidance_tier_and_cutoff(
    processor: MpepGuidanceProcessor, acquisition
):
    assert processor.every_record_exposes_tier_and_cutoff(acquisition)
    assert acquisition.records
    for record in acquisition.records.values():
        assert record.authority_tier is AuthorityTier.GUIDANCE
        assert record.authority_tier.value == "guidance"
        assert record.cutoff is not None
        assert isinstance(record.cutoff, date)
        assert record.cutoff == date(2022, 7, 1)
        assert record.is_binding is False
        payload = record.to_dict()
        assert payload["authority_tier"] == "guidance"
        assert payload["cutoff"] == "2022-07-01"
        assert payload["is_binding"] is False


def test_authority_sources_are_guidance_tier(acquisition):
    assert acquisition.authority_sources
    for source in acquisition.authority_sources.values():
        assert source.authority_tier is AuthorityTier.GUIDANCE
        # Cutoff is carried in metadata and/or effective_start.
        assert (
            source.metadata.get("cutoff") == "2022-07-01"
            or source.effective_start == date(2022, 7, 1)
        )
        assert source.metadata.get("is_binding") is False


def test_freshness_gaps_also_label_guidance_tier(acquisition):
    assert acquisition.freshness_gaps
    for gap in acquisition.freshness_gaps:
        assert gap.authority_tier is AuthorityTier.GUIDANCE
        assert gap.cutoff == date(2022, 7, 1)
        assert gap.kind in FreshnessGapKind
        assert gap.reason


def test_registry_registration_on_acquire(processor: MpepGuidanceProcessor, acquisition):
    for key in acquisition.authority_sources:
        assert key in processor.registry
        stored = processor.registry.get(key)
        assert stored.authority_tier is AuthorityTier.GUIDANCE


def test_record_rejects_missing_cutoff():
    with pytest.raises(MissingCutoffError):
        GuidanceRecord(
            guidance_id="x",
            kind=GuidanceKind.MPEP_SECTION,
            cutoff=None,  # type: ignore[arg-type]
            anchor="2106",
        )


def test_record_rejects_non_guidance_tier():
    with pytest.raises(BindingElevationError):
        GuidanceRecord(
            guidance_id="x",
            kind=GuidanceKind.MPEP_SECTION,
            cutoff=date(2022, 7, 1),
            authority_tier=AuthorityTier.OFFICIAL_BASE,
            anchor="2106",
        )


def test_record_rejects_binding_flag():
    with pytest.raises(BindingElevationError):
        GuidanceRecord(
            guidance_id="x",
            kind=GuidanceKind.MPEP_SECTION,
            cutoff=date(2022, 7, 1),
            anchor="2106",
            is_binding=True,
        )


# ---------------------------------------------------------------------------
# Later guidance supersedes manual text without elevating to law
# ---------------------------------------------------------------------------


def test_post_cutoff_publications_are_listed(acquisition):
    post = acquisition.post_cutoff_publications()
    assert post
    ids = {r.guidance_id for r in post}
    assert "exam-guide-1-23" in ids
    assert "notice-2023-10-17" in ids
    assert "fees-fy2024" in ids
    for record in post:
        assert record.is_post_cutoff_publication is True
        assert record.publication_date is not None
        assert record.publication_date > acquisition.edition.cutoff
        # Still guidance, still non-binding, still carry the manual cutoff.
        assert record.authority_tier is AuthorityTier.GUIDANCE
        assert record.is_binding is False
        assert record.cutoff == acquisition.edition.cutoff


def test_fixture_supersessions_link_manual_and_later(acquisition):
    assert len(acquisition.supersessions) >= 2
    pairs = {(e.successor_id, e.predecessor_id) for e in acquisition.supersessions}
    assert ("exam-guide-1-23", "mpep-706.02") in pairs
    assert ("notice-2023-10-17", "mpep-2106") in pairs

    guide = acquisition.get_record("exam-guide-1-23")
    manual = acquisition.get_record("mpep-706.02")
    assert "mpep-706.02" in guide.supersedes
    assert manual.superseded_by == "exam-guide-1-23"

    for edge in acquisition.supersessions:
        assert edge.remains_guidance is True
        assert edge.elevates_to_law is False
        assert edge.to_dict()["elevates_to_law"] is False
        assert edge.to_dict()["remains_guidance"] is True


def test_supersede_manual_text_api(processor: MpepGuidanceProcessor, acquisition):
    # Start from a clean re-acquire without the second edge to exercise API.
    # Apply an additional supersession from notice over form paragraph for demo.
    # Prefer re-applying existing edge through API on a fresh copy without links.
    raw = processor.load_fixture_package()
    # Strip supersessions so we can apply via API.
    raw = dict(raw)
    raw["supersessions"] = []
    # Clear pre-linked supersedes on records.
    cleaned_records = []
    for item in raw["records"]:
        item = dict(item)
        item.pop("supersedes", None)
        item.pop("superseded_by", None)
        cleaned_records.append(item)
    raw["records"] = cleaned_records
    base = processor.acquire_from_payload(raw, register=False)

    updated = processor.supersede_manual_text(
        base,
        later_guidance_id="exam-guide-1-23",
        manual_guidance_id="mpep-706.02",
        relation=SupersessionRelation.SUPERSEDES,
        effective_date="2023-03-15",
        reason="Guide supersedes inconsistent manual text",
    )
    guide = updated.get_record("exam-guide-1-23")
    manual = updated.get_record("mpep-706.02")
    assert "mpep-706.02" in guide.supersedes
    assert manual.superseded_by == "exam-guide-1-23"
    assert guide.authority_tier is AuthorityTier.GUIDANCE
    assert manual.authority_tier is AuthorityTier.GUIDANCE
    assert guide.is_binding is False
    assert manual.is_binding is False
    processor.assert_not_elevated_to_law(updated)


def test_supersession_edge_rejects_elevation_to_law():
    with pytest.raises(BindingElevationError):
        SupersessionEdge(
            successor_id="exam-guide-1-23",
            predecessor_id="mpep-706.02",
            elevates_to_law=True,
        )
    with pytest.raises(BindingElevationError):
        SupersessionEdge(
            successor_id="exam-guide-1-23",
            predecessor_id="mpep-706.02",
            remains_guidance=False,
        )


def test_assert_not_elevated_to_law(processor: MpepGuidanceProcessor, acquisition):
    processor.assert_not_elevated_to_law(acquisition)


def test_mpep_form_fee_and_guide_kinds_present(acquisition):
    kinds = {r.kind for r in acquisition.records.values()}
    assert GuidanceKind.MPEP_SECTION in kinds
    assert GuidanceKind.FORM_PARAGRAPH in kinds
    assert GuidanceKind.FORM in kinds
    assert GuidanceKind.FEE_SCHEDULE in kinds
    assert GuidanceKind.EXAMINATION_GUIDE in kinds
    assert GuidanceKind.NOTICE in kinds


# ---------------------------------------------------------------------------
# Unavailable or changed documents → explicit freshness gaps
# ---------------------------------------------------------------------------


def test_freshness_gaps_include_unavailable_and_changed(acquisition):
    kinds = {g.kind for g in acquisition.freshness_gaps}
    assert FreshnessGapKind.UNAVAILABLE in kinds
    assert FreshnessGapKind.CONTENT_CHANGED in kinds
    assert FreshnessGapKind.DELAYED_INVENTORY in kinds

    changed = next(
        g for g in acquisition.freshness_gaps if g.kind is FreshnessGapKind.CONTENT_CHANGED
    )
    assert changed.expected_sha256
    assert changed.observed_sha256
    assert changed.expected_sha256 != changed.observed_sha256
    assert "silent" in changed.reason.lower() or "version" in changed.reason.lower()

    unavailable = next(
        g for g in acquisition.freshness_gaps if g.kind is FreshnessGapKind.UNAVAILABLE
    )
    assert unavailable.source_id
    assert unavailable.reason


def test_unavailable_edition_fixture_yields_unknown(
    processor: MpepGuidanceProcessor, fixture_dir: Path
):
    acq = processor.acquire_from_fixture(fixture_dir / "mpep_unavailable_edition.json")
    assert acq.status is ResolutionStatus.UNKNOWN
    assert acq.is_unknown
    assert acq.edition is None
    assert acq.unknown_reason
    assert acq.freshness_gaps
    assert any(g.kind is FreshnessGapKind.UNAVAILABLE for g in acq.freshness_gaps)


def test_empty_payload_yields_unknown(processor: MpepGuidanceProcessor):
    acq = processor.acquire_from_payload({"records": []})
    assert acq.status is ResolutionStatus.UNKNOWN
    assert acq.unknown_reason == "missing edition/cutoff data"


def test_acquire_unknown_helper(processor: MpepGuidanceProcessor):
    acq = processor.acquire_unknown(reason="operator withheld edition")
    assert acq.status is ResolutionStatus.UNKNOWN
    assert acq.unknown_reason == "operator withheld edition"


def test_detect_content_change_api(processor: MpepGuidanceProcessor, acquisition):
    record = acquisition.get_record("form-pto-sb-08")
    assert record.content_sha256
    new_sha = content_sha256("changed-form-bytes")
    gap = processor.detect_content_change(
        source_id=record.guidance_id,
        expected_sha256=record.content_sha256,
        observed_sha256=new_sha,
        source_url=record.source_url,
        cutoff=record.cutoff,
    )
    assert gap.kind is FreshnessGapKind.CONTENT_CHANGED
    assert gap.expected_sha256 == record.content_sha256
    assert gap.observed_sha256 == new_sha
    assert gap.authority_tier is AuthorityTier.GUIDANCE


def test_detect_content_change_rejects_identical_digest(processor: MpepGuidanceProcessor):
    digest = "a" * 64
    with pytest.raises(MpepGuidanceError):
        processor.detect_content_change(
            source_id="x",
            expected_sha256=digest,
            observed_sha256=digest,
        )


def test_reconcile_observed_digest(processor: MpepGuidanceProcessor, acquisition):
    record = acquisition.get_record("mpep-2106")
    assert processor.reconcile_observed_digest(
        acquisition, guidance_id="mpep-2106", observed_sha256=record.content_sha256
    ) is None
    gap = processor.reconcile_observed_digest(
        acquisition,
        guidance_id="mpep-2106",
        observed_sha256=content_sha256("mutated"),
    )
    assert gap is not None
    assert gap.kind is FreshnessGapKind.CONTENT_CHANGED


def test_detect_unavailable_api(processor: MpepGuidanceProcessor):
    gap = processor.detect_unavailable(
        source_id="exam-guide-9-99",
        reason="HTTP 404",
        cutoff="2022-07-01",
    )
    assert gap.kind is FreshnessGapKind.UNAVAILABLE
    assert gap.cutoff == date(2022, 7, 1)
    assert gap.to_dict()["authority_tier"] == "guidance"


# ---------------------------------------------------------------------------
# Helpers, serialization, fixture recipe
# ---------------------------------------------------------------------------


def test_hard_coded_latest_rejected():
    with pytest.raises(HardCodedLatestEditionError):
        parse_mpep_edition_revision(edition="latest", revision="07.2022")
    with pytest.raises(HardCodedLatestEditionError):
        parse_mpep_edition_revision(edition="9", revision="latest")
    with pytest.raises((HardCodedLatestEditionError, MissingCutoffError, MpepGuidanceError)):
        GuidanceEdition(edition="latest", revision="07.2022", cutoff=date(2022, 7, 1))


def test_section_and_form_paragraph_normalization():
    assert normalize_mpep_section("2106") == "2106"
    assert normalize_mpep_section("§ 2106") == "2106"
    assert normalize_mpep_section("MPEP section 706.02") == "706.02"
    assert normalize_form_paragraph("7.05") == "7.05"
    assert normalize_form_paragraph("FP 7.05") == "7.05"
    assert normalize_form_paragraph("form paragraph 7.05") == "7.05"
    assert normalize_form_paragraph("¶7.05") == "7.05"


def test_stable_guidance_identity_independent_of_presentation():
    a = stable_guidance_identity(kind="mpep_section", anchor="§ 2106")
    b = stable_guidance_identity(kind=GuidanceKind.MPEP_SECTION, anchor="2106")
    assert a == b == "guidance:us:mpep_section:2106"
    fp = stable_guidance_identity(kind="form_paragraph", anchor="FP 7.05")
    assert fp == "guidance:us:form_paragraph:7.05"


def test_acquisition_canonical_json_is_stable(acquisition):
    blob1 = acquisition.to_canonical_json()
    blob2 = acquisition.to_canonical_json()
    assert blob1 == blob2
    payload = json.loads(blob1)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["edition"]["cutoff"] == "2022-07-01"
    assert "mpep-2106" in payload["records"]
    assert payload["records"]["mpep-2106"]["authority_tier"] == "guidance"
    assert payload["freshness_gaps"]


def test_fixture_recipe_schema_and_contents(fixture_dir: Path):
    recipe_path = fixture_dir / "mpep_guidance_recipe.json"
    assert recipe_path.is_file()
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    assert recipe["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert recipe["edition"]["cutoff"] == "2022-07-01"
    assert recipe["edition"]["edition"] == "9"
    assert recipe["edition"]["revision"] == "07.2022"
    kinds = {r["kind"] for r in recipe["records"]}
    assert "mpep_section" in kinds
    assert "form_paragraph" in kinds
    assert "form" in kinds
    assert "fee_schedule" in kinds
    assert "examination_guide" in kinds
    assert recipe["supersessions"]
    assert recipe["freshness_gaps"]


def test_build_recipe_matches_on_disk(fixture_dir: Path):
    generated = build_mpep_guidance_fixture_recipe()
    on_disk = json.loads(
        (fixture_dir / "mpep_guidance_recipe.json").read_text(encoding="utf-8")
    )
    assert generated["edition"]["cutoff"] == on_disk["edition"]["cutoff"]
    assert {r["guidance_id"] for r in generated["records"]} == {
        r["guidance_id"] for r in on_disk["records"]
    }
    assert len(generated["supersessions"]) == len(on_disk["supersessions"])
    assert len(generated["freshness_gaps"]) == len(on_disk["freshness_gaps"])


def test_content_sha256_deterministic():
    assert content_sha256("abc") == content_sha256(b"abc")
    assert content_sha256("abc") != content_sha256("abd")


def test_missing_record_raises(acquisition):
    with pytest.raises(GuidanceNotFoundError):
        acquisition.get_record("does-not-exist")


def test_records_by_kind(acquisition):
    sections = acquisition.records_by_kind(GuidanceKind.MPEP_SECTION)
    assert sections
    assert all(r.kind is GuidanceKind.MPEP_SECTION for r in sections)


def test_guidance_record_round_trip():
    record = GuidanceRecord(
        guidance_id="mpep-2106",
        kind=GuidanceKind.MPEP_SECTION,
        cutoff=date(2022, 7, 1),
        anchor="§ 2106",
        citation="MPEP § 2106",
        edition="9",
        revision="07.2022",
        content_sha256="b" * 64,
        source_url="https://www.uspto.gov/web/offices/pac/mpep/s2106.html",
    )
    restored = GuidanceRecord.from_dict(record.to_dict())
    assert restored.to_dict() == record.to_dict()
    assert restored.anchor == "2106"
    assert restored.stable_id == "guidance:us:mpep_section:2106"


def test_freshness_gap_round_trip():
    gap = FreshnessGap(
        gap_id="gap-x",
        kind=FreshnessGapKind.HASH_MISMATCH,
        source_id="form-x",
        reason="hash mismatch",
        cutoff=date(2022, 7, 1),
        expected_sha256="a" * 64,
        observed_sha256="b" * 64,
    )
    restored = FreshnessGap.from_dict(gap.to_dict())
    assert restored.to_dict() == gap.to_dict()
    assert restored.authority_tier is AuthorityTier.GUIDANCE
