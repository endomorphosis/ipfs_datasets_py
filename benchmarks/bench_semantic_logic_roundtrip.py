#!/usr/bin/env python3
"""Benchmark source-withheld legal text <-> logic round trips.

This pilot measures the full path requested by the semantic-logic work:

    source text T0 -> logic L1 -> source-withheld text T1 -> logic L2

It deliberately reports forward fidelity (gold vs L1), cycle consistency
(L1 vs L2), and end-to-end fidelity (gold vs L2) separately.  A translator
therefore cannot pass merely by being consistently wrong in both directions.

The live lanes reuse the already-running, identity-pinned Leanstral service.
SyMAI is recorded as a distinct prompting/router method, but not as an
independent model: it resolves to that same one-slot Leanstral service.
Hammer/cvc5 and Lean are validators only; they never supply semantic gold.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.logic_pipeline.content_addressing import (  # noqa: E402
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
)


SCHEMA_VERSION = "ipfs-datasets.semantic-logic-roundtrip-benchmark.v1"
RULE_FIELDS = (
    "modality",
    "actor",
    "action",
    "object",
    "conditions",
    "exceptions",
    "temporal",
)
LIST_FIELDS = ("conditions", "exceptions", "temporal")
MODALITIES = frozenset({"O", "P", "F"})
TOKEN_RE = re.compile(r"[a-z0-9]+")
DEFAULT_FIXTURE = (
    REPO_ROOT / "tests/fixtures/semantic_roundtrip/pilot_cases.json"
)
DEFAULT_ENDPOINT = "http://127.0.0.1:8080/v1"
DEFAULT_MODEL = (
    "Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4:NVFP4"
)


class BenchmarkError(RuntimeError):
    """Raised for a benchmark contract or execution failure."""


@dataclass
class TimedResult:
    value: Any
    elapsed_seconds: float
    metadata: dict[str, Any]


def _canonical(value: Any) -> str:
    return canonical_dag_json_bytes(value).decode("utf-8")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item) for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_json_safe(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _json_safe(asdict(value))
    return value


def _legacy_sha(value: Any) -> str:
    """Compatibility digest for repository APIs that still require SHA-256."""

    return hashlib.sha256(canonical_dag_json_bytes(value)).hexdigest()


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _tokens(value: Any) -> tuple[str, ...]:
    words = TOKEN_RE.findall(_clean_text(value).lower().replace("_", " "))
    normalized: list[str] = []
    for word in words:
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        normalized.append(word)
    return tuple(normalized)


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        result: list[str] = []
        for key, item in value.items():
            result.append(str(key))
            result.extend(_flatten_strings(item))
        return result
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        result = []
        for item in value:
            result.extend(_flatten_strings(item))
        return result
    if value is None:
        return []
    return [str(value)]


def _jaccard(left: Any, right: Any) -> float:
    a, b = set(_tokens(left)), set(_tokens(right))
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _allowed(case: Mapping[str, Any], group: str) -> list[str]:
    raw = case.get("allowed_atoms", {}).get(group, [])
    return [str(item) for item in raw if isinstance(item, str)]


def _best_atom(
    value: Any,
    candidates: Sequence[str],
    *,
    allow_empty: bool = False,
    threshold: float = 0.12,
) -> str:
    pieces = _flatten_strings(value)
    text = " ".join(pieces)
    if not _clean_text(text):
        return "" if allow_empty else ""
    scored = sorted(
        (
            (
                max(
                    [_jaccard(text, candidate)]
                    + [_jaccard(piece, candidate) for piece in pieces]
                ),
                candidate,
            )
            for candidate in candidates
        ),
        key=lambda item: (-item[0], item[1]),
    )
    if not scored or scored[0][0] < threshold:
        return ""
    return scored[0][1]


def _map_many(value: Any, candidates: Sequence[str]) -> list[str]:
    values: list[Any]
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        values = list(value)
    elif value in (None, "", []):
        values = []
    else:
        values = [value]
    mapped = {
        atom
        for item in values
        if (atom := _best_atom(item, candidates))
    }
    return sorted(mapped)


def _empty_rule() -> dict[str, Any]:
    return {
        "modality": "O",
        "actor": "",
        "action": "",
        "object": "",
        "conditions": [],
        "exceptions": [],
        "temporal": [],
    }


def validate_semantic_ir(
    value: Any,
    case: Mapping[str, Any],
    *,
    strict_vocabulary: bool = True,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"rules"}:
        raise BenchmarkError("semantic IR must contain exactly the rules key")
    raw_rules = value.get("rules")
    if not isinstance(raw_rules, list) or len(raw_rules) > 16:
        raise BenchmarkError("semantic IR rules must be an array of at most 16")
    vocab = {
        "actor": set(_allowed(case, "actors")),
        "action": set(_allowed(case, "actions")),
        "object": set(_allowed(case, "objects")) | {""},
        "qualifier": set(_allowed(case, "qualifiers")),
    }
    rules: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_rules):
        if not isinstance(raw, Mapping) or set(raw) != set(RULE_FIELDS):
            raise BenchmarkError(
                f"rule {index} must contain exactly {', '.join(RULE_FIELDS)}"
            )
        modality = str(raw["modality"])
        if modality not in MODALITIES:
            raise BenchmarkError(f"rule {index} has invalid modality")
        rule = {
            "modality": modality,
            "actor": _clean_text(raw["actor"]),
            "action": _clean_text(raw["action"]),
            "object": _clean_text(raw["object"]),
        }
        for field in LIST_FIELDS:
            items = raw[field]
            if (
                not isinstance(items, list)
                or len(items) > 8
                or not all(isinstance(item, str) for item in items)
            ):
                raise BenchmarkError(
                    f"rule {index}.{field} must be a bounded string array"
                )
            rule[field] = sorted(
                {_clean_text(item) for item in items if _clean_text(item)}
            )
        if strict_vocabulary:
            for field in ("actor", "action", "object"):
                if rule[field] not in vocab[field]:
                    raise BenchmarkError(
                        f"rule {index}.{field} is outside the case vocabulary"
                    )
            for field in LIST_FIELDS:
                unknown = set(rule[field]) - vocab["qualifier"]
                if unknown:
                    raise BenchmarkError(
                        f"rule {index}.{field} contains unknown atoms"
                    )
        rules.append(rule)
    rules.sort(key=_rule_key)
    return {"rules": rules}


def _rule_key(rule: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(rule.get("modality") or ""),
        str(rule.get("actor") or ""),
        str(rule.get("action") or ""),
        str(rule.get("object") or ""),
        *(tuple(rule.get(field) or ()) for field in LIST_FIELDS),
    )


def _set_score(left: Any, right: Any) -> float:
    a, b = set(left or ()), set(right or ())
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def rule_similarity(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    weights = {
        "modality": 0.25,
        "actor": 0.15,
        "action": 0.20,
        "object": 0.10,
        "conditions": 0.10,
        "exceptions": 0.10,
        "temporal": 0.10,
    }
    score = 0.0
    for field, weight in weights.items():
        if field in LIST_FIELDS:
            part = _set_score(left.get(field), right.get(field))
        else:
            part = float(left.get(field) == right.get(field))
        score += weight * part
    return round(score, 9)


def _maximum_weight_assignment(
    weights: Sequence[Sequence[float]],
) -> list[tuple[int, int]]:
    """Return an exact maximum-weight one-to-one assignment.

    The implementation is the rectangular Hungarian algorithm.  A greedy
    highest-pair-first matcher can choose a locally attractive pair that
    lowers the total semantic score of the remaining rules.
    """

    if not weights or not weights[0]:
        return []
    row_count = len(weights)
    column_count = len(weights[0])
    if any(len(row) != column_count for row in weights):
        raise BenchmarkError("assignment matrix must be rectangular")

    transposed = row_count > column_count
    matrix = (
        [
            [float(weights[row][column]) for row in range(row_count)]
            for column in range(column_count)
        ]
        if transposed
        else [[float(value) for value in row] for row in weights]
    )
    n = len(matrix)
    m = len(matrix[0])
    potentials_rows = [0.0] * (n + 1)
    potentials_columns = [0.0] * (m + 1)
    matched_row = [0] * (m + 1)
    predecessor = [0] * (m + 1)

    for row in range(1, n + 1):
        matched_row[0] = row
        column0 = 0
        minimum = [float("inf")] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[column0] = True
            current_row = matched_row[column0]
            delta = float("inf")
            next_column = 0
            for column in range(1, m + 1):
                if used[column]:
                    continue
                # Hungarian solves minimum cost; negate weights to maximize.
                reduced = (
                    -matrix[current_row - 1][column - 1]
                    - potentials_rows[current_row]
                    - potentials_columns[column]
                )
                if reduced < minimum[column]:
                    minimum[column] = reduced
                    predecessor[column] = column0
                if minimum[column] < delta:
                    delta = minimum[column]
                    next_column = column
            for column in range(m + 1):
                if used[column]:
                    potentials_rows[matched_row[column]] += delta
                    potentials_columns[column] -= delta
                else:
                    minimum[column] -= delta
            column0 = next_column
            if matched_row[column0] == 0:
                break
        while True:
            previous = predecessor[column0]
            matched_row[column0] = matched_row[previous]
            column0 = previous
            if column0 == 0:
                break

    assignment: list[tuple[int, int]] = []
    for column in range(1, m + 1):
        if matched_row[column] == 0:
            continue
        row_index = matched_row[column] - 1
        column_index = column - 1
        assignment.append(
            (column_index, row_index)
            if transposed
            else (row_index, column_index)
        )
    return sorted(assignment)


def compare_semantic_ir(
    reference: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    left = list(reference.get("rules") or [])
    right = list(candidate.get("rules") or [])
    weights = [
        [
            rule_similarity(left_rule, right_rule)
            for right_rule in right
        ]
        for left_rule in left
    ]
    pairs = [
        (weights[left_index][right_index], left_index, right_index)
        for left_index, right_index in _maximum_weight_assignment(weights)
    ]
    matches: list[dict[str, Any]] = []
    for score, li, ri in sorted(
        pairs, key=lambda item: (item[1], item[2])
    ):
        matches.append(
            {
                "reference_index": li,
                "candidate_index": ri,
                "score": score,
                "exact": left[li] == right[ri],
                "modality_preserved": (
                    left[li].get("modality") == right[ri].get("modality")
                ),
                "condition_preserved": (
                    set(left[li].get("conditions") or ())
                    == set(right[ri].get("conditions") or ())
                ),
                "exception_preserved": (
                    set(left[li].get("exceptions") or ())
                    == set(right[ri].get("exceptions") or ())
                ),
                "temporal_preserved": (
                    set(left[li].get("temporal") or ())
                    == set(right[ri].get("temporal") or ())
                ),
            }
        )
    denominator = max(len(left), len(right), 1)
    semantic_score = sum(item["score"] for item in matches) / denominator
    exact_count = sum(bool(item["exact"]) for item in matches)
    exact_precision = exact_count / len(right) if right else 0.0
    exact_recall = exact_count / len(left) if left else 0.0
    exact_f1 = (
        2 * exact_precision * exact_recall / (exact_precision + exact_recall)
        if exact_precision + exact_recall
        else 0.0
    )
    nonvacuous = bool(left) and bool(right)
    return {
        "reference_rule_count": len(left),
        "candidate_rule_count": len(right),
        "matched_rule_count": len(matches),
        "semantic_score": round(semantic_score, 9),
        "semantic_loss": round(1.0 - semantic_score, 9),
        "exact_rule_f1": round(exact_f1, 9),
        "exact_ir": left == right,
        "nonvacuous": nonvacuous,
        "exact_ir_nonvacuous": bool(nonvacuous and left == right),
        "missing_rule_count": max(0, len(left) - len(matches)),
        "extra_rule_count": max(0, len(right) - len(matches)),
        "matches": matches,
        "facet_survival": {
            field: round(
                (
                    sum(
                        bool(item[f"{field[:-1] if field.endswith('s') else field}_preserved"])
                        for item in matches
                    )
                    / len(matches)
                )
                if matches
                else 0.0,
                9,
            )
            for field in ("modality", "conditions", "exceptions", "temporal")
        },
    }


def source_copy_metrics(source: str, reconstruction: str) -> dict[str, Any]:
    source_tokens = _tokens(source)
    output_tokens = _tokens(reconstruction)

    def ngrams(tokens: tuple[str, ...], width: int) -> Counter[tuple[str, ...]]:
        return Counter(
            tuple(tokens[index : index + width])
            for index in range(max(0, len(tokens) - width + 1))
        )

    source_ngrams = ngrams(source_tokens, 8)
    output_ngrams = ngrams(output_tokens, 8)
    copied = sum((source_ngrams & output_ngrams).values())
    output_total = sum(output_ngrams.values())
    source_total = sum(source_ngrams.values())
    exact = bool(
        source_tokens and output_tokens and source_tokens == output_tokens
    )
    precision = copied / output_total if output_total else 0.0
    recall = copied / source_total if source_total else 0.0
    return {
        "exact_normalized_copy": exact,
        "source_token_count": len(source_tokens),
        "reconstruction_token_count": len(output_tokens),
        "shared_8gram_count": copied,
        "shared_8gram_precision": round(precision, 9),
        "shared_8gram_recall": round(recall, 9),
        "copy_risk": exact or precision >= 0.80,
    }


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise BenchmarkError("pilot fixture must be a nonempty JSON array")
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise BenchmarkError("each pilot case must be an object")
        case_id = str(raw.get("id") or "")
        if not case_id or case_id in seen:
            raise BenchmarkError("case ids must be nonempty and unique")
        seen.add(case_id)
        if not _clean_text(raw.get("source_text")):
            raise BenchmarkError(f"{case_id} has no source text")
        raw["gold_ir"] = validate_semantic_ir(raw.get("gold_ir"), raw)
        raw["source_text_cid"] = cid_for_bytes(
            raw["source_text"].encode("utf-8")
        )
        raw["gold_ir_cid"] = cid_for_dag_json(raw["gold_ir"])
        result.append(raw)
    return result


def _modality_from_text(value: Any) -> str:
    text = _clean_text(value).lower()
    if (
        text in {"f", "prohibition", "forbidden"}
        or "prohibit" in text
        or "shall not" in text
        or "must not" in text
    ):
        return "F"
    if text in {"p", "permission", "permitted"} or "permission" in text:
        return "P"
    return "O"


def _qualifier_values(records: Any) -> list[str]:
    values: list[str] = []
    if not isinstance(records, Sequence) or isinstance(
        records, (str, bytes, bytearray)
    ):
        return values
    for record in records:
        if isinstance(record, Mapping):
            for key in (
                "scope_atom",
                "normalized_text",
                "raw_text",
                "value",
                "anchor",
                "anchor_event",
                "duration",
                "start",
                "end",
            ):
                if record.get(key):
                    values.append(str(record[key]))
        elif record:
            values.append(str(record))
    return values


def project_decompiler_record(
    record: Mapping[str, Any], case: Mapping[str, Any]
) -> dict[str, Any]:
    actors = _allowed(case, "actors")
    actions = _allowed(case, "actions")
    objects = _allowed(case, "objects")
    qualifiers = _allowed(case, "qualifiers")
    rules: list[dict[str, Any]] = []
    for formula in record.get("formulas") or []:
        if not isinstance(formula, Mapping):
            continue
        predicate = formula.get("predicate")
        if (
            isinstance(predicate, Mapping)
            and predicate.get("role") not in {None, "", "clause"}
        ):
            # The modal compiler also materializes if/unless cues as helper
            # formulas. They are guards, not independent legal norms.
            continue
        structure = formula.get("reconstructed_structure")
        structure = structure if isinstance(structure, Mapping) else {}
        roles = structure.get("roles")
        roles = roles if isinstance(roles, Mapping) else {}
        modality = formula.get("modality")
        modality = modality if isinstance(modality, Mapping) else {}
        actor = _best_atom(roles.get("actor"), actors)
        action = _best_atom(
            [roles.get("action"), predicate, formula.get("arguments")],
            actions,
        )
        obj = _best_atom(roles.get("object"), objects, allow_empty=True)
        conditions = _map_many(
            formula.get("conditions") or (), qualifiers
        )
        exceptions = _map_many(
            formula.get("exceptions") or (), qualifiers
        )
        temporal = _map_many(
            structure.get("temporal_anchors") or (), qualifiers
        )
        if not actor or not action:
            continue
        rules.append(
            {
                "modality": _modality_from_text(
                    [
                        formula.get("operator"),
                        modality.get("force"),
                        modality.get("label"),
                    ]
                ),
                "actor": actor,
                "action": action,
                "object": obj,
                "conditions": conditions,
                "exceptions": exceptions,
                "temporal": temporal,
            }
        )
    return validate_semantic_ir(
        {"rules": rules}, case, strict_vocabulary=True
    )


def _compact_modal_realization(record: Mapping[str, Any]) -> str:
    sentences: list[str] = []
    for formula in record.get("formulas") or []:
        if not isinstance(formula, Mapping):
            continue
        predicate = formula.get("predicate")
        if (
            isinstance(predicate, Mapping)
            and predicate.get("role") not in {None, "", "clause"}
        ):
            continue
        structure = formula.get("reconstructed_structure")
        structure = structure if isinstance(structure, Mapping) else {}
        roles = structure.get("roles")
        roles = roles if isinstance(roles, Mapping) else {}
        actor = _clean_text(roles.get("actor")).replace("_", " ")
        action = _clean_text(roles.get("action")).replace("_", " ")
        obj = _clean_text(roles.get("object")).replace("_", " ")
        modality = formula.get("modality")
        modality = modality if isinstance(modality, Mapping) else {}
        symbol = _modality_from_text(
            [
                formula.get("operator"),
                modality.get("force"),
                modality.get("label"),
            ]
        )
        modal = {"O": "shall", "P": "may", "F": "shall not"}[symbol]
        if not actor or not action:
            continue
        sentence = f"{actor} {modal} {action}"
        if obj and set(_tokens(obj)) - set(_tokens(action)):
            sentence += f" concerning {obj}"
        conditions = _qualifier_values(formula.get("conditions") or ())
        exceptions = _qualifier_values(formula.get("exceptions") or ())
        temporal = _qualifier_values(
            structure.get("temporal_anchors") or ()
        )
        if conditions:
            sentence += " if " + " and ".join(
                value.replace("_", " ") for value in conditions
            )
        if temporal:
            sentence += " " + " and ".join(
                value.replace("_", " ") for value in temporal
            )
        if exceptions:
            sentence += " unless " + " or ".join(
                value.replace("_", " ") for value in exceptions
            )
        sentences.append(sentence.strip() + ".")
    return " ".join(sentences)


def run_modal_codec(
    case: Mapping[str, Any], *, backend: str
) -> dict[str, Any]:
    from ipfs_datasets_py.logic.modal.codec import (
        DeterministicModalLogicCodec,
        ModalLogicCodecConfig,
    )
    from ipfs_datasets_py.logic.modal.decompiler_repairs import (
        repair_decompiler_round_trip,
    )

    started = time.perf_counter()
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend=backend)
    )
    encoded = codec.encode(
        str(case["source_text"]),
        document_id=str(case["id"]),
        source="semantic_roundtrip_pilot",
    )
    forward_seconds = time.perf_counter() - started
    record = repair_decompiler_round_trip(encoded.modal_ir)
    l1 = project_decompiler_record(record, case)
    realization = _compact_modal_realization(record)
    recompile_started = time.perf_counter()
    if realization:
        recompiled = codec.encode(
            realization,
            document_id=f"{case['id']}:roundtrip",
            source="source_withheld_modal_realization",
        )
        record2 = repair_decompiler_round_trip(recompiled.modal_ir)
        l2 = project_decompiler_record(record2, case)
        recompile_seconds = time.perf_counter() - recompile_started
        l2_codec_losses = dict(recompiled.losses)
    else:
        l2 = {"rules": []}
        recompile_seconds = 0.0
        l2_codec_losses = {}
    return {
        "status": "success",
        "translator": f"modal_codec_{backend}",
        "source_withheld_from_realizer": True,
        "l1": l1,
        "l1_cid": cid_for_dag_json(l1),
        "realization": realization,
        "realization_cid": cid_for_bytes(realization.encode("utf-8")),
        "l2": l2,
        "l2_cid": cid_for_dag_json(l2),
        "forward_vs_gold": compare_semantic_ir(case["gold_ir"], l1),
        "cycle_l1_vs_l2": compare_semantic_ir(l1, l2),
        "end_to_end_vs_gold": compare_semantic_ir(case["gold_ir"], l2),
        "source_copy": source_copy_metrics(
            str(case["source_text"]), realization
        ),
        "codec_losses_l1": dict(encoded.losses),
        "codec_losses_l2": l2_codec_losses,
        "diagnostic_structural_text": {
            "cid": cid_for_bytes(
                str(
                    encoded.metadata.get(
                        "modal_decompiler_structural_text", ""
                    )
                ).encode("utf-8")
            ),
            "bytes": len(
                str(
                    encoded.metadata.get(
                        "modal_decompiler_structural_text", ""
                    )
                ).encode("utf-8")
            ),
            "readable_realization_used": False,
        },
        "timing": {
            "forward_seconds": round(forward_seconds, 9),
            "recompile_seconds": round(recompile_seconds, 9),
            "total_seconds": round(
                forward_seconds + recompile_seconds, 9
            ),
        },
    }


def _project_legal_norms(
    norms: Sequence[Any], case: Mapping[str, Any]
) -> dict[str, Any]:
    actors = _allowed(case, "actors")
    actions = _allowed(case, "actions")
    objects = _allowed(case, "objects")
    qualifiers = _allowed(case, "qualifiers")
    rules: list[dict[str, Any]] = []
    for norm in norms:
        data = norm.to_dict()
        actor = _best_atom(data.get("actor"), actors)
        action = _best_atom(
            [data.get("action"), data.get("action_verb")], actions
        )
        obj = _best_atom(
            data.get("action_object"), objects, allow_empty=True
        )
        if not actor or not action:
            continue
        rules.append(
            {
                "modality": _modality_from_text(
                    [data.get("modality"), data.get("norm_type")]
                ),
                "actor": actor,
                "action": action,
                "object": obj,
                "conditions": _map_many(
                    data.get("conditions") or (), qualifiers
                ),
                "exceptions": _map_many(
                    data.get("exceptions") or (), qualifiers
                ),
                "temporal": _map_many(
                    data.get("temporal_constraints") or (), qualifiers
                ),
            }
        )
    return validate_semantic_ir(
        {"rules": rules}, case, strict_vocabulary=True
    )


def run_deontic_codec(case: Mapping[str, Any]) -> dict[str, Any]:
    from ipfs_datasets_py.logic.deontic.converter import DeonticConverter
    from ipfs_datasets_py.logic.deontic.decoder import decode_legal_norm_ir
    from ipfs_datasets_py.logic.deontic.ir import LegalNormIR

    converter = DeonticConverter(
        use_cache=False,
        use_ipfs=False,
        use_ml=False,
        enable_monitoring=False,
        document_type="general",
    )
    started = time.perf_counter()
    converted = converter.convert(
        str(case["source_text"]), use_cache=False
    )
    elements = (
        list(getattr(converted.output, "parser_elements", ()) or ())
        if converted.output is not None
        else []
    )
    norms = [LegalNormIR.from_parser_element(element) for element in elements]
    forward_seconds = time.perf_counter() - started
    l1 = _project_legal_norms(norms, case)
    realization = " ".join(
        decode_legal_norm_ir(norm).text for norm in norms
    )
    recompile_started = time.perf_counter()
    reconverted = converter.convert(realization, use_cache=False)
    elements2 = (
        list(getattr(reconverted.output, "parser_elements", ()) or ())
        if reconverted.output is not None
        else []
    )
    norms2 = [
        LegalNormIR.from_parser_element(element) for element in elements2
    ]
    l2 = _project_legal_norms(norms2, case)
    recompile_seconds = time.perf_counter() - recompile_started
    return {
        "status": "success",
        "translator": "typed_deontic_codec",
        "source_withheld_from_realizer": True,
        "coverage": {
            "parser_element_count": len(elements),
            "gold_rule_count": len(case["gold_ir"]["rules"]),
        },
        "l1": l1,
        "l1_cid": cid_for_dag_json(l1),
        "realization": realization,
        "realization_cid": cid_for_bytes(realization.encode("utf-8")),
        "l2": l2,
        "l2_cid": cid_for_dag_json(l2),
        "forward_vs_gold": compare_semantic_ir(case["gold_ir"], l1),
        "cycle_l1_vs_l2": compare_semantic_ir(l1, l2),
        "end_to_end_vs_gold": compare_semantic_ir(case["gold_ir"], l2),
        "source_copy": source_copy_metrics(
            str(case["source_text"]), realization
        ),
        "timing": {
            "forward_seconds": round(forward_seconds, 9),
            "recompile_seconds": round(recompile_seconds, 9),
            "total_seconds": round(
                forward_seconds + recompile_seconds, 9
            ),
        },
    }


def _condition_atoms(value: Any) -> list[str]:
    if value is None:
        return []
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    return _flatten_strings(value)


def _project_cnl_v2(ir: Any, case: Mapping[str, Any]) -> dict[str, Any]:
    actors = _allowed(case, "actors")
    actions = _allowed(case, "actions")
    objects = _allowed(case, "objects")
    qualifiers = _allowed(case, "qualifiers")
    rules: list[dict[str, Any]] = []
    for norm in ir.norms.values():
        frame = ir.frames[norm.target_frame_ref]
        actor_ref = frame.roles.get("agent", "")
        actor_entity = ir.entities.get(actor_ref)
        actor_label = (
            actor_entity.attrs.get("label", actor_ref)
            if actor_entity is not None
            else actor_ref
        )
        patient_ref = frame.roles.get("patient", "")
        patient = ir.entities.get(patient_ref)
        patient_label = (
            patient.attrs.get("label", patient_ref)
            if patient is not None
            else patient_ref
        )
        activation = (
            []
            if (
                norm.activation.atom is not None
                and norm.activation.atom.pred == "true"
            )
            else _condition_atoms(norm.activation)
        )
        temporal: list[Any] = []
        if norm.temporal_ref and norm.temporal_ref in ir.temporals:
            temporal = _condition_atoms(ir.temporals[norm.temporal_ref])
        actor = _best_atom(actor_label, actors)
        action = _best_atom(frame.predicate, actions)
        if not actor or not action:
            continue
        rules.append(
            {
                "modality": str(norm.op.value),
                "actor": actor,
                "action": action,
                "object": _best_atom(
                    patient_label, objects, allow_empty=True
                ),
                "conditions": _map_many(activation, qualifiers),
                "exceptions": _map_many(
                    [
                        item
                        for exception in norm.exceptions
                        for item in _condition_atoms(exception)
                    ],
                    qualifiers,
                ),
                "temporal": _map_many(temporal, qualifiers),
            }
        )
    return validate_semantic_ir(
        {"rules": rules}, case, strict_vocabulary=True
    )


def run_cnl_v2(case: Mapping[str, Any]) -> dict[str, Any]:
    from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_v2_blueprint import (
        generate_cnl_from_ir,
        parse_cnl_to_ir_with_diagnostics,
    )

    started = time.perf_counter()
    try:
        ir, diagnostics = parse_cnl_to_ir_with_diagnostics(
            str(case["source_text"]), jurisdiction="us/federal"
        )
    except Exception as exc:
        return {
            "status": "unsupported",
            "translator": "controlled_natural_language_v2",
            "reason": f"{type(exc).__name__}: {_clean_text(exc)[:300]}",
            "timing": {
                "total_seconds": round(time.perf_counter() - started, 9)
            },
        }
    forward_seconds = time.perf_counter() - started
    l1 = _project_cnl_v2(ir, case)
    sentences = [
        generate_cnl_from_ir(norm_ref, ir)
        for norm_ref in sorted(ir.norms)
    ]
    realization = " ".join(sentences)
    l2_rules: list[dict[str, Any]] = []
    recompile_started = time.perf_counter()
    roundtrip_diagnostics: list[dict[str, Any]] = []
    for sentence in sentences:
        try:
            parsed, diag = parse_cnl_to_ir_with_diagnostics(
                sentence, jurisdiction="us/federal"
            )
            l2_rules.extend(_project_cnl_v2(parsed, case)["rules"])
            roundtrip_diagnostics.append(diag)
        except Exception as exc:
            roundtrip_diagnostics.append(
                {"error": f"{type(exc).__name__}: {_clean_text(exc)[:300]}"}
            )
    l2 = validate_semantic_ir(
        {"rules": l2_rules}, case, strict_vocabulary=True
    )
    recompile_seconds = time.perf_counter() - recompile_started
    return {
        "status": "success",
        "translator": "controlled_natural_language_v2",
        "source_withheld_from_realizer": True,
        "coverage": {
            "norm_count": len(ir.norms),
            "rule_count": len(ir.rules),
            "gold_rule_count": len(case["gold_ir"]["rules"]),
        },
        "l1": l1,
        "l1_cid": cid_for_dag_json(l1),
        "realization": realization,
        "realization_cid": cid_for_bytes(realization.encode("utf-8")),
        "l2": l2,
        "l2_cid": cid_for_dag_json(l2),
        "forward_vs_gold": compare_semantic_ir(case["gold_ir"], l1),
        "cycle_l1_vs_l2": compare_semantic_ir(l1, l2),
        "end_to_end_vs_gold": compare_semantic_ir(case["gold_ir"], l2),
        "source_copy": source_copy_metrics(
            str(case["source_text"]), realization
        ),
        "parser_diagnostics": diagnostics,
        "roundtrip_parser_diagnostics": roundtrip_diagnostics,
        "timing": {
            "forward_seconds": round(forward_seconds, 9),
            "recompile_seconds": round(recompile_seconds, 9),
            "total_seconds": round(
                forward_seconds + recompile_seconds, 9
            ),
        },
    }


def _atoms_supported_by_text(
    text: str, candidates: Sequence[str], *, threshold: float = 0.22
) -> list[str]:
    return sorted(
        candidate
        for candidate in candidates
        if _jaccard(text, candidate) >= threshold
    )


def _project_dcec_formula(
    formula_text: str,
    realization: str,
    case: Mapping[str, Any],
) -> dict[str, Any]:
    signal = f"{formula_text} {realization}"
    action = _best_atom(signal, _allowed(case, "actions"))
    actor = _best_atom(signal, _allowed(case, "actors"))
    obj = _best_atom(
        signal, _allowed(case, "objects"), allow_empty=True
    )
    if not actor or not action:
        return {"rules": []}
    formula_lower = formula_text.lower()
    realization_lower = realization.lower()
    if (
        formula_text.startswith("F(")
        or "prohibition" in formula_lower
        or realization_lower.startswith(("must not ", "shall not ", "not "))
        or "¬" in formula_text
    ):
        modality = "F"
    elif formula_text.startswith("P(") or realization_lower.startswith(
        ("may ", "can ")
    ):
        modality = "P"
    else:
        modality = "O"
    qualifiers = _allowed(case, "qualifiers")
    supported = _atoms_supported_by_text(signal, qualifiers)
    conditions = [
        item
        for item in supported
        if any(token in item for token in ("if_", "when_", "condition"))
    ]
    exceptions = [
        item
        for item in supported
        if any(token in item for token in ("unless_", "except_", "without_"))
    ]
    temporal = sorted(
        set(supported) - set(conditions) - set(exceptions)
    )
    return validate_semantic_ir(
        {
            "rules": [
                {
                    "modality": modality,
                    "actor": actor,
                    "action": action,
                    "object": obj,
                    "conditions": conditions,
                    "exceptions": exceptions,
                    "temporal": temporal,
                }
            ]
        },
        case,
    )


def run_dcec(case: Mapping[str, Any]) -> dict[str, Any]:
    from ipfs_datasets_py.logic.CEC.native.nl_converter import (
        NaturalLanguageConverter,
    )

    converter = NaturalLanguageConverter()
    started = time.perf_counter()
    result = converter.convert_to_dcec(str(case["source_text"]))
    if not result.success or result.dcec_formula is None:
        return {
            "status": "failed",
            "translator": "dcec_natural_language_converter",
            "reason": _clean_text(result.error_message),
            "timing": {
                "total_seconds": round(time.perf_counter() - started, 9)
            },
        }
    formula_text = result.dcec_formula.to_string()
    realization = converter.convert_from_dcec(result.dcec_formula)
    l1 = _project_dcec_formula(
        formula_text, realization, case
    )
    forward_seconds = time.perf_counter() - started
    recompile_started = time.perf_counter()
    result2 = converter.convert_to_dcec(realization)
    if result2.success and result2.dcec_formula is not None:
        formula_text2 = result2.dcec_formula.to_string()
        realization2 = converter.convert_from_dcec(result2.dcec_formula)
        l2 = _project_dcec_formula(formula_text2, realization2, case)
    else:
        formula_text2 = ""
        l2 = {"rules": []}
    recompile_seconds = time.perf_counter() - recompile_started
    return {
        "status": "success",
        "translator": "dcec_natural_language_converter",
        "source_withheld_from_realizer": True,
        "coverage": {
            "formula_nontrivial": any(
                marker in formula_text for marker in ("O(", "P(", "F(", "¬")
            ),
            "gold_rule_count": len(case["gold_ir"]["rules"]),
        },
        "formula": formula_text,
        "formula_cid": cid_for_bytes(formula_text.encode("utf-8")),
        "l1": l1,
        "l1_cid": cid_for_dag_json(l1),
        "realization": realization,
        "realization_cid": cid_for_bytes(realization.encode("utf-8")),
        "recompiled_formula": formula_text2,
        "l2": l2,
        "l2_cid": cid_for_dag_json(l2),
        "forward_vs_gold": compare_semantic_ir(case["gold_ir"], l1),
        "cycle_l1_vs_l2": compare_semantic_ir(l1, l2),
        "end_to_end_vs_gold": compare_semantic_ir(case["gold_ir"], l2),
        "source_copy": source_copy_metrics(
            str(case["source_text"]), realization
        ),
        "timing": {
            "forward_seconds": round(forward_seconds, 9),
            "recompile_seconds": round(recompile_seconds, 9),
            "total_seconds": round(
                forward_seconds + recompile_seconds, 9
            ),
        },
    }


SEMANTIC_IR_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rules"],
    "properties": {
        "rules": {
            "type": "array",
            "maxItems": 16,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(RULE_FIELDS),
                "properties": {
                    "modality": {
                        "type": "string",
                        "enum": ["O", "P", "F"],
                    },
                    "actor": {"type": "string", "maxLength": 80},
                    "action": {"type": "string", "maxLength": 80},
                    "object": {"type": "string", "maxLength": 80},
                    **{
                        field: {
                            "type": "array",
                            "maxItems": 8,
                            "items": {
                                "type": "string",
                                "maxLength": 120,
                            },
                        }
                        for field in LIST_FIELDS
                    },
                },
            },
        }
    },
}
REALIZATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text"],
    "properties": {
        "text": {
            "type": "string",
            "maxLength": 12000,
        }
    },
}


def _semantic_schema_for_case(
    case: Mapping[str, Any], text: str
) -> dict[str, Any]:
    schema = json.loads(json.dumps(SEMANTIC_IR_JSON_SCHEMA))
    rules_schema = schema["properties"]["rules"]
    cue_count = len(
        re.findall(
            r"\b(?:shall|must|may|cannot|required\s+to|allowed\s+to)\b",
            text,
            flags=re.IGNORECASE,
        )
    )
    # This is derived solely from the presented text, not the gold rule count.
    # It prevents grammar-guided models from filling the global 16-rule bound
    # with duplicates after all explicit modal clauses have been consumed.
    rules_schema["maxItems"] = min(16, max(1, cue_count))
    properties = rules_schema["items"]["properties"]
    properties["actor"]["enum"] = _allowed(case, "actors")
    properties["action"]["enum"] = _allowed(case, "actions")
    properties["object"]["enum"] = ["", *_allowed(case, "objects")]
    qualifiers = _allowed(case, "qualifiers")
    for field in LIST_FIELDS:
        properties[field]["items"]["enum"] = qualifiers
    return schema


def _strict_json_object(raw: str) -> dict[str, Any]:
    def reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise BenchmarkError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=reject_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                BenchmarkError(f"non-finite JSON constant: {token}")
            ),
        )
    except BenchmarkError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError) as exc:
        raise BenchmarkError(
            f"model response is not strict JSON: {type(exc).__name__}"
        ) from exc
    if not isinstance(value, dict):
        raise BenchmarkError("model response must be one JSON object")
    return value


def _server_grammar_schema(value: Any) -> Any:
    """Remove string bounds unsupported by this llama.cpp schema compiler.

    The client-side validator still enforces every removed bound. Keeping the
    array bounds, structural keys, enums, required sets, and
    ``additionalProperties`` in the server grammar prevents duplicate/unknown
    fields and runaway prose.
    """

    if isinstance(value, Mapping):
        return {
            str(key): _server_grammar_schema(item)
            for key, item in value.items()
            if key != "maxLength"
        }
    if isinstance(value, list):
        return [_server_grammar_schema(item) for item in value]
    return value


class LeanstralClient:
    """Bounded client for one pre-existing, identity-pinned llama.cpp service."""

    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        timeout_seconds: float,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.origin = (
            self.endpoint[:-3]
            if self.endpoint.endswith("/v1")
            else self.endpoint
        )
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.cache: dict[str, TimedResult] = {}

    def _get_json(self, path: str, *, max_bytes: int = 1_048_576) -> Any:
        request = urllib.request.Request(self.origin + path)
        with urllib.request.urlopen(
            request, timeout=min(self.timeout_seconds, 10.0)
        ) as response:
            raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise BenchmarkError(f"HTTP response from {path} is oversized")
        return json.loads(raw)

    def probe(self) -> dict[str, Any]:
        health = self._get_json("/health")
        models = self._get_json("/v1/models")
        props = self._get_json("/props")
        served = [
            str(item.get("id") or "")
            for item in models.get("data", [])
            if isinstance(item, Mapping)
        ]
        if str(health.get("status") or "").lower() not in {"ok", "healthy"}:
            raise BenchmarkError("Leanstral service is not healthy")
        if served.count(self.model) != 1:
            raise BenchmarkError(
                "exact Leanstral model is absent or ambiguous"
            )
        selected_model = next(
            (
                item
                for item in models.get("data", [])
                if isinstance(item, Mapping)
                and str(item.get("id") or "") == self.model
            ),
            {},
        )
        defaults = props.get("default_generation_settings", {})
        defaults = defaults if isinstance(defaults, Mapping) else {}
        return {
            "health": str(health.get("status")).lower(),
            "endpoint": self.endpoint,
            "model": self.model,
            "served_models": served,
            "backend_owner": selected_model.get("owned_by"),
            "model_metadata": selected_model.get("meta"),
            "model_alias": props.get("model_alias"),
            "model_path": props.get("model_path"),
            "model_format": props.get("model_ftype"),
            "backend_build": props.get("build_info"),
            "context_size": defaults.get("n_ctx"),
            "total_slots": props.get("total_slots"),
            "props_cid": cid_for_dag_json(props),
        }

    def complete_json(
        self,
        *,
        system: str,
        prompt: str,
        schema_name: str,
        schema: Mapping[str, Any],
        max_tokens: int,
    ) -> TimedResult:
        server_schema = _server_grammar_schema(schema)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "seed": 0,
            "max_tokens": max_tokens,
            "stop": ["<|im_end|>"],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": server_schema,
                },
            },
        }
        request_cid = cid_for_dag_json(payload)
        if request_cid in self.cache:
            cached = self.cache[request_cid]
            return TimedResult(
                cached.value,
                0.0,
                {
                    **cached.metadata,
                    "benchmark_cache": "memory_hit",
                    "request_cid": request_cid,
                },
            )
        body = canonical_dag_json_bytes(payload)
        if len(body) > 64 * 1024:
            raise BenchmarkError("Leanstral request exceeds 64 KiB")
        request = urllib.request.Request(
            self.endpoint + "/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                raw_response = response.read(2 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", "replace")
            raise BenchmarkError(
                f"Leanstral HTTP {exc.code}: {_clean_text(detail)[:500]}"
            ) from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            raise BenchmarkError(
                f"Leanstral request failed: {type(exc).__name__}"
            ) from exc
        elapsed = time.perf_counter() - started
        if len(raw_response) > 2 * 1024 * 1024:
            raise BenchmarkError("Leanstral response exceeds 2 MiB")
        envelope = json.loads(raw_response)
        choices = envelope.get("choices")
        if (
            not isinstance(choices, list)
            or len(choices) != 1
            or not isinstance(choices[0], Mapping)
        ):
            raise BenchmarkError("Leanstral returned an invalid choice set")
        choice = choices[0]
        if choice.get("finish_reason") != "stop":
            raise BenchmarkError(
                f"Leanstral finish reason: {choice.get('finish_reason')!r}"
            )
        message = choice.get("message")
        content = (
            message.get("content")
            if isinstance(message, Mapping)
            else None
        )
        if not isinstance(content, str) or not content.strip():
            raise BenchmarkError("Leanstral returned no content")
        if envelope.get("model") != self.model:
            raise BenchmarkError("Leanstral response model identity drifted")
        value = _strict_json_object(content)
        metadata = {
            "request_cid": request_cid,
            "prompt_cid": cid_for_bytes(prompt.encode("utf-8")),
            "raw_content_cid": cid_for_bytes(content.encode("utf-8")),
            "response_envelope_cid": cid_for_dag_json(envelope),
            "response_model": str(envelope.get("model")),
            "finish_reason": str(choice.get("finish_reason")),
            "usage": envelope.get("usage") or {},
            "timings": envelope.get("timings") or {},
            "benchmark_cache": "miss",
            "server_response_format": "json_schema",
            "client_schema_validation": True,
            "requested_schema_name": schema_name,
            "requested_schema_cid": cid_for_dag_json(schema),
            "server_schema_cid": cid_for_dag_json(server_schema),
        }
        result = TimedResult(value, elapsed, metadata)
        self.cache[request_cid] = result
        return result


def _spacy_evidence(nlp: Any, text: str) -> dict[str, Any]:
    doc = nlp(text)
    return {
        "pipeline": list(nlp.pipe_names),
        "tokens": [
            {
                "text": token.text,
                "lemma": token.lemma_,
                "pos": token.pos_,
                "dep": token.dep_,
                "head": token.head.i,
            }
            for token in list(doc)[:256]
        ],
        "entities": [
            {"text": entity.text, "label": entity.label_}
            for entity in list(doc.ents)[:32]
        ],
    }


def _encoder_prompt(
    case: Mapping[str, Any],
    text: str,
    *,
    spacy_evidence: Mapping[str, Any] | None = None,
) -> str:
    evidence = (
        "\nSPACY_EVIDENCE_JSON:\n" + _canonical(spacy_evidence)
        if spacy_evidence is not None
        else ""
    )
    return (
        "Convert the source into atomic legal rules. Return only the JSON "
        "schema. O means obligation, P permission, F prohibition. Preserve "
        "negation, actor/action binding, conditions, exceptions, and temporal "
        "scope. Split conjunctions into separate rules only when they impose "
        "separate actions. Use only exact atom IDs from ALLOWED_ATOMS; use an "
        "empty object string when no object atom applies. Ignore headings and "
        "descriptive recital text. Return an empty rules array only if there "
        "is no norm. The top level has exactly one key, rules. Every rule has "
        "exactly seven keys and all conditions, exceptions, and temporal "
        "values are arrays of exact qualifier IDs. Do not emit ids, type, "
        "confidence, explanations, mappings, booleans, or distractor rules.\n"
        "OUTPUT_SHAPE_EXAMPLE_JSON:\n"
        '{"rules":[{"modality":"O","actor":"actor_atom","action":'
        '"action_atom","object":"","conditions":[],"exceptions":[],'
        '"temporal":[]}]}\nALLOWED_ATOMS_JSON:\n'
        + _canonical(case["allowed_atoms"])
        + "\nSOURCE_TEXT_JSON_STRING:\n"
        + _canonical(text)
        + evidence
    )


def _realizer_prompt(
    case: Mapping[str, Any], logic_ir: Mapping[str, Any]
) -> str:
    return (
        "Realize every and only the supplied legal rules as concise, fluent "
        "English. Atom IDs are semantic labels: replace underscores with "
        "natural spacing and inflect minimally. Preserve O as shall/must, P "
        "as may, and F as shall not/must not. Preserve every condition, "
        "exception, and temporal qualifier with unambiguous scope. Do not "
        "invent facts, explanations, headings, citations, or rules. Return "
        "exactly one compact JSON object with exactly one string key: "
        '{"text":"..."}. Do not imitate a generic example; lexicalize the '
        "actual IR below.\nLOGIC_IR_JSON:\n"
        + _canonical(logic_ir)
    )


def _leanstral_encode(
    client: LeanstralClient,
    case: Mapping[str, Any],
    text: str,
    *,
    nlp: Any | None = None,
) -> TimedResult:
    evidence = _spacy_evidence(nlp, text) if nlp is not None else None
    base_prompt = _encoder_prompt(case, text, spacy_evidence=evidence)
    response_schema = _semantic_schema_for_case(case, text)
    max_tokens = min(
        3072,
        max(768, 256 + 192 * len(case["gold_ir"]["rules"])),
    )
    total_seconds = 0.0
    attempt_receipts: list[dict[str, Any]] = []
    final_error: BenchmarkError | None = None
    for attempt in range(2):
        prompt = base_prompt
        if attempt:
            prompt += (
                "\nSAFE_REPAIR_CLASS:structured_contract_failure\n"
                "SAFE_REPAIR_INSTRUCTION:The prior response was invalid. "
                "Return a shorter object with exactly the required keys, no "
                "duplicate rules or keys, and only exact ALLOWED_ATOMS values. "
                "Conditions, exceptions, and temporal must be arrays. Stop "
                "immediately after the final JSON brace."
            )
        try:
            result = client.complete_json(
                system=(
                    "You are a deterministic legal semantic parser. Emit one "
                    "compact JSON object, never repeat a rule, stop immediately "
                    "after the final brace, never explain, and never claim "
                    "that generated logic is proved."
                ),
                prompt=prompt,
                schema_name="semantic_legal_ir",
                schema=response_schema,
                max_tokens=max_tokens,
            )
            total_seconds += result.elapsed_seconds
            try:
                ir = validate_semantic_ir(result.value, case)
            except BenchmarkError as exc:
                attempt_receipts.append(
                    {
                        "attempt": attempt + 1,
                        "status": "contract_rejected",
                        "failure_type": type(exc).__name__,
                        "failure_detail": str(exc)[:500],
                        "candidate_cid": cid_for_dag_json(result.value),
                        **result.metadata,
                    }
                )
                final_error = exc
                continue
            attempt_receipts.append(
                {
                    "attempt": attempt + 1,
                    "status": "accepted",
                    **result.metadata,
                }
            )
            return TimedResult(
                ir,
                total_seconds,
                {
                    **result.metadata,
                    "attempt_count": attempt + 1,
                    "attempt_receipts": attempt_receipts,
                },
            )
        except BenchmarkError as exc:
            attempt_receipts.append(
                {
                    "attempt": attempt + 1,
                    "status": "generation_rejected",
                    "failure_type": type(exc).__name__,
                    "failure_detail": str(exc)[:500],
                }
            )
            final_error = exc
    raise BenchmarkError(
        "Leanstral semantic encoding failed after bounded repair: "
        + str(final_error or "unknown failure")
    )


def _leanstral_realize(
    client: LeanstralClient,
    case: Mapping[str, Any],
    logic_ir: Mapping[str, Any],
) -> TimedResult:
    prompt = _realizer_prompt(case, logic_ir)
    source = str(case["source_text"])
    if source in prompt:
        raise BenchmarkError(
            "source text leaked into the source-withheld realization prompt"
        )
    result = client.complete_json(
        system=(
            "You are a source-withheld formal-logic realizer. The supplied "
            "IR is your only semantic authority."
        ),
        prompt=prompt,
        schema_name="semantic_legal_realization",
        schema=REALIZATION_JSON_SCHEMA,
        max_tokens=min(
            1536,
            max(256, 80 + 80 * len(logic_ir.get("rules") or ())),
        ),
    )
    if set(result.value) != {"text"}:
        raise BenchmarkError("realization response has unexpected keys")
    text = _clean_text(result.value["text"])
    if not text:
        raise BenchmarkError("realization response is empty")
    return TimedResult(text, result.elapsed_seconds, result.metadata)


def run_leanstral_cycle(
    case: Mapping[str, Any],
    client: LeanstralClient,
    *,
    nlp: Any | None = None,
    oracle_l1: bool = False,
) -> dict[str, Any]:
    method = (
        "leanstral_oracle_reverse"
        if oracle_l1
        else (
            "spacy_plus_leanstral_cycle"
            if nlp is not None
            else "leanstral_direct_cycle"
        )
    )
    receipts: list[dict[str, Any]] = []
    if oracle_l1:
        l1 = case["gold_ir"]
        forward_seconds = 0.0
    else:
        encoded = _leanstral_encode(
            client, case, str(case["source_text"]), nlp=nlp
        )
        l1 = encoded.value
        forward_seconds = encoded.elapsed_seconds
        receipts.append({"operation": "encode", **encoded.metadata})
    realized = _leanstral_realize(client, case, l1)
    receipts.append({"operation": "realize", **realized.metadata})
    reencoded = _leanstral_encode(
        client, case, realized.value, nlp=nlp
    )
    receipts.append({"operation": "reencode", **reencoded.metadata})
    l2 = reencoded.value
    total_seconds = (
        forward_seconds
        + realized.elapsed_seconds
        + reencoded.elapsed_seconds
    )
    return {
        "status": "success",
        "translator": method,
        "shared_model_resource": "leanstral-119b-one-slot",
        "source_withheld_from_realizer": True,
        "oracle_l1": oracle_l1,
        "l1": l1,
        "l1_cid": cid_for_dag_json(l1),
        "realization": realized.value,
        "realization_cid": cid_for_bytes(
            realized.value.encode("utf-8")
        ),
        "l2": l2,
        "l2_cid": cid_for_dag_json(l2),
        "forward_vs_gold": compare_semantic_ir(case["gold_ir"], l1),
        "cycle_l1_vs_l2": compare_semantic_ir(l1, l2),
        "end_to_end_vs_gold": compare_semantic_ir(case["gold_ir"], l2),
        "source_copy": source_copy_metrics(
            str(case["source_text"]), realized.value
        ),
        "timing": {
            "forward_seconds": round(forward_seconds, 9),
            "realize_seconds": round(realized.elapsed_seconds, 9),
            "recompile_seconds": round(reencoded.elapsed_seconds, 9),
            "total_seconds": round(total_seconds, 9),
        },
        "receipts": receipts,
    }


class SymaiForwardRunner:
    """Run the repository's strict SyMAI adapter on the pinned inner route."""

    def __init__(self, *, endpoint: str, inner_model: str) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.inner_model = inner_model
        self._temporary = tempfile.TemporaryDirectory(
            prefix="semantic-roundtrip-symai-"
        )
        config_root = Path(self._temporary.name)
        config_dir = config_root / ".symai"
        config_dir.mkdir(mode=0o700)
        (config_dir / "symai.config.json").write_text(
            _canonical(
                {
                    "NEUROSYMBOLIC_ENGINE_MODEL": "ipfs:Leanstral-119B",
                    "NEUROSYMBOLIC_ENGINE_API_KEY": "ipfs",
                    "SYMBOLIC_ENGINE": "ipfs",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        original_prefix = sys.prefix
        try:
            sys.prefix = str(config_root)
            importlib.import_module("symai")
            adapters = importlib.import_module(
                "benchmarks.logic_pipeline.adapters"
            )
            contracts = importlib.import_module(
                "benchmarks.logic_pipeline.contracts"
            )
        finally:
            sys.prefix = original_prefix
        self.StageRequest = adapters.StageRequest
        self.CacheMode = contracts.CacheMode
        self.Split = contracts.Split
        self.adapter = adapters.SymaiAdapter(
            config=adapters.SymaiAdapterConfig(
                provider="ipfs_accelerate_py",
                model="Leanstral-119B",
                max_retries=1,
                dry_run=False,
                cache_enabled=False,
                max_text_bytes=8192,
                max_raw_output_bytes=4096,
                expected_inner_provider="leanstral_local",
                expected_inner_model=inner_model,
                expected_inner_endpoint=self.endpoint,
                expected_inner_backend="existing_leanstral_service",
            ),
            cache={},
        )

    def close(self) -> None:
        self._temporary.cleanup()

    def run(self, case: Mapping[str, Any], *, run_id: str) -> dict[str, Any]:
        started = time.perf_counter()
        request_identity = {
            "provider": "ipfs_accelerate_py",
            "model": "Leanstral-119B",
            "inner_provider": "leanstral_local",
            "inner_model": self.inner_model,
            "inner_endpoint": self.endpoint,
        }
        record = self.adapter.run(
            self.StageRequest(
                run_id=run_id,
                case_id=str(case["id"]),
                case_manifest_sha256=_legacy_sha(case),
                variant_id="A4",
                split=self.Split.PILOT,
                cache_mode=self.CacheMode.COLD,
                input_data={"text": str(case["source_text"])},
                requested_identity=request_identity,
                environment_sha256=_legacy_sha(request_identity),
            )
        )
        elapsed = time.perf_counter() - started
        status = str(getattr(record.status, "value", record.status))
        data = _json_safe(record.data)
        if not isinstance(data, dict):
            raise BenchmarkError("SyMAI record data is not an object")
        serialized = _json_safe(record.to_dict())
        if status != "success":
            return {
                "status": status,
                "translator": "symai_forward_projection",
                "roundtrip_supported": False,
                "failure_code": str(
                    getattr(record.failure_code, "value", record.failure_code)
                ),
                "failure_detail": record.failure_detail,
                "record_cid": cid_for_dag_json(serialized),
                "timing": {"total_seconds": round(elapsed, 9)},
            }
        output_strings = _flatten_strings(data)
        gold_atoms = sorted(
            {
                str(value)
                for rule in case["gold_ir"]["rules"]
                for field, value in rule.items()
                if field != "modality"
                for value in (
                    value
                    if isinstance(value, list)
                    else [value]
                )
                if value
            }
        )
        atom_scores = {
            atom: round(
                max(
                    (_jaccard(item, atom) for item in output_strings),
                    default=0.0,
                ),
                9,
            )
            for atom in gold_atoms
        }
        recovered = sum(score >= 0.20 for score in atom_scores.values())
        return {
            "status": "success",
            "translator": "symai_forward_projection",
            "roundtrip_supported": False,
            "shared_model_resource": "leanstral-119b-one-slot",
            "reason": (
                "The current pinned SyMAI contract produces forward semantic "
                "evidence but has no logic-to-natural-language field."
            ),
            "candidate_ir": data.get("candidate_ir"),
            "normalized_predicates": data.get("normalized_predicates"),
            "quantifiers": data.get("quantifiers"),
            "entities": data.get("entities"),
            "ambiguity_flags": data.get("ambiguity_flags"),
            "confidence": data.get("confidence"),
            "gold_atom_lexical_recall": round(
                recovered / len(gold_atoms) if gold_atoms else 0.0, 9
            ),
            "gold_atom_scores": atom_scores,
            "backend_provenance": data.get("backend_provenance"),
            "raw_output_cid": (
                cid_for_bytes(str(data["raw_output"]).encode("utf-8"))
                if isinstance(data.get("raw_output"), str)
                else None
            ),
            "record_cid": cid_for_dag_json(serialized),
            "timing": {"total_seconds": round(elapsed, 9)},
        }


def _rule_cids(ir: Mapping[str, Any]) -> list[str]:
    return sorted(
        cid_for_dag_json(rule) for rule in (ir.get("rules") or ())
    )


def hammer_cvc5_equivalence(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    request_id: str,
) -> dict[str, Any]:
    from ipfs_datasets_py.logic.hammers.models import (
        HammerPolicy,
        SolverVerdict,
        TranslationTarget,
    )
    from ipfs_datasets_py.logic.hammers.policy import (
        PortfolioPolicy,
        SolverBudget,
    )
    from ipfs_datasets_py.logic.hammers.portfolio import (
        PortfolioAttemptSpec,
        SolverPortfolio,
    )
    from ipfs_datasets_py.logic.hammers.translation import (
        PROP_SORT,
        And,
        BoolLit,
        Const,
        Iff,
        Not,
        TranslationContext,
    )

    left_ids = _rule_cids(left)
    right_ids = _rule_cids(right)
    all_ids = sorted(set(left_ids) | set(right_ids))
    atoms = {
        cid: Const(f"rule_{index:03d}", PROP_SORT)
        for index, cid in enumerate(all_ids)
    }

    def conjunction(values: Sequence[str]) -> Any:
        terms = [atoms[value] for value in sorted(set(values))]
        if not terms:
            return BoolLit(True)
        result = terms[0]
        for term in terms[1:]:
            result = And(result, term)
        return result

    counterexample_query = Not(
        Iff(conjunction(left_ids), conjunction(right_ids))
    )
    translation = TranslationContext(request_id=request_id).translate(
        source_construct="semantic_rule_set_counterexample",
        term=counterexample_query,
        target=TranslationTarget.SMTLIB,
    )
    policy = PortfolioPolicy(
        hammer_policy=HammerPolicy(
            timeout_seconds=5.0,
            allowed_solvers=["cvc5"],
            network_allowed=False,
        ),
        solver_budgets={"cvc5": SolverBudget(timeout_seconds=5.0)},
        cancel_on_first_conclusive=True,
    )
    started = time.perf_counter()
    result = SolverPortfolio(policy).run(
        request_id,
        [
            PortfolioAttemptSpec(
                translation=translation, solver_name="cvc5"
            )
        ],
    )
    elapsed = time.perf_counter() - started
    if not result.attempts:
        return {
            "status": "unavailable",
            "equivalent": False,
            "denied": result.denied,
            "translation_cid": cid_for_dag_json(translation.to_dict()),
            "elapsed_seconds": round(elapsed, 9),
        }
    attempt = result.attempts[0]
    evidence = result.evidence.get(attempt.attempt_id)
    verdict = str(getattr(attempt.verdict, "value", attempt.verdict))
    solver_set_equivalent = attempt.verdict is SolverVerdict.UNSAT
    # Propositional conjunctions are sets. Preserve multiplicity separately
    # so duplicate generated rules cannot be hidden by idempotence.
    multiplicity_equal = left_ids == right_ids
    nonvacuous = bool(left_ids) and bool(right_ids)
    return {
        "status": "success",
        "validator": "hammer_solver_portfolio/cvc5",
        "query": "exists_counterexample_to_rule_set_equivalence",
        "solver_verdict": verdict,
        "solver_set_equivalent": solver_set_equivalent,
        "multiplicity_equal": multiplicity_equal,
        "nonvacuous": nonvacuous,
        "equivalent": (
            solver_set_equivalent and multiplicity_equal and nonvacuous
        ),
        "left_rule_cids": left_ids,
        "right_rule_cids": right_ids,
        "translation_cid": cid_for_dag_json(translation.to_dict()),
        "attempt_cid": cid_for_dag_json(attempt.to_dict()),
        "evidence_cid": (
            cid_for_dag_json(evidence.to_dict())
            if evidence is not None
            else None
        ),
        "elapsed_seconds": round(elapsed, 9),
    }


def lean_exact_identity(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    lean_path: str,
) -> dict[str, Any]:
    left_ids = _rule_cids(left)
    right_ids = _rule_cids(right)

    def lean_list(values: Sequence[str]) -> str:
        return "[" + ", ".join(json.dumps(value) for value in values) + "]"

    source = (
        "def leftRules : List String := "
        + lean_list(left_ids)
        + "\n"
        + "def rightRules : List String := "
        + lean_list(right_ids)
        + "\n"
        + "theorem exactSemanticRuleIdentity : leftRules = rightRules := by\n"
        + "  decide\n"
    )
    with tempfile.TemporaryDirectory(
        prefix="semantic-roundtrip-lean-"
    ) as raw_directory:
        directory = Path(raw_directory)
        source_path = directory / "Main.lean"
        source_path.write_text(source, encoding="utf-8")
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                [lean_path, str(source_path)],
                cwd=directory,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10.0,
                check=False,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "LANG": "C.UTF-8",
                },
            )
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            completed = None
            timed_out = True
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
        elapsed = time.perf_counter() - started
    if completed is not None:
        stdout = completed.stdout
        stderr = completed.stderr
        return_code = completed.returncode
    else:
        return_code = None
    return {
        "status": "timeout" if timed_out else "success",
        "validator": "lean_native_kernel",
        "claim": "exact_canonical_rule_cid_list_identity",
        "kernel_accepted": return_code == 0,
        "nonvacuous": bool(left_ids) and bool(right_ids),
        "benchmark_accepted": (
            return_code == 0 and bool(left_ids) and bool(right_ids)
        ),
        "return_code": return_code,
        "source_cid": cid_for_bytes(source.encode("utf-8")),
        "stdout_cid": cid_for_bytes(stdout),
        "stderr_cid": cid_for_bytes(stderr),
        "stderr_excerpt": stderr.decode("utf-8", "replace")[:500],
        "elapsed_seconds": round(elapsed, 9),
    }


def attach_validators(
    arm: dict[str, Any],
    *,
    case_id: str,
    arm_id: str,
    lean_path: str,
) -> dict[str, Any]:
    if (
        arm.get("status") != "success"
        or not isinstance(arm.get("l1"), Mapping)
        or not isinstance(arm.get("l2"), Mapping)
    ):
        return {
            "status": "not_applicable",
            "reason": "arm did not produce both L1 and L2",
        }
    safe_request = re.sub(
        r"[^A-Za-z0-9_.:-]", "_", f"{case_id}:{arm_id}"
    )[:120]
    arm["validation"] = {
        "status": "success",
        "hammer_cvc5": hammer_cvc5_equivalence(
            arm["l1"],
            arm["l2"],
            request_id=safe_request,
        ),
        "lean": lean_exact_identity(
            arm["l1"], arm["l2"], lean_path=lean_path
        ),
        "scope": (
            "Exact canonical rule-set identity only. Unsupported richer "
            "legal semantics are not promoted to proof claims."
        ),
    }
    return {"status": "success"}


def _safe_arm(function: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        return function(*args, **kwargs)
    except Exception as exc:
        return {
            "status": "failed",
            "translator": getattr(function, "__name__", "unknown"),
            "failure_type": type(exc).__name__,
            "failure_detail": _clean_text(exc)[:1000],
            "timing": {
                "total_seconds": round(time.perf_counter() - started, 9)
            },
        }


def attach_validators_safely(
    arm: dict[str, Any],
    *,
    case_id: str,
    arm_id: str,
    lean_path: str,
) -> dict[str, Any]:
    """Attach validators and preserve any validator failure on the arm."""

    receipt = _safe_arm(
        attach_validators,
        arm,
        case_id=case_id,
        arm_id=arm_id,
        lean_path=lean_path,
    )
    if receipt.get("status") == "failed":
        arm["validation"] = {
            **receipt,
            "scope": (
                "Validator execution failed; no proof-backed identity claim "
                "is available."
            ),
        }
    return receipt


def _package_version(distribution: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(distribution)
    except Exception:
        return None


def _command_identity(arguments: Sequence[str]) -> dict[str, Any]:
    executable = shutil.which(arguments[0])
    if not executable:
        return {"available": False, "command": arguments[0]}
    try:
        completed = subprocess.run(
            [executable, *arguments[1:]],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10.0,
            check=False,
        )
        output = completed.stdout.decode("utf-8", "replace")[:1000]
        return {
            "available": True,
            "path": executable,
            "return_code": completed.returncode,
            "version_output": _clean_text(output),
            "version_output_cid": cid_for_bytes(completed.stdout),
        }
    except Exception as exc:
        return {
            "available": True,
            "path": executable,
            "probe_error": type(exc).__name__,
        }


def capability_inventory(
    *,
    client: LeanstralClient | None,
    spacy_nlp: Any | None,
) -> dict[str, Any]:
    processor = platform.processor()
    if not processor:
        try:
            processor = next(
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                if line.lower().startswith("model name")
            )
        except (OSError, StopIteration):
            processor = "unknown"
    inventory: dict[str, Any] = {
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
        },
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": processor,
            "logical_cpu_count": os.cpu_count(),
        },
        "spacy": {
            "package_version": _package_version("spacy"),
            "model": "en_core_web_sm",
            "model_version": _package_version("en-core-web-sm"),
            "pipeline": (
                list(spacy_nlp.pipe_names) if spacy_nlp is not None else []
            ),
        },
        "symai": {
            "distribution": "symbolicai",
            "version": _package_version("symbolicai"),
            "method_role": "prompting_and_router_layer",
            "independent_model": False,
        },
        "hammer": {
            "distribution": "ipfs-datasets-py",
            "module": "ipfs_datasets_py.logic.hammers",
        },
        "cvc5": _command_identity(("cvc5", "--version")),
        "lean": _command_identity(("lean", "--version")),
    }
    if client is not None:
        inventory["leanstral"] = client.probe()
        inventory["leanstral"]["parallel_slots"] = 1
        inventory["leanstral"]["shared_with_symai"] = True
    return inventory


def _aggregate_standard_arm(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    successful = [
        record for record in records if record.get("status") == "success"
    ]
    forward_covered = [
        record
        for record in successful
        if isinstance(record.get("l1"), Mapping)
        and bool(record["l1"].get("rules"))
    ]
    roundtrip_covered = [
        record
        for record in forward_covered
        if isinstance(record.get("l2"), Mapping)
        and bool(record["l2"].get("rules"))
    ]

    def values(
        source: Sequence[Mapping[str, Any]],
        path: tuple[str, ...],
    ) -> list[float]:
        result: list[float] = []
        for record in source:
            value: Any = record
            for key in path:
                value = value.get(key) if isinstance(value, Mapping) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result.append(float(value))
        return result

    def conditional_mean(path: tuple[str, ...]) -> float | None:
        found = values(successful, path)
        return round(sum(found) / len(found), 9) if found else None

    def all_case_mean(
        path: tuple[str, ...], *, missing_value: float
    ) -> float | None:
        if not records:
            return None
        values: list[float] = []
        for record in records:
            value: Any = record
            for key in path:
                value = value.get(key) if isinstance(value, Mapping) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
            else:
                values.append(missing_value)
        return round(sum(values) / len(records), 9)

    return {
        "case_count": len(records),
        "success_count": len(successful),
        "execution_rate": round(
            len(successful) / len(records) if records else 0.0, 9
        ),
        "forward_semantic_coverage_count": len(forward_covered),
        "forward_semantic_coverage_rate": round(
            len(forward_covered) / len(records) if records else 0.0, 9
        ),
        "full_roundtrip_coverage_count": len(roundtrip_covered),
        "full_roundtrip_coverage_rate": round(
            len(roundtrip_covered) / len(records) if records else 0.0, 9
        ),
        # Backward-compatible aliases now use the stricter full-roundtrip
        # definition rather than merely checking for a non-empty L1.
        "semantic_coverage_count": len(roundtrip_covered),
        "coverage_rate": round(
            len(roundtrip_covered) / len(records) if records else 0.0, 9
        ),
        "mean_forward_semantic_score": all_case_mean(
            ("forward_vs_gold", "semantic_score"), missing_value=0.0
        ),
        "mean_cycle_semantic_score": all_case_mean(
            ("cycle_l1_vs_l2", "semantic_score"), missing_value=0.0
        ),
        "mean_end_to_end_semantic_score": all_case_mean(
            ("end_to_end_vs_gold", "semantic_score"), missing_value=0.0
        ),
        "mean_forward_semantic_loss": all_case_mean(
            ("forward_vs_gold", "semantic_loss"), missing_value=1.0
        ),
        "mean_cycle_semantic_loss": all_case_mean(
            ("cycle_l1_vs_l2", "semantic_loss"), missing_value=1.0
        ),
        "mean_end_to_end_semantic_loss": all_case_mean(
            ("end_to_end_vs_gold", "semantic_loss"), missing_value=1.0
        ),
        "conditional_mean_forward_semantic_score": conditional_mean(
            ("forward_vs_gold", "semantic_score")
        ),
        "conditional_mean_cycle_semantic_score": conditional_mean(
            ("cycle_l1_vs_l2", "semantic_score")
        ),
        "conditional_mean_end_to_end_semantic_score": conditional_mean(
            ("end_to_end_vs_gold", "semantic_score")
        ),
        "mean_total_seconds": conditional_mean(
            ("timing", "total_seconds")
        ),
        "timing_scope": "arm_reported_wall_time_on_executed_cases",
        "copy_risk_count": sum(
            bool(record.get("source_copy", {}).get("copy_risk"))
            for record in successful
        ),
        "hammer_equivalent_count": sum(
            bool(
                record.get("validation", {})
                .get("hammer_cvc5", {})
                .get("equivalent")
            )
            for record in successful
        ),
        "raw_lean_kernel_accepted_count": sum(
            bool(
                record.get("validation", {})
                .get("lean", {})
                .get("kernel_accepted")
            )
            for record in successful
        ),
        "nonvacuous_exact_identity_count": sum(
            bool(
                record.get("validation", {})
                .get("lean", {})
                .get("benchmark_accepted")
            )
            for record in successful
        ),
        "validation_failure_count": sum(
            record.get("validation", {}).get("status") == "failed"
            for record in successful
            if isinstance(record.get("validation"), Mapping)
        ),
    }


def summarize_cases(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    arms: dict[str, list[Mapping[str, Any]]] = {}
    for case in cases:
        for arm_id, record in case.get("arms", {}).items():
            arms.setdefault(str(arm_id), []).append(record)
    result: dict[str, Any] = {}
    for arm_id, records in sorted(arms.items()):
        if arm_id == "symai_forward":
            successful = [
                record
                for record in records
                if record.get("status") == "success"
            ]
            values = [
                float(record["gold_atom_lexical_recall"])
                for record in successful
                if isinstance(
                    record.get("gold_atom_lexical_recall"), (int, float)
                )
            ]
            timings = [
                float(record["timing"]["total_seconds"])
                for record in successful
                if isinstance(record.get("timing"), Mapping)
                and isinstance(
                    record["timing"].get("total_seconds"), (int, float)
                )
            ]
            result[arm_id] = {
                "case_count": len(records),
                "success_count": len(successful),
                "execution_rate": round(
                    len(successful) / len(records) if records else 0.0, 9
                ),
                "roundtrip_supported": False,
                "mean_gold_atom_lexical_recall": (
                    round(sum(values) / len(records), 9)
                    if records
                    else None
                ),
                "lexical_recall_scope": (
                    "all_cases_missing_or_failed_cases_score_zero"
                ),
                "mean_total_seconds": (
                    round(sum(timings) / len(timings), 9)
                    if timings
                    else None
                ),
                "timing_scope": "adapter_wall_time_on_executed_cases",
            }
        else:
            result[arm_id] = _aggregate_standard_arm(records)
    return result


def _summary_markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Semantic logic round-trip pilot",
        "",
        (
            f"Corpus: `{report['corpus']['case_count']}` cases, "
            f"`{report['corpus']['gold_rule_count']}` adjudicated rules, "
            f"CID `{report['corpus']['cid']}`."
        ),
        "",
        (
            "Scores distinguish source→logic fidelity, logic→text→logic "
            "cycle consistency, and end-to-end fidelity. These are all-case "
            "means: failed or missing cases score zero. Higher is better."
        ),
        "",
        (
            "| Arm | Executed | L1 coverage | L1+L2 coverage | Forward | "
            "Cycle | End-to-end | Arm-reported s |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm_id, values in summary.items():
        if values.get("roundtrip_supported") is False:
            lines.append(
                f"| {arm_id} | {values['success_count']}/"
                f"{values['case_count']} | forward evidence | unsupported | "
                f"{float(values['mean_gold_atom_lexical_recall']):.3f} "
                "lexical recall | n/a | n/a | "
                f"{float(values['mean_total_seconds']):.3f} |"
            )
            continue

        def show(value: Any) -> str:
            return "n/a" if value is None else f"{float(value):.3f}"

        lines.append(
            f"| {arm_id} | {values['success_count']}/"
            f"{values['case_count']} | "
            f"{values['forward_semantic_coverage_count']}/"
            f"{values['case_count']} | "
            f"{values['full_roundtrip_coverage_count']}/"
            f"{values['case_count']} | "
            f"{show(values.get('mean_forward_semantic_score'))} | "
            f"{show(values.get('mean_cycle_semantic_score'))} | "
            f"{show(values.get('mean_end_to_end_semantic_score'))} | "
            f"{show(values.get('mean_total_seconds'))} |"
        )
    lines.extend(
        [
            "",
            "Interpretation constraints:",
            "",
            "- SyMAI and direct Leanstral share the same one-slot model.",
            "- Hammer/cvc5 and Lean validate exact canonical rule identities; "
            "they do not judge whether natural language was formalized correctly.",
            "- Empty-IR identity is reported as a raw kernel result but never "
            "counts as benchmark-accepted equivalence.",
            "- The pilot uses a closed atom vocabulary with distractors. It "
            "tests structure and scope, not open-world ontology induction.",
            "- Realizers never receive the source. Source-overlap is a separate "
            "diagnostic and does not enter the semantic score.",
            "- Timing is each arm's reported wall time and is not a uniform "
            "end-to-end resource measurement.",
            "",
        ]
    )
    return "\n".join(lines)


def _git_state() -> dict[str, Any]:
    def run(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10.0,
            check=False,
        )
        return completed.stdout.decode("utf-8", "replace").strip()

    diff = run("diff", "--binary", "--submodule=diff", "HEAD")
    untracked_paths = [
        item
        for item in run(
            "ls-files", "--others", "--exclude-standard"
        ).splitlines()
        if item
        and item.startswith(("benchmarks/", "ipfs_datasets_py/", "tests/"))
    ]
    untracked_file_cids: dict[str, str] = {}
    for relative in sorted(untracked_paths):
        path = REPO_ROOT / relative
        if path.is_symlink():
            untracked_file_cids[relative] = cid_for_bytes(
                os.readlink(path).encode("utf-8")
            )
        elif path.is_file():
            untracked_file_cids[relative] = cid_for_bytes(path.read_bytes())
    submodule_status = run("submodule", "status", "--recursive")
    return {
        "head_commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "worktree_status": run(
            "status", "--short", "--untracked-files=all"
        ),
        "worktree_diff_cid": cid_for_bytes(diff.encode("utf-8")),
        "untracked_file_cids": untracked_file_cids,
        "untracked_manifest_cid": cid_for_dag_json(untracked_file_cids),
        "submodule_status": submodule_status,
        "submodule_status_cid": cid_for_bytes(
            submodule_status.encode("utf-8")
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture", type=Path, default=DEFAULT_FIXTURE
    )
    parser.add_argument(
        "--output-directory", type=Path, required=True
    )
    parser.add_argument(
        "--mode",
        choices=("deterministic", "live", "all"),
        default="all",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="Run only this case id; repeat as needed.",
    )
    parser.add_argument(
        "--endpoint", default=DEFAULT_ENDPOINT
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--skip-symai", action="store_true")
    parser.add_argument("--skip-hybrid", action="store_true")
    parser.add_argument("--skip-oracle", action="store_true")
    parser.add_argument("--skip-validation", action="store_true")
    return parser


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    cases = _load_cases(args.fixture.resolve())
    if args.case:
        requested = set(args.case)
        cases = [case for case in cases if case["id"] in requested]
        missing = requested - {case["id"] for case in cases}
        if missing:
            raise BenchmarkError(
                "unknown requested cases: " + ", ".join(sorted(missing))
            )
    deterministic = args.mode in {"deterministic", "all"}
    live = args.mode in {"live", "all"}
    client = (
        LeanstralClient(
            args.endpoint,
            args.model,
            timeout_seconds=args.timeout_seconds,
        )
        if live
        else None
    )
    spacy_nlp = None
    if live and not args.skip_hybrid:
        import spacy

        spacy_nlp = spacy.load("en_core_web_sm")
    symai_runner = None
    symai_max_tokens_key = "IPFS_DATASETS_PY_SYMAI_MAX_TOKENS"
    symai_max_tokens_previous = os.environ.get(symai_max_tokens_key)
    if live and not args.skip_symai:
        # Keep bounded output generation on the shared service.
        os.environ[symai_max_tokens_key] = "384"
        try:
            symai_runner = SymaiForwardRunner(
                endpoint=args.endpoint,
                inner_model=args.model,
            )
        except Exception:
            if symai_max_tokens_previous is None:
                os.environ.pop(symai_max_tokens_key, None)
            else:
                os.environ[symai_max_tokens_key] = symai_max_tokens_previous
            raise
    capabilities = capability_inventory(
        client=client, spacy_nlp=spacy_nlp
    )
    lean_path = str(capabilities["lean"].get("path") or "")
    if not args.skip_validation and not lean_path:
        raise BenchmarkError("Lean is required for validation")

    run_started = time.perf_counter()
    run_id = "semantic-roundtrip-" + time.strftime(
        "%Y%m%dT%H%M%SZ", time.gmtime()
    )
    case_results: list[dict[str, Any]] = []
    try:
        for case in cases:
            arms: dict[str, dict[str, Any]] = {}
            if deterministic:
                arms["modal_regex"] = _safe_arm(
                    run_modal_codec, case, backend="regex"
                )
                arms["modal_spacy"] = _safe_arm(
                    run_modal_codec, case, backend="spacy"
                )
                arms["typed_deontic"] = _safe_arm(
                    run_deontic_codec, case
                )
                arms["cnl_v2"] = _safe_arm(run_cnl_v2, case)
                arms["dcec"] = _safe_arm(run_dcec, case)
            if live and client is not None:
                arms["leanstral_direct"] = _safe_arm(
                    run_leanstral_cycle, case, client
                )
                if spacy_nlp is not None:
                    arms["spacy_leanstral"] = _safe_arm(
                        run_leanstral_cycle,
                        case,
                        client,
                        nlp=spacy_nlp,
                    )
                if not args.skip_oracle:
                    arms["leanstral_oracle_reverse"] = _safe_arm(
                        run_leanstral_cycle,
                        case,
                        client,
                        oracle_l1=True,
                    )
            if symai_runner is not None:
                arms["symai_forward"] = _safe_arm(
                    symai_runner.run, case, run_id=run_id
                )
            if not args.skip_validation:
                for arm_id, arm in arms.items():
                    attach_validators_safely(
                        arm,
                        case_id=str(case["id"]),
                        arm_id=arm_id,
                        lean_path=lean_path,
                    )
            case_results.append(
                {
                    "case_id": case["id"],
                    "complexity": case.get(
                        "complexity", case.get("complexity_tier")
                    ),
                    "source_ref": case.get("source_ref"),
                    "source_text_cid": case["source_text_cid"],
                    "source_word_count": len(_tokens(case["source_text"])),
                    "gold_ir_cid": case["gold_ir_cid"],
                    "gold_rule_count": len(case["gold_ir"]["rules"]),
                    "arms": arms,
                }
            )
    finally:
        if symai_runner is not None:
            symai_runner.close()
        if live and not args.skip_symai:
            if symai_max_tokens_previous is None:
                os.environ.pop(symai_max_tokens_key, None)
            else:
                os.environ[symai_max_tokens_key] = symai_max_tokens_previous
    corpus_identity = [
        {
            "case_id": case["id"],
            "source_text_cid": case["source_text_cid"],
            "gold_ir_cid": case["gold_ir_cid"],
        }
        for case in cases
    ]
    fixture_file_cid = cid_for_bytes(args.fixture.resolve().read_bytes())
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "mode": args.mode,
        "run_configuration": {
            "fixture": str(args.fixture.resolve()),
            "output_directory": str(args.output_directory.resolve()),
            "case_ids": [str(case["id"]) for case in cases],
            "deterministic_arms_enabled": deterministic,
            "live_arms_enabled": live,
            "skip_symai": bool(args.skip_symai),
            "skip_hybrid": bool(args.skip_hybrid),
            "skip_oracle": bool(args.skip_oracle),
            "skip_validation": bool(args.skip_validation),
            "endpoint": args.endpoint if live else None,
            "model": args.model if live else None,
            "timeout_seconds": args.timeout_seconds,
            "generation_temperature": 0,
            "generation_seed": 0,
            "symai_max_tokens": (
                384 if live and not args.skip_symai else None
            ),
        },
        "methodology": {
            "path": "T0_source -> L1_logic -> T1_source_withheld_text -> L2_logic",
            "primary_scores": [
                "gold_vs_l1_forward_fidelity",
                "l1_vs_l2_cycle_consistency",
                "gold_vs_l2_end_to_end_fidelity",
            ],
            "closed_atom_vocabulary": True,
            "distractors_present": True,
            "source_withheld_from_realizers": True,
            "artifact_identity": "CIDv1/base32/dag-json-or-raw/sha2-256",
            "model_resource_note": (
                "SyMAI and direct Leanstral share one physical model service "
                "and were executed serially."
            ),
        },
        "source_state": _git_state(),
        "capabilities": capabilities,
        "corpus": {
            "fixture": str(args.fixture.resolve()),
            "fixture_file_cid": fixture_file_cid,
            "semantic_case_manifest_cid": cid_for_dag_json(
                corpus_identity
            ),
            "cid": cid_for_dag_json(
                {
                    "fixture_file_cid": fixture_file_cid,
                    "semantic_cases": corpus_identity,
                }
            ),
            "case_count": len(cases),
            "gold_rule_count": sum(
                len(case["gold_ir"]["rules"]) for case in cases
            ),
            "source_word_count": sum(
                len(_tokens(case["source_text"])) for case in cases
            ),
        },
        "cases": case_results,
        "summary": summarize_cases(case_results),
        "elapsed_seconds": round(time.perf_counter() - run_started, 9),
    }
    report["report_body_cid"] = cid_for_dag_json(report)
    return report


def write_report(report: Mapping[str, Any], output_directory: Path) -> dict[str, Any]:
    output_directory.mkdir(parents=True, exist_ok=False)
    report_path = output_directory / "semantic-roundtrip-report.json"
    summary_path = output_directory / "semantic-roundtrip-summary.md"
    report_bytes = (
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    report_path.write_bytes(report_bytes)
    summary_text = _summary_markdown(report)
    summary_path.write_text(summary_text, encoding="utf-8")
    manifest = {
        "schema_version": (
            "ipfs-datasets.semantic-logic-roundtrip-artifacts.v1"
        ),
        "run_id": report["run_id"],
        "report": {
            "path": report_path.name,
            "cid": cid_for_bytes(report_bytes),
            "bytes": len(report_bytes),
        },
        "summary": {
            "path": summary_path.name,
            "cid": cid_for_bytes(summary_text.encode("utf-8")),
            "bytes": len(summary_text.encode("utf-8")),
        },
    }
    manifest_path = output_directory / "artifact-manifest.json"
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    return {
        "output_directory": str(output_directory.resolve()),
        "report_path": str(report_path.resolve()),
        "summary_path": str(summary_path.resolve()),
        "manifest_path": str(manifest_path.resolve()),
        "manifest_cid": cid_for_bytes(manifest_bytes),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.timeout_seconds <= 0 or args.timeout_seconds > 600:
        raise SystemExit("--timeout-seconds must be in (0, 600]")
    try:
        report = run_benchmark(args)
        outputs = write_report(report, args.output_directory.resolve())
    except (BenchmarkError, OSError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": "success",
                "run_id": report["run_id"],
                "summary": report["summary"],
                **outputs,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
