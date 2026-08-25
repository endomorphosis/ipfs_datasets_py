"""Unit tests for canonical Federal Register identity and provenance (LCR-054).

Acceptance:

* Identity is stable across ordering and resume.
* Distinct legal versions (corrections, withdrawals, republications) do not
  collapse.
* Exact duplicates and duplicate source formats reconcile deterministically.
"""

from __future__ import annotations

import hashlib
import itertools
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
    SCHEMA_VERSION as RELEASE_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    CorpusRecord,
    example_corpus_payload,
    example_correction_corpus_payload,
    validate_digest,
    validate_entry_cid,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    DocumentIdentityError as ReleaseDocumentIdentityError,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    validate_document_number as release_validate_document_number,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    validate_legal_id as schema_validate_legal_id,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    DocumentIdentityError as SourceDocumentIdentityError,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    parse_legal_id as source_parse_legal_id,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    validate_document_number as source_validate_document_number,
)

# tests/unit/processors/legal_data/this_file.py → tests/
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "federal_register_identity_collisions.json"
)


def _official_url(document_number: str, publication_date: str) -> str:
    return (
        "https://www.federalregister.gov/documents/"
        f"{publication_date[0:4]}/{publication_date[5:7]}/"
        f"{publication_date[8:10]}/{document_number}"
    )


def _raw_row(
    document_number: str,
    publication_date: str,
    text: str,
    *,
    source_format: str = "html",
    **extra,
) -> dict:
    return {
        "document_number": document_number,
        "publication_date": publication_date,
        "document_type": "notice",
        "source_format": source_format,
        "official_source_url": _official_url(document_number, publication_date),
        "text": text,
        **extra,
    }


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
    assert built == on_disk
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
        assert validate_entry_cid(row["entry_cid"]) == row["entry_cid"]
        assert (
            validate_digest(row["source_cid"], name="source_cid") == row["source_cid"]
        )
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
        (r["legal_id"], r.get("entry_cid"), r.get("text"))
        for r in forward["current_rows"]
    )
    backward_keys = sorted(
        (r["legal_id"], r.get("entry_cid"), r.get("text"))
        for r in backward["current_rows"]
    )
    assert forward_keys == backward_keys
    assert forward["current_count"] == backward["current_count"]
    assert forward["duplicate_count"] == backward["duplicate_count"]
    assert forward["changed_text_count"] == backward["changed_text_count"]


def test_merge_by_legal_identity_resume_stable():
    existing = [
        _raw_row(
            "2021-22222",
            "2021-08-08",
            "version-one body",
            document_type="notice",
            acquisition_time="2021-08-08T01:00:00Z",
        )
    ]
    new_rows = [
        _raw_row(
            "2021-22222",
            "2021-08-08",
            "version-two body",
            document_type="notice",
            acquisition_time="2021-08-08T02:00:00Z",
        )
    ]
    merged_ab = merge_by_legal_identity(existing, new_rows)
    merged_ba = merge_by_legal_identity(new_rows, existing)
    assert merged_ab["current_count"] == 1
    assert merged_ba["current_count"] == 1
    assert merged_ab == merged_ba
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
    for members in families.values():
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
    left = _raw_row("2020-12345", "2020-06-15", "same")
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
        _raw_row(
            "2021-05678",
            "2021-03-01",
            "v1",
            acquisition_time="2021-03-01T00:00:00Z",
        ),
        _raw_row(
            "2021-05678",
            "2021-03-01",
            "v1",
            acquisition_time="2021-03-01T00:00:00Z",
        ),
        _raw_row(
            "2021-05678",
            "2021-03-01",
            "v2",
            acquisition_time="2021-03-01T01:00:00Z",
        ),
    ]
    resolved = resolve_version_dispositions(rows)
    assert resolved["current_count"] == 1
    assert resolved["duplicate_count"] == 0
    assert resolved["changed_text_count"] == 1
    assert len(resolved["all_rows"]) == 2
    assert len(resolved["history_keys"]) == 1
    current = resolved["current_rows"][0]
    assert current["identity_disposition"] == IdentityDisposition.KEEP_CURRENT.value
    history = resolved["history_by_key"][current["legal_id"]]
    assert {current["text"], *(h["text"] for h in history)} == {"v1", "v2"}


# ---------------------------------------------------------------------------
# Content CID / positional non-merges
# ---------------------------------------------------------------------------


def test_content_cid_alone_cannot_merge():
    left = _raw_row("2022-01000", "2022-01-10", "boilerplate")
    right = _raw_row("2022-02000", "2022-02-10", "boilerplate")
    result = classify_identity_pair(left, right)
    assert (
        result["disposition"] == IdentityDisposition.REJECT_CONTENT_CID_ONLY_MERGE.value
    )
    assert result["merge_allowed"] is False
    assert result["same_legal_id"] is False

    resolved = resolve_version_dispositions([left, right])
    assert resolved["current_count"] == 2
    assert any(
        e["disposition"] == IdentityDisposition.REJECT_CONTENT_CID_ONLY_MERGE.value
        for e in resolved["reject_events"]
    )


def test_row_position_alone_cannot_merge():
    left = _raw_row("2023-01000", "2023-01-15", "alpha", document_index=42)
    right = _raw_row("2023-02000", "2023-02-15", "beta", document_index=42)
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


