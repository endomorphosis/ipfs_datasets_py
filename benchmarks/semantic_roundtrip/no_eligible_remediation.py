"""Freeze the authoritative SRT-014 no-eligible remediation evidence.

SRT-014 is an immutable measurement.  This module does not reinterpret its
scores or edit its protocol: it recomputes the repository-bound downstream
gate, verifies the complete remediation summary, and projects that summary
unchanged into the CID-bound SRT-021 manifest.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json, validate_cid

from benchmarks.semantic_roundtrip_scheduler import (
    NO_ELIGIBLE_REMEDIATION_MANIFEST_INTERFACE,
    NO_ELIGIBLE_REMEDIATION_MANIFEST_RELATIVE_PATH,
    NO_ELIGIBLE_REMEDIATION_MANIFEST_SCHEMA,
    SRT014_DOWNSTREAM_GATE_SCHEMA,
    SRT014_REPORT_RELATIVE_PATH,
    SRT014_SELECTION_GATE_IDS,
    evaluate_srt014_downstream_gate,
)


MANIFEST_INTERFACE: Final = NO_ELIGIBLE_REMEDIATION_MANIFEST_INTERFACE
MANIFEST_SCHEMA_VERSION: Final = NO_ELIGIBLE_REMEDIATION_MANIFEST_SCHEMA
MANIFEST_RELATIVE_PATH: Final = NO_ELIGIBLE_REMEDIATION_MANIFEST_RELATIVE_PATH
REPORT_RELATIVE_PATH: Final = SRT014_REPORT_RELATIVE_PATH

_GATE_FIELDS: Final = {
    "schema",
    "status",
    "launch_authorized",
    "report_path",
    "report_cid",
    "report_raw_cid",
    "selection_outcome",
    "selection_basis",
    "selectable_arm_ids",
    "implementation_representative_arm_id",
    "tie_bound",
    "reason_codes",
    "remediation",
    "gate_cid",
    "gate_cid_codec",
    "gate_cid_scope",
}
_REMEDIATION_FIELDS: Final = {
    "source_report_cid",
    "classification",
    "arm_count",
    "eligible_arm_count",
    "gate_evidence",
    "systemic_gate_ids",
    "component_local_gate_ids",
    "terminal_failure_reason_counts",
    "terminal_failure_stage_counts",
    "arms",
    "recommended_task_inputs",
    "srt015_must_remain_fenced",
    "frozen_protocol_must_not_change",
}
_ARM_FIELDS: Final = {
    "coordinate_count",
    "failed_gate_ids",
    "failed_coordinate_count_by_gate",
    "affected_case_ids_by_gate",
    "sample_coordinate_keys_by_gate",
    "terminal_failure_count",
    "terminal_failure_reason_counts",
    "terminal_failure_stage_counts",
}
_MANIFEST_FIELDS: Final = {
    "interface",
    "schema_version",
    "status",
    "source",
    "remediation",
    "protocol_immutable",
    "replacement_run_required",
    "srt015_fenced",
    "manifest_cid",
}


class NoEligibleRemediationError(ValueError):
    """Raised when SRT-014 evidence cannot support a frozen manifest."""


def _require(condition: object, message: str) -> None:
    if not condition:
        raise NoEligibleRemediationError(message)


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise NoEligibleRemediationError(f"{path} must be an object")
    return value


def _array(value: object, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise NoEligibleRemediationError(f"{path} must be an array")
    return value


def _exact_fields(
    value: Mapping[str, Any],
    expected: set[str],
    path: str,
) -> None:
    if set(value) != expected:
        raise NoEligibleRemediationError(
            f"{path} fields changed; expected {sorted(expected)}, "
            f"got {sorted(value)}"
        )


def _count(value: object, path: str, *, positive: bool = False) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < (1 if positive else 0)
    ):
        qualifier = "positive" if positive else "nonnegative"
        raise NoEligibleRemediationError(
            f"{path} must be a {qualifier} integer"
        )
    return value


def _string_array(
    value: object,
    path: str,
    *,
    unique: bool = True,
) -> list[str]:
    values = _array(value, path)
    if any(not isinstance(item, str) or not item for item in values):
        raise NoEligibleRemediationError(
            f"{path} must contain nonempty strings"
        )
    if unique and len(set(values)) != len(values):
        raise NoEligibleRemediationError(f"{path} contains duplicates")
    return values


def _counter(
    value: object,
    path: str,
) -> dict[str, int]:
    counts = _mapping(value, path)
    result: dict[str, int] = {}
    for key, count in counts.items():
        if not key:
            raise NoEligibleRemediationError(
                f"{path} keys must be nonempty strings"
            )
        result[key] = _count(count, f"{path}.{key}", positive=True)
    return result


def _canonical_cid(value: object, path: str, *, codec: str) -> str:
    try:
        return validate_cid(value, codecs=(codec,))
    except (TypeError, ValueError) as exc:
        raise NoEligibleRemediationError(
            f"{path} must be a canonical {codec} CID"
        ) from exc


def _validate_gate_identity(gate: Mapping[str, Any]) -> None:
    _require(
        gate.get("gate_cid_codec") == "dag-json",
        "SRT-014 gate CID codec changed",
    )
    _require(
        gate.get("gate_cid_scope") == "payload_without_gate_cid_fields",
        "SRT-014 gate CID scope changed",
    )
    gate_cid = _canonical_cid(
        gate.get("gate_cid"),
        "SRT-014 gate.gate_cid",
        codec="dag-json",
    )
    payload = {
        key: value
        for key, value in gate.items()
        if key not in {"gate_cid", "gate_cid_codec", "gate_cid_scope"}
    }
    _require(
        cid_for_dag_json(payload) == gate_cid,
        "SRT-014 gate CID does not match its payload",
    )


def _validate_remediation(
    value: object,
    *,
    report_cid: str,
) -> Mapping[str, Any]:
    remediation = _mapping(value, "SRT-014 gate.remediation")
    _exact_fields(remediation, _REMEDIATION_FIELDS, "SRT-014 remediation")
    _require(
        remediation.get("source_report_cid") == report_cid,
        "SRT-014 remediation source report CID is contradictory",
    )
    _require(
        remediation.get("classification")
        == "all_preregistered_arms_failed_selection_eligibility",
        "SRT-014 remediation classification changed",
    )
    _require(
        _count(remediation.get("arm_count"), "remediation.arm_count") == 30,
        "SRT-014 remediation must cover exactly 30 arms",
    )
    _require(
        _count(
            remediation.get("eligible_arm_count"),
            "remediation.eligible_arm_count",
        )
        == 0,
        "SRT-014 remediation contradicts the no-eligible outcome",
    )
    _require(
        remediation.get("srt015_must_remain_fenced") is True,
        "SRT-014 remediation must fence SRT-015",
    )
    _require(
        remediation.get("frozen_protocol_must_not_change") is True,
        "SRT-014 remediation must preserve the frozen protocol",
    )

    arms = _mapping(remediation.get("arms"), "remediation.arms")
    _require(len(arms) == 30, "SRT-014 remediation arms must contain 30 IDs")
    _require(
        all(arm_id for arm_id in arms),
        "SRT-014 remediation arm IDs must be nonempty",
    )

    gate_ids = tuple(SRT014_SELECTION_GATE_IDS)
    gate_id_set = set(gate_ids)
    affected_arm_ids: dict[str, list[str]] = {
        gate_id: [] for gate_id in gate_ids
    }
    failed_coordinate_totals = Counter(
        {gate_id: 0 for gate_id in gate_ids}
    )
    terminal_reason_totals: Counter[str] = Counter()
    terminal_stage_totals: Counter[str] = Counter()

    for arm_id, raw_summary in arms.items():
        summary = _mapping(raw_summary, f"remediation.arms.{arm_id}")
        _exact_fields(
            summary,
            _ARM_FIELDS,
            f"remediation.arms.{arm_id}",
        )
        coordinate_count = _count(
            summary.get("coordinate_count"),
            f"remediation.arms.{arm_id}.coordinate_count",
            positive=True,
        )
        failed_ids = _string_array(
            summary.get("failed_gate_ids"),
            f"remediation.arms.{arm_id}.failed_gate_ids",
        )
        _require(
            failed_ids and set(failed_ids) <= gate_id_set,
            f"remediation arm {arm_id!r} must fail a known selection gate",
        )

        failed_counts = _mapping(
            summary.get("failed_coordinate_count_by_gate"),
            f"remediation.arms.{arm_id}.failed_coordinate_count_by_gate",
        )
        affected_cases = _mapping(
            summary.get("affected_case_ids_by_gate"),
            f"remediation.arms.{arm_id}.affected_case_ids_by_gate",
        )
        sample_coordinates = _mapping(
            summary.get("sample_coordinate_keys_by_gate"),
            f"remediation.arms.{arm_id}.sample_coordinate_keys_by_gate",
        )
        for name, per_gate in (
            ("failed_coordinate_count_by_gate", failed_counts),
            ("affected_case_ids_by_gate", affected_cases),
            ("sample_coordinate_keys_by_gate", sample_coordinates),
        ):
            _require(
                set(per_gate) == gate_id_set,
                f"remediation.arms.{arm_id}.{name} gate IDs changed",
            )

        derived_failed_ids: list[str] = []
        for gate_id in gate_ids:
            failed_count = _count(
                failed_counts[gate_id],
                (
                    f"remediation.arms.{arm_id}."
                    f"failed_coordinate_count_by_gate.{gate_id}"
                ),
            )
            _require(
                failed_count <= coordinate_count,
                f"remediation arm {arm_id!r} has impossible gate counts",
            )
            cases = _string_array(
                affected_cases[gate_id],
                (
                    f"remediation.arms.{arm_id}."
                    f"affected_case_ids_by_gate.{gate_id}"
                ),
            )
            samples = _string_array(
                sample_coordinates[gate_id],
                (
                    f"remediation.arms.{arm_id}."
                    f"sample_coordinate_keys_by_gate.{gate_id}"
                ),
            )
            _require(
                len(samples) <= min(5, failed_count),
                f"remediation arm {arm_id!r} has impossible samples",
            )
            if failed_count == 0:
                _require(
                    not cases and not samples,
                    f"remediation arm {arm_id!r} has evidence for a passed gate",
                )
            else:
                _require(
                    cases and samples,
                    f"remediation arm {arm_id!r} lacks failed-gate evidence",
                )
                derived_failed_ids.append(gate_id)
                affected_arm_ids[gate_id].append(arm_id)
                failed_coordinate_totals[gate_id] += failed_count
        _require(
            failed_ids == derived_failed_ids,
            f"remediation arm {arm_id!r} failed gate IDs are contradictory",
        )

        terminal_count = _count(
            summary.get("terminal_failure_count"),
            f"remediation.arms.{arm_id}.terminal_failure_count",
        )
        _require(
            terminal_count <= coordinate_count,
            f"remediation arm {arm_id!r} has impossible terminal failures",
        )
        arm_reasons = _counter(
            summary.get("terminal_failure_reason_counts"),
            f"remediation.arms.{arm_id}.terminal_failure_reason_counts",
        )
        arm_stages = _counter(
            summary.get("terminal_failure_stage_counts"),
            f"remediation.arms.{arm_id}.terminal_failure_stage_counts",
        )
        _require(
            sum(arm_reasons.values()) == terminal_count,
            f"remediation arm {arm_id!r} terminal reason counts disagree",
        )
        _require(
            sum(arm_stages.values()) == terminal_count,
            f"remediation arm {arm_id!r} terminal stage counts disagree",
        )
        terminal_reason_totals.update(arm_reasons)
        terminal_stage_totals.update(arm_stages)

    gate_evidence = _mapping(
        remediation.get("gate_evidence"),
        "remediation.gate_evidence",
    )
    _require(
        set(gate_evidence) == gate_id_set,
        "remediation gate evidence IDs changed",
    )
    normalized_gate_evidence: dict[str, dict[str, Any]] = {}
    for gate_id in gate_ids:
        evidence = _mapping(
            gate_evidence[gate_id],
            f"remediation.gate_evidence.{gate_id}",
        )
        _exact_fields(
            evidence,
            {
                "affected_arm_count",
                "affected_arm_ids",
                "failed_coordinate_count",
            },
            f"remediation.gate_evidence.{gate_id}",
        )
        evidence_arm_ids = _string_array(
            evidence.get("affected_arm_ids"),
            f"remediation.gate_evidence.{gate_id}.affected_arm_ids",
        )
        _require(
            set(evidence_arm_ids) == set(affected_arm_ids[gate_id]),
            f"remediation gate {gate_id!r} affected arm IDs disagree",
        )
        _require(
            _count(
                evidence.get("affected_arm_count"),
                f"remediation.gate_evidence.{gate_id}.affected_arm_count",
            )
            == len(evidence_arm_ids),
            f"remediation gate {gate_id!r} affected arm count disagrees",
        )
        _require(
            _count(
                evidence.get("failed_coordinate_count"),
                f"remediation.gate_evidence.{gate_id}.failed_coordinate_count",
            )
            == failed_coordinate_totals[gate_id],
            f"remediation gate {gate_id!r} coordinate count disagrees",
        )
        normalized_gate_evidence[gate_id] = {
            "affected_arm_count": len(evidence_arm_ids),
            "affected_arm_ids": evidence_arm_ids,
            "failed_coordinate_count": failed_coordinate_totals[gate_id],
        }

    systemic_gate_ids = [
        gate_id
        for gate_id in gate_ids
        if len(affected_arm_ids[gate_id]) == len(arms)
    ]
    component_local_gate_ids = [
        gate_id
        for gate_id in gate_ids
        if affected_arm_ids[gate_id] and gate_id not in systemic_gate_ids
    ]
    _require(
        _string_array(
            remediation.get("systemic_gate_ids"),
            "remediation.systemic_gate_ids",
        )
        == systemic_gate_ids,
        "remediation systemic gate classification disagrees",
    )
    _require(
        _string_array(
            remediation.get("component_local_gate_ids"),
            "remediation.component_local_gate_ids",
        )
        == component_local_gate_ids,
        "remediation component-local gate classification disagrees",
    )

    aggregate_reasons = _counter(
        remediation.get("terminal_failure_reason_counts"),
        "remediation.terminal_failure_reason_counts",
    )
    aggregate_stages = _counter(
        remediation.get("terminal_failure_stage_counts"),
        "remediation.terminal_failure_stage_counts",
    )
    _require(
        aggregate_reasons == dict(sorted(terminal_reason_totals.items())),
        "remediation terminal failure reason counts disagree",
    )
    _require(
        aggregate_stages == dict(sorted(terminal_stage_totals.items())),
        "remediation terminal failure stage counts disagree",
    )

    expected_inputs: list[dict[str, Any]] = [
        {
            "task_kind": "diagnose_and_repair_selection_gate",
            "gate_id": gate_id,
            **normalized_gate_evidence[gate_id],
        }
        for gate_id in gate_ids
        if normalized_gate_evidence[gate_id]["failed_coordinate_count"] > 0
    ]
    if aggregate_reasons:
        expected_inputs.append(
            {
                "task_kind": "diagnose_and_repair_terminal_failures",
                "failure_reason_counts": aggregate_reasons,
                "failure_stage_counts": aggregate_stages,
            }
        )
    expected_inputs.append(
        {
            "task_kind": "execute_replacement_full_matrix",
            "protocol_action": "preserve_frozen_protocol",
            "artifact_action": "new_immutable_run_namespace_and_report",
            "requires_all_prior_remediation_receipts": True,
        }
    )
    _require(
        remediation.get("recommended_task_inputs") == expected_inputs,
        "remediation recommended inputs are missing or contradictory",
    )
    return remediation


def _validated_srt014_gate(
    repo_root: Path,
    *,
    supplied_gate: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    gate = evaluate_srt014_downstream_gate(repo_root.resolve())
    gate = _mapping(gate, "SRT-014 gate")
    _exact_fields(gate, _GATE_FIELDS, "SRT-014 gate")
    if supplied_gate is not None:
        supplied = _mapping(supplied_gate, "supplied SRT-014 gate")
        _require(
            dict(supplied) == dict(gate),
            "supplied SRT-014 gate contradicts repository evidence",
        )
    _validate_gate_identity(gate)
    _require(
        gate.get("schema") == SRT014_DOWNSTREAM_GATE_SCHEMA,
        "SRT-014 gate schema changed",
    )
    _require(
        gate.get("status") == "remediation_required",
        "SRT-014 evidence is missing or is not remediation-required",
    )
    _require(
        gate.get("launch_authorized") is False,
        "SRT-014 no-eligible gate cannot authorize launch",
    )
    _require(
        gate.get("report_path") == str(REPORT_RELATIVE_PATH),
        "SRT-014 report path changed",
    )
    _require(
        gate.get("selection_outcome") == "no_eligible_composition",
        "SRT-014 selection outcome is not no-eligible",
    )
    _require(
        gate.get("selection_basis") is None
        and gate.get("selectable_arm_ids") == []
        and gate.get("implementation_representative_arm_id") is None,
        "SRT-014 no-eligible gate contains a contradictory selection",
    )
    _require(
        gate.get("tie_bound") == 30,
        "SRT-014 gate no longer binds the 30-arm preregistration",
    )
    _require(
        gate.get("reason_codes")
        == [
            "srt014_no_eligible_composition",
            "all_preregistered_arms_failed_selection_eligibility",
        ],
        "SRT-014 no-eligible reason codes changed",
    )
    report_cid = _canonical_cid(
        gate.get("report_cid"),
        "SRT-014 gate.report_cid",
        codec="dag-json",
    )
    _canonical_cid(
        gate.get("report_raw_cid"),
        "SRT-014 gate.report_raw_cid",
        codec="raw",
    )
    _validate_remediation(gate.get("remediation"), report_cid=report_cid)
    return gate


def build_no_eligible_remediation_manifest(
    repo_root: Path,
    *,
    srt014_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build SRT-021 solely from freshly recomputed SRT-014 evidence.

    ``srt014_gate`` is an optional cache/assertion, never an authority.  When
    supplied, it must exactly equal the repository-derived receipt.
    """

    gate = _validated_srt014_gate(
        repo_root,
        supplied_gate=srt014_gate,
    )
    payload: dict[str, Any] = {
        "interface": MANIFEST_INTERFACE,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "frozen_no_eligible",
        "source": {
            "srt014_report_path": str(REPORT_RELATIVE_PATH),
            "srt014_report_cid": gate["report_cid"],
            "srt014_report_raw_cid": gate["report_raw_cid"],
            "srt014_gate_cid": gate["gate_cid"],
        },
        "remediation": copy.deepcopy(gate["remediation"]),
        "protocol_immutable": True,
        "replacement_run_required": True,
        "srt015_fenced": True,
    }
    payload["manifest_cid"] = cid_for_dag_json(payload)
    return payload


