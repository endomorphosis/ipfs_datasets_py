"""Opt-in TypeSafe autoresearch for clause/formula rows.

A closed catalog of noul/score questions is answered per row. Code fits a
regressor (CatBoost if installed, else numpy least squares). Predictions are
advisory only: they cannot rewrite IR, drop formulas, or admit kernel proofs.

Unconstrained LLM question invention is out of catalog and dropped. No API
key → no HTTP, empty features. Keys stay in-memory.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from ipfs_datasets_py.logic.integrations.typesafe_advisor import typesafe_permitted

MAX_ROWS = 32
MAX_ROUNDS = 3
MAX_FEATURES = 8
MIN_SPREAD = 0.05
ADD_PER_ROUND = 1
INTENSITY_LEVELS = (
    "Not present at all",
    "Barely present",
    "Present at a moderate level",
    "Present strongly",
    "Dominant in the pair",
)
FEATURE_CATALOG: dict[str, dict[str, str]] = {
    "captures_clause": {
        "kind": "presence",
        "question": "Does `formula` capture the obligation or fact in `clause`?",
    },
    "hallucinated": {
        "kind": "presence",
        "question": "Does `formula` assert something `clause` does not state?",
    },
    "off_target": {
        "kind": "presence",
        "question": "Is `formula` about a different actor, action, or object than `clause`?",
    },
    "incomplete": {
        "kind": "presence",
        "question": "Does `formula` omit a condition, actor, or deadline stated in `clause`?",
    },
    "supported_by_source": {
        "kind": "presence",
        "question": "Is every predicate in `formula` grounded in `clause`?",
    },
    "names_deadline": {
        "kind": "presence",
        "question": "Does `clause` state a calendar or relative deadline?",
    },
    "formula_specificity": {
        "kind": "intensity",
        "question": "How specific is `formula` relative to `clause`?",
    },
    "modal_strength": {
        "kind": "intensity",
        "question": "How strong is the obligation, permission, or prohibition in `clause`?",
    },
}

_LAST = threading.local()


@dataclass(frozen=True)
class AutoresearchRow:
    clause: str
    formula: str = ""
    label: float = 0.0
    row_id: str = ""


def last_autoresearch() -> dict[str, Any]:
    value = getattr(_LAST, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


def catalog_feature_ids() -> tuple[str, ...]:
    return tuple(FEATURE_CATALOG.keys())


def _empty_payload(*, reason: str) -> dict[str, Any]:
    payload = {
        "accepted_as_authority": False,
        "rewrites_ir": False,
        "drops_formula": False,
        "kernel_verified": False,
        "features": [],
        "n_rows": 0,
        "rmse": None,
        "backend": "skipped",
        "predictions": [],
        "reason_codes": [reason],
    }
    _LAST.value = {
        key: value
        for key, value in payload.items()
        if key != "predictions"
    }
    return payload


def _sanitize_catalog(
    extra: Mapping[str, Mapping[str, str]] | None,
) -> dict[str, dict[str, str]]:
    catalog = {key: dict(value) for key, value in FEATURE_CATALOG.items()}
    for name, spec in dict(extra or {}).items():
        ident = str(name or "").strip()
        kind = str((spec or {}).get("kind") or "").strip()
        question = str((spec or {}).get("question") or "").strip()
        if ident in catalog or ident == "none":
            continue
        if kind not in {"presence", "intensity"} or not question:
            continue
        if len(catalog) >= MAX_FEATURES * 2:
            break
        catalog[ident] = {"kind": kind, "question": question[:240]}
    return catalog


def _build_questions(names: Sequence[str], catalog: Mapping[str, Mapping[str, str]]) -> dict[str, Any]:
    from ipfs_accelerate_py.typesafe_inference import Noul, Score

    questions: dict[str, Any] = {}
    for name in names:
        spec = catalog.get(name)
        if not spec:
            continue
        ask = str(spec.get("question") or "")[:240]
        if spec.get("kind") == "intensity":
            questions[name] = Score(
                instructions={"question": ask, "inspect": "`clause`"},
                criteria=list(INTENSITY_LEVELS),
            )
        else:
            questions[name] = Noul(
                instructions={"question": ask, "compare": ["`clause`", "`formula`"]},
            )
    return questions


def _noul_value(answer: Any) -> float:
    try:
        return float(getattr(answer, "noul", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _score_mean_spread(answer: Any) -> tuple[float, float]:
    probs = dict(getattr(answer, "probabilities", None) or {})
    weights: list[float] = []
    if probs:
        keys = list(INTENSITY_LEVELS)
        for index, key in enumerate(keys):
            raw = probs.get(index, probs.get(str(index), probs.get(key, 0.0)))
            try:
                weights.append(float(raw or 0.0))
            except (TypeError, ValueError):
                weights.append(0.0)
        total = sum(weights)
        if total > 0:
            weights = [item / total for item in weights]
            mean = sum(index * weight for index, weight in enumerate(weights))
            second = sum((index**2) * weight for index, weight in enumerate(weights))
            variance = max(0.0, second - mean * mean)
            return mean, variance**0.5
    try:
        score = float(getattr(answer, "score", 0.0) or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return score, 0.0


def _answer_rows(
    rows: Sequence[AutoresearchRow],
    names: Sequence[str],
    catalog: Mapping[str, Mapping[str, str]],
    *,
    timeout: float,
) -> dict[str, list[list[float]]]:
    from ipfs_accelerate_py.typesafe_inference import system_one

    questions = _build_questions(names, catalog)
    columns: dict[str, list[list[float]]] = {name: [] for name in names if name in questions}
    if not questions:
        return columns
    for row in rows:
        try:
            result = system_one(
                {
                    "clause": str(row.clause or "")[:240],
                    "formula": str(row.formula or "")[:240],
                    "row_id": str(row.row_id or "")[:64],
                },
                questions,
                timeout=timeout,
            )
        except Exception:
            for name, spec in ((ident, catalog[ident]) for ident in columns):
                columns[name].append([0.0] if spec["kind"] == "presence" else [0.0, 0.0])
            continue
        nouls = getattr(result, "nouls", None) or {}
        scores = getattr(result, "scores", None) or {}
        for name, spec in ((ident, catalog[ident]) for ident in columns):
            if spec["kind"] == "presence":
                columns[name].append([_noul_value(nouls.get(name))])
            else:
                mean, spread = _score_mean_spread(scores.get(name))
                columns[name].append([mean, spread])
    return columns


def _spread(column: Sequence[Sequence[float]]) -> float:
    if not column:
        return 0.0
    values = [float(row[0]) for row in column]
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / len(values)
    return variance**0.5


def _design(
    names: Sequence[str],
    columns: Mapping[str, Sequence[Sequence[float]]],
    catalog: Mapping[str, Mapping[str, str]],
) -> tuple[list[list[float]], list[str]]:
    labels: list[str] = []
    matrix: list[list[float]] = []
    n_rows = 0
    for name in names:
        rows = list(columns.get(name) or ())
        n_rows = max(n_rows, len(rows))
    for index in range(n_rows):
        matrix.append([])
    for name in names:
        spec = catalog.get(name) or {}
        rows = list(columns.get(name) or ())
        if spec.get("kind") == "intensity":
            labels.extend([name, f"{name}_sd"])
            for index in range(n_rows):
                pair = list(rows[index]) if index < len(rows) else [0.0, 0.0]
                matrix[index].extend([float(pair[0] if pair else 0.0), float(pair[1] if len(pair) > 1 else 0.0)])
        else:
            labels.append(name)
            for index in range(n_rows):
                pair = list(rows[index]) if index < len(rows) else [0.0]
                matrix[index].append(float(pair[0] if pair else 0.0))
    return matrix, labels


def _fit_predict(matrix: Sequence[Sequence[float]], labels: Sequence[float]) -> tuple[list[float], Optional[float], str]:
    if not matrix or not labels:
        return [], None, "skipped"
    try:
        import numpy as np
    except Exception:
        return [], None, "skipped"
    x = np.asarray(matrix, dtype=float)
    y = np.asarray(list(labels)[: len(x)], dtype=float)
    if len(y) < 2 or x.shape[0] != len(y):
        return [], None, "skipped"
    split = max(1, len(y) // 5)
    train = np.arange(0, len(y) - split) if len(y) - split >= 2 else np.arange(len(y))
    held = np.arange(len(y) - split, len(y)) if len(y) - split >= 2 else train
    backend = "numpy"
    try:
        from catboost import CatBoostRegressor

        model = CatBoostRegressor(
            iterations=40,
            depth=3,
            learning_rate=0.1,
            loss_function="RMSE",
            verbose=0,
            random_seed=0,
            allow_writing_files=False,
            thread_count=1,
        )
        model.fit(x[train], y[train])
        predicted = model.predict(x)
        backend = "catboost"
    except Exception:
        ones = np.ones((len(train), 1))
        design = np.concatenate([ones, x[train]], axis=1)
        beta, *_ = np.linalg.lstsq(design, y[train], rcond=None)
        predicted = x @ beta[1:] + beta[0]
        backend = "numpy"
    err = float(np.sqrt(np.mean((y[held] - predicted[held]) ** 2)))
    return [float(item) for item in predicted], round(err, 4), backend


def _propose_next(
    remaining: Sequence[str],
    *,
    timeout: float,
) -> str:
    if not remaining:
        return ""
    from ipfs_accelerate_py.typesafe_inference import Choice, system_one

    criteria = {name: {"what": name} for name in remaining[:MAX_FEATURES]}
    criteria["none"] = {"what": "Do not add another feature this round."}
    try:
        result = system_one(
            {"remaining": list(remaining[:MAX_FEATURES])},
            {
                "add": Choice(
                    instructions={
                        "question": (
                            "Which remaining catalog feature should be added for "
                            "clause/formula quality?"
                        )
                    },
                    criteria=criteria,
                )
            },
            timeout=timeout,
        )
    except Exception:
        return ""
    picked = str(
        getattr((getattr(result, "choices", None) or {}).get("add"), "choice", "")
        or ""
    ).strip()
    if picked == "none" or picked not in remaining:
        return ""
    return picked


def run_autoresearch(
    rows: Sequence[AutoresearchRow | Mapping[str, Any]],
    *,
    seed_features: Sequence[str] = ("captures_clause", "hallucinated", "formula_specificity"),
    extra_catalog: Mapping[str, Mapping[str, str]] | None = None,
    rounds: int = MAX_ROUNDS,
    min_spread: float = MIN_SPREAD,
    privacy_class: str = "repository_private",
    remote_disclosure_permitted: bool = True,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Propose from the closed catalog, answer, fit. Never admits proofs."""

    catalog = _sanitize_catalog(extra_catalog)
    parsed: list[AutoresearchRow] = []
    for item in rows:
        if isinstance(item, AutoresearchRow):
            parsed.append(
                AutoresearchRow(
                    clause=str(item.clause or "")[:240],
                    formula=str(item.formula or "")[:240],
                    label=float(item.label or 0.0),
                    row_id=str(item.row_id or "")[:64],
                )
            )
        elif isinstance(item, Mapping):
            parsed.append(
                AutoresearchRow(
                    clause=str(item.get("clause") or "")[:240],
                    formula=str(item.get("formula") or "")[:240],
                    label=float(item.get("label") or 0.0),
                    row_id=str(item.get("row_id") or item.get("id") or "")[:64],
                )
            )
        if len(parsed) >= MAX_ROWS:
            break
    if not parsed:
        return _empty_payload(reason="no_rows")
    if not typesafe_permitted(
        privacy_class=privacy_class,
        remote_disclosure_permitted=remote_disclosure_permitted,
    ):
        payload = _empty_payload(reason="privacy_or_unconfigured")
        payload["n_rows"] = len(parsed)
        _LAST.value["n_rows"] = len(parsed)
        return payload

    selected: list[str] = []
    for name in seed_features:
        ident = str(name or "").strip()
        if ident in catalog and ident not in selected:
            selected.append(ident)
        if len(selected) >= MAX_FEATURES:
            break
    columns: dict[str, list[list[float]]] = {}
    history: list[float] = []
    predictions: list[float] = []
    rmse: Optional[float] = None
    backend = "skipped"
    reasons = ["composed_in_code", "closed_catalog", "advisory_only"]
    bound = max(1, min(int(rounds or 1), MAX_ROUNDS))

    for round_index in range(bound):
        unanswered = [name for name in selected if name not in columns]
        if unanswered:
            columns.update(
                _answer_rows(parsed, unanswered, catalog, timeout=timeout)
            )
        kept: list[str] = []
        for name in selected:
            if _spread(columns.get(name) or []) < float(min_spread) and name not in kept:
                reasons.append(f"flat:{name}")
                continue
            kept.append(name)
        selected = kept[:MAX_FEATURES]
        matrix, _labels = _design(selected, columns, catalog)
        y = [float(row.label) for row in parsed]
        predictions, rmse, backend = _fit_predict(matrix, y)
        if rmse is not None:
            history.append(rmse)
        remaining = [name for name in catalog if name not in selected]
        if round_index + 1 >= bound or not remaining:
            break
        added = 0
        while added < ADD_PER_ROUND and remaining:
            picked = _propose_next(remaining, timeout=timeout)
            if not picked:
                remaining = []
                break
            if picked not in selected:
                selected.append(picked)
                added += 1
            remaining = [name for name in remaining if name != picked]

    payload = {
        "accepted_as_authority": False,
        "rewrites_ir": False,
        "drops_formula": False,
        "kernel_verified": False,
        "features": list(selected),
        "n_rows": len(parsed),
        "rmse": rmse,
        "backend": backend,
        "history": history,
        "predictions": predictions,
        "reason_codes": list(dict.fromkeys(reasons)),
    }
    _LAST.value = {
        key: value for key, value in payload.items() if key != "predictions"
    }
    return payload


def observe_autoresearch(
    rows: Sequence[AutoresearchRow | Mapping[str, Any]],
    **kwargs: Any,
) -> dict[str, Any]:
    """Never-raises wrapper. Does not rewrite IR or admit proofs."""

    try:
        return run_autoresearch(rows, **kwargs)
    except Exception:
        return _empty_payload(reason="typesafe_error_fail_open")


__all__ = [
    "AutoresearchRow",
    "FEATURE_CATALOG",
    "catalog_feature_ids",
    "last_autoresearch",
    "observe_autoresearch",
    "run_autoresearch",
]
