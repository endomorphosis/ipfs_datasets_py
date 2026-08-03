"""Unit tests for USPTO identifier normalization (PATLAW-020)."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    ApplicationIdentity,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.identifiers import (
    IDENTIFIERS_SCHEMA_VERSION,
    IdentifierError,
    IdentifierKind,
    IdentifierStatus,
    NormalizedIdentifier,
    application_check_digit,
    build_application_identity,
    format_identifier,
    normalize_application_number,
    normalize_confirmation_number,
    normalize_customer_number,
    normalize_patent_number,
    normalize_publication_number,
    parse_identifier,
    round_trip_identifier,
)


def _assert_ident_round_trip(record: NormalizedIdentifier) -> None:
    first = record.to_dict()
    restored = NormalizedIdentifier.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    assert (
        json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        == canonical_json(first)
    )
    assert restored == record


# ---------------------------------------------------------------------------
# Application numbers
# ---------------------------------------------------------------------------


def test_application_display_and_compact_round_trip() -> None:
    display = normalize_application_number("16/123,456")
    assert display.status is IdentifierStatus.RESOLVED
    assert display.compact == "16123456"
    assert display.display == "16/123,456"
    assert display.components["series"] == "16"
    assert display.components["serial"] == "123456"

    compact = normalize_application_number("16123456")
    assert compact.compact == display.compact
    assert compact.display == display.display

    again = normalize_application_number(display.display)
    assert again.compact == display.compact
    assert again.display == display.display

    via_api = round_trip_identifier("16/123456", kind=IdentifierKind.APPLICATION)
    assert via_api.compact == "16123456"


def test_application_check_digit_verified_and_mismatch() -> None:
    body = "16123456"
    check = application_check_digit(body)
    assert len(check) == 1 and check.isdigit()

    good = normalize_application_number(f"{body}{check}")
    assert good.status is IdentifierStatus.RESOLVED
    assert good.check_digit_valid is True

    bad = normalize_application_number(f"{body}{(int(check) + 1) % 10}")
    assert bad.status is IdentifierStatus.INVALID
    assert bad.check_digit_valid is False

    with pytest.raises(IdentifierError) as excinfo:
        normalize_application_number(f"{body}{(int(check) + 1) % 10}", strict=True)
    assert excinfo.value.code == "check_digit_mismatch"


def test_invalid_application_rejected_or_invalid() -> None:
    soft = normalize_application_number("not-an-app")
    assert soft.status is IdentifierStatus.INVALID
    assert soft.compact == ""
    assert soft.display == ""

    with pytest.raises(IdentifierError):
        normalize_application_number("99/12", strict=True)

    with pytest.raises(IdentifierError):
        normalize_application_number("", strict=True)


# ---------------------------------------------------------------------------
# Publication / patent / confirmation / customer
# ---------------------------------------------------------------------------


def test_publication_round_trip() -> None:
    forms = (
        "US 2020/0123456 A1",
        "US20200123456A1",
        "2020/0123456A1",
        "2020/0,123,456 A1",
    )
    compacts = set()
    for form in forms:
        ident = normalize_publication_number(form)
        assert ident.status is IdentifierStatus.RESOLVED, form
        assert ident.kind is IdentifierKind.PUBLICATION
        assert ident.components["year"] == "2020"
        assert ident.components["sequence"] == "0123456"
        assert ident.components.get("kind_code") == "A1"
        assert ident.compact.startswith("US2020")
        compacts.add(ident.compact)
        # display → parse → same compact
        again = normalize_publication_number(ident.display)
        assert again.compact == ident.compact
    assert len(compacts) == 1


def test_patent_kinds_without_conflation() -> None:
    utility = normalize_patent_number("10,123,456")
    assert utility.status is IdentifierStatus.RESOLVED
    assert utility.compact == "10123456"
    assert utility.display == "10,123,456"
    assert utility.components["prefix"] == ""

    design = normalize_patent_number("D1234567")
    assert design.compact == "D1234567"
    assert design.components["prefix"] == "D"

    plant = normalize_patent_number("PP12,345")
    assert plant.compact == "PP12345"
    assert plant.components["prefix"] == "PP"

    reissue = normalize_patent_number("RE45678")
    assert reissue.compact == "RE45678"

    # Patent number must not be stored as an application.
    assert design.kind is IdentifierKind.PATENT
    assert normalize_application_number("D1234567").status is IdentifierStatus.INVALID


def test_confirmation_and_customer() -> None:
    conf = normalize_confirmation_number("1234")
    assert conf.status is IdentifierStatus.RESOLVED
    assert conf.compact == conf.display == "1234"
    assert normalize_confirmation_number("12").status is IdentifierStatus.INVALID

    cust = normalize_customer_number("12345")
    assert cust.status is IdentifierStatus.RESOLVED
    assert cust.compact == "12345"
    assert normalize_customer_number("12").status is IdentifierStatus.INVALID
    assert normalize_customer_number("1234567").status is IdentifierStatus.INVALID


# ---------------------------------------------------------------------------
# Ambiguity / disambiguation
# ---------------------------------------------------------------------------


def test_ambiguous_digit_string_returned_unresolved() -> None:
    # 8 digits can be application compact or utility patent.
    result = parse_identifier("16123456")
    assert result.status is IdentifierStatus.UNRESOLVED
    assert result.compact == ""
    assert "ambiguous_identifier" in result.notes
    assert "application" in result.components.get("candidate_kinds", "")
    assert "patent" in result.components.get("candidate_kinds", "")

    with pytest.raises(IdentifierError) as excinfo:
        parse_identifier("16123456", strict=True)
    assert excinfo.value.code == "ambiguous_identifier"


def test_declared_kind_disambiguates() -> None:
    as_app = parse_identifier("16123456", kind=IdentifierKind.APPLICATION)
    assert as_app.status is IdentifierStatus.RESOLVED
    assert as_app.kind is IdentifierKind.APPLICATION
    assert as_app.display == "16/123,456"

    as_pat = parse_identifier("16123456", kind=IdentifierKind.PATENT)
    assert as_pat.status is IdentifierStatus.RESOLVED
    assert as_pat.kind is IdentifierKind.PATENT
    assert as_pat.compact == "16123456"


def test_distinctive_formats_resolve_without_kind() -> None:
    app = parse_identifier("16/123,456")
    assert app.status is IdentifierStatus.RESOLVED
    assert app.kind is IdentifierKind.APPLICATION

    pub = parse_identifier("US20200123456A1")
    assert pub.status is IdentifierStatus.RESOLVED
    assert pub.kind is IdentifierKind.PUBLICATION

    design = parse_identifier("D1,234,567")
    assert design.status is IdentifierStatus.RESOLVED
    assert design.kind is IdentifierKind.PATENT


def test_unrecognized_invalid() -> None:
    bad = parse_identifier("???")
    assert bad.status is IdentifierStatus.INVALID
    with pytest.raises(IdentifierError):
        parse_identifier("???", strict=True)


# ---------------------------------------------------------------------------
# ApplicationIdentity builder
# ---------------------------------------------------------------------------


def test_build_application_identity_round_trip_and_notes() -> None:
    identity = build_application_identity(
        application="16/123,456",
        publication="US 2020/0123456 A1",
        patent=None,
        confirmation="4321",
        customer="99887",
        source="odp_patent_file_wrapper",
        confidence=0.95,
    )
    assert isinstance(identity, ApplicationIdentity)
    assert identity.schema_version == CONTRACTS_SCHEMA_VERSION
    assert identity.application_number == "16/123,456"
    assert identity.publication_number is not None
    assert identity.unresolved_ambiguity is False
    assert any(n.startswith("confirmation:") for n in identity.notes)
    assert any(n.startswith("customer:") for n in identity.notes)

    # Contract serialization still round-trips.
    restored = ApplicationIdentity.from_dict(identity.to_dict())
    assert restored == identity


def test_build_identity_marks_unresolved_components() -> None:
    identity = build_application_identity(
        application="16/123,456",
        patent="not-a-patent",
        source="test",
        strict=False,
    )
    assert identity.unresolved_ambiguity is True
    assert any("patent:invalid" in n for n in identity.notes)


def test_build_identity_rejects_incomplete_and_strict_invalid() -> None:
    with pytest.raises(IdentifierError) as excinfo:
        build_application_identity(
            confirmation="1234",
            source="test",
        )
    assert excinfo.value.code == "identity_incomplete"

    with pytest.raises(IdentifierError):
        build_application_identity(
            application="16/123,456",
            patent="not-a-patent",
            source="test",
            strict=True,
        )


def test_kind_slot_mismatch() -> None:
    patent = normalize_patent_number("10123456")
    with pytest.raises(IdentifierError) as excinfo:
        build_application_identity(
            application=patent,
            source="test",
        )
    assert excinfo.value.code == "kind_slot_mismatch"


def test_normalized_identifier_dict_round_trip() -> None:
    ident = normalize_application_number("17/000,001")
    _assert_ident_round_trip(ident)
    unresolved = parse_identifier("16123456")
    _assert_ident_round_trip(unresolved)


def test_format_identifier_styles() -> None:
    ident = normalize_application_number("16/123,456")
    assert format_identifier(ident, style="display") == "16/123,456"
    assert format_identifier(ident, style="compact") == "16123456"
    assert format_identifier(ident.to_dict(), style="compact") == "16123456"

    unresolved = parse_identifier("16123456")
    with pytest.raises(IdentifierError):
        format_identifier(unresolved)


def test_schema_version_pinned() -> None:
    assert IDENTIFIERS_SCHEMA_VERSION == "uspto.identifiers.v1"
