"""Stratified sampler: proportionally samples GNIS places by state.

Fixes:
- Bug #16: ``.to_dict('records')`` (was ``.to_records('records')``).
- Bug #3/factory: no incorrect kwarg passing; reference_db is passed directly.
- Uses parameterized SQL, never f-strings with user data.
"""

from __future__ import annotations

import functools
import itertools
import logging
import random
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class StratifiedSampler:
    """Stratified random sampler for GNIS places, stratified by state.

    Args:
        config: A :class:`~config.ValidatorConfig` instance.
    """

    def __init__(self, config) -> None:
        self._config = config
        self._sample_size: int = config.sample_size
        self._random_seed: int = config.random_seed

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_stratified_sample(
        self, citations: list[Path], reference_db
    ) -> tuple[dict[str, int], list[int]]:
        """Compute a stratified sample of GNIS identifiers.

        Args:
            citations: List of ``*_citation.parquet`` file paths.  The GNIS
                identifier is assumed to be the numeric prefix of the stem
                (e.g. ``1234567_citation.parquet`` → gnis ``1234567``).
            reference_db: Open database connection with a ``locations`` table.

        Returns:
            A two-tuple ``(gnis_counts_by_state, sampled_gnis_list)``.
        """
        logger.info("Computing stratified sample from %d citation files.", len(citations))
        gnis_counts_by_state = self._count_gnis_by_state(citations, reference_db)
        sample_sizes = self._calculate_sample_sizes(gnis_counts_by_state)
        sampled_gnis = self._select_sampled_places(citations, sample_sizes, reference_db)
        logger.info(
            "Selected %d places from %d states.",
            len(sampled_gnis),
            len(gnis_counts_by_state),
        )
        return gnis_counts_by_state, sampled_gnis

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _count_gnis_by_state(
        self, citations: list[Path], reference_db
    ) -> dict[str, int]:
        """Count how many GNIS identifiers from *citations* belong to each state.

        Bug #16 fix: uses ``.to_dict('records')`` not ``.to_records('records')``.
        Uses parameterized SQL (``?`` placeholders) to avoid SQL injection.
        """
        gnis_set: set[int] = {
            int(f.stem.split("_")[0]) for f in citations if f.stem.split("_")[0].isdigit()
        }

        state_rows: list[dict] = []
        for batch in itertools.batched(gnis_set, 100):
            placeholders = ", ".join("?" * len(batch))
            query = (
                f"SELECT state_code, COUNT(state_code) AS counts "
                f"FROM locations WHERE gnis IN ({placeholders}) "
                f"GROUP BY state_code"
            )
            try:
                df = reference_db.execute(query, list(batch)).fetchdf()
                state_rows.extend(df.to_dict("records"))  # Bug #16 fix
            except Exception as exc:
                logger.error("Error counting GNIS by state: %s", exc)

        # Reduce list of per-batch dicts into one cumulative dict.
        return functools.reduce(
            lambda acc, row: {
                **acc,
                row["state_code"]: acc.get(row["state_code"], 0) + row["counts"],
            },
            state_rows,
            {},
        )

    def _calculate_sample_sizes(
        self, counts: dict[str, int]
    ) -> dict[str, int]:
        """Allocate the target sample size proportionally across states.

        Guarantees at least 1 sample per state and adjusts for rounding to
        hit the exact ``sample_size`` target.
        """
        total = sum(counts.values())
        if total == 0:
            return {}

        target = self._sample_size
        strategy: dict[str, int] = {}
        allocated = 0

        for state, count in counts.items():
            proportion = count / total
            size = max(1, min(round(proportion * target), count))
            strategy[state] = size
            allocated += size

        difference = target - allocated
        if difference != 0:
            # Adjust from the largest states first.
            for state, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
                if difference == 0:
                    break
                if difference > 0 and strategy[state] < counts[state]:
                    strategy[state] += 1
                    difference -= 1
                elif difference < 0 and strategy[state] > 1:
                    strategy[state] -= 1
                    difference += 1

        return strategy

    def _select_sampled_places(
        self,
        citations: list[Path],
        sample_strategy: dict[str, int],
        reference_db,
    ) -> list[int]:
        """Randomly select GNIS identifiers according to *sample_strategy*.

        Args:
            citations: Full list of citation file paths.
            sample_strategy: Dict mapping state_code → desired sample count.
            reference_db: Open database connection.

        Returns:
            Flat list of sampled GNIS integers.
        """
        # Build gnis → state_code lookup via the reference DB.
        gnis_set: set[int] = {
            int(f.stem.split("_")[0]) for f in citations if f.stem.split("_")[0].isdigit()
        }

        gnis_to_state: dict[int, str] = {}
        for batch in itertools.batched(gnis_set, 100):
            placeholders = ", ".join("?" * len(batch))
            query = (
                f"SELECT gnis, state_code FROM locations "
                f"WHERE gnis IN ({placeholders})"
            )
            try:
                rows = reference_db.execute(query, list(batch)).fetchall()
                for gnis_val, state_code in rows:
                    gnis_to_state[int(gnis_val)] = state_code
            except Exception as exc:
                logger.error("Error building gnis→state lookup: %s", exc)

        # Group GNIS by state.
        by_state: dict[str, list[int]] = {}
        for gnis_val, state_code in gnis_to_state.items():
            by_state.setdefault(state_code, []).append(gnis_val)

        # Apply random seed before sampling for reproducibility.
        rng = random.Random(self._random_seed)
        sampled: list[int] = []
        for state, desired in sample_strategy.items():
            available = by_state.get(state, [])
            k = min(desired, len(available))
            sampled.extend(rng.sample(available, k))

        return sampled