def test_unknown_effective_dates_canonicalize_to_absence(collision_rows):
    unknown_rows = [
        row
        for row in collision_rows
        if str(row.get("collision_family") or "").startswith("unk-eff")
        or str(row.get("row_id") or "") == "seed-unknown-eff"
    ]
    assert len(unknown_rows) >= 5
    for row in unknown_rows:
        assert "effective_date" not in row
        # legal_id still builds from publication identity, not effective date.
        legal_id = legal_id_from_row(row)
        assert row["publication_date"] in legal_id
        assert "unknown" not in legal_id
        assert "tbd" not in legal_id


def test_unknown_effective_date_not_invented_from_publication():
    row = _raw_row(
        "2024-44444",
        "2024-02-29",
        "body",
        effective_date="unknown",
    )
    enriched = enrich_row_identity(row)
    assert "effective_date" not in enriched
    assert enriched["publication_date"] == "2024-02-29"
    resolved = resolve_version_dispositions([enriched])
    current = resolved["current_rows"][0]
    assert "effective_date" not in current


# ---------------------------------------------------------------------------
# legal_id construction / parsing / provenance helpers
# ---------------------------------------------------------------------------


def test_build_legal_id_simple_and_qualified():
    simple = build_legal_id("2020-12345", "2020-06-15", document_type="notice")
    assert simple == "fr:2020-12345:2020-06-15:type=notice"
    assert SCHEMA_VERSION.startswith("federal-register-identity")
    schema_validate_legal_id(simple)

    correction = build_legal_id(
        "2020-13000",
        "2020-07-01",
        document_type="correction",
        correction_relation="corrects",
        related_document_number="2020-12345",
    )
    assert correction.startswith("fr:2020-13000:2020-07-01:")
    assert "type=correction" in correction
    assert "rel=corrects" in correction
    assert "related=2020-12345" in correction
    schema_validate_legal_id(correction)


def test_document_type_is_mandatory_identity_without_caller_toggle():
    rule = LegalIdentity(
        document_number="2020-12345",
        publication_date="2020-06-15",
        document_type="rule",
        effective_date="2020-07-01",
    )
    same_rule = LegalIdentity(
        document_number="2020-12345",
        publication_date="2020-06-15",
        document_type="rule",
        effective_date="2020-08-01",
    )
    proposed = LegalIdentity(
        document_number="2020-12345",
        publication_date="2020-06-15",
        document_type="proposed_rule",
    )
    assert rule.legal_id == "fr:2020-12345:2020-06-15:type=rule"
    assert proposed.legal_id == "fr:2020-12345:2020-06-15:type=proposed_rule"
    assert rule == same_rule
    assert hash(rule) == hash(same_rule)
    assert rule != proposed
    assert rule.legal_id != proposed.legal_id

    with pytest.raises(TypeError):
        build_legal_id("2020-12345", "2020-06-15")
    with pytest.raises(IdentityParseError):
        build_legal_id("2020-12345", "2020-06-15", document_type=None)
    with pytest.raises(IdentityParseError):
        build_chunk_parent_id(
            "2020-12345",
            "2020-06-15",
            document_type="rule",
            include_type_qualifier=False,
        )
    with pytest.raises(IdentityParseError):
        identity_from_row(
            {
                "document_number": "2020-12345",
                "publication_date": "2020-06-15",
            }
        )
    with pytest.raises(IdentityParseError):
        identity_from_row(
            {
                "document_number": "2020-12345",
                "publication_date": "2020-06-15",
                "document_type": "rule",
                "include_type_qualifier": False,
            }
        )


def test_parse_legal_id_round_trip():
    legal_id = build_legal_id(
        "2020-13000",
        "2020-07-01",
        document_type="correction",
        correction_relation="corrects",
        related_document_number="2020-12345",
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
    for noncanonical in ("2020-123", "FR-2020-12345", " 2020-12345"):
        with pytest.raises(IdentityParseError):
            normalize_document_number(noncanonical)
    with pytest.raises(PositionalIdentityError):
        normalize_document_number("row-12")


def test_normalize_publication_date_variants():
    assert normalize_publication_date("2020-06-15") == "2020-06-15"
    assert normalize_publication_date("20200615") == "2020-06-15"
    with pytest.raises(IdentityParseError):
        normalize_publication_date("06/15/2020")  # ambiguous US form after slash→dash


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("C1-2026-02383", "C1-2026-02383"),
        ("C2-2026-02383", "C2-2026-02383"),
        ("R1-2026-05038", "R1-2026-05038"),
    ],
)
def test_official_correction_and_replacement_number_prefixes_are_identity(
    raw, canonical
):
    assert normalize_document_number(raw) == canonical
    legal_id = build_legal_id(canonical, "2026-03-12", document_type="notice")
    assert legal_id == f"fr:{canonical}:2026-03-12:type=notice"
    assert parse_legal_id(legal_id).document_number == canonical

    prefixed = enrich_row_identity(
        _raw_row(canonical, "2026-03-12", f"body for {canonical}")
    )
    base = enrich_row_identity(
        _raw_row(canonical.split("-", 1)[1], "2026-03-12", f"body for {canonical}")
    )
    assert prefixed["legal_id"] != base["legal_id"]
    assert prefixed["document_number"] == canonical
    assert prefixed["source_cid"] != base["source_cid"]
    assert prefixed["entry_cid"] != base["entry_cid"]
    assert validate_entry_cid(prefixed["entry_cid"]) == prefixed["entry_cid"]
    comparison = classify_identity_pair(prefixed, base)
    assert comparison["same_legal_id"] is False
    assert comparison["merge_allowed"] is False


