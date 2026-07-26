#!/usr/bin/env python3
"""Run the fair eight-cell semantic round-trip composition matrix."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.logic_pipeline.content_addressing import (  # noqa: E402
    canonical_dag_json_bytes,
)
from benchmarks.semantic_roundtrip.constructors.leanstral import (  # noqa: E402
    LeanstralClient,
)
from benchmarks.semantic_roundtrip.matrix import (  # noqa: E402
    default_matrix,
    load_matrix_cases,
)
from benchmarks.semantic_roundtrip_capabilities import (  # noqa: E402
    SPACY_MODEL,
)


DEFAULT_FIXTURE = (
    REPO_ROOT / "tests/fixtures/semantic_roundtrip/pilot_cases.json"
)


def _load_spacy_pipeline() -> object | None:
    """Load the declared model once; adapters report absence as a failure."""

    try:
        import spacy

        return spacy.load(SPACY_MODEL)
    except (ImportError, OSError, RuntimeError):
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run typed, modal-spaCy, direct Leanstral, and spaCy-Leanstral "
            "constructors against deterministic and Leanstral realizers."
        )
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="JSON case fixture (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write canonical JSON to this path instead of stdout",
    )
    return parser


def run(fixture: Path) -> dict[str, object]:
    cases = load_matrix_cases(fixture)
    client = LeanstralClient()
    matrix = default_matrix(
        leanstral_client=client,
        spacy_pipeline=_load_spacy_pipeline(),
    )
    return matrix.run(cases).to_dict()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run(args.fixture)
    raw = canonical_dag_json_bytes(report) + b"\n"
    if args.output is None:
        sys.stdout.buffer.write(raw)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(raw)
        print(
            json.dumps(
                {
                    "status": "success",
                    "output": str(args.output),
                    "run_cid": report["run_cid"],
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
