"""Unit tests for canonical U.S. Code section and edition identity (USCIR-006).

Acceptance:

* All 1,798 known truncated-ID collision rows remain distinguishable.
* Unicode section fixtures parse fully.
* Duplicate primary keys fail validation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.uscode_identity import (
    FIXTURE_SCHEMA_VERSION,
    KNOWN_TRUNCATED_COLLISION_COUNT,
    SCHEMA_VERSION,
    CollisionFixtureError,
    DuplicatePrimaryKeyError,
    IdentityParseError,
    LegalIdentity,
    UscodeIdentityError,
    assert_legal_ids_distinguishable,
    build_canonical_citation,
    build_chunk_parent_id,
    build_default_collision_fixture_payload,
    build_legal_id,
    default_collision_fixture_path,
    expand_collision_fixture,
    identity_from_row,
    load_collision_fixture,
    load_collision_fixture_payload,
    naive_truncated_section_token,
    normalize_dash_chars,
    normalize_section_token,
    normalize_title,
    parse_chunk_id,
    parse_legal_id,
    unicode_section_fixtures,
    validate_primary_keys,
)

# tests/unit/processors/legal_data/this_file.py → tests/
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "uscode_identity_collisions.json"
)


@pytest.fixture(scope="module")
def collision_payload() -> dict:
    return load_collision_fixture_payload(_FIXTURE_PATH)


@pytest.fixture(scope="module")
def collision_rows(collision_payload: dict) -> list[dict]:
    return expand_collision_fixture(collision_payload)


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_collision_fixture_is_present_and_compact():
    assert _FIXTURE_PATH.is_file()
    assert default_collision_fixture_path().name == "uscode_identity_collisions.json"
    # Compact recipe must stay well under a bulk golden dump.
    size = _FIXTURE_PATH.stat().st_size
    assert size < 64_000
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert payload["expected_row_count"] == KNOWN_TRUNCATED_COLLISION_COUNT
    # Recipe form: generators present, not 1,798 inline rows.
    assert "generators" in payload
    assert len(payload.get("seed_rows") or []) < 50


def test_default_payload_matches_on_disk_recipe():
    built = build_default_collision_fixture_payload()
    on_disk = load_collision_fixture_payload(_FIXTURE_PATH)
    assert built["schema_version"] == on_disk["schema_version"]
    assert built["expected_row_count"] == on_disk["expected_row_count"]
    assert len(expand_collision_fixture(built)) == KNOWN_TRUNCATED_COLLISION_COUNT


# ---------------------------------------------------------------------------
# Acceptance: 1,798 truncated-ID collision rows remain distinguishable
# ---------------------------------------------------------------------------


def test_all_known_truncated_collision_rows_remain_distinguishable(collision_rows):
    assert len(collision_rows) == KNOWN_TRUNCATED_COLLISION_COUNT
    legal_ids = assert_legal_ids_distinguishable(collision_rows)
    assert len(legal_ids) == KNOWN_TRUNCATED_COLLISION_COUNT
    assert len(set(legal_ids)) == KNOWN_TRUNCATED_COLLISION_COUNT


def test_load_collision_fixture_helper_returns_1798_rows():
    rows = load_collision_fixture(_FIXTURE_PATH)
    assert len(rows) == KNOWN_TRUNCATED_COLLISION_COUNT
    validate_primary_keys(rows)


def test_dash_pairs_collide_under_naive_truncation_but_not_repaired_ids(collision_rows):
    families: dict[str, list[dict]] = {}
    for row in collision_rows:
        family = row.get("collision_family") or ""
        if family.startswith("dash-pair-") or family.startswith("seed-en-dash") or family.startswith(
            "seed-em-dash"
        ):
            families.setdefault(family, []).append(row)

    # At least the seed dash families and generated pairs must be present.
    assert any(f.startswith("dash-pair-") for f in families)
    checked = 0
    for family, members in families.items():
        if len(members) < 2:
            continue
        naive_keys = {m["naive_truncated_section"] for m in members}
        repaired = {m["legal_id"] for m in members}
        # Truncated tokens collide within the family...
        assert len(naive_keys) < len(members), (family, naive_keys, members)
        # ...but repaired legal_ids never do.
        assert len(repaired) == len(members)
        checked += 1
    assert checked >= 10


def test_naive_truncation_drops_en_dash_range_tail():
    assert naive_truncated_section_token("1001–1003") == "1001"
    assert naive_truncated_section_token("1001—1003") == "1001"
    assert normalize_section_token("1001–1003") == "1001-1003"
    assert normalize_section_token("1001—1003") == "1001-1003"
    assert build_legal_id(title="26", section="1001–1003") != build_legal_id(
        title="26", section="1001"
    )


def test_qualifier_rows_disambiguate_shared_title_section(collision_rows):
    by_title_section: dict[tuple[str, str], list[dict]] = {}
    for row in collision_rows:
        if not str(row.get("row_id", "")).startswith("qual-") and not str(
            row.get("row_id", "")
        ).startswith("seed-appendix") and not str(row.get("row_id", "")).startswith("seed-note") and not str(
            row.get("row_id", "")
        ).startswith("seed-granule"):
            continue
        key = (str(row["title"]), str(row["normalized_section"]))
        by_title_section.setdefault(key, []).append(row)

    disambiguated = 0
    for members in by_title_section.values():
        if len(members) < 2:
            continue
        legal_ids = {m["legal_id"] for m in members}
        assert len(legal_ids) == len(members)
        disambiguated += 1
    assert disambiguated >= 1


# ---------------------------------------------------------------------------
# Acceptance: Unicode section fixtures parse fully
# ---------------------------------------------------------------------------


def test_unicode_section_fixtures_parse_fully(collision_payload):
    fixtures = unicode_section_fixtures(collision_payload)
    assert len(fixtures) >= 8
    for item in fixtures:
        normalized = normalize_section_token(item["section"])
        assert normalized == item["expected_section"], item
        # Full parse must not equal naive truncation when Unicode dashes remain
        # in the source token (the failure mode under repair).
        if any(ch in item["section"] for ch in ("\u2013", "\u2014", "\u2212", "\u2011")):
            naive = naive_truncated_section_token(item["section"])
            assert naive != normalized, (item, naive, normalized)
        identity = identity_from_row(item)
        assert identity.section == item["expected_section"]
        assert identity.legal_id.startswith("usc:us:")
        # Round-trip legal_id.
        restored = parse_legal_id(identity.legal_id)
        assert restored.section == identity.section
        assert restored.title == identity.title


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1001–1003", "1001-1003"),
        ("1001—1003", "1001-1003"),
        ("1001−1003", "1001-1003"),
        ("1001-1003", "1001-1003"),
        ("§ 122", "122"),
        ("section 122", "122"),
        ("35 U.S.C. § 122", "122"),
        ("Sec. 181(a)", "181(a)"),
        ("0101a", "101a"),
        ("552(a)–(e)", "552(a)-(e)"),
        ("2000e–2", "2000e-2"),
        ("106A–106B", "106A-106B"),
    ],
)
def test_normalize_section_token_unicode_and_citation_forms(raw, expected):
    assert normalize_section_token(raw) == expected


def test_normalize_dash_chars_does_not_truncate():
    text = "1001–1003—1005−1007"
    assert normalize_dash_chars(text) == "1001-1003-1005-1007"


def test_empty_section_raises():
    with pytest.raises(IdentityParseError):
        normalize_section_token("")
    with pytest.raises(IdentityParseError):
        normalize_section_token(None)


# ---------------------------------------------------------------------------
# Acceptance: duplicate primary keys fail validation
# ---------------------------------------------------------------------------


def test_duplicate_primary_keys_fail_validation(collision_rows):
    validate_primary_keys(collision_rows)  # unique set passes

    dup = list(collision_rows[:3])
    dup.append(dict(dup[0]))  # clone first row → duplicate entry_cid
    with pytest.raises(DuplicatePrimaryKeyError) as excinfo:
        validate_primary_keys(dup)
    assert "duplicate primary key" in str(excinfo.value).lower()


def test_missing_primary_key_fails_validation():
    rows = [
        {"entry_cid": "a" * 64, "title": "35", "section": "101"},
        {"title": "35", "section": "102"},  # missing entry_cid
    ]
    with pytest.raises(UscodeIdentityError):
        validate_primary_keys(rows)


def test_duplicate_legal_id_rejected_by_assert_helper():
    rows = [
        {"title": "35", "section": "101", "entry_cid": "a" * 64},
        {"title": "35", "section": "101", "entry_cid": "b" * 64},
    ]
    with pytest.raises(UscodeIdentityError):
        assert_legal_ids_distinguishable(rows)


# ---------------------------------------------------------------------------
# legal_id / citation / chunk parent identity
# ---------------------------------------------------------------------------


def test_build_legal_id_simple_and_qualified():
    simple = build_legal_id(title="35", section="122")
    assert simple == "usc:us:35:122"
    assert SCHEMA_VERSION.startswith("uscode-identity")

    qualified = build_legal_id(
        title="28",
        section="1291",
        appendix="A",
        note="historical",
        edition="olrc-us-pl-118-45",
        granule="USC-prelim-title28-section1291",
        kind="appendix",
    )
    assert qualified.startswith("usc:us:28:1291;")
    assert "appendix=a" in qualified
    assert "edition=olrc-us-pl-118-45" in qualified
    assert "granule=usc-prelim-title28-section1291" in qualified
    assert "kind=appendix" in qualified
    assert "note=historical" in qualified
    # Qualifiers are sorted for determinism.
    assert qualified == (
        "usc:us:28:1291;appendix=a;edition=olrc-us-pl-118-45;"
        "granule=usc-prelim-title28-section1291;kind=appendix;note=historical"
    )


def test_canonical_citation_text():
    cite = build_canonical_citation(title="5", section="552")
    assert cite == "5 U.S.C. § 552"
    cite_app = build_canonical_citation(title="28", section="1291", appendix="A")
    assert "28 U.S.C. § 1291" in cite_app
    assert "app. a" in cite_app


def test_chunk_parent_identity_is_deterministic():
    parent = build_chunk_parent_id(title="42", section="1983")
    assert parent == "usc:us:42:1983"
    identity = LegalIdentity(title="42", section="1983", subsection="a", kind="subsection")
    assert identity.parent_legal_id == "usc:us:42:1983"
    chunk0 = identity.chunk_id(0)
    chunk1 = identity.chunk_id(1)
    assert chunk0 != chunk1
    assert parse_chunk_id(chunk0) == (parent, 0)
    assert parse_chunk_id(chunk1) == (parent, 1)


def test_parse_legal_id_round_trip():
    legal_id = build_legal_id(
        title="26",
        section="1001–1003",
        edition="govinfo-2023",
        note="editorial",
    )
    restored = parse_legal_id(legal_id)
    assert restored.legal_id == legal_id
    assert restored.section == "1001-1003"
    assert restored.edition == "govinfo-2023"
    assert restored.note == "editorial"


def test_normalize_title():
    assert normalize_title("35") == "35"
    assert normalize_title("035") == "35"
    assert normalize_title("10A") == "10a"


def test_identity_to_dict_contains_schema_version():
    identity = LegalIdentity(title="35", section="§ 101")
    payload = identity.to_dict()
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["section"] == "101"
    assert payload["legal_id"] == "usc:us:35:101"
    assert payload["canonical_citation"] == "35 U.S.C. § 101"


def test_malformed_fixture_rejected():
    with pytest.raises(CollisionFixtureError):
        expand_collision_fixture({"schema_version": "nope", "expected_row_count": 1798})
    with pytest.raises(CollisionFixtureError):
        expand_collision_fixture(
            {
                "schema_version": FIXTURE_SCHEMA_VERSION,
                "expected_row_count": 10,
                "generators": [],
                "seed_rows": [],
            }
        )