def validate_no_eligible_remediation_manifest(
    manifest: Mapping[str, Any],
    *,
    repo_root: Path,
    srt014_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the manifest after checking its exact repository-bound form."""

    value = _mapping(manifest, "no-eligible remediation manifest")
    _exact_fields(value, _MANIFEST_FIELDS, "no-eligible remediation manifest")
    manifest_cid = _canonical_cid(
        value.get("manifest_cid"),
        "manifest.manifest_cid",
        codec="dag-json",
    )
    cid_payload = dict(value)
    del cid_payload["manifest_cid"]
    _require(
        cid_for_dag_json(cid_payload) == manifest_cid,
        "manifest CID does not match payload without manifest_cid",
    )
    expected = build_no_eligible_remediation_manifest(
        repo_root,
        srt014_gate=srt014_gate,
    )
    _require(
        dict(value) == expected,
        "manifest contradicts freshly recomputed SRT-014 evidence",
    )
    return copy.deepcopy(expected)


def _load_json_object(path: Path) -> Mapping[str, Any]:
    def reject_duplicates(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise NoEligibleRemediationError(
                    f"duplicate JSON key {key!r} in {path}"
                )
            value[key] = item
        return value

    try:
        raw_value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NoEligibleRemediationError(
            f"cannot load remediation manifest: {path}"
        ) from exc
    return _mapping(raw_value, str(path))


def write_no_eligible_remediation_manifest(
    repo_root: Path,
    *,
    output_path: Path | None = None,
    srt014_gate: Mapping[str, Any] | None = None,
) -> Path:
    """Atomically create the frozen manifest, refusing a changed overwrite."""

    repo_root = repo_root.resolve()
    path = (
        output_path.resolve()
        if output_path is not None
        else repo_root / MANIFEST_RELATIVE_PATH
    )
    manifest = build_no_eligible_remediation_manifest(
        repo_root,
        srt014_gate=srt014_gate,
    )
    if path.exists():
        validate_no_eligible_remediation_manifest(
            _load_json_object(path),
            repo_root=repo_root,
            srt014_gate=srt014_gate,
        )
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(rendered)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass
    return path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or validate the frozen SRT-014 remediation manifest"
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the checked-in manifest without writing it",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    path = repo_root / MANIFEST_RELATIVE_PATH
    try:
        if args.check:
            validate_no_eligible_remediation_manifest(
                _load_json_object(path),
                repo_root=repo_root,
            )
        else:
            write_no_eligible_remediation_manifest(repo_root)
    except NoEligibleRemediationError as exc:
        print(str(exc))
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
