"""Regression vectors for durable semantic-symbol identity."""

from __future__ import annotations

import ast

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_index import identity
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    stable_symbol_id,
    symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import SemanticIndexModelError, SymbolKind, SymbolRecord


def test_aggregate_facets_have_span_independent_stable_identity() -> None:
    """Constructed extractor aggregates need no source span to identify them."""
    overload = stable_symbol_id("repo:aggregate", "python", "pkg/api.py", "pkg.api.parse", SymbolKind.FUNCTION, "pkg")
    rebound = stable_symbol_id("repo:aggregate", "python", "pkg/api.py", "pkg.api.parse", SymbolKind.FUNCTION, "pkg")
    property_facet = stable_symbol_id("repo:aggregate", "python", "pkg/api.py", "pkg.api.Item.value", SymbolKind.PROPERTY, "pkg")
    assert overload == rebound
    assert overload != property_facet


def test_unrelated_fields_and_formatting_do_not_change_logical_identity() -> None:
    stable = stable_symbol_id("repo:aggregate", "python", "pkg/api.py", "pkg.api.Item.value", "property", "pkg")
    compact = ast.parse("def value(self): return 1").body[0]
    formatted = ast.parse("\n\ndef value(self):\n    return 1\n").body[0]
    assert stable == stable_symbol_id("repo:aggregate", "python", "pkg/api.py", "pkg.api.Item.value", "property", "pkg")
    assert symbol_version_cid(stable, compact, property_role="getter") == symbol_version_cid(stable, formatted, property_role="getter")


def test_constructed_property_aggregate_round_trips_without_a_span() -> None:
    stable = stable_symbol_id("repo:aggregate", "python", "pkg/api.py", "pkg.api.Item.value", "property", "pkg")
    aggregate = {"_type": "PropertyAggregate", "facets": ["getter", "setter", "getter"]}
    version = symbol_version_cid(stable, aggregate, property_role="aggregate")
    symbol = SymbolRecord(
        stable, version, "repo:aggregate", "python", "pkg/api.py", "pkg.api.Item.value",
        "property", "pkg", normalized_ast=aggregate, property_role="aggregate",
    )
    assert symbol.span is None
    assert SymbolRecord.from_dict(symbol.to_dict()) == symbol
    with pytest.raises(TypeError):
        symbol.normalized_ast["facets"] = ()
    with pytest.raises(AttributeError):
        symbol.normalized_ast["facets"].append("deleter")


def test_nonfinite_and_signed_zero_ast_literals_have_distinct_tagged_cids() -> None:
    stable = stable_symbol_id("repo:aggregate", "python", "pkg/api.py", "pkg.api.literal", "constant", "pkg")
    positive_infinity = ast.parse("x = 1e400").body[0]
    negative_infinity = ast.parse("x = -1e400").body[0]
    complex_positive = ast.Constant(value=complex(float("inf"), float("-inf")))
    complex_negative = ast.Constant(value=complex(float("-inf"), float("inf")))
    plus_zero = ast.Constant(value=0.0)
    minus_zero = ast.Constant(value=-0.0)

    cids = {
        symbol_version_cid(stable, positive_infinity),
        symbol_version_cid(stable, negative_infinity),
        symbol_version_cid(stable, complex_positive),
        symbol_version_cid(stable, complex_negative),
        symbol_version_cid(stable, plus_zero),
        symbol_version_cid(stable, minus_zero),
    }
    assert len(cids) == 6

    record = SymbolRecord(
        stable, symbol_version_cid(stable, complex_positive), "repo:aggregate", "python",
        "pkg/api.py", "pkg.api.literal", "constant", "pkg", normalized_ast=complex_positive,
    )
    assert SymbolRecord.from_dict(record.to_dict()) == record


@pytest.mark.parametrize(
    "literal",
    [
        float("nan"),
        complex(float("nan"), 0.0),
        complex(0.0, float("nan")),
    ],
)
def test_symbol_version_cid_rejects_nan_before_content_hashing(
    monkeypatch: pytest.MonkeyPatch, literal: object
) -> None:
    stable = stable_symbol_id("repo:aggregate", "python", "pkg/api.py", "pkg.api.literal", "constant", "pkg")

    def content_hasher_must_not_run(value: object) -> str:
        pytest.fail(f"content hasher received rejected value: {value!r}")

    monkeypatch.setattr(identity, "cid_for_structured", content_hasher_must_not_run)

    with pytest.raises(SemanticIndexModelError, match="rejects NaN"):
        identity.symbol_version_cid(stable, ast.Constant(value=literal))


def test_forged_aggregate_facet_cannot_retain_the_old_version_cid() -> None:
    stable = stable_symbol_id("repo:aggregate", "python", "pkg/api.py", "pkg.api.Item.value", "property", "pkg")
    aggregate = {"_type": "PropertyAggregate", "facets": ["getter", "setter"]}
    symbol = SymbolRecord(
        stable, symbol_version_cid(stable, aggregate, property_role="aggregate"),
        "repo:aggregate", "python", "pkg/api.py", "pkg.api.Item.value", "property", "pkg",
        normalized_ast=aggregate, property_role="aggregate",
    )
    forged = symbol.to_dict()
    forged["normalized_ast"]["facets"].append("deleter")
    with pytest.raises(SemanticIndexModelError, match="version_cid does not verify"):
        SymbolRecord.from_dict(forged)
