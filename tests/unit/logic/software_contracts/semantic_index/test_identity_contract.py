"""Regression vectors for durable semantic-symbol identity."""

from __future__ import annotations

import ast

from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    stable_symbol_id,
    symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import SymbolKind, SymbolRecord


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