@pytest.mark.parametrize(
    "document_number",
    ["c1-2026-02383", "X1-2026-02383", "C-2026-02383"],
)
def test_malformed_official_number_prefixes_rejected(document_number):
    with pytest.raises(IdentityParseError):
        normalize_document_number(document_number)


@pytest.mark.parametrize(
    "document_number",
    (
        "2024-19189",
        "93-32034",
        "94-184",
        "00-1",
        "00-10",
        "E9-5927",
        "E9-9",
        "C1-12345",
        "C0-1",
        "C6-102",
        "C1-2010-31877",
        "C3-2014-04105",
        "R1-2017-02032",
        "R2-2023-00490",
        "20-12345",
        "X0-12345",
        "Z9-9",
    ),
)
def test_lcr050_document_number_positive_matrix(document_number):
    assert normalize_document_number(document_number) == document_number
    legal_id = build_legal_id(document_number, "2026-03-15", document_type="notice")
    assert parse_legal_id(legal_id).document_number == document_number


@pytest.mark.parametrize(
    "document_number",
    (
        "CDC-2024-0015",
        "A0-1",
        "10-1",
        "21-12345",
        "91-12345",
        "E2-1",
        "X2-1",
        "Z3-1",
        "C1-C1-12345",
        "c1-2010-31877",
        "2024-1",
        "2024-123",
        "C1-2024-123",
        "R2-2023-490",
        "E9-1234567",
        "2024-1234567",
        "1935-12345",
        "2101-12345",
    ),
)
def test_lcr050_document_number_negative_matrix(document_number):
    with pytest.raises(IdentityParseError):
        normalize_document_number(document_number)


def test_document_number_matrix_converges_across_lcr049_lcr050_lcr054():
    positives = (
        "00-1",
        "94-184",
        "E9-9",
        "Z9-12345",
        "2024-19189",
        "C0-1",
        "C1-2010-31877",
        "R2-2023-00490",
    )
    negatives = (
        "A0-1",
        "E2-1",
        "c1-2010-31877",
        "2024-123",
        "C1-2024-123",
        "1935-12345",
        "2101-12345",
    )
    for document_number in positives:
        assert source_validate_document_number(document_number) == document_number
        assert release_validate_document_number(document_number) == document_number
        assert normalize_document_number(document_number) == document_number
    for document_number in negatives:
        for validator, error_type in (
            (source_validate_document_number, SourceDocumentIdentityError),
            (release_validate_document_number, ReleaseDocumentIdentityError),
            (normalize_document_number, IdentityParseError),
        ):
            with pytest.raises(error_type):
                validator(document_number)


def test_identity_whitespace_policy_converges_across_contracts():
    for document_number in (" 2024-19189", "2024-19189 "):
        for validator, error_type in (
            (source_validate_document_number, SourceDocumentIdentityError),
            (release_validate_document_number, ReleaseDocumentIdentityError),
            (normalize_document_number, IdentityParseError),
        ):
            with pytest.raises(error_type):
                validator(document_number)
    for legal_id in (
        " fr:2024-19189:2026-03-15",
        "fr:2024-19189:2026-03-15 ",
    ):
        with pytest.raises(SourceDocumentIdentityError):
            source_parse_legal_id(legal_id)
        with pytest.raises(ReleaseDocumentIdentityError):
            schema_validate_legal_id(legal_id)
        with pytest.raises(IdentityParseError):
            legal_id_from_row(
                {
                    "document_number": "2024-19189",
                    "publication_date": "2026-03-15",
                    "document_type": "notice",
                    "legal_id": legal_id,
                }
            )


def test_related_revision_qualifier_preserves_uppercase_document_bytes():
    legal_id = build_legal_id(
        "C1-2010-31877",
        "2010-12-29",
        document_type="notice",
        correction_relation="corrects",
        related_document_number="R2-2023-00490",
    )
    assert "related=R2-2023-00490" in legal_id
    assert parse_legal_id(legal_id).legal_id == legal_id
    with pytest.raises(IdentityParseError):
        parse_legal_id(legal_id.replace("related=R2", "related=r2"))


def test_chunk_parent_and_chunk_id():
    parent = build_chunk_parent_id(
        "2020-12345", "2020-06-15", document_type="notice", part="1"
    )
    assert parent == "fr:2020-12345:2020-06-15:type=notice"
    identity = LegalIdentity(
        document_number="2020-12345",
        publication_date="2020-06-15",
        document_type="notice",
        part="1",
    )
    chunk = identity.chunk_id(3)
    assert chunk.endswith("#chunk=0003")
    restored_parent, index = parse_chunk_id(chunk)
    assert restored_parent == parent
    assert index == 3


def test_compute_entry_and_source_cid_stable():
    url = _official_url("2020-12345", "2020-06-15")
    source_a = compute_source_cid(
        "2020-12345",
        "2020-06-15",
        source_format="html",
        official_source_url=url,
        body="official body",
    )
    source_b = compute_source_cid(
        "2020-12345",
        "2020-06-15",
        source_format="html",
        official_source_url=url,
        body="official body",
    )
    assert source_a == source_b
    source_pdf = compute_source_cid(
        "2020-12345",
        "2020-06-15",
        source_format="pdf",
        official_source_url=url,
        body="official body",
    )
    # Format participates in source identity when body is present under that format.
    assert source_pdf != source_a

    entry_v1 = compute_entry_cid(_raw_row("2020-12345", "2020-06-15", "v1"))
    entry_v2 = compute_entry_cid(_raw_row("2020-12345", "2020-06-15", "v2"))
    assert entry_v1 != entry_v2
    assert entry_v1.startswith("bafkrei")
    assert source_a.startswith("bafkrei")
    assert validate_entry_cid(entry_v1) == entry_v1
    assert validate_digest(source_a, name="source_cid") == source_a


