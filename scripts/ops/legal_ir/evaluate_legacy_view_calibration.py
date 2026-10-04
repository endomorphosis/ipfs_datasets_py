#!/usr/bin/env python3
"""Search and report calibrated legacy feature-to-LegalIR-view transfer.

The input contains only validation/development observations and an immutable
canary digest commitment.  Canary observations are deliberately rejected by
this command; a separate post-selection evaluator must produce canary reports
for ``promote_legacy_view_calibration``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_legacy_view_calibration import (  # noqa: E402
    LegacyViewCalibrationError,
    LegacyViewCalibrationExample,
    LegacyViewCalibrationLineage,
    LegacyViewCalibrationSearchSpace,
    search_legacy_view_calibration,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help=(
            "JSON search packet containing lineage, split_manifest, "
            "development_examples, and current/legacy feature logit tables."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination for the source-free, content-addressed search report.",
    )
    parser.add_argument(
        "--regression-tolerance",
        type=float,
        default=0.0,
        help="Maximum numerical per-family regression tolerated during search.",
    )
    return parser


def _load_mapping(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LegacyViewCalibrationError(
            f"cannot read calibration packet {path}: {exc}"
        ) from exc
    if not isinstance(value, Mapping):
        raise LegacyViewCalibrationError(
            "calibration input must be a JSON object"
        )
    return dict(value)


def _reject_canary_exposure(packet: Mapping[str, Any]) -> None:
    forbidden = {
        "canary_examples",
        "canary_evaluation",
        "canary_metrics",
        "canary_observations",
        "immutable_canary_examples",
    }
    exposed: set[str] = set()

    def inspect(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                text = str(key)
                if text in forbidden:
                    exposed.add(text)
                inspect(item)
        elif isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            for item in value:
                inspect(item)

    inspect(packet)
    if exposed:
        raise LegacyViewCalibrationError(
            "immutable canary must remain hidden during search; exposed keys: "
            + ", ".join(sorted(exposed))
        )
    canary = packet.get("canary")
    if isinstance(canary, Mapping):
        extra = set(canary) - {
            "artifact_sha256",
            "hidden",
            "immutable",
        }
        if extra:
            raise LegacyViewCalibrationError(
                "canary section may contain only its immutable digest commitment"
            )


def _write_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def evaluate_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate an already-decoded packet; useful to operational callers/tests."""

    _reject_canary_exposure(packet)
    lineage_payload = packet.get("lineage")
    split_manifest = packet.get("split_manifest")
    raw_examples = packet.get(
        "development_examples", packet.get("examples")
    )
    if not isinstance(lineage_payload, Mapping):
        raise LegacyViewCalibrationError("input is missing lineage")
    if not isinstance(split_manifest, Mapping):
        raise LegacyViewCalibrationError("input is missing split_manifest")
    if not isinstance(raw_examples, Sequence) or isinstance(
        raw_examples, (str, bytes, bytearray)
    ):
        raise LegacyViewCalibrationError(
            "input is missing development_examples"
        )
    current = packet.get(
        "current_feature_legal_ir_view_logits",
        packet.get("student_feature_legal_ir_view_logits", {}),
    )
    legacy = packet.get(
        "legacy_feature_legal_ir_view_logits",
        packet.get("teacher_feature_legal_ir_view_logits", {}),
    )
    if not isinstance(current, Mapping) or not isinstance(legacy, Mapping):
        raise LegacyViewCalibrationError(
            "current and legacy feature logit tables must be mappings"
        )
    examples = tuple(
        LegacyViewCalibrationExample.from_mapping(
            item,
            current_feature_logits=current,
            legacy_feature_logits=legacy,
        )
        for item in raw_examples
        if isinstance(item, Mapping)
    )
    if len(examples) != len(raw_examples):
        raise LegacyViewCalibrationError(
            "every development example must be a JSON object"
        )
    raw_space = packet.get("search_space", {})
    if not isinstance(raw_space, Mapping):
        raise LegacyViewCalibrationError("search_space must be a mapping")
    result = search_legacy_view_calibration(
        examples,
        lineage=LegacyViewCalibrationLineage.from_mapping(lineage_payload),
        split_manifest=split_manifest,
        search_space=LegacyViewCalibrationSearchSpace.from_mapping(raw_space),
        regression_tolerance=packet.get("regression_tolerance", 0.0),
    )
    return result.to_dict()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite output: {output}")
    try:
        packet = _load_mapping(args.input.resolve())
        if args.regression_tolerance:
            packet["regression_tolerance"] = args.regression_tolerance
        report = evaluate_packet(packet)
        _write_atomic(output, report)
    except LegacyViewCalibrationError as exc:
        raise SystemExit(
            f"legacy view calibration evaluation failed: {exc}"
        ) from exc
    print(
        "decision=development_search_complete "
        f"selected_config={report['config_digest']} "
        f"evaluated_candidates={report['evaluated_candidate_count']} "
        f"rejected_candidates={report['rejected_candidate_count']} "
        "canary_hidden=true "
        f"output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
