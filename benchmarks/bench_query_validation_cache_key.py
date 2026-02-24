#!/usr/bin/env python3
"""Micro-benchmark for QueryValidationMixin.generate_cache_key on nested payloads."""

from __future__ import annotations

import json
import time
from statistics import mean, median
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ipfs_datasets_py.optimizers.common.query_validation import QueryValidationMixin


class _BenchValidationMixin(QueryValidationMixin):
    pass


def _build_nested_payload(width: int, depth: int) -> dict:
    payload = {"level": depth, "items": []}
    current_items = payload["items"]
    for d in range(depth):
        block = {
            "depth": d,
            "items": [],
            "entities": [
                {
                    "id": f"e-{d}-{i}",
                    "name": f"Entity {d}-{i}",
                    "props": {"score": i / max(width, 1), "tags": [f"t{j}" for j in range(5)]},
                }
                for i in range(width)
            ],
            "relationships": [
                {"source": f"e-{d}-{i}", "target": f"e-{d}-{(i + 1) % max(width, 1)}", "type": "rel"}
                for i in range(width)
            ],
        }
        current_items.append(block)
        current_items = block["items"]
    return payload


def _run_case(
    mixin: _BenchValidationMixin,
    payload: dict,
    iterations: int = 200,
    include_class_name: bool = True,
) -> dict:
    samples_ms = []
    for _ in range(iterations):
        start = time.perf_counter()
        mixin.generate_cache_key(payload, include_class_name=include_class_name)
        samples_ms.append((time.perf_counter() - start) * 1000.0)
    return {
        "iterations": iterations,
        "avg_ms": round(mean(samples_ms), 4),
        "median_ms": round(median(samples_ms), 4),
        "p95_ms": round(sorted(samples_ms)[int(iterations * 0.95) - 1], 4),
        "max_ms": round(max(samples_ms), 4),
    }


def main() -> None:
    mixin = _BenchValidationMixin()
    cases = {
        "small": _build_nested_payload(width=5, depth=2),
        "medium": _build_nested_payload(width=20, depth=4),
        "large": _build_nested_payload(width=50, depth=6),
    }

    report = {
        name: {
            "include_class_name_true": _run_case(
                mixin, payload, include_class_name=True
            ),
            "include_class_name_false": _run_case(
                mixin, payload, include_class_name=False
            ),
        }
        for name, payload in cases.items()
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