def test_enrich_row_identity_fills_missing_fields():
    row = {
        "document_number": "2020-12345",
        "publication_date": "2020-06-15",
        "document_type": "rule",
        "source_format": "html",
        "text": "body text",
        "official_source_url": "https://www.federalregister.gov/documents/2020-12345",
    }
    enriched = enrich_row_identity(row)
    assert enriched["legal_id"] == "fr:2020-12345:2020-06-15:type=rule"
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
        enrich_row_identity(_raw_row("2021-05678", "2021-03-01", "old")),
        enrich_row_identity(_raw_row("2021-05678", "2021-03-01", "new")),
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


# ---------------------------------------------------------------------------
# Fail-closed regression matrix for the LCR-054 audit
# ---------------------------------------------------------------------------


def test_source_cid_requires_official_observed_bytes_and_matching_checksum():
    url = _official_url("2020-12345", "2020-06-15")
    digest = hashlib.sha256(b"body-a").hexdigest()
    cid = compute_source_cid(
        "2020-12345",
        "2020-06-15",
        source_format="html",
        official_source_url=url,
        source_checksum=digest,
        source_bytes=b"body-a",
    )
    assert validate_digest(cid, name="source_cid") == cid
    assert cid != compute_source_cid(
        "2020-12345",
        "2020-06-15",
        source_format="html",
        official_source_url=url,
        source_bytes=b"body-b",
    )
    with pytest.raises(FederalRegisterIdentityError):
        compute_source_cid(
            "2020-12345",
            "2020-06-15",
            source_format="html",
            official_source_url=url,
            source_checksum=digest,
            source_bytes=b"body-b",
        )
    with pytest.raises(FederalRegisterIdentityError):
        compute_source_cid(
            "2020-12345",
            "2020-06-15",
            source_format="html",
            official_source_url=url,
            source_checksum=digest,
        )
    with pytest.raises(ValueError):
        compute_source_cid(
            "2020-12345",
            "2020-06-15",
            source_format="html",
            official_source_url="https://example.invalid/not-official",
            source_bytes=b"body-a",
        )
    with pytest.raises(FederalRegisterIdentityError):
        compute_source_cid(
            "2020-12345",
            "2020-06-15",
            official_source_url=url,
            source_bytes=b"body-a",
        )
    with pytest.raises(FederalRegisterIdentityError):
        compute_source_cid(
            "2020-12345",
            "2020-06-15",
            source_format="text/html",
            official_source_url=url,
            source_bytes=b"body-a",
        )
    with pytest.raises(FederalRegisterIdentityError):
        compute_source_cid(
            "2020-12345",
            "2020-06-15",
            source_format="html",
            official_source_url=url,
            source_bytes=b"body-a",
            body=b"body-b",
        )


def test_entry_cid_recomputes_content_and_source_claims():
    url = _official_url("2020-12345", "2020-06-15")
    source = compute_source_cid(
        "2020-12345",
        "2020-06-15",
        source_format="html",
        official_source_url=url,
        source_bytes=b"source-a",
    )
    base = _raw_row(
        "2020-12345",
        "2020-06-15",
        "body-a",
        source_cid=source,
        source_bytes=b"source-a",
    )
    with pytest.raises(FederalRegisterIdentityError):
        compute_entry_cid({**base, "content_cid": "0" * 64})
    with pytest.raises(FederalRegisterIdentityError):
        compute_entry_cid({**base, "source_bytes": b"source-b"})
    with pytest.raises(FederalRegisterIdentityError):
        compute_entry_cid({**base, "content_bytes": b"body-b"})
    with pytest.raises(FederalRegisterIdentityError):
        compute_entry_cid({**base, "record_fields": {"title": "attacker"}})
    with pytest.raises(TypeError):
        compute_entry_cid(base, record_fields={"title": "attacker"})


def test_declared_content_cid_cannot_hide_changed_text():
    left = _raw_row("2020-12345", "2020-06-15", "body-a", content_cid="0" * 64)
    with pytest.raises(FederalRegisterIdentityError):
        content_identity_from_row(left)
    with pytest.raises(FederalRegisterIdentityError):
        classify_identity_pair(left, {**left, "text": "body-b"})


@pytest.mark.parametrize(
    "legal_id",
    [
        "fr:2020-12345:2020-06-15:vendor=alpha:type=notice",
        "fr:2020-12345:2020-06-15:granule=a:granule=b:type=notice",
        "fr:2020-12345:2020-06-15:free-form:type=notice",
    ],
)
def test_unknown_duplicate_and_free_form_qualifiers_rejected(legal_id):
    with pytest.raises(IdentityParseError):
        parse_legal_id(legal_id)
    with pytest.raises((IdentityParseError, ValueError)):
        legal_id_from_row({"legal_id": legal_id})
    with pytest.raises(IdentityParseError):
        build_legal_id(
            "2020-12345",
            "2020-06-15",
            document_type="notice",
            qualifier="free-form",
        )
    with pytest.raises(IdentityParseError):
        build_legal_id(
            "2020-12345", "2020-06-15", document_type="notice", edition="a/b"
        )
    with pytest.raises(IdentityParseError):
        build_legal_id("2020-12345", "2020-06-15", document_type="notice", edition=" a")


