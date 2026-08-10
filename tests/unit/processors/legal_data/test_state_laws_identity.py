"""Unit tests for canonical jurisdiction and statute identity (LCR-006).

Acceptance:

* Logical statute duplicates and changed-text versions receive explicit
  deterministic dispositions.
* Row position and content CID alone cannot merge versions incorrectly.
* Unicode section fixtures parse fully; dash-truncated collisions stay
  distinguishable under repaired legal_id.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_identity import (
    FIXTURE_SCHEMA_VERSION,
    KNOWN_COLLISION_ROW_COUNT,
    SCHEMA_VERSION,
    CollisionFixtureError,
    DuplicatePrimaryKeyError,
    IdentityDisposition,
    IdentityParseError,
    LegalIdentity,
    StateLawsIdentityError,
    assert_legal_ids_distinguishable,
    build_canonical_citation,
    build_chunk_parent_id,
    build_default_collision_fixture_payload,
    build_legal_id,
    classify_identity_pair,
    content_identity_from_row,
    default_collision_fixture_path,
    disposition_cases,
    expand_collision_fixture,
    identity_from_row,
    legal_id_from_row,
    load_collision_fixture,
    load_collision_fixture_payload,
    merge_by_legal_identity,
    naive_truncated_section_token,
    normalize_dash_chars,
    normalize_jurisdiction,
    normalize_section_token,
    parse_chunk_id,
    parse_legal_id,
    reject_positional_or_cid_only_merge,
    resolve_version_dispositions,
    unicode_section_fixtures,
    validate_primary_keys,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    CANONICAL_JURISDICTIONS,
    EXPECTED_JURISDICTION_COUNT,
    validate_legal_id as schema_validate_legal_id,
)

# tests/unit/processors/legal_data/this_file.py → tests/
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "state_laws_identity_collisions.json"
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
    assert default_collision_fixture_path().name == "state_laws_identity_collisions.json"
    size = _FIXTURE_PATH.stat().st_size
    assert size < 64_000
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert payload["expected_row_count"] == KNOWN_COLLISION_ROW_COUNT
    assert "generators" in payload
    assert len(payload.get("seed_rows") or []) < 50
    assert len(payload.get("disposition_cases") or []) >= 4


def test_default_payload_matches_on_disk_recipe():
    built = build_default_collision_fixture_payload()
    on_disk = load_collision_fixture_payload(_FIXTURE_PATH)
    assert built["schema_version"] == on_disk["schema_version"]
    assert built["expected_row_count"] == on_disk["expected_row_count"]
    assert len(expand_collision_fixture(built)) == KNOWN_COLLISION_ROW_COUNT
    # Generator kinds must match so recipe and on-disk stay aligned.
    assert [g["kind"] for g in built["generators"]] == [
        g["kind"] for g in on_disk["generators"]
    ]


def test_load_collision_fixture_helper_returns_expected_rows():
    rows = load_collision_fixture(_FIXTURE_PATH)
    assert len(rows) == KNOWN_COLLISION_ROW_COUNT
    validate_primary_keys(rows)


# ---------------------------------------------------------------------------
# Acceptance: dispositions for duplicates and changed-text versions
# ---------------------------------------------------------------------------


def test_disposition_cases_are_deterministic(collision_payload):
    cases = disposition_cases(collision_payload)
    assert len(cases) >= 4
    for case in cases:
        result = classify_identity_pair(case["left"], case["right"])
        assert result["disposition"] == case["expected_disposition"], case["case_id"]
        guarded = reject_positional_or_cid_only_merge(case["left"], case["right"])
        assert guarded["disposition"] == case["expected_disposition"]


def test_logical_duplicate_disposition():
    left = {
        "jurisdiction": "OR",
        "code_family": "ors",
        "title": "123",
        "section": "456",
        "entry_cid": "a" * 64,
        "text": "same",
    }
    right = dict(left)
    result = classify_identity_pair(left, right)
    assert result["disposition"] == IdentityDisposition.DUPLICATE.value
    assert result["same_legal_id"] is True
    assert result["merge_allowed"] is True


def test_changed_text_version_disposition():
    left = {
        "jurisdiction": "MN",
        "code_family": "minnesota-statutes",
        "title": "518",
        "section": "17",
        "entry_cid": "b" * 64,
        "text": "old body",
    }
    right = {
        "jurisdiction": "MN",
        "code_family": "minnesota-statutes",
        "title": "518",
        "section": "17",
        "entry_cid": "c" * 64,
        "text": "new body",
    }
    result = classify_identity_pair(left, right)
    assert result["disposition"] == IdentityDisposition.CHANGED_TEXT_VERSION.value
    assert result["version_pair"] is True
    assert result["same_legal_id"] is True
    assert result["same_content_id"] is False


def test_resolve_version_dispositions_archives_history():
    rows = [
        {
            "jurisdiction": "OR",
            "code_family": "ors",
            "title": "123",
            "section": "456",
            "entry_cid": "1" * 64,
            "text": "v1",
        },
        {
            "jurisdiction": "OR",
            "code_family": "ors",
            "title": "123",
            "section": "456",
            "entry_cid": "1" * 64,
            "text": "v1",
        },
        {
            "jurisdiction": "OR",
            "code_family": "ors",
            "title": "123",
            "section": "456",
            "entry_cid": "2" * 64,
            "text": "v2",
        },
    ]
    resolved = resolve_version_dispositions(rows)
    assert resolved["current_count"] == 1
    assert resolved["duplicate_count"] == 1
    assert resolved["changed_text_count"] == 1
    assert len(resolved["history_keys"]) == 1
    current = resolved["current_rows"][0]
    assert current["entry_cid"] == "2" * 64
    assert current["identity_disposition"] == IdentityDisposition.KEEP_CURRENT.value
    history = resolved["history_by_key"][current["legal_id"]]
    assert any(h["entry_cid"] == "1" * 64 for h in history)


def test_merge_by_legal_identity_prefers_new_content():
    existing = [
        {
            "jurisdiction": "MN",
            "code_family": "minnesota-statutes",
            "title": "518",
            "section": "17",
            "entry_cid": "old" + "0" * 61,
            "text": "old",
        }
    ]
    new_rows = [
        {
            "jurisdiction": "MN",
            "code_family": "minnesota-statutes",
            "title": "518",
            "section": "17",
            "entry_cid": "new" + "0" * 61,
            "text": "new",
        }
    ]
    merged = merge_by_legal_identity(existing, new_rows)
    assert len(merged["current_rows"]) == 1
    assert merged["current_rows"][0]["text"] == "new"
    assert merged["history_keys"]


def test_changed_text_fixture_pairs_receive_version_disposition(collision_rows):
    families: dict[str, list[dict]] = {}
    for row in collision_rows:
        family = str(row.get("collision_family") or "")
        if family.startswith("version-"):
            families.setdefault(family, []).append(row)
    assert len(families) >= 10
    for family, members in families.items():
        assert len(members) == 2
        result = classify_identity_pair(members[0], members[1])
        assert result["disposition"] == IdentityDisposition.CHANGED_TEXT_VERSION.value, family
        legal_ids = {legal_id_from_row(m) for m in members}
        assert len(legal_ids) == 1
        content_ids = {content_identity_from_row(m) for m in members}
        assert len(content_ids) == 2


# ---------------------------------------------------------------------------
# Acceptance: row position / content CID alone cannot merge incorrectly
# ---------------------------------------------------------------------------


def test_content_cid_alone_cannot_merge():
    left = {
        "jurisdiction": "CA",
        "code_family": "civil-code",
        "title": "1",
        "section": "100",
        "entry_cid": "a" * 64,
        "content_cid": "shared" + "0" * 58,
        "text": "boilerplate",
    }
    right = {
        "jurisdiction": "NY",
        "code_family": "penal-code",
        "title": "2",
        "section": "200",
        "entry_cid": "b" * 64,
        "content_cid": "shared" + "0" * 58,
        "text": "boilerplate",
    }
    result = classify_identity_pair(left, right)
    assert result["disposition"] == IdentityDisposition.REJECT_CONTENT_CID_ONLY_MERGE.value
    assert result["merge_allowed"] is False
    assert result["same_legal_id"] is False

    resolved = resolve_version_dispositions([left, right])
    assert resolved["current_count"] == 2
    assert any(
        e["disposition"] == IdentityDisposition.REJECT_CONTENT_CID_ONLY_MERGE.value
        for e in resolved["reject_events"]
    )


def test_row_position_alone_cannot_merge():
    left = {
        "jurisdiction": "TX",
        "code_family": "revised-statutes",
        "title": "1",
        "section": "10",
        "document_index": 42,
        "entry_cid": "1" * 64,
        "text": "alpha",
    }
    right = {
        "jurisdiction": "FL",
        "code_family": "official-code",
        "title": "2",
        "section": "20",
        "document_index": 42,
        "entry_cid": "2" * 64,
        "text": "beta",
    }
    result = classify_identity_pair(left, right)
    assert result["disposition"] == IdentityDisposition.REJECT_POSITIONAL_MERGE.value
    assert result["merge_allowed"] is False

    resolved = resolve_version_dispositions([left, right])
    assert resolved["current_count"] == 2
    assert any(
        e["disposition"] == IdentityDisposition.REJECT_POSITIONAL_MERGE.value
        for e in resolved["reject_events"]
    )


def test_fixture_content_cid_only_pairs_reject_merge(collision_rows):
    families: dict[str, list[dict]] = {}
    for row in collision_rows:
        family = str(row.get("collision_family") or "")
        if family.startswith("cid-only-"):
            families.setdefault(family, []).append(row)
    assert len(families) >= 5
    for family, members in families.items():
        assert len(members) == 2
        result = classify_identity_pair(members[0], members[1])
        assert (
            result["disposition"]
            == IdentityDisposition.REJECT_CONTENT_CID_ONLY_MERGE.value
        ), family
        assert legal_id_from_row(members[0]) != legal_id_from_row(members[1])


def test_fixture_positional_only_pairs_reject_merge(collision_rows):
    families: dict[str, list[dict]] = {}
    for row in collision_rows:
        family = str(row.get("collision_family") or "")
        if family.startswith("pos-only-"):
            families.setdefault(family, []).append(row)
    assert len(families) >= 5
    for family, members in families.items():
        assert len(members) == 2
        result = classify_identity_pair(members[0], members[1])
        assert (
            result["disposition"] == IdentityDisposition.REJECT_POSITIONAL_MERGE.value
        ), family


def test_positional_primary_key_rejected():
    rows = [
        {"entry_cid": "row-12", "jurisdiction": "OR", "code_family": "ors", "section": "1"},
    ]
    with pytest.raises(StateLawsIdentityError):
        validate_primary_keys(rows)


# ---------------------------------------------------------------------------
# Dash truncation / Unicode / legal_id construction
# ---------------------------------------------------------------------------


def test_dash_pairs_collide_under_naive_truncation_but_not_repaired_ids(collision_rows):
    families: dict[str, list[dict]] = {}
    for row in collision_rows:
        family = row.get("collision_family") or ""
        if (
            family.startswith("dash-pair-")
            or family.startswith("seed-en-dash")
            or family.startswith("seed-em-dash")
        ):
            families.setdefault(family, []).append(row)

    assert any(f.startswith("dash-pair-") for f in families)
    checked = 0
    for family, members in families.items():
        if len(members) < 2:
            continue
        naive_keys = {m["naive_truncated_section"] for m in members}
        repaired = {m["legal_id"] for m in members}
        assert len(naive_keys) < len(members), (family, naive_keys, members)
        assert len(repaired) == len(members)
        checked += 1
    assert checked >= 10


def test_naive_truncation_drops_en_dash_range_tail():
    assert naive_truncated_section_token("1001–1003") == "1001"
    assert naive_truncated_section_token("1001—1003") == "1001"
    assert normalize_section_token("1001–1003") == "1001-1003"
    assert normalize_section_token("1001—1003") == "1001-1003"
    assert build_legal_id(
        jurisdiction="OR", code_family="ors", title="1", section="1001–1003"
    ) != build_legal_id(
        jurisdiction="OR", code_family="ors", title="1", section="1001"
    )


def test_unicode_section_fixtures_parse_fully(collision_payload):
    fixtures = unicode_section_fixtures(collision_payload)
    assert len(fixtures) >= 8
    for item in fixtures:
        normalized = normalize_section_token(item["section"])
        assert normalized == item["expected_section"], item
        if any(ch in item["section"] for ch in ("\u2013", "\u2014", "\u2212", "\u2011")):
            naive = naive_truncated_section_token(item["section"])
            assert naive != normalized, (item, naive, normalized)
        identity = identity_from_row(item)
        assert identity.section == item["expected_section"]
        assert identity.legal_id.startswith("state:")
        assert identity.jurisdiction in CANONICAL_JURISDICTIONS
        restored = parse_legal_id(identity.legal_id)
        assert restored.section == identity.section
        assert restored.jurisdiction == identity.jurisdiction
        # Must satisfy the release-schema legal_id contract.
        schema_validate_legal_id(identity.legal_id)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1001–1003", "1001-1003"),
        ("1001—1003", "1001-1003"),
        ("1001−1003", "1001-1003"),
        ("1001-1003", "1001-1003"),
        ("§ 122", "122"),
        ("section 122", "122"),
        ("Sec. 181(a)", "181(a)"),
        ("0101a", "101a"),
        ("552(a)–(e)", "552(a)-(e)"),
        ("2000e–2", "2000e-2"),
        ("106A–106B", "106A-106B"),
        ("518.17", "518.17"),
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


def test_jurisdiction_must_be_exact_51_set():
    assert normalize_jurisdiction("or") == "OR"
    assert normalize_jurisdiction("DC") == "DC"
    assert len(CANONICAL_JURISDICTIONS) == EXPECTED_JURISDICTION_COUNT
    with pytest.raises(StateLawsIdentityError):
        normalize_jurisdiction("XX")
    with pytest.raises(StateLawsIdentityError):
        normalize_jurisdiction("PR")


def test_build_legal_id_simple_and_qualified():
    simple = build_legal_id(
        jurisdiction="OR",
        code_family="ors",
        title="123",
        section="456",
    )
    assert simple == "state:OR:ors:123:456"
    assert SCHEMA_VERSION.startswith("state-laws-identity")
    schema_validate_legal_id(simple)

    qualified = build_legal_id(
        jurisdiction="OR",
        code_family="ors",
        title="123",
        section="456",
        appendix="A",
        note="historical",
        edition="2023-official",
        granule="ors-title123-section456",
        kind="appendix",
    )
    assert qualified.startswith("state:OR:ors:123:456;")
    assert "appendix=a" in qualified
    assert "edition=2023-official" in qualified
    assert "kind=appendix" in qualified
    assert "note=historical" in qualified
    # Qualifiers sorted for determinism.
    assert qualified == (
        "state:OR:ors:123:456;appendix=a;edition=2023-official;"
        "granule=ors-title123-section456;kind=appendix;note=historical"
    )
    schema_validate_legal_id(qualified)


def test_code_family_and_history_disambiguate(collision_rows):
    by_path: dict[tuple[str, str, str], list[dict]] = {}
    for row in collision_rows:
        rid = str(row.get("row_id") or "")
        if not (
            rid.startswith("seed-family")
            or rid.startswith("seed-appendix")
            or rid.startswith("seed-note")
            or rid.startswith("seed-history")
            or rid.startswith("seed-granule")
            or rid.startswith("qual-")
            or rid.startswith("family-")
        ):
            continue
        key = (
            str(row["jurisdiction"]),
            str(row.get("title") or ""),
            str(row["normalized_section"]),
        )
        by_path.setdefault(key, []).append(row)

    disambiguated = 0
    for members in by_path.values():
        if len(members) < 2:
            continue
        legal_ids = {m["legal_id"] for m in members}
        assert len(legal_ids) == len(members)
        disambiguated += 1
    assert disambiguated >= 1


def test_canonical_citation_and_chunk_parent():
    cite = build_canonical_citation(
        jurisdiction="OR",
        code_family="ors",
        title="123",
        section="456",
    )
    assert "OR" in cite
    assert "§ 456" in cite
    parent = build_chunk_parent_id(
        jurisdiction="OR",
        code_family="ors",
        title="123",
        section="456",
    )
    assert parent == "state:OR:ors:123:456"
    identity = LegalIdentity(
        jurisdiction="OR",
        code_family="ors",
        title="123",
        section="456",
        subsection="a",
        kind="subsection",
    )
    assert identity.parent_legal_id == parent
    chunk0 = identity.chunk_id(0)
    chunk1 = identity.chunk_id(1)
    assert chunk0 != chunk1
    assert parse_chunk_id(chunk0) == (parent, 0)


def test_parse_legal_id_round_trip():
    legal_id = build_legal_id(
        jurisdiction="MN",
        code_family="minnesota-statutes",
        title="518",
        section="17",
        edition="2024-official",
        note="editorial",
    )
    restored = parse_legal_id(legal_id)
    assert restored.legal_id == legal_id
    assert restored.section == "17"
    assert restored.edition == "2024-official"
    assert restored.note == "editorial"


def test_identity_to_dict_contains_schema_version():
    identity = LegalIdentity(
        jurisdiction="OR",
        code_family="ors",
        title="123",
        section="§ 456",
    )
    payload = identity.to_dict()
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["section"] == "456"
    assert payload["legal_id"] == "state:OR:ors:123:456"


def test_duplicate_primary_keys_fail_validation(collision_rows):
    validate_primary_keys(collision_rows)
    dup = list(collision_rows[:3])
    dup.append(dict(dup[0]))
    with pytest.raises(DuplicatePrimaryKeyError) as excinfo:
        validate_primary_keys(dup)
    assert "duplicate primary key" in str(excinfo.value).lower()


def test_missing_primary_key_fails_validation():
    rows = [
        {
            "entry_cid": "a" * 64,
            "jurisdiction": "OR",
            "code_family": "ors",
            "section": "1",
        },
        {"jurisdiction": "OR", "code_family": "ors", "section": "2"},
    ]
    with pytest.raises(StateLawsIdentityError):
        validate_primary_keys(rows)


def test_assert_legal_ids_distinguishable_on_non_version_rows(collision_rows):
    # Exclude intentional version pairs (shared legal_id, different content).
    non_version = [
        r
        for r in collision_rows
        if not str(r.get("collision_family") or "").startswith("version-")
    ]
    legal_ids = assert_legal_ids_distinguishable(non_version)
    assert len(legal_ids) == len(set(legal_ids))


def test_assert_allows_version_collisions_when_flagged():
    rows = [
        {
            "jurisdiction": "OR",
            "code_family": "ors",
            "title": "1",
            "section": "1",
            "entry_cid": "a" * 64,
            "text": "v1",
        },
        {
            "jurisdiction": "OR",
            "code_family": "ors",
            "title": "1",
            "section": "1",
            "entry_cid": "b" * 64,
            "text": "v2",
        },
    ]
    with pytest.raises(StateLawsIdentityError):
        assert_legal_ids_distinguishable(rows)
    ids = assert_legal_ids_distinguishable(rows, allow_version_collisions=True)
    assert len(ids) == 2
    assert ids[0] == ids[1]


def test_malformed_fixture_rejected():
    with pytest.raises(CollisionFixtureError):
        expand_collision_fixture({"schema_version": "nope", "expected_row_count": 420})
    with pytest.raises(CollisionFixtureError):
        expand_collision_fixture(
            {
                "schema_version": FIXTURE_SCHEMA_VERSION,
                "expected_row_count": 10,
                "generators": [],
                "seed_rows": [],
            }
        )


def test_dc_is_first_class_jurisdiction():
    legal_id = build_legal_id(
        jurisdiction="DC",
        code_family="dc-official-code",
        title="22",
        section="3001",
    )
    assert legal_id == "state:DC:dc-official-code:22:3001"
    schema_validate_legal_id(legal_id)
