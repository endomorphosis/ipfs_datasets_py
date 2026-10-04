#!/usr/bin/env python3

from ipfs_datasets_py.processors.web_archiving.structured_schema_compat import (
    normalize_domain,
    normalize_structured_fields,
    validate_structured_fields_contract,
)


def test_normalize_domain_aliases() -> None:
    assert normalize_domain("laws") == "legal"
    assert normalize_domain("financial") == "finance"
    assert normalize_domain("clinical") == "medical"
    assert normalize_domain("unknown-domain") == "general"


def test_normalize_structured_fields_applies_schema_contract() -> None:
    fields, meta = normalize_structured_fields(
        fields={
            "schema": "general_v1",
            "section_headers": ["TITLE 1"],
            "dates": [],
            "legal_citations": ["18 U.S.C. 1001"],
            "statute_identifiers": [],
            "monetary_amounts": [],
            "is_pdf_content": False,
        },
        requested_domain="legal",
        source_type="pdf",
    )

    assert fields["schema"] == "legal_v1"
    assert fields["section_headers"] == ["TITLE 1"]
    assert fields["is_pdf_content"] is True
    assert fields["effective_dates"] == []
    assert fields["parties"] == []

    assert meta["requested_domain"] == "legal"
    assert meta["schema_migration_applied"] is True
    assert meta["structured_fields_contract"] == "v1"


def test_validate_structured_fields_contract() -> None:
    ok = {
        "schema": "finance_v1",
        "dates": [],
        "monetary_amounts": [],
        "percentages": [],
        "ticker_symbols": [],
        "accounting_terms": [],
        "is_pdf_content": False,
    }
    bad = {**ok, "extra": "nope"}

    assert validate_structured_fields_contract(ok) is True
    assert validate_structured_fields_contract(bad) is False
