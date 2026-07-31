#!/usr/bin/env python3
"""Evaluate Solidity CPT formalizer leakage, grounding, abstention, and provers.

The command is offline by default.  ``--fixture-offline`` runs the repository's
deterministic multi-metric fixture covering held-out and adversarial controls.
It never downloads models, contacts a network, publishes artifacts, or treats
approximate / model / SAT / simulation / unexecuted claims as proof.

Uncertainty and unsupported coverage are reported as separate metric slices.
A single accuracy score is never emitted as promotion authority.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes  # noqa: E402
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.evaluation import (  # noqa: E402
    EvaluationAuthorityError,
    EvaluationContractError,
    EvaluationIntegrityError,
    EvaluationLeakageError,
    EvaluationMode,
    EvaluationPromotionError,
    ExternalLabelCorpusAdmission,
    ProverAgreement,
    SolidityFormalEvaluation,
    SolidityFormalEvaluator,
    build_offline_fixture_evaluation,
    verify_evaluation_receipt,
)

MAX_REQUEST_BYTES: Final = 2 * 1024 * 1024
MAX_CASES_BYTES: Final = 16 * 1024 * 1024
MAX_CASES: Final = 100_000


class EvaluationCommandError(RuntimeError):
    """Safe user-facing command failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a content-addressed multi-metric Solidity CPT formalizer "
            "evaluation without network access or model download "
            "(dry-run fixture by default)."
        )
    )
    parser.add_argument(
        "--cases",
        type=Path,
        help=(
            "Optional bounded JSON array of evaluation case objects. "
            "When omitted with --fixture-offline, the deterministic fixture is used."
        ),
    )
    parser.add_argument(
        "--bindings",
        type=Path,
        help=(
            "Optional JSON object binding source/graph/index/partition/license/"
            "model CIDs and optional external-label admission. Required when "
            "supplying --cases without --fixture-offline."
        ),
    )
    parser.add_argument(
        "--fixture-offline",
        action="store_true",
        help=(
            "Run the deterministic offline multi-metric fixture evaluation. "
            "This validates leakage, grounding, abstention, calibration, and "
            "prover-agreement contracts without executing provers."
        ),
    )
    parser.add_argument(
        "--require-promotion",
        action="store_true",
        help=(
            "Exit non-zero unless the promotion gate passes "
            "(zero leakage, zero false proofs, full control coverage)."
        ),
    )
    parser.add_argument(
        "--receipt-out",
        type=Path,
        help="Atomically write the evaluation receipt as canonical JSON.",
    )
    return parser


def _bounded_regular_file(path: Path, *, maximum: int, label: str) -> bytes:
    try:
        stat = path.stat()
    except OSError as exc:
        raise EvaluationCommandError(f"cannot inspect {label}") from exc
    if path.is_symlink() or not path.is_file():
        raise EvaluationCommandError(f"{label} must be a regular non-symlink file")
    if stat.st_size > maximum:
        raise EvaluationCommandError(f"{label} exceeds its byte budget")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise EvaluationCommandError(f"cannot read {label}") from exc


def _json_value(content: bytes, label: str) -> Any:
    try:
        return json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluationCommandError(f"{label} must be UTF-8 JSON") from exc


def _load_cases(path: Path | None) -> tuple[Mapping[str, Any], ...]:
    if path is None:
        return ()
    value = _json_value(
        _bounded_regular_file(path, maximum=MAX_CASES_BYTES, label="cases file"),
        "cases file",
    )
    if not isinstance(value, list):
        raise EvaluationCommandError("cases file must contain a JSON array")
    if len(value) > MAX_CASES:
        raise EvaluationCommandError("cases file exceeds its case-count budget")
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise EvaluationCommandError(
                f"cases file item {index} must be a JSON object"
            )
        result.append(item)
    return tuple(result)


def _load_bindings(path: Path | None) -> Mapping[str, Any]:
    if path is None:
        return {}
    value = _json_value(
        _bounded_regular_file(
            path, maximum=MAX_REQUEST_BYTES, label="bindings file"
        ),
        "bindings file",
    )
    if not isinstance(value, Mapping):
        raise EvaluationCommandError("bindings file must contain a JSON object")
    return value


def _optional_external(
    value: Any,
) -> ExternalLabelCorpusAdmission | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise EvaluationCommandError(
            "external_label_admission must be a JSON object or null"
        )
    try:
        return ExternalLabelCorpusAdmission.from_dict(value)
    except (EvaluationContractError, EvaluationAuthorityError) as exc:
        raise EvaluationCommandError(
            f"external_label_admission rejected: {exc}"
        ) from exc


