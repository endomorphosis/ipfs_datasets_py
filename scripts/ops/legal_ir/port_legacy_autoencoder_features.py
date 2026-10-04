#!/usr/bin/env python3
"""Port a legacy autoencoder state into a selected proof-aware checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_hparam_execution import (  # noqa: E402
    _verify_embedded_report_digest,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (  # noqa: E402
    MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION,
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import (  # noqa: E402
    CHECKPOINT_MAGIC,
    write_checkpoint_atomic,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_feature_transfer import (  # noqa: E402
    DEFAULT_LEGACY_FEATURE_TRANSFER_CAPACITY,
    MODAL_AUTOENCODER_FEATURE_TRANSFER_SCHEMA_VERSION,
    LegacyFeatureTransferConfig,
    transfer_legacy_autoencoder_features,
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _declared_architecture(path: Path) -> str:
    with path.open("rb") as handle:
        prefix = handle.read(len(CHECKPOINT_MAGIC))
    if prefix == CHECKPOINT_MAGIC:
        return ModalAutoencoderTrainingState.load_json(path).architecture_version
    value = _load_json(path)
    return str(
        value.get("architecture_version")
        or MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION
    )


def _verify_selected_target(
    selection_path: Path,
    target_path: Path,
) -> dict[str, Any]:
    selection = _load_json(selection_path)
    embedded_digest = _verify_embedded_report_digest(selection)
    if selection.get("promotion_eligible") is not True:
        raise ValueError("hparam selection is not promotion eligible")
    if (
        selection.get("selection_evidence_mode")
        != "verified_immutable_posthoc_rescore"
    ):
        raise ValueError(
            "feature transfer requires verified immutable posthoc selection evidence"
        )
    candidate = _mapping(selection.get("selected_candidate"))
    candidate_id = str(candidate.get("candidate_id") or "")
    primary_seed = int(candidate.get("seed", -1))
    selected_states = _mapping(selection.get("selected_seed_states"))
    expected_target = Path(str(selected_states.get(str(primary_seed)) or "")).resolve()
    if expected_target != target_path.resolve():
        raise ValueError(
            "target state must be the selected candidate's primary seed state: "
            f"{expected_target}"
        )

    matching_records = [
        record
        for record in selection.get("run_records", [])
        if isinstance(record, Mapping)
        and str(record.get("candidate_id") or "") == candidate_id
        and int(record.get("seed", -1)) == primary_seed
        and Path(str(record.get("state_path") or "")).resolve() == target_path.resolve()
    ]
    if len(matching_records) != 1:
        raise ValueError("selected target has no unique final run record")
    record = matching_records[0]
    observed_target_hash = _sha256_file(target_path)
    if record.get("state_sha256") != observed_target_hash:
        raise ValueError("selected target checkpoint digest mismatch")
    return {
        "candidate_id": candidate_id,
        "params": dict(_mapping(candidate.get("params"))),
        "primary_seed": primary_seed,
        "selection_embedded_sha256": embedded_digest,
        "selection_file_sha256": _sha256_file(selection_path),
        "selection_path": str(selection_path),
        "target_state_sha256": observed_target_hash,
        "training_revision": _mapping(
            selection.get("rescore_provenance")
        ).get("training_revision"),
    }


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-state", type=Path, required=True)
    parser.add_argument("--target-state", type=Path, required=True)
    parser.add_argument("--selection-report", type=Path, required=True)
    parser.add_argument("--output-state", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument(
        "--max-entries-per-group",
        type=int,
        default=DEFAULT_LEGACY_FEATURE_TRANSFER_CAPACITY,
    )
    parser.add_argument(
        "--minimum-source-signal-coverage",
        type=float,
        default=0.95,
    )
    parser.add_argument(
        "--transfer-legacy-embeddings",
        action="store_true",
        help=(
            "Activate legacy-only embedding vectors. Disabled by default because "
            "they require a held-out cosine gate."
        ),
    )
    parser.add_argument(
        "--source-field",
        action="append",
        default=[],
        help=(
            "Transfer only this reusable state field; repeatable. By default all "
            "non-embedding fields are eligible."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    legacy_path = args.legacy_state.resolve()
    target_path = args.target_state.resolve()
    selection_path = args.selection_report.resolve()
    output_state = args.output_state.resolve()
    output_report = args.output_report.resolve()
    for path in (legacy_path, target_path, selection_path):
        if not path.is_file():
            raise SystemExit(f"required input does not exist: {path}")
    for path in (output_state, output_report):
        if path.exists():
            raise SystemExit(f"refusing to overwrite output: {path}")

    selection_lineage = _verify_selected_target(selection_path, target_path)
    legacy_hash = _sha256_file(legacy_path)
    legacy_architecture = _declared_architecture(legacy_path)
    legacy = ModalAutoencoderTrainingState.load_json(legacy_path)
    target = ModalAutoencoderTrainingState.load_json(target_path)
    result = transfer_legacy_autoencoder_features(
        legacy,
        target,
        config=LegacyFeatureTransferConfig(
            max_entries_per_group=args.max_entries_per_group,
            minimum_source_signal_coverage=(
                args.minimum_source_signal_coverage
            ),
            transfer_source_embedding_weights=args.transfer_legacy_embeddings,
            source_field_allowlist=tuple(sorted(set(args.source_field))),
        ),
        source_architecture_version=legacy_architecture,
    )
    if not result.accepted:
        raise SystemExit(
            "legacy feature transfer rejected: "
            f"source signal coverage={result.report['source_signal_coverage']:.9f}"
        )

    checkpoint_manifest = write_checkpoint_atomic(
        output_state,
        result.state,
        metadata={
            "feature_transfer_schema_version": (
                MODAL_AUTOENCODER_FEATURE_TRANSFER_SCHEMA_VERSION
            ),
            "legacy_state_sha256": legacy_hash,
            "required_max_generalizable_entries_per_group": int(
                result.report["capacity"]
            ),
            "selection_embedded_sha256": selection_lineage[
                "selection_embedded_sha256"
            ],
            "target_state_sha256": selection_lineage["target_state_sha256"],
        },
    )
    reloaded = ModalAutoencoderTrainingState.load_json(output_state)
    if reloaded.to_dict() != result.state.to_dict():
        raise SystemExit("feature transfer checkpoint failed exact round-trip")

    report = dict(result.report)
    report.update(
        {
            "artifacts": {
                "legacy_state": {
                    "path": str(legacy_path),
                    "sha256": legacy_hash,
                },
                "output_state": {
                    "bytes": output_state.stat().st_size,
                    "checkpoint_id": checkpoint_manifest.checkpoint_id,
                    "path": str(output_state),
                    "sha256": _sha256_file(output_state),
                    "state_digest": checkpoint_manifest.state_digest,
                },
                "target_state": {
                    "path": str(target_path),
                    "sha256": selection_lineage["target_state_sha256"],
                },
            },
            "required_runtime": {
                "autoencoder_canonical_warm_start": "off",
                "autoencoder_max_generalizable_entries_per_group": int(
                    result.report["capacity"]
                ),
                "warm_start_state": str(output_state),
            },
            "selection_lineage": selection_lineage,
        }
    )
    report["report_sha256"] = _sha256_value(report)
    _atomic_json(output_report, report)
    print(
        f"accepted=true source_signal_coverage="
        f"{report['source_signal_coverage']:.9f} "
        f"output={output_state} report={output_report}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
