"""Source-safe HSSL-G241 release boundary for the replacement holdout.

The HSSL-G232 authorization object is intentionally only a proposal: its
shape can prove that it names A0 and one to four registered candidates, but it
cannot prove that those candidates are the result of the frozen pilot.  This
module supplies the stricter downstream boundary.  It:

* reparses G231 from all canonical source records;
* replays the persisted G211 batches and joins their exact evidence to G212;
* deterministically derives the G232 shortlist from the frozen gate policy;
* compares the complete proposed authorization to that derivation;
* locally projects the G239 external-completion schema without importing the
  nested supervisor package (whose package import has application side
  effects);
* requires an externally pinned authority and custodian trust root; and
* appends a path-free receipt to an independently stored, append-only ledger.

CID identity and parsed receipt objects are not authority.  The public
authorizer durably appends a record, and the public consumer accepts it only
when it remains the current head of the exact locked release ledger while the
seal-bound access ledger is still empty.  Pure source-replay and parsing
helpers return non-authorizing evidence and are safe for synthetic tests.  No
function in this module accepts or reads holdout bytes, case contents, labels,
proof obligations, model outputs, or result coordinates.
"""

from __future__ import annotations

import base64
import binascii
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from types import MappingProxyType
from typing import Callable, Final, Iterator, Mapping, Sequence, Self

from .content_addressing import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)
from .contracts import DEFAULT_PROTOCOL
from .holdout_execution import (
    G232_REPLACEMENT_HOLDOUT_AUTHORIZATION_SCHEMA,
    REPLACEMENT_HOLDOUT_ACCESS_LEDGER_SCHEMA,
    REPLACEMENT_HOLDOUT_ACCESS_RECEIPT_SCHEMA,
    REPLACEMENT_HOLDOUT_AUTHORIZED_PROTOCOL_KEYS,
    G232ReplacementHoldoutAuthorization,
    ReplacementHoldoutAccessReceipt,
    ReplacementHoldoutSeal,
    replacement_holdout_ledger_authority_cid,
)
from .positive_gate_bundle import (
    G202_AUTHORITY_ROLE_KEYS,
    G202_SHORTLIST_SELECTION_POLICY_V2_CID,
    G231_EVALUATED_CANDIDATE_IDS,
    G202FrozenRunInputsV2,
    G231ArtifactBindingsV2,
    validate_g231_positive_gate_bundle_v2,
)
from .replay_gate import g238_git_commit_cid
from .revised_pilot_authorization import G210RuntimeReceiptMatrixV2
from .semantic_quality import (
    G201SemanticEvidenceIndexV2,
    validate_g201_semantic_evidence_index_v2,
)


G241_SOURCE_INDEX_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-source-decision-index.v1"
)
G241_G211_GRAPH_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-persisted-runtime-graph.v1"
)
G241_G212_GRAPH_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-causal-resource-graph.v1"
)
G241_SELECTION_EVIDENCE_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-source-derived-shortlist.v1"
)
G241_PILOT_DECISION_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-recomputed-g232-pilot-decision.v1"
)
G241_PARENT_LEDGER_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-parent-completion-ledger.v1"
)
G241_ARTIFACT_SLOT_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-external-artifact-slot.v1"
)
G241_EXTERNAL_PROJECTION_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-g239-external-evaluation-projection.v1"
)
G241_CUSTODIAN_TRUST_ROOT_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-custodian-trust-root.v1"
)
G241_RELEASE_REQUEST_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-custodian-release-request.v1"
)
G241_RELEASE_RECEIPT_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-externally-governed-custodian-release.v1"
)
G241_GIT_TREE_IDENTITY_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-git-tree-identity.v1"
)
G241_ACCESS_LEDGER_SNAPSHOT_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-pre-release-access-ledger-snapshot.v1"
)
G241_VALIDATOR_KEY_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-ed25519-validator-key.v1"
)
G241_VALIDATOR_CLAIM_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-g239-validator-claim.v1"
)
G241_VALIDATOR_SIGNED_PAYLOAD_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-g239-validator-signed-payload.v1"
)
G241_VALIDATOR_ATTESTATION_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-g239-validator-attestation.v1"
)
G241_EXTERNAL_ARTIFACT_SET_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-g239-external-artifact-set.v1"
)
G241_GIT_EXECUTABLE_IDENTITY_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-git-executable-identity.v1"
)
G241_RELEASE_LEDGER_AUTHORITY_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-release-ledger-authority.v1"
)
G241_RELEASE_CONSUMPTION_TOMBSTONE_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-release-consumption-tombstone.v1"
)
G241_LEDGER_FILE_IDENTITY_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g241-ledger-file-identity.v1"
)

_MAX_EXTERNAL_FILE_BYTES: Final = 16 * 1024 * 1024
_GIT_SAFE_ENV: Final = MappingProxyType(
    {
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "PAGER": "cat",
    }
)

G239_EXTERNAL_GITLINK_SCHEMA: Final = (
    "ipfs_accelerate_py.agent_supervisor.external-gitlink-identity.v1"
)
G239_EXTERNAL_SOURCE_SCHEMA: Final = (
    "ipfs_accelerate_py.agent_supervisor.external-source-identity.v1"
)
G239_EXTERNAL_ARTIFACT_SCHEMA: Final = (
    "ipfs_accelerate_py.agent_supervisor.external-artifact-identity.v1"
)
G239_EXTERNAL_REQUIREMENT_SCHEMA: Final = (
    "ipfs_accelerate_py.agent_supervisor."
    "external-completion-requirement.v1"
)
G239_EXTERNAL_RECEIPT_SCHEMA: Final = (
    "ipfs_accelerate_py.agent_supervisor."
    "external-operational-completion.v1"
)
G239_EXTERNAL_AUTHORITY_SCHEMA: Final = (
    "ipfs_accelerate_py.agent_supervisor."
    "external-completion-authority.v1"
)

G241_GOVERNED_GOAL_ID: Final = "HSSL-G232"
G241_GOVERNED_EVIDENCE_TERM: Final = "HSSLEV2329A65"
G241_CACHE_MODES: Final = ("cold", "warm")
G241_ACTIVITY_KEYS: Final = (
    "holdout_reads",
    "holdout_writes",
    "holdout_schedules",
    "backend_calls",
    "result_coordinates",
)
G241_PARENT_KEYS: Final = (
    "g201_semantic_evidence",
    "g202_source_run_freeze",
    "g211_persisted_runtime_graph",
    "g212_causal_resource_graph",
    "g220_replacement_holdout_seal",
    "g231_positive_gate_bundle",
    "g232_authorization_proposal",
)
G241_EXTERNAL_ARTIFACT_KEYS: Final = (
    *G241_PARENT_KEYS,
    "g232_pilot_decision",
)
G241_UPSTREAM_AUTHORITY_ROLES: Final = G202_AUTHORITY_ROLE_KEYS

_GIT_OBJECT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class CustodianReleaseError(ValueError):
    """Raised when any source, governance, or custody join fails closed."""


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise CustodianReleaseError(
                "G241 DAG-JSON objects require string keys"
            )
        return {
            str(key): _plain(member)
            for key, member in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_plain(member) for member in value]
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise CustodianReleaseError(
        f"G241 value is not DAG-JSON: {type(value).__name__}"
    )


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _freeze(member)
                for key, member in value.items()
            }
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(member) for member in value)
    return value


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise CustodianReleaseError(
            f"{field_name} must be an object with string keys"
        )
    return value


def _array(value: object, field_name: str) -> tuple[object, ...]:
    if not isinstance(value, (tuple, list)):
        raise CustodianReleaseError(f"{field_name} must be an array")
    return tuple(value)


def _exact(
    value: Mapping[str, object],
    expected: set[str],
    field_name: str,
) -> None:
    if set(value) != expected:
        raise CustodianReleaseError(f"{field_name} fields changed")


def _cid(value: object, field_name: str) -> str:
    try:
        return validate_cid(value)
    except (TypeError, ValueError) as exc:
        raise CustodianReleaseError(
            f"{field_name} must be a canonical CIDv1"
        ) from exc


def _dag_cid(value: object, field_name: str) -> str:
    try:
        return validate_cid(value, codecs=("dag-json",))
    except (TypeError, ValueError) as exc:
        raise CustodianReleaseError(
            f"{field_name} must be a canonical DAG-JSON CIDv1"
        ) from exc


def _git_object(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _GIT_OBJECT.fullmatch(value):
        raise CustodianReleaseError(
            f"{field_name} must be a full lowercase Git object identity"
        )
    return value


def _actor(value: object, field_name: str) -> str:
    return _dag_cid(value, field_name)


def _positive_gate(
    value: object,
    field_name: str,
) -> Mapping[str, object]:
    gate = _mapping(value, field_name)
    if (
        gate.get("complete") is not True
        or gate.get("passed") is not True
        or gate.get("status") != "passed"
    ):
        raise CustodianReleaseError(
            f"{field_name} is not a complete positive source gate"
        )
    if (
        gate.get("holdout_accessed") is True
        or gate.get("holdout_included") is True
    ):
        raise CustodianReleaseError(
            f"{field_name} contains premature holdout activity"
        )
    return gate


def g241_git_tree_cid(tree_oid: str) -> str:
    """Address one Git tree without presenting its bare OID as content."""

    tree = _git_object(tree_oid, "tree_oid")
    return cid_for_dag_json(
        {
            "schema": G241_GIT_TREE_IDENTITY_SCHEMA_V1,
            "object_format": "sha1" if len(tree) == 40 else "sha256",
            "object_type": "tree",
            "oid": tree,
        }
    )


def g241_artifact_slot_cid(name: str) -> str:
    """Return the stable external artifact-slot identity for one parent."""

    if not isinstance(name, str) or name not in G241_EXTERNAL_ARTIFACT_KEYS:
        raise CustodianReleaseError("unknown G241 external artifact slot")
    return cid_for_dag_json(
        {
            "schema": G241_ARTIFACT_SLOT_SCHEMA_V1,
            "goal_id": G241_GOVERNED_GOAL_ID,
            "artifact_name": name,
        }
    )


def _zero_activity(value: object) -> Mapping[str, int]:
    activity = _mapping(value, "pre-release activity")
    if set(activity) != set(G241_ACTIVITY_KEYS):
        raise CustodianReleaseError(
            "pre-release activity must contain every exact counter"
        )
    normalized: dict[str, int] = {}
    for key in G241_ACTIVITY_KEYS:
        count = activity[key]
        if type(count) is not int or count != 0:
            raise CustodianReleaseError(
                "any pre-release holdout activity permanently invalidates "
                "the seal"
            )
        normalized[key] = count
    return MappingProxyType(normalized)


def zero_g241_activity() -> Mapping[str, int]:
    """Return the only pre-release activity state accepted by G241."""

    return MappingProxyType({key: 0 for key in G241_ACTIVITY_KEYS})


def _candidate_rows(
    gate: Mapping[str, object],
    field_name: str,
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        _mapping(row, f"{field_name}[]")
        for row in _array(gate.get(field_name), field_name)
    )


def _relative_reduction(
    baseline: object,
    candidate: object,
) -> float | None:
    if (
        type(baseline) not in {int, float}
        or type(candidate) not in {int, float}
    ):
        return None
    baseline_value = float(baseline)
    candidate_value = float(candidate)
    if baseline_value < 0.0 or candidate_value < 0.0:
        return None
    if baseline_value == 0.0:
        return 0.0 if candidate_value == 0.0 else None
    return (baseline_value - candidate_value) / baseline_value


def derive_g232_shortlist_from_validated_gates_v1(
    *,
    g231_bundle: object,
    semantic_quality_gate: object,
    efficacy_gate: object,
    reliability_gate: object,
    routing_gate: object,
    safety_gate: object,
    resource_statistics_gate: object,
    detached_replay_gate: object,
) -> Mapping[str, object]:
    """Derive the exact nonbaseline shortlist without ranking or truncation.

    The G210 pilot/development population is the preregistered causal-rescue
    population, so the complete paired verified delta is the frozen
    hard-case gain.  A candidate must also preserve every split/cache
    regression floor and every baseline-solved case.
    """

    bundle = _positive_gate(g231_bundle, "G231 bundle")
    if (
        bundle.get("source_recomputed") is not True
        or bundle.get("holdout_authorized") is not False
        or bundle.get("holdout_accessed") is not False
        or bundle.get("holdout_outcomes_inspected") is not False
    ):
        raise CustodianReleaseError(
            "G231 bundle is not a source-recomputed non-holdout bundle"
        )
    candidates = tuple(
        str(item)
        for item in _array(
            bundle.get("candidate_variant_ids"),
            "G231 candidate_variant_ids",
        )
    )
    if candidates != G231_EVALUATED_CANDIDATE_IDS:
        raise CustodianReleaseError(
            "G231 must evaluate the complete frozen candidate population"
        )

    semantic = _positive_gate(
        semantic_quality_gate, "semantic-quality gate"
    )
    efficacy = _positive_gate(efficacy_gate, "efficacy gate")
    _positive_gate(reliability_gate, "reliability gate")
    _positive_gate(routing_gate, "routing gate")
    _positive_gate(safety_gate, "safety gate")
    resources = _positive_gate(
        resource_statistics_gate, "resource/statistics gate"
    )
    _positive_gate(detached_replay_gate, "detached replay gate")

    child_receipts = _mapping(
        bundle.get("child_gate_receipt_cids"),
        "G231 child gate receipts",
    )
    for key, gate in (
        ("g235_semantic_quality", semantic),
        ("g234_efficacy", efficacy),
        ("g234_reliability", _mapping(reliability_gate, "reliability")),
        ("g234_routing", _mapping(routing_gate, "routing")),
        ("g236_safety", _mapping(safety_gate, "safety")),
        ("g237_resource_statistics", resources),
        ("g238_detached_replay", _mapping(
            detached_replay_gate, "detached replay"
        )),
    ):
        if child_receipts.get(key) != gate.get("receipt_cid"):
            raise CustodianReleaseError(
                "G231 child receipt identities changed after source replay"
            )

    semantic_rows = {
        str(row.get("variant_id")): row
        for row in _candidate_rows(semantic, "per_arm_metrics")
    }
    if set(semantic_rows) != {"A0", *candidates}:
        raise CustodianReleaseError(
            "semantic evidence does not exactly cover A0 and all candidates"
        )
    quality_values = {
        variant_id: row.get("semantic_quality_millionths")
        for variant_id, row in semantic_rows.items()
    }
    if any(type(value) is not int for value in quality_values.values()):
        raise CustodianReleaseError(
            "semantic evidence contains null or non-integral quality"
        )
    best_quality = max(int(value) for value in quality_values.values())

    efficacy_evidence = _mapping(
        efficacy.get("evidence"), "efficacy evidence"
    )
    comparisons = tuple(
        _mapping(row, "efficacy comparison")
        for row in _array(
            efficacy_evidence.get("comparisons"),
            "efficacy comparisons",
        )
    )
    expected_cells = {
        (candidate, split, cache)
        for candidate in candidates
        for split in ("pilot", "development")
        for cache in G241_CACHE_MODES
    }
    actual_cells = {
        (
            str(row.get("candidate_variant_id")),
            str(row.get("split")),
            str(row.get("cache_mode")),
        )
        for row in comparisons
    }
    if actual_cells != expected_cells or len(comparisons) != len(
        expected_cells
    ):
        raise CustodianReleaseError(
            "paired efficacy cells are incomplete, duplicated, or foreign"
        )

    cost_rows = {
        str(row.get("variant_id")): row
        for row in _candidate_rows(resources, "cost_evidence")
    }
    if set(cost_rows) != {"A0", *candidates}:
        raise CustodianReleaseError(
            "cost evidence does not exactly cover A0 and all candidates"
        )
    pareto = _mapping(
        resources.get("pareto_evidence"), "Pareto evidence"
    )
    pareto_rows = {
        str(row.get("variant_id")): row
        for row in _candidate_rows(pareto, "candidates")
    }
    if set(pareto_rows) != {"A0", *candidates}:
        raise CustodianReleaseError(
            "Pareto evidence does not exactly cover A0 and all candidates"
        )
    frontier = tuple(
        str(item)
        for item in _array(
            pareto.get("frontier_variant_ids"),
            "Pareto frontier",
        )
    )
    if len(frontier) != len(set(frontier)) or any(
        item not in {"A0", *candidates} for item in frontier
    ):
        raise CustodianReleaseError("Pareto frontier is duplicated or foreign")

    thresholds = DEFAULT_PROTOCOL.thresholds
    baseline_costs = _mapping(
        cost_rows["A0"].get("metrics"), "A0 cost metrics"
    )
    evidence_rows: list[dict[str, object]] = []
    selected: list[str] = []
    for candidate in candidates:
        rows = tuple(
            row
            for row in comparisons
            if row.get("candidate_variant_id") == candidate
        )
        scheduled = sum(int(row["scheduled_pair_count"]) for row in rows)
        measured = sum(int(row["measured_pair_count"]) for row in rows)
        net_gain = sum(int(row["net_verified_gain_count"]) for row in rows)
        baseline_only = sum(
            int(row["baseline_only_verified_count"]) for row in rows
        )
        deltas = tuple(row.get("net_verified_delta") for row in rows)
        complete_pairs = (
            scheduled > 0
            and measured == scheduled
            and all(type(value) in {int, float} for value in deltas)
        )
        regression_floor_passed = bool(
            complete_pairs
            and min(float(value) for value in deltas)
            >= thresholds.paired_regression_floor
        )
        hard_case_gain = (
            net_gain / scheduled if complete_pairs else None
        )
        baseline_regression_rate = (
            baseline_only / scheduled if complete_pairs else None
        )
        efficacy_passed = bool(
            regression_floor_passed
            and hard_case_gain is not None
            and hard_case_gain
            >= thresholds.hard_case_verified_gain_min
            and baseline_regression_rate is not None
            and baseline_regression_rate
            <= thresholds.baseline_solved_regression_rate_max
            and baseline_only
            <= thresholds.unexplained_baseline_regressions_max
        )

        semantic_row = semantic_rows[candidate]
        quality = int(quality_values[candidate])
        quality_gap = (best_quality - quality) / 1_000_000
        semantic_passed = bool(
            semantic_row.get("complete") is True
            and semantic_row.get("absolute_quality_passed") is True
        )
        candidate_costs = _mapping(
            cost_rows[candidate].get("metrics"),
            f"{candidate} cost metrics",
        )
        reductions = {
            metric: _relative_reduction(
                baseline_costs.get(metric),
                candidate_costs.get(metric),
            )
            for metric in ("wall_time_ms", "model_calls")
        }
        measured_reductions = tuple(
            value for value in reductions.values() if value is not None
        )
        efficiency_passed = bool(
            semantic_passed
            and quality_gap <= thresholds.near_best_quality_margin_max
            and measured_reductions
            and max(measured_reductions)
            >= thresholds.efficiency_reduction_min
        )

        pareto_row = pareto_rows[candidate]
        frontier_passed = bool(
            candidate in frontier
            and pareto_row.get("eligible") is True
            and pareto_row.get("safety_feasible") is True
            and pareto_row.get("on_frontier") is True
            and not _array(
                pareto_row.get("dominated_by"), "Pareto dominators"
            )
        )
        materiality_passed = efficacy_passed or efficiency_passed
        eligible = semantic_passed and materiality_passed and frontier_passed
        reasons: list[str] = []
        if not semantic_passed:
            reasons.append("semantic_absolute_or_completeness_failed")
        if not complete_pairs:
            reasons.append("paired_efficacy_incomplete")
        if not regression_floor_passed:
            reasons.append("paired_regression_floor_failed")
        if baseline_only:
            reasons.append("unexplained_baseline_regression")
        if not materiality_passed:
            reasons.append("materiality_gate_failed")
        if not frontier_passed:
            reasons.append("not_on_exact_safe_pareto_frontier")
        row_body = {
            "variant_id": candidate,
            "semantic_metrics_cid": semantic_row.get("metrics_cid"),
            "semantic_quality_millionths": quality,
            "quality_gap_from_best": quality_gap,
            "semantic_passed": semantic_passed,
            "efficacy_comparison_cids": sorted(
                str(row["comparison_cid"]) for row in rows
            ),
            "scheduled_pair_count": scheduled,
            "measured_pair_count": measured,
            "hard_case_verified_gain": hard_case_gain,
            "paired_regression_floor_passed": regression_floor_passed,
            "baseline_solved_regression_rate": (
                baseline_regression_rate
            ),
            "unexplained_baseline_regressions": baseline_only,
            "efficacy_materiality_passed": efficacy_passed,
            "efficiency_reductions": reductions,
            "efficiency_materiality_passed": efficiency_passed,
            "pareto_candidate_cid": cid_for_dag_json(_plain(pareto_row)),
            "frontier_passed": frontier_passed,
            "eligible": eligible,
            "failure_codes": reasons,
        }
        evidence_rows.append(
            {
                **row_body,
                "eligibility_cid": cid_for_dag_json(row_body),
            }
        )
        if eligible:
            selected.append(candidate)

    if (
        not selected
        or len(selected) > thresholds.shortlist_candidate_max
    ):
        raise CustodianReleaseError(
            "deterministic eligible frontier must contain one to four "
            "candidates; ranking and truncation are forbidden"
        )
    body = {
        "schema": G241_SELECTION_EVIDENCE_SCHEMA_V1,
        "g231_bundle_cid": bundle.get("bundle_cid"),
        "shortlist_selection_policy_cid": (
            G202_SHORTLIST_SELECTION_POLICY_V2_CID
        ),
        "evaluated_candidate_ids": list(candidates),
        "candidate_evidence": evidence_rows,
        "selected_candidate_ids": selected,
        "authorized_variant_ids": ["A0", *selected],
        "candidate_min": 1,
        "candidate_max": thresholds.shortlist_candidate_max,
        "ranking_permitted": False,
        "truncation_permitted": False,
        "source_recomputed": True,
        "holdout_accessed": False,
    }
    return _freeze(
        {**body, "selection_cid": cid_for_dag_json(body)}
    )  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class G241PersistedBatchSourceV1:
    """Private, non-serializable source required to replay one G211 batch."""

    plan: object
    rescue_manifest: object
    execution_profile: object
    output_root: Path

    def __post_init__(self) -> None:
        root = Path(self.output_root)
        if not root.is_absolute():
            raise CustodianReleaseError(
                "G211 persisted source root must be absolute"
            )
        object.__setattr__(self, "output_root", root)


def _replay_g211_batches(
    sources: Sequence[G241PersistedBatchSourceV1],
    matrix: G210RuntimeReceiptMatrixV2,
) -> tuple[Mapping[str, object], tuple[object, ...]]:
    try:
        from .causal_batch import validate_causal_runtime_batch_v2
    except ImportError as exc:
        raise CustodianReleaseError(
            "G211 persisted-runtime validator is unavailable"
        ) from exc

    if not sources:
        raise CustodianReleaseError(
            "G241 requires persisted G211 pilot/development batches"
        )
    batches: list[object] = []
    for source in sources:
        if not isinstance(source, G241PersistedBatchSourceV1):
            raise CustodianReleaseError(
                "G211 sources must use G241PersistedBatchSourceV1"
            )
        try:
            batch = validate_causal_runtime_batch_v2(
                source.plan,  # type: ignore[arg-type]
                source.rescue_manifest,  # type: ignore[arg-type]
                source.execution_profile,  # type: ignore[arg-type]
                output_root=source.output_root,
            )
        except (TypeError, ValueError, OSError) as exc:
            raise CustodianReleaseError(
                "persisted G211 batch failed complete source replay"
            ) from exc
        if (
            batch.complete is not True
            or batch.runtime_namespace_evidence_set is None
            or batch.source_orchestration_evidence_set is None
            or batch.identity_body().get("holdout_included") is not False
        ):
            raise CustodianReleaseError(
                "G211 batch lacks complete runtime namespace and live "
                "source-orchestration evidence"
            )
        batches.append(batch)

    by_split = {
        str(batch.plan.split.value): batch for batch in batches
    }
    if (
        set(by_split) != {"pilot", "development"}
        or len(by_split) != len(batches)
    ):
        raise CustodianReleaseError(
            "G211 batches must exactly cover pilot and development"
        )
    batches = [by_split["pilot"], by_split["development"]]
    evidence_cids = tuple(
        sorted(
            str(item.receipt_cid)
            for batch in batches
            for item in batch.evidence
        )
    )
    matrix_cids = tuple(
        sorted(str(item.receipt_cid) for item in matrix.runtime_evidence)
    )
    if (
        evidence_cids != matrix_cids
        or len(evidence_cids) != len(set(evidence_cids))
    ):
        raise CustodianReleaseError(
            "G211 persisted evidence does not exactly equal the G212 matrix"
        )
    body = {
        "schema": G241_G211_GRAPH_SCHEMA_V1,
        "batch_receipt_cids": [
            str(batch.receipt_cid) for batch in batches
        ],
        "plan_cids": [
            str(batch.receipt["plan_cid"]) for batch in batches
        ],
        "runtime_namespace_evidence_set_cids": [
            str(
                batch.runtime_namespace_evidence_set.evidence_set_cid
            )
            for batch in batches
        ],
        "runtime_namespace_policy_cids": [
            str(batch.runtime_namespace_evidence_set.policy.policy_cid)
            for batch in batches
        ],
        "source_orchestration_evidence_set_cids": [
            str(
                batch.source_orchestration_evidence_set.evidence_set_cid
            )
            for batch in batches
        ],
        "causal_runtime_evidence_cids": list(evidence_cids),
        "complete": True,
        "holdout_included": False,
        "source_recomputed": True,
    }
    graph = {
        **body,
        "graph_cid": cid_for_dag_json(body),
    }
    return (
        _freeze(graph),  # type: ignore[return-value]
        tuple(batches),
    )


@dataclass(frozen=True, slots=True)
class G241SourceDecisionIndexV1:
    """Path-free exact source graph consumed by external governance."""

    source_commit: str
    source_commit_cid: str
    source_tree_cid: str
    recursive_gitlinks_cid: str
    run_plan_cid: str
    capability_inventory_cid: str
    environment_cid: str
    namespace_identity_cids: Mapping[str, str]
    upstream_authority_cids: Mapping[str, str]
    parent_artifact_cids: Mapping[str, str]
    g211_batch_receipt_cids: tuple[str, ...]
    g212_runtime_evidence_cids: tuple[str, ...]
    shortlist_selection_cid: str
    g232_pilot_decision_cid: str
    access_ledger_authority_cid: str
    schema: str = G241_SOURCE_INDEX_SCHEMA_V1
    source_index_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G241_SOURCE_INDEX_SCHEMA_V1:
            raise CustodianReleaseError("unsupported G241 source index")
        object.__setattr__(
            self,
            "source_commit",
            _git_object(self.source_commit, "source_commit"),
        )
        for name in (
            "source_commit_cid",
            "source_tree_cid",
            "recursive_gitlinks_cid",
            "run_plan_cid",
            "capability_inventory_cid",
            "environment_cid",
            "shortlist_selection_cid",
            "g232_pilot_decision_cid",
            "access_ledger_authority_cid",
        ):
            object.__setattr__(
                self, name, _dag_cid(getattr(self, name), name)
            )
        if self.source_commit_cid != g238_git_commit_cid(
            self.source_commit
        ):
            raise CustodianReleaseError("source commit CID changed")
        namespaces = _mapping(
            self.namespace_identity_cids, "namespace identities"
        )
        expected_namespaces = {
            "worktree",
            "cache_policy",
            "runtime_identity_policy",
            "execution_identities",
            "runtime_orchestration_policy",
            "runtime_namespace_policy_pilot",
            "runtime_namespace_policy_development",
            "runtime_namespace_evidence_pilot",
            "runtime_namespace_evidence_development",
            "source_orchestration_evidence_pilot",
            "source_orchestration_evidence_development",
        }
        if set(namespaces) != expected_namespaces:
            raise CustodianReleaseError(
                "G202 namespace identity set is incomplete or foreign"
            )
        object.__setattr__(
            self,
            "namespace_identity_cids",
            MappingProxyType(
                {
                    key: _dag_cid(value, f"namespace.{key}")
                    for key, value in sorted(namespaces.items())
                }
            ),
        )
        authority_roles = _mapping(
            self.upstream_authority_cids, "upstream authority identities"
        )
        if set(authority_roles) != set(G241_UPSTREAM_AUTHORITY_ROLES):
            raise CustodianReleaseError(
                "upstream authority role set is incomplete or foreign"
            )
        normalized_authorities = {
            role: _dag_cid(
                authority_roles[role],
                f"upstream_authority_cids.{role}",
            )
            for role in G241_UPSTREAM_AUTHORITY_ROLES
        }
        if len(set(normalized_authorities.values())) != len(
            normalized_authorities
        ):
            raise CustodianReleaseError(
                "upstream execution, review, measurement, and validation "
                "authorities overlap"
            )
        object.__setattr__(
            self,
            "upstream_authority_cids",
            MappingProxyType(normalized_authorities),
        )
        parents = _mapping(
            self.parent_artifact_cids, "parent artifact identities"
        )
        if set(parents) != set(G241_PARENT_KEYS):
            raise CustodianReleaseError(
                "G241 parent ledger is incomplete or foreign"
            )
        object.__setattr__(
            self,
            "parent_artifact_cids",
            MappingProxyType(
                {
                    key: _dag_cid(parents[key], f"parent.{key}")
                    for key in G241_PARENT_KEYS
                }
            ),
        )
        batches = tuple(
            _dag_cid(value, "G211 batch receipt")
            for value in self.g211_batch_receipt_cids
        )
        runtime = tuple(
            _dag_cid(value, "G212 runtime evidence")
            for value in self.g212_runtime_evidence_cids
        )
        if (
            not batches
            or not runtime
            or len(batches) != len(set(batches))
            or len(runtime) != len(set(runtime))
            or runtime != tuple(sorted(runtime))
        ):
            raise CustodianReleaseError(
                "G211/G212 receipt graphs are empty, duplicated, or unordered"
            )
        object.__setattr__(self, "g211_batch_receipt_cids", batches)
        object.__setattr__(self, "g212_runtime_evidence_cids", runtime)
        expected = cid_for_dag_json(self.identity_payload())
        if self.source_index_cid is None:
            object.__setattr__(self, "source_index_cid", expected)
        elif (
            _dag_cid(self.source_index_cid, "source_index_cid")
            != expected
        ):
            raise CustodianReleaseError("G241 source index CID changed")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "source_commit": self.source_commit,
            "source_commit_cid": self.source_commit_cid,
            "source_tree_cid": self.source_tree_cid,
            "recursive_gitlinks_cid": self.recursive_gitlinks_cid,
            "run_plan_cid": self.run_plan_cid,
            "capability_inventory_cid": self.capability_inventory_cid,
            "environment_cid": self.environment_cid,
            "namespace_identity_cids": dict(
                self.namespace_identity_cids
            ),
            "upstream_authority_cids": dict(
                self.upstream_authority_cids
            ),
            "parent_artifact_cids": dict(self.parent_artifact_cids),
            "g211_batch_receipt_cids": list(
                self.g211_batch_receipt_cids
            ),
            "g212_runtime_evidence_cids": list(
                self.g212_runtime_evidence_cids
            ),
            "shortlist_selection_cid": self.shortlist_selection_cid,
            "g232_pilot_decision_cid": self.g232_pilot_decision_cid,
            "access_ledger_authority_cid": (
                self.access_ledger_authority_cid
            ),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "source_index_cid": self.source_index_cid,
        }


