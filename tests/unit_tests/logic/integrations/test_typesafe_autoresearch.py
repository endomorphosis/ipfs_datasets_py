from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.integrations.typesafe_autoresearch import (
    AutoresearchRow,
    catalog_feature_ids,
    last_autoresearch,
    observe_autoresearch,
    run_autoresearch,
)


def _clear_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "ipfs_accelerate_py_TYPESAFE_API_KEY",
        "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
        "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def _install_inference_stub(monkeypatch: pytest.MonkeyPatch, system_one) -> None:
    import sys
    import types as _types

    parent = sys.modules.get("ipfs_accelerate_py")
    if parent is None:
        parent = _types.ModuleType("ipfs_accelerate_py")
        monkeypatch.setitem(sys.modules, "ipfs_accelerate_py", parent)

    class _Noul:
        def __init__(self, instructions=None, criteria=None) -> None:
            self.instructions = instructions

    class _Score:
        def __init__(self, instructions=None, criteria=None) -> None:
            self.instructions = instructions
            self.criteria = criteria

    class _Choice:
        def __init__(self, instructions=None, criteria=None) -> None:
            self.instructions = instructions
            self.criteria = criteria

    stub = _types.ModuleType("ipfs_accelerate_py.typesafe_inference")
    stub.Noul = _Noul
    stub.Score = _Score
    stub.Choice = _Choice
    stub.system_one = system_one
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.typesafe_inference", stub)


def test_autoresearch_without_key_skips_http(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    called: list[int] = []
    _install_inference_stub(monkeypatch, lambda *_a, **_k: called.append(1))
    view = run_autoresearch(
        [
            {"clause": "All humans are mortal", "formula": "Human(x)", "label": 0.9},
            {"clause": "Socrates is a human", "formula": "Human(s)", "label": 0.8},
        ]
    )
    assert called == []
    assert view["features"] == []
    assert view["predictions"] == []
    assert view["accepted_as_authority"] is False
    assert view["kernel_verified"] is False
    assert view["rewrites_ir"] is False
    assert last_autoresearch()["accepted_as_authority"] is False
    assert "predictions" not in last_autoresearch()


def test_autoresearch_drops_unknown_catalog_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.integrations.typesafe_autoresearch.typesafe_permitted",
        lambda **_kwargs: True,
    )
    calls: list[int] = []

    def _system_one(_state, questions, **_kwargs):
        index = len(calls)
        calls.append(1)
        if "add" in questions:
            return SimpleNamespace(
                choices={
                    "add": SimpleNamespace(choice="invented_wine_score", confidence=0.99)
                },
                nouls={},
                scores={},
            )
        return SimpleNamespace(
            nouls={
                "captures_clause": SimpleNamespace(noul=0.2 + 0.1 * index),
                "hallucinated": SimpleNamespace(noul=0.7 - 0.05 * index),
            },
            scores={
                "formula_specificity": SimpleNamespace(
                    score=float(index % 5),
                    probabilities={
                        i: (1.0 if i == index % 5 else 0.0) for i in range(5)
                    },
                )
            },
            choices={},
        )

    _install_inference_stub(monkeypatch, _system_one)
    view = run_autoresearch(
        [
            AutoresearchRow("All humans are mortal", "H(x)", 0.9, "r1"),
            AutoresearchRow("Socrates is human", "H(s)", 0.2, "r2"),
            AutoresearchRow("Birds fly", "Bird(x)", 0.5, "r3"),
            AutoresearchRow("Fish swim", "Fish(x)", 0.4, "r4"),
            AutoresearchRow("Dogs bark", "Dog(x)", 0.6, "r5"),
        ],
        extra_catalog={
            "invented_wine_score": {"kind": "presence", "question": ""},
            "bad_kind": {"kind": "embedding", "question": "vector please"},
        },
        rounds=2,
    )
    assert "invented_wine_score" not in view["features"]
    assert "bad_kind" not in view["features"]
    assert set(view["features"]).issubset(set(catalog_feature_ids()))
    assert view["accepted_as_authority"] is False
    assert view["kernel_verified"] is False
    assert view["drops_formula"] is False


def test_autoresearch_predictions_are_advisory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.integrations.typesafe_autoresearch.typesafe_permitted",
        lambda **_kwargs: True,
    )
    calls: list[int] = []

    def _system_one(_state, questions, **_kwargs):
        index = len(calls)
        calls.append(1)
        if "add" in questions:
            return SimpleNamespace(
                choices={"add": SimpleNamespace(choice="none", confidence=0.4)},
                nouls={},
                scores={},
            )
        return SimpleNamespace(
            nouls={
                "captures_clause": SimpleNamespace(noul=0.2 + 0.15 * (index % 5)),
                "hallucinated": SimpleNamespace(noul=0.8 - 0.1 * (index % 5)),
            },
            scores={
                "formula_specificity": SimpleNamespace(
                    score=float(index % 5),
                    probabilities={
                        i: (1.0 if i == index % 5 else 0.0) for i in range(5)
                    },
                )
            },
            choices={},
        )

    _install_inference_stub(monkeypatch, _system_one)
    view = observe_autoresearch(
        [
            {"clause": "All humans are mortal", "formula": "∀x.(H(x)→M(x))", "label": 1.0},
            {"clause": "Socrates is a human", "formula": "H(s)", "label": 0.8},
            {"clause": "The sky is green", "formula": "Green(sky)", "label": 0.1},
            {"clause": "Water is wet", "formula": "Wet(water)", "label": 0.7},
            {"clause": "2+2=4", "formula": "Eq(plus(2,2),4)", "label": 0.9},
        ],
        rounds=1,
    )
    assert view["accepted_as_authority"] is False
    assert view["kernel_verified"] is False
    assert view["rewrites_ir"] is False
    assert view["n_rows"] == 5
    if view["predictions"]:
        assert len(view["predictions"]) == 5
    assert last_autoresearch().get("backend") in {"numpy", "catboost", "skipped"}