@pytest.mark.parametrize(
    "legal_id",
    [
        "FR:2020-12345:2020-06-15",
        "fr:2020-12345:2020-06-15 ",
        "fr:2020-12345:2020-06-15:TYPE=rule",
        "attacker-selected-id",
    ],
)
def test_explicit_legal_id_requires_exact_canonical_grammar(legal_id):
    row = _raw_row("2020-12345", "2020-06-15", "body", legal_id=legal_id)
    with pytest.raises(IdentityParseError):
        legal_id_from_row(row)
    with pytest.raises(IdentityParseError):
        enrich_row_identity(row)


def test_lcr050_bare_legal_id_is_an_input_assertion_then_canonicalized():
    row = _raw_row(
        "2020-12345",
        "2020-06-15",
        "body",
        document_type="rule",
        legal_id="fr:2020-12345:2020-06-15",
    )
    canonical = enrich_row_identity(row)
    assert canonical["legal_id"] == ("fr:2020-12345:2020-06-15:type=rule")
    with pytest.raises(IdentityParseError):
        parse_legal_id(row["legal_id"])


def test_lcr050_legacy_relation_legal_id_is_closed_and_canonicalized():
    row = _raw_row(
        "2026-05001",
        "2026-04-01",
        "correction body",
        document_type="correction",
        correction_relation="corrects",
        related_document_number="2026-04567",
        legal_id="fr:2026-05001:2026-04-01:corrects:2026-04567",
    )
    canonical = enrich_row_identity(row)
    assert canonical["legal_id"] == (
        "fr:2026-05001:2026-04-01:related=2026-04567:rel=corrects:type=correction"
    )
    for attacker_legal_id in (
        "fr:2026-05001:2026-04-01:correction:2026-04567",
        "fr:2026-05001:2026-04-01:corrects",
        "fr:2026-05001:2026-04-01:corrects:2026-04567:extra",
    ):
        with pytest.raises(IdentityParseError):
            enrich_row_identity({**row, "legal_id": attacker_legal_id})
    with pytest.raises(IdentityParseError):
        enrich_row_identity({**row, "correction_relation": "withdraws"})


def test_correction_and_withdrawal_identity_is_mandatory_not_caller_optional():
    withdrawn = build_legal_id(
        "2020-12345",
        "2020-06-15",
        document_type="notice",
        correction_relation="withdraws",
        related_document_number="2020-11111",
    )
    corrected = build_legal_id(
        "2020-12345",
        "2020-06-15",
        document_type="notice",
        correction_relation="corrects",
        related_document_number="2020-22222",
    )
    assert "rel=withdraws" in withdrawn and "related=2020-11111" in withdrawn
    assert "rel=corrects" in corrected and "related=2020-22222" in corrected
    assert withdrawn != corrected
    left = _raw_row(
        "2020-12345",
        "2020-06-15",
        "same body",
        correction_relation="withdraws",
        related_document_number="2020-11111",
    )
    right = _raw_row(
        "2020-12345",
        "2020-06-15",
        "same body",
        correction_relation="corrects",
        related_document_number="2020-22222",
    )
    result = classify_identity_pair(left, right)
    assert result["same_legal_id"] is False
    assert result["merge_allowed"] is False
    for incomplete in (
        "fr:2020-12345:2020-06-15:rel=withdraws:type=notice",
        "fr:2020-12345:2020-06-15:related=2020-11111:type=notice",
        "fr:2020-12345:2020-06-15:type=correction",
    ):
        with pytest.raises(IdentityParseError):
            parse_legal_id(incomplete)


def test_explicit_legal_id_must_exactly_match_row_identity():
    row = _raw_row("2021-54321", "2021-01-02", "body")
    row["legal_id"] = "fr:2020-12345:2020-06-15:type=notice"
    with pytest.raises(IdentityParseError):
        enrich_row_identity(row)

    related = _raw_row(
        "2020-12345",
        "2020-06-15",
        "body",
        correction_relation="withdraws",
        related_document_number="2020-11111",
    )
    related["legal_id"] = "fr:2020-12345:2020-06-15:type=notice"
    with pytest.raises(IdentityParseError):
        enrich_row_identity(related)


def test_enrichment_rejects_missing_or_coerced_provenance_and_cid_overrides():
    with pytest.raises(FederalRegisterIdentityError):
        enrich_row_identity(
            {
                "document_number": "2020-12345",
                "publication_date": "2020-06-15",
                "document_type": "notice",
                "text": "body",
                "official_source_url": _official_url("2020-12345", "2020-06-15"),
            }
        )
    for source_format in ("text/html", "HTML", " html"):
        with pytest.raises(FederalRegisterIdentityError):
            enrich_row_identity(
                _raw_row(
                    "2020-12345",
                    "2020-06-15",
                    "body",
                    source_format=source_format,
                )
            )
    canonical = enrich_row_identity(_raw_row("2020-12345", "2020-06-15", "body"))
    with pytest.raises(FederalRegisterIdentityError):
        enrich_row_identity({**canonical, "source_cid": "a" * 64})
    with pytest.raises(FederalRegisterIdentityError):
        enrich_row_identity({**canonical, "entry_cid": "b" * 64})
    with pytest.raises(FederalRegisterIdentityError):
        enrich_row_identity({**canonical, "text": "mutated body"})