@dataclass(frozen=True, slots=True)
class G241SourceReplayResultV1:
    """Non-authorizing in-memory projection of complete source replay.

    Construction has no authority.  Operational issuance always calls
    :func:`recompute_g241_source_chain_v1` itself and a consumer always
    revalidates the durable release and access ledgers.
    """

    source_index: G241SourceDecisionIndexV1
    selection_evidence: Mapping[str, object]
    pilot_decision: Mapping[str, object]
    authorization: G232ReplacementHoldoutAuthorization
    external_artifact_cids: Mapping[str, str]
    parent_ledger_cid: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_index, G241SourceDecisionIndexV1):
            raise CustodianReleaseError(
                "source replay requires a typed G241 source index"
            )
        object.__setattr__(
            self, "selection_evidence", _freeze(self.selection_evidence)
        )
        object.__setattr__(
            self, "pilot_decision", _freeze(self.pilot_decision)
        )
        artifacts = _mapping(
            self.external_artifact_cids, "external artifact identities"
        )
        if set(artifacts) != set(G241_EXTERNAL_ARTIFACT_KEYS):
            raise CustodianReleaseError(
                "external artifact graph is incomplete or foreign"
            )
        object.__setattr__(
            self,
            "external_artifact_cids",
            MappingProxyType(
                {
                    key: _dag_cid(artifacts[key], f"artifact.{key}")
                    for key in G241_EXTERNAL_ARTIFACT_KEYS
                }
            ),
        )
        object.__setattr__(
            self,
            "parent_ledger_cid",
            _dag_cid(self.parent_ledger_cid, "parent_ledger_cid"),
        )


def _build_expected_g232_authorization(
    *,
    pilot_artifact_cid: str,
    seal: ReplacementHoldoutSeal,
    source_commit: str,
    selected_candidates: Sequence[str],
) -> G232ReplacementHoldoutAuthorization:
    body = {
        "schema": G232_REPLACEMENT_HOLDOUT_AUTHORIZATION_SCHEMA,
        "goal_id": "HSSL-G232",
        "pilot_artifact_cid": pilot_artifact_cid,
        "seal_contract_cid": seal.seal_contract_cid,
        "sealed_manifest_cid": seal.sealed_manifest_cid,
        "protocol_cids": {
            key: seal.protocol_cids[key]
            for key in sorted(
                REPLACEMENT_HOLDOUT_AUTHORIZED_PROTOCOL_KEYS
            )
        },
        "source_commit": source_commit,
        "authorized_variant_ids": ["A0", *selected_candidates],
        "cache_modes": list(G241_CACHE_MODES),
        "passed": True,
        "complete": True,
        "shortlist_frozen": True,
        "holdout_authorized": True,
        "outcomes_inspected": False,
        "tuning_permitted": False,
    }
    return G232ReplacementHoldoutAuthorization.from_dict(
        {
            **body,
            "authorization_cid": cid_for_dag_json(body),
        }
    )


