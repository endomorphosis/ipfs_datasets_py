"""Unit tests for full MPEP section inventory and edition pin contracts.

PATLAW-182 / PATLAW-G216 acceptance:

* Schema requires concrete edition **and** revision pins (never ``latest``)
* Inventory enumerates section anchors across **all** required chapters
* Chapter-only inventories cannot satisfy acceptance
* Guidance never elevates to binding law
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.mpep_full_section_contracts import (
    AUTHORITY_TIER_GUIDANCE,
    CODE_VERSION,
    CONFIG_ID,
    GOAL_ID,
    INTERFACE,
    PRODUCER,
    REQUIRED_CHAPTER_IDS,
    REQUIRED_MPEP_CHAPTERS,
    SCHEMA_VERSION,
    TASK_ID,
    BindingElevationError,
    ChapterOnlyInventoryError,
    EditionPinError,
    GapKind,
    IncompleteChapterCoverageError,
    InventoryEntryKind,
    InventoryEntryStatus,
    MissingCutoffError,
    MpepEditionPin,
    MpepFullInventoryManifest,
    MpepInventoryGap,
    MpepSectionInventoryEntry,
    MpepSupersessionRecord,
    SchemaValidationError,
    SupersessionRelation,
    assert_guidance_not_elevated,
    build_compact_full_inventory_fixture,
    build_mpep_full_manifest,
    canonical_json,
    chapter_id_for_section,
    chapters_with_section_level_coverage,
    content_digest_of,
    content_sha256,
    default_manifest_schema_path,
    is_chapter_landing_anchor,
    is_section_level_anchor,
    load_manifest_schema,
    normalize_chapter_id,
    normalize_form_paragraph,
    normalize_mpep_section,
    parse_mpep_edition_revision,
    stable_section_identity,
    validate_full_chapter_coverage,
    validate_inventory_not_chapter_only,
    validate_manifest_against_json_schema,
    validate_manifest_dict,
)

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None  # type: ignore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def compact_manifest_dict() -> dict:
    return build_compact_full_inventory_fixture()


@pytest.fixture(scope="module")
def compact_manifest(compact_manifest_dict: dict) -> MpepFullInventoryManifest:
    return MpepFullInventoryManifest.from_dict(compact_manifest_dict)


@pytest.fixture(scope="module")
def schema_path() -> Path:
    return default_manifest_schema_path()


@pytest.fixture(scope="module")
def schema(schema_path: Path) -> dict:
    assert schema_path.is_file(), f"missing schema at {schema_path}"
    return load_manifest_schema(path=schema_path)


# ---------------------------------------------------------------------------
# Schema / pin constants
# ---------------------------------------------------------------------------


def test_schema_and_task_pins() -> None:
    assert SCHEMA_VERSION == "patent.mpep_full.v1"
    assert INTERFACE == "MpepFullSectionInventory@1"
    assert TASK_ID == "PATLAW-182"
    assert GOAL_ID == "PATLAW-G216"
    assert PRODUCER == "producer:mpep-full-section-inventory"
    assert CONFIG_ID == "config:mpep-full-section/v1"
    assert CODE_VERSION == "1.0.0"
    assert AUTHORITY_TIER_GUIDANCE == "guidance"


def test_required_chapter_catalog_is_complete() -> None:
    ids = [c.chapter_id for c in REQUIRED_MPEP_CHAPTERS]
    assert len(ids) == len(set(ids))
    # All standard numbered chapters 100–2900
    for n in range(100, 3000, 100):
        assert str(n) in REQUIRED_CHAPTER_IDS
    # Appendices and index
    for appx in ("appx-L", "appx-R", "appx-T", "appx-AI", "appx-P", "appx-II", "index"):
        assert appx in REQUIRED_CHAPTER_IDS
    assert len(REQUIRED_MPEP_CHAPTERS) >= 36


def test_manifest_schema_file_exists_and_is_draft_2020(schema_path: Path, schema: dict) -> None:
    assert schema_path.name == "mpep_full.manifest.schema.json"
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("patent-mpep-full.manifest.v1.schema.json")
    required = set(schema["required"])
    assert "edition_pin" in required
    assert "inventory" in required
    assert "authority_tier" in required
    assert "is_binding" in required
    # Edition pin requires both edition and revision
    pin_required = set(schema["$defs"]["editionPin"]["required"])
    assert pin_required == {"edition", "revision", "cutoff"}
    assert schema["properties"]["authority_tier"]["const"] == "guidance"
    assert schema["properties"]["is_binding"]["const"] is False
    # Supersession cannot elevate to law
    ss = schema["$defs"]["supersession"]
    assert ss["properties"]["elevates_to_law"]["const"] is False
    assert ss["properties"]["remains_guidance"]["const"] is True


# ---------------------------------------------------------------------------
# Edition + revision pins
# ---------------------------------------------------------------------------


def test_parse_edition_revision_requires_both_pins() -> None:
    edition, revision = parse_mpep_edition_revision(edition="9", revision="07.2022")
    assert edition == "9"
    assert revision == "07.2022"

    with pytest.raises(EditionPinError):
        parse_mpep_edition_revision(edition="", revision="07.2022")
    with pytest.raises(EditionPinError):
        parse_mpep_edition_revision(edition="9", revision="")
    with pytest.raises(EditionPinError):
        parse_mpep_edition_revision(edition=None, revision="07.2022")
    with pytest.raises(EditionPinError):
        parse_mpep_edition_revision(edition="9", revision=None)


def test_hard_coded_latest_rejected_on_edition_and_revision() -> None:
    with pytest.raises(EditionPinError):
        parse_mpep_edition_revision(edition="latest", revision="07.2022")
    with pytest.raises(EditionPinError):
        parse_mpep_edition_revision(edition="9", revision="latest")
    with pytest.raises(EditionPinError):
        parse_mpep_edition_revision(edition="LATEST", revision="01.2024")
    with pytest.raises(EditionPinError):
        MpepEditionPin(edition="latest", revision="07.2022", cutoff=date(2022, 7, 1))
    with pytest.raises(EditionPinError):
        MpepEditionPin(edition="9", revision="latest", cutoff=date(2022, 7, 1))


def test_edition_pin_requires_cutoff() -> None:
    with pytest.raises(MissingCutoffError):
        MpepEditionPin.from_dict(
            {"edition": "9", "revision": "07.2022"}
        )


def test_edition_pin_round_trip() -> None:
    pin = MpepEditionPin(
        edition="9",
        revision="07.2022",
        cutoff=date(2022, 7, 1),
        publication_date=date(2022, 7, 1),
        source_url="https://www.uspto.gov/web/offices/pac/mpep/index.html",
        notes="MPEP 9 r07.2022",
    )
    assert pin.edition_key == "mpep-9-r07.2022"
    restored = MpepEditionPin.from_dict(pin.to_dict())
    assert restored.to_dict() == pin.to_dict()
    assert "latest" not in restored.edition.lower()
    assert "latest" not in restored.revision.lower()


def test_manifest_rejects_missing_edition_pin() -> None:
    payload = build_compact_full_inventory_fixture()
    del payload["edition_pin"]
    with pytest.raises(EditionPinError):
        validate_manifest_dict(payload)


def test_manifest_rejects_edition_pin_without_revision() -> None:
    payload = build_compact_full_inventory_fixture()
    pin = dict(payload["edition_pin"])
    del pin["revision"]
    payload["edition_pin"] = pin
    with pytest.raises(EditionPinError):
        validate_manifest_dict(payload)


def test_manifest_rejects_edition_pin_without_edition() -> None:
    payload = build_compact_full_inventory_fixture()
    pin = dict(payload["edition_pin"])
    del pin["edition"]
    # Keep edition_key so we still exercise the revision-only / missing edition path
    pin.pop("edition_key", None)
    payload["edition_pin"] = pin
    with pytest.raises(EditionPinError):
        validate_manifest_dict(payload)


def test_schema_rejects_missing_edition_or_revision_pins(
    schema: dict, compact_manifest_dict: dict
) -> None:
    if jsonschema is None:  # pragma: no cover
        pytest.skip("jsonschema not installed")
    validator = jsonschema.Draft202012Validator(schema)

    missing_edition = copy.deepcopy(compact_manifest_dict)
    del missing_edition["edition_pin"]["edition"]
    assert list(validator.iter_errors(missing_edition))

    missing_revision = copy.deepcopy(compact_manifest_dict)
    del missing_revision["edition_pin"]["revision"]
    assert list(validator.iter_errors(missing_revision))

    latest_edition = copy.deepcopy(compact_manifest_dict)
    latest_edition["edition_pin"]["edition"] = "latest"
    assert list(validator.iter_errors(latest_edition))

    latest_revision = copy.deepcopy(compact_manifest_dict)
    latest_revision["edition_pin"]["revision"] = "latest"
    assert list(validator.iter_errors(latest_revision))


# ---------------------------------------------------------------------------
# Section anchors across all chapters
# ---------------------------------------------------------------------------


def test_compact_fixture_covers_all_required_chapters(
    compact_manifest: MpepFullInventoryManifest,
) -> None:
    covered = chapters_with_section_level_coverage(compact_manifest.inventory)
    assert covered == REQUIRED_CHAPTER_IDS
    assert compact_manifest.counts.chapters_covered == len(REQUIRED_MPEP_CHAPTERS)
    assert compact_manifest.counts.chapters_required == len(REQUIRED_MPEP_CHAPTERS)
    assert compact_manifest.counts.section_level_entries >= len(REQUIRED_MPEP_CHAPTERS)
    # At least one section-level anchor per chapter in coverage tallies
    for cov in compact_manifest.chapter_coverage:
        assert cov.chapter_id in REQUIRED_CHAPTER_IDS
        assert cov.section_level_count >= 1


def test_inventory_enumerates_section_anchors_not_only_chapters(
    compact_manifest: MpepFullInventoryManifest,
) -> None:
    section_level = [e for e in compact_manifest.inventory if e.is_section_level]
    assert len(section_level) >= len(REQUIRED_MPEP_CHAPTERS)
    # Representative real section numbers present
    anchors = {e.section_anchor for e in compact_manifest.inventory}
    assert "706.02" in anchors
    assert "2106" in anchors
    assert "7.05" in anchors  # form paragraph
    # No chapter-landing-only exclusive inventory
    for e in compact_manifest.inventory:
        if e.kind is InventoryEntryKind.MPEP_SECTION and e.status is InventoryEntryStatus.PRESENT:
            assert not is_chapter_landing_anchor(
                chapter_id=e.chapter_id, section_anchor=e.section_anchor
            )


def test_chapter_only_inventory_rejected() -> None:
    pin = MpepEditionPin(edition="9", revision="07.2022", cutoff=date(2022, 7, 1))
    # Only chapter landing anchors — must fail
    landings = [
        MpepSectionInventoryEntry(
            entry_id=f"ch-{ch.chapter_id}",
            chapter_id=ch.chapter_id,
            section_anchor=ch.chapter_id if ch.chapter_id.isdigit() else f"chapter-{ch.chapter_id}",
            kind=(
                InventoryEntryKind.APPENDIX_ANCHOR
                if ch.chapter_id.startswith("appx-")
                else (
                    InventoryEntryKind.INDEX_ANCHOR
                    if ch.chapter_id == "index"
                    else InventoryEntryKind.MPEP_SECTION
                )
            ),
            status=InventoryEntryStatus.GAP,
            gap_reason="chapter landing only — not a section inventory",
        )
        for ch in REQUIRED_MPEP_CHAPTERS
        if ch.chapter_id.isdigit()
    ]
    # Present chapter landings for numbered chapters should raise at entry build
    with pytest.raises(ChapterOnlyInventoryError):
        MpepSectionInventoryEntry(
            entry_id="ch-700-landing",
            chapter_id="700",
            section_anchor="700",
            kind=InventoryEntryKind.MPEP_SECTION,
            status=InventoryEntryStatus.PRESENT,
        )

    # Gap-status landings alone still fail full coverage / chapter-only checks
    with pytest.raises((ChapterOnlyInventoryError, IncompleteChapterCoverageError)):
        build_mpep_full_manifest(edition_pin=pin, inventory=landings)


def test_incomplete_chapter_coverage_rejected() -> None:
    pin = MpepEditionPin(edition="9", revision="07.2022", cutoff=date(2022, 7, 1))
    # Only chapter 700 / 2100 — missing the rest
    partial = [
        MpepSectionInventoryEntry(
            entry_id="mpep-700-706.02",
            chapter_id="700",
            section_anchor="706.02",
            kind=InventoryEntryKind.MPEP_SECTION,
            status=InventoryEntryStatus.PRESENT,
            content_sha256=content_sha256("partial-706.02"),
        ),
        MpepSectionInventoryEntry(
            entry_id="mpep-2100-2106",
            chapter_id="2100",
            section_anchor="2106",
            kind=InventoryEntryKind.MPEP_SECTION,
            status=InventoryEntryStatus.PRESENT,
            content_sha256=content_sha256("partial-2106"),
        ),
    ]
    with pytest.raises(IncompleteChapterCoverageError):
        build_mpep_full_manifest(edition_pin=pin, inventory=partial)
    with pytest.raises(IncompleteChapterCoverageError):
        validate_full_chapter_coverage(partial, require_all_chapters=True)


def test_empty_inventory_rejected() -> None:
    pin = MpepEditionPin(edition="9", revision="07.2022", cutoff=date(2022, 7, 1))
    with pytest.raises(IncompleteChapterCoverageError):
        build_mpep_full_manifest(edition_pin=pin, inventory=[])
    with pytest.raises((IncompleteChapterCoverageError, ChapterOnlyInventoryError)):
        validate_inventory_not_chapter_only([])


def test_section_and_chapter_normalization() -> None:
    assert normalize_mpep_section("§ 2106.04(a)") == "2106.04(a)"
    assert normalize_mpep_section("MPEP section 706.02") == "706.02"
    assert normalize_form_paragraph("FP 7.05") == "7.05"
    assert normalize_form_paragraph("¶7.21") == "7.21"
    assert normalize_chapter_id("700") == "700"
    assert normalize_chapter_id("Appendix L") == "appx-L"
    assert normalize_chapter_id("appx-R") == "appx-R"
    assert normalize_chapter_id("index") == "index"
    assert chapter_id_for_section("706.02") == "700"
    assert chapter_id_for_section("2106") == "2100"
    assert chapter_id_for_section("101") == "100"
    assert chapter_id_for_section("1001") == "1000"
    assert is_chapter_landing_anchor(chapter_id="700", section_anchor="700")
    assert not is_chapter_landing_anchor(chapter_id="700", section_anchor="706.02")
    assert is_section_level_anchor(
        chapter_id="700", section_anchor="706.02", kind="mpep_section"
    )
    assert is_section_level_anchor(
        chapter_id="700", section_anchor="7.05", kind="form_paragraph"
    )
    assert stable_section_identity(kind="mpep_section", anchor="2106") == (
        "mpep:us:mpep_section:2106"
    )


# ---------------------------------------------------------------------------
# Guidance never elevates to binding law
# ---------------------------------------------------------------------------


def test_guidance_tier_forced_on_every_inventory_entry(
    compact_manifest: MpepFullInventoryManifest,
) -> None:
    for entry in compact_manifest.inventory:
        assert entry.authority_tier == "guidance"
        assert entry.is_binding is False
        d = entry.to_dict()
        assert d["authority_tier"] == "guidance"
        assert d["is_binding"] is False


def test_manifest_authority_is_guidance_not_binding(
    compact_manifest: MpepFullInventoryManifest,
) -> None:
    assert compact_manifest.authority_tier == "guidance"
    assert compact_manifest.is_binding is False
    d = compact_manifest.to_dict()
    assert d["authority_tier"] == "guidance"
    assert d["is_binding"] is False


def test_entry_rejects_binding_flag() -> None:
    with pytest.raises(BindingElevationError):
        MpepSectionInventoryEntry(
            entry_id="mpep-2106",
            chapter_id="2100",
            section_anchor="2106",
            is_binding=True,
        )


def test_entry_rejects_non_guidance_tier() -> None:
    with pytest.raises(BindingElevationError):
        MpepSectionInventoryEntry(
            entry_id="mpep-2106",
            chapter_id="2100",
            section_anchor="2106",
            authority_tier="official-base",
        )


def test_supersession_rejects_elevation_to_law() -> None:
    with pytest.raises(BindingElevationError):
        MpepSupersessionRecord(
            successor_id="exam-guide-1",
            predecessor_id="mpep-706.02",
            elevates_to_law=True,
        )
    with pytest.raises(BindingElevationError):
        MpepSupersessionRecord(
            successor_id="exam-guide-1",
            predecessor_id="mpep-706.02",
            remains_guidance=False,
        )


def test_assert_guidance_not_elevated_helper() -> None:
    assert_guidance_not_elevated(authority_tier="guidance", is_binding=False)
    with pytest.raises(BindingElevationError):
        assert_guidance_not_elevated(authority_tier="statute")
    with pytest.raises(BindingElevationError):
        assert_guidance_not_elevated(is_binding=True)
    with pytest.raises(BindingElevationError):
        assert_guidance_not_elevated(elevates_to_law=True)


def test_manifest_rejects_binding_elevation_in_payload(
    compact_manifest_dict: dict,
) -> None:
    payload = copy.deepcopy(compact_manifest_dict)
    payload["is_binding"] = True
    with pytest.raises(BindingElevationError):
        validate_manifest_dict(payload)

    payload2 = copy.deepcopy(compact_manifest_dict)
    payload2["authority_tier"] = "official-base"
    with pytest.raises(BindingElevationError):
        validate_manifest_dict(payload2)

    payload3 = copy.deepcopy(compact_manifest_dict)
    payload3["supersessions"][0]["elevates_to_law"] = True
    with pytest.raises(BindingElevationError):
        validate_manifest_dict(payload3)


def test_schema_rejects_binding_or_non_guidance(
    schema: dict, compact_manifest_dict: dict
) -> None:
    if jsonschema is None:  # pragma: no cover
        pytest.skip("jsonschema not installed")
    validator = jsonschema.Draft202012Validator(schema)

    binding = copy.deepcopy(compact_manifest_dict)
    binding["is_binding"] = True
    assert list(validator.iter_errors(binding))

    elevated = copy.deepcopy(compact_manifest_dict)
    elevated["authority_tier"] = "regulation"
    assert list(validator.iter_errors(elevated))

    ss = copy.deepcopy(compact_manifest_dict)
    ss["supersessions"][0]["elevates_to_law"] = True
    assert list(validator.iter_errors(ss))


# ---------------------------------------------------------------------------
# Digests, round-trip, JSON Schema acceptance of valid fixture
# ---------------------------------------------------------------------------


def test_compact_manifest_round_trip(compact_manifest: MpepFullInventoryManifest) -> None:
    first = compact_manifest.to_dict()
    restored = MpepFullInventoryManifest.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    assert restored.edition_pin.edition == "9"
    assert restored.edition_pin.revision == "07.2022"
    assert restored.inventory_digest_sha256 == content_digest_of(
        [e.to_dict() for e in restored.inventory]
    )


def test_inventory_digest_mismatch_rejected(
    compact_manifest_dict: dict,
) -> None:
    payload = copy.deepcopy(compact_manifest_dict)
    payload["inventory_digest_sha256"] = "0" * 64
    with pytest.raises(SchemaValidationError):
        validate_manifest_dict(payload)


def test_content_sha256_deterministic() -> None:
    assert content_sha256("abc") == content_sha256(b"abc")
    assert content_sha256("abc") != content_sha256("abd")


def test_valid_fixture_passes_json_schema(
    schema: dict, compact_manifest_dict: dict
) -> None:
    if jsonschema is None:  # pragma: no cover
        pytest.skip("jsonschema not installed")
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(compact_manifest_dict), key=lambda e: list(e.path))
    assert errors == [], f"unexpected schema errors: {[e.message for e in errors[:5]]}"
    validate_manifest_against_json_schema(compact_manifest_dict, schema=schema)


def test_schema_rejects_empty_inventory(
    schema: dict, compact_manifest_dict: dict
) -> None:
    if jsonschema is None:  # pragma: no cover
        pytest.skip("jsonschema not installed")
    payload = copy.deepcopy(compact_manifest_dict)
    payload["inventory"] = []
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(payload))


def test_supersession_and_gap_round_trips() -> None:
    edge = MpepSupersessionRecord(
        successor_id="exam-guide-1-23",
        predecessor_id="mpep-706.02",
        relation=SupersessionRelation.SUPERSEDES,
        effective_date=date(2023, 3, 15),
        reason="Later guide supersedes inconsistent manual text; both remain guidance.",
    )
    assert edge.to_dict()["elevates_to_law"] is False
    assert edge.to_dict()["remains_guidance"] is True
    assert MpepSupersessionRecord.from_dict(edge.to_dict()).to_dict() == edge.to_dict()

    gap = MpepInventoryGap(
        gap_id="gap-unavailable-2201",
        kind=GapKind.UNAVAILABLE,
        chapter_id="2200",
        reason="Section HTML temporarily unavailable (HTTP 404).",
        section_anchor="2201",
    )
    assert gap.to_dict()["authority_tier"] == "guidance"
    assert MpepInventoryGap.from_dict(gap.to_dict()).to_dict() == gap.to_dict()


def test_form_paragraph_entries_in_fixture(
    compact_manifest: MpepFullInventoryManifest,
) -> None:
    fps = [
        e
        for e in compact_manifest.inventory
        if e.kind is InventoryEntryKind.FORM_PARAGRAPH
    ]
    assert len(fps) >= 2
    assert compact_manifest.counts.form_paragraph_entries >= 2
    assert all(e.authority_tier == "guidance" for e in fps)


def test_compact_fixture_is_bounded_size(compact_manifest_dict: dict) -> None:
    raw = json.dumps(compact_manifest_dict, sort_keys=True, separators=(",", ":"))
    # Compact recipe: one anchor per chapter + form paragraphs — well under 1 MiB.
    assert len(raw.encode("utf-8")) < 200_000


def test_build_manifest_helper_matches_fixture_structure() -> None:
    payload = build_compact_full_inventory_fixture(
        edition="9",
        revision="01.2024",
        cutoff="2024-01-01",
        include_form_paragraphs=False,
        include_supersession=False,
    )
    manifest = validate_manifest_dict(payload)
    assert manifest.edition_pin.revision == "01.2024"
    assert manifest.counts.form_paragraph_entries == 0
    assert manifest.counts.supersession_edges == 0
    assert set(e.chapter_id for e in manifest.inventory if e.is_section_level) == (
        REQUIRED_CHAPTER_IDS
    )
