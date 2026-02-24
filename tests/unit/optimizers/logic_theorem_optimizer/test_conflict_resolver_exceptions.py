"""Tests for typed exception handling in conflict resolver paths."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import conflict_resolver as cr


def _sample_conflict() -> cr.Conflict:
    return cr.Conflict(
        conflict_id="c1",
        conflict_type=cr.ConflictType.DISAGREEMENT,
        statements=[
            cr.LogicalStatement(formula="P(a)", source="s1"),
            cr.LogicalStatement(formula="Q(a)", source="s2"),
        ],
        description="sample",
        detected_at=0.0,
        severity=0.5,
    )


def test_resolve_conflicts_handles_typed_value_error(monkeypatch) -> None:
    resolver = cr.ConflictResolver(strategy=cr.ResolutionStrategy.VOTING)
    conflict = _sample_conflict()

    monkeypatch.setattr(resolver.detector, "detect_conflicts", lambda statements: [conflict])
    monkeypatch.setattr(resolver, "_resolve_conflict", lambda c: (_ for _ in ()).throw(ValueError("bad resolution")))

    result = resolver.resolve_conflicts(conflict.statements)

    assert result.total_conflicts == 1
    assert result.conflicts_resolved == 0
    assert result.conflicts_unresolved == 1
    assert result.unresolved_conflicts == [conflict]


def test_resolve_conflicts_does_not_swallow_keyboard_interrupt(monkeypatch) -> None:
    resolver = cr.ConflictResolver(strategy=cr.ResolutionStrategy.VOTING)
    conflict = _sample_conflict()

    monkeypatch.setattr(resolver.detector, "detect_conflicts", lambda statements: [conflict])
    monkeypatch.setattr(resolver, "_resolve_conflict", lambda c: (_ for _ in ()).throw(KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        resolver.resolve_conflicts(conflict.statements)