def validate_g232_proposal_against_source_replay_v1(
    *,
    proposal: object,
    selection_evidence: object,
    pilot_decision: object,
    seal: ReplacementHoldoutSeal,
    source_commit: str,
) -> G232ReplacementHoldoutAuthorization:
    """Compare a proposal with one internally source-derived pilot decision.

    The helper is non-authorizing and exists so synthetic tests can exercise
    exact proposal rejection without constructing operational G239 authority.
    """

    selection = _mapping(selection_evidence, "selection evidence")
    decision = _mapping(pilot_decision, "pilot decision")
    if (
        selection.get("schema") != G241_SELECTION_EVIDENCE_SCHEMA_V1
        or selection.get("source_recomputed") is not True
        or selection.get("holdout_accessed") is not False
    ):
        raise CustodianReleaseError(
            "shortlist evidence is not a source-recomputed G241 selection"
        )
    selection_body = {
        key: _plain(value)
        for key, value in selection.items()
        if key != "selection_cid"
    }
    selection_cid = cid_for_dag_json(selection_body)
    if selection.get("selection_cid") != selection_cid:
        raise CustodianReleaseError("shortlist evidence CID changed")
    if (
        decision.get("schema") != G241_PILOT_DECISION_SCHEMA_V1
        or decision.get("complete") is not True
        or decision.get("passed") is not True
        or decision.get("source_recomputed") is not True
        or decision.get("holdout_accessed") is not False
        or decision.get("holdout_outcomes_inspected") is not False
        or decision.get("production_promotion_authorized") is not False
        or decision.get("shortlist_selection_cid") != selection_cid
        or _plain(decision.get("selected_candidate_ids"))
        != _plain(selection.get("selected_candidate_ids"))
        or _plain(decision.get("authorized_variant_ids"))
        != _plain(selection.get("authorized_variant_ids"))
    ):
        raise CustodianReleaseError(
            "pilot decision does not exactly bind the source-derived shortlist"
        )
    decision_body = {
        key: _plain(value)
        for key, value in decision.items()
        if key != "pilot_decision_cid"
    }
    pilot_cid = cid_for_dag_json(decision_body)
    if decision.get("pilot_decision_cid") != pilot_cid:
        raise CustodianReleaseError("pilot-decision CID changed")
    selected = tuple(
        str(item)
        for item in _array(
            selection.get("selected_candidate_ids"),
            "selected candidate IDs",
        )
    )
    expected = _build_expected_g232_authorization(
        pilot_artifact_cid=pilot_cid,
        seal=seal,
        source_commit=_git_object(source_commit, "source_commit"),
        selected_candidates=selected,
    )
    try:
        supplied = (
            G232ReplacementHoldoutAuthorization.from_dict(
                proposal.to_dict()
            )
            if isinstance(proposal, G232ReplacementHoldoutAuthorization)
            else G232ReplacementHoldoutAuthorization.from_dict(proposal)
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise CustodianReleaseError(
            "G232 proposal failed strict typed parsing"
        ) from exc
    if supplied.to_dict() != expected.to_dict():
        raise CustodianReleaseError(
            "G232 proposal differs from the deterministic source-derived "
            "pilot decision"
        )
    supplied.validate_against(seal)
    return supplied


def _g231_persisted_batch_sources(
    sources: Mapping[str, object],
) -> tuple[G241PersistedBatchSourceV1, ...]:
    result: list[G241PersistedBatchSourceV1] = []
    for split in ("pilot", "development"):
        batch = sources.get(f"{split}_runtime_batch")
        if batch is None or any(
            not hasattr(batch, name)
            for name in (
                "plan",
                "rescue_manifest",
                "execution_profile",
                "output_root",
            )
        ):
            raise CustodianReleaseError(
                "G231 sources do not contain exact persisted G211 "
                "pilot/development batches"
            )
        result.append(
            G241PersistedBatchSourceV1(
                plan=batch.plan,
                rescue_manifest=batch.rescue_manifest,
                execution_profile=batch.execution_profile,
                output_root=Path(batch.output_root),
            )
        )
    return tuple(result)


def _single_authority(
    values: Sequence[object],
    role: str,
) -> str:
    normalized = {
        _dag_cid(value, f"{role} authority") for value in values
    }
    if len(normalized) != 1:
        raise CustodianReleaseError(
            f"{role} authority changed across the source graph"
        )
    return next(iter(normalized))


def _derive_upstream_authorities(
    *,
    freeze: G202FrozenRunInputsV2,
    artifacts: G231ArtifactBindingsV2,
    batches: Sequence[object],
    sources: Mapping[str, object],
) -> Mapping[str, str]:
    manifest = freeze.authority_role_manifest
    manifested = dict(manifest.role_identity_cids)
    manifested_roles = G241_UPSTREAM_AUTHORITY_ROLES
    if (
        set(manifested) != set(manifested_roles)
        or len(set(manifested.values())) != len(manifested)
    ):
        raise CustodianReleaseError(
            "G202 authority-role manifest is incomplete or overlapping"
        )
    control_index = sources.get("control_index")
    if control_index is None or any(
        not hasattr(control_index, name)
        for name in (
            "review_authority_cid",
            "execution_authority_cid",
        )
    ):
        raise CustodianReleaseError(
            "G236 control authorities are unavailable"
        )
    resource_receipts = tuple(
        _array(sources.get("resource_receipts"), "resource receipts")
    )
    if not resource_receipts:
        raise CustodianReleaseError(
            "G237 resource authority population is empty"
        )
    namespace_sets = tuple(
        batch.runtime_namespace_evidence_set for batch in batches
    )
    orchestration_sets = tuple(
        batch.source_orchestration_evidence_set for batch in batches
    )
    if any(item is None for item in (*namespace_sets, *orchestration_sets)):
        raise CustodianReleaseError(
            "G211/G240 authority evidence is incomplete"
        )
    orchestration_receipts = tuple(
        receipt
        for evidence_set in orchestration_sets
        for receipt in evidence_set.receipts
    )
    source_executor = _single_authority(
        (
            freeze.source_executor_authority_cid,
            control_index.execution_authority_cid,
            *(
                receipt.producer_identity_cid
                for receipt in resource_receipts
            ),
            *(
                receipt.executor_identity_cid
                for receipt in orchestration_receipts
            ),
        ),
        "source executor",
    )
    operational_replays = _mapping(
        sources.get("operational_replay_sources"),
        "operational replay sources",
    )
    if not operational_replays:
        raise CustodianReleaseError(
            "G238 operational replay authority population is empty"
        )
    replay_namespaces = tuple(
        getattr(item, "namespace_receipt", None)
        for item in operational_replays.values()
    )
    replay_orchestrations = tuple(
        getattr(item, "orchestration_receipt", None)
        for item in operational_replays.values()
    )
    if any(
        item is None
        for item in (*replay_namespaces, *replay_orchestrations)
    ):
        raise CustodianReleaseError(
            "G238 replay authority receipts are unavailable"
        )
    observed = {
        "source_executor": source_executor,
        "namespace_authority": _single_authority(
            tuple(
                item.policy.namespace_authority_cid
                for item in namespace_sets
            ),
            "namespace authority",
        ),
        "namespace_observer": _single_authority(
            tuple(
                receipt.namespace_observer_identity_cid
                for receipt in orchestration_receipts
            ),
            "namespace observer",
        ),
        "source_orchestration_observer": _single_authority(
            tuple(
                receipt.orchestration_observer_identity_cid
                for receipt in orchestration_receipts
            ),
            "source orchestration observer",
        ),
        "runtime_namespace_validator": _single_authority(
            tuple(item.validator_identity_cid for item in namespace_sets),
            "runtime namespace validator",
        ),
        "source_orchestration_validator": _single_authority(
            tuple(
                item.validator_identity_cid
                for item in orchestration_sets
            ),
            "source orchestration validator",
        ),
        "resource_meter": _single_authority(
            tuple(
                receipt.meter_identity_cid
                for receipt in resource_receipts
            ),
            "resource meter",
        ),
        "resource_validator": _single_authority(
            tuple(
                receipt.validator_identity_cid
                for receipt in resource_receipts
            ),
            "resource validator",
        ),
        "replay_executor": _single_authority(
            tuple(
                receipt.replay_executor_identity_cid
                for receipt in replay_namespaces
            ),
            "replay executor",
        ),
        "replay_namespace_observer": _single_authority(
            (
                *(
                    receipt.replay_observer_identity_cid
                    for receipt in replay_namespaces
                ),
                sources.get("replay_validator_authority_cid"),
            ),
            "replay namespace observer",
        ),
        "replay_orchestration_observer": _single_authority(
            tuple(
                receipt.orchestration_observer_identity_cid
                for receipt in replay_orchestrations
            ),
            "replay orchestration observer",
        ),
        "freeze_producer": freeze.freeze_producer_identity_cid,
        "freeze_validator": freeze.freeze_validator_identity_cid,
        "runtime_identity_policy_authority": (
            freeze.runtime_identity_policy.policy_authority_cid
        ),
        "artifact_validator": artifacts.validator_identity_cid,
        "control_reviewer": control_index.review_authority_cid,
    }
    if any(observed[role] != manifested[role] for role in manifested_roles):
        raise CustodianReleaseError(
            "G211/G231/G237/G238/G240 authorities differ from the "
            "pre-execution G202 authority-role manifest"
        )
    roles = {role: manifested[role] for role in manifested_roles}
    if set(roles) != set(G241_UPSTREAM_AUTHORITY_ROLES) or len(
        set(roles.values())
    ) != len(roles):
        raise CustodianReleaseError(
            "full upstream authority roles overlap or are incomplete"
        )
    return MappingProxyType(roles)


def _join_g211_to_g231_bindings(
    *,
    rebuilt_bundle: Mapping[str, object],
    g211_graph: Mapping[str, object],
    batches: Sequence[object],
    authority_role_manifest_cid: str,
) -> None:
    bindings = _mapping(
        rebuilt_bundle.get("source_bindings"), "G231 source bindings"
    )
    expected_batches = {
        split: str(batches[index].receipt_cid)
        for index, split in enumerate(("pilot", "development"))
    }
    expected_namespace_policies = {
        split: str(
            batches[index]
            .runtime_namespace_evidence_set
            .policy
            .policy_cid
        )
        for index, split in enumerate(("pilot", "development"))
    }
    expected_namespace_sets = {
        split: str(
            batches[index]
            .runtime_namespace_evidence_set
            .evidence_set_cid
        )
        for index, split in enumerate(("pilot", "development"))
    }
    expected_orchestration_sets = {
        split: str(
            batches[index]
            .source_orchestration_evidence_set
            .evidence_set_cid
        )
        for index, split in enumerate(("pilot", "development"))
    }
    if (
        bindings.get("authority_role_manifest_cid")
        != _dag_cid(
            authority_role_manifest_cid,
            "G202 authority-role manifest CID",
        )
        or _plain(bindings.get("g211_runtime_batch_receipt_cids"))
        != expected_batches
        or _plain(
            bindings.get("g240_runtime_namespace_policy_cids")
        )
        != expected_namespace_policies
        or _plain(
            bindings.get(
                "g240_runtime_namespace_evidence_set_cids"
            )
        )
        != expected_namespace_sets
        or _plain(
            bindings.get(
                "g240_source_orchestration_evidence_set_cids"
            )
        )
        != expected_orchestration_sets
        or tuple(g211_graph["batch_receipt_cids"])
        != tuple(expected_batches.values())
    ):
        raise CustodianReleaseError(
            "G211 batch/namespace/orchestration identities differ from "
            "the source-recomputed G231 bindings"
        )
    for batch in batches:
        plan_cid = str(batch.receipt["plan_cid"])
        namespace_set = batch.runtime_namespace_evidence_set
        orchestration_set = batch.source_orchestration_evidence_set
        if (
            namespace_set.policy.plan_cids != (plan_cid,)
            or orchestration_set.plan_cids != (plan_cid,)
            or any(
                receipt.plan_cid != plan_cid
                for receipt in orchestration_set.receipts
            )
        ):
            raise CustodianReleaseError(
                "G211 plan identities differ from their namespace or "
                "orchestration graphs"
            )


def recompute_g241_source_chain_v1(
    *,
    g231_bundle: object,
    g231_sources: Mapping[str, object],
    g232_proposal: object,
) -> G241SourceReplayResultV1:
    """Recompute the complete upstream graph and exact G232 proposal.

    This function is deliberately non-authorizing.  In particular, its
    return value cannot be used by the replacement-holdout loader in place of
    an externally governed G241 release receipt.
    """

    sources = dict(_mapping(g231_sources, "G231 source records"))
    try:
        rebuilt_bundle = validate_g231_positive_gate_bundle_v2(
            g231_bundle,
            **sources,
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise CustodianReleaseError(
            "G231 positive bundle failed complete canonical source replay"
        ) from exc
    _positive_gate(rebuilt_bundle, "source-replayed G231 bundle")

    freeze_value = sources.get("g202_freeze")
    index_value = sources.get("g201_index")
    matrix_value = sources.get("runtime_matrix")
    seal_value = sources.get("replacement_holdout_seal")
    bindings_value = sources.get("artifact_bindings")
    if not isinstance(freeze_value, G202FrozenRunInputsV2):
        raise CustodianReleaseError("G241 requires typed G202 freeze sources")
    if not isinstance(index_value, G201SemanticEvidenceIndexV2):
        raise CustodianReleaseError("G241 requires typed G201 source records")
    if not isinstance(matrix_value, G210RuntimeReceiptMatrixV2):
        raise CustodianReleaseError("G241 requires typed G212 runtime sources")
    if not isinstance(seal_value, ReplacementHoldoutSeal):
        raise CustodianReleaseError("G241 requires typed G220 seal metadata")
    if not isinstance(bindings_value, G231ArtifactBindingsV2):
        raise CustodianReleaseError(
            "G241 requires typed G231 artifact bindings"
        )
    freeze = G202FrozenRunInputsV2.from_dict(freeze_value.to_dict())
    index = validate_g201_semantic_evidence_index_v2(index_value)
    matrix = G210RuntimeReceiptMatrixV2.from_dict(matrix_value.to_dict())
    seal = ReplacementHoldoutSeal.from_dict(seal_value.to_dict())
    bindings = G231ArtifactBindingsV2.from_dict(
        bindings_value.to_dict()
    )
    if (
        freeze.frozen is not True
        or freeze.holdout_accessed is not False
        or freeze.source_freeze.ready is not True
        or matrix.complete is not True
        or index.absolute_quality_passed is not True
    ):
        raise CustodianReleaseError(
            "G201/G202/G212 sources are not complete, clean, and frozen"
        )

    g211_graph, batches = _replay_g211_batches(
        _g231_persisted_batch_sources(sources), matrix
    )
    _join_g211_to_g231_bindings(
        rebuilt_bundle=rebuilt_bundle,
        g211_graph=g211_graph,
        batches=batches,
        authority_role_manifest_cid=(
            freeze.authority_role_manifest.manifest_cid
        ),
    )
    g212_body = {
        "schema": G241_G212_GRAPH_SCHEMA_V1,
        "runtime_matrix_cid": matrix.runtime_matrix_cid,
        "runtime_evidence_cids": sorted(
            item.receipt_cid for item in matrix.runtime_evidence
        ),
        "g211_persisted_runtime_graph_cid": g211_graph["graph_cid"],
        "resource_evidence_set_cid": bindings.artifact_cids[
            "g237_resource_evidence_set"
        ],
        "resource_statistics_receipt_cid": _mapping(
            sources.get("resource_statistics_gate"),
            "resource statistics gate",
        ).get("receipt_cid"),
        "efficacy_receipt_cid": _mapping(
            sources.get("efficacy_gate"), "efficacy gate"
        ).get("receipt_cid"),
        "reliability_receipt_cid": _mapping(
            sources.get("reliability_gate"), "reliability gate"
        ).get("receipt_cid"),
        "routing_receipt_cid": _mapping(
            sources.get("routing_gate"), "routing gate"
        ).get("receipt_cid"),
        "complete": True,
        "holdout_included": False,
        "source_recomputed": True,
    }
    g212_graph = {
        **g212_body,
        "graph_cid": cid_for_dag_json(g212_body),
    }
    selection = derive_g232_shortlist_from_validated_gates_v1(
        g231_bundle=rebuilt_bundle,
        semantic_quality_gate=sources.get("semantic_quality_gate"),
        efficacy_gate=sources.get("efficacy_gate"),
        reliability_gate=sources.get("reliability_gate"),
        routing_gate=sources.get("routing_gate"),
        safety_gate=sources.get("safety_gate"),
        resource_statistics_gate=sources.get(
            "resource_statistics_gate"
        ),
        detached_replay_gate=sources.get("detached_replay_gate"),
    )
    selected = tuple(
        str(item)
        for item in _array(
            selection["selected_candidate_ids"],
            "selected candidates",
        )
    )
    pilot_body = {
        "schema": G241_PILOT_DECISION_SCHEMA_V1,
        "g201_semantic_evidence_index_cid": index.index_cid,
        "g202_freeze_cid": freeze.receipt_cid,
        "g211_persisted_runtime_graph_cid": g211_graph["graph_cid"],
        "g212_causal_resource_graph_cid": g212_graph["graph_cid"],
        "g220_seal_contract_cid": seal.seal_contract_cid,
        "g231_positive_gate_bundle_cid": rebuilt_bundle["bundle_cid"],
        "shortlist_selection_cid": selection["selection_cid"],
        "selected_candidate_ids": list(selected),
        "authorized_variant_ids": ["A0", *selected],
        "complete": True,
        "passed": True,
        "holdout_accessed": False,
        "holdout_outcomes_inspected": False,
        "production_promotion_authorized": False,
        "source_recomputed": True,
    }
    pilot_decision = {
        **pilot_body,
        "pilot_decision_cid": cid_for_dag_json(pilot_body),
    }
    expected_proposal = _build_expected_g232_authorization(
        pilot_artifact_cid=pilot_decision["pilot_decision_cid"],
        seal=seal,
        source_commit=freeze.source_freeze.source_commit,
        selected_candidates=selected,
    )
    supplied_proposal = validate_g232_proposal_against_source_replay_v1(
        proposal=g232_proposal,
        selection_evidence=selection,
        pilot_decision=pilot_decision,
        seal=seal,
        source_commit=freeze.source_freeze.source_commit,
    )
    assert supplied_proposal.to_dict() == expected_proposal.to_dict()

    parents = {
        "g201_semantic_evidence": index.index_cid,
        "g202_source_run_freeze": freeze.receipt_cid,
        "g211_persisted_runtime_graph": g211_graph["graph_cid"],
        "g212_causal_resource_graph": g212_graph["graph_cid"],
        "g220_replacement_holdout_seal": seal.seal_contract_cid,
        "g231_positive_gate_bundle": rebuilt_bundle["bundle_cid"],
        "g232_authorization_proposal": (
            expected_proposal.authorization_cid
        ),
    }
    namespaces = {
        "worktree": freeze.source_worktree_cid,
        "cache_policy": freeze.cache_policy.policy_cid,
        "runtime_identity_policy": (
            freeze.runtime_identity_policy.policy_cid
        ),
        "execution_identities": freeze.execution_identities.bundle_cid,
        "runtime_orchestration_policy": (
            freeze.runtime_orchestration_policy_cid
        ),
        "runtime_namespace_policy_pilot": (
            g211_graph["runtime_namespace_policy_cids"][0]
        ),
        "runtime_namespace_policy_development": (
            g211_graph["runtime_namespace_policy_cids"][1]
        ),
        "runtime_namespace_evidence_pilot": (
            g211_graph["runtime_namespace_evidence_set_cids"][0]
        ),
        "runtime_namespace_evidence_development": (
            g211_graph["runtime_namespace_evidence_set_cids"][1]
        ),
        "source_orchestration_evidence_pilot": (
            g211_graph["source_orchestration_evidence_set_cids"][0]
        ),
        "source_orchestration_evidence_development": (
            g211_graph["source_orchestration_evidence_set_cids"][1]
        ),
    }
    upstream_authorities = _derive_upstream_authorities(
        freeze=freeze,
        artifacts=bindings,
        batches=batches,
        sources=sources,
    )
    source_index = G241SourceDecisionIndexV1(
        source_commit=freeze.source_freeze.source_commit,
        source_commit_cid=freeze.source_commit_cid,
        source_tree_cid=freeze.source_freeze.source_tree_cid,
        recursive_gitlinks_cid=freeze.recursive_gitlinks_cid,
        run_plan_cid=freeze.run_plan_cid,
        capability_inventory_cid=freeze.capability_inventory_cid,
        environment_cid=freeze.environment_cid,
        namespace_identity_cids=namespaces,
        upstream_authority_cids=upstream_authorities,
        parent_artifact_cids=parents,
        g211_batch_receipt_cids=tuple(
            str(item)
            for item in _array(
                g211_graph["batch_receipt_cids"],
                "G211 batch receipt CIDs",
            )
        ),
        g212_runtime_evidence_cids=tuple(
            sorted(item.receipt_cid for item in matrix.runtime_evidence)
        ),
        shortlist_selection_cid=str(selection["selection_cid"]),
        g232_pilot_decision_cid=str(
            pilot_decision["pilot_decision_cid"]
        ),
        access_ledger_authority_cid=(
            seal.access_ledger_authority_cid
        ),
    )
    artifacts = {
        **parents,
        "g232_pilot_decision": pilot_decision["pilot_decision_cid"],
    }
    parent_ledger_body = {
        "schema": G241_PARENT_LEDGER_SCHEMA_V1,
        "goal_id": G241_GOVERNED_GOAL_ID,
        "source_index_cid": source_index.source_index_cid,
        "ordered_parent_artifact_cids": {
            key: parents[key] for key in G241_PARENT_KEYS
        },
        "shortlist_selection_cid": selection["selection_cid"],
        "complete": True,
        "holdout_accessed": False,
    }
    return G241SourceReplayResultV1(
        source_index=source_index,
        selection_evidence=selection,
        pilot_decision=_freeze(pilot_decision),  # type: ignore[arg-type]
        authorization=expected_proposal,
        external_artifact_cids=artifacts,
        parent_ledger_cid=cid_for_dag_json(parent_ledger_body),
    )


@dataclass(frozen=True, slots=True)
class _CurrentSourceV1:
    outer_commit: str
    outer_tree: str
    submodule_map_cid: str
    source_identity_cid: str
    g240_recursive_gitlinks_cid: str


def _git_executable_identity_from_fd(
    candidate: Path,
    descriptor: int,
) -> str:
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or not before.st_mode & stat.S_IXUSR
        or before.st_nlink != 1
        or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise CustodianReleaseError(
            "pinned Git executable is not a safe regular executable"
        )
    raw = _read_bounded_fd(
        descriptor,
        field_name="pinned Git executable",
        maximum_bytes=64 * 1024 * 1024,
    )
    after = os.fstat(descriptor)
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise CustodianReleaseError(
            "pinned Git executable changed while it was being read"
        )
    return cid_for_dag_json(
        {
            "schema": G241_GIT_EXECUTABLE_IDENTITY_SCHEMA_V1,
            "absolute_path": str(candidate),
            "raw_executable_cid": cid_for_bytes(raw, codec="raw"),
        }
    )


def _open_pinned_git_executable(
    executable_path: Path,
) -> tuple[Path, int, str]:
    candidate = _canonical_absolute_path(
        Path(executable_path), "pinned Git executable"
    )
    descriptor = -1
    try:
        descriptor = _open_secure_file(
            candidate,
            repo_root=None,
            field_name="pinned Git executable",
            flags=os.O_RDONLY,
            create=False,
            private=False,
        )
        identity_cid = _git_executable_identity_from_fd(
            candidate, descriptor
        )
        return candidate, descriptor, identity_cid
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def g241_git_executable_cid_v1(executable_path: Path) -> str:
    """Address one externally configured absolute Git executable.

    PATH lookup is deliberately forbidden.  Every path component must be
    real (not a symbolic link), the final object must be a single-link
    regular executable, and group/other write permission is rejected.
    """

    descriptor = -1
    try:
        _, descriptor, identity_cid = _open_pinned_git_executable(
            Path(executable_path)
        )
        return identity_cid
    except (OSError, ValueError) as exc:
        raise CustodianReleaseError(
            "pinned Git executable is unavailable"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _git(
    root: Path,
    *arguments: str,
    binary: bool = False,
    executable_path: Path,
    expected_executable_cid: str | None = None,
) -> tuple[int, str | bytes]:
    descriptor = -1
    try:
        candidate, descriptor, executable_cid = (
            _open_pinned_git_executable(Path(executable_path))
        )
    except (OSError, ValueError):
        return 1, b"" if binary else ""
    if (
        expected_executable_cid is not None
        and executable_cid
        != _dag_cid(
            expected_executable_cid,
            "trusted Git executable CID",
        )
    ):
        os.close(descriptor)
        return 1, b"" if binary else ""
    try:
        descriptor_path = f"/proc/self/fd/{descriptor}"
        if not Path(descriptor_path).exists():
            return 1, b"" if binary else ""
        completed = subprocess.run(
            [
                str(candidate),
                "--no-replace-objects",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.untrackedCache=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                f"core.worktree={root}",
                "-c",
                "core.symlinks=true",
                "-c",
                "core.fileMode=true",
                "-c",
                "core.ignoreCase=false",
                "-c",
                "core.attributesFile=/dev/null",
                "-c",
                "core.excludesFile=/dev/null",
                *arguments,
            ],
            executable=descriptor_path,
            pass_fds=(descriptor,),
            cwd=root,
            env=dict(_GIT_SAFE_ENV),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=not binary,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, b"" if binary else ""
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    output: str | bytes = completed.stdout
    return (
        completed.returncode,
        output if binary else str(output).strip(),
    )


def _git_clean(
    root: Path,
    *,
    git_executable_path: Path,
    expected_executable_cid: str | None = None,
) -> bool:
    """Require the index and every live tracked byte to equal ``HEAD``.

    ``git status`` alone is not a source-integrity check: assume-unchanged and
    skip-worktree entries can conceal tracked changes, while ignored Python or
    executable files can alter imports or process dispatch.  The checks below
    reject those states and compare live blobs and modes to the no-replace
    ``HEAD`` tree.
    """

    code, output = _git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        binary=True,
        executable_path=git_executable_path,
        expected_executable_cid=expected_executable_cid,
    )
    if code != 0 or output != b"":
        return False

    replace_code, replace_output = _git(
        root,
        "replace",
        "-l",
        binary=True,
        executable_path=git_executable_path,
        expected_executable_cid=expected_executable_cid,
    )
    if replace_code != 0 or replace_output != b"":
        return False

    config_code, config_output = _git(
        root,
        "config",
        "--local",
        "--null",
        "--get-regexp",
        (
            r"^(core\.(worktree|symlinks|ignorecase|precomposeunicode|"
            r"sparsecheckout|sparsecheckoutcone|attributesfile|excludesfile))$"
        ),
        binary=True,
        executable_path=git_executable_path,
        expected_executable_cid=expected_executable_cid,
    )
    # ``git config --get-regexp`` returns one when there are no matches.
    if config_code not in {0, 1} or config_output:
        return False

    flags_code, flags_output = _git(
        root,
        "ls-files",
        "-v",
        "-z",
        binary=True,
        executable_path=git_executable_path,
        expected_executable_cid=expected_executable_cid,
    )
    if flags_code != 0 or not isinstance(flags_output, bytes):
        return False
    if any(
        not entry.startswith(b"H ")
        for entry in flags_output.split(b"\0")
        if entry
    ):
        return False

    tree_code, tree_output = _git(
        root,
        "ls-tree",
        "-r",
        "-z",
        "HEAD",
        binary=True,
        executable_path=git_executable_path,
        expected_executable_cid=expected_executable_cid,
    )
    index_code, index_output = _git(
        root,
        "ls-files",
        "--stage",
        "-z",
        binary=True,
        executable_path=git_executable_path,
        expected_executable_cid=expected_executable_cid,
    )
    if (
        tree_code != 0
        or index_code != 0
        or not isinstance(tree_output, bytes)
        or not isinstance(index_output, bytes)
    ):
        return False
    try:
        tree_entries = _parse_git_tree_entries(tree_output)
        index_entries = _parse_git_index_entries(index_output)
    except (UnicodeError, ValueError):
        return False
    if tuple(
        (mode, oid, raw_path) for mode, _, oid, raw_path in tree_entries
    ) != index_entries:
        return False
    if not _live_tracked_tree_matches(root, tree_entries):
        return False

    ignored_code, ignored_output = _git(
        root,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
        binary=True,
        executable_path=git_executable_path,
        expected_executable_cid=expected_executable_cid,
    )
    if (
        ignored_code != 0
        or not isinstance(ignored_output, bytes)
        or _ignored_source_risk(root, ignored_output)
    ):
        return False
    return True


def _parse_git_tree_entries(
    raw: bytes,
) -> tuple[tuple[str, str, str, bytes], ...]:
    entries: list[tuple[str, str, str, bytes]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        parts = metadata.split()
        if (
            not separator
            or len(parts) != 3
            or parts[0] not in {b"100644", b"100755", b"120000", b"160000"}
            or parts[1] not in {b"blob", b"commit"}
            or not raw_path
        ):
            raise ValueError("invalid Git tree entry")
        mode = parts[0].decode("ascii")
        kind = parts[1].decode("ascii")
        oid = parts[2].decode("ascii")
        _git_object(oid, "tracked object")
        path = PurePosixPath(
            raw_path.decode("utf-8", errors="surrogateescape")
        )
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise ValueError("unsafe tracked path")
        entries.append((mode, kind, oid, raw_path))
    return tuple(entries)


def _parse_git_index_entries(
    raw: bytes,
) -> tuple[tuple[str, str, bytes], ...]:
    entries: list[tuple[str, str, bytes]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        parts = metadata.split()
        if (
            not separator
            or len(parts) != 3
            or parts[2] != b"0"
            or not raw_path
        ):
            raise ValueError("invalid Git index entry")
        mode = parts[0].decode("ascii")
        oid = parts[1].decode("ascii")
        _git_object(oid, "indexed object")
        entries.append((mode, oid, raw_path))
    return tuple(entries)


def _git_blob_oid(path: Path, metadata: os.stat_result, oid: str) -> str:
    algorithm = hashlib.sha1() if len(oid) == 40 else hashlib.sha256()
    algorithm.update(f"blob {metadata.st_size}\0".encode("ascii"))
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or (before.st_dev, before.st_ino, before.st_size)
            != (metadata.st_dev, metadata.st_ino, metadata.st_size)
        ):
            return ""
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            algorithm.update(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            return ""
        return algorithm.hexdigest()
    except OSError:
        return ""
    finally:
        os.close(descriptor)


def _live_tracked_tree_matches(
    root: Path,
    entries: Sequence[tuple[str, str, str, bytes]],
) -> bool:
    for mode, kind, oid, raw_path in entries:
        if mode == "160000" and kind == "commit":
            continue
        if kind != "blob":
            return False
        relative = os.fsdecode(raw_path)
        path = root / relative
        try:
            metadata = path.lstat()
        except OSError:
            return False
        if mode == "120000":
            if not stat.S_ISLNK(metadata.st_mode):
                return False
            try:
                target = os.fsencode(os.readlink(path))
            except OSError:
                return False
            algorithm = (
                hashlib.sha1() if len(oid) == 40 else hashlib.sha256()
            )
            algorithm.update(f"blob {len(target)}\0".encode("ascii"))
            algorithm.update(target)
            if algorithm.hexdigest() != oid:
                return False
            continue
        if not stat.S_ISREG(metadata.st_mode):
            return False
        expected_executable = mode == "100755"
        if bool(metadata.st_mode & 0o111) != expected_executable:
            return False
        if _git_blob_oid(path, metadata, oid) != oid:
            return False
    return True


def _ignored_source_risk(root: Path, raw: bytes) -> bool:
    risky_suffixes = {
        ".dll",
        ".dylib",
        ".pth",
        ".py",
        ".pyc",
        ".pyo",
        ".sh",
        ".so",
    }
    risky_names = {"sitecustomize.py", "usercustomize.py"}
    for raw_path in raw.split(b"\0"):
        if not raw_path:
            continue
        relative = os.fsdecode(raw_path)
        path = root / relative
        try:
            metadata = path.lstat()
        except OSError:
            return True
        if (
            path.name.casefold() in risky_names
            or path.suffix.casefold() in risky_suffixes
            or stat.S_ISLNK(metadata.st_mode)
            or bool(metadata.st_mode & 0o111)
        ):
            return True
    return False


def _gitlinks_at(
    root: Path,
    commit: str,
    *,
    git_executable_path: Path,
    expected_executable_cid: str | None = None,
) -> tuple[tuple[str, str], ...]:
    code, output = _git(
        root,
        "ls-tree",
        "-r",
        "-z",
        commit,
        binary=True,
        executable_path=git_executable_path,
        expected_executable_cid=expected_executable_cid,
    )
    if code != 0 or not isinstance(output, bytes):
        raise CustodianReleaseError(
            "current recursive Gitlink map is unavailable"
        )
    rows: list[tuple[str, str]] = []
    for raw in output.split(b"\0"):
        if not raw or b"\t" not in raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        parts = metadata.split()
        if len(parts) == 3 and parts[0] == b"160000":
            rows.append(
                (
                    raw_path.decode(
                        "utf-8", errors="surrogateescape"
                    ),
                    parts[2].decode("ascii"),
                )
            )
    return tuple(sorted(rows))


def _inspect_current_source(
    repo_root: Path,
    *,
    git_executable_path: Path,
    expected_git_executable_cid: str | None = None,
) -> _CurrentSourceV1:
    root = Path(repo_root).resolve()
    code, output = _git(
        root,
        "rev-parse",
        "--show-toplevel",
        executable_path=git_executable_path,
        expected_executable_cid=expected_git_executable_cid,
    )
    if code != 0 or Path(str(output)).resolve() != root:
        raise CustodianReleaseError(
            "G241 source must name one Git worktree root"
        )
    commit_code, commit_value = _git(
        root,
        "rev-parse",
        "HEAD",
        executable_path=git_executable_path,
        expected_executable_cid=expected_git_executable_cid,
    )
    tree_code, tree_value = _git(
        root,
        "rev-parse",
        "HEAD^{tree}",
        executable_path=git_executable_path,
        expected_executable_cid=expected_git_executable_cid,
    )
    branch_code, _ = _git(
        root,
        "symbolic-ref",
        "-q",
        "HEAD",
        executable_path=git_executable_path,
        expected_executable_cid=expected_git_executable_cid,
    )
    if (
        commit_code
        or tree_code
        or branch_code == 0
        or not _git_clean(
            root,
            git_executable_path=git_executable_path,
            expected_executable_cid=expected_git_executable_cid,
        )
    ):
        raise CustodianReleaseError(
            "G241 requires a clean detached committed source tree"
        )
    commit = _git_object(commit_value, "current source commit")
    tree = _git_object(tree_value, "current source tree")
    entries: list[dict[str, object]] = []
    g240_records: list[object] = []
    visited: set[tuple[Path, str]] = set()

    def visit(
        checkout: Path,
        pinned_commit: str,
        *,
        parent_gitlink_id: str = "",
        prefix: str = "",
        depth: int = 0,
    ) -> None:
        identity = (checkout.resolve(), pinned_commit)
        if identity in visited or depth > 16:
            raise CustodianReleaseError(
                "recursive Gitlink map is cyclic or too deep"
            )
        visited.add(identity)
        for relative, recorded_commit in _gitlinks_at(
            checkout,
            pinned_commit,
            git_executable_path=git_executable_path,
            expected_executable_cid=expected_git_executable_cid,
        ):
            qualified = f"{prefix}/{relative}" if prefix else relative
            link_id = cid_for_dag_json(
                {
                    "schema": G239_EXTERNAL_GITLINK_SCHEMA + "/location",
                    "parent_commit": pinned_commit,
                    "location": relative,
                }
            )
            child = (checkout / relative).resolve()
            try:
                child.relative_to(root)
            except ValueError as exc:
                raise CustodianReleaseError(
                    "Gitlink checkout escaped the source worktree"
                ) from exc
            child_code, child_head = _git(
                child,
                "rev-parse",
                "HEAD",
                executable_path=git_executable_path,
                expected_executable_cid=expected_git_executable_cid,
            )
            child_tree_code, child_tree = _git(
                child,
                "rev-parse",
                "HEAD^{tree}",
                executable_path=git_executable_path,
                expected_executable_cid=expected_git_executable_cid,
            )
            if (
                child_code
                or child_tree_code
                or child_head != recorded_commit
                or not _git_clean(
                    child,
                    git_executable_path=git_executable_path,
                    expected_executable_cid=expected_git_executable_cid,
                )
            ):
                raise CustodianReleaseError(
                    "recursive Gitlink checkout is missing, dirty, or rebased"
                )
            entry = {
                "schema": G239_EXTERNAL_GITLINK_SCHEMA,
                "gitlink_id": link_id,
                "commit": _git_object(
                    recorded_commit, "Gitlink commit"
                ),
                "tree": _git_object(child_tree, "Gitlink tree"),
                "parent_gitlink_id": parent_gitlink_id,
                "depth": depth,
            }
            entries.append(entry)
            try:
                from .source_reconciliation import GitlinkIdentity

                g240_records.append(
                    GitlinkIdentity(
                        path=qualified,
                        commit=recorded_commit,
                        parent_path=prefix or ".",
                        parent_commit=pinned_commit,
                        depth=depth + 1,
                    )
                )
            except (ImportError, TypeError, ValueError) as exc:
                raise CustodianReleaseError(
                    "current G240 Gitlink identity projection failed"
                ) from exc
            visit(
                child,
                str(child_head),
                parent_gitlink_id=link_id,
                prefix=qualified,
                depth=depth + 1,
            )

    visit(root, commit)
    entries.sort(key=lambda item: str(item["gitlink_id"]))
    submodule_map_cid = cid_for_dag_json(
        {
            "schema": G239_EXTERNAL_SOURCE_SCHEMA + "/submodule-map",
            "entries": entries,
        }
    )
    source_identity_cid = cid_for_dag_json(
        {
            "schema": G239_EXTERNAL_SOURCE_SCHEMA,
            "outer_commit": commit,
            "outer_tree": tree,
            "clean": True,
            "recursive_gitlinks_complete": True,
            "submodule_map_cid": submodule_map_cid,
        }
    )
    try:
        from .namespace_provenance import g240_recursive_gitlinks_cid

        g240_gitlinks = g240_recursive_gitlinks_cid(
            tuple(sorted(g240_records))
        )
    except (ImportError, TypeError, ValueError) as exc:
        raise CustodianReleaseError(
            "current G240 recursive Gitlink projection failed"
        ) from exc
    return _CurrentSourceV1(
        outer_commit=commit,
        outer_tree=tree,
        submodule_map_cid=submodule_map_cid,
        source_identity_cid=source_identity_cid,
        g240_recursive_gitlinks_cid=g240_gitlinks,
    )


def _external_file(
    path: Path,
    *,
    repo_root: Path,
    field_name: str,
) -> Mapping[str, object]:
    descriptor = _open_secure_file(
        Path(path),
        repo_root=Path(repo_root),
        field_name=field_name,
        flags=os.O_RDONLY,
        create=False,
        private=False,
    )
    try:
        before = os.fstat(descriptor)
        raw = _read_bounded_fd(descriptor, field_name=field_name)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise CustodianReleaseError(
                f"{field_name} changed while it was being read"
            )
    finally:
        os.close(descriptor)
    return _mapping(_strict_json(raw, field_name), field_name)


def _canonical_absolute_path(path: Path, field_name: str) -> Path:
    candidate = Path(path)
    if (
        not candidate.is_absolute()
        or ".." in candidate.parts
        or str(candidate) != os.path.normpath(str(candidate))
        or candidate.name in {"", ".", ".."}
    ):
        raise CustodianReleaseError(
            f"{field_name} must use canonical absolute spelling"
        )
    return candidate


def g241_release_ledger_authority_cid_v1(
    *,
    ledger_path: Path,
    ledger_genesis_cid: str,
    monotonic_store_id: str,
    monotonic_store_policy_cid: str,
) -> str:
    """Bind an externally pinned store policy to one lexical ledger path."""

    candidate = _canonical_absolute_path(
        Path(ledger_path), "custodian release ledger"
    )
    return cid_for_dag_json(
        {
            "schema": G241_RELEASE_LEDGER_AUTHORITY_SCHEMA_V1,
            "canonical_absolute_ledger_path": str(candidate),
            "ledger_genesis_cid": _dag_cid(
                ledger_genesis_cid, "ledger_genesis_cid"
            ),
            "monotonic_store_id": _actor(
                monotonic_store_id, "monotonic_store_id"
            ),
            "monotonic_store_policy_cid": _dag_cid(
                monotonic_store_policy_cid,
                "monotonic_store_policy_cid",
            ),
            "external_monotonic_store_required": True,
        }
    )


def _ledger_file_identity_cid(
    descriptor: int,
    *,
    ledger_role: str,
) -> str:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise CustodianReleaseError(
            f"{ledger_role} is no longer a private single-link file"
        )
    return cid_for_dag_json(
        {
            "schema": G241_LEDGER_FILE_IDENTITY_SCHEMA_V1,
            "ledger_role": ledger_role,
            "filesystem_device": metadata.st_dev,
            "filesystem_inode": metadata.st_ino,
        }
    )


def _require_external_path(
    candidate: Path,
    *,
    repo_root: Path,
    field_name: str,
) -> None:
    root = Path(repo_root).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError:
        return
    raise CustodianReleaseError(
        f"{field_name} must be independently stored outside source"
    )


def _open_secure_file(
    path: Path,
    *,
    repo_root: Path | None,
    field_name: str,
    flags: int,
    create: bool,
    private: bool,
) -> int:
    """Open a regular file through no-follow directory descriptors.

    Both the directory walk and final component are resolved with
    ``O_NOFOLLOW``.  The returned descriptor, not a pathname reopened later,
    is the object whose metadata and contents are validated.
    """

    candidate = _canonical_absolute_path(Path(path), field_name)
    if repo_root is not None:
        _require_external_path(
            candidate,
            repo_root=repo_root,
            field_name=field_name,
        )
    required_flags = ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC")
    if any(not hasattr(os, name) for name in required_flags):
        raise CustodianReleaseError(
            "G241 requires no-follow descriptor support"
        )
    directory_flags = (
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    directory_descriptor = -1
    descriptor = -1
    try:
        directory_descriptor = os.open(candidate.anchor, directory_flags)
        for component in candidate.parts[1:-1]:
            next_descriptor = os.open(
                component,
                directory_flags,
                dir_fd=directory_descriptor,
            )
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        open_flags = flags | os.O_NOFOLLOW | os.O_CLOEXEC
        created = False
        if create:
            try:
                descriptor = os.open(
                    candidate.name,
                    open_flags | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=directory_descriptor,
                )
                created = True
            except FileExistsError:
                descriptor = os.open(
                    candidate.name,
                    open_flags,
                    0o600,
                    dir_fd=directory_descriptor,
                )
        else:
            descriptor = os.open(
                candidate.name,
                open_flags,
                0o600,
                dir_fd=directory_descriptor,
            )
        descriptor_metadata = os.fstat(descriptor)
        path_metadata = os.stat(
            candidate.name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(descriptor_metadata.st_mode)
            or descriptor_metadata.st_nlink != 1
            or (descriptor_metadata.st_dev, descriptor_metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
            or (
                private
                and stat.S_IMODE(descriptor_metadata.st_mode) & 0o077
            )
            or (
                not private
                and descriptor_metadata.st_mode
                & (stat.S_IWGRP | stat.S_IWOTH)
            )
        ):
            raise CustodianReleaseError(
                f"{field_name} must be a stable, single-link regular file "
                "with safe permissions"
            )
        if created:
            # A file fsync alone does not portably persist its new directory
            # entry.  Make both the empty inode and its name durable before a
            # later receipt can claim that this is the ledger being appended.
            os.fsync(descriptor)
            os.fsync(directory_descriptor)
        return descriptor
    except (OSError, RuntimeError) as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise CustodianReleaseError(
            f"{field_name} cannot be securely opened"
        ) from exc
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    finally:
        if directory_descriptor >= 0:
            os.close(directory_descriptor)


def _read_bounded_fd(
    descriptor: int,
    *,
    field_name: str,
    maximum_bytes: int = _MAX_EXTERNAL_FILE_BYTES,
) -> bytes:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                break
            size += len(chunk)
            if size > maximum_bytes:
                raise CustodianReleaseError(
                    f"{field_name} exceeds the bounded validation size"
                )
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError as exc:
        raise CustodianReleaseError(
            f"{field_name} cannot be read"
        ) from exc


def _strict_json(raw: bytes, field_name: str) -> object:
    def reject_duplicates(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise CustodianReleaseError(
                    f"{field_name} contains duplicate JSON key {key!r}"
                )
            result[key] = value
        return result

    try:
        text = raw.decode("utf-8")
        return json.loads(text, object_pairs_hook=reject_duplicates)
    except CustodianReleaseError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CustodianReleaseError(
            f"{field_name} must contain strict UTF-8 JSON"
        ) from exc


def _parse_time(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise CustodianReleaseError(
            f"{field_name} must be an ISO-8601 timestamp"
        )
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        result = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CustodianReleaseError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from exc
    if result.tzinfo is None:
        raise CustodianReleaseError(
            f"{field_name} must include a timezone"
        )
    return result.astimezone(timezone.utc)


def _validate_g239_source(
    value: object,
) -> Mapping[str, object]:
    source = _mapping(value, "G239 source identity")
    _exact(
        source,
        {
            "schema",
            "outer_commit",
            "outer_tree",
            "clean",
            "recursive_gitlinks_complete",
            "recursive_gitlinks",
            "submodule_map_cid",
            "source_identity_cid",
        },
        "G239 source identity",
    )
    if source.get("schema") != G239_EXTERNAL_SOURCE_SCHEMA:
        raise CustodianReleaseError("unsupported G239 source schema")
    commit = _git_object(source.get("outer_commit"), "G239 source commit")
    tree = _git_object(source.get("outer_tree"), "G239 source tree")
    if (
        source.get("clean") is not True
        or source.get("recursive_gitlinks_complete") is not True
    ):
        raise CustodianReleaseError("G239 source is dirty or incomplete")
    entries = tuple(
        _mapping(item, "G239 Gitlink")
        for item in _array(
            source.get("recursive_gitlinks"), "G239 Gitlinks"
        )
    )
    normalized_entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for entry in entries:
        _exact(
            entry,
            {
                "schema",
                "gitlink_id",
                "commit",
                "tree",
                "parent_gitlink_id",
                "depth",
            },
            "G239 Gitlink",
        )
        if entry.get("schema") != G239_EXTERNAL_GITLINK_SCHEMA:
            raise CustodianReleaseError("unsupported G239 Gitlink schema")
        link_id = _dag_cid(entry.get("gitlink_id"), "G239 Gitlink ID")
        if link_id in seen:
            raise CustodianReleaseError("G239 Gitlinks are duplicated")
        seen.add(link_id)
        parent = entry.get("parent_gitlink_id")
        if parent:
            parent = _dag_cid(parent, "G239 parent Gitlink ID")
        elif parent != "":
            raise CustodianReleaseError(
                "G239 parent Gitlink ID must be a CID or empty"
            )
        depth = entry.get("depth")
        if type(depth) is not int or depth < 0:
            raise CustodianReleaseError(
                "G239 Gitlink depth must be nonnegative"
            )
        normalized_entries.append(
            {
                "schema": G239_EXTERNAL_GITLINK_SCHEMA,
                "gitlink_id": link_id,
                "commit": _git_object(
                    entry.get("commit"), "G239 Gitlink commit"
                ),
                "tree": _git_object(
                    entry.get("tree"), "G239 Gitlink tree"
                ),
                "parent_gitlink_id": parent,
                "depth": depth,
            }
        )
    normalized_entries.sort(key=lambda item: str(item["gitlink_id"]))
    if list(entries) != normalized_entries:
        raise CustodianReleaseError(
            "G239 Gitlinks are not in canonical identity order"
        )
    map_cid = cid_for_dag_json(
        {
            "schema": G239_EXTERNAL_SOURCE_SCHEMA + "/submodule-map",
            "entries": normalized_entries,
        }
    )
    if source.get("submodule_map_cid") != map_cid:
        raise CustodianReleaseError("G239 submodule-map CID changed")
    identity_cid = cid_for_dag_json(
        {
            "schema": G239_EXTERNAL_SOURCE_SCHEMA,
            "outer_commit": commit,
            "outer_tree": tree,
            "clean": True,
            "recursive_gitlinks_complete": True,
            "submodule_map_cid": map_cid,
        }
    )
    if source.get("source_identity_cid") != identity_cid:
        raise CustodianReleaseError("G239 source identity CID changed")
    return source


def _g241_artifact_set_cid(
    artifact_cids: Mapping[str, str],
) -> str:
    artifacts = _mapping(
        artifact_cids, "G239 external artifact identities"
    )
    if set(artifacts) != set(G241_EXTERNAL_ARTIFACT_KEYS):
        raise CustodianReleaseError(
            "G239 external artifact set is incomplete or foreign"
        )
    ordered = {
        key: _dag_cid(artifacts[key], f"artifact_cids.{key}")
        for key in G241_EXTERNAL_ARTIFACT_KEYS
    }
    return cid_for_dag_json(
        {
            "schema": G241_EXTERNAL_ARTIFACT_SET_SCHEMA_V1,
            "ordered_artifact_cids": ordered,
        }
    )


def _canonical_base64(
    value: object,
    field_name: str,
    *,
    expected_bytes: int | None = None,
) -> bytes:
    if not isinstance(value, str) or not value:
        raise CustodianReleaseError(
            f"{field_name} must be canonical base64"
        )
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CustodianReleaseError(
            f"{field_name} must be canonical base64"
        ) from exc
    if (
        base64.b64encode(decoded).decode("ascii") != value
        or (
            expected_bytes is not None
            and len(decoded) != expected_bytes
        )
    ):
        raise CustodianReleaseError(
            f"{field_name} has a noncanonical or invalid length"
        )
    return decoded


def _g241_validator_key_id(
    *,
    validator_id: str,
    public_key_base64: str,
) -> str:
    return cid_for_dag_json(
        {
            "schema": G241_VALIDATOR_KEY_SCHEMA_V1,
            "algorithm": "ed25519",
            "validator_id": _actor(validator_id, "validator_id"),
            "public_key_base64": public_key_base64,
        }
    )


def _g241_validator_claim_cid(
    *,
    validator_id: str,
    source_identity_cid: str,
    run_plan_cid: str,
    parent_ledger_cid: str,
    artifact_set_cid: str,
) -> str:
    return cid_for_dag_json(
        {
            "schema": G241_VALIDATOR_CLAIM_SCHEMA_V1,
            "validator_id": _actor(validator_id, "validator_id"),
            "source_identity_cid": _dag_cid(
                source_identity_cid, "source_identity_cid"
            ),
            "run_plan_cid": _dag_cid(run_plan_cid, "run_plan_cid"),
            "parent_ledger_cid": _dag_cid(
                parent_ledger_cid, "parent_ledger_cid"
            ),
            "artifact_set_cid": _dag_cid(
                artifact_set_cid, "artifact_set_cid"
            ),
            "status": "verified",
        }
    )


def _validate_g241_validator_attestation(
    *,
    path: Path,
    trusted_attestation_cid: str,
    repo_root: Path,
    trust_root: "G241CustodianTrustRootV1",
    authority_cid: str,
    requirement_cid: str,
    operational_receipt_cid: str,
    validator_claim_cid: str,
    source_identity_cid: str,
    run_plan_cid: str,
    parent_ledger_cid: str,
    artifact_set_cid: str,
    observed_at: str,
) -> str:
    attestation = _external_file(
        path,
        repo_root=repo_root,
        field_name="G239 validator attestation",
    )
    _exact(
        attestation,
        {
            "schema",
            "signed_payload",
            "signed_payload_cid",
            "algorithm",
            "validator_key_id",
            "signature_base64",
            "attestation_cid",
        },
        "G239 validator attestation",
    )
    if (
        attestation.get("schema")
        != G241_VALIDATOR_ATTESTATION_SCHEMA_V1
        or attestation.get("algorithm") != "ed25519"
        or attestation.get("validator_key_id")
        != trust_root.validator_key_id
    ):
        raise CustodianReleaseError(
            "G239 validator attestation key or schema changed"
        )
    signed_payload = _mapping(
        attestation.get("signed_payload"),
        "G239 validator signed payload",
    )
    _exact(
        signed_payload,
        {
            "schema",
            "authority_cid",
            "requirement_cid",
            "operational_receipt_cid",
            "validator_id",
            "validator_receipt_cid",
            "source_identity_cid",
            "run_plan_cid",
            "parent_ledger_cid",
            "artifact_set_cid",
            "observed_at",
        },
        "G239 validator signed payload",
    )
    expected_payload = {
        "schema": G241_VALIDATOR_SIGNED_PAYLOAD_SCHEMA_V1,
        "authority_cid": authority_cid,
        "requirement_cid": requirement_cid,
        "operational_receipt_cid": operational_receipt_cid,
        "validator_id": trust_root.validator_id,
        "validator_receipt_cid": validator_claim_cid,
        "source_identity_cid": source_identity_cid,
        "run_plan_cid": run_plan_cid,
        "parent_ledger_cid": parent_ledger_cid,
        "artifact_set_cid": artifact_set_cid,
        "observed_at": observed_at,
    }
    if _plain(signed_payload) != expected_payload:
        raise CustodianReleaseError(
            "G239 validator attestation differs from the operational graph"
        )
    payload_cid = cid_for_dag_json(expected_payload)
    if attestation.get("signed_payload_cid") != payload_cid:
        raise CustodianReleaseError(
            "G239 validator signed-payload CID changed"
        )
    signature = _canonical_base64(
        attestation.get("signature_base64"),
        "G239 validator signature",
        expected_bytes=64,
    )
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError as exc:
        raise CustodianReleaseError(
            "G239 Ed25519 validator support is unavailable"
        ) from exc
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            trust_root.validator_public_key
        )
        public_key.verify(
            signature,
            canonical_dag_json_bytes(expected_payload),
        )
    except InvalidSignature as exc:
        raise CustodianReleaseError(
            "G239 validator signature is invalid"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise CustodianReleaseError(
            "G239 Ed25519 validator key is invalid"
        ) from exc
    body = {
        key: _plain(value)
        for key, value in attestation.items()
        if key != "attestation_cid"
    }
    attestation_cid = cid_for_dag_json(body)
    if (
        attestation.get("attestation_cid") != attestation_cid
        or _dag_cid(
            trusted_attestation_cid,
            "trusted G239 validator-attestation CID",
        )
        != attestation_cid
    ):
        raise CustodianReleaseError(
            "G239 validator attestation does not match its independent pin"
        )
    return attestation_cid


@dataclass(frozen=True, slots=True)
class G241G239ExternalProjectionV1:
    """Strict, path-free projection of one valid G239 governed receipt."""

    authority_cid: str
    requirement_cid: str
    operational_receipt_cid: str
    validator_claim_cid: str
    validator_attestation_cid: str
    validator_key_id: str
    source_identity_cid: str
    producer_id: str
    validator_id: str
    run_plan_cid: str
    parent_ledger_cid: str
    artifact_cids: Mapping[str, str]
    artifact_set_cid: str
    observed_at: str
    evaluated_at: str
    schema: str = G241_EXTERNAL_PROJECTION_SCHEMA_V1
    evaluation_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G241_EXTERNAL_PROJECTION_SCHEMA_V1:
            raise CustodianReleaseError(
                "unsupported G239 evaluation projection"
            )
        for name in (
            "authority_cid",
            "requirement_cid",
            "operational_receipt_cid",
            "validator_claim_cid",
            "validator_attestation_cid",
            "validator_key_id",
            "source_identity_cid",
            "producer_id",
            "validator_id",
            "run_plan_cid",
            "parent_ledger_cid",
            "artifact_set_cid",
        ):
            object.__setattr__(
                self, name, _dag_cid(getattr(self, name), name)
            )
        if self.producer_id == self.validator_id:
            raise CustodianReleaseError(
                "external producer and validator must be independent"
            )
        artifacts = _mapping(self.artifact_cids, "G239 artifact CIDs")
        if set(artifacts) != set(G241_EXTERNAL_ARTIFACT_KEYS):
            raise CustodianReleaseError(
                "G239 artifacts do not exactly cover the G241 source chain"
            )
        object.__setattr__(
            self,
            "artifact_cids",
            MappingProxyType(
                {
                    key: _dag_cid(artifacts[key], f"G239 artifact.{key}")
                    for key in G241_EXTERNAL_ARTIFACT_KEYS
                }
            ),
        )
        if self.artifact_set_cid != _g241_artifact_set_cid(
            self.artifact_cids
        ):
            raise CustodianReleaseError(
                "G239 external artifact-set CID changed"
            )
        _parse_time(self.observed_at, "observed_at")
        _parse_time(self.evaluated_at, "evaluated_at")
        expected = cid_for_dag_json(self.identity_payload())
        if self.evaluation_cid is None:
            object.__setattr__(self, "evaluation_cid", expected)
        elif (
            _dag_cid(self.evaluation_cid, "evaluation_cid") != expected
        ):
            raise CustodianReleaseError("G239 evaluation CID changed")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "authority_cid": self.authority_cid,
            "requirement_cid": self.requirement_cid,
            "operational_receipt_cid": self.operational_receipt_cid,
            "validator_claim_cid": self.validator_claim_cid,
            "validator_attestation_cid": (
                self.validator_attestation_cid
            ),
            "validator_key_id": self.validator_key_id,
            "source_identity_cid": self.source_identity_cid,
            "producer_id": self.producer_id,
            "validator_id": self.validator_id,
            "run_plan_cid": self.run_plan_cid,
            "parent_ledger_cid": self.parent_ledger_cid,
            "artifact_cids": dict(self.artifact_cids),
            "artifact_set_cid": self.artifact_set_cid,
            "observed_at": self.observed_at,
            "evaluated_at": self.evaluated_at,
            "valid": True,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "evaluation_cid": self.evaluation_cid,
        }


def _evaluate_g239_for_g241_v1(
    *,
    authority_path: Path,
    trusted_authority_cid: str,
    validator_attestation_path: Path,
    trusted_validator_attestation_cid: str,
    custodian_trust_root: "G241CustodianTrustRootV1",
    source_replay: object,
    repo_root: Path,
    evaluated_at: datetime,
    freshness_reference_at: datetime,
    freshness_seconds: float = 86_400.0,
    clock_skew_seconds: float = 300.0,
) -> G241G239ExternalProjectionV1:
    """Strictly re-evaluate one externally pinned G239 authority.

    This is the explicit adapter/trust-root boundary.  It mirrors the nested
    supervisor schema locally because importing the nested package executes
    application bootstrap code.  The authority file must be outside the
    source tree and its complete CID must be pinned independently.
    """

    if not isinstance(
        source_replay,
        (G241SourceReplayResultV1, _G241DurableReplayView),
    ):
        raise CustodianReleaseError(
            "G239 evaluation requires complete G241 source replay"
        )
    if not isinstance(
        custodian_trust_root, G241CustodianTrustRootV1
    ):
        raise CustodianReleaseError(
            "G239 evaluation requires a typed custodian trust root"
        )
    authority = _external_file(
        authority_path,
        repo_root=repo_root,
        field_name="G239 authority",
    )
    _exact(
        authority,
        {"schema", "requirements", "receipts", "authority_cid"},
        "G239 authority",
    )
    if authority.get("schema") != G239_EXTERNAL_AUTHORITY_SCHEMA:
        raise CustodianReleaseError("unsupported G239 authority schema")
    authority_body = {
        "schema": G239_EXTERNAL_AUTHORITY_SCHEMA,
        "requirements": _plain(authority.get("requirements")),
        "receipts": _plain(authority.get("receipts")),
    }
    authority_cid = cid_for_dag_json(authority_body)
    if (
        authority.get("authority_cid") != authority_cid
        or _dag_cid(
            trusted_authority_cid, "trusted G239 authority CID"
        )
        != authority_cid
        or custodian_trust_root.g239_authority_cid != authority_cid
    ):
        raise CustodianReleaseError(
            "G239 authority does not match the independently pinned trust root"
        )
    requirements = tuple(
        _mapping(item, "G239 requirement")
        for item in _array(
            authority.get("requirements"), "G239 requirements"
        )
    )
    receipts = tuple(
        _mapping(item, "G239 receipt")
        for item in _array(authority.get("receipts"), "G239 receipts")
    )
    if len(requirements) != 1 or len(receipts) != 1:
        raise CustodianReleaseError(
            "G241 requires a dedicated G239 authority containing exactly "
            "one G232 requirement and one operational receipt"
        )
    selected_requirements = tuple(
        item
        for item in requirements
        if (
            item.get("goal_id") == G241_GOVERNED_GOAL_ID
            and item.get("evidence_term")
            == G241_GOVERNED_EVIDENCE_TERM
        )
    )
    selected_receipts = tuple(
        item
        for item in receipts
        if (
            item.get("goal_id") == G241_GOVERNED_GOAL_ID
            and item.get("evidence_term")
            == G241_GOVERNED_EVIDENCE_TERM
        )
    )
    if len(selected_requirements) != 1 or len(selected_receipts) != 1:
        raise CustodianReleaseError(
            "G239 requires exactly one current G232 requirement and receipt"
        )
    requirement = selected_requirements[0]
    receipt = selected_receipts[0]
    _exact(
        requirement,
        {
            "schema",
            "goal_id",
            "evidence_term",
            "source_identity_cid",
            "run_plan_cid",
            "parent_ledger_cid",
            "required_artifact_ids",
            "expected_producer_id",
            "expected_validator_id",
            "requirement_cid",
        },
        "G239 requirement",
    )
    if requirement.get("schema") != G239_EXTERNAL_REQUIREMENT_SCHEMA:
        raise CustodianReleaseError("unsupported G239 requirement schema")
    required_ids = tuple(
        _dag_cid(item, "required artifact ID")
        for item in _array(
            requirement.get("required_artifact_ids"),
            "required artifact IDs",
        )
    )
    expected_artifacts = dict(source_replay.external_artifact_cids)
    expected_ids = tuple(
        sorted(g241_artifact_slot_cid(key) for key in expected_artifacts)
    )
    if (
        required_ids != tuple(sorted(required_ids))
        or required_ids != expected_ids
        or len(required_ids) != len(set(required_ids))
    ):
        raise CustodianReleaseError(
            "G239 requirement does not exactly name every source artifact"
        )
    requirement_body = {
        key: _plain(value)
        for key, value in requirement.items()
        if key != "requirement_cid"
    }
    requirement_cid = cid_for_dag_json(requirement_body)
    if requirement.get("requirement_cid") != requirement_cid:
        raise CustodianReleaseError("G239 requirement CID changed")

    _exact(
        receipt,
        {
            "schema",
            "goal_id",
            "evidence_term",
            "source",
            "run_plan_cid",
            "parent_ledger_cid",
            "artifacts",
            "producer_id",
            "validator_id",
            "validator_receipt_cid",
            "observed_at",
            "fresh_until",
            "status",
            "receipt_cid",
        },
        "G239 operational receipt",
    )
    if (
        receipt.get("schema") != G239_EXTERNAL_RECEIPT_SCHEMA
        or receipt.get("status") != "completed"
    ):
        raise CustodianReleaseError(
            "G239 operational receipt is not completed"
        )
    receipt_source = _validate_g239_source(receipt.get("source"))
    receipt_artifacts = tuple(
        _mapping(item, "G239 artifact")
        for item in _array(receipt.get("artifacts"), "G239 artifacts")
    )
    artifact_by_id: dict[str, str] = {}
    artifact_id_order: list[str] = []
    for artifact in receipt_artifacts:
        _exact(
            artifact,
            {"schema", "artifact_id", "artifact_cid"},
            "G239 artifact",
        )
        if artifact.get("schema") != G239_EXTERNAL_ARTIFACT_SCHEMA:
            raise CustodianReleaseError(
                "unsupported G239 artifact schema"
            )
        artifact_id = _dag_cid(
            artifact.get("artifact_id"), "G239 artifact ID"
        )
        artifact_cid = _dag_cid(
            artifact.get("artifact_cid"), "G239 artifact CID"
        )
        if artifact_id in artifact_by_id:
            raise CustodianReleaseError("G239 artifacts are duplicated")
        artifact_by_id[artifact_id] = artifact_cid
        artifact_id_order.append(artifact_id)
    expected_by_id = {
        g241_artifact_slot_cid(key): value
        for key, value in expected_artifacts.items()
    }
    if (
        tuple(artifact_id_order) != tuple(sorted(expected_by_id))
        or artifact_by_id != expected_by_id
    ):
        raise CustodianReleaseError(
            "G239 artifact CIDs differ from the source-recomputed chain"
        )
    if len(set(artifact_by_id.values())) != len(artifact_by_id):
        raise CustodianReleaseError(
            "G239 external artifact content identities are duplicated"
        )
    receipt_body = {
        key: _plain(value)
        for key, value in receipt.items()
        if key != "receipt_cid"
    }
    operational_receipt_cid = cid_for_dag_json(receipt_body)
    if receipt.get("receipt_cid") != operational_receipt_cid:
        raise CustodianReleaseError("G239 operational receipt CID changed")

    producer = _actor(receipt.get("producer_id"), "G239 producer")
    validator = _actor(receipt.get("validator_id"), "G239 validator")
    validator_receipt = _dag_cid(
        receipt.get("validator_receipt_cid"),
        "G239 validator receipt",
    )
    source_identity_cid = _dag_cid(
        receipt_source.get("source_identity_cid"),
        "G239 source identity",
    )
    if (
        requirement.get("source_identity_cid") != source_identity_cid
        or requirement.get("run_plan_cid")
        != source_replay.source_index.run_plan_cid
        or receipt.get("run_plan_cid")
        != source_replay.source_index.run_plan_cid
        or requirement.get("parent_ledger_cid")
        != source_replay.parent_ledger_cid
        or receipt.get("parent_ledger_cid")
        != source_replay.parent_ledger_cid
        or requirement.get("expected_producer_id") != producer
        or requirement.get("expected_validator_id") != validator
        or receipt.get("goal_id") != requirement.get("goal_id")
        or receipt.get("evidence_term") != requirement.get("evidence_term")
        or producer == validator
    ):
        raise CustodianReleaseError(
            "G239 requirement, receipt, source chain, or authorities differ"
        )
    artifact_set_cid = _g241_artifact_set_cid(expected_artifacts)
    validator_claim_cid = _g241_validator_claim_cid(
        validator_id=validator,
        source_identity_cid=source_identity_cid,
        run_plan_cid=source_replay.source_index.run_plan_cid,
        parent_ledger_cid=source_replay.parent_ledger_cid,
        artifact_set_cid=artifact_set_cid,
    )
    if (
        validator != custodian_trust_root.validator_id
        or validator_receipt != validator_claim_cid
    ):
        raise CustodianReleaseError(
            "G239 validator receipt is not the separately trusted claim"
        )

    current = _inspect_current_source(
        Path(repo_root),
        git_executable_path=Path(
            custodian_trust_root.git_executable_path
        ),
        expected_git_executable_cid=(
            custodian_trust_root.git_executable_cid
        ),
    )
    source_index = source_replay.source_index
    if (
        current.outer_commit != source_index.source_commit
        or source_index.source_commit_cid
        != g238_git_commit_cid(current.outer_commit)
        or source_index.source_tree_cid
        != g241_git_tree_cid(current.outer_tree)
        or source_index.recursive_gitlinks_cid
        != current.g240_recursive_gitlinks_cid
        or receipt_source.get("outer_commit") != current.outer_commit
        or receipt_source.get("outer_tree") != current.outer_tree
        or receipt_source.get("submodule_map_cid")
        != current.submodule_map_cid
        or source_identity_cid != current.source_identity_cid
    ):
        raise CustodianReleaseError(
            "G202/G239 source commit, tree, or recursive Gitlinks are stale "
            "or rebased"
        )

    if (
        evaluated_at.tzinfo is None
        or freshness_reference_at.tzinfo is None
    ):
        raise CustodianReleaseError(
            "G239 trusted clock values must include a timezone"
        )
    evaluated_at = evaluated_at.astimezone(timezone.utc)
    freshness_reference_at = freshness_reference_at.astimezone(
        timezone.utc
    )
    observed_at = _parse_time(receipt.get("observed_at"), "observed_at")
    fresh_until_value = receipt.get("fresh_until")
    if fresh_until_value in {None, ""}:
        fresh_until = None
    else:
        fresh_until = _parse_time(fresh_until_value, "fresh_until")
    if (
        receipt.get("observed_at") != observed_at.isoformat()
        or (
            fresh_until is not None
            and receipt.get("fresh_until") != fresh_until.isoformat()
        )
    ):
        raise CustodianReleaseError(
            "G239 receipt timestamps are not canonically normalized"
        )
    max_age = timedelta(seconds=max(0.0, freshness_seconds))
    skew = timedelta(seconds=max(0.0, clock_skew_seconds))
    if (
        observed_at > freshness_reference_at + skew
        or freshness_reference_at - observed_at > max_age
        or (
            fresh_until is not None
            and (
                fresh_until < observed_at
                or freshness_reference_at > fresh_until
            )
        )
    ):
        raise CustodianReleaseError("G239 operational receipt is stale")
    timestamp = evaluated_at.isoformat()
    attestation_cid = _validate_g241_validator_attestation(
        path=validator_attestation_path,
        trusted_attestation_cid=trusted_validator_attestation_cid,
        repo_root=Path(repo_root),
        trust_root=custodian_trust_root,
        authority_cid=authority_cid,
        requirement_cid=requirement_cid,
        operational_receipt_cid=operational_receipt_cid,
        validator_claim_cid=validator_claim_cid,
        source_identity_cid=source_identity_cid,
        run_plan_cid=source_replay.source_index.run_plan_cid,
        parent_ledger_cid=source_replay.parent_ledger_cid,
        artifact_set_cid=artifact_set_cid,
        observed_at=observed_at.isoformat(),
    )
    return G241G239ExternalProjectionV1(
        authority_cid=authority_cid,
        requirement_cid=requirement_cid,
        operational_receipt_cid=operational_receipt_cid,
        validator_claim_cid=validator_claim_cid,
        validator_attestation_cid=attestation_cid,
        validator_key_id=custodian_trust_root.validator_key_id,
        source_identity_cid=source_identity_cid,
        producer_id=producer,
        validator_id=validator,
        run_plan_cid=source_index.run_plan_cid,
        parent_ledger_cid=source_replay.parent_ledger_cid,
        artifact_cids=expected_artifacts,
        artifact_set_cid=artifact_set_cid,
        observed_at=observed_at.isoformat(),
        evaluated_at=timestamp,
    )


@dataclass(frozen=True, slots=True)
class G241CustodianTrustRootV1:
    """Externally pinned custody and executor identities."""

    g239_authority_cid: str
    git_executable_path: str
    git_executable_cid: str
    monotonic_store_id: str
    monotonic_store_policy_cid: str
    release_ledger_authority_cid: str
    validator_id: str
    validator_key_id: str
    validator_public_key_base64: str
    custodian_id: str
    executor_id: str
    ledger_genesis_cid: str
    schema: str = G241_CUSTODIAN_TRUST_ROOT_SCHEMA_V1
    trust_root_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G241_CUSTODIAN_TRUST_ROOT_SCHEMA_V1:
            raise CustodianReleaseError(
                "unsupported G241 custodian trust root"
            )
        for name in (
            "g239_authority_cid",
            "git_executable_cid",
            "monotonic_store_id",
            "monotonic_store_policy_cid",
            "release_ledger_authority_cid",
            "validator_id",
            "validator_key_id",
            "custodian_id",
            "executor_id",
            "ledger_genesis_cid",
        ):
            object.__setattr__(
                self, name, _dag_cid(getattr(self, name), name)
            )
        public_key = _canonical_base64(
            self.validator_public_key_base64,
            "validator_public_key_base64",
            expected_bytes=32,
        )
        git_path = _canonical_absolute_path(
            Path(self.git_executable_path),
            "git_executable_path",
        )
        object.__setattr__(self, "git_executable_path", str(git_path))
        if self.git_executable_cid != g241_git_executable_cid_v1(
            git_path
        ):
            raise CustodianReleaseError(
                "custodian trust root does not pin the validated system Git "
                "executable"
            )
        if self.validator_key_id != _g241_validator_key_id(
            validator_id=self.validator_id,
            public_key_base64=self.validator_public_key_base64,
        ):
            raise CustodianReleaseError(
                "validator key ID does not bind the trusted Ed25519 key"
            )
        if len(
            {
                self.monotonic_store_id,
                self.validator_id,
                self.custodian_id,
                self.executor_id,
            }
        ) != 4:
            raise CustodianReleaseError(
                "monotonic store, validator, custodian, and holdout executor "
                "must differ"
            )
        if not public_key:
            raise CustodianReleaseError(
                "validator public key must not be empty"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.trust_root_cid is None:
            object.__setattr__(self, "trust_root_cid", expected)
        elif (
            _dag_cid(self.trust_root_cid, "trust_root_cid")
            != expected
        ):
            raise CustodianReleaseError("custodian trust-root CID changed")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "g239_authority_cid": self.g239_authority_cid,
            "git_executable_path": self.git_executable_path,
            "git_executable_cid": self.git_executable_cid,
            "monotonic_store_id": self.monotonic_store_id,
            "monotonic_store_policy_cid": (
                self.monotonic_store_policy_cid
            ),
            "release_ledger_authority_cid": (
                self.release_ledger_authority_cid
            ),
            "validator_id": self.validator_id,
            "validator_key_id": self.validator_key_id,
            "validator_public_key_base64": (
                self.validator_public_key_base64
            ),
            "custodian_id": self.custodian_id,
            "executor_id": self.executor_id,
            "ledger_genesis_cid": self.ledger_genesis_cid,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "trust_root_cid": self.trust_root_cid,
        }

    @property
    def validator_public_key(self) -> bytes:
        return _canonical_base64(
            self.validator_public_key_base64,
            "validator_public_key_base64",
            expected_bytes=32,
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "custodian trust root")
        _exact(data, set(cls.__dataclass_fields__), "custodian trust root")
        return cls(**data)  # type: ignore[arg-type]


def load_g241_custodian_trust_root_v1(
    *,
    path: Path,
    trusted_trust_root_cid: str,
    repo_root: Path,
) -> G241CustodianTrustRootV1:
    """Load an externally stored trust root against an out-of-band pin."""

    root = G241CustodianTrustRootV1.from_dict(
        _external_file(
            path,
            repo_root=repo_root,
            field_name="custodian trust root",
        )
    )
    if root.trust_root_cid != _dag_cid(
        trusted_trust_root_cid, "trusted custodian trust-root CID"
    ):
        raise CustodianReleaseError(
            "custodian trust root does not match its out-of-band pin"
        )
    return root


def _validate_release_ledger_authority(
    trust_root: G241CustodianTrustRootV1,
    ledger_path: Path,
) -> None:
    expected = g241_release_ledger_authority_cid_v1(
        ledger_path=Path(ledger_path),
        ledger_genesis_cid=trust_root.ledger_genesis_cid,
        monotonic_store_id=trust_root.monotonic_store_id,
        monotonic_store_policy_cid=(
            trust_root.monotonic_store_policy_cid
        ),
    )
    if trust_root.release_ledger_authority_cid != expected:
        raise CustodianReleaseError(
            "custodian release ledger does not match the externally pinned "
            "monotonic-store authority"
        )


def evaluate_g239_for_g241_v1(
    *,
    authority_path: Path,
    trusted_authority_cid: str,
    validator_attestation_path: Path,
    trusted_validator_attestation_cid: str,
    custodian_trust_root: G241CustodianTrustRootV1,
    source_replay: G241SourceReplayResultV1,
    repo_root: Path,
    freshness_seconds: float = 86_400.0,
    clock_skew_seconds: float = 300.0,
) -> G241G239ExternalProjectionV1:
    """Validate G239 against the system clock and an independent signature."""

    if not isinstance(source_replay, G241SourceReplayResultV1):
        raise CustodianReleaseError(
            "public G239 evaluation requires source-recomputed G241 evidence"
        )
    trusted_now = datetime.now(timezone.utc)
    return _evaluate_g239_for_g241_v1(
        authority_path=authority_path,
        trusted_authority_cid=trusted_authority_cid,
        validator_attestation_path=validator_attestation_path,
        trusted_validator_attestation_cid=(
            trusted_validator_attestation_cid
        ),
        custodian_trust_root=custodian_trust_root,
        source_replay=source_replay,
        repo_root=repo_root,
        evaluated_at=trusted_now,
        freshness_reference_at=trusted_now,
        freshness_seconds=freshness_seconds,
        clock_skew_seconds=clock_skew_seconds,
    )


@dataclass(frozen=True, slots=True)
class G241CustodianReleaseRequestV1:
    """Path-free request; this object does not authorize holdout access."""

    source_index_cid: str
    source_commit: str
    source_tree_cid: str
    recursive_gitlinks_cid: str
    source_identity_cid: str
    run_plan_cid: str
    parent_ledger_cid: str
    artifact_cids: Mapping[str, str]
    artifact_set_cid: str
    upstream_authority_cids: Mapping[str, str]
    g232_authorization_cid: str
    seal_contract_cid: str
    sealed_manifest_cid: str
    authorized_variant_ids: tuple[str, ...]
    g239_evaluation_cid: str
    g239_authority_cid: str
    g239_operational_receipt_cid: str
    g239_validator_claim_cid: str
    g239_validator_attestation_cid: str
    g239_validator_key_id: str
    g239_observed_at: str
    g239_evaluated_at: str
    decision_producer_id: str
    external_validator_id: str
    custodian_id: str
    executor_id: str
    trust_root_cid: str
    access_ledger_authority_cid: str
    access_ledger_file_identity_cid: str
    access_ledger_head_cid: str
    access_ledger_event_count: int
    release_ledger_file_identity_cid: str
    ledger_sequence: int
    previous_ledger_receipt_cid: str
    schema: str = G241_RELEASE_REQUEST_SCHEMA_V1
    request_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G241_RELEASE_REQUEST_SCHEMA_V1:
            raise CustodianReleaseError(
                "unsupported G241 release request"
            )
        for name in (
            "source_index_cid",
            "source_tree_cid",
            "recursive_gitlinks_cid",
            "source_identity_cid",
            "run_plan_cid",
            "parent_ledger_cid",
            "artifact_set_cid",
            "g232_authorization_cid",
            "seal_contract_cid",
            "sealed_manifest_cid",
            "g239_evaluation_cid",
            "g239_authority_cid",
            "g239_operational_receipt_cid",
            "g239_validator_claim_cid",
            "g239_validator_attestation_cid",
            "g239_validator_key_id",
            "decision_producer_id",
            "external_validator_id",
            "custodian_id",
            "executor_id",
            "trust_root_cid",
            "access_ledger_authority_cid",
            "access_ledger_file_identity_cid",
            "access_ledger_head_cid",
            "release_ledger_file_identity_cid",
            "previous_ledger_receipt_cid",
        ):
            object.__setattr__(
                self, name, _cid(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "source_commit",
            _git_object(self.source_commit, "source_commit"),
        )
        artifacts = _mapping(self.artifact_cids, "artifact_cids")
        if set(artifacts) != set(G241_EXTERNAL_ARTIFACT_KEYS):
            raise CustodianReleaseError(
                "release request artifact graph is incomplete or foreign"
            )
        normalized_artifacts = {
            key: _dag_cid(artifacts[key], f"artifact_cids.{key}")
            for key in G241_EXTERNAL_ARTIFACT_KEYS
        }
        object.__setattr__(
            self,
            "artifact_cids",
            MappingProxyType(normalized_artifacts),
        )
        if self.artifact_set_cid != _g241_artifact_set_cid(
            normalized_artifacts
        ):
            raise CustodianReleaseError(
                "release request artifact-set CID changed"
            )
        authorities = _mapping(
            self.upstream_authority_cids,
            "upstream_authority_cids",
        )
        if set(authorities) != set(G241_UPSTREAM_AUTHORITY_ROLES):
            raise CustodianReleaseError(
                "release request upstream authority graph is incomplete"
            )
        normalized_authorities = {
            role: _actor(
                authorities[role],
                f"upstream_authority_cids.{role}",
            )
            for role in G241_UPSTREAM_AUTHORITY_ROLES
        }
        if len(set(normalized_authorities.values())) != len(
            normalized_authorities
        ):
            raise CustodianReleaseError(
                "release request upstream authorities overlap"
            )
        object.__setattr__(
            self,
            "upstream_authority_cids",
            MappingProxyType(normalized_authorities),
        )
        actors = {
            self.decision_producer_id,
            self.external_validator_id,
            self.custodian_id,
            self.executor_id,
        }
        if len(actors) != 4:
            raise CustodianReleaseError(
                "decision producer, external validator, custodian, and "
                "executor must be pairwise distinct"
            )
        if actors & set(normalized_authorities.values()):
            raise CustodianReleaseError(
                "G241 producer, validator, custodian, or executor overlaps "
                "an upstream authority"
            )
        variants = tuple(self.authorized_variant_ids)
        if (
            len(variants) < 2
            or len(variants) > 5
            or variants[0] != "A0"
            or tuple(variants[1:]) != tuple(
                candidate
                for candidate in G231_EVALUATED_CANDIDATE_IDS
                if candidate in set(variants[1:])
            )
            or len(variants) != len(set(variants))
        ):
            raise CustodianReleaseError(
                "release variants must be A0 plus one to four ordered "
                "frozen candidates"
            )
        object.__setattr__(self, "authorized_variant_ids", variants)
        if (
            type(self.access_ledger_event_count) is not int
            or self.access_ledger_event_count != 0
        ):
            raise CustodianReleaseError(
                "any pre-release access-ledger event invalidates G241"
            )
        expected_access_head = cid_for_dag_json(
            {
                "schema": G241_ACCESS_LEDGER_SNAPSHOT_SCHEMA_V1,
                "seal_contract_cid": self.seal_contract_cid,
                "sealed_manifest_cid": self.sealed_manifest_cid,
                "access_ledger_authority_cid": (
                    self.access_ledger_authority_cid
                ),
                "event_count": 0,
                "last_receipt_cid": None,
                "ledger_file_identity_cid": (
                    self.access_ledger_file_identity_cid
                ),
            }
        )
        if self.access_ledger_head_cid != expected_access_head:
            raise CustodianReleaseError(
                "pre-release access-ledger head changed"
            )
        if type(self.ledger_sequence) is not int or self.ledger_sequence < 0:
            raise CustodianReleaseError(
                "ledger sequence must be a nonnegative integer"
            )
        observed = _parse_time(self.g239_observed_at, "g239_observed_at")
        evaluated = _parse_time(
            self.g239_evaluated_at, "g239_evaluated_at"
        )
        if (
            self.g239_observed_at != observed.isoformat()
            or self.g239_evaluated_at != evaluated.isoformat()
            or evaluated < observed
        ):
            raise CustodianReleaseError(
                "G239 request timestamps are noncanonical or reversed"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.request_cid is None:
            object.__setattr__(self, "request_cid", expected)
        elif _cid(self.request_cid, "request_cid") != expected:
            raise CustodianReleaseError("release-request CID changed")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "source_index_cid": self.source_index_cid,
            "source_commit": self.source_commit,
            "source_tree_cid": self.source_tree_cid,
            "recursive_gitlinks_cid": self.recursive_gitlinks_cid,
            "source_identity_cid": self.source_identity_cid,
            "run_plan_cid": self.run_plan_cid,
            "parent_ledger_cid": self.parent_ledger_cid,
            "artifact_cids": dict(self.artifact_cids),
            "artifact_set_cid": self.artifact_set_cid,
            "upstream_authority_cids": dict(
                self.upstream_authority_cids
            ),
            "g232_authorization_cid": self.g232_authorization_cid,
            "seal_contract_cid": self.seal_contract_cid,
            "sealed_manifest_cid": self.sealed_manifest_cid,
            "authorized_variant_ids": list(self.authorized_variant_ids),
            "g239_evaluation_cid": self.g239_evaluation_cid,
            "g239_authority_cid": self.g239_authority_cid,
            "g239_operational_receipt_cid": (
                self.g239_operational_receipt_cid
            ),
            "g239_validator_claim_cid": (
                self.g239_validator_claim_cid
            ),
            "g239_validator_attestation_cid": (
                self.g239_validator_attestation_cid
            ),
            "g239_validator_key_id": self.g239_validator_key_id,
            "g239_observed_at": self.g239_observed_at,
            "g239_evaluated_at": self.g239_evaluated_at,
            "decision_producer_id": self.decision_producer_id,
            "external_validator_id": self.external_validator_id,
            "custodian_id": self.custodian_id,
            "executor_id": self.executor_id,
            "trust_root_cid": self.trust_root_cid,
            "access_ledger_authority_cid": (
                self.access_ledger_authority_cid
            ),
            "access_ledger_file_identity_cid": (
                self.access_ledger_file_identity_cid
            ),
            "access_ledger_head_cid": self.access_ledger_head_cid,
            "access_ledger_event_count": self.access_ledger_event_count,
            "release_ledger_file_identity_cid": (
                self.release_ledger_file_identity_cid
            ),
            "ledger_sequence": self.ledger_sequence,
            "previous_ledger_receipt_cid": (
                self.previous_ledger_receipt_cid
            ),
            "holdout_content_included": False,
            "release_authorized": False,
            "production_promotion_authorized": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "request_cid": self.request_cid}


@dataclass(frozen=True, slots=True)
class G241ExternallyGovernedCustodianReleaseReceiptV1:
    """Parsed receipt content; authority requires durable-ledger validation."""

    request_cid: str
    source_index_cid: str
    source_commit: str
    source_tree_cid: str
    recursive_gitlinks_cid: str
    source_identity_cid: str
    run_plan_cid: str
    parent_ledger_cid: str
    artifact_cids: Mapping[str, str]
    artifact_set_cid: str
    upstream_authority_cids: Mapping[str, str]
    g232_authorization_cid: str
    seal_contract_cid: str
    sealed_manifest_cid: str
    authorized_variant_ids: tuple[str, ...]
    g239_evaluation_cid: str
    g239_authority_cid: str
    g239_operational_receipt_cid: str
    g239_validator_claim_cid: str
    g239_validator_attestation_cid: str
    g239_validator_key_id: str
    g239_observed_at: str
    g239_evaluated_at: str
    decision_producer_id: str
    external_validator_id: str
    custodian_id: str
    executor_id: str
    trust_root_cid: str
    access_ledger_authority_cid: str
    access_ledger_file_identity_cid: str
    access_ledger_head_cid: str
    access_ledger_event_count: int
    release_ledger_file_identity_cid: str
    sequence: int
    previous_receipt_cid: str
    recorded_at: str
    schema: str = G241_RELEASE_RECEIPT_SCHEMA_V1
    receipt_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G241_RELEASE_RECEIPT_SCHEMA_V1:
            raise CustodianReleaseError(
                "unsupported G241 release receipt schema"
            )
        request = self.as_request()
        if request.request_cid != _dag_cid(
            self.request_cid, "request_cid"
        ):
            raise CustodianReleaseError(
                "release receipt request CID changed"
            )
        timestamp = _parse_time(self.recorded_at, "recorded_at")
        if (
            self.recorded_at != timestamp.isoformat()
            or timestamp
            < _parse_time(
                self.g239_evaluated_at, "g239_evaluated_at"
            )
        ):
            raise CustodianReleaseError(
                "release receipt timestamp is noncanonical or predates "
                "G239 evaluation"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.receipt_cid is None:
            object.__setattr__(self, "receipt_cid", expected)
        elif _dag_cid(self.receipt_cid, "receipt_cid") != expected:
            raise CustodianReleaseError(
                "custodian release-receipt CID changed"
            )

    @classmethod
    def _from_request(
        cls,
        *,
        request: G241CustodianReleaseRequestV1,
        recorded_at: datetime,
    ) -> Self:
        if recorded_at.tzinfo is None:
            raise CustodianReleaseError(
                "release receipt clock must include a timezone"
            )
        values = {
            name: getattr(request, name)
            for name in (
                "source_index_cid",
                "source_commit",
                "source_tree_cid",
                "recursive_gitlinks_cid",
                "source_identity_cid",
                "run_plan_cid",
                "parent_ledger_cid",
                "artifact_cids",
                "artifact_set_cid",
                "upstream_authority_cids",
                "g232_authorization_cid",
                "seal_contract_cid",
                "sealed_manifest_cid",
                "authorized_variant_ids",
                "g239_evaluation_cid",
                "g239_authority_cid",
                "g239_operational_receipt_cid",
                "g239_validator_claim_cid",
                "g239_validator_attestation_cid",
                "g239_validator_key_id",
                "g239_observed_at",
                "g239_evaluated_at",
                "decision_producer_id",
                "external_validator_id",
                "custodian_id",
                "executor_id",
                "trust_root_cid",
                "access_ledger_authority_cid",
                "access_ledger_file_identity_cid",
                "access_ledger_head_cid",
                "access_ledger_event_count",
                "release_ledger_file_identity_cid",
            )
        }
        return cls(
            request_cid=str(request.request_cid),
            **values,  # type: ignore[arg-type]
            sequence=request.ledger_sequence,
            previous_receipt_cid=(
                request.previous_ledger_receipt_cid
            ),
            recorded_at=recorded_at.astimezone(timezone.utc).isoformat(),
        )

    def as_request(self) -> G241CustodianReleaseRequestV1:
        values = {
            name: getattr(self, name)
            for name in (
                "source_index_cid",
                "source_commit",
                "source_tree_cid",
                "recursive_gitlinks_cid",
                "source_identity_cid",
                "run_plan_cid",
                "parent_ledger_cid",
                "artifact_cids",
                "artifact_set_cid",
                "upstream_authority_cids",
                "g232_authorization_cid",
                "seal_contract_cid",
                "sealed_manifest_cid",
                "authorized_variant_ids",
                "g239_evaluation_cid",
                "g239_authority_cid",
                "g239_operational_receipt_cid",
                "g239_validator_claim_cid",
                "g239_validator_attestation_cid",
                "g239_validator_key_id",
                "g239_observed_at",
                "g239_evaluated_at",
                "decision_producer_id",
                "external_validator_id",
                "custodian_id",
                "executor_id",
                "trust_root_cid",
                "access_ledger_authority_cid",
                "access_ledger_file_identity_cid",
                "access_ledger_head_cid",
                "access_ledger_event_count",
                "release_ledger_file_identity_cid",
            )
        }
        return G241CustodianReleaseRequestV1(
            **values,  # type: ignore[arg-type]
            ledger_sequence=self.sequence,
            previous_ledger_receipt_cid=self.previous_receipt_cid,
            request_cid=self.request_cid,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "goal_id": "HSSL-G241",
            "request_cid": self.request_cid,
            "source_index_cid": self.source_index_cid,
            "source_commit": self.source_commit,
            "source_tree_cid": self.source_tree_cid,
            "recursive_gitlinks_cid": self.recursive_gitlinks_cid,
            "source_identity_cid": self.source_identity_cid,
            "run_plan_cid": self.run_plan_cid,
            "parent_ledger_cid": self.parent_ledger_cid,
            "artifact_cids": dict(self.artifact_cids),
            "artifact_set_cid": self.artifact_set_cid,
            "upstream_authority_cids": dict(
                self.upstream_authority_cids
            ),
            "g232_authorization_cid": self.g232_authorization_cid,
            "seal_contract_cid": self.seal_contract_cid,
            "sealed_manifest_cid": self.sealed_manifest_cid,
            "authorized_variant_ids": list(self.authorized_variant_ids),
            "g239_evaluation_cid": self.g239_evaluation_cid,
            "g239_authority_cid": self.g239_authority_cid,
            "g239_operational_receipt_cid": (
                self.g239_operational_receipt_cid
            ),
            "g239_validator_claim_cid": (
                self.g239_validator_claim_cid
            ),
            "g239_validator_attestation_cid": (
                self.g239_validator_attestation_cid
            ),
            "g239_validator_key_id": self.g239_validator_key_id,
            "g239_observed_at": self.g239_observed_at,
            "g239_evaluated_at": self.g239_evaluated_at,
            "decision_producer_id": self.decision_producer_id,
            "external_validator_id": self.external_validator_id,
            "custodian_id": self.custodian_id,
            "executor_id": self.executor_id,
            "trust_root_cid": self.trust_root_cid,
            "access_ledger_authority_cid": (
                self.access_ledger_authority_cid
            ),
            "access_ledger_file_identity_cid": (
                self.access_ledger_file_identity_cid
            ),
            "access_ledger_head_cid": self.access_ledger_head_cid,
            "access_ledger_event_count": self.access_ledger_event_count,
            "release_ledger_file_identity_cid": (
                self.release_ledger_file_identity_cid
            ),
            "sequence": self.sequence,
            "previous_receipt_cid": self.previous_receipt_cid,
            "recorded_at": self.recorded_at,
            "holdout_content_included": False,
            "release_authorized": True,
            "production_promotion_authorized": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_cid": self.receipt_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = dict(_mapping(value, "G241 release receipt"))
        expected = set(cls.__dataclass_fields__) | {
            "goal_id",
            "holdout_content_included",
            "release_authorized",
            "production_promotion_authorized",
        }
        _exact(data, expected, "G241 release receipt")
        if (
            data.pop("goal_id") != "HSSL-G241"
            or data.pop("holdout_content_included") is not False
            or data.pop("release_authorized") is not True
            or data.pop("production_promotion_authorized") is not False
        ):
            raise CustodianReleaseError(
                "G241 release receipt state changed"
            )
        variants = _array(
            data.get("authorized_variant_ids"),
            "authorized_variant_ids",
        )
        data["authorized_variant_ids"] = tuple(variants)
        data["artifact_cids"] = _mapping(
            data.get("artifact_cids"), "artifact_cids"
        )
        data["upstream_authority_cids"] = _mapping(
            data.get("upstream_authority_cids"),
            "upstream_authority_cids",
        )
        return cls(**data)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class G241ReleaseConsumptionTombstoneV1:
    """Durable release-ledger head proving one G241 receipt was spent."""

    release_receipt_cid: str
    access_grant_receipt_cid: str
    access_ledger_file_identity_cid: str
    release_ledger_file_identity_cid: str
    purpose: str
    executor_id: str
    custodian_id: str
    trust_root_cid: str
    monotonic_store_id: str
    monotonic_store_policy_cid: str
    release_ledger_authority_cid: str
    sequence: int
    previous_receipt_cid: str
    recorded_at: str
    schema: str = G241_RELEASE_CONSUMPTION_TOMBSTONE_SCHEMA_V1
    tombstone_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G241_RELEASE_CONSUMPTION_TOMBSTONE_SCHEMA_V1:
            raise CustodianReleaseError(
                "unsupported G241 release-consumption tombstone"
            )
        for name in (
            "release_receipt_cid",
            "access_grant_receipt_cid",
            "access_ledger_file_identity_cid",
            "release_ledger_file_identity_cid",
            "executor_id",
            "custodian_id",
            "trust_root_cid",
            "monotonic_store_id",
            "monotonic_store_policy_cid",
            "release_ledger_authority_cid",
            "previous_receipt_cid",
        ):
            object.__setattr__(
                self, name, _dag_cid(getattr(self, name), name)
            )
        if self.release_receipt_cid != self.previous_receipt_cid:
            raise CustodianReleaseError(
                "G241 consumption tombstone must directly spend its release"
            )
        if self.purpose not in {"evaluation", "replay"}:
            raise CustodianReleaseError(
                "G241 consumption purpose must be evaluation or replay"
            )
        if type(self.sequence) is not int or self.sequence < 1:
            raise CustodianReleaseError(
                "G241 consumption sequence must be positive"
            )
        timestamp = _parse_time(self.recorded_at, "recorded_at")
        if self.recorded_at != timestamp.isoformat():
            raise CustodianReleaseError(
                "G241 consumption timestamp is noncanonical"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.tombstone_cid is None:
            object.__setattr__(self, "tombstone_cid", expected)
        elif _dag_cid(
            self.tombstone_cid, "tombstone_cid"
        ) != expected:
            raise CustodianReleaseError(
                "G241 consumption tombstone CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "goal_id": "HSSL-G241",
            "release_receipt_cid": self.release_receipt_cid,
            "access_grant_receipt_cid": (
                self.access_grant_receipt_cid
            ),
            "access_ledger_file_identity_cid": (
                self.access_ledger_file_identity_cid
            ),
            "release_ledger_file_identity_cid": (
                self.release_ledger_file_identity_cid
            ),
            "purpose": self.purpose,
            "executor_id": self.executor_id,
            "custodian_id": self.custodian_id,
            "trust_root_cid": self.trust_root_cid,
            "monotonic_store_id": self.monotonic_store_id,
            "monotonic_store_policy_cid": (
                self.monotonic_store_policy_cid
            ),
            "release_ledger_authority_cid": (
                self.release_ledger_authority_cid
            ),
            "sequence": self.sequence,
            "previous_receipt_cid": self.previous_receipt_cid,
            "recorded_at": self.recorded_at,
            "release_spent": True,
            "holdout_content_included": False,
            "production_promotion_authorized": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "tombstone_cid": self.tombstone_cid,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = dict(_mapping(value, "G241 consumption tombstone"))
        expected = set(cls.__dataclass_fields__) | {
            "goal_id",
            "release_spent",
            "holdout_content_included",
            "production_promotion_authorized",
        }
        _exact(data, expected, "G241 consumption tombstone")
        if (
            data.pop("goal_id") != "HSSL-G241"
            or data.pop("release_spent") is not True
            or data.pop("holdout_content_included") is not False
            or data.pop("production_promotion_authorized") is not False
        ):
            raise CustodianReleaseError(
                "G241 consumption tombstone state changed"
            )
        return cls(**data)  # type: ignore[arg-type]


G241ReleaseLedgerRecordV1 = (
    G241ExternallyGovernedCustodianReleaseReceiptV1
    | G241ReleaseConsumptionTombstoneV1
)


def _release_ledger_record_cid(
    record: G241ReleaseLedgerRecordV1,
) -> str:
    if isinstance(
        record, G241ExternallyGovernedCustodianReleaseReceiptV1
    ):
        return str(record.receipt_cid)
    return str(record.tombstone_cid)


def _ledger_records(
    raw: bytes,
    *,
    genesis_cid: str,
) -> tuple[G241ReleaseLedgerRecordV1, ...]:
    """Parse the exact canonical, monotonic release-ledger chain."""

    if not raw:
        return ()
    if not raw.endswith(b"\n"):
        raise CustodianReleaseError(
            "custodian ledger contains a torn final record"
        )
    records: list[G241ReleaseLedgerRecordV1] = []
    previous = _dag_cid(
        genesis_cid, "custodian ledger genesis CID"
    )
    previous_time: datetime | None = None
    for sequence, line in enumerate(raw.splitlines(keepends=True)):
        if line == b"\n" or not line.endswith(b"\n"):
            raise CustodianReleaseError(
                "custodian ledger contains an empty or torn record"
            )
        value = _mapping(
            _strict_json(
                line[:-1],
                f"custodian ledger record {sequence}",
            ),
            f"custodian ledger record {sequence}",
        )
        schema = value.get("schema")
        if schema == G241_RELEASE_RECEIPT_SCHEMA_V1:
            record: G241ReleaseLedgerRecordV1 = (
                G241ExternallyGovernedCustodianReleaseReceiptV1.from_dict(
                    value
                )
            )
        elif schema == G241_RELEASE_CONSUMPTION_TOMBSTONE_SCHEMA_V1:
            record = G241ReleaseConsumptionTombstoneV1.from_dict(
                value
            )
        else:
            raise CustodianReleaseError(
                "custodian ledger record schema changed"
            )
        if canonical_dag_json_bytes(record.to_dict()) != line[:-1]:
            raise CustodianReleaseError(
                "custodian ledger record is not canonical DAG-JSON"
            )
        timestamp = _parse_time(
            record.recorded_at, "custodian ledger recorded_at"
        )
        if (
            record.sequence != sequence
            or record.previous_receipt_cid != previous
            or (
                previous_time is not None
                and timestamp <= previous_time
            )
        ):
            raise CustodianReleaseError(
                "custodian ledger sequence, parent, or monotonic time changed"
            )
        if isinstance(record, G241ReleaseConsumptionTombstoneV1):
            if (
                not records
                or not isinstance(
                    records[-1],
                    G241ExternallyGovernedCustodianReleaseReceiptV1,
                )
                or record.release_receipt_cid
                != records[-1].receipt_cid
                or record.access_ledger_file_identity_cid
                != records[-1].access_ledger_file_identity_cid
                or record.release_ledger_file_identity_cid
                != records[-1].release_ledger_file_identity_cid
                or record.executor_id != records[-1].executor_id
                or record.custodian_id != records[-1].custodian_id
                or record.trust_root_cid
                != records[-1].trust_root_cid
            ):
                raise CustodianReleaseError(
                    "G241 consumption tombstone does not spend the "
                    "immediately preceding release"
                )
        previous = _release_ledger_record_cid(record)
        previous_time = timestamp
        records.append(record)
    record_cids = tuple(
        _release_ledger_record_cid(item) for item in records
    )
    if len(record_cids) != len(set(record_cids)):
        raise CustodianReleaseError(
            "custodian ledger contains duplicate record CIDs"
        )
    return tuple(records)


def _open_ledger(
    path: Path,
    *,
    repo_root: Path,
    create: bool = True,
) -> int:
    return _open_secure_file(
        Path(path),
        repo_root=Path(repo_root),
        field_name="custodian release ledger",
        flags=os.O_RDWR | os.O_APPEND,
        create=create,
        private=True,
    )


def _parse_access_ledger(
    raw: bytes,
) -> tuple[ReplacementHoldoutAccessReceipt, ...]:
    if not raw:
        return ()
    records: list[ReplacementHoldoutAccessReceipt] = []
    for sequence, line in enumerate(raw.splitlines(keepends=True)):
        if line == b"\n" or not line.endswith(b"\n"):
            raise CustodianReleaseError(
                "replacement access ledger contains an empty or torn record"
            )
        wrapper = _mapping(
            _strict_json(
                line[:-1],
                f"replacement access ledger record {sequence}",
            ),
            "replacement access ledger record",
        )
        _exact(
            wrapper,
            {"schema", "receipt"},
            "replacement access ledger record",
        )
        if (
            wrapper.get("schema")
            != REPLACEMENT_HOLDOUT_ACCESS_LEDGER_SCHEMA
        ):
            raise CustodianReleaseError(
                "replacement access ledger schema changed"
            )
        try:
            receipt = ReplacementHoldoutAccessReceipt.from_dict(
                wrapper.get("receipt")
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise CustodianReleaseError(
                "replacement access ledger receipt is invalid"
            ) from exc
        if canonical_dag_json_bytes(
            {
                "schema": REPLACEMENT_HOLDOUT_ACCESS_LEDGER_SCHEMA,
                "receipt": receipt.to_dict(),
            }
        ) != line[:-1]:
            raise CustodianReleaseError(
                "replacement access ledger record is not canonical DAG-JSON"
            )
        expected_previous = (
            None if sequence == 0 else records[-1].receipt_cid
        )
        if (
            receipt.sequence != sequence
            or receipt.previous_receipt_cid != expected_previous
        ):
            raise CustodianReleaseError(
                "replacement access ledger chain is broken"
            )
        records.append(receipt)
    return tuple(records)


def _open_access_ledger(
    path: Path,
    *,
    repo_root: Path,
    seal: ReplacementHoldoutSeal,
    create: bool = True,
) -> int:
    candidate = _canonical_absolute_path(
        Path(path), "replacement access ledger"
    )
    try:
        authority_cid = replacement_holdout_ledger_authority_cid(
            seal.sealed_manifest_cid,
            candidate,
        )
    except (TypeError, ValueError) as exc:
        raise CustodianReleaseError(
            "replacement access-ledger authority is invalid"
        ) from exc
    if (
        seal.access_ledger_authority_cid != authority_cid
    ):
        raise CustodianReleaseError(
            "replacement access ledger is not the exact seal-bound ledger"
        )
    return _open_secure_file(
        candidate,
        repo_root=Path(repo_root),
        field_name="replacement access ledger",
        flags=os.O_RDWR | os.O_APPEND,
        create=create,
        private=True,
    )


def _empty_access_ledger_snapshot(
    descriptor: int,
    *,
    seal: ReplacementHoldoutSeal,
) -> tuple[str, int]:
    records = _parse_access_ledger(
        _read_bounded_fd(
            descriptor,
            field_name="replacement access ledger",
        )
    )
    if records:
        if any(
            receipt.seal_contract_cid != seal.seal_contract_cid
            or receipt.sealed_manifest_cid
            != seal.sealed_manifest_cid
            for receipt in records
        ):
            raise CustodianReleaseError(
                "replacement access ledger mixes seal identities"
            )
        raise CustodianReleaseError(
            "pre-release access-ledger activity permanently invalidates "
            "the G241 release"
        )
    snapshot = {
        "schema": G241_ACCESS_LEDGER_SNAPSHOT_SCHEMA_V1,
        "seal_contract_cid": seal.seal_contract_cid,
        "sealed_manifest_cid": seal.sealed_manifest_cid,
        "access_ledger_authority_cid": (
            seal.access_ledger_authority_cid
        ),
        "event_count": 0,
        "last_receipt_cid": None,
        "ledger_file_identity_cid": _ledger_file_identity_cid(
            descriptor,
            ledger_role="replacement-access",
        ),
    }
    return cid_for_dag_json(snapshot), 0


def _open_source_lock(
    repo_root: Path,
    *,
    git_executable_path: Path,
    expected_git_executable_cid: str,
) -> int:
    code, value = _git(
        repo_root,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
        executable_path=git_executable_path,
        expected_executable_cid=expected_git_executable_cid,
    )
    if code != 0 or not isinstance(value, str) or not value:
        raise CustodianReleaseError(
            "G241 Git common directory is unavailable"
        )
    common = Path(value)
    if not common.is_absolute():
        common = repo_root / common
    try:
        common = common.resolve(strict=True)
    except OSError as exc:
        raise CustodianReleaseError(
            "G241 Git common directory cannot be resolved"
        ) from exc
    return _open_secure_file(
        common / "g241-custodian-release.lock",
        repo_root=None,
        field_name="G241 source lock",
        flags=os.O_RDWR,
        create=True,
        private=True,
    )


def _write_all(descriptor: int, payload: bytes) -> None:
    pending = memoryview(payload)
    while pending:
        try:
            written = os.write(descriptor, pending)
        except OSError as exc:
            raise CustodianReleaseError(
                "custodian ledger append failed"
            ) from exc
        if written <= 0:
            raise CustodianReleaseError(
                "custodian ledger append did not complete"
            )
        pending = pending[written:]


def _revalidate_private_path(
    descriptor: int,
    path: Path,
    *,
    repo_root: Path,
    field_name: str,
) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise CustodianReleaseError(
            f"{field_name} descriptor is no longer a private single-link file"
        )
    reopened = _open_secure_file(
        Path(path),
        repo_root=repo_root,
        field_name=field_name,
        flags=os.O_RDONLY,
        create=False,
        private=True,
    )
    try:
        reopened_metadata = os.fstat(reopened)
        if (
            metadata.st_dev,
            metadata.st_ino,
        ) != (
            reopened_metadata.st_dev,
            reopened_metadata.st_ino,
        ):
            raise CustodianReleaseError(
                f"{field_name} path changed after it was locked"
            )
    finally:
        os.close(reopened)


def _same_current_source(
    left: _CurrentSourceV1,
    right: _CurrentSourceV1,
) -> bool:
    return left == right


def _validate_receipt_source(
    receipt: G241ExternallyGovernedCustodianReleaseReceiptV1,
    current: _CurrentSourceV1,
) -> None:
    if (
        receipt.source_commit != current.outer_commit
        or receipt.source_tree_cid
        != g241_git_tree_cid(current.outer_tree)
        or receipt.recursive_gitlinks_cid
        != current.g240_recursive_gitlinks_cid
        or receipt.source_identity_cid
        != current.source_identity_cid
    ):
        raise CustodianReleaseError(
            "durable G241 receipt source is dirty, stale, or rebased"
        )


@dataclass(frozen=True, slots=True)
class _G241DurableSourceIndexView:
    source_commit: str
    source_commit_cid: str
    source_tree_cid: str
    recursive_gitlinks_cid: str
    run_plan_cid: str


@dataclass(frozen=True, slots=True)
class _G241DurableReplayView:
    source_index: _G241DurableSourceIndexView
    external_artifact_cids: Mapping[str, str]
    parent_ledger_cid: str


def _g239_replay_view(
    receipt: G241ExternallyGovernedCustodianReleaseReceiptV1,
) -> _G241DurableReplayView:
    return _G241DurableReplayView(
        source_index=_G241DurableSourceIndexView(
            source_commit=receipt.source_commit,
            source_commit_cid=g238_git_commit_cid(
                receipt.source_commit
            ),
            source_tree_cid=receipt.source_tree_cid,
            recursive_gitlinks_cid=receipt.recursive_gitlinks_cid,
            run_plan_cid=receipt.run_plan_cid,
        ),
        external_artifact_cids=receipt.artifact_cids,
        parent_ledger_cid=receipt.parent_ledger_cid,
    )


def _authorize_g241_custodian_release_v1(
    *,
    g231_bundle: object,
    g231_sources: Mapping[str, object],
    g232_proposal: object,
    authority_path: Path,
    trusted_authority_cid: str,
    validator_attestation_path: Path,
    trusted_validator_attestation_cid: str,
    custodian_trust_root_path: Path,
    trusted_custodian_trust_root_cid: str,
    ledger_path: Path,
    access_ledger_path: Path,
    repo_root: Path,
    clock: Callable[[], datetime],
) -> G241ExternallyGovernedCustodianReleaseReceiptV1:
    """Private clock-injection seam used only by deterministic tests."""

    root = Path(repo_root).resolve(strict=True)
    seal_value = _mapping(g231_sources, "G231 sources").get(
        "replacement_holdout_seal"
    )
    if not isinstance(seal_value, ReplacementHoldoutSeal):
        raise CustodianReleaseError(
            "G241 requires the typed G231 replacement seal"
        )
    seal = ReplacementHoldoutSeal.from_dict(seal_value.to_dict())
    trust_root = load_g241_custodian_trust_root_v1(
        path=custodian_trust_root_path,
        trusted_trust_root_cid=trusted_custodian_trust_root_cid,
        repo_root=root,
    )
    _validate_release_ledger_authority(
        trust_root, Path(ledger_path)
    )
    if trust_root.g239_authority_cid != _dag_cid(
        trusted_authority_cid, "trusted G239 authority CID"
    ):
        raise CustodianReleaseError(
            "custodian and G239 trust roots name different authorities"
        )

    source_lock = _open_source_lock(
        root,
        git_executable_path=Path(trust_root.git_executable_path),
        expected_git_executable_cid=trust_root.git_executable_cid,
    )
    access_descriptor = -1
    ledger_descriptor = -1
    try:
        fcntl.flock(source_lock, fcntl.LOCK_EX)
        access_descriptor = _open_access_ledger(
            Path(access_ledger_path),
            repo_root=root,
            seal=seal,
        )
        fcntl.flock(access_descriptor, fcntl.LOCK_EX)
        access_head, access_count = _empty_access_ledger_snapshot(
            access_descriptor, seal=seal
        )
        access_file_identity_cid = _ledger_file_identity_cid(
            access_descriptor,
            ledger_role="replacement-access",
        )
        ledger_descriptor = _open_ledger(
            Path(ledger_path), repo_root=root
        )
        fcntl.flock(ledger_descriptor, fcntl.LOCK_EX)
        release_file_identity_cid = _ledger_file_identity_cid(
            ledger_descriptor,
            ledger_role="custodian-release",
        )
        records = _ledger_records(
            _read_bounded_fd(
                ledger_descriptor,
                field_name="custodian release ledger",
            ),
            genesis_cid=trust_root.ledger_genesis_cid,
        )
        previous = (
            trust_root.ledger_genesis_cid
            if not records
            else _release_ledger_record_cid(records[-1])
        )

        source_replay = recompute_g241_source_chain_v1(
            g231_bundle=g231_bundle,
            g231_sources=g231_sources,
            g232_proposal=g232_proposal,
        )
        authorization = source_replay.authorization
        try:
            authorization.validate_against(seal)
        except (TypeError, ValueError) as exc:
            raise CustodianReleaseError(
                "source-replayed authorization does not bind the exact seal"
            ) from exc
        if (
            source_replay.source_index.access_ledger_authority_cid
            != seal.access_ledger_authority_cid
        ):
            raise CustodianReleaseError(
                "source replay names a different access-ledger authority"
            )
        timestamp = clock()
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            raise CustodianReleaseError(
                "G241 trusted clock must return a timezone-aware datetime"
            )
        timestamp = timestamp.astimezone(timezone.utc)
        if records and timestamp <= _parse_time(
            records[-1].recorded_at,
            "previous custodian ledger timestamp",
        ):
            raise CustodianReleaseError(
                "G241 trusted clock did not advance monotonically"
            )
        external = _evaluate_g239_for_g241_v1(
            authority_path=authority_path,
            trusted_authority_cid=trusted_authority_cid,
            validator_attestation_path=validator_attestation_path,
            trusted_validator_attestation_cid=(
                trusted_validator_attestation_cid
            ),
            custodian_trust_root=trust_root,
            source_replay=source_replay,
            repo_root=root,
            evaluated_at=timestamp,
            freshness_reference_at=timestamp,
        )
        current = _inspect_current_source(
            root,
            git_executable_path=Path(trust_root.git_executable_path),
            expected_git_executable_cid=trust_root.git_executable_cid,
        )
        index = source_replay.source_index
        if (
            current.outer_commit != index.source_commit
            or g241_git_tree_cid(current.outer_tree)
            != index.source_tree_cid
            or current.g240_recursive_gitlinks_cid
            != index.recursive_gitlinks_cid
            or current.source_identity_cid
            != external.source_identity_cid
        ):
            raise CustodianReleaseError(
                "G241 source changed after external validation"
            )
        request = G241CustodianReleaseRequestV1(
            source_index_cid=str(index.source_index_cid),
            source_commit=index.source_commit,
            source_tree_cid=index.source_tree_cid,
            recursive_gitlinks_cid=index.recursive_gitlinks_cid,
            source_identity_cid=external.source_identity_cid,
            run_plan_cid=index.run_plan_cid,
            parent_ledger_cid=source_replay.parent_ledger_cid,
            artifact_cids=source_replay.external_artifact_cids,
            artifact_set_cid=external.artifact_set_cid,
            upstream_authority_cids=index.upstream_authority_cids,
            g232_authorization_cid=authorization.authorization_cid,
            seal_contract_cid=authorization.seal_contract_cid,
            sealed_manifest_cid=authorization.sealed_manifest_cid,
            authorized_variant_ids=authorization.authorized_variant_ids,
            g239_evaluation_cid=str(external.evaluation_cid),
            g239_authority_cid=external.authority_cid,
            g239_operational_receipt_cid=(
                external.operational_receipt_cid
            ),
            g239_validator_claim_cid=external.validator_claim_cid,
            g239_validator_attestation_cid=(
                external.validator_attestation_cid
            ),
            g239_validator_key_id=external.validator_key_id,
            g239_observed_at=external.observed_at,
            g239_evaluated_at=external.evaluated_at,
            decision_producer_id=external.producer_id,
            external_validator_id=external.validator_id,
            custodian_id=trust_root.custodian_id,
            executor_id=trust_root.executor_id,
            trust_root_cid=str(trust_root.trust_root_cid),
            access_ledger_authority_cid=(
                seal.access_ledger_authority_cid
            ),
            access_ledger_file_identity_cid=(
                access_file_identity_cid
            ),
            access_ledger_head_cid=access_head,
            access_ledger_event_count=access_count,
            release_ledger_file_identity_cid=(
                release_file_identity_cid
            ),
            ledger_sequence=len(records),
            previous_ledger_receipt_cid=previous,
        )
        receipt = (
            G241ExternallyGovernedCustodianReleaseReceiptV1._from_request(
                request=request,
                recorded_at=timestamp,
            )
        )

        final_access_head, _ = _empty_access_ledger_snapshot(
            access_descriptor, seal=seal
        )
        final_source = _inspect_current_source(
            root,
            git_executable_path=Path(trust_root.git_executable_path),
            expected_git_executable_cid=trust_root.git_executable_cid,
        )
        if (
            final_access_head != access_head
            or not _same_current_source(current, final_source)
        ):
            raise CustodianReleaseError(
                "source or access ledger changed before durable append"
            )
        _revalidate_private_path(
            access_descriptor,
            Path(access_ledger_path),
            repo_root=root,
            field_name="replacement access ledger",
        )
        _revalidate_private_path(
            ledger_descriptor,
            Path(ledger_path),
            repo_root=root,
            field_name="custodian release ledger",
        )
        os.lseek(ledger_descriptor, 0, os.SEEK_END)
        _write_all(
            ledger_descriptor,
            canonical_dag_json_bytes(receipt.to_dict()) + b"\n",
        )
        os.fsync(ledger_descriptor)
        durable_records = _ledger_records(
            _read_bounded_fd(
                ledger_descriptor,
                field_name="custodian release ledger",
            ),
            genesis_cid=trust_root.ledger_genesis_cid,
        )
        durable_access_head, _ = _empty_access_ledger_snapshot(
            access_descriptor, seal=seal
        )
        _revalidate_private_path(
            access_descriptor,
            Path(access_ledger_path),
            repo_root=root,
            field_name="replacement access ledger",
        )
        _revalidate_private_path(
            ledger_descriptor,
            Path(ledger_path),
            repo_root=root,
            field_name="custodian release ledger",
        )
        durable_source = _inspect_current_source(
            root,
            git_executable_path=Path(trust_root.git_executable_path),
            expected_git_executable_cid=trust_root.git_executable_cid,
        )
        if (
            not durable_records
            or not isinstance(
                durable_records[-1],
                G241ExternallyGovernedCustodianReleaseReceiptV1,
            )
            or durable_records[-1].receipt_cid
            != receipt.receipt_cid
            or durable_access_head != access_head
            or not _same_current_source(current, durable_source)
        ):
            raise CustodianReleaseError(
                "G241 durable release revalidation failed closed"
            )
        durable_receipt = durable_records[-1]
        if not isinstance(
            durable_receipt,
            G241ExternallyGovernedCustodianReleaseReceiptV1,
        ):  # pragma: no cover - guarded above
            raise CustodianReleaseError(
                "G241 durable ledger head is not a release receipt"
            )
        return durable_receipt
    finally:
        for descriptor in (
            ledger_descriptor,
            access_descriptor,
            source_lock,
        ):
            if descriptor >= 0:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)


def authorize_g241_custodian_release_v1(
    *,
    g231_bundle: object,
    g231_sources: Mapping[str, object],
    g232_proposal: object,
    authority_path: Path,
    trusted_authority_cid: str,
    validator_attestation_path: Path,
    trusted_validator_attestation_cid: str,
    custodian_trust_root_path: Path,
    trusted_custodian_trust_root_cid: str,
    ledger_path: Path,
    access_ledger_path: Path,
    repo_root: Path,
) -> G241ExternallyGovernedCustodianReleaseReceiptV1:
    """Append a release using only the trusted UTC system clock."""

    return _authorize_g241_custodian_release_v1(
        g231_bundle=g231_bundle,
        g231_sources=g231_sources,
        g232_proposal=g232_proposal,
        authority_path=authority_path,
        trusted_authority_cid=trusted_authority_cid,
        validator_attestation_path=validator_attestation_path,
        trusted_validator_attestation_cid=(
            trusted_validator_attestation_cid
        ),
        custodian_trust_root_path=custodian_trust_root_path,
        trusted_custodian_trust_root_cid=(
            trusted_custodian_trust_root_cid
        ),
        ledger_path=ledger_path,
        access_ledger_path=access_ledger_path,
        repo_root=repo_root,
        clock=lambda: datetime.now(timezone.utc),
    )


def _append_locked_access_event(
    descriptor: int,
    *,
    seal: ReplacementHoldoutSeal,
    authorization: G232ReplacementHoldoutAuthorization,
    g241_release_receipt_cid: str,
    purpose: str,
    executor_id: str,
    event: str,
) -> ReplacementHoldoutAccessReceipt:
    records = _parse_access_ledger(
        _read_bounded_fd(
            descriptor,
            field_name="replacement access ledger",
        )
    )
    if purpose not in {"evaluation", "replay"}:
        raise CustodianReleaseError(
            "replacement holdout purpose must be evaluation or replay"
        )
    executor = _actor(executor_id, "holdout executor")
    release_cid = _dag_cid(
        g241_release_receipt_cid, "G241 release receipt CID"
    )
    outcomes = {
        "custody_integrity_failure",
        "custody_release_failed",
        "manifest_released",
    }
    if event == "access_granted":
        if records:
            raise CustodianReleaseError(
                "validated G241 release is already consumed"
            )
    elif event in outcomes:
        if (
            not records
            or records[-1].event != "access_granted"
            or records[-1].authorization_cid
            != authorization.authorization_cid
            or records[-1].pilot_artifact_cid
            != authorization.pilot_artifact_cid
            or records[-1].g241_release_receipt_cid != release_cid
            or records[-1].purpose != purpose
            or records[-1].executor_id != executor
        ):
            raise CustodianReleaseError(
                "custody outcome does not match the locked access grant"
            )
    else:
        raise CustodianReleaseError(
            "unsupported locked replacement access event"
        )
    flags = {
        "access_granted": (True, False, False),
        "custody_integrity_failure": (True, True, True),
        "custody_release_failed": (True, False, False),
        "manifest_released": (True, True, False),
    }[event]
    body = {
        "schema": REPLACEMENT_HOLDOUT_ACCESS_RECEIPT_SCHEMA,
        "sequence": len(records),
        "previous_receipt_cid": (
            records[-1].receipt_cid if records else None
        ),
        "event": event,
        "seal_contract_cid": seal.seal_contract_cid,
        "sealed_manifest_cid": seal.sealed_manifest_cid,
        "authorization_cid": authorization.authorization_cid,
        "pilot_artifact_cid": authorization.pilot_artifact_cid,
        "g241_release_receipt_cid": release_cid,
        "purpose": purpose,
        "executor_id": executor,
        "access_authorized": flags[0],
        "manifest_released": flags[1],
        "invalidates_seal": flags[2],
    }
    receipt = ReplacementHoldoutAccessReceipt(
        **body,
        receipt_cid=cid_for_dag_json(body),
    )
    wrapper = {
        "schema": REPLACEMENT_HOLDOUT_ACCESS_LEDGER_SCHEMA,
        "receipt": receipt.to_dict(),
    }
    os.lseek(descriptor, 0, os.SEEK_END)
    _write_all(
        descriptor,
        canonical_dag_json_bytes(wrapper) + b"\n",
    )
    os.fsync(descriptor)
    durable = _parse_access_ledger(
        _read_bounded_fd(
            descriptor,
            field_name="replacement access ledger",
        )
    )
    if not durable or durable[-1].receipt_cid != receipt.receipt_cid:
        raise CustodianReleaseError(
            "locked access event was not durably appended"
        )
    return durable[-1]


def _append_locked_release_consumption(
    descriptor: int,
    *,
    trust_root: G241CustodianTrustRootV1,
    release_receipt: G241ExternallyGovernedCustodianReleaseReceiptV1,
    access_grant: ReplacementHoldoutAccessReceipt,
    access_ledger_file_identity_cid: str,
    purpose: str,
    executor_id: str,
    custodian_id: str,
) -> G241ReleaseConsumptionTombstoneV1:
    """Make the release-ledger head a durable spent marker."""

    records = _ledger_records(
        _read_bounded_fd(
            descriptor,
            field_name="custodian release ledger",
        ),
        genesis_cid=trust_root.ledger_genesis_cid,
    )
    if (
        not records
        or not isinstance(
            records[-1],
            G241ExternallyGovernedCustodianReleaseReceiptV1,
        )
        or records[-1].receipt_cid != release_receipt.receipt_cid
        or access_grant.event != "access_granted"
        or access_grant.g241_release_receipt_cid
        != release_receipt.receipt_cid
        or access_grant.executor_id != executor_id
        or release_receipt.executor_id != executor_id
        or release_receipt.custodian_id != custodian_id
        or release_receipt.trust_root_cid
        != trust_root.trust_root_cid
        or release_receipt.access_ledger_file_identity_cid
        != access_ledger_file_identity_cid
    ):
        raise CustodianReleaseError(
            "G241 release consumption does not match the locked heads"
        )
    release_file_identity_cid = _ledger_file_identity_cid(
        descriptor,
        ledger_role="custodian-release",
    )
    if (
        release_receipt.release_ledger_file_identity_cid
        != release_file_identity_cid
    ):
        raise CustodianReleaseError(
            "G241 release-ledger identity changed before consumption"
        )
    timestamp = datetime.now(timezone.utc)
    if timestamp <= _parse_time(
        release_receipt.recorded_at, "release recorded_at"
    ):
        raise CustodianReleaseError(
            "trusted clock did not advance for G241 consumption"
        )
    tombstone = G241ReleaseConsumptionTombstoneV1(
        release_receipt_cid=str(release_receipt.receipt_cid),
        access_grant_receipt_cid=str(access_grant.receipt_cid),
        access_ledger_file_identity_cid=(
            access_ledger_file_identity_cid
        ),
        release_ledger_file_identity_cid=(
            release_file_identity_cid
        ),
        purpose=purpose,
        executor_id=executor_id,
        custodian_id=custodian_id,
        trust_root_cid=str(trust_root.trust_root_cid),
        monotonic_store_id=trust_root.monotonic_store_id,
        monotonic_store_policy_cid=(
            trust_root.monotonic_store_policy_cid
        ),
        release_ledger_authority_cid=(
            trust_root.release_ledger_authority_cid
        ),
        sequence=len(records),
        previous_receipt_cid=str(release_receipt.receipt_cid),
        recorded_at=timestamp.isoformat(),
    )
    os.lseek(descriptor, 0, os.SEEK_END)
    _write_all(
        descriptor,
        canonical_dag_json_bytes(tombstone.to_dict()) + b"\n",
    )
    os.fsync(descriptor)
    durable = _ledger_records(
        _read_bounded_fd(
            descriptor,
            field_name="custodian release ledger",
        ),
        genesis_cid=trust_root.ledger_genesis_cid,
    )
    if (
        not durable
        or not isinstance(
            durable[-1], G241ReleaseConsumptionTombstoneV1
        )
        or durable[-1].tombstone_cid != tombstone.tombstone_cid
    ):
        raise CustodianReleaseError(
            "G241 consumption tombstone was not durably appended"
        )
    return durable[-1]


@dataclass(slots=True)
class G241CustodyAccessTransactionV1:
    """Live, lock-scoped handoff; never serialize or retain this object."""

    release_receipt: G241ExternallyGovernedCustodianReleaseReceiptV1
    grant_receipt: ReplacementHoldoutAccessReceipt
    consumption_tombstone: G241ReleaseConsumptionTombstoneV1
    _descriptor: int
    _release_descriptor: int
    _seal: ReplacementHoldoutSeal
    _authorization: G232ReplacementHoldoutAuthorization
    _purpose: str
    _executor_id: str
    _repo_root: Path
    _git_executable_path: Path
    _git_executable_cid: str
    _source: _CurrentSourceV1
    _access_ledger_path: Path
    _release_ledger_path: Path
    terminal_receipt: ReplacementHoldoutAccessReceipt | None = None

    def _record_terminal(
        self, event: str
    ) -> ReplacementHoldoutAccessReceipt:
        if self.terminal_receipt is not None:
            raise CustodianReleaseError(
                "G241 custody transaction already has a terminal outcome"
            )
        receipt = _append_locked_access_event(
            self._descriptor,
            seal=self._seal,
            authorization=self._authorization,
            g241_release_receipt_cid=str(
                self.release_receipt.receipt_cid
            ),
            purpose=self._purpose,
            executor_id=self._executor_id,
            event=event,
        )
        self.terminal_receipt = receipt
        return receipt

    def record_manifest_released(
        self,
    ) -> ReplacementHoldoutAccessReceipt:
        try:
            current = _inspect_current_source(
                self._repo_root,
                git_executable_path=self._git_executable_path,
                expected_git_executable_cid=(
                    self._git_executable_cid
                ),
            )
            if not _same_current_source(self._source, current):
                raise CustodianReleaseError(
                    "source changed before the custody success receipt"
                )
            _revalidate_private_path(
                self._descriptor,
                self._access_ledger_path,
                repo_root=self._repo_root,
                field_name="replacement access ledger",
            )
            _revalidate_private_path(
                self._release_descriptor,
                self._release_ledger_path,
                repo_root=self._repo_root,
                field_name="custodian release ledger",
            )
        except (OSError, ValueError) as exc:
            self._record_terminal("custody_integrity_failure")
            raise CustodianReleaseError(
                "G241 custody boundary changed before manifest release"
            ) from exc
        return self._record_terminal("manifest_released")

    def record_custody_failure(
        self,
        *,
        integrity_failure: bool = False,
    ) -> ReplacementHoldoutAccessReceipt:
        return self._record_terminal(
            "custody_integrity_failure"
            if integrity_failure
            else "custody_release_failed"
        )


@contextmanager
def _locked_g241_release_receipt_v1(
    *,
    receipt_cid: str,
    ledger_path: Path,
    access_ledger_path: Path,
    seal: ReplacementHoldoutSeal,
    authorization: G232ReplacementHoldoutAuthorization,
    authority_path: Path,
    trusted_authority_cid: str,
    validator_attestation_path: Path,
    trusted_validator_attestation_cid: str,
    custodian_trust_root_path: Path,
    trusted_custodian_trust_root_cid: str,
    repo_root: Path,
    consume_purpose: str | None = None,
    consume_executor_id: str | None = None,
    consume_custodian_id: str | None = None,
) -> Iterator[
    tuple[
        G241ExternallyGovernedCustodianReleaseReceiptV1,
        G241CustodyAccessTransactionV1 | None,
    ]
]:
    """Hold all cooperating locks across validation and optional custody."""

    requested_cid = _dag_cid(receipt_cid, "G241 release receipt CID")
    root = Path(repo_root).resolve(strict=True)
    try:
        canonical_seal = ReplacementHoldoutSeal.from_dict(seal.to_dict())
        canonical_authorization = (
            G232ReplacementHoldoutAuthorization.from_dict(
                authorization.to_dict()
            )
        )
        canonical_authorization.validate_against(canonical_seal)
    except (AttributeError, TypeError, ValueError, KeyError) as exc:
        raise CustodianReleaseError(
            "G241 consumer requires an exact typed seal and authorization"
        ) from exc
    trust_root = load_g241_custodian_trust_root_v1(
        path=custodian_trust_root_path,
        trusted_trust_root_cid=trusted_custodian_trust_root_cid,
        repo_root=root,
    )
    _validate_release_ledger_authority(
        trust_root, Path(ledger_path)
    )
    source_lock = _open_source_lock(
        root,
        git_executable_path=Path(trust_root.git_executable_path),
        expected_git_executable_cid=trust_root.git_executable_cid,
    )
    access_descriptor = -1
    ledger_descriptor = -1
    try:
        fcntl.flock(source_lock, fcntl.LOCK_EX)
        access_descriptor = _open_access_ledger(
            Path(access_ledger_path),
            repo_root=root,
            seal=canonical_seal,
            create=False,
        )
        fcntl.flock(access_descriptor, fcntl.LOCK_EX)
        access_head, access_count = _empty_access_ledger_snapshot(
            access_descriptor,
            seal=canonical_seal,
        )
        access_file_identity_cid = _ledger_file_identity_cid(
            access_descriptor,
            ledger_role="replacement-access",
        )
        ledger_descriptor = _open_ledger(
            Path(ledger_path), repo_root=root, create=False
        )
        fcntl.flock(ledger_descriptor, fcntl.LOCK_EX)
        release_file_identity_cid = _ledger_file_identity_cid(
            ledger_descriptor,
            ledger_role="custodian-release",
        )
        records = _ledger_records(
            _read_bounded_fd(
                ledger_descriptor,
                field_name="custodian release ledger",
            ),
            genesis_cid=trust_root.ledger_genesis_cid,
        )
        if (
            records
            and isinstance(
                records[-1], G241ReleaseConsumptionTombstoneV1
            )
            and records[-1].release_receipt_cid == requested_cid
        ):
            raise CustodianReleaseError(
                "requested G241 release receipt is durably spent"
            )
        if (
            not records
            or not isinstance(
                records[-1],
                G241ExternallyGovernedCustodianReleaseReceiptV1,
            )
            or records[-1].receipt_cid != requested_cid
        ):
            raise CustodianReleaseError(
                "requested G241 receipt is not the durable current ledger head"
            )
        receipt = records[-1]
        if (
            receipt.g232_authorization_cid
            != canonical_authorization.authorization_cid
            or receipt.seal_contract_cid
            != canonical_seal.seal_contract_cid
            or receipt.sealed_manifest_cid
            != canonical_seal.sealed_manifest_cid
            or receipt.authorized_variant_ids
            != canonical_authorization.authorized_variant_ids
            or receipt.source_commit
            != canonical_authorization.source_commit
            or receipt.access_ledger_authority_cid
            != canonical_seal.access_ledger_authority_cid
            or receipt.access_ledger_file_identity_cid
            != access_file_identity_cid
            or receipt.access_ledger_head_cid != access_head
            or receipt.access_ledger_event_count != access_count
            or receipt.release_ledger_file_identity_cid
            != release_file_identity_cid
            or receipt.artifact_cids["g220_replacement_holdout_seal"]
            != canonical_seal.seal_contract_cid
            or receipt.artifact_cids["g232_authorization_proposal"]
            != canonical_authorization.authorization_cid
            or receipt.artifact_cids["g232_pilot_decision"]
            != canonical_authorization.pilot_artifact_cid
        ):
            raise CustodianReleaseError(
                "durable G241 receipt differs from the exact seal, "
                "authorization, or empty access-ledger head"
            )
        if (
            receipt.trust_root_cid != trust_root.trust_root_cid
            or receipt.g239_authority_cid
            != trust_root.g239_authority_cid
            or receipt.g239_validator_key_id
            != trust_root.validator_key_id
            or receipt.external_validator_id
            != trust_root.validator_id
            or receipt.custodian_id != trust_root.custodian_id
            or receipt.executor_id != trust_root.executor_id
            or receipt.g239_validator_attestation_cid
            != _dag_cid(
                trusted_validator_attestation_cid,
                "trusted G239 validator-attestation CID",
            )
        ):
            raise CustodianReleaseError(
                "durable G241 receipt differs from the custody trust root"
            )
        current = _inspect_current_source(
            root,
            git_executable_path=Path(trust_root.git_executable_path),
            expected_git_executable_cid=trust_root.git_executable_cid,
        )
        _validate_receipt_source(receipt, current)
        trusted_now = datetime.now(timezone.utc)
        external = _evaluate_g239_for_g241_v1(
            authority_path=authority_path,
            trusted_authority_cid=trusted_authority_cid,
            validator_attestation_path=validator_attestation_path,
            trusted_validator_attestation_cid=(
                trusted_validator_attestation_cid
            ),
            custodian_trust_root=trust_root,
            source_replay=_g239_replay_view(receipt),
            repo_root=root,
            evaluated_at=_parse_time(
                receipt.g239_evaluated_at,
                "receipt G239 evaluated_at",
            ),
            freshness_reference_at=trusted_now,
        )
        if (
            external.evaluation_cid != receipt.g239_evaluation_cid
            or external.authority_cid != receipt.g239_authority_cid
            or external.operational_receipt_cid
            != receipt.g239_operational_receipt_cid
            or external.validator_claim_cid
            != receipt.g239_validator_claim_cid
            or external.validator_attestation_cid
            != receipt.g239_validator_attestation_cid
            or external.validator_key_id
            != receipt.g239_validator_key_id
            or external.source_identity_cid
            != receipt.source_identity_cid
            or external.producer_id != receipt.decision_producer_id
            or external.validator_id != receipt.external_validator_id
            or external.run_plan_cid != receipt.run_plan_cid
            or external.parent_ledger_cid != receipt.parent_ledger_cid
            or dict(external.artifact_cids)
            != dict(receipt.artifact_cids)
            or external.artifact_set_cid != receipt.artifact_set_cid
            or external.observed_at != receipt.g239_observed_at
            or external.evaluated_at != receipt.g239_evaluated_at
        ):
            raise CustodianReleaseError(
                "durable G241 receipt differs from revalidated G239 evidence"
            )
        final_access_head, _ = _empty_access_ledger_snapshot(
            access_descriptor,
            seal=canonical_seal,
        )
        final_source = _inspect_current_source(
            root,
            git_executable_path=Path(trust_root.git_executable_path),
            expected_git_executable_cid=trust_root.git_executable_cid,
        )
        if (
            final_access_head != access_head
            or not _same_current_source(current, final_source)
        ):
            raise CustodianReleaseError(
                "source or access ledger changed during G241 consumption"
            )
        _revalidate_private_path(
            access_descriptor,
            Path(access_ledger_path),
            repo_root=root,
            field_name="replacement access ledger",
        )
        _revalidate_private_path(
            ledger_descriptor,
            Path(ledger_path),
            repo_root=root,
            field_name="custodian release ledger",
        )
        consume_values = (consume_purpose, consume_executor_id)
        if any(value is not None for value in consume_values) and not all(
            value is not None for value in consume_values
        ):
            raise CustodianReleaseError(
                "G241 consumption requires purpose and executor"
            )

        transaction: G241CustodyAccessTransactionV1 | None = None
        if all(value is not None for value in consume_values):
            assert consume_purpose is not None
            assert consume_executor_id is not None
            purpose = consume_purpose
            if purpose not in {"evaluation", "replay"}:
                raise CustodianReleaseError(
                    "replacement holdout purpose must be evaluation or replay"
                )
            executor = _actor(
                consume_executor_id, "holdout executor"
            )
            custodian = _dag_cid(
                (
                    receipt.custodian_id
                    if consume_custodian_id is None
                    else consume_custodian_id
                ),
                "holdout custodian",
            )
            if (
                executor != receipt.executor_id
                or custodian != receipt.custodian_id
            ):
                raise CustodianReleaseError(
                    "G241 release does not authorize this executor or "
                    "custodian"
                )
            grant = _append_locked_access_event(
                access_descriptor,
                seal=canonical_seal,
                authorization=canonical_authorization,
                g241_release_receipt_cid=str(receipt.receipt_cid),
                purpose=purpose,
                executor_id=executor,
                event="access_granted",
            )
            try:
                tombstone = _append_locked_release_consumption(
                    ledger_descriptor,
                    trust_root=trust_root,
                    release_receipt=receipt,
                    access_grant=grant,
                    access_ledger_file_identity_cid=(
                        access_file_identity_cid
                    ),
                    purpose=purpose,
                    executor_id=executor,
                    custodian_id=custodian,
                )
            except Exception:
                _append_locked_access_event(
                    access_descriptor,
                    seal=canonical_seal,
                    authorization=canonical_authorization,
                    g241_release_receipt_cid=str(
                        receipt.receipt_cid
                    ),
                    purpose=purpose,
                    executor_id=executor,
                    event="custody_release_failed",
                )
                raise
            transaction = G241CustodyAccessTransactionV1(
                release_receipt=receipt,
                grant_receipt=grant,
                consumption_tombstone=tombstone,
                _descriptor=access_descriptor,
                _release_descriptor=ledger_descriptor,
                _seal=canonical_seal,
                _authorization=canonical_authorization,
                _purpose=purpose,
                _executor_id=executor,
                _repo_root=root,
                _git_executable_path=Path(
                    trust_root.git_executable_path
                ),
                _git_executable_cid=trust_root.git_executable_cid,
                _source=current,
                _access_ledger_path=Path(access_ledger_path),
                _release_ledger_path=Path(ledger_path),
            )

        try:
            yield receipt, transaction
        finally:
            if (
                transaction is not None
                and transaction.terminal_receipt is None
            ):
                transaction.record_custody_failure()
            final_source = _inspect_current_source(
                root,
                git_executable_path=Path(
                    trust_root.git_executable_path
                ),
                expected_git_executable_cid=(
                    trust_root.git_executable_cid
                ),
            )
            if not _same_current_source(current, final_source):
                raise CustodianReleaseError(
                    "source changed during the locked G241 custody "
                    "transaction"
                )
            _revalidate_private_path(
                access_descriptor,
                Path(access_ledger_path),
                repo_root=root,
                field_name="replacement access ledger",
            )
            _revalidate_private_path(
                ledger_descriptor,
                Path(ledger_path),
                repo_root=root,
                field_name="custodian release ledger",
            )
    finally:
        for descriptor in (
            ledger_descriptor,
            access_descriptor,
            source_lock,
        ):
            if descriptor >= 0:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)


def load_and_validate_g241_release_receipt_v1(
    *,
    receipt_cid: str,
    ledger_path: Path,
    access_ledger_path: Path,
    seal: ReplacementHoldoutSeal,
    authorization: G232ReplacementHoldoutAuthorization,
    authority_path: Path,
    trusted_authority_cid: str,
    validator_attestation_path: Path,
    trusted_validator_attestation_cid: str,
    custodian_trust_root_path: Path,
    trusted_custodian_trust_root_cid: str,
    repo_root: Path,
) -> G241ExternallyGovernedCustodianReleaseReceiptV1:
    """Inspect the current G241 head without granting holdout access.

    This read-only inspection is not a custody authorization.  Callers that
    release sealed bytes must use :func:`consume_g241_release_for_access_v1`
    so validation, the single-use grant, custody, and the terminal outcome
    share one lock scope.
    """

    with _locked_g241_release_receipt_v1(
        receipt_cid=receipt_cid,
        ledger_path=ledger_path,
        access_ledger_path=access_ledger_path,
        seal=seal,
        authorization=authorization,
        authority_path=authority_path,
        trusted_authority_cid=trusted_authority_cid,
        validator_attestation_path=validator_attestation_path,
        trusted_validator_attestation_cid=(
            trusted_validator_attestation_cid
        ),
        custodian_trust_root_path=custodian_trust_root_path,
        trusted_custodian_trust_root_cid=(
            trusted_custodian_trust_root_cid
        ),
        repo_root=repo_root,
    ) as (receipt, transaction):
        if transaction is not None:  # pragma: no cover - invariant
            raise CustodianReleaseError(
                "read-only G241 validation unexpectedly granted access"
            )
        return receipt


@contextmanager
def consume_g241_release_for_access_v1(
    *,
    receipt_cid: str,
    ledger_path: Path,
    access_ledger_path: Path,
    seal: ReplacementHoldoutSeal,
    authorization: G232ReplacementHoldoutAuthorization,
    authority_path: Path,
    trusted_authority_cid: str,
    validator_attestation_path: Path,
    trusted_validator_attestation_cid: str,
    custodian_trust_root_path: Path,
    trusted_custodian_trust_root_cid: str,
    repo_root: Path,
    purpose: str,
    executor_id: str,
    custodian_id: str | None = None,
) -> Iterator[G241CustodyAccessTransactionV1]:
    """Atomically consume one G241 head and hold its locks through custody."""

    with _locked_g241_release_receipt_v1(
        receipt_cid=receipt_cid,
        ledger_path=ledger_path,
        access_ledger_path=access_ledger_path,
        seal=seal,
        authorization=authorization,
        authority_path=authority_path,
        trusted_authority_cid=trusted_authority_cid,
        validator_attestation_path=validator_attestation_path,
        trusted_validator_attestation_cid=(
            trusted_validator_attestation_cid
        ),
        custodian_trust_root_path=custodian_trust_root_path,
        trusted_custodian_trust_root_cid=(
            trusted_custodian_trust_root_cid
        ),
        repo_root=repo_root,
        consume_purpose=purpose,
        consume_executor_id=executor_id,
        consume_custodian_id=custodian_id,
    ) as (_, transaction):
        if transaction is None:  # pragma: no cover - invariant
            raise CustodianReleaseError(
                "G241 consumption did not create an access transaction"
            )
        yield transaction


__all__ = [
    "G239_EXTERNAL_ARTIFACT_SCHEMA",
    "G239_EXTERNAL_AUTHORITY_SCHEMA",
    "G239_EXTERNAL_GITLINK_SCHEMA",
    "G239_EXTERNAL_RECEIPT_SCHEMA",
    "G239_EXTERNAL_REQUIREMENT_SCHEMA",
    "G239_EXTERNAL_SOURCE_SCHEMA",
    "G241_ACTIVITY_KEYS",
    "G241_CUSTODIAN_TRUST_ROOT_SCHEMA_V1",
    "G241_ACCESS_LEDGER_SNAPSHOT_SCHEMA_V1",
    "G241_EXTERNAL_ARTIFACT_KEYS",
    "G241_EXTERNAL_ARTIFACT_SET_SCHEMA_V1",
    "G241_EXTERNAL_PROJECTION_SCHEMA_V1",
    "G241_GOVERNED_EVIDENCE_TERM",
    "G241_GOVERNED_GOAL_ID",
    "G241_GIT_EXECUTABLE_IDENTITY_SCHEMA_V1",
    "G241_LEDGER_FILE_IDENTITY_SCHEMA_V1",
    "G241_PARENT_KEYS",
    "G241_RELEASE_CONSUMPTION_TOMBSTONE_SCHEMA_V1",
    "G241_RELEASE_LEDGER_AUTHORITY_SCHEMA_V1",
    "G241_RELEASE_RECEIPT_SCHEMA_V1",
    "G241_RELEASE_REQUEST_SCHEMA_V1",
    "G241_SOURCE_INDEX_SCHEMA_V1",
    "G241_UPSTREAM_AUTHORITY_ROLES",
    "G241_VALIDATOR_ATTESTATION_SCHEMA_V1",
    "G241_VALIDATOR_CLAIM_SCHEMA_V1",
    "G241_VALIDATOR_KEY_SCHEMA_V1",
    "G241_VALIDATOR_SIGNED_PAYLOAD_SCHEMA_V1",
    "CustodianReleaseError",
    "G241CustodianReleaseRequestV1",
    "G241CustodyAccessTransactionV1",
    "G241CustodianTrustRootV1",
    "G241ExternallyGovernedCustodianReleaseReceiptV1",
    "G241G239ExternalProjectionV1",
    "G241PersistedBatchSourceV1",
    "G241ReleaseConsumptionTombstoneV1",
    "G241ReleaseLedgerRecordV1",
    "G241SourceDecisionIndexV1",
    "G241SourceReplayResultV1",
    "authorize_g241_custodian_release_v1",
    "consume_g241_release_for_access_v1",
    "derive_g232_shortlist_from_validated_gates_v1",
    "evaluate_g239_for_g241_v1",
    "g241_artifact_slot_cid",
    "g241_git_tree_cid",
    "g241_git_executable_cid_v1",
    "g241_release_ledger_authority_cid_v1",
    "load_g241_custodian_trust_root_v1",
    "load_and_validate_g241_release_receipt_v1",
    "recompute_g241_source_chain_v1",
    "validate_g232_proposal_against_source_replay_v1",
    "zero_g241_activity",
]