def _optional_agreements(
    value: Any,
) -> tuple[ProverAgreement, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise EvaluationCommandError("prover_agreements must be a JSON array")
    result: list[ProverAgreement] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise EvaluationCommandError(
                f"prover_agreements item {index} must be a JSON object"
            )
        try:
            result.append(ProverAgreement.from_dict(item))
        except (EvaluationContractError, EvaluationIntegrityError) as exc:
            raise EvaluationCommandError(
                f"prover_agreements item {index} rejected: {exc}"
            ) from exc
    return tuple(result)


def _evaluate_from_inputs(
    *,
    cases: Sequence[Mapping[str, Any]],
    bindings: Mapping[str, Any],
    fixture_offline: bool,
) -> SolidityFormalEvaluation:
    if fixture_offline and not cases and not bindings:
        return build_offline_fixture_evaluation(
            mode=EvaluationMode.FIXTURE_OFFLINE
        )
    if fixture_offline and not cases:
        # Bindings may override fixture CIDs while still using fixture cases.
        fixture = build_offline_fixture_evaluation(
            mode=EvaluationMode.FIXTURE_OFFLINE
        )
        payload = fixture.to_dict()
        for key in (
            "source_cid",
            "graph_cid",
            "index_cid",
            "partition_cid",
            "license_cid",
            "model_or_checkpoint_cid",
        ):
            if key in bindings:
                payload[key] = bindings[key]
        payload.pop("evaluation_cid", None)
        payload.pop("promotion_gate", None)
        if "external_label_admission" in bindings:
            payload["external_label_admission"] = bindings[
                "external_label_admission"
            ]
        if "prover_agreements" in bindings:
            payload["prover_agreements"] = bindings["prover_agreements"]
        if "diagnostics" in bindings:
            payload["diagnostics"] = bindings["diagnostics"]
        try:
            return SolidityFormalEvaluation.from_dict(payload)
        except (
            EvaluationContractError,
            EvaluationAuthorityError,
            EvaluationIntegrityError,
        ) as exc:
            raise EvaluationCommandError(f"evaluation rejected: {exc}") from exc

    required = (
        "source_cid",
        "graph_cid",
        "index_cid",
        "partition_cid",
        "license_cid",
        "model_or_checkpoint_cid",
    )
    missing = [key for key in required if key not in bindings]
    if missing:
        raise EvaluationCommandError(
            "bindings must include: " + ", ".join(missing)
        )
    if not cases:
        raise EvaluationCommandError(
            "cases are required unless --fixture-offline is used"
        )
    mode = (
        EvaluationMode.FIXTURE_OFFLINE
        if fixture_offline
        else EvaluationMode.DRY_RUN
    )
    try:
        evaluator = SolidityFormalEvaluator(
            source_cid=str(bindings["source_cid"]),
            graph_cid=str(bindings["graph_cid"]),
            index_cid=str(bindings["index_cid"]),
            partition_cid=str(bindings["partition_cid"]),
            license_cid=str(bindings["license_cid"]),
            model_or_checkpoint_cid=str(bindings["model_or_checkpoint_cid"]),
            evaluation_partitions=tuple(
                bindings.get(
                    "evaluation_partitions",
                    ("validation", "test", "held_out", "adversarial"),
                )
            ),
            external_label_admission=_optional_external(
                bindings.get("external_label_admission")
            ),
            mode=mode,
            diagnostics=tuple(bindings.get("diagnostics", ())),
        )
        return evaluator.evaluate(
            cases,
            prover_agreements=_optional_agreements(
                bindings.get("prover_agreements")
            ),
        )
    except (
        EvaluationContractError,
        EvaluationAuthorityError,
        EvaluationIntegrityError,
    ) as exc:
        raise EvaluationCommandError(f"evaluation rejected: {exc}") from exc


def _atomic_write(path: Path, content: bytes) -> None:
    parent = path.parent
    if not parent.is_dir():
        raise EvaluationCommandError("receipt output parent must already exist")
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise EvaluationCommandError(
            "receipt output must be absent or a regular non-symlink file"
        )
    temporary_name = ""
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=parent
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = ""
    except OSError as exc:
        raise EvaluationCommandError("cannot atomically write receipt") from exc
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not args.fixture_offline and args.cases is None and args.bindings is None:
            # Safe default: deterministic dry-run fixture without promotion gate.
            evaluation = build_offline_fixture_evaluation(
                mode=EvaluationMode.DRY_RUN
            )
        else:
            evaluation = _evaluate_from_inputs(
                cases=_load_cases(args.cases),
                bindings=_load_bindings(args.bindings),
                fixture_offline=args.fixture_offline,
            )
        verified = verify_evaluation_receipt(evaluation)
        if args.require_promotion:
            verified.require_promotion_safe()
        content = canonical_json_bytes(verified.to_dict()) + b"\n"
        if args.receipt_out is not None:
            _atomic_write(args.receipt_out, content)
        sys.stdout.buffer.write(content)
        sys.stdout.buffer.flush()
        return 0
    except (
        EvaluationCommandError,
        EvaluationContractError,
        EvaluationAuthorityError,
        EvaluationIntegrityError,
        EvaluationLeakageError,
        EvaluationPromotionError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