def test_unretainable_corpus_evidence_and_identity_states_fail_closed():
    base = _raw_row("2020-12345", "2020-06-15", "body")
    with pytest.raises(FederalRegisterIdentityError):
        enrich_row_identity({**base, "source_bytes": b"different source artifact"})
    with pytest.raises(FederalRegisterIdentityError):
        enrich_row_identity({**base, "effective_date": "2020-07-01"})
    for field_name in ("edition", "granule", "part"):
        with pytest.raises(FederalRegisterIdentityError):
            enrich_row_identity({**base, field_name: "1"})
    assert "effective_date" not in enrich_row_identity(
        {**base, "effective_date": "unknown"}
    )


def test_lcr050_defaults_are_canonicalized_before_entry_cid():
    base = _raw_row("2020-12345", "2020-06-15", "body")
    omitted = enrich_row_identity(base)
    explicit = enrich_row_identity({**base, "source_authority_class": "official"})
    assert omitted == explicit
    assert omitted["source_authority_class"] == "official"


def test_bool_document_index_is_rejected_before_entry_cid():
    base = _raw_row("2020-12345", "2020-06-15", "body")
    for value in (True, False):
        with pytest.raises(FederalRegisterIdentityError):
            enrich_row_identity({**base, "document_index": value})


def test_abstract_bound_matches_lcr050_corpus_record():
    base = _raw_row("2020-12345", "2020-06-15", "body")
    accepted = enrich_row_identity({**base, "abstract": "a" * 4096})
    assert len(accepted["abstract"]) == 4096
    with pytest.raises(FederalRegisterIdentityError):
        enrich_row_identity({**base, "abstract": "a" * 4097})


def test_empty_optional_urls_canonicalize_to_absence_before_entry_cid():
    base = _raw_row("2020-12345", "2020-06-15", "body")
    absent = enrich_row_identity(base)
    empty = enrich_row_identity(
        {
            **base,
            "official_html_url": "",
            "official_pdf_url": "",
            "official_xml_url": "",
        }
    )
    assert empty == absent
    assert "official_html_url" not in empty
    assert "official_pdf_url" not in empty
    assert "official_xml_url" not in empty


def test_unknown_extensions_rejected_and_every_emitted_field_is_cid_bound():
    base = enrich_row_identity(_raw_row("2020-12345", "2020-06-15", "body"))
    with pytest.raises(FederalRegisterIdentityError):
        enrich_row_identity({**base, "attacker_extension": "unbound"})
    for field_name, changed in (
        ("title", "changed title"),
        ("observed_at", "changed observation"),
        ("parent_path", "changed/path"),
        ("canonical_citation", "attacker citation"),
    ):
        mutated = {**base, field_name: changed}
        with pytest.raises(FederalRegisterIdentityError):
            enrich_row_identity(mutated)


def test_source_format_is_exact_or_recovered_from_bound_evidence():
    recoverable = {
        "document_number": "2020-12345",
        "publication_date": "2020-06-15",
        "document_type": "notice",
        "text": "body",
        "text_availability": "html_body",
        "official_source_url": _official_url("2020-12345", "2020-06-15"),
    }
    assert enrich_row_identity(recoverable)["source_format"] == "html"
    assert (
        enrich_row_identity(
            {**recoverable, "source_format": "html", "text_availability": "full_text"}
        )["text_availability"]
        == "html_body"
    )
    projected = enrich_row_identity({**recoverable, "text_availability": "full_text"})
    assert projected["source_format"] == "html"
    assert projected["text_availability"] == "html_body"
    with pytest.raises(FederalRegisterIdentityError):
        enrich_row_identity(
            {
                **recoverable,
                "source_format": "pdf",
                "text_availability": "html_body",
            }
        )
    with pytest.raises(FederalRegisterIdentityError):
        enrich_row_identity({**recoverable, "schema_version": SCHEMA_VERSION})


def test_accepted_alias_hash_and_sequence_representations_canonicalize_exactly():
    text = "Canonical official body"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    canonical_input = _raw_row(
        "2020-12345",
        "2020-06-15",
        text,
        document_type="rule",
        agencies=["Agency A", "Agency B"],
        admission_status="admitted",
        source_authority_class="official",
        text_availability="html_body",
        verification_result="verified",
        content_sha256=digest,
        official_content_hash=digest,
        source_checksum=digest,
    )
    canonical = enrich_row_identity(canonical_input)
    aliased_input = {
        "documentNumber": "2020-12345",
        "publicationDate": "2020-06-15",
        "type": "rules",
        "format": "html",
        "official_source_url": _official_url("2020-12345", "2020-06-15"),
        "content_bytes": text.encode("utf-8"),
        "artifact_bytes": text,
        "agencies": ("Agency A", "Agency B"),
        "admission_status": "include",
        "source_authority_class": "federal_register",
        "text_availability": "html",
        "verification_result": "VERIFIED",
        "content_cid": canonical["content_cid"].upper(),
        "content_sha256": digest.upper(),
        "official_content_hash": digest.upper(),
        "source_checksum": digest.upper(),
        "source_cid": canonical["source_cid"].upper(),
        "entry_cid": canonical["entry_cid"].upper(),
    }
    assert enrich_row_identity(aliased_input) == canonical
    forward = resolve_version_dispositions([canonical_input, aliased_input])
    reverse = resolve_version_dispositions([aliased_input, canonical_input])
    assert forward == reverse


