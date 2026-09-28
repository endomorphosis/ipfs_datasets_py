"""Census a federal span with the codec and the compiler.

Agreement requires a compiler round trip, codec text, and a Lake build of a
formula. Lake success is not a legal admit. Training starts when cosine
similarity is below 0.72, reconstruction loss is above 0.20, or the IR
compression loss is above 0.50. Family cross-entropy is reported and is not
a training gate: a uniform prediction over nine families is always ln(9).
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence


# CodexCallGateConfig in modal_autoencoder.py.
MIN_COSINE_SIMILARITY = 0.72
MAX_RECONSTRUCTION_LOSS = 0.20
FAMILY_CROSS_ENTROPY_LIMIT = 1.20
VIEW_CROSS_ENTROPY_LIMIT = 0.05
MAX_COMPRESSION_LOSS = 0.50
FEDERAL_SPAN_CACHE = "/tmp/ipfs-uscode-autoformal/span-cache.duckdb"
INITIAL_LEARNING_RATE = 0.35
MIN_LEARNING_RATE = 0.05
MAX_LEARNING_RATE = 0.35


def threshold_at_round(round_index: int) -> dict[str, float]:
    """Tighten the holdout gate as training proceeds. Round 0 is the loose gate."""

    step = max(0, min(int(round_index), 8))
    return {
        "cosine_similarity": min(MIN_COSINE_SIMILARITY, 0.40 + 0.04 * step),
        "cross_entropy_loss": max(2.4, 3.2 - 0.10 * step),
        "reconstruction_loss": max(MAX_RECONSTRUCTION_LOSS, 0.60 - 0.05 * step),
    }


def metric_misses(scores: Mapping[str, Any], threshold: Mapping[str, float]) -> list[str]:
    """Names of measured scores that miss this round's gate. Unmeasured scores are not misses."""

    misses: list[str] = []
    similarity = _loss(scores.get("cosine_similarity"))
    reconstruction = _loss(scores.get("reconstruction_loss"))
    cross_entropy = _loss(scores.get("cross_entropy_loss"))
    if similarity is not None and similarity < float(threshold["cosine_similarity"]):
        misses.append("cosine_similarity")
    if reconstruction is not None and reconstruction > float(threshold["reconstruction_loss"]):
        misses.append("reconstruction_loss")
    if cross_entropy is not None and cross_entropy > float(threshold["cross_entropy_loss"]):
        misses.append("cross_entropy_loss")
    return misses


def _scores_need_training(scores: Mapping[str, Any]) -> bool:
    """True when cosine similarity, reconstruction, or IR compression misses its gate."""

    similarity = _loss(scores.get("cosine_similarity"))
    reconstruction = _loss(scores.get("reconstruction_loss"))
    compression = _loss(scores.get("ir_compression_loss"))
    return (
        (similarity is not None and similarity < MIN_COSINE_SIMILARITY)
        or (reconstruction is not None and reconstruction > MAX_RECONSTRUCTION_LOSS)
        or (compression is not None and compression > MAX_COMPRESSION_LOSS)
    )


