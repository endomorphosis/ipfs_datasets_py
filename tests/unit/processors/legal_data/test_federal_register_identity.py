"""Unit tests for canonical Federal Register identity and provenance (LCR-054).

Acceptance:

* Identity is stable across ordering and resume.
* Distinct legal versions (corrections, withdrawals, republications) do not
  collapse.
* Exact duplicates and duplicate source formats reconcile deterministically.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_identity import (
    FIXTURE_SCHEMA_VERSION,
    KNOWN_COLLISION_ROW_COUNT,
    SCHEMA_VERSION,
    CollisionFixtureError,
    DuplicatePrimaryKeyError,
    FederalRegisterIdentityError,
    IdentityDisposition,
    IdentityParseError,
    LegalIdentity,
    PositionalIdentityError,
    assert_legal_ids_distinguishable,
    build_canonical_citation,
    build_chunk_parent_id,
    build_default_collision_fixture_payload,
    build_legal_id,
    classify_identity_pair,
    compute_entry_cid,
    compute_source_cid,
    content_identity_from_row,
    default_collision_fixture_path,
    disposition_cases,
    enrich_row_identity,
    expand_collision_fixture,
    identity_from_row,
    legal_id_from_row,
    load_collision_fixture,
    load_collision_fixture_payload,
    merge_by_legal_identity,
    normalize_document_number,
    normalize_effective_date,
    normalize_publication_date,
    normalize_source_format,
    parse_chunk_id,
    parse_legal_id,
    reject_positional_or_cid_only_merge,
    resolve_version_dispositions,
    source_format_priority,
    validate_primary_keys,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    validate_legal_id as schema_validate_legal_id,
)

# tests/unit/processors/legal_data/this_file.py → tests/
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "federal_register_identity_collisions.json"
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
    assert default_collision_fixture_path().name == (
        "federal_register_identity_collisions.json"
    )
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
    assert [g["kind"] for g in built["generators"]] == [
        g["kind"] for g in on_disk["generators"]
    ]


def test_load_collision_fixture_helper_returns_expected_rows():
    rows = load_collision_fixture(_FIXTURE_PATH)
    assert len(rows) == KNOWN_COLLISION_ROW_COUNT
    validate_primary_keys(rows)


def test_all_fixture_rows_have_schema_valid_legal_ids(collision_rows):
    assert len(collision_rows) == KNOWN_COLLISION_ROW_COUNT
    for row in collision_rows:
        schema_validate_legal_id(row["legal_id"])
        assert row["legal_id"].startswith("fr:")
        assert row["entry_cid"]
        assert row["source_cid"]
        assert row["entry_cid"] != row["source_cid"] or row.get("text")


# ---------------------------------------------------------------------------
# Acceptance: identity stable across ordering and resume
# ---------------------------------------------------------------------------


def test_resolve_dispositions_is_order_independent(collision_rows):
    subset = [
        row
        for row in collision_rows
        if str(row.get("collision_family") or "").startswith(
            ("fmt-", "version-", "seed-format", "seed-version")
        )
    ]
    assert len(subset) >= 10
    forward = resolve_version_dispositions(subset)
    reversed_rows = list(reversed(subset))
    backward = resolve_version_dispositions(reversed_rows)
    # Current legal_ids and entry_cids must match regardless of input order.
    forward_keys = sorted(
        (r["legal_id"], r.get("entry_cid"), r.get("text")) for r in forward["current_rows"]
    )
    backward_keys = sorted(
        (r["legal_id"], r.get("entry_cid"), r.get("text")) for r in backward["current_rows"]
    )
    assert forward_keys == backward_keys
    assert forward["current_count"] == backward["current_count"]
    assert forward["duplicate_count"] == backward["duplicate_count"]
    assert forward["changed_text_count"] == backward["changed_text_count"]


def test_merge_by_legal_identity_resume_stable():
    existing = [
        {
            "document_number": "2021-22222",
            "publication_date": "2021-08-08",
            "document_type": "notice",
            "source_format": "html",
            "text": "version-one body",
            "entry_cid": "a" * 64,
            "acquisition_time": "2021-08-08T01:00:00Z",
        }
    ]
    new_rows = [
        {
            "document_number": "2021-22222",
            "publication_date": "2021-08-08",
            "document_type": "notice",
            "source_format": "html",
            "text": "version-two body",
            "entry_cid": "b" * 64,
            "acquisition_time": "2021-08-08T02:00:00Z",
        }
    ]
    merged_ab = merge_by_legal_identity(existing, new_rows)
    merged_ba = merge_by_legal_identity(new_rows, existing)
    assert merged_ab["current_count"] == 1
    assert merged_ba["current_count"] == 1
    assert merged_ab["current_rows"][0]["text"] == "version-two body"
    assert merged_ba["current_rows"][0]["text"] == "version-two body"
    assert merged_ab["history_keys"] == merged_ba["history_keys"]


# ---------------------------------------------------------------------------
# Acceptance: distinct legal versions do not collapse
# ---------------------------------------------------------------------------


def test_correction_pairs_remain_distinct(collision_rows):
    families: dict[str, list[dict]] = {}
    for row in collision_rows:
        family = str(row.get("collision_family") or "")
        if family.startswith("corr-") or family == "seed-basic":
            families.setdefault(family, []).append(row)
    assert len(families) >= 5
    for family, members in families.items():
        if len(members) < 2:
            continue
        legal_ids = {legal_id_from_row(m) for m in members}
        assert len(legal_ids) == len(members), family
        result = classify_identity_pair(members[0], members[1])
        assert result["same_legal_id"] is False
        assert result["disposition"] in {
            IdentityDisposition.CORRECTION_DISTINCT.value,
            IdentityDisposition.DISTINCT_IDENTITY.value,
        }
        assert result["merge_allowed"] is False


def test_withdrawal_pairs_remain_distinct(collision_rows):
    families: dict[str, list[dict]] = {}
    for row in collision_rows:
        family = str(row.get("collision_family") or "")
        if family.startswith("wd-") or family == "seed-withdrawal":
            families.setdefault(family, []).append(row)
    assert len(families) >= 5
    for family, members in families.items():
        if len(members) < 2:
            continue
        legal_ids = {legal_id_from_row(m) for m in members}
        assert len(legal_ids) == len(members), family
        result = classify_identity_pair(members[0], members[1])
        assert result["merge_allowed"] is False
        assert result["same_legal_id"] is False


def test_publication_date_variants_do_not_collapse(collision_rows):
    families: dict[str, list[dict]] = {}
    for row in collision_rows:
        family = str(row.get("collision_family") or "")
        if family.startswith("pubdate-") or family == "seed-pubdate":
            families.setdefault(family, []).append(row)
    assert len(families) >= 5
    for family, members in families.items():
        assert len(members) == 2
        docs = {m["document_number"] for m in members}
        dates = {m["publication_date"] for m in members}
        assert len(docs) == 1
        assert len(dates) == 2
        legal_ids = {legal_id_from_row(m) for m in members}
        assert len(legal_ids) == 2
        result = classify_identity_pair(members[0], members[1])
        assert result["disposition"] == IdentityDisposition.DISTINCT_IDENTITY.value
        assert result["merge_allowed"] is False


def test_changed_text_fixture_pairs_receive_version_disposition(collision_rows):
    families: dict[str, list[dict]] = {}
    for row in collision_rows:
        family = str(row.get("collision_family") or "")
        if family.startswith("version-") or family == "seed-version":
            families.setdefault(family, []).append(row)
    assert len(families) >= 10
    for family, members in families.items():
        assert len(members) == 2
        result = classify_identity_pair(members[0], members[1])
        assert (
            result["disposition"] == IdentityDisposition.CHANGED_TEXT_VERSION.value
        ), family
        legal_ids = {legal_id_from_row(m) for m in members}
        assert len(legal_ids) == 1
        content_ids = {content_identity_from_row(m) for m in members}
        assert len(content_ids) == 2


# ---------------------------------------------------------------------------
# Acceptance: exact duplicates reconcile deterministically
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
        "document_number": "2020-12345",
        "publication_date": "2020-06-15",
        "source_format": "html",
        "entry_cid": "a" * 64,
        "text": "same",
    }
    right = dict(left)
    result = classify_identity_pair(left, right)
    assert result["disposition"] == IdentityDisposition.DUPLICATE.value
    assert result["same_legal_id"] is True
    assert result["merge_allowed"] is True


def test_source_format_duplicates_reconcile_preferring_html(collision_rows):
    families: dict[str, list[dict]] = {}
    for row in collision_rows:
        family = str(row.get("collision_family") or "")
        if family.startswith("fmt-") or family == "seed-format":
            families.setdefault(family, []).append(row)
    assert len(families) >= 5
    for family, members in families.items():
        assert len(members) >= 2
        legal_ids = {legal_id_from_row(m) for m in members}
        assert len(legal_ids) == 1, family
        formats = {_source_format(m) for m in members}
        assert len(formats) >= 2
        # Pairwise: different formats → duplicate_source_format
        result = classify_identity_pair(members[0], members[1])
        assert result["same_legal_id"] is True
        assert result["disposition"] in {
            IdentityDisposition.DUPLICATE_SOURCE_FORMAT.value,
            IdentityDisposition.DUPLICATE.value,
        }
        if _source_format(members[0]) != _source_format(members[1]):
            assert (
                result["disposition"]
                == IdentityDisposition.DUPLICATE_SOURCE_FORMAT.value
            )
        resolved = resolve_version_dispositions(members)
        assert resolved["current_count"] == 1
        preferred = resolved["current_rows"][0]
        assert preferred["source_format"] == "html"
        assert resolved["source_format_duplicate_count"] >= 1


def _source_format(row: dict) -> str:
    return str(row.get("source_format") or "html")


def test_resolve_version_dispositions_archives_history():
    rows = [
        {
            "document_number": "2021-05678",
            "publication_date": "2021-03-01",
            "entry_cid": "1" * 64,
            "text": "v1",
            "acquisition_time": "2021-03-01T00:00:00Z",
        },
        {
            "document_number": "2021-05678",
            "publication_date": "2021-03-01",
            "entry_cid": "1" * 64,
            "text": "v1",
            "acquisition_time": "2021-03-01T00:00:00Z",
        },
        {
            "document_number": "2021-05678",
            "publication_date": "2021-03-01",
            "entry_cid": "2" * 64,
            "text": "v2",
            "acquisition_time": "2021-03-01T01:00:00Z",
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


# ---------------------------------------------------------------------------
# Content CID / positional non-merges
# ---------------------------------------------------------------------------


def test_content_cid_alone_cannot_merge():
    left = {
        "document_number": "2022-01000",
        "publication_date": "2022-01-10",
        "entry_cid": "a" * 64,
        "content_cid": "shared" + "0" * 58,
        "text": "boilerplate",
    }
    right = {
        "document_number": "2022-02000",
        "publication_date": "2022-02-10",
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
        "document_number": "2023-01000",
        "publication_date": "2023-01-15",
        "document_index": 42,
        "entry_cid": "1" * 64,
        "text": "alpha",
    }
    right = {
        "document_number": "2023-02000",
        "publication_date": "2023-02-15",
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
        if family.startswith("cid-only-") or family == "seed-cid-only":
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
        {
            "entry_cid": "row-12",
            "document_number": "2020-12345",
            "publication_date": "2020-06-15",
        },
    ]
    with pytest.raises((FederalRegisterIdentityError, PositionalIdentityError)):
        validate_primary_keys(rows)


# ---------------------------------------------------------------------------
# Unknown effective dates preserved
# ---------------------------------------------------------------------------


def test_unknown_effective_dates_are_preserved(collision_rows):
    unknown_rows = [
        row
        for row in collision_rows
        if str(row.get("collision_family") or "").startswith("unk-eff")
        or str(row.get("row_id") or "") == "seed-unknown-eff"
    ]
    assert len(unknown_rows) >= 5
    for row in unknown_rows:
        assert "effective_date" in row
        assert normalize_effective_date(row.get("effective_date")) is None
        assert row.get("normalized_effective_date") is None
        # legal_id still builds from publication identity, not effective date.
        legal_id = legal_id_from_row(row)
        assert row["publication_date"] in legal_id
        assert "unknown" not in legal_id
        assert "tbd" not in legal_id


def test_unknown_effective_date_not_invented_from_publication():
    row = {
        "document_number": "2024-44444",
        "publication_date": "2024-02-29",
        "effective_date": "unknown",
        "text": "body",
        "entry_cid": "a" * 64,
    }
    enriched = enrich_row_identity(row)
    assert enriched["effective_date"] is None
    assert enriched["publication_date"] == "2024-02-29"
    resolved = resolve_version_dispositions([enriched])
    current = resolved["current_rows"][0]
    assert current["effective_date"] is None
    assert (
        current.get("effective_date_status")
        == IdentityDisposition.PRESERVE_UNKNOWN_EFFECTIVE_DATE.value
    )


# ---------------------------------------------------------------------------
# legal_id construction / parsing / provenance helpers
# ---------------------------------------------------------------------------


def test_build_legal_id_simple_and_qualified():
    simple = build_legal_id("2020-12345", "2020-06-15")
    assert simple == "fr:2020-12345:2020-06-15"
    assert SCHEMA_VERSION.startswith("federal-register-identity")
    schema_validate_legal_id(simple)

    correction = build_legal_id(
        "2020-13000",
        "2020-07-01",
        document_type="correction",
        correction_relation="corrects",
        related_document_number="2020-12345",
        include_type_qualifier=True,
        include_correction_qualifier=True,
    )
    assert correction.startswith("fr:2020-13000:2020-07-01:")
    assert "type=correction" in correction
    assert "rel=corrects" in correction
    assert "related=2020-12345" in correction
    schema_validate_legal_id(correction)


def test_parse_legal_id_round_trip():
    legal_id = build_legal_id(
        "2020-13000",
        "2020-07-01",
        document_type="correction",
        correction_relation="corrects",
        related_document_number="2020-12345",
        include_type_qualifier=True,
        include_correction_qualifier=True,
    )
    parsed = parse_legal_id(legal_id)
    assert parsed.document_number == "2020-13000"
    assert parsed.publication_date == "2020-07-01"
    assert parsed.document_type == "correction"
    assert parsed.correction_relation == "corrects"
    assert parsed.related_document_number == "2020-12345"
    assert parsed.legal_id == legal_id


def test_normalize_document_number_variants():
    assert normalize_document_number("2020-12345") == "2020-12345"
    assert normalize_document_number("2020-123") == "2020-0123"
    assert normalize_document_number("FR-2020-12345") == "2020-12345"
    with pytest.raises(IdentityParseError):
        normalize_document_number("not-a-doc")
    with pytest.raises(PositionalIdentityError):
        normalize_document_number("row-12")


def test_normalize_publication_date_variants():
    assert normalize_publication_date("2020-06-15") == "2020-06-15"
    assert normalize_publication_date("20200615") == "2020-06-15"
    with pytest.raises(IdentityParseError):
        normalize_publication_date("06/15/2020")  # ambiguous US form after slash→dash


def test_chunk_parent_and_chunk_id():
    parent = build_chunk_parent_id("2020-12345", "2020-06-15", part="1")
    assert parent == "fr:2020-12345:2020-06-15"
    identity = LegalIdentity(
        document_number="2020-12345",
        publication_date="2020-06-15",
        part="1",
    )
    chunk = identity.chunk_id(3)
    assert chunk.endswith("#chunk=0003")
    restored_parent, index = parse_chunk_id(chunk)
    assert restored_parent == parent
    assert index == 3


def test_compute_entry_and_source_cid_stable():
    source_a = compute_source_cid(
        "2020-12345",
        "2020-06-15",
        source_format="html",
        body="official body",
    )
    source_b = compute_source_cid(
        "2020-12345",
        "2020-06-15",
        source_format="html",
        body="official body",
    )
    assert source_a == source_b
    source_pdf = compute_source_cid(
        "2020-12345",
        "2020-06-15",
        source_format="pdf",
        body="official body",
    )
    # Format participates in source identity when body is present under that format.
    assert source_pdf != source_a

    entry_v1 = compute_entry_cid(
        "2020-12345", "2020-06-15", text="v1", legal_id="fr:2020-12345:2020-06-15"
    )
    entry_v2 = compute_entry_cid(
        "2020-12345", "2020-06-15", text="v2", legal_id="fr:2020-12345:2020-06-15"
    )
    assert entry_v1 != entry_v2
    assert entry_v1.startswith("bafkreie")
    assert source_a.startswith("bafkreis")


def test_enrich_row_identity_fills_missing_fields():
    row = {
        "document_number": "2020-12345",
        "publication_date": "2020-06-15",
        "document_type": "rule",
        "text": "body text",
        "official_source_url": "https://www.federalregister.gov/documents/2020-12345",
    }
    enriched = enrich_row_identity(row)
    assert enriched["legal_id"] == "fr:2020-12345:2020-06-15"
    assert enriched["entry_cid"]
    assert enriched["source_cid"]
    assert enriched["year_month"] == "2020-06"
    assert enriched["canonical_citation"]
    schema_validate_legal_id(enriched["legal_id"])


def test_source_format_priority_orders_html_first():
    assert source_format_priority("html") < source_format_priority("pdf")
    assert source_format_priority("pdf") < source_format_priority("unknown")
    assert normalize_source_format("text/html") == "html"
    assert normalize_source_format("application/pdf") == "pdf"


def test_canonical_citation_includes_known_effective_date():
    cite = build_canonical_citation(
        "2024-44444",
        "2024-02-29",
        document_type="rule",
        effective_date="2024-06-01",
    )
    assert "2024-44444" in cite
    assert "2024-02-29" in cite
    assert "eff. 2024-06-01" in cite
    # Unknown / missing effective dates are omitted (not invented) in the citation.
    bare = build_canonical_citation("2024-44444", "2024-02-29", document_type="rule")
    assert "eff." not in bare
    assert "unknown" not in bare


def test_duplicate_primary_keys_fail_closed():
    rows = [
        {
            "entry_cid": "a" * 64,
            "document_number": "2020-12345",
            "publication_date": "2020-06-15",
        },
        {
            "entry_cid": "a" * 64,
            "document_number": "2020-12346",
            "publication_date": "2020-06-16",
        },
    ]
    with pytest.raises(DuplicatePrimaryKeyError):
        validate_primary_keys(rows)


def test_assert_legal_ids_distinguishable_allows_version_collisions():
    rows = [
        {
            "document_number": "2021-05678",
            "publication_date": "2021-03-01",
            "text": "old",
            "entry_cid": "1" * 64,
        },
        {
            "document_number": "2021-05678",
            "publication_date": "2021-03-01",
            "text": "new",
            "entry_cid": "2" * 64,
        },
    ]
    with pytest.raises(FederalRegisterIdentityError):
        assert_legal_ids_distinguishable(rows, allow_version_collisions=False)
    ids = assert_legal_ids_distinguishable(rows, allow_version_collisions=True)
    assert len(ids) == 2
    assert ids[0] == ids[1]


def test_malformed_fixture_schema_rejected():
    with pytest.raises(CollisionFixtureError):
        expand_collision_fixture(
            {
                "schema_version": "wrong",
                "expected_row_count": KNOWN_COLLISION_ROW_COUNT,
                "generators": [],
                "seed_rows": [],
            }
        )


def test_identity_from_row_and_legal_id_from_row(collision_rows):
    row = collision_rows[0]
    identity = identity_from_row(row)
    assert identity.legal_id == row["legal_id"]
    assert legal_id_from_row(row) == row["legal_id"]
    assert identity.document_number == row["document_number"]