def test_primary_key_validator_has_no_caller_selected_or_case_bypass():
    with pytest.raises(FederalRegisterIdentityError):
        validate_primary_keys([{"entry_cid": "not-a-digest"}])
    with pytest.raises(FederalRegisterIdentityError):
        validate_primary_keys(
            [
                {"entry_cid": "a" * 64, "alternate": "one"},
                {"entry_cid": "a" * 64, "alternate": "two"},
            ],
            key_field="alternate",
        )
    with pytest.raises(DuplicatePrimaryKeyError):
        validate_primary_keys([{"entry_cid": "A" * 64}, {"entry_cid": "a" * 64}])
    canonical = enrich_row_identity(
        _raw_row("2020-12345", "2020-06-15", "canonical body")
    )
    with pytest.raises(FederalRegisterIdentityError):
        validate_primary_keys([{**canonical, "entry_cid": canonical["source_cid"]}])


def test_document_type_variants_are_distinguishable_without_collision_override():
    rows = [
        _raw_row(
            "2020-12345",
            "2020-06-15",
            "body-a",
            document_type="rule",
        ),
        _raw_row(
            "2020-12345",
            "2020-06-15",
            "body-b",
            document_type="proposed_rule",
        ),
    ]
    ids = assert_legal_ids_distinguishable(rows, allow_version_collisions=False)
    assert len(set(ids)) == 2
    assert any("type=rule" in legal_id for legal_id in ids)
    assert any("type=proposed_rule" in legal_id for legal_id in ids)


def test_calendar_and_partition_identity_fail_closed():
    with pytest.raises(IdentityParseError):
        normalize_publication_date("2024-02-31")
    with pytest.raises(IdentityParseError):
        LegalIdentity(
            document_number="2024-12345",
            publication_date="2024-02-29",
            document_type="notice",
            year_month="2024-03",
        )


def test_full_resolution_is_permutation_stable_with_tied_provenance():
    rows = [
        _raw_row(
            "2020-12345",
            "2020-06-15",
            "same body",
            title="Title B",
            acquisition_time="zzzz-untrusted",
        ),
        _raw_row(
            "2020-12345",
            "2020-06-15",
            "same body",
            title="Title A",
            acquisition_time="0000-untrusted",
        ),
    ]
    assert resolve_version_dispositions(rows) == resolve_version_dispositions(
        list(reversed(rows))
    )


def test_resume_from_full_resolution_preserves_every_version_exactly():
    rows = [
        _raw_row("2020-12345", "2020-06-15", f"version-{index}") for index in range(3)
    ]
    one_shot = resolve_version_dispositions(rows)
    checkpoint = resolve_version_dispositions(rows[:2])
    resumed = merge_by_legal_identity(checkpoint, rows[2:])
    assert resumed == one_shot
    key = one_shot["current_keys"][0]
    retained = [one_shot["current_rows"][0], *one_shot["history_by_key"][key]]
    assert {row["text"] for row in retained} == {
        "version-0",
        "version-1",
        "version-2",
    }
    assert all(row["source_cid"] for row in retained)


def test_replaying_last_batch_is_exactly_idempotent():
    initial = [_raw_row("2020-12345", "2020-06-15", "version-0")]
    last_batch = [
        _raw_row("2020-12345", "2020-06-15", "version-1"),
        _raw_row("2020-12345", "2020-06-15", "version-1", source_format="pdf"),
    ]
    once = merge_by_legal_identity(initial, last_batch)
    replayed = merge_by_legal_identity(once, last_batch)
    assert replayed == once
    assert replayed["all_rows"] == once["all_rows"]
    assert replayed["duplicate_count"] == once["duplicate_count"]


def test_exact_repeats_are_one_canonical_observation_in_every_merge_shape():
    row = _raw_row("2020-12345", "2020-06-15", "same version")
    expected = resolve_version_dispositions([row])
    for observations in ([row, row], [row, row, row]):
        assert resolve_version_dispositions(observations) == expected
        assert merge_by_legal_identity(observations[:1], observations[1:]) == expected
        checkpoint = resolve_version_dispositions(observations[:1])
        assert merge_by_legal_identity(checkpoint, observations[1:]) == expected
    assert len(expected["all_rows"]) == 1
    assert expected["duplicate_count"] == 0


def test_five_observations_are_stable_across_every_permutation_and_split():
    version_one = _raw_row("2020-12345", "2020-06-15", "version one")
    version_two = _raw_row("2020-12345", "2020-06-15", "version two")
    version_two_pdf = _raw_row(
        "2020-12345",
        "2020-06-15",
        "version two",
        source_format="pdf",
    )
    observations = [
        version_one,
        version_one,
        version_two,
        version_two,
        version_two_pdf,
    ]
    expected = resolve_version_dispositions(observations)
    assert len(expected["all_rows"]) == 3
    assert expected["changed_text_count"] == 1
    assert expected["duplicate_count"] == 1
    assert expected["source_format_duplicate_count"] == 1
    key = expected["current_keys"][0]
    retained_versions = [
        expected["current_rows"][0],
        *expected["history_by_key"][key],
    ]
    assert {row["text"] for row in retained_versions} == {
        "version one",
        "version two",
    }
    assert {
        row["source_format"] for row in expected["source_variants_by_key"][key]
    } == {"pdf"}

    for ordering in itertools.permutations(observations):
        assert resolve_version_dispositions(ordering) == expected
        for split in range(len(observations) + 1):
            checkpoint = resolve_version_dispositions(ordering[:split])
            assert merge_by_legal_identity(checkpoint, ordering[split:]) == expected