def _loss(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Mean Laplace cross-entropy over round-trip tokens and formula atoms.
# A shall/must paraphrase is about 2.0. A citation the decompiler dropped, or an
# unrelated decompilation, is about 2.6. This is not the nine-family ln(9) score.
RESULT_CROSS_ENTROPY_LIMIT = 2.4


def _token_counts(text: str) -> dict[str, int]:
    import re

    counts: dict[str, int] = {}
    for token in re.findall(r"[a-z0-9]+", str(text or "").lower()):
        counts[token] = counts.get(token, 0) + 1
    return counts


def _count_cosine(left: Mapping[str, int], right: Mapping[str, int]) -> float:
    import math

    keys = set(left) | set(right)
    dot = sum(left.get(key, 0) * right.get(key, 0) for key in keys)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _mean_laplace_cross_entropy(measurements: Sequence[str], support: Sequence[str]) -> tuple[float | None, int]:
    """Mean ``-log p`` over measurements. Laplace smoothing keeps a miss finite."""

    import math

    checked = [token for token in measurements if token]
    if not checked or not support:
        return None, len(checked)
    counts: dict[str, int] = {}
    for token in support:
        counts[token] = counts.get(token, 0) + 1
    vocabulary = set(counts) | set(checked)
    denominator = sum(counts.values()) + len(vocabulary)
    loss = 0.0
    for token in checked:
        probability = (counts.get(token, 0) + 1) / denominator
        loss += -math.log(probability)
    return loss / len(checked), len(checked)


def _formula_matches_text(formulas: Sequence[Mapping[str, Any]], text: str) -> bool:
    import re

    tokens = set(re.findall(r"[a-z0-9]+", str(text or "").lower()))
    if not tokens:
        return False
    for formula in formulas:
        if not isinstance(formula, Mapping):
            continue
        parts = re.findall(r"[a-z0-9]+", str(formula.get("predicate") or "").lower())
        for part in parts:
            if len(part) < 4:
                continue
            if any(token.startswith(part) or part.startswith(token) for token in tokens):
                return True
    return False


def _formula_measurements(formulas: Sequence[Mapping[str, Any]]) -> list[str]:
    import re

    cues = {"O": "must", "F": "not", "P": "may"}
    measurements: list[str] = []
    for formula in formulas:
        if not isinstance(formula, Mapping):
            continue
        operator = str(formula.get("op") or "")
        cue = cues.get(operator)
        if cue:
            measurements.append(cue)
        measurements.extend(
            token
            for token in re.findall(r"[a-z0-9]+", str(formula.get("predicate") or "").lower())
            if len(token) >= 2
        )
    return measurements


def result_alignment(row: Mapping[str, Any]) -> dict[str, Any]:
    """Mean cross-entropy of the round-trip text and the formula, divided by the check count."""

    import re

    repair = dict(row.get("repair") or {})
    autoencoder = dict(repair.get("autoencoder") or {})
    decoded = str(autoencoder.get("decoded_text") or "")
    decompiled = str(row.get("decompiled") or "")
    formulas = list(autoencoder.get("formulas") or [])
    decoded_tokens = re.findall(r"[a-z0-9]+", decoded.lower())
    decompiled_tokens = re.findall(r"[a-z0-9]+", decompiled.lower())
    formula_tokens = _formula_measurements(formulas)
    round_trip_loss, round_trip_count = _mean_laplace_cross_entropy(decompiled_tokens, decoded_tokens)
    formula_loss, formula_count = _mean_laplace_cross_entropy(formula_tokens, decompiled_tokens)
    # An empty decompilation leaves formula atoms with nothing to score.
    # Those attempts are not a zero loss.
    scored = 0
    weighted = 0.0
    if round_trip_loss is not None:
        weighted += round_trip_loss * round_trip_count
        scored += round_trip_count
    if formula_loss is not None:
        weighted += formula_loss * formula_count
        scored += formula_count
    cross_entropy = (weighted / scored) if scored else None
    measurements = scored
    cosine = _count_cosine(_token_counts(decoded), _token_counts(decompiled))
    return {
        "admitted": False,
        "cosine_similarity": cosine,
        "cross_entropy_loss": cross_entropy,
        "formula_cross_entropy_loss": formula_loss,
        "formula_matches": _formula_matches_text(formulas, decompiled),
        "formalized": False,
        "measurements": measurements,
        "round_trip_cross_entropy_loss": round_trip_loss,
    }


def encoding_consensus(row: Mapping[str, Any]) -> str:
    """Agree only when the round-trip text, the formula, and the two losses match.

    ``agree`` requires a compiler decompilation, a formula token in that text,
    cosine similarity of at least 0.72, and mean cross-entropy of at most 2.4
    across the decompiled words and the formula atoms.
    ``unscored`` means the autoencoder emitted no formula.
    """

    repair = dict(row.get("repair") or {})
    formulas = list((repair.get("autoencoder") or {}).get("formulas") or [])
    encoded = any(
        str(item.get("predicate") or "").strip()
        for item in formulas
        if isinstance(item, Mapping)
    )
    decompiled = str(row.get("decompiled") or "").strip()
    compiler_ok = (row.get("agrees") is True or row.get("compiled") is True) and bool(decompiled)
    alignment = result_alignment(row)
    cross_entropy = alignment["cross_entropy_loss"]
    matched = (
        compiler_ok
        and alignment["formula_matches"]
        and float(alignment["cosine_similarity"]) >= MIN_COSINE_SIMILARITY
        and cross_entropy is not None
        and float(cross_entropy) <= RESULT_CROSS_ENTROPY_LIMIT
    )
    if encoded and matched:
        return "agree"
    if encoded and not matched:
        return "disagree"
    if compiler_ok:
        return "compiler_only"
    return "unscored"


def consensus_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Agreement rate over spans the autoencoder encoded."""

    counts = {"agree": 0, "disagree": 0, "compiler_only": 0, "unscored": 0}
    for row in rows:
        label = str((row.get("census") or {}).get("consensus") or encoding_consensus(row))
        if label not in counts:
            label = "unscored"
        counts[label] += 1
    encoded = counts["agree"] + counts["disagree"]
    rate = (counts["agree"] / encoded) if encoded else None
    return {
        "admitted": False,
        "agree": counts["agree"],
        "agreement_rate": rate,
        "compiler_only": counts["compiler_only"],
        "disagree": counts["disagree"],
        "encoded": encoded,
        "formalized": False,
        "unscored": counts["unscored"],
    }


def decide_span(row: Mapping[str, Any], *, lake_ok: bool | None = None) -> dict[str, Any]:
    """Record agreement, a compiler goal, or an autoencoder training trigger."""

    item = dict(row)
    repair = dict(item.get("repair") or {})
    decoded = str((repair.get("autoencoder") or {}).get("decoded_text") or item.get("text") or "")
    captured = dict(repair.get("autoencoder") or {})
    cosine_loss = _loss(item.get("cosine_loss"))
    if cosine_loss is None:
        cosine_loss = _loss(captured.get("cosine_loss"))
    similarity = _loss(item.get("cosine_similarity"))
    if similarity is None:
        similarity = _loss(captured.get("cosine_similarity"))
    if similarity is None and cosine_loss is not None:
        similarity = 1.0 - cosine_loss
    reconstruction = _loss(item.get("reconstruction_loss"))
    if reconstruction is None:
        reconstruction = _loss(captured.get("reconstruction_loss"))
    compression = _loss(item.get("ir_compression_loss"))
    if compression is None:
        compression = _loss(captured.get("ir_compression_loss"))
    cross_entropy = _loss(item.get("cross_entropy_loss"))
    if cross_entropy is None:
        cross_entropy = _loss(captured.get("cross_entropy_loss"))
    view_cross_entropy = _loss(item.get("view_cross_entropy_loss"))
    if view_cross_entropy is None:
        view_cross_entropy = _loss(captured.get("view_cross_entropy_loss"))
    compiler_ok = item.get("agrees") is True and bool(str(item.get("decompiled") or "").strip())
    losses_high = _scores_need_training(
        {
            "cosine_similarity": similarity,
            "cross_entropy_loss": cross_entropy,
            "ir_compression_loss": compression,
            "reconstruction_loss": reconstruction,
            "view_cross_entropy_loss": view_cross_entropy,
        }
    )
    train = lake_ok is False or losses_high
    lake_accepts = True if lake_ok is None else lake_ok is True
    agree = compiler_ok and bool(decoded.strip()) and lake_accepts and not losses_high
    census = {
        "admitted": False,
        "agree": agree,
        "consensus": encoding_consensus(item),
        "cosine_loss": cosine_loss,
        "cosine_similarity": similarity,
        "cross_entropy_loss": cross_entropy,
        "ir_compression_loss": compression,
        "reconstruction_loss": reconstruction,
        "view_cross_entropy_loss": view_cross_entropy,
        "formalized": False,
        "lake_ok": lake_ok,
        "train": train,
        "work_kind": "compiler_decompiler_edit" if not agree else "",
    }
    item["census"] = census
    if isinstance(item.get("repair"), dict):
        item["repair"] = {**item["repair"], "census": census}
    return item


class LearningRateSchedule:
    """Shrink the step when the holdout fails to improve. Grow it when the holdout improves."""

    def __init__(
        self,
        initial: float = INITIAL_LEARNING_RATE,
        floor: float = MIN_LEARNING_RATE,
        ceiling: float = MAX_LEARNING_RATE,
        decay: float = 0.5,
        growth: float = 1.1,
    ) -> None:
        self.rate = float(initial)
        self.floor = float(floor)
        self.ceiling = float(ceiling)
        self.decay = float(decay)
        self.growth = float(growth)
        self.history = [self.rate]

    def step(self, *, improved: bool) -> float:
        if improved:
            self.rate = min(self.ceiling, self.rate * self.growth)
        else:
            self.rate = max(self.floor, self.rate * self.decay)
        self.history.append(self.rate)
        return self.rate


def _movement(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    checks = (
        ("cosine_similarity", True),
        ("reconstruction_loss", False),
        ("ir_compression_loss", False),
    )
    better = False
    worse = False
    for key, higher_is_better in checks:
        left = _loss(before.get(key))
        right = _loss(after.get(key))
        if left is None or right is None or abs(right - left) <= 1e-9:
            continue
        improved = right > left if higher_is_better else right < left
        if improved:
            better = True
        else:
            worse = True
    if better and not worse:
        return "better"
    if worse:
        return "worse"
    return "plateau"


def split_train_holdout(
    rows: Sequence[Mapping[str, Any]],
    *,
    holdout_fraction: float = 0.25,
    seed: int = 0,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Shuffle a draw. The holdout ids are never returned in the training list."""

    import random

    usable = [
        {
            "legal_id": str(row.get("legal_id") or ""),
            "source_span_id": str(row.get("source_span_id") or ""),
            "text": str(row.get("text") or row.get("source_text") or ""),
        }
        for row in rows
        if str(row.get("text") or row.get("source_text") or "").strip()
        and str(row.get("source_span_id") or "")
    ]
    if len(usable) < 2:
        raise ValueError("a train/holdout split needs at least two span texts")
    shuffled = list(usable)
    random.Random(int(seed)).shuffle(shuffled)
    holdout_count = max(1, int(round(len(shuffled) * float(holdout_fraction))))
    if holdout_count >= len(shuffled):
        holdout_count = len(shuffled) // 2 or 1
    holdout = shuffled[:holdout_count]
    train = shuffled[holdout_count:]
    return holdout, train


def sample_federal_spans(
    cache_path: str = FEDERAL_SPAN_CACHE,
    *,
    count: int = 32,
    seed: int = 0,
    status: str | None = None,
) -> list[dict[str, str]]:
    """Read a seeded random sample. Opens the catalog read-only and does not write it."""

    import duckdb

    try:
        connection = duckdb.connect(str(cache_path), read_only=True)
    except Exception as exc:
        raise RuntimeError(
            "the federal span cache is not readable; refusing to open it as a second writer"
        ) from exc
    minimum = 12 if status == "gap" else 40
    where = "length(coalesce(source_text, '')) BETWEEN ? AND 800"
    parameters: list[Any] = [minimum]
    if status:
        where += " AND status = ? AND admitted = FALSE"
        parameters.append(status)
    parameters.extend([str(int(seed)), max(2, int(count))])
    try:
        found = connection.execute(
            f"""
            SELECT source_span_id, legal_id, source_text
            FROM span_cache
            WHERE {where}
            ORDER BY hash(source_span_id || ?)
            LIMIT ?
            """,
            parameters,
        ).fetchall()
    finally:
        connection.close()
    return [
        {"legal_id": str(row[1] or ""), "source_span_id": str(row[0]), "text": str(row[2] or "")}
        for row in found
    ]


def annotate_compiled_batch(
    rows: Sequence[Mapping[str, Any]],
    *,
    lake_check: Callable[[str], Mapping[str, Any]] | None = None,
    lake_limit: int = 4,
) -> list[dict[str, Any]]:
    """Add census fields. Lake runs only for rows the compiler rejected, up to a cap."""

    from .lake_probe import lake_check as default_lake_check
    from .lake_probe import pattern_from_fixture, pattern_from_rule, render_fixture, render_norm

    check = lake_check or default_lake_check
    remaining = max(0, int(lake_limit))
    annotated: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        lake_ok: bool | None = None
        if item.get("agrees") is not True and remaining > 0:
            formulas = list(((item.get("repair") or {}).get("autoencoder") or {}).get("formulas") or [])
            source_parts: list[str] = []
            saw_formula = False
            for formula in formulas[:4]:
                if not isinstance(formula, Mapping):
                    continue
                arguments = [str(part) for part in formula.get("arguments") or []]
                actor = next((part.split(":", 1)[1] for part in arguments if part.startswith("actor:")), "")
                scope = next((part.split(":", 1)[1] for part in arguments if part.startswith("scope:")), "")
                rule = {
                    "action": str(formula.get("predicate") or ""),
                    "actor": actor,
                    "modality": str(formula.get("op") or ""),
                    "object": scope,
                }
                duty = pattern_from_rule(rule)
                fixture = pattern_from_fixture(rule)
                if duty is not None:
                    source_parts.append(render_norm(duty, suffix=str(len(source_parts))))
                    saw_formula = True
                elif fixture is not None:
                    source_parts.append(render_fixture(fixture, suffix=str(len(source_parts))))
                    saw_formula = True
            if saw_formula:
                receipt = dict(check("\n".join(source_parts)) or {})
                lake_ok = receipt.get("lake_ok") is True
                remaining -= 1
            else:
                lake_ok = False
        annotated.append(decide_span(item, lake_ok=lake_ok))
    return annotated


def train_until_canary_improves(
    model: Any | None = None,
    *,
    rounds: int = 2,
    spans: Sequence[Mapping[str, Any]] | None = None,
    cache_path: str = FEDERAL_SPAN_CACHE,
    seed: int = 0,
    draw: int = 32,
    holdout_fraction: float = 0.25,
) -> dict[str, Any]:
    """Train on a random federal draw. Scores are measured only on the held-out part."""

    if spans is None:
        spans = sample_federal_spans(cache_path, count=draw, seed=seed, status="gap")
    holdout, train = split_train_holdout(spans, holdout_fraction=holdout_fraction, seed=seed)
    schedule = LearningRateSchedule()
    holdout_texts = [row["text"] for row in holdout]
    train_texts = [row["text"] for row in train]

    if model is not None and hasattr(model, "measure_canary") and hasattr(model, "fit_train"):

        def measure() -> dict[str, float]:
            return dict(model.measure_canary(holdout_texts))

        def fit(rate: float) -> None:
            model.fit_train(train_texts, rate)
    else:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
            AdaptiveModalAutoencoder,
        )

        if model is None:
            model = AdaptiveModalAutoencoder()
        from ipfs_datasets_py.logic.autoformal.family_supervision import TRAINING_BRIDGE_NAMES

        def samples(texts: Sequence[str]) -> list[Any]:
            return [build_us_code_sample(title="18", section="1", text=text) for text in texts]

        def measure() -> dict[str, float]:
            evaluation = model.evaluate(
                samples(holdout_texts),
                legal_ir_bridge_names=TRAINING_BRIDGE_NAMES,
                legal_ir_evaluate_provers=False,
                use_sample_memory=False,
            )
            cosine_loss = float(evaluation.cosine_loss)
            from ipfs_datasets_py.logic.modal.codec import decode_modal_ir_text
            from ipfs_datasets_py.logic.modal.ir_symbol_catalog import ir_compression_loss

            built = samples(holdout_texts)
            compression_values = [
                ir_compression_loss(
                    str(getattr(sample, "text", "") or ""),
                    decode_modal_ir_text(sample.modal_ir),
                )[0]
                for sample in built
                if getattr(sample, "modal_ir", None) is not None
            ]
            compression = (
                sum(compression_values) / len(compression_values) if compression_values else 0.0
            )
            return {
                "cosine_loss": cosine_loss,
                "cosine_similarity": 1.0 - cosine_loss,
                "cross_entropy_loss": float(evaluation.cross_entropy_loss),
                "ir_compression_loss": compression,
                "reconstruction_loss": float(evaluation.reconstruction_loss),
            }

        def fit(rate: float) -> None:
            model.train_generalizable_projection(
                samples(train_texts),
                validation_samples=(),
                legal_ir_bridge_names=TRAINING_BRIDGE_NAMES,
                legal_ir_evaluate_provers=False,
                epochs=1,
                learning_rate=rate,
                projection_max_update_families=len(TRAINING_BRIDGE_NAMES),
            )

    before = measure()
    improved = False
    trained_rounds = 0
    after = dict(before)
    rate = schedule.rate

    def _scored(scores: Mapping[str, Any], round_index: int, learning_rate: float, *, movement: str = "") -> dict[str, Any]:
        threshold = threshold_at_round(round_index)
        return {
            "below_threshold": metric_misses(scores, threshold),
            "learning_rate": learning_rate,
            "movement": movement,
            "scores": dict(scores),
            "threshold": threshold,
        }

    history = [_scored(before, 0, rate)]
    if _scores_need_training(before):
        for _ in range(max(1, int(rounds))):
            fit(rate)
            trained_rounds += 1
            previous = dict(after)
            after = measure()
            movement = _movement(previous, after)
            history.append(_scored(after, trained_rounds, rate, movement=movement))
            improved = movement == "better" or (
                movement != "worse"
                and (
                    float(after.get("cosine_similarity") or 0.0) > float(before.get("cosine_similarity") or 0.0)
                    or float(after.get("reconstruction_loss") or 0.0) < float(before.get("reconstruction_loss") or 0.0)
                    or float(after.get("cross_entropy_loss") or 0.0) < float(before.get("cross_entropy_loss") or 0.0)
                )
            )
            if not _scores_need_training(after):
                break
            rate = schedule.step(improved=movement == "better")
    holdout_ids = [row["source_span_id"] for row in holdout]
    train_ids = [row["source_span_id"] for row in train]
    weight_update = {"delta_count": 0, "uploaded": False, "admitted": False}
    if model is not None and not hasattr(model, "fit_train"):
        try:
            from .autoencoder_weight_store import publish_model_update

            weight_update = publish_model_update(model, improved=improved)
        except Exception:
            weight_update = {"delta_count": 0, "uploaded": False, "admitted": False, "error": "store_failed"}
    from ipfs_datasets_py.logic.autoformal.family_supervision import FAMILY_NAMES, TRAINING_BRIDGE_NAMES

    final_threshold = threshold_at_round(trained_rounds)
    return {
        "admitted": False,
        "after": after,
        "before": before,
        "below_threshold": metric_misses(after, final_threshold),
        "formalized": False,
        "history": history,
        "holdout_ids": holdout_ids,
        "improved": improved,
        "learning_rates": list(schedule.history),
        "rounds": trained_rounds,
        "seed": int(seed),
        "threshold": final_threshold,
        "train_ids": train_ids,
        "trained": trained_rounds > 0,
        "training_bridges": list(TRAINING_BRIDGE_NAMES),
        "training_families": list(FAMILY_NAMES),
        "weight_update": weight_update,
    }
