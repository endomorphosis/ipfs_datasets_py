"""Run-scoped HSSL-G210 causal proof-ablation boundary.

The frozen revision-1 ablation registry and the source-only G200 protocol are
immutable.  This module adds a separate, content-addressed G210 boundary that
can reveal reviewed proof obligations only after the semantic producers have
finished.  It never treats a solver or model verdict as proof authority.

The public rescue manifest deliberately contains no source text, expected
semantic class, expected IR, kernel outcome, or optional-component outcome.
It binds source bytes by CID and retains only the reviewed obligation needed
at the proof boundary.  Selection must happen before any optional producer is
run, and holdout is forbidden.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Final, Mapping, Sequence, Self

from .ablation import AblationPlan, AblationValidationError, ScheduledCase
from .content_addressing import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)
from .contracts import (
    CAUSAL_PROOF_PROTOCOL_V2_CID,
    CAUSAL_PROOF_RESCUE_POPULATION_V2_CID,
    CAUSAL_PROOF_SELECTION_SPEC_V2_CID,
    CAUSAL_PROOF_VARIANT_PROFILE_V2_CID,
    SEMANTIC_CALIBRATION_CASE_COUNT_V2,
    SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2,
    SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID,
    SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID,
    SEMANTIC_PRODUCER_IDS_V2,
    CacheMode,
    SEMANTIC_PROTOCOL_V2_CID,
    SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID,
    Split,
    validate_causal_proof_selection_receipt,
)
from .runtime import (
    CausalProofCandidate,
    CausalProofGraphController,
    CausalProofGraphResult,
)


CAUSAL_RESCUE_CASE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.causal-rescue-case.v2"
)
CAUSAL_RESCUE_MANIFEST_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.causal-rescue-manifest.v2"
)
CAUSAL_RESCUE_COMPONENTS_V2: Final = ("hammer", "leanstral")
CAUSAL_REFERENCE_FAILURE_CONDITION_V2: Final = (
    "compiler_reference_absent_or_independently_rejected"
)
CAUSAL_EXECUTION_PROFILE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "causal-proof-execution-profile.v2"
)
CAUSAL_ABLATION_RESULT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.causal-proof-result.v2"
)
SEMANTIC_CALIBRATION_REPORT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.semantic-calibration-report.v2"
)


class CausalAblationError(ValueError):
    """Raised before a malformed or outcome-informed G210 run can execute."""


def _safe_id(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or not value[0].isalnum()
        or any(
            not (character.isalnum() or character in "._-")
            for character in value
        )
        or value in {".", ".."}
    ):
        raise CausalAblationError(
            f"{field} must be a safe 1-128 character identifier"
        )
    return value


def _cid(
    value: object,
    field: str,
    *,
    codecs: tuple[str, ...] = ("dag-json",),
) -> str:
    try:
        return validate_cid(value, codecs=codecs)
    except (TypeError, ValueError) as exc:
        raise CausalAblationError(
            f"{field} must be a canonical CIDv1/base32/sha2-256 value"
        ) from exc


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise CausalAblationError(f"{field} must be an object")
    return value


def _exact(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    if set(value) != expected:
        raise CausalAblationError(
            f"{field} fields changed: "
            f"missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def _proof_obligation(
    value: object,
    field: str = "proof_obligation",
) -> Mapping[str, str]:
    raw = _mapping(value, field)
    _exact(raw, {"kind", "logic", "target"}, field)
    kind = raw["kind"]
    logic = raw["logic"]
    target = raw["target"]
    if (
        kind not in {"theorem", "countermodel"}
        or logic not in {"fol", "deontic", "temporal"}
        or not isinstance(target, str)
        or not target.strip()
        or len(target.encode("utf-8")) > 4_096
    ):
        raise CausalAblationError(
            f"{field} is not a bounded reviewed proof obligation"
        )
    return MappingProxyType(
        {"kind": str(kind), "logic": str(logic), "target": target}
    )


def _components(value: object) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise CausalAblationError("optional_components must be an array")
    components = tuple(value)
    expected_order = tuple(
        component
        for component in CAUSAL_RESCUE_COMPONENTS_V2
        if component in components
    )
    if (
        not components
        or components != expected_order
        or len(components) != len(set(components))
    ):
        raise CausalAblationError(
            "optional_components must be a nonempty canonical subset of "
            f"{CAUSAL_RESCUE_COMPONENTS_V2!r}"
        )
    return components  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class CausalRescueCaseV2:
    """One preregistered pilot/development proof-boundary case.

    ``source_cid`` joins the entry to the source-only G200 plan without
    copying source text into this record.  ``review_attestation_cid`` belongs
    to the external review record; a content address alone does not assert
    that review happened.
    """

    case_id: str
    split: Split
    source_cid: str
    obligation_id: str
    proof_obligation: Mapping[str, str]
    optional_components: tuple[str, ...]
    review_attestation_cid: str
    deterministic_reference_condition: str = (
        CAUSAL_REFERENCE_FAILURE_CONDITION_V2
    )
    selected_before_optional_outcomes: bool = True
    schema: str = CAUSAL_RESCUE_CASE_SCHEMA_V2

    def __post_init__(self) -> None:
        if self.schema != CAUSAL_RESCUE_CASE_SCHEMA_V2:
            raise CausalAblationError("unsupported causal-rescue-case schema")
        object.__setattr__(self, "case_id", _safe_id(self.case_id, "case_id"))
        if self.split not in {Split.PILOT, Split.DEVELOPMENT}:
            raise CausalAblationError(
                "causal rescue cases are pilot/development only"
            )
        object.__setattr__(
            self,
            "source_cid",
            _cid(self.source_cid, "source_cid", codecs=("raw",)),
        )
        object.__setattr__(
            self,
            "obligation_id",
            _safe_id(self.obligation_id, "obligation_id"),
        )
        object.__setattr__(
            self,
            "proof_obligation",
            _proof_obligation(self.proof_obligation),
        )
        object.__setattr__(
            self,
            "optional_components",
            _components(self.optional_components),
        )
        object.__setattr__(
            self,
            "review_attestation_cid",
            _cid(
                self.review_attestation_cid,
                "review_attestation_cid",
                codecs=("dag-json",),
            ),
        )
        if (
            self.deterministic_reference_condition
            != CAUSAL_REFERENCE_FAILURE_CONDITION_V2
            or self.selected_before_optional_outcomes is not True
        ):
            raise CausalAblationError(
                "rescue cases must be selected before outcomes under the "
                "frozen compiler-reference failure condition"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "case_id": self.case_id,
            "split": self.split.value,
            "source_cid": self.source_cid,
            "obligation_id": self.obligation_id,
            "proof_obligation": dict(self.proof_obligation),
            "optional_components": list(self.optional_components),
            "review_attestation_cid": self.review_attestation_cid,
            "deterministic_reference_condition": (
                self.deterministic_reference_condition
            ),
            "selected_before_optional_outcomes": (
                self.selected_before_optional_outcomes
            ),
        }

    @property
    def case_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "case_cid": self.case_cid}

    @property
    def proof_context(self) -> dict[str, object]:
        """Return the exact object permitted across the proof boundary."""

        return {
            "obligation_id": self.obligation_id,
            "proof_obligation": dict(self.proof_obligation),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "causal_rescue_case")
        _exact(
            data,
            {
                "schema",
                "case_id",
                "split",
                "source_cid",
                "obligation_id",
                "proof_obligation",
                "optional_components",
                "review_attestation_cid",
                "deterministic_reference_condition",
                "selected_before_optional_outcomes",
                "case_cid",
            },
            "causal_rescue_case",
        )
        components = data["optional_components"]
        if not isinstance(components, list):
            raise CausalAblationError(
                "causal_rescue_case.optional_components must be an array"
            )
        try:
            split = Split(data["split"])
        except (TypeError, ValueError) as exc:
            raise CausalAblationError(
                "causal_rescue_case.split is unsupported"
            ) from exc
        result = cls(
            schema=data["schema"],  # type: ignore[arg-type]
            case_id=data["case_id"],  # type: ignore[arg-type]
            split=split,
            source_cid=data["source_cid"],  # type: ignore[arg-type]
            obligation_id=data["obligation_id"],  # type: ignore[arg-type]
            proof_obligation=_mapping(
                data["proof_obligation"], "proof_obligation"
            ),  # type: ignore[arg-type]
            optional_components=tuple(components),  # type: ignore[arg-type]
            review_attestation_cid=data[
                "review_attestation_cid"
            ],  # type: ignore[arg-type]
            deterministic_reference_condition=data[
                "deterministic_reference_condition"
            ],  # type: ignore[arg-type]
            selected_before_optional_outcomes=data[
                "selected_before_optional_outcomes"
            ],  # type: ignore[arg-type]
        )
        if data["case_cid"] != result.case_cid:
            raise CausalAblationError("causal rescue case CID changed")
        return result


@dataclass(frozen=True, slots=True)
class CausalRescueManifestV2:
    """Frozen non-holdout rescue population for a single source-only plan."""

    plan_cid: str
    source_manifest_cid: str
    case_manifest_sha256: str
    cases: tuple[CausalRescueCaseV2, ...]
    semantic_protocol_cid: str = SEMANTIC_PROTOCOL_V2_CID
    causal_proof_protocol_cid: str = CAUSAL_PROOF_PROTOCOL_V2_CID
    rescue_population_policy_cid: str = (
        CAUSAL_PROOF_RESCUE_POPULATION_V2_CID
    )
    frozen: bool = True
    holdout_included: bool = False
    schema: str = CAUSAL_RESCUE_MANIFEST_SCHEMA_V2

    def __post_init__(self) -> None:
        if self.schema != CAUSAL_RESCUE_MANIFEST_SCHEMA_V2:
            raise CausalAblationError(
                "unsupported causal-rescue-manifest schema"
            )
        for name, expected in (
            ("semantic_protocol_cid", SEMANTIC_PROTOCOL_V2_CID),
            ("causal_proof_protocol_cid", CAUSAL_PROOF_PROTOCOL_V2_CID),
            (
                "rescue_population_policy_cid",
                CAUSAL_PROOF_RESCUE_POPULATION_V2_CID,
            ),
        ):
            actual = _cid(getattr(self, name), name)
            if actual != expected:
                raise CausalAblationError(
                    f"{name} differs from the frozen G210 protocol"
                )
        object.__setattr__(
            self,
            "plan_cid",
            _cid(self.plan_cid, "plan_cid"),
        )
        object.__setattr__(
            self,
            "source_manifest_cid",
            _cid(self.source_manifest_cid, "source_manifest_cid"),
        )
        if (
            not isinstance(self.case_manifest_sha256, str)
            or len(self.case_manifest_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.case_manifest_sha256
            )
        ):
            raise CausalAblationError(
                "case_manifest_sha256 must retain the legacy source join"
            )
        cases = tuple(self.cases)
        if (
            not cases
            or any(not isinstance(case, CausalRescueCaseV2) for case in cases)
            or tuple(case.case_id for case in cases)
            != tuple(sorted(case.case_id for case in cases))
            or len({case.case_id for case in cases}) != len(cases)
            or len({case.case_cid for case in cases}) != len(cases)
        ):
            raise CausalAblationError(
                "causal rescue cases must be nonempty, unique, and sorted"
            )
        coverage = {
            component: sum(
                component in case.optional_components for case in cases
            )
            for component in CAUSAL_RESCUE_COMPONENTS_V2
        }
        if any(count < 1 for count in coverage.values()):
            raise CausalAblationError(
                "the preregistered rescue population must cover Hammer and "
                "Leanstral at least once"
            )
        if self.frozen is not True or self.holdout_included is not False:
            raise CausalAblationError(
                "the rescue manifest must be frozen and exclude holdout"
            )
        object.__setattr__(self, "cases", cases)

    @property
    def split_counts(self) -> Mapping[str, int]:
        return MappingProxyType(
            {
                split.value: sum(case.split is split for case in self.cases)
                for split in (Split.PILOT, Split.DEVELOPMENT)
            }
        )

    @property
    def component_case_counts(self) -> Mapping[str, int]:
        return MappingProxyType(
            {
                component: sum(
                    component in case.optional_components
                    for case in self.cases
                )
                for component in CAUSAL_RESCUE_COMPONENTS_V2
            }
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "semantic_protocol_cid": self.semantic_protocol_cid,
            "causal_proof_protocol_cid": self.causal_proof_protocol_cid,
            "rescue_population_policy_cid": (
                self.rescue_population_policy_cid
            ),
            "plan_cid": self.plan_cid,
            "source_manifest_cid": self.source_manifest_cid,
            "case_manifest_sha256": self.case_manifest_sha256,
            "case_count": len(self.cases),
            "split_counts": dict(self.split_counts),
            "component_case_counts": dict(self.component_case_counts),
            "cases": [case.to_dict() for case in self.cases],
            "selected_before_optional_outcomes": True,
            "frozen": self.frozen,
            "holdout_included": self.holdout_included,
        }

    @property
    def manifest_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "manifest_cid": self.manifest_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "causal_rescue_manifest")
        _exact(
            data,
            {
                "schema",
                "semantic_protocol_cid",
                "causal_proof_protocol_cid",
                "rescue_population_policy_cid",
                "plan_cid",
                "source_manifest_cid",
                "case_manifest_sha256",
                "case_count",
                "split_counts",
                "component_case_counts",
                "cases",
                "selected_before_optional_outcomes",
                "frozen",
                "holdout_included",
                "manifest_cid",
            },
            "causal_rescue_manifest",
        )
        raw_cases = data["cases"]
        if not isinstance(raw_cases, list):
            raise CausalAblationError(
                "causal_rescue_manifest.cases must be an array"
            )
        result = cls(
            schema=data["schema"],  # type: ignore[arg-type]
            semantic_protocol_cid=data[
                "semantic_protocol_cid"
            ],  # type: ignore[arg-type]
            causal_proof_protocol_cid=data[
                "causal_proof_protocol_cid"
            ],  # type: ignore[arg-type]
            rescue_population_policy_cid=data[
                "rescue_population_policy_cid"
            ],  # type: ignore[arg-type]
            plan_cid=data["plan_cid"],  # type: ignore[arg-type]
            source_manifest_cid=data[
                "source_manifest_cid"
            ],  # type: ignore[arg-type]
            case_manifest_sha256=data[
                "case_manifest_sha256"
            ],  # type: ignore[arg-type]
            cases=tuple(
                CausalRescueCaseV2.from_dict(case) for case in raw_cases
            ),
            frozen=data["frozen"],  # type: ignore[arg-type]
            holdout_included=data["holdout_included"],  # type: ignore[arg-type]
        )
        expected_derived = {
            "case_count": len(result.cases),
            "split_counts": dict(result.split_counts),
            "component_case_counts": dict(result.component_case_counts),
            "selected_before_optional_outcomes": True,
            "manifest_cid": result.manifest_cid,
        }
        if any(data[key] != expected for key, expected in expected_derived.items()):
            raise CausalAblationError(
                "causal rescue manifest derived fields or CID changed"
            )
        return result


def _plan_source_manifest_cid(plan: AblationPlan) -> str:
    cases: dict[str, dict[str, str]] = {}
    for job in plan.jobs:
        value = job.case.input_data
        if (
            not isinstance(value, Mapping)
            or set(value) != {"text"}
            or not isinstance(value.get("text"), str)
            or not str(value["text"]).strip()
        ):
            raise CausalAblationError(
                "G210 requires an exact source-only G200 plan"
            )
        entry = {
            "split": job.case.split.value,
            "source_cid": cid_for_bytes(
                str(value["text"]).encode("utf-8")
            ),
        }
        previous = cases.setdefault(job.case.case_id, entry)
        if previous != entry:
            raise CausalAblationError(
                "paired jobs changed a case source or split"
            )
    return cid_for_dag_json(
        {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark."
                "causal-rescue-source-manifest.v2"
            ),
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "causal_proof_protocol_cid": CAUSAL_PROOF_PROTOCOL_V2_CID,
            "cases": [
                {"case_id": case_id, **cases[case_id]}
                for case_id in sorted(cases)
            ],
            "holdout_included": False,
        }
    )


def build_causal_rescue_manifest_v2(
    plan: AblationPlan,
    cases: Sequence[CausalRescueCaseV2],
) -> CausalRescueManifestV2:
    """Bind an already independently reviewed rescue population to ``plan``.

    This function verifies identities only.  It cannot establish independent
    review and therefore requires each caller-supplied case to carry the CID
    of its external review attestation.
    """

    if not isinstance(plan, AblationPlan):
        raise CausalAblationError("plan must be an AblationPlan")
    if plan.split is Split.HOLDOUT:
        raise CausalAblationError("G210 cannot build or execute holdout plans")
    if "A0" not in plan.variant_ids:
        raise CausalAblationError(
            "equal compiler-reference exposure requires A0"
        )
    if any(variant_id == "S1" for variant_id in plan.variant_ids):
        raise CausalAblationError(
            "the legacy S1 diagnostic is outside the G210 causal profile"
        )
    try:
        plan_cid = cid_for_dag_json(plan.to_dict())
    except (AblationValidationError, TypeError, ValueError) as exc:
        raise CausalAblationError("cannot bind the G200 plan") from exc
    ordered = tuple(sorted(cases, key=lambda case: case.case_id))
    by_plan: dict[str, tuple[Split, str]] = {}
    for job in plan.jobs:
        value = job.case.input_data
        if not isinstance(value, Mapping) or not isinstance(
            value.get("text"), str
        ):
            raise CausalAblationError(
                "G210 requires source-only G200 plan cases"
            )
        coordinate = (
            job.case.split,
            cid_for_bytes(str(value["text"]).encode("utf-8")),
        )
        previous = by_plan.setdefault(job.case.case_id, coordinate)
        if previous != coordinate:
            raise CausalAblationError("paired plan case identity drifted")
    if set(by_plan) != {case.case_id for case in ordered}:
        raise CausalAblationError(
            "rescue manifest cases must exactly equal the scheduled population"
        )
    for case in ordered:
        expected_split, expected_source_cid = by_plan[case.case_id]
        if (
            case.split is not expected_split
            or case.source_cid != expected_source_cid
        ):
            raise CausalAblationError(
                f"rescue case {case.case_id} differs from its source-only plan"
            )
    return CausalRescueManifestV2(
        plan_cid=plan_cid,
        source_manifest_cid=_plan_source_manifest_cid(plan),
        case_manifest_sha256=plan.case_manifest_sha256,
        cases=ordered,
    )


def validate_semantic_calibration_prerequisite_v2(
    value: object,
) -> Mapping[str, object]:
    """Validate the exact G200 gate fields required before G210 execution.

    This is an integrity and prerequisite check, not a substitute for the
    independent source recomputation performed by the semantic reassessment
    validator.  The artifact must already be the output of that boundary.
    """

    report = _mapping(value, "semantic_calibration_report")
    _exact(
        report,
        {
            "schema",
            "semantic_protocol_cid",
            "calibration_route_manifest_cid",
            "calibration_metric_spec_cid",
            "reviewed_target_source_cid",
            "reviewed_target_manifest",
            "reviewed_target_manifest_cid",
            "measurement_attribution",
            "status",
            "scope",
            "coverage",
            "quality",
            "absolute_quality_gate",
            "relative_selection",
            "shortlist",
            "holdout_authorized",
            "production_promotion_authorized",
            "observations",
            "artifact_cid",
        },
        "semantic_calibration_report",
    )
    if (
        report.get("schema") != SEMANTIC_CALIBRATION_REPORT_SCHEMA_V2
        or report.get("semantic_protocol_cid") != SEMANTIC_PROTOCOL_V2_CID
        or report.get("calibration_route_manifest_cid")
        != SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID
        or report.get("calibration_metric_spec_cid")
        != SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID
        or report.get("reviewed_target_source_cid")
        != SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID
        or report.get("status") != "complete"
        or report.get("holdout_authorized") is not False
        or report.get("production_promotion_authorized") is not False
    ):
        raise CausalAblationError(
            "G210 requires a complete non-authorizing G200 calibration report"
        )
    coverage = _mapping(
        report.get("coverage"), "semantic_calibration_report.coverage"
    )
    required_coverage = (
        "case_population_complete",
        "coordinate_coverage_complete",
        "validated_ablation_graph_coverage_complete",
        "field_coverage_complete",
        "quality_coordinate_complete",
    )
    if any(coverage.get(field) is not True for field in required_coverage):
        raise CausalAblationError(
            "G200 calibration coverage is incomplete"
        )
    scope = _mapping(
        report.get("scope"), "semantic_calibration_report.scope"
    )
    case_ids = scope.get("case_ids")
    producer_ids = scope.get("producer_ids")
    semantic_fields = scope.get("semantic_fields")
    if (
        scope.get("injected_unsealed_cases_only") is not True
        or scope.get("holdout_case_count") != 0
        or scope.get("expected_case_count")
        != SEMANTIC_CALIBRATION_CASE_COUNT_V2
        or scope.get("observed_case_count")
        != SEMANTIC_CALIBRATION_CASE_COUNT_V2
        or scope.get("expected_coordinate_count")
        != SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2
        or scope.get("observed_coordinate_count")
        != SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2
        or not isinstance(case_ids, list)
        or len(case_ids) != SEMANTIC_CALIBRATION_CASE_COUNT_V2
        or len(set(case_ids)) != len(case_ids)
        or any(not isinstance(case_id, str) for case_id in case_ids)
        or producer_ids != list(SEMANTIC_PRODUCER_IDS_V2)
        or semantic_fields
        != ["logic_family", "target", "class", "predicates", "entities"]
    ):
        raise CausalAblationError(
            "G200 calibration scope is not the complete frozen 20/100 grid"
        )
    observations = report.get("observations")
    if (
        not isinstance(observations, list)
        or len(observations) != SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2
    ):
        raise CausalAblationError(
            "G200 calibration observations are incomplete"
        )
    observed_coordinates: set[tuple[str, str]] = set()
    for observation in observations:
        coordinate = _mapping(
            _mapping(
                observation, "semantic calibration observation"
            ).get("coordinate"),
            "semantic calibration observation.coordinate",
        )
        case_id = coordinate.get("case_id")
        producer_id = coordinate.get("producer_id")
        if not isinstance(case_id, str) or not isinstance(
            producer_id, str
        ):
            raise CausalAblationError(
                "G200 calibration observation coordinate is invalid"
            )
        observed_coordinates.add((case_id, producer_id))
    expected_coordinates = {
        (case_id, producer_id)
        for case_id in case_ids
        for producer_id in SEMANTIC_PRODUCER_IDS_V2
    }
    if observed_coordinates != expected_coordinates:
        raise CausalAblationError(
            "G200 calibration observations differ from the frozen grid"
        )
    quality = _mapping(
        report.get("quality"), "semantic_calibration_report.quality"
    )
    absolute_gate = _mapping(
        report.get("absolute_quality_gate"),
        "semantic_calibration_report.absolute_quality_gate",
    )
    if (
        quality.get("identified") is not True
        or quality.get("semantic_quality_millionths") is None
        or absolute_gate.get("passed") is not True
    ):
        raise CausalAblationError(
            "G200 calibration is not identified and non-vacuously passing"
        )
    artifact_cid = _cid(report.get("artifact_cid"), "artifact_cid")
    body = {
        key: item for key, item in report.items() if key != "artifact_cid"
    }
    if cid_for_dag_json(body) != artifact_cid:
        raise CausalAblationError(
            "G200 calibration artifact CID changed from its body"
        )
    return MappingProxyType(dict(report))


def revalidate_semantic_calibration_prerequisite_v2(
    *,
    reviewed_cases: Sequence[object],
    evidence_sources: Sequence[tuple[AblationPlan, str | Path]],
) -> Mapping[str, object]:
    """Replay complete persisted G200 sources and return the derived report."""

    from .semantic_reassessment import (
        SemanticReassessmentError,
        evaluate_semantic_ablation_calibration_v2,
    )

    try:
        report = evaluate_semantic_ablation_calibration_v2(
            reviewed_cases=reviewed_cases,  # type: ignore[arg-type]
            evidence_sources=evidence_sources,
        )
    except (
        SemanticReassessmentError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        raise CausalAblationError(
            "G200 source evidence failed independent revalidation"
        ) from exc
    return validate_semantic_calibration_prerequisite_v2(report)


def _reference_key(
    case_id: str,
    cache_mode: CacheMode,
) -> tuple[str, CacheMode]:
    return case_id, cache_mode


def _reference_population(
    plan: AblationPlan,
    candidates: Mapping[
        tuple[str, CacheMode],
        CausalProofCandidate | None,
    ],
) -> tuple[dict[str, object], ...]:
    expected = {
        _reference_key(job.case.case_id, job.cache_mode)
        for job in plan.jobs
    }
    if set(candidates) != expected:
        raise CausalAblationError(
            "compiler candidate population must exactly cover every paired "
            "case/cache coordinate once"
        )
    result: list[dict[str, object]] = []
    for case_id, cache_mode in sorted(
        expected, key=lambda item: (item[0], item[1].value)
    ):
        candidate = candidates[(case_id, cache_mode)]
        if candidate is not None and (
            not isinstance(candidate, CausalProofCandidate)
            or candidate.source != "compiler"
        ):
            raise CausalAblationError(
                "compiler reference population contains a non-compiler "
                "candidate"
            )
        result.append(
            {
                "case_id": case_id,
                "cache_mode": cache_mode.value,
                "candidate_cid": (
                    None if candidate is None else candidate.candidate_cid
                ),
                "artifact_cid": (
                    None if candidate is None else candidate.artifact_cid
                ),
            }
        )
    return tuple(result)


@dataclass(frozen=True, slots=True)
class CausalExecutionProfileV2:
    """Immutable G210 namespace binding for one complete paired execution."""

    plan_cid: str
    source_manifest_cid: str
    rescue_manifest_cid: str
    semantic_calibration_artifact_cid: str
    compiler_reference_population_cid: str
    environment_sha256: str
    semantic_protocol_cid: str = SEMANTIC_PROTOCOL_V2_CID
    causal_proof_protocol_cid: str = CAUSAL_PROOF_PROTOCOL_V2_CID
    variant_profile_cid: str = CAUSAL_PROOF_VARIANT_PROFILE_V2_CID
    selection_spec_cid: str = CAUSAL_PROOF_SELECTION_SPEC_V2_CID
    holdout_included: bool = False
    schema: str = CAUSAL_EXECUTION_PROFILE_SCHEMA_V2

    def __post_init__(self) -> None:
        if self.schema != CAUSAL_EXECUTION_PROFILE_SCHEMA_V2:
            raise CausalAblationError(
                "unsupported causal execution profile schema"
            )
        for name, expected in (
            ("semantic_protocol_cid", SEMANTIC_PROTOCOL_V2_CID),
            ("causal_proof_protocol_cid", CAUSAL_PROOF_PROTOCOL_V2_CID),
            (
                "variant_profile_cid",
                CAUSAL_PROOF_VARIANT_PROFILE_V2_CID,
            ),
            ("selection_spec_cid", CAUSAL_PROOF_SELECTION_SPEC_V2_CID),
        ):
            if _cid(getattr(self, name), name) != expected:
                raise CausalAblationError(
                    f"causal execution {name} differs from the frozen profile"
                )
        for name in (
            "plan_cid",
            "source_manifest_cid",
            "rescue_manifest_cid",
            "semantic_calibration_artifact_cid",
            "compiler_reference_population_cid",
        ):
            object.__setattr__(
                self,
                name,
                _cid(getattr(self, name), name),
            )
        if (
            not isinstance(self.environment_sha256, str)
            or len(self.environment_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.environment_sha256
            )
        ):
            raise CausalAblationError(
                "causal execution requires one pinned environment SHA-256"
            )
        if self.holdout_included is not False:
            raise CausalAblationError(
                "causal execution profile cannot include holdout"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "semantic_protocol_cid": self.semantic_protocol_cid,
            "causal_proof_protocol_cid": self.causal_proof_protocol_cid,
            "variant_profile_cid": self.variant_profile_cid,
            "selection_spec_cid": self.selection_spec_cid,
            "plan_cid": self.plan_cid,
            "source_manifest_cid": self.source_manifest_cid,
            "rescue_manifest_cid": self.rescue_manifest_cid,
            "semantic_calibration_artifact_cid": (
                self.semantic_calibration_artifact_cid
            ),
            "compiler_reference_population_cid": (
                self.compiler_reference_population_cid
            ),
            "environment_sha256": self.environment_sha256,
            "holdout_included": self.holdout_included,
        }

    @property
    def profile_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "profile_cid": self.profile_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "causal_execution_profile")
        _exact(
            data,
            {
                "schema",
                "semantic_protocol_cid",
                "causal_proof_protocol_cid",
                "variant_profile_cid",
                "selection_spec_cid",
                "plan_cid",
                "source_manifest_cid",
                "rescue_manifest_cid",
                "semantic_calibration_artifact_cid",
                "compiler_reference_population_cid",
                "environment_sha256",
                "holdout_included",
                "profile_cid",
            },
            "causal_execution_profile",
        )
        result = cls(
            **{
                field: data[field]
                for field in cls.__dataclass_fields__
            }  # type: ignore[arg-type]
        )
        if data["profile_cid"] != result.profile_cid:
            raise CausalAblationError(
                "causal execution profile CID changed"
            )
        return result


@dataclass(frozen=True, slots=True)
class CausalAblationRunResultV2:
    """Validated G210 selection receipts for one complete plan."""

    plan: AblationPlan
    profile: CausalExecutionProfileV2
    results: tuple[CausalProofGraphResult, ...]
    executed_job_ids: tuple[str, ...]
    resumed_job_ids: tuple[str, ...]
    output_root: Path

    @property
    def complete(self) -> bool:
        return len(self.results) == len(self.plan.jobs)

    @property
    def result_cids(self) -> tuple[str, ...]:
        return tuple(result.receipt_cid for result in self.results)

    @property
    def receipt(self) -> Mapping[str, object]:
        body = {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark."
                "causal-proof-run-receipt.v2"
            ),
            "plan_cid": self.profile.plan_cid,
            "profile_cid": self.profile.profile_cid,
            "rescue_manifest_cid": self.profile.rescue_manifest_cid,
            "semantic_calibration_artifact_cid": (
                self.profile.semantic_calibration_artifact_cid
            ),
            "compiler_reference_population_cid": (
                self.profile.compiler_reference_population_cid
            ),
            "job_ids": [job.job_id for job in self.plan.jobs],
            "result_cids": list(self.result_cids),
            "complete": self.complete,
            "holdout_included": False,
        }
        return MappingProxyType(
            {**body, "receipt_cid": cid_for_dag_json(body)}
        )

    @property
    def receipt_cid(self) -> str:
        return str(self.receipt["receipt_cid"])


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CausalAblationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_canonical(path: Path, field: str) -> object:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise CausalAblationError(f"cannot read {field}: {path}") from exc
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise CausalAblationError(f"{field} is not canonical newline JSON")
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except (json.JSONDecodeError, ValueError) as exc:
        raise CausalAblationError(f"{field} is not strict JSON") from exc
    if raw != canonical_dag_json_bytes(value) + b"\n":
        raise CausalAblationError(f"{field} is not canonical DAG-JSON")
    return value


def _write_once(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(canonical_dag_json_bytes(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise CausalAblationError(
            f"refusing to overwrite immutable G210 record: {path}"
        ) from exc


def _causal_result_path(root: Path, job: ScheduledCase) -> Path:
    return (
        root
        / "results"
        / job.case.split.value
        / job.cache_mode.value
        / job.variant_id
        / f"{job.case.case_id}.json"
    )


def _result_envelope(
    *,
    plan: AblationPlan,
    profile: CausalExecutionProfileV2,
    job: ScheduledCase,
    result: CausalProofGraphResult,
    compiler_reference_population_cid: str,
) -> dict[str, object]:
    body = {
        "schema": CAUSAL_ABLATION_RESULT_SCHEMA_V2,
        "plan_cid": cid_for_dag_json(plan.to_dict()),
        "profile_cid": profile.profile_cid,
        "rescue_manifest_cid": profile.rescue_manifest_cid,
        "semantic_calibration_artifact_cid": (
            profile.semantic_calibration_artifact_cid
        ),
        "compiler_reference_population_cid": (
            compiler_reference_population_cid
        ),
        "job": job.to_dict(),
        "causal_result": dict(result.receipt),
        "causal_result_cid": result.receipt_cid,
    }
    return {**body, "envelope_cid": cid_for_dag_json(body)}


def _validate_result_envelope(
    value: object,
    *,
    plan: AblationPlan,
    profile: CausalExecutionProfileV2,
    job: ScheduledCase,
    expected_compiler_candidate: CausalProofCandidate | None,
) -> CausalProofGraphResult:
    data = _mapping(value, "causal_result_envelope")
    expected_keys = {
        "schema",
        "plan_cid",
        "profile_cid",
        "rescue_manifest_cid",
        "semantic_calibration_artifact_cid",
        "compiler_reference_population_cid",
        "job",
        "causal_result",
        "causal_result_cid",
        "envelope_cid",
    }
    _exact(data, expected_keys, "causal_result_envelope")
    body = {
        key: item for key, item in data.items() if key != "envelope_cid"
    }
    if (
        data["schema"] != CAUSAL_ABLATION_RESULT_SCHEMA_V2
        or data["plan_cid"] != cid_for_dag_json(plan.to_dict())
        or data["profile_cid"] != profile.profile_cid
        or data["rescue_manifest_cid"] != profile.rescue_manifest_cid
        or data["semantic_calibration_artifact_cid"]
        != profile.semantic_calibration_artifact_cid
        or data["compiler_reference_population_cid"]
        != profile.compiler_reference_population_cid
        or data["job"] != job.to_dict()
        or data["envelope_cid"] != cid_for_dag_json(body)
    ):
        raise CausalAblationError(
            "causal result envelope differs from its frozen coordinate"
        )
    receipt = _mapping(data["causal_result"], "causal_result")
    result = CausalProofGraphResult(
        receipt=receipt,
        receipt_cid=_cid(data["causal_result_cid"], "causal_result_cid"),
    )
    try:
        validate_causal_proof_selection_receipt(result.receipt)
    except (TypeError, ValueError) as exc:
        raise CausalAblationError(
            "causal graph receipt failed independent replay validation"
        ) from exc
    source_text = job.case.input_data.get("text")
    compiler_reference = _mapping(
        result.receipt.get("compiler_reference"),
        "causal_result.compiler_reference",
    )
    expected_compiler_identity = {
        "candidate_cid": (
            None
            if expected_compiler_candidate is None
            else expected_compiler_candidate.candidate_cid
        ),
        "artifact_cid": (
            None
            if expected_compiler_candidate is None
            else expected_compiler_candidate.artifact_cid
        ),
    }
    if (
        result.receipt.get("run_id") != plan.run_id
        or result.receipt.get("case_id") != job.case.case_id
        or result.receipt.get("variant_id") != job.variant_id
        or result.receipt.get("source_cid")
        != cid_for_bytes(str(source_text).encode("utf-8"))
        or result.receipt.get("protocol_cid")
        != CAUSAL_PROOF_PROTOCOL_V2_CID
        or any(
            compiler_reference.get(field) != expected
            for field, expected in expected_compiler_identity.items()
        )
    ):
        raise CausalAblationError(
            "causal graph result differs from its plan coordinate"
        )
    return result


ControllerFactory = Callable[
    [ScheduledCase, CausalRescueCaseV2],
    CausalProofGraphController,
]
OptionalProducerFactoryMap = Mapping[
    str,
    Mapping[str, Callable[[], object]],
]


def execute_causal_proof_ablation_v2(
    plan: AblationPlan,
    rescue_manifest: CausalRescueManifestV2,
    compiler_candidates: Mapping[
        tuple[str, CacheMode],
        CausalProofCandidate | None,
    ],
    optional_producers: OptionalProducerFactoryMap,
    controller_factory: ControllerFactory,
    *,
    semantic_reviewed_cases: Sequence[object],
    semantic_evidence_sources: Sequence[
        tuple[AblationPlan, str | Path]
    ],
    output_root: str | Path,
    resume: bool = True,
) -> CausalAblationRunResultV2:
    """Reject the retired selection-only G210 batch persistence path.

    The manifest/profile types remain useful planning artifacts, but a
    selection receipt without a complete CaseResult cannot replay native
    kernel authority.  Authoritative execution is provided only by
    :func:`benchmarks.logic_pipeline.causal_runtime.
    execute_causal_runtime_case_v2`; a future batch wrapper must persist that
    function's full ``CausalRuntimeEvidenceV2`` value.
    """

    raise CausalAblationError(
        "selection-only G210 batch execution is disabled; use the full "
        "causal_runtime evidence bridge"
    )


__all__ = [
    "CAUSAL_ABLATION_RESULT_SCHEMA_V2",
    "CAUSAL_EXECUTION_PROFILE_SCHEMA_V2",
    "CAUSAL_REFERENCE_FAILURE_CONDITION_V2",
    "CAUSAL_RESCUE_CASE_SCHEMA_V2",
    "CAUSAL_RESCUE_COMPONENTS_V2",
    "CAUSAL_RESCUE_MANIFEST_SCHEMA_V2",
    "CausalAblationError",
    "CausalAblationRunResultV2",
    "CausalExecutionProfileV2",
    "CausalRescueCaseV2",
    "CausalRescueManifestV2",
    "build_causal_rescue_manifest_v2",
    "execute_causal_proof_ablation_v2",
    "revalidate_semantic_calibration_prerequisite_v2",
    "validate_semantic_calibration_prerequisite_v2",
]