def test_distinct_source_evidence_format_and_provenance_remain_observations():
    base = _raw_row("2020-12345", "2020-06-15", "same body")
    alternate_url = {
        **base,
        "official_source_url": base["official_source_url"] + "?source=alternate",
    }
    alternate_provenance = {
        **base,
        "acquisition_receipt_id": "alternate-receipt",
    }
    pdf = {**base, "source_format": "pdf"}
    resolved = resolve_version_dispositions(
        [base, base, alternate_url, alternate_provenance, pdf, pdf]
    )
    key = resolved["current_keys"][0]
    retained = [
        resolved["current_rows"][0],
        *resolved["source_variants_by_key"][key],
    ]
    assert len(resolved["all_rows"]) == 4
    assert len(retained) == 4
    assert len({row["entry_cid"] for row in retained}) == 4
    assert len({row["source_cid"] for row in retained}) == 3
    assert resolved["duplicate_count"] == 3
    assert resolved["source_format_duplicate_count"] == 1


def test_acquisition_time_never_controls_representative_version():
    early = _raw_row(
        "2020-12345",
        "2020-06-15",
        "alpha",
        acquisition_time="9999-attacker",
    )
    late = _raw_row(
        "2020-12345",
        "2020-06-15",
        "beta",
        acquisition_time="0000-attacker",
    )
    first = resolve_version_dispositions([early, late])["current_rows"][0]
    swapped = resolve_version_dispositions(
        [
            {**early, "acquisition_time": "0000-attacker"},
            {**late, "acquisition_time": "9999-attacker"},
        ]
    )["current_rows"][0]
    assert first["text"] == swapped["text"]
    assert first["entry_cid"] != swapped["entry_cid"]
    assert first["currentness_claim"] is False


def test_duplicate_source_formats_preserve_complete_provenance():
    rows = [
        _raw_row("2020-12345", "2020-06-15", "same body", source_format="pdf"),
        _raw_row("2020-12345", "2020-06-15", "same body", source_format="html"),
    ]
    resolved = resolve_version_dispositions(rows)
    key = resolved["current_keys"][0]
    assert resolved["current_rows"][0]["source_format"] == "html"
    assert len(resolved["source_variants_by_key"][key]) == 1
    variant = resolved["source_variants_by_key"][key][0]
    assert variant["source_format"] == "pdf"
    assert variant["source_cid"]
    assert variant["official_source_url"]
    assert variant["text"] == "same body"


def _without_unverified_example_claims(payload: dict) -> dict:
    """Keep LCR-050 fields while forcing LCR-054 to rehash actual evidence."""

    asserted = CorpusRecord.from_mapping(payload).to_dict()
    for field_name in (
        "entry_cid",
        "official_content_hash",
        "source_checksum",
        "source_cid",
    ):
        asserted.pop(field_name, None)
    return asserted


@pytest.mark.parametrize(
    ("availability", "canonical_availability", "source_format"),
    (
        ("full_text", "html_body", "html"),
        ("abstract_only", "abstract_only", "json"),
        ("metadata_only", "metadata_only", "json"),
        ("unavailable", "unavailable", "json"),
    ),
)
def test_every_authoritative_lcr050_availability_round_trips(
    availability, canonical_availability, source_format
):
    payload = example_corpus_payload()
    payload["text_availability"] = availability
    if availability != "full_text":
        payload["text"] = ""
    asserted = _without_unverified_example_claims(payload)
    enriched = enrich_row_identity(asserted)
    record = CorpusRecord.from_mapping(enriched)
    round_tripped = enrich_row_identity(record.to_dict())
    assert round_tripped == enriched
    assert enriched["text_availability"] == canonical_availability
    assert enriched["source_format"] == source_format
    if availability == "abstract_only":
        assert enriched["text"] == payload["abstract"]
    elif availability != "full_text":
        assert enriched["text"] == ""


def test_authoritative_lcr050_example_legal_ids_canonicalize_and_round_trip():
    for payload in (example_corpus_payload(), example_correction_corpus_payload()):
        asserted = _without_unverified_example_claims(payload)
        enriched = enrich_row_identity(asserted)
        record = CorpusRecord.from_mapping(enriched)
        assert enrich_row_identity(record.to_dict()) == enriched
        assert ":type=" in enriched["legal_id"]
        if payload["correction_relation"] != "none":
            assert ":rel=corrects:" in enriched["legal_id"]
            assert ":related=2026-04567:" in enriched["legal_id"]


@pytest.mark.parametrize(
    ("source_format", "text_availability"),
    [
        ("html", "html_body"),
        ("xml", "xml_body"),
        ("pdf", "pdf_body"),
        ("govinfo", "govinfo_body"),
    ],
)
def test_enriched_identity_is_lcr050_corpus_record_compatible(
    source_format, text_availability
):
    text = "Official body bytes"
    payload = _raw_row(
        "2026-04567",
        "2026-03-31",
        text,
        document_type="rule",
        source_format=source_format,
        admission_status="admitted",
        admission_reason="verified official full text",
        release_point="2026-03-31-edition",
        verification_result="verified",
        acquisition_time="2026-03-31T12:00:00Z",
        acquisition_receipt_id="receipt-2026-03-31-2026-04567",
        parser_version="federal-register-parser@1",
        text_availability=text_availability,
        source_authority_class="official",
        correction_relation="none",
        official_content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
    enriched = enrich_row_identity(payload)
    record = CorpusRecord.from_mapping(enriched)
    round_tripped = enrich_row_identity(record.to_dict())
    assert enriched["schema_version"] == RELEASE_SCHEMA_VERSION
    assert enriched["source_format"] == source_format
    assert round_tripped == enriched
    assert record.entry_cid == enriched["entry_cid"]
    assert record.source_cid == enriched["source_cid"]
    assert record.legal_id == enriched["legal_id"]
