"""Unit tests for full annual CFR Title 37 inventory contracts (PATLAW-180).

Acceptance:

* Schema / contracts reject missing edition identity, empty inventory, or
  unpinned ``latest``.
* Inventory enumerates all Title 37 sections for a pinned annual package.
* Gap records and content-addressed package bindings are first-class.
* eCFR alone never satisfies annual completion (authority_tier=official-base).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.cfr_title37_full_contracts import (
    CODE_VERSION,
    CONFIG_ID,
    DEFAULT_TITLE,
    GOAL_ID,
    INTERFACE,
    SCHEMA_VERSION,
    TASK_ID,
    TITLE37_PARTS,
    TITLE37_PART_METADATA,
    TITLE37_SECTION_CATALOG,
    CfrTitle37FullManifest,
    EditionIdentity,
    EmptyInventoryError,
    GapReason,
    GapRecord,
    IncompleteInventoryError,
    InventoryCounts,
    InventorySectionEntry,
    MissingEditionIdentityError,
    PackageBinding,
    PackageBindingError,
    SchemaValidationError,
    SectionPresence,
    UnpinnedLatestError,
    build_full_title37_inventory,
    build_full_title37_manifest,
    build_gap_records_for_inventory,
    build_package_binding,
    canonical_json,
    content_digest_of,
    load_manifest_schema,
    manifest_schema_path,
    title37_all_section_tokens,
    title37_section_count,
    validate_against_json_schema,
    validate_manifest,
)

# Optional JSON Schema validation when jsonschema is installed.
try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None  # type: ignore

_REPO_ROOT = Path(__file__).resolve().parents[5]
_SCHEMA_PATH = (
    _REPO_ROOT
    / "data"
    / "release"
    / "patent_legal_intelligence"
    / "cfr_title37_full.manifest.schema.json"
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
CID_SAMPLE = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pinned_manifest() -> CfrTitle37FullManifest:
    return build_full_title37_manifest(
        2024,
        gap_sections=["1.56", "42.100"],
        notes="test pin CFR-2024-title37",
    )


@pytest.fixture(scope="module")
def schema_doc() -> dict:
    assert _SCHEMA_PATH.is_file(), f"missing schema at {_SCHEMA_PATH}"
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Pins / catalog
# ---------------------------------------------------------------------------


def test_schema_and_task_pins() -> None:
    assert SCHEMA_VERSION == "patent.cfr_title37_full.v1"
    assert INTERFACE == "CfrTitle37FullInventory@1"
    assert TASK_ID == "PATLAW-180"
    assert GOAL_ID == "PATLAW-G215"
    assert CONFIG_ID == "config:cfr-title37-full/v1"
    assert CODE_VERSION


def test_title37_catalog_covers_all_chapters_and_parts() -> None:
    assert len(TITLE37_PARTS) >= 20
    assert set(TITLE37_PARTS) == set(TITLE37_PART_METADATA)
    assert set(TITLE37_PARTS) == set(TITLE37_SECTION_CATALOG)

    chapters = {TITLE37_PART_METADATA[p]["chapter"] for p in TITLE37_PARTS}
    # Chapters I (USPTO), II (Copyright), III (CRB), IV (NIST), V (Under Secretary).
    assert chapters == {"I", "II", "III", "IV", "V"}

    # Patent-critical parts must be present.
    for part in ("1", "3", "11", "41", "42"):
        assert part in TITLE37_PARTS
        assert len(TITLE37_SECTION_CATALOG[part]) >= 3

    total = title37_section_count()
    assert total == len(title37_all_section_tokens())
    assert total == sum(len(v) for v in TITLE37_SECTION_CATALOG.values())
    assert total >= 500  # full inventory, not a handful of cross-check anchors


def test_manifest_schema_file_exists_and_is_valid(schema_doc: dict) -> None:
    assert schema_doc["$schema"].startswith("https://json-schema.org/draft/2020-12")
    assert schema_doc["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    assert schema_doc["properties"]["task_id"]["const"] == TASK_ID
    assert "edition_identity" in schema_doc["required"]
    assert "inventory" in schema_doc["required"]
    # Empty inventory rejected at schema level.
    assert schema_doc["properties"]["inventory"]["minItems"] == 1
    # Unpinned latest rejected on identity fields.
    year_not = schema_doc["$defs"]["year"]["not"]["pattern"]
    assert "latest" in year_not.lower()
    pkg_not = schema_doc["$defs"]["packageId"]["not"]["pattern"]
    assert "latest" in pkg_not.lower()

    path = manifest_schema_path(_REPO_ROOT)
    assert path == _SCHEMA_PATH
    loaded = load_manifest_schema(_REPO_ROOT)
    assert loaded["title"] == schema_doc["title"]

    if jsonschema is not None:
        jsonschema.Draft202012Validator.check_schema(schema_doc)


# ---------------------------------------------------------------------------
# Edition identity
# ---------------------------------------------------------------------------


def test_edition_identity_for_year_is_pinned() -> None:
    identity = EditionIdentity.for_year(2024)
    assert identity.year == "2024"
    assert identity.package_id == "CFR-2024-title37"
    assert identity.title == DEFAULT_TITLE
    assert identity.edition == "annual-2024"
    assert identity.authority_tier == "official-base"
    assert identity.provider == "govinfo"
    _assert_round_trip(identity)


def test_edition_identity_rejects_missing_year_and_package() -> None:
    with pytest.raises(MissingEditionIdentityError):
        EditionIdentity.from_dict({})
    with pytest.raises(MissingEditionIdentityError):
        EditionIdentity(year="", package_id="")
    with pytest.raises(MissingEditionIdentityError):
        EditionIdentity.from_dict({"edition": "annual-2024"})


def test_edition_identity_rejects_unpinned_latest() -> None:
    with pytest.raises(UnpinnedLatestError):
        EditionIdentity.for_year("latest")
    with pytest.raises(UnpinnedLatestError):
        EditionIdentity(
            year="2024",
            package_id="CFR-2024-title37",
            edition="latest",
        )
    with pytest.raises(UnpinnedLatestError):
        EditionIdentity.from_dict(
            {
                "year": "latest",
                "package_id": "CFR-2024-title37",
            }
        )
    with pytest.raises(UnpinnedLatestError):
        EditionIdentity.from_dict(
            {
                "year": "2024",
                "package_id": "latest",
            }
        )
    with pytest.raises(UnpinnedLatestError):
        EditionIdentity(
            year="2024",
            package_id="CFR-2024-title37",
            provider="latest",
        )


def test_edition_identity_rejects_non_title37_package() -> None:
    with pytest.raises(MissingEditionIdentityError):
        EditionIdentity(year="2024", package_id="CFR-2024-title35")


def test_edition_identity_rejects_non_official_tier() -> None:
    with pytest.raises(SchemaValidationError):
        EditionIdentity(
            year="2024",
            package_id="CFR-2024-title37",
            authority_tier="unofficial-current",
        )


# ---------------------------------------------------------------------------
# Inventory builders
# ---------------------------------------------------------------------------


def test_full_inventory_enumerates_all_title37_sections() -> None:
    identity = EditionIdentity.for_year(2024)
    inventory = build_full_title37_inventory(identity)
    catalog = set(title37_all_section_tokens())
    have = {e.section for e in inventory}
    assert have == catalog
    assert len(inventory) == title37_section_count()
    # Every catalog part appears.
    assert {e.part for e in inventory} == set(TITLE37_PARTS)
    # Stable ids and citations are well-formed.
    sample = next(e for e in inventory if e.section == "1.56")
    assert sample.stable_id == "cfr:us:37:1.56"
    assert sample.citation == "37 CFR 1.56"
    assert sample.part == "1"
    assert sample.chapter == "I"
    assert sample.granule_id == "CFR-2024-title37-part1-sec1-56"
    assert "govinfo.gov" in (sample.source_url or "")


def test_full_inventory_with_gaps() -> None:
    inventory = build_full_title37_inventory(
        2024, gap_sections=["1.56", "not-a-real-but-normalized"]
    )
    # Only real catalog sections become gaps.
    gap_rows = [e for e in inventory if e.presence is SectionPresence.GAP]
    # "not-a-real-but-normalized" is not in catalog so only 1.56 if present.
    assert any(e.section == "1.56" for e in gap_rows)
    gaps = build_gap_records_for_inventory(
        inventory, reason=GapReason.ACQUISITION_PENDING
    )
    assert {g.section for g in gaps} == {e.section for e in gap_rows}
    assert all(g.reason is GapReason.ACQUISITION_PENDING for g in gaps)


def test_build_full_manifest_covers_catalog(
    pinned_manifest: CfrTitle37FullManifest,
) -> None:
    pinned_manifest.assert_full_catalog_coverage()
    assert pinned_manifest.edition_identity.package_id == "CFR-2024-title37"
    assert pinned_manifest.counts is not None
    assert pinned_manifest.counts.total_sections == title37_section_count()
    assert pinned_manifest.counts.total_parts == len(TITLE37_PARTS)
    assert pinned_manifest.counts.gap_sections == 2
    assert pinned_manifest.package_binding.package_id == "CFR-2024-title37"
    assert len(pinned_manifest.package_binding.package_digest_sha256) == 64
    assert pinned_manifest.inventory_digest_sha256 == content_digest_of(
        [e.to_dict() for e in pinned_manifest.inventory]
    )


def test_manifest_round_trip(pinned_manifest: CfrTitle37FullManifest) -> None:
    first = pinned_manifest.to_dict()
    restored = CfrTitle37FullManifest.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    assert restored.inventory_digest_sha256 == pinned_manifest.inventory_digest_sha256
    assert restored.content_digest() == pinned_manifest.content_digest()


def test_repeat_build_is_content_address_stable() -> None:
    a = build_full_title37_manifest(2024, gap_sections=["1.56"])
    b = build_full_title37_manifest(2024, gap_sections=["1.56"])
    assert a.inventory_digest_sha256 == b.inventory_digest_sha256
    assert a.package_binding.package_digest_sha256 == b.package_binding.package_digest_sha256
    assert a.to_canonical_bytes() == b.to_canonical_bytes()


# ---------------------------------------------------------------------------
# Fail-closed validation (acceptance)
# ---------------------------------------------------------------------------


def test_rejects_missing_edition_identity(pinned_manifest: CfrTitle37FullManifest) -> None:
    payload = pinned_manifest.to_dict()
    del payload["edition_identity"]
    with pytest.raises(MissingEditionIdentityError):
        validate_manifest(payload, require_full_catalog=False)
    with pytest.raises(MissingEditionIdentityError):
        CfrTitle37FullManifest.from_dict(payload)

    payload = pinned_manifest.to_dict()
    payload["edition_identity"] = {}
    with pytest.raises(MissingEditionIdentityError):
        validate_manifest(payload, require_full_catalog=False)

    payload = pinned_manifest.to_dict()
    payload["edition_identity"] = None
    with pytest.raises(MissingEditionIdentityError):
        validate_manifest(payload, require_full_catalog=False)


def test_rejects_empty_inventory(pinned_manifest: CfrTitle37FullManifest) -> None:
    payload = pinned_manifest.to_dict()
    payload["inventory"] = []
    payload["counts"] = {
        "total_sections": 0,
        "total_parts": 0,
        "present_sections": 0,
        "gap_sections": 0,
        "by_part": {},
        "by_chapter": {},
    }
    payload["gaps"] = []
    with pytest.raises(EmptyInventoryError):
        validate_manifest(payload, require_full_catalog=False)
    with pytest.raises(EmptyInventoryError):
        CfrTitle37FullManifest.from_dict(payload)


def test_rejects_unpinned_latest_in_manifest(
    pinned_manifest: CfrTitle37FullManifest,
) -> None:
    payload = pinned_manifest.to_dict()
    payload["edition_identity"] = dict(payload["edition_identity"])
    payload["edition_identity"]["edition"] = "latest"
    with pytest.raises(UnpinnedLatestError):
        validate_manifest(payload, require_full_catalog=False)

    payload = pinned_manifest.to_dict()
    payload["edition_identity"] = dict(payload["edition_identity"])
    payload["edition_identity"]["year"] = "latest"
    with pytest.raises(UnpinnedLatestError):
        validate_manifest(payload, require_full_catalog=False)

    payload = pinned_manifest.to_dict()
    payload["edition_identity"] = dict(payload["edition_identity"])
    payload["edition_identity"]["package_id"] = "latest"
    with pytest.raises(UnpinnedLatestError):
        validate_manifest(payload, require_full_catalog=False)


def test_rejects_incomplete_catalog_coverage() -> None:
    identity = EditionIdentity.for_year(2024)
    # Only a single cross-check style section — not full Title 37.
    entry = InventorySectionEntry(
        part="1",
        section="1.56",
        heading="Duty to disclose",
        chapter="I",
        presence=SectionPresence.PRESENT,
    )
    binding = build_package_binding(identity, inventory=[entry])
    manifest = CfrTitle37FullManifest(
        edition_identity=identity,
        inventory=(entry,),
        package_binding=binding,
        gaps=(),
    )
    with pytest.raises(IncompleteInventoryError):
        manifest.assert_full_catalog_coverage()
    with pytest.raises(IncompleteInventoryError):
        validate_manifest(manifest, require_full_catalog=True)


def test_rejects_missing_package_binding(
    pinned_manifest: CfrTitle37FullManifest,
) -> None:
    payload = pinned_manifest.to_dict()
    del payload["package_binding"]
    with pytest.raises(PackageBindingError):
        CfrTitle37FullManifest.from_dict(payload)


def test_gap_consistency_enforced() -> None:
    identity = EditionIdentity.for_year(2024)
    entry = InventorySectionEntry(
        part="1",
        section="1.56",
        presence=SectionPresence.GAP,
    )
    binding = build_package_binding(identity, inventory=[entry])
    # Missing gap record for presence=gap.
    with pytest.raises(Exception) as exc_info:
        CfrTitle37FullManifest(
            edition_identity=identity,
            inventory=(entry,),
            package_binding=binding,
            gaps=(),
        )
    assert "gap" in str(exc_info.value).lower()

    # Matching gap record is accepted (without full-catalog requirement).
    gap = GapRecord(
        section="1.56",
        part="1",
        reason=GapReason.GRANULE_MISSING,
        note="fixture gap",
    )
    manifest = CfrTitle37FullManifest(
        edition_identity=identity,
        inventory=(entry,),
        package_binding=binding,
        gaps=(gap,),
    )
    assert manifest.counts is not None
    assert manifest.counts.gap_sections == 1
    assert manifest.counts.present_sections == 0


def test_gap_row_cannot_carry_content_digest() -> None:
    with pytest.raises(Exception):
        InventorySectionEntry(
            part="1",
            section="1.56",
            presence=SectionPresence.GAP,
            content_sha256=DIGEST_A,
        )


def test_package_binding_must_match_edition() -> None:
    identity = EditionIdentity.for_year(2024)
    other = PackageBinding(
        package_id="CFR-2023-title37",
        package_digest_sha256=DIGEST_A,
    )
    entry = InventorySectionEntry(part="1", section="1.56")
    with pytest.raises(PackageBindingError):
        CfrTitle37FullManifest(
            edition_identity=identity,
            inventory=(entry,),
            package_binding=other,
        )


# ---------------------------------------------------------------------------
# JSON Schema rejection paths (acceptance)
# ---------------------------------------------------------------------------


def test_json_schema_rejects_missing_edition_identity(
    pinned_manifest: CfrTitle37FullManifest, schema_doc: dict
) -> None:
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    payload = pinned_manifest.to_dict()
    del payload["edition_identity"]
    validator = jsonschema.Draft202012Validator(schema_doc)
    errors = list(validator.iter_errors(payload))
    assert errors
    assert any("edition_identity" in e.message or list(e.path) == [] for e in errors)


def test_json_schema_rejects_empty_inventory(
    pinned_manifest: CfrTitle37FullManifest, schema_doc: dict
) -> None:
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    payload = pinned_manifest.to_dict()
    payload["inventory"] = []
    validator = jsonschema.Draft202012Validator(schema_doc)
    errors = list(validator.iter_errors(payload))
    assert any("inventory" in str(list(e.absolute_path)) or "minItems" in e.message or e.validator == "minItems" for e in errors)


def test_json_schema_rejects_unpinned_latest(
    pinned_manifest: CfrTitle37FullManifest, schema_doc: dict
) -> None:
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    validator = jsonschema.Draft202012Validator(schema_doc)

    for field, value in (
        ("year", "latest"),
        ("package_id", "latest"),
        ("edition", "latest"),
    ):
        payload = copy.deepcopy(pinned_manifest.to_dict())
        payload["edition_identity"][field] = value
        errors = list(validator.iter_errors(payload))
        assert errors, f"expected schema rejection for edition_identity.{field}=latest"


def test_json_schema_accepts_pinned_full_manifest(
    pinned_manifest: CfrTitle37FullManifest, schema_doc: dict
) -> None:
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    validate_against_json_schema(pinned_manifest, schema=schema_doc, repo_root=_REPO_ROOT)
    jsonschema.Draft202012Validator(schema_doc).validate(pinned_manifest.to_dict())


def test_json_schema_rejects_zero_total_sections(
    pinned_manifest: CfrTitle37FullManifest, schema_doc: dict
) -> None:
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    payload = copy.deepcopy(pinned_manifest.to_dict())
    # Keep inventory non-empty for this probe; only counts.total_sections = 0.
    payload["counts"]["total_sections"] = 0
    validator = jsonschema.Draft202012Validator(schema_doc)
    errors = list(validator.iter_errors(payload))
    assert errors


# ---------------------------------------------------------------------------
# Counts / digests / misc records
# ---------------------------------------------------------------------------


def test_inventory_counts_from_inventory() -> None:
    entries = [
        InventorySectionEntry(part="1", section="1.56", chapter="I"),
        InventorySectionEntry(
            part="41", section="41.50", chapter="I", presence=SectionPresence.GAP
        ),
    ]
    # Need gap record only when building full manifest; counts helper is direct.
    counts = InventoryCounts.from_inventory(entries)
    assert counts.total_sections == 2
    assert counts.total_parts == 2
    assert counts.present_sections == 1
    assert counts.gap_sections == 1
    assert counts.by_part["1"] == 1
    assert counts.by_part["41"] == 1
    _assert_round_trip(counts)


def test_empty_counts_rejected() -> None:
    with pytest.raises(EmptyInventoryError):
        InventoryCounts(
            total_sections=0,
            total_parts=0,
            present_sections=0,
            gap_sections=0,
        )
    with pytest.raises(EmptyInventoryError):
        InventoryCounts.from_inventory([])


def test_section_part_mismatch_rejected() -> None:
    with pytest.raises(SchemaValidationError):
        InventorySectionEntry(part="41", section="1.56")


def test_package_binding_round_trip() -> None:
    binding = PackageBinding(
        package_id="CFR-2024-title37",
        package_digest_sha256=DIGEST_A,
        package_root_cid=CID_SAMPLE,
        xml_sha256=DIGEST_B,
        source_url="https://www.govinfo.gov/content/pkg/CFR-2024-title37/xml/CFR-2024-title37.xml",
    )
    _assert_round_trip(binding)
    with pytest.raises(PackageBindingError):
        PackageBinding.from_dict({"package_id": "CFR-2024-title37"})


def test_validate_manifest_object_passthrough(
    pinned_manifest: CfrTitle37FullManifest,
) -> None:
    out = validate_manifest(pinned_manifest, require_full_catalog=True)
    assert out is pinned_manifest


def test_different_years_produce_distinct_package_ids() -> None:
    m2023 = build_full_title37_manifest(2023)
    m2024 = build_full_title37_manifest(2024)
    assert m2023.edition_identity.package_id == "CFR-2023-title37"
    assert m2024.edition_identity.package_id == "CFR-2024-title37"
    assert m2023.inventory_digest_sha256 != m2024.inventory_digest_sha256 or True
    # Inventory section set is the same catalog; digests may still differ via
    # granule_id / source_url which embed package_id.
    assert m2023.inventory_digest_sha256 != m2024.inventory_digest_sha256


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_round_trip(record: object) -> None:
    assert hasattr(record, "to_dict") and hasattr(type(record), "from_dict")
    first = record.to_dict()  # type: ignore[attr-defined]
    restored = type(record).from_dict(first)  # type: ignore[attr-defined]
    second = restored.to_dict()  # type: ignore[attr-defined]
    assert first == second
    assert canonical_json(first) == canonical_json(second)
