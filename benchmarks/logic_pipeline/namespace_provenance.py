"""Canonical runtime namespace provenance for HSSL-G240.

The revision-2 benchmark must not treat a caller-selected CID as proof that a
process group, state directory, output directory, or physical cache namespace
was actually isolated.  This module defines a path-free preregistration and
receipt boundary:

* the policy is derived from exact source, environment, run-plan, job, route,
  and cache-mode identities;
* an execution receipt binds the full runtime evidence to those preimages and
  records terminal process/state/output/cache lifecycle observations; and
* an evidence set source-replays every receipt against the scheduled plans and
  full ``CausalRuntimeEvidenceV2`` values.

Only CIDs and public coordinate identifiers enter these records.  Filesystem
paths, PIDs, source text, reviewed labels, proof obligations, and model output
are deliberately excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Final, Mapping, Self, Sequence

from .ablation import AblationPlan, ScheduledCase
from .causal_runtime import (
    CausalRuntimeEvidenceV2,
    validate_causal_runtime_evidence_v2,
)
from .content_addressing import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)
from .contracts import CacheMode, Split, canonical_json
from .source_bootstrap_contract import (
    G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2,
)
from .variants import get_causal_proof_variant_profile


G240_NAMESPACE_CONTEXT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "runtime-namespace-context.v2"
)
G240_NAMESPACE_PREIMAGE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "runtime-namespace-preimage.v2"
)
G240_JOB_NAMESPACE_PLAN_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "runtime-job-namespace-plan.v2"
)
G240_NAMESPACE_POLICY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "runtime-namespace-policy.v2"
)
G240_CACHE_KEY_OBSERVATION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "runtime-cache-key-observation.v2"
)
G240_CACHE_NAMESPACE_SET_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "physical-cache-namespace-set.v2"
)
G240_RUNTIME_NAMESPACE_RECEIPT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "runtime-namespace-receipt.v2"
)
G240_RUNTIME_NAMESPACE_EVIDENCE_SET_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "runtime-namespace-evidence-set.v2"
)
G240_REPLAY_NAMESPACE_CONTEXT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "detached-replay-namespace-context.v2"
)
G240_REPLAY_NAMESPACE_RECEIPT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "detached-replay-namespace-receipt.v2"
)
G240_REPLAY_WORKTREE_PROJECTION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "detached-replay-worktree-projection.v2"
)
G240_RECURSIVE_GITLINKS_PROJECTION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "recursive-gitlinks-projection.v2"
)
G240_REPLAY_ORCHESTRATION_RECEIPT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "detached-replay-orchestration-receipt.v2"
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SPLITS: Final = frozenset({Split.PILOT.value, Split.DEVELOPMENT.value})
_CACHE_MODES: Final = frozenset(
    {CacheMode.COLD.value, CacheMode.WARM.value}
)
_JOB_NAMESPACE_KINDS: Final = ("process_group", "state", "output")


class RuntimeNamespaceProvenanceError(ValueError):
    """Raised when a G240 namespace claim is opaque, stale, or incomplete."""


def _g240_evidence_boundary_text() -> str:
    """Describe the unfinished G240 implementation boundary internally."""

    return (
        "CID-native source-recomputed process state output and physical "
        "cache namespace preimages with terminal lifecycle receipts"
    )


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise RuntimeNamespaceProvenanceError(
                "G240 DAG-JSON objects require string keys"
            )
        return {
            str(key): _plain(member)
            for key, member in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_plain(member) for member in value]
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise RuntimeNamespaceProvenanceError(
        f"G240 value is not DAG-JSON: {type(value).__name__}"
    )


def _freeze(value: object) -> object:
    plain = _plain(value)
    if isinstance(plain, dict):
        return MappingProxyType(
            {
                key: _freeze(member)
                for key, member in plain.items()
            }
        )
    if isinstance(plain, list):
        return tuple(_freeze(member) for member in plain)
    return plain


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise RuntimeNamespaceProvenanceError(
            f"{field} must be an object with string keys"
        )
    return value


def _exact(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    if set(value) != expected:
        raise RuntimeNamespaceProvenanceError(
            f"{field} fields changed: "
            f"missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def _cid(value: object, field: str) -> str:
    try:
        return validate_cid(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeNamespaceProvenanceError(
            f"{field} must be a canonical CIDv1/base32/sha2-256 value"
        ) from exc


def _safe_id(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not _SAFE_ID.fullmatch(value)
        or value in {".", ".."}
    ):
        raise RuntimeNamespaceProvenanceError(
            f"{field} must be a safe nonempty identifier"
        )
    return value


def _plan_cid(plan: AblationPlan) -> str:
    if not isinstance(plan, AblationPlan):
        raise RuntimeNamespaceProvenanceError(
            "G240 requires typed AblationPlan values"
        )
    return cid_for_dag_json(_plain(plan.to_dict()))


def _namespace_context_cid(
    *,
    source_commit_cid: str,
    recursive_gitlinks_cid: str,
    environment_cid: str,
    runtime_orchestration_policy_cid: str,
    run_id: str,
    plan_cids: Sequence[str],
) -> str:
    return cid_for_dag_json(
        {
            "schema": G240_NAMESPACE_CONTEXT_SCHEMA_V2,
            "source_commit_cid": source_commit_cid,
            "recursive_gitlinks_cid": recursive_gitlinks_cid,
            "environment_cid": environment_cid,
            "runtime_orchestration_policy_cid": (
                runtime_orchestration_policy_cid
            ),
            "run_id": run_id,
            "plan_cids": list(plan_cids),
        }
    )


def _job_namespace_cid(
    *,
    context_cid: str,
    kind: str,
    plan_cid: str,
    run_id: str,
    split: str,
    job_id: str,
    case_id: str,
    variant_id: str,
    cache_mode: str,
) -> str:
    if kind not in _JOB_NAMESPACE_KINDS:
        raise RuntimeNamespaceProvenanceError(
            f"unsupported G240 job namespace kind: {kind}"
        )
    return cid_for_dag_json(
        {
            "schema": G240_NAMESPACE_PREIMAGE_SCHEMA_V2,
            "context_cid": context_cid,
            "kind": kind,
            "plan_cid": plan_cid,
            "run_id": run_id,
            "split": split,
            "job_id": job_id,
            "case_id": case_id,
            "variant_id": variant_id,
            "stage": "job",
            "cache_mode": cache_mode,
        }
    )


def _cache_namespace_cid(
    *,
    context_cid: str,
    plan_cid: str,
    run_id: str,
    split: str,
    variant_id: str,
    stage: str,
    cache_mode: str,
) -> str:
    """Address one shareable physical cache namespace without a path.

    Case and job IDs are intentionally absent: cache reuse within one frozen
    variant/split/mode/stage is required to measure warm execution.  The plan,
    run, variant, stage, and cache mode still make every treatment namespace
    source-recomputable and keep cold/warm roots disjoint.
    """

    return cid_for_dag_json(
        {
            "schema": G240_NAMESPACE_PREIMAGE_SCHEMA_V2,
            "context_cid": context_cid,
            "kind": "physical_cache",
            "plan_cid": plan_cid,
            "run_id": run_id,
            "split": split,
            "variant_id": variant_id,
            "stage": stage,
            "cache_mode": cache_mode,
        }
    )


def g240_cache_namespace_set_cid(
    cache_namespace_cids: Mapping[str, str],
) -> str:
    """Address one exact stage-to-physical-cache namespace projection."""

    caches = {
        _safe_id(stage, "cache stage"): _cid(
            value, f"cache_namespace_cids.{stage}"
        )
        for stage, value in _mapping(
            cache_namespace_cids, "cache_namespace_cids"
        ).items()
    }
    if not caches:
        raise RuntimeNamespaceProvenanceError(
            "cache namespace set must not be empty"
        )
    return cid_for_dag_json(
        {
            "schema": G240_CACHE_NAMESPACE_SET_SCHEMA_V2,
            "cache_namespace_cids": {
                stage: caches[stage] for stage in sorted(caches)
            },
        }
    )


def g240_recursive_gitlinks_cid(values: Sequence[object]) -> str:
    """Address the exact bounded Gitlink inventory used by replay.

    The projection contains repository-relative Gitlink coordinates only.
    Host filesystem paths and mutable checkout locations never enter it.
    """

    try:
        from .source_reconciliation import GitlinkIdentity

        records = tuple(
            item
            if isinstance(item, GitlinkIdentity)
            else GitlinkIdentity.from_dict(item)
            for item in values
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeNamespaceProvenanceError(
            "G240 recursive Gitlink projection is malformed"
        ) from exc
    if records != tuple(sorted(records)) or len(records) != len(set(records)):
        raise RuntimeNamespaceProvenanceError(
            "G240 recursive Gitlink projection must be sorted and unique"
        )
    return cid_for_dag_json(
        {
            "schema": G240_RECURSIVE_GITLINKS_PROJECTION_SCHEMA_V2,
            "gitlinks": [record.to_dict() for record in records],
        }
    )


@dataclass(frozen=True, slots=True)
class G240JobNamespacePlanV2:
    """Canonical pre-execution namespaces for one scheduled job."""

    context_cid: str
    plan_cid: str
    run_id: str
    split: str
    job_id: str
    case_id: str
    variant_id: str
    cache_mode: str
    stages: tuple[str, ...]
    process_namespace_cid: str
    state_namespace_cid: str
    output_namespace_cid: str
    cache_namespace_cids: Mapping[str, str]
    schema: str = G240_JOB_NAMESPACE_PLAN_SCHEMA_V2
    coordinate_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G240_JOB_NAMESPACE_PLAN_SCHEMA_V2:
            raise RuntimeNamespaceProvenanceError(
                "unsupported G240 job namespace-plan schema"
            )
        for field in ("context_cid", "plan_cid"):
            object.__setattr__(
                self, field, _cid(getattr(self, field), field)
            )
        for field in ("run_id", "job_id", "case_id", "variant_id"):
            object.__setattr__(
                self, field, _safe_id(getattr(self, field), field)
            )
        if self.split not in _SPLITS:
            raise RuntimeNamespaceProvenanceError(
                "G240 job split must be pilot or development"
            )
        if self.cache_mode not in _CACHE_MODES:
            raise RuntimeNamespaceProvenanceError(
                "G240 job cache mode must be cold or warm"
            )
        expected_stages = tuple(
            stage.value
            for stage in get_causal_proof_variant_profile(
                self.variant_id
            ).effective_stages
        )
        stages = tuple(self.stages)
        if stages != expected_stages:
            raise RuntimeNamespaceProvenanceError(
                "G240 job stages differ from the causal route"
            )
        object.__setattr__(self, "stages", stages)
        for field, kind in (
            ("process_namespace_cid", "process_group"),
            ("state_namespace_cid", "state"),
            ("output_namespace_cid", "output"),
        ):
            expected = _job_namespace_cid(
                context_cid=self.context_cid,
                kind=kind,
                plan_cid=self.plan_cid,
                run_id=self.run_id,
                split=self.split,
                job_id=self.job_id,
                case_id=self.case_id,
                variant_id=self.variant_id,
                cache_mode=self.cache_mode,
            )
            observed = _cid(getattr(self, field), field)
            if observed != expected:
                raise RuntimeNamespaceProvenanceError(
                    f"{field} does not derive from the canonical preimage"
                )
            object.__setattr__(self, field, observed)
        cache_values = _mapping(
            self.cache_namespace_cids,
            "cache_namespace_cids",
        )
        if set(cache_values) != set(stages):
            raise RuntimeNamespaceProvenanceError(
                "G240 cache namespace map must cover every causal stage"
            )
        caches: dict[str, str] = {}
        for stage in stages:
            expected = _cache_namespace_cid(
                context_cid=self.context_cid,
                plan_cid=self.plan_cid,
                run_id=self.run_id,
                split=self.split,
                variant_id=self.variant_id,
                stage=stage,
                cache_mode=self.cache_mode,
            )
            observed = _cid(
                cache_values[stage],
                f"cache_namespace_cids.{stage}",
            )
            if observed != expected:
                raise RuntimeNamespaceProvenanceError(
                    "physical cache namespace does not derive from its "
                    "variant/stage/cache-mode preimage"
                )
            caches[stage] = observed
        object.__setattr__(
            self,
            "cache_namespace_cids",
            MappingProxyType(caches),
        )
        expected_coordinate = cid_for_dag_json(self.identity_payload())
        if self.coordinate_cid is None:
            object.__setattr__(
                self, "coordinate_cid", expected_coordinate
            )
        elif _cid(self.coordinate_cid, "coordinate_cid") != expected_coordinate:
            raise RuntimeNamespaceProvenanceError(
                "G240 job namespace coordinate CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "context_cid": self.context_cid,
            "plan_cid": self.plan_cid,
            "run_id": self.run_id,
            "split": self.split,
            "job_id": self.job_id,
            "case_id": self.case_id,
            "variant_id": self.variant_id,
            "cache_mode": self.cache_mode,
            "stages": list(self.stages),
            "process_namespace_cid": self.process_namespace_cid,
            "state_namespace_cid": self.state_namespace_cid,
            "output_namespace_cid": self.output_namespace_cid,
            "cache_namespace_cids": dict(self.cache_namespace_cids),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "coordinate_cid": self.coordinate_cid,
        }

    @classmethod
    def create(
        cls,
        *,
        context_cid: str,
        plan_cid: str,
        plan: AblationPlan,
        job: ScheduledCase,
    ) -> Self:
        stages = tuple(
            stage.value
            for stage in get_causal_proof_variant_profile(
                job.variant_id
            ).effective_stages
        )
        common = {
            "context_cid": context_cid,
            "plan_cid": plan_cid,
            "run_id": plan.run_id,
            "split": plan.split.value,
            "job_id": job.job_id,
            "case_id": job.case.case_id,
            "variant_id": job.variant_id,
            "cache_mode": job.cache_mode.value,
        }
        return cls(
            **common,
            stages=stages,
            process_namespace_cid=_job_namespace_cid(
                **common, kind="process_group"
            ),
            state_namespace_cid=_job_namespace_cid(
                **common, kind="state"
            ),
            output_namespace_cid=_job_namespace_cid(
                **common, kind="output"
            ),
            cache_namespace_cids={
                stage: _cache_namespace_cid(
                    context_cid=context_cid,
                    plan_cid=plan_cid,
                    run_id=plan.run_id,
                    split=plan.split.value,
                    variant_id=job.variant_id,
                    stage=stage,
                    cache_mode=job.cache_mode.value,
                )
                for stage in stages
            },
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G240 job namespace plan")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G240 job namespace plan",
        )
        stages = data["stages"]
        if not isinstance(stages, list):
            raise RuntimeNamespaceProvenanceError(
                "G240 job stages must be an array"
            )
        return cls(
            **{
                **data,
                "stages": tuple(stages),
                "cache_namespace_cids": _mapping(
                    data["cache_namespace_cids"],
                    "cache_namespace_cids",
                ),
            }
        )  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class G240NamespacePolicyV2:
    """Frozen namespace derivation policy for one revision-2 run."""

    source_commit_cid: str
    recursive_gitlinks_cid: str
    environment_cid: str
    runtime_orchestration_policy_cid: str
    run_id: str
    plan_cids: tuple[str, ...]
    context_cid: str
    namespace_authority_cid: str
    jobs: tuple[G240JobNamespacePlanV2, ...]
    schema: str = G240_NAMESPACE_POLICY_SCHEMA_V2
    policy_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G240_NAMESPACE_POLICY_SCHEMA_V2:
            raise RuntimeNamespaceProvenanceError(
                "unsupported G240 namespace-policy schema"
            )
        for field in (
            "source_commit_cid",
            "recursive_gitlinks_cid",
            "environment_cid",
            "runtime_orchestration_policy_cid",
            "context_cid",
            "namespace_authority_cid",
        ):
            object.__setattr__(
                self, field, _cid(getattr(self, field), field)
            )
        object.__setattr__(self, "run_id", _safe_id(self.run_id, "run_id"))
        plans = tuple(_cid(value, "plan_cid") for value in self.plan_cids)
        if not plans or plans != tuple(sorted(plans)) or len(set(plans)) != len(
            plans
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 plan CIDs must be nonempty, sorted, and unique"
            )
        object.__setattr__(self, "plan_cids", plans)
        expected_context = _namespace_context_cid(
            source_commit_cid=self.source_commit_cid,
            recursive_gitlinks_cid=self.recursive_gitlinks_cid,
            environment_cid=self.environment_cid,
            runtime_orchestration_policy_cid=(
                self.runtime_orchestration_policy_cid
            ),
            run_id=self.run_id,
            plan_cids=plans,
        )
        if self.context_cid != expected_context:
            raise RuntimeNamespaceProvenanceError(
                "G240 namespace context differs from the frozen source/run"
            )
        jobs = tuple(
            item
            if isinstance(item, G240JobNamespacePlanV2)
            else G240JobNamespacePlanV2.from_dict(item)
            for item in self.jobs
        )
        order = tuple(
            (item.plan_cid, item.job_id) for item in jobs
        )
        if (
            not jobs
            or order != tuple(sorted(order))
            or len(order) != len(set(order))
            or any(
                item.context_cid != self.context_cid
                or item.run_id != self.run_id
                or item.plan_cid not in plans
                for item in jobs
            )
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 namespace jobs are incomplete, unsorted, or foreign"
            )
        for field in (
            "process_namespace_cid",
            "state_namespace_cid",
            "output_namespace_cid",
        ):
            values = [getattr(item, field) for item in jobs]
            if len(values) != len(set(values)):
                raise RuntimeNamespaceProvenanceError(
                    f"G240 {field} values must be unique per job"
                )
        cache_coordinates: dict[
            tuple[str, str, str, str, str], str
        ] = {}
        for item in jobs:
            for stage, cache_cid in item.cache_namespace_cids.items():
                key = (
                    item.plan_cid,
                    item.split,
                    item.variant_id,
                    stage,
                    item.cache_mode,
                )
                previous = cache_coordinates.setdefault(key, cache_cid)
                if previous != cache_cid:
                    raise RuntimeNamespaceProvenanceError(
                        "G240 cache namespace changed within one coordinate"
                    )
        by_treatment: dict[
            tuple[str, str, str, str], dict[str, str]
        ] = {}
        for (
            plan_cid,
            split,
            variant_id,
            stage,
            cache_mode,
        ), cache_cid in cache_coordinates.items():
            by_treatment.setdefault(
                (plan_cid, split, variant_id, stage), {}
            )[cache_mode] = cache_cid
        if any(
            len(set(modes.values())) != len(modes)
            for modes in by_treatment.values()
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 cold and warm physical cache namespaces collide"
            )
        object.__setattr__(self, "jobs", jobs)
        expected_policy = cid_for_dag_json(self.identity_payload())
        if self.policy_cid is None:
            object.__setattr__(self, "policy_cid", expected_policy)
        elif _cid(self.policy_cid, "policy_cid") != expected_policy:
            raise RuntimeNamespaceProvenanceError(
                "G240 namespace policy CID changed"
            )

    @property
    def job_map(self) -> Mapping[tuple[str, str], G240JobNamespacePlanV2]:
        return MappingProxyType(
            {
                (item.plan_cid, item.job_id): item
                for item in self.jobs
            }
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "source_commit_cid": self.source_commit_cid,
            "recursive_gitlinks_cid": self.recursive_gitlinks_cid,
            "environment_cid": self.environment_cid,
            "runtime_orchestration_policy_cid": (
                self.runtime_orchestration_policy_cid
            ),
            "run_id": self.run_id,
            "plan_cids": list(self.plan_cids),
            "context_cid": self.context_cid,
            "namespace_authority_cid": self.namespace_authority_cid,
            "jobs": [item.to_dict() for item in self.jobs],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "policy_cid": self.policy_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G240 namespace policy")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G240 namespace policy",
        )
        plan_cids = data["plan_cids"]
        jobs = data["jobs"]
        if not isinstance(plan_cids, list) or not isinstance(jobs, list):
            raise RuntimeNamespaceProvenanceError(
                "G240 policy plan/job fields must be arrays"
            )
        return cls(
            **{
                **data,
                "plan_cids": tuple(plan_cids),
                "jobs": tuple(
                    G240JobNamespacePlanV2.from_dict(item)
                    for item in jobs
                ),
            }
        )  # type: ignore[arg-type]


def build_g240_namespace_policy_v2(
    plans: Sequence[AblationPlan],
    *,
    source_commit_cid: str,
    recursive_gitlinks_cid: str,
    environment_cid: str,
    runtime_orchestration_policy_cid: str,
    namespace_authority_cid: str,
) -> G240NamespacePolicyV2:
    """Derive all path-free namespace identities before execution."""

    restored = tuple(
        AblationPlan.from_dict(plan.to_dict())
        if isinstance(plan, AblationPlan)
        else None
        for plan in plans
    )
    if not restored or any(plan is None for plan in restored):
        raise RuntimeNamespaceProvenanceError(
            "G240 policy requires one or more typed plans"
        )
    typed = tuple(plan for plan in restored if plan is not None)
    run_ids = {plan.run_id for plan in typed}
    environments = {plan.environment_sha256 for plan in typed}
    if (
        len(run_ids) != 1
        or None in environments
        or len(environments) != 1
        or any(
            plan.split.value not in _SPLITS
            or plan.holdout_access_log_id is not None
            for plan in typed
        )
    ):
        raise RuntimeNamespaceProvenanceError(
            "G240 plans must share one pinned non-holdout run/environment"
        )
    keyed = sorted((_plan_cid(plan), plan) for plan in typed)
    plan_cids = tuple(key for key, _plan in keyed)
    if len(plan_cids) != len(set(plan_cids)):
        raise RuntimeNamespaceProvenanceError(
            "G240 plans must have distinct content identities"
        )
    source_cid = _cid(source_commit_cid, "source_commit_cid")
    gitlinks_cid = _cid(
        recursive_gitlinks_cid, "recursive_gitlinks_cid"
    )
    frozen_environment_cid = _cid(environment_cid, "environment_cid")
    orchestration_policy_cid = _cid(
        runtime_orchestration_policy_cid,
        "runtime_orchestration_policy_cid",
    )
    run_id = next(iter(run_ids))
    context_cid = _namespace_context_cid(
        source_commit_cid=source_cid,
        recursive_gitlinks_cid=gitlinks_cid,
        environment_cid=frozen_environment_cid,
        runtime_orchestration_policy_cid=orchestration_policy_cid,
        run_id=run_id,
        plan_cids=plan_cids,
    )
    jobs = tuple(
        sorted(
            (
                G240JobNamespacePlanV2.create(
                    context_cid=context_cid,
                    plan_cid=plan_cid,
                    plan=plan,
                    job=job,
                )
                for plan_cid, plan in keyed
                for job in plan.jobs
            ),
            key=lambda item: (item.plan_cid, item.job_id),
        )
    )
    return G240NamespacePolicyV2(
        source_commit_cid=source_cid,
        recursive_gitlinks_cid=gitlinks_cid,
        environment_cid=frozen_environment_cid,
        runtime_orchestration_policy_cid=orchestration_policy_cid,
        run_id=run_id,
        plan_cids=plan_cids,
        context_cid=context_cid,
        namespace_authority_cid=namespace_authority_cid,
        jobs=jobs,
    )


def validate_g240_namespace_policy_v2(
    value: object,
    plans: Sequence[AblationPlan],
) -> G240NamespacePolicyV2:
    """Recompute a policy from the exact plans and reject copied identities."""

    policy = (
        value
        if isinstance(value, G240NamespacePolicyV2)
        else G240NamespacePolicyV2.from_dict(value)
    )
    rebuilt = build_g240_namespace_policy_v2(
        plans,
        source_commit_cid=policy.source_commit_cid,
        recursive_gitlinks_cid=policy.recursive_gitlinks_cid,
        environment_cid=policy.environment_cid,
        runtime_orchestration_policy_cid=(
            policy.runtime_orchestration_policy_cid
        ),
        namespace_authority_cid=policy.namespace_authority_cid,
    )
    if _plain(policy.to_dict()) != _plain(rebuilt.to_dict()):
        raise RuntimeNamespaceProvenanceError(
            "G240 namespace policy differs from source-recomputed plans"
        )
    return rebuilt


def _cache_key_cids_for_stage_map(
    *,
    evidence: CausalRuntimeEvidenceV2,
    stages: Sequence[str],
    cache_namespace_cids: Mapping[str, str],
) -> Mapping[str, tuple[str, ...]]:
    stage_records = tuple(evidence.case_result.stages)
    observed_stages = tuple(stage.stage.value for stage in stage_records)
    if observed_stages != tuple(stages):
        raise RuntimeNamespaceProvenanceError(
            "G240 runtime stages differ from the preregistered causal route"
        )
    result: dict[str, tuple[str, ...]] = {}
    for stage in stage_records:
        stage_name = stage.stage.value
        identity = stage.provenance.effective_identity
        logical_namespace = identity.get("cache_namespace")
        logical_key = identity.get("cache_key")
        if (logical_namespace is None) != (logical_key is None):
            raise RuntimeNamespaceProvenanceError(
                f"{stage_name} cache namespace/key observation is partial"
            )
        if logical_namespace is None:
            result[stage_name] = ()
            continue
        if (
            not isinstance(logical_namespace, str)
            or not logical_namespace
            or not isinstance(logical_key, str)
            or not logical_key
        ):
            raise RuntimeNamespaceProvenanceError(
                f"{stage_name} cache namespace/key must be nonempty strings"
            )
        key_cid = cid_for_dag_json(
            {
                "schema": G240_CACHE_KEY_OBSERVATION_SCHEMA_V2,
                "runtime_evidence_cid": evidence.receipt_cid,
                "stage_record_cid": cid_for_dag_json(
                    _plain(stage.to_dict())
                ),
                "stage": stage_name,
                "physical_cache_namespace_cid": (
                    cache_namespace_cids[stage_name]
                ),
                "logical_cache_namespace": logical_namespace,
                "logical_cache_key": logical_key,
            }
        )
        result[stage_name] = (key_cid,)
    return MappingProxyType(result)


def _cache_key_cids(
    *,
    evidence: CausalRuntimeEvidenceV2,
    namespace_plan: G240JobNamespacePlanV2,
) -> Mapping[str, tuple[str, ...]]:
    return _cache_key_cids_for_stage_map(
        evidence=evidence,
        stages=namespace_plan.stages,
        cache_namespace_cids=namespace_plan.cache_namespace_cids,
    )


@dataclass(frozen=True, slots=True)
class G240RuntimeNamespaceReceiptV2:
    """Observed namespace and lifecycle evidence for one runtime job."""

    policy_cid: str
    plan_cid: str
    coordinate_cid: str
    job_id: str
    runtime_evidence_cid: str
    process_namespace_cid: str
    state_namespace_cid: str
    output_namespace_cid: str
    cache_namespace_cids: Mapping[str, str]
    cache_key_cids: Mapping[str, tuple[str, ...]]
    executor_identity_cid: str
    observer_identity_cid: str
    process_group_started: bool
    process_group_reaped: bool
    active_process_count_after_reap: int
    state_namespace_created_exclusive: bool
    state_namespace_finalized: bool
    output_namespace_created_exclusive: bool
    output_namespace_finalized: bool
    cache_namespaces_mounted: bool
    holdout_accessed: bool
    schema: str = G240_RUNTIME_NAMESPACE_RECEIPT_SCHEMA_V2
    receipt_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G240_RUNTIME_NAMESPACE_RECEIPT_SCHEMA_V2:
            raise RuntimeNamespaceProvenanceError(
                "unsupported G240 runtime namespace-receipt schema"
            )
        for field in (
            "policy_cid",
            "plan_cid",
            "coordinate_cid",
            "runtime_evidence_cid",
            "process_namespace_cid",
            "state_namespace_cid",
            "output_namespace_cid",
            "executor_identity_cid",
            "observer_identity_cid",
        ):
            object.__setattr__(
                self, field, _cid(getattr(self, field), field)
            )
        object.__setattr__(self, "job_id", _safe_id(self.job_id, "job_id"))
        caches = {
            _safe_id(stage, "cache stage"): _cid(
                value, f"cache_namespace_cids.{stage}"
            )
            for stage, value in _mapping(
                self.cache_namespace_cids,
                "cache_namespace_cids",
            ).items()
        }
        keys: dict[str, tuple[str, ...]] = {}
        for stage, values in _mapping(
            self.cache_key_cids,
            "cache_key_cids",
        ).items():
            _safe_id(stage, "cache-key stage")
            if not isinstance(values, (tuple, list)):
                raise RuntimeNamespaceProvenanceError(
                    f"cache_key_cids.{stage} must be an array"
                )
            normalized = tuple(
                _cid(value, f"cache_key_cids.{stage}[]")
                for value in values
            )
            if (
                normalized != tuple(sorted(normalized))
                or len(normalized) != len(set(normalized))
            ):
                raise RuntimeNamespaceProvenanceError(
                    f"cache_key_cids.{stage} must be sorted and unique"
                )
            keys[stage] = normalized
        if set(caches) != set(keys):
            raise RuntimeNamespaceProvenanceError(
                "G240 cache namespace and key stage maps differ"
            )
        object.__setattr__(
            self, "cache_namespace_cids", MappingProxyType(caches)
        )
        object.__setattr__(
            self, "cache_key_cids", MappingProxyType(keys)
        )
        for field in (
            "process_group_started",
            "process_group_reaped",
            "state_namespace_created_exclusive",
            "state_namespace_finalized",
            "output_namespace_created_exclusive",
            "output_namespace_finalized",
            "cache_namespaces_mounted",
            "holdout_accessed",
        ):
            if type(getattr(self, field)) is not bool:
                raise RuntimeNamespaceProvenanceError(
                    f"{field} must be an observed boolean"
                )
        if (
            type(self.active_process_count_after_reap) is not int
            or self.active_process_count_after_reap < 0
        ):
            raise RuntimeNamespaceProvenanceError(
                "active_process_count_after_reap must be nonnegative"
            )
        if self.executor_identity_cid == self.observer_identity_cid:
            raise RuntimeNamespaceProvenanceError(
                "G240 execution and namespace observation authorities differ"
            )
        if not all(
            (
                self.process_group_started,
                self.process_group_reaped,
                self.active_process_count_after_reap == 0,
                self.state_namespace_created_exclusive,
                self.state_namespace_finalized,
                self.output_namespace_created_exclusive,
                self.output_namespace_finalized,
                self.cache_namespaces_mounted,
                not self.holdout_accessed,
            )
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 runtime namespace lifecycle is incomplete"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.receipt_cid is None:
            object.__setattr__(self, "receipt_cid", expected)
        elif _cid(self.receipt_cid, "receipt_cid") != expected:
            raise RuntimeNamespaceProvenanceError(
                "G240 runtime namespace receipt CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "policy_cid": self.policy_cid,
            "plan_cid": self.plan_cid,
            "coordinate_cid": self.coordinate_cid,
            "job_id": self.job_id,
            "runtime_evidence_cid": self.runtime_evidence_cid,
            "process_namespace_cid": self.process_namespace_cid,
            "state_namespace_cid": self.state_namespace_cid,
            "output_namespace_cid": self.output_namespace_cid,
            "cache_namespace_cids": dict(self.cache_namespace_cids),
            "cache_key_cids": {
                stage: list(values)
                for stage, values in self.cache_key_cids.items()
            },
            "executor_identity_cid": self.executor_identity_cid,
            "observer_identity_cid": self.observer_identity_cid,
            "process_group_started": self.process_group_started,
            "process_group_reaped": self.process_group_reaped,
            "active_process_count_after_reap": (
                self.active_process_count_after_reap
            ),
            "state_namespace_created_exclusive": (
                self.state_namespace_created_exclusive
            ),
            "state_namespace_finalized": self.state_namespace_finalized,
            "output_namespace_created_exclusive": (
                self.output_namespace_created_exclusive
            ),
            "output_namespace_finalized": self.output_namespace_finalized,
            "cache_namespaces_mounted": self.cache_namespaces_mounted,
            "holdout_accessed": self.holdout_accessed,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_cid": self.receipt_cid}

    @classmethod
    def create(
        cls,
        *,
        policy: G240NamespacePolicyV2,
        plan: AblationPlan,
        job: ScheduledCase,
        evidence: CausalRuntimeEvidenceV2,
        executor_identity_cid: str,
        observer_identity_cid: str,
        process_group_started: bool,
        process_group_reaped: bool,
        active_process_count_after_reap: int,
        state_namespace_created_exclusive: bool,
        state_namespace_finalized: bool,
        output_namespace_created_exclusive: bool,
        output_namespace_finalized: bool,
        cache_namespaces_mounted: bool,
        holdout_accessed: bool = False,
    ) -> Self:
        plan_cid = _plan_cid(plan)
        try:
            coordinate = policy.job_map[(plan_cid, job.job_id)]
        except KeyError as exc:
            raise RuntimeNamespaceProvenanceError(
                "G240 policy does not contain the runtime job"
            ) from exc
        restored = validate_causal_runtime_evidence_v2(evidence.to_dict())
        return cls(
            policy_cid=str(policy.policy_cid),
            plan_cid=plan_cid,
            coordinate_cid=str(coordinate.coordinate_cid),
            job_id=job.job_id,
            runtime_evidence_cid=restored.receipt_cid,
            process_namespace_cid=coordinate.process_namespace_cid,
            state_namespace_cid=coordinate.state_namespace_cid,
            output_namespace_cid=coordinate.output_namespace_cid,
            cache_namespace_cids=coordinate.cache_namespace_cids,
            cache_key_cids=_cache_key_cids(
                evidence=restored,
                namespace_plan=coordinate,
            ),
            executor_identity_cid=executor_identity_cid,
            observer_identity_cid=observer_identity_cid,
            process_group_started=process_group_started,
            process_group_reaped=process_group_reaped,
            active_process_count_after_reap=(
                active_process_count_after_reap
            ),
            state_namespace_created_exclusive=(
                state_namespace_created_exclusive
            ),
            state_namespace_finalized=state_namespace_finalized,
            output_namespace_created_exclusive=(
                output_namespace_created_exclusive
            ),
            output_namespace_finalized=output_namespace_finalized,
            cache_namespaces_mounted=cache_namespaces_mounted,
            holdout_accessed=holdout_accessed,
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G240 runtime namespace receipt")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G240 runtime namespace receipt",
        )
        return cls(
            **{
                **data,
                "cache_namespace_cids": _mapping(
                    data["cache_namespace_cids"],
                    "cache_namespace_cids",
                ),
                "cache_key_cids": _mapping(
                    data["cache_key_cids"],
                    "cache_key_cids",
                ),
            }
        )  # type: ignore[arg-type]


def validate_g240_runtime_namespace_receipt_v2(
    value: object,
    *,
    policy: G240NamespacePolicyV2,
    plan: AblationPlan,
    job: ScheduledCase,
    evidence: CausalRuntimeEvidenceV2,
) -> G240RuntimeNamespaceReceiptV2:
    """Replay one receipt from the frozen policy and full runtime evidence."""

    receipt = (
        value
        if isinstance(value, G240RuntimeNamespaceReceiptV2)
        else G240RuntimeNamespaceReceiptV2.from_dict(value)
    )
    plan_cid = _plan_cid(plan)
    try:
        coordinate = policy.job_map[(plan_cid, job.job_id)]
    except KeyError as exc:
        raise RuntimeNamespaceProvenanceError(
            "G240 receipt job is absent from the namespace policy"
        ) from exc
    restored = validate_causal_runtime_evidence_v2(evidence.to_dict())
    result = _validate_g240_receipt_against_coordinate(
        receipt,
        policy=policy,
        coordinate=coordinate,
        evidence=restored,
    )
    result_record = restored.case_result
    if (
        coordinate.plan_cid != plan_cid
        or coordinate.run_id != plan.run_id
        or coordinate.split != plan.split.value
        or coordinate.job_id != job.job_id
        or coordinate.case_id != job.case.case_id
        or coordinate.variant_id != job.variant_id
        or coordinate.cache_mode != job.cache_mode.value
        or result_record.case_id != job.case.case_id
        or result_record.variant_id != job.variant_id
        or result_record.split is not plan.split
        or result_record.cache_mode is not job.cache_mode
    ):
        raise RuntimeNamespaceProvenanceError(
            "G240 receipt coordinate differs from the scheduled plan job"
        )
    return result


def _validate_g240_receipt_against_coordinate(
    receipt: G240RuntimeNamespaceReceiptV2,
    *,
    policy: G240NamespacePolicyV2,
    coordinate: G240JobNamespacePlanV2,
    evidence: CausalRuntimeEvidenceV2,
) -> G240RuntimeNamespaceReceiptV2:
    """Recompute one receipt from an already selected canonical coordinate."""

    expected_keys = _cache_key_cids(
        evidence=evidence,
        namespace_plan=coordinate,
    )
    if (
        receipt.policy_cid != policy.policy_cid
        or receipt.plan_cid != coordinate.plan_cid
        or receipt.coordinate_cid != coordinate.coordinate_cid
        or receipt.job_id != coordinate.job_id
        or receipt.runtime_evidence_cid != evidence.receipt_cid
        or receipt.process_namespace_cid
        != coordinate.process_namespace_cid
        or receipt.state_namespace_cid != coordinate.state_namespace_cid
        or receipt.output_namespace_cid
        != coordinate.output_namespace_cid
        or dict(receipt.cache_namespace_cids)
        != dict(coordinate.cache_namespace_cids)
        or _plain(receipt.cache_key_cids) != _plain(expected_keys)
    ):
        raise RuntimeNamespaceProvenanceError(
            "G240 runtime namespace receipt differs from source evidence"
        )
    return G240RuntimeNamespaceReceiptV2.from_dict(receipt.to_dict())


def validate_g240_runtime_namespace_receipt_from_policy_v2(
    value: object,
    *,
    policy: G240NamespacePolicyV2,
    evidence: CausalRuntimeEvidenceV2,
) -> G240RuntimeNamespaceReceiptV2:
    """Replay a persisted receipt when the original plan object is external."""

    receipt = (
        value
        if isinstance(value, G240RuntimeNamespaceReceiptV2)
        else G240RuntimeNamespaceReceiptV2.from_dict(value)
    )
    try:
        coordinate = policy.job_map[
            (receipt.plan_cid, receipt.job_id)
        ]
    except KeyError as exc:
        raise RuntimeNamespaceProvenanceError(
            "G240 source receipt is absent from its policy"
        ) from exc
    runtime = validate_causal_runtime_evidence_v2(evidence.to_dict())
    result = runtime.case_result
    if (
        coordinate.run_id != result.run_id
        or coordinate.split != result.split.value
        or coordinate.case_id != result.case_id
        or coordinate.variant_id != result.variant_id
        or coordinate.cache_mode != result.cache_mode.value
    ):
        raise RuntimeNamespaceProvenanceError(
            "G240 policy coordinate differs from runtime evidence"
        )
    return _validate_g240_receipt_against_coordinate(
        receipt,
        policy=policy,
        coordinate=coordinate,
        evidence=runtime,
    )


@dataclass(frozen=True, slots=True)
class G240RuntimeNamespaceEvidenceSetV2:
    """Complete source-replayed namespace receipts for selected plans."""

    policy: G240NamespacePolicyV2
    plan_cids: tuple[str, ...]
    receipts: tuple[G240RuntimeNamespaceReceiptV2, ...]
    validator_identity_cid: str
    complete: bool
    holdout_included: bool
    schema: str = G240_RUNTIME_NAMESPACE_EVIDENCE_SET_SCHEMA_V2
    evidence_set_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G240_RUNTIME_NAMESPACE_EVIDENCE_SET_SCHEMA_V2:
            raise RuntimeNamespaceProvenanceError(
                "unsupported G240 namespace evidence-set schema"
            )
        if not isinstance(self.policy, G240NamespacePolicyV2):
            raise RuntimeNamespaceProvenanceError(
                "G240 evidence set requires a typed namespace policy"
            )
        policy = G240NamespacePolicyV2.from_dict(self.policy.to_dict())
        object.__setattr__(self, "policy", policy)
        plans = tuple(_cid(value, "plan_cid") for value in self.plan_cids)
        if (
            not plans
            or plans != tuple(sorted(plans))
            or len(plans) != len(set(plans))
            or not set(plans).issubset(policy.plan_cids)
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 evidence-set plan identities are invalid"
            )
        object.__setattr__(self, "plan_cids", plans)
        receipts = tuple(
            item
            if isinstance(item, G240RuntimeNamespaceReceiptV2)
            else G240RuntimeNamespaceReceiptV2.from_dict(item)
            for item in self.receipts
        )
        order = tuple(
            (item.plan_cid, item.job_id) for item in receipts
        )
        if (
            not receipts
            or order != tuple(sorted(order))
            or len(order) != len(set(order))
            or any(
                item.policy_cid != policy.policy_cid
                or item.plan_cid not in plans
                for item in receipts
            )
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 receipts are empty, duplicated, unsorted, or foreign"
            )
        object.__setattr__(self, "receipts", receipts)
        validator = _cid(
            self.validator_identity_cid, "validator_identity_cid"
        )
        object.__setattr__(self, "validator_identity_cid", validator)
        authorities = {
            policy.namespace_authority_cid,
            validator,
            *(
                receipt.executor_identity_cid
                for receipt in receipts
            ),
            *(
                receipt.observer_identity_cid
                for receipt in receipts
            ),
        }
        expected_authority_count = (
            2
            + len(
                {
                    receipt.executor_identity_cid
                    for receipt in receipts
                }
            )
            + len(
                {
                    receipt.observer_identity_cid
                    for receipt in receipts
                }
            )
        )
        if len(authorities) != expected_authority_count:
            raise RuntimeNamespaceProvenanceError(
                "G240 policy, executor, observer, and validator authorities "
                "must be disjoint"
            )
        if self.complete is not True or self.holdout_included is not False:
            raise RuntimeNamespaceProvenanceError(
                "G240 evidence set must be complete and non-holdout"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.evidence_set_cid is None:
            object.__setattr__(self, "evidence_set_cid", expected)
        elif _cid(self.evidence_set_cid, "evidence_set_cid") != expected:
            raise RuntimeNamespaceProvenanceError(
                "G240 namespace evidence-set CID changed"
            )

    @property
    def receipt_map(
        self,
    ) -> Mapping[tuple[str, str], G240RuntimeNamespaceReceiptV2]:
        return MappingProxyType(
            {
                (item.plan_cid, item.job_id): item
                for item in self.receipts
            }
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "policy": self.policy.to_dict(),
            "plan_cids": list(self.plan_cids),
            "receipts": [item.to_dict() for item in self.receipts],
            "validator_identity_cid": self.validator_identity_cid,
            "complete": self.complete,
            "holdout_included": self.holdout_included,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "evidence_set_cid": self.evidence_set_cid,
        }

    @classmethod
    def create(
        cls,
        *,
        policy: G240NamespacePolicyV2,
        plan_cids: Sequence[str],
        receipts: Sequence[G240RuntimeNamespaceReceiptV2],
        validator_identity_cid: str,
    ) -> Self:
        return cls(
            policy=policy,
            plan_cids=tuple(sorted(plan_cids)),
            receipts=tuple(
                sorted(
                    receipts,
                    key=lambda item: (item.plan_cid, item.job_id),
                )
            ),
            validator_identity_cid=validator_identity_cid,
            complete=True,
            holdout_included=False,
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G240 namespace evidence set")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G240 namespace evidence set",
        )
        plan_cids = data["plan_cids"]
        receipts = data["receipts"]
        if not isinstance(plan_cids, list) or not isinstance(receipts, list):
            raise RuntimeNamespaceProvenanceError(
                "G240 evidence-set plans/receipts must be arrays"
            )
        return cls(
            **{
                **data,
                "policy": G240NamespacePolicyV2.from_dict(data["policy"]),
                "plan_cids": tuple(plan_cids),
                "receipts": tuple(
                    G240RuntimeNamespaceReceiptV2.from_dict(item)
                    for item in receipts
                ),
            }
        )  # type: ignore[arg-type]


def validate_g240_runtime_namespace_evidence_set_v2(
    value: object,
    *,
    plans: Sequence[AblationPlan],
    evidence_by_plan_and_job: Mapping[
        tuple[str, str], CausalRuntimeEvidenceV2
    ],
) -> G240RuntimeNamespaceEvidenceSetV2:
    """Source-recompute an exact G240 receipt population."""

    evidence_set = (
        value
        if isinstance(value, G240RuntimeNamespaceEvidenceSetV2)
        else G240RuntimeNamespaceEvidenceSetV2.from_dict(value)
    )
    plans_by_cid = {
        _plan_cid(plan): AblationPlan.from_dict(plan.to_dict())
        for plan in plans
    }
    if set(plans_by_cid) != set(evidence_set.plan_cids):
        raise RuntimeNamespaceProvenanceError(
            "G240 evidence set differs from the selected plan population"
        )
    validate_g240_namespace_policy_v2(
        evidence_set.policy,
        tuple(
            plan
            for plan_cid, plan in sorted(plans_by_cid.items())
            if plan_cid in evidence_set.policy.plan_cids
        ),
    )
    expected_coordinates = {
        (plan_cid, job.job_id): (plan, job)
        for plan_cid, plan in plans_by_cid.items()
        for job in plan.jobs
    }
    if (
        set(evidence_by_plan_and_job) != set(expected_coordinates)
        or set(evidence_set.receipt_map) != set(expected_coordinates)
    ):
        raise RuntimeNamespaceProvenanceError(
            "G240 receipts/evidence must exactly cover every scheduled job"
        )
    restored: list[G240RuntimeNamespaceReceiptV2] = []
    for key in sorted(expected_coordinates):
        plan, job = expected_coordinates[key]
        evidence = evidence_by_plan_and_job[key]
        restored.append(
            validate_g240_runtime_namespace_receipt_v2(
                evidence_set.receipt_map[key],
                policy=evidence_set.policy,
                plan=plan,
                job=job,
                evidence=evidence,
            )
        )
    rebuilt = G240RuntimeNamespaceEvidenceSetV2.create(
        policy=evidence_set.policy,
        plan_cids=tuple(sorted(plans_by_cid)),
        receipts=restored,
        validator_identity_cid=evidence_set.validator_identity_cid,
    )
    if _plain(rebuilt.to_dict()) != _plain(evidence_set.to_dict()):
        raise RuntimeNamespaceProvenanceError(
            "G240 namespace evidence set differs from source replay"
        )
    return rebuilt


def validate_g240_runtime_namespace_population_v2(
    values: Sequence[object],
    *,
    plan_cids_by_split: Mapping[str, str],
    runtime_evidence: Sequence[CausalRuntimeEvidenceV2],
    expected_environment_cid: str | None = None,
) -> tuple[G240RuntimeNamespaceEvidenceSetV2, ...]:
    """Join persisted G211 namespace sets to a full G210 runtime population.

    This post-persistence validator deliberately does not trust a caller to
    resupply the original ``AblationPlan`` objects.  It reparses each policy
    and receipt, joins the policy plan identities to the G211 rescue-manifest
    plan CIDs, derives each canonical job ID from full runtime evidence, and
    then recomputes cache-key observations and every namespace/lifecycle join.
    """

    plan_map = {
        split: _cid(plan_cid, f"plan_cids_by_split.{split}")
        for split, plan_cid in _mapping(
            plan_cids_by_split, "plan_cids_by_split"
        ).items()
    }
    if set(plan_map) != _SPLITS or len(set(plan_map.values())) != len(plan_map):
        raise RuntimeNamespaceProvenanceError(
            "G240 population requires distinct pilot/development plan CIDs"
        )
    sets = tuple(
        value
        if isinstance(value, G240RuntimeNamespaceEvidenceSetV2)
        else G240RuntimeNamespaceEvidenceSetV2.from_dict(value)
        for value in values
    )
    if len(sets) != 2:
        raise RuntimeNamespaceProvenanceError(
            "G240 population requires two persisted G211 evidence sets"
        )
    set_by_plan: dict[str, G240RuntimeNamespaceEvidenceSetV2] = {}
    for item in sets:
        if len(item.plan_cids) != 1:
            raise RuntimeNamespaceProvenanceError(
                "each G211 namespace evidence set must bind one split plan"
            )
        plan_cid = item.plan_cids[0]
        if plan_cid in set_by_plan:
            raise RuntimeNamespaceProvenanceError(
                "G240 namespace evidence sets duplicate a plan"
            )
        set_by_plan[plan_cid] = item
    if set(set_by_plan) != set(plan_map.values()):
        raise RuntimeNamespaceProvenanceError(
            "G240 namespace evidence plan population changed"
        )
    restored_evidence = tuple(
        validate_causal_runtime_evidence_v2(item.to_dict())
        for item in runtime_evidence
    )
    evidence_by_key: dict[
        tuple[str, str], CausalRuntimeEvidenceV2
    ] = {}
    for evidence in restored_evidence:
        result = evidence.case_result
        split = result.split.value
        if split not in plan_map:
            raise RuntimeNamespaceProvenanceError(
                "G240 runtime evidence includes a foreign split"
            )
        job_id = (
            f"j-{result.cache_mode.value}-{result.case_id}-"
            f"{result.variant_id.lower()}"
        )
        key = (plan_map[split], job_id)
        if key in evidence_by_key:
            raise RuntimeNamespaceProvenanceError(
                "G240 runtime evidence duplicates a namespace coordinate"
            )
        evidence_by_key[key] = evidence
    expected_keys = {
        (plan_cid, coordinate.job_id)
        for plan_cid, evidence_set in set_by_plan.items()
        for coordinate in evidence_set.policy.jobs
        if coordinate.plan_cid == plan_cid
    }
    if set(evidence_by_key) != expected_keys:
        raise RuntimeNamespaceProvenanceError(
            "G240 namespace policies do not exactly cover runtime evidence"
        )
    environment = (
        None
        if expected_environment_cid is None
        else _cid(expected_environment_cid, "expected_environment_cid")
    )
    restored_sets: list[G240RuntimeNamespaceEvidenceSetV2] = []
    all_process: set[str] = set()
    all_state: set[str] = set()
    all_output: set[str] = set()
    cache_modes_by_treatment: dict[
        tuple[str, str, str, str], dict[str, str]
    ] = {}
    for plan_cid in sorted(set_by_plan):
        evidence_set = set_by_plan[plan_cid]
        policy = evidence_set.policy
        if (
            policy.plan_cids != (plan_cid,)
            or (
                environment is not None
                and policy.environment_cid != environment
            )
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 policy plan/environment differs from the source freeze"
            )
        coordinates = {
            (item.plan_cid, item.job_id): item
            for item in policy.jobs
            if item.plan_cid == plan_cid
        }
        if set(evidence_set.receipt_map) != set(coordinates):
            raise RuntimeNamespaceProvenanceError(
                "G240 evidence set does not cover its complete policy"
            )
        receipts: list[G240RuntimeNamespaceReceiptV2] = []
        for key in sorted(coordinates):
            coordinate = coordinates[key]
            evidence = evidence_by_key[key]
            result = evidence.case_result
            split = result.split.value
            if (
                plan_map[split] != coordinate.plan_cid
                or coordinate.run_id != result.run_id
                or coordinate.split != split
                or coordinate.case_id != result.case_id
                or coordinate.variant_id != result.variant_id
                or coordinate.cache_mode != result.cache_mode.value
            ):
                raise RuntimeNamespaceProvenanceError(
                    "G240 policy coordinate differs from full runtime evidence"
                )
            receipt = _validate_g240_receipt_against_coordinate(
                evidence_set.receipt_map[key],
                policy=policy,
                coordinate=coordinate,
                evidence=evidence,
            )
            receipts.append(receipt)
            for seen, namespace_cid, name in (
                (
                    all_process,
                    receipt.process_namespace_cid,
                    "process",
                ),
                (all_state, receipt.state_namespace_cid, "state"),
                (all_output, receipt.output_namespace_cid, "output"),
            ):
                if namespace_cid in seen:
                    raise RuntimeNamespaceProvenanceError(
                        f"G240 {name} namespace was reused across jobs"
                    )
                seen.add(namespace_cid)
            for stage, cache_cid in receipt.cache_namespace_cids.items():
                treatment = (
                    coordinate.plan_cid,
                    coordinate.split,
                    coordinate.variant_id,
                    stage,
                )
                mode_map = cache_modes_by_treatment.setdefault(
                    treatment, {}
                )
                previous = mode_map.setdefault(
                    coordinate.cache_mode, cache_cid
                )
                if previous != cache_cid:
                    raise RuntimeNamespaceProvenanceError(
                        "G240 physical cache namespace changed within a "
                        "treatment"
                    )
        rebuilt = G240RuntimeNamespaceEvidenceSetV2.create(
            policy=policy,
            plan_cids=(plan_cid,),
            receipts=receipts,
            validator_identity_cid=evidence_set.validator_identity_cid,
        )
        if _plain(rebuilt.to_dict()) != _plain(evidence_set.to_dict()):
            raise RuntimeNamespaceProvenanceError(
                "G240 persisted evidence set changed under source replay"
            )
        restored_sets.append(rebuilt)
    if any(
        len(set(modes.values())) != len(modes)
        for modes in cache_modes_by_treatment.values()
    ):
        raise RuntimeNamespaceProvenanceError(
            "G240 cold/warm cache namespace reuse crossed a treatment"
        )
    return tuple(
        sorted(restored_sets, key=lambda item: item.plan_cids)
    )


def _replay_context_cid(
    *,
    source_policy_cid: str,
    source_coordinate_cid: str,
    source_runtime_evidence_cid: str,
    replay_run_id: str,
) -> str:
    return cid_for_dag_json(
        {
            "schema": G240_REPLAY_NAMESPACE_CONTEXT_SCHEMA_V2,
            "source_policy_cid": source_policy_cid,
            "source_coordinate_cid": source_coordinate_cid,
            "source_runtime_evidence_cid": source_runtime_evidence_cid,
            "replay_run_id": replay_run_id,
        }
    )


def _replay_job_namespace_cid(
    *,
    replay_context_cid: str,
    kind: str,
    replay_run_id: str,
    source_coordinate: G240JobNamespacePlanV2,
) -> str:
    if kind not in _JOB_NAMESPACE_KINDS:
        raise RuntimeNamespaceProvenanceError(
            f"unsupported G240 replay namespace kind: {kind}"
        )
    return cid_for_dag_json(
        {
            "schema": G240_NAMESPACE_PREIMAGE_SCHEMA_V2,
            "context_cid": replay_context_cid,
            "kind": f"replay_{kind}",
            "run_id": replay_run_id,
            "source_coordinate_cid": source_coordinate.coordinate_cid,
            "split": source_coordinate.split,
            "case_id": source_coordinate.case_id,
            "variant_id": source_coordinate.variant_id,
            "stage": "job",
            "cache_mode": source_coordinate.cache_mode,
        }
    )


def _replay_cache_namespace_cid(
    *,
    replay_context_cid: str,
    replay_run_id: str,
    source_coordinate: G240JobNamespacePlanV2,
    stage: str,
) -> str:
    return cid_for_dag_json(
        {
            "schema": G240_NAMESPACE_PREIMAGE_SCHEMA_V2,
            "context_cid": replay_context_cid,
            "kind": "replay_physical_cache",
            "run_id": replay_run_id,
            "source_coordinate_cid": source_coordinate.coordinate_cid,
            "split": source_coordinate.split,
            "case_id": source_coordinate.case_id,
            "variant_id": source_coordinate.variant_id,
            "stage": stage,
            "cache_mode": source_coordinate.cache_mode,
        }
    )


@dataclass(frozen=True, slots=True)
class G240ReplayNamespaceReceiptV2:
    """Path-free namespace evidence for one fresh detached G238 replay."""

    source_policy_cid: str
    source_namespace_receipt_cid: str
    source_runtime_evidence_cid: str
    source_coordinate_cid: str
    replay_run_id: str
    replay_worktree_cid: str
    replay_runtime_evidence_cid: str
    replay_context_cid: str
    replay_process_namespace_cid: str
    replay_state_namespace_cid: str
    replay_output_namespace_cid: str
    replay_cache_namespace_cids: Mapping[str, str]
    replay_cache_key_cids: Mapping[str, tuple[str, ...]]
    replay_executor_identity_cid: str
    replay_observer_identity_cid: str
    process_group_started: bool
    process_group_reaped: bool
    active_process_count_after_reap: int
    state_namespace_created_exclusive: bool
    state_namespace_finalized: bool
    output_namespace_created_exclusive: bool
    output_namespace_finalized: bool
    cache_namespaces_mounted: bool
    detached: bool
    attached: bool
    holdout_accessed: bool
    schema: str = G240_REPLAY_NAMESPACE_RECEIPT_SCHEMA_V2
    receipt_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G240_REPLAY_NAMESPACE_RECEIPT_SCHEMA_V2:
            raise RuntimeNamespaceProvenanceError(
                "unsupported G240 replay namespace-receipt schema"
            )
        for field in (
            "source_policy_cid",
            "source_namespace_receipt_cid",
            "source_runtime_evidence_cid",
            "source_coordinate_cid",
            "replay_worktree_cid",
            "replay_runtime_evidence_cid",
            "replay_context_cid",
            "replay_process_namespace_cid",
            "replay_state_namespace_cid",
            "replay_output_namespace_cid",
            "replay_executor_identity_cid",
            "replay_observer_identity_cid",
        ):
            object.__setattr__(
                self, field, _cid(getattr(self, field), field)
            )
        object.__setattr__(
            self,
            "replay_run_id",
            _safe_id(self.replay_run_id, "replay_run_id"),
        )
        caches = {
            _safe_id(stage, "replay cache stage"): _cid(
                value, f"replay_cache_namespace_cids.{stage}"
            )
            for stage, value in _mapping(
                self.replay_cache_namespace_cids,
                "replay_cache_namespace_cids",
            ).items()
        }
        keys: dict[str, tuple[str, ...]] = {}
        for stage, values in _mapping(
            self.replay_cache_key_cids,
            "replay_cache_key_cids",
        ).items():
            _safe_id(stage, "replay cache-key stage")
            if not isinstance(values, (tuple, list)):
                raise RuntimeNamespaceProvenanceError(
                    f"replay_cache_key_cids.{stage} must be an array"
                )
            normalized = tuple(
                _cid(value, f"replay_cache_key_cids.{stage}[]")
                for value in values
            )
            if (
                normalized != tuple(sorted(normalized))
                or len(normalized) != len(set(normalized))
            ):
                raise RuntimeNamespaceProvenanceError(
                    f"replay_cache_key_cids.{stage} must be sorted and unique"
                )
            keys[stage] = normalized
        if set(caches) != set(keys):
            raise RuntimeNamespaceProvenanceError(
                "G240 replay cache namespace/key stage maps differ"
            )
        object.__setattr__(
            self,
            "replay_cache_namespace_cids",
            MappingProxyType(caches),
        )
        object.__setattr__(
            self,
            "replay_cache_key_cids",
            MappingProxyType(keys),
        )
        for field in (
            "process_group_started",
            "process_group_reaped",
            "state_namespace_created_exclusive",
            "state_namespace_finalized",
            "output_namespace_created_exclusive",
            "output_namespace_finalized",
            "cache_namespaces_mounted",
            "detached",
            "attached",
            "holdout_accessed",
        ):
            if type(getattr(self, field)) is not bool:
                raise RuntimeNamespaceProvenanceError(
                    f"{field} must be an observed boolean"
                )
        if (
            type(self.active_process_count_after_reap) is not int
            or self.active_process_count_after_reap < 0
        ):
            raise RuntimeNamespaceProvenanceError(
                "active_process_count_after_reap must be nonnegative"
            )
        if (
            self.replay_executor_identity_cid
            == self.replay_observer_identity_cid
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 replay executor and observer must differ"
            )
        if not all(
            (
                self.process_group_started,
                self.process_group_reaped,
                self.active_process_count_after_reap == 0,
                self.state_namespace_created_exclusive,
                self.state_namespace_finalized,
                self.output_namespace_created_exclusive,
                self.output_namespace_finalized,
                self.cache_namespaces_mounted,
                self.detached,
                not self.attached,
                not self.holdout_accessed,
            )
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 replay namespace lifecycle is incomplete"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.receipt_cid is None:
            object.__setattr__(self, "receipt_cid", expected)
        elif _cid(self.receipt_cid, "receipt_cid") != expected:
            raise RuntimeNamespaceProvenanceError(
                "G240 replay namespace receipt CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "source_policy_cid": self.source_policy_cid,
            "source_namespace_receipt_cid": (
                self.source_namespace_receipt_cid
            ),
            "source_runtime_evidence_cid": (
                self.source_runtime_evidence_cid
            ),
            "source_coordinate_cid": self.source_coordinate_cid,
            "replay_run_id": self.replay_run_id,
            "replay_worktree_cid": self.replay_worktree_cid,
            "replay_runtime_evidence_cid": (
                self.replay_runtime_evidence_cid
            ),
            "replay_context_cid": self.replay_context_cid,
            "replay_process_namespace_cid": (
                self.replay_process_namespace_cid
            ),
            "replay_state_namespace_cid": (
                self.replay_state_namespace_cid
            ),
            "replay_output_namespace_cid": (
                self.replay_output_namespace_cid
            ),
            "replay_cache_namespace_cids": dict(
                self.replay_cache_namespace_cids
            ),
            "replay_cache_key_cids": {
                stage: list(values)
                for stage, values in self.replay_cache_key_cids.items()
            },
            "replay_executor_identity_cid": (
                self.replay_executor_identity_cid
            ),
            "replay_observer_identity_cid": (
                self.replay_observer_identity_cid
            ),
            "process_group_started": self.process_group_started,
            "process_group_reaped": self.process_group_reaped,
            "active_process_count_after_reap": (
                self.active_process_count_after_reap
            ),
            "state_namespace_created_exclusive": (
                self.state_namespace_created_exclusive
            ),
            "state_namespace_finalized": self.state_namespace_finalized,
            "output_namespace_created_exclusive": (
                self.output_namespace_created_exclusive
            ),
            "output_namespace_finalized": self.output_namespace_finalized,
            "cache_namespaces_mounted": self.cache_namespaces_mounted,
            "detached": self.detached,
            "attached": self.attached,
            "holdout_accessed": self.holdout_accessed,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_cid": self.receipt_cid}

    @classmethod
    def create(
        cls,
        *,
        source_policy: G240NamespacePolicyV2,
        source_receipt: G240RuntimeNamespaceReceiptV2,
        replay_run_id: str,
        replay_worktree_cid: str,
        replay_runtime_evidence: CausalRuntimeEvidenceV2,
        replay_executor_identity_cid: str,
        replay_observer_identity_cid: str,
        process_group_started: bool,
        process_group_reaped: bool,
        active_process_count_after_reap: int,
        state_namespace_created_exclusive: bool,
        state_namespace_finalized: bool,
        output_namespace_created_exclusive: bool,
        output_namespace_finalized: bool,
        cache_namespaces_mounted: bool,
        detached: bool = True,
        attached: bool = False,
        holdout_accessed: bool = False,
    ) -> Self:
        try:
            coordinate = source_policy.job_map[
                (source_receipt.plan_cid, source_receipt.job_id)
            ]
        except KeyError as exc:
            raise RuntimeNamespaceProvenanceError(
                "G240 source receipt is absent from its policy"
            ) from exc
        replay_evidence = validate_causal_runtime_evidence_v2(
            replay_runtime_evidence.to_dict()
        )
        replay_id = _safe_id(replay_run_id, "replay_run_id")
        replay_result = replay_evidence.case_result
        if (
            replay_result.run_id != replay_id
            or replay_result.split.value != coordinate.split
            or replay_result.case_id != coordinate.case_id
            or replay_result.variant_id != coordinate.variant_id
            or replay_result.cache_mode.value != coordinate.cache_mode
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 replay runtime differs from its fresh run/coordinate"
            )
        worktree_cid = _cid(
            replay_worktree_cid, "replay_worktree_cid"
        )
        context_cid = _replay_context_cid(
            source_policy_cid=str(source_policy.policy_cid),
            source_coordinate_cid=str(coordinate.coordinate_cid),
            source_runtime_evidence_cid=(
                source_receipt.runtime_evidence_cid
            ),
            replay_run_id=replay_id,
        )
        caches = {
            stage: _replay_cache_namespace_cid(
                replay_context_cid=context_cid,
                replay_run_id=replay_id,
                source_coordinate=coordinate,
                stage=stage,
            )
            for stage in coordinate.stages
        }
        return cls(
            source_policy_cid=str(source_policy.policy_cid),
            source_namespace_receipt_cid=str(
                source_receipt.receipt_cid
            ),
            source_runtime_evidence_cid=(
                source_receipt.runtime_evidence_cid
            ),
            source_coordinate_cid=str(coordinate.coordinate_cid),
            replay_run_id=replay_id,
            replay_worktree_cid=worktree_cid,
            replay_runtime_evidence_cid=replay_evidence.receipt_cid,
            replay_context_cid=context_cid,
            replay_process_namespace_cid=_replay_job_namespace_cid(
                replay_context_cid=context_cid,
                kind="process_group",
                replay_run_id=replay_id,
                source_coordinate=coordinate,
            ),
            replay_state_namespace_cid=_replay_job_namespace_cid(
                replay_context_cid=context_cid,
                kind="state",
                replay_run_id=replay_id,
                source_coordinate=coordinate,
            ),
            replay_output_namespace_cid=_replay_job_namespace_cid(
                replay_context_cid=context_cid,
                kind="output",
                replay_run_id=replay_id,
                source_coordinate=coordinate,
            ),
            replay_cache_namespace_cids=caches,
            replay_cache_key_cids=_cache_key_cids_for_stage_map(
                evidence=replay_evidence,
                stages=coordinate.stages,
                cache_namespace_cids=caches,
            ),
            replay_executor_identity_cid=replay_executor_identity_cid,
            replay_observer_identity_cid=replay_observer_identity_cid,
            process_group_started=process_group_started,
            process_group_reaped=process_group_reaped,
            active_process_count_after_reap=(
                active_process_count_after_reap
            ),
            state_namespace_created_exclusive=(
                state_namespace_created_exclusive
            ),
            state_namespace_finalized=state_namespace_finalized,
            output_namespace_created_exclusive=(
                output_namespace_created_exclusive
            ),
            output_namespace_finalized=output_namespace_finalized,
            cache_namespaces_mounted=cache_namespaces_mounted,
            detached=detached,
            attached=attached,
            holdout_accessed=holdout_accessed,
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G240 replay namespace receipt")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G240 replay namespace receipt",
        )
        return cls(
            **{
                **data,
                "replay_cache_namespace_cids": _mapping(
                    data["replay_cache_namespace_cids"],
                    "replay_cache_namespace_cids",
                ),
                "replay_cache_key_cids": _mapping(
                    data["replay_cache_key_cids"],
                    "replay_cache_key_cids",
                ),
            }
        )  # type: ignore[arg-type]


def validate_g240_replay_namespace_receipt_v2(
    value: object,
    *,
    source_policy: G240NamespacePolicyV2,
    source_receipt: G240RuntimeNamespaceReceiptV2,
    source_runtime_evidence: CausalRuntimeEvidenceV2,
    replay_runtime_evidence: CausalRuntimeEvidenceV2,
) -> G240ReplayNamespaceReceiptV2:
    """Recompute a detached replay namespace without volatile equality."""

    receipt = (
        value
        if isinstance(value, G240ReplayNamespaceReceiptV2)
        else G240ReplayNamespaceReceiptV2.from_dict(value)
    )
    try:
        coordinate = source_policy.job_map[
            (source_receipt.plan_cid, source_receipt.job_id)
        ]
    except KeyError as exc:
        raise RuntimeNamespaceProvenanceError(
            "G240 replay source coordinate is absent from the policy"
        ) from exc
    source_evidence = validate_causal_runtime_evidence_v2(
        source_runtime_evidence.to_dict()
    )
    _validate_g240_receipt_against_coordinate(
        source_receipt,
        policy=source_policy,
        coordinate=coordinate,
        evidence=source_evidence,
    )
    rebuilt = G240ReplayNamespaceReceiptV2.create(
        source_policy=source_policy,
        source_receipt=source_receipt,
        replay_run_id=receipt.replay_run_id,
        replay_worktree_cid=receipt.replay_worktree_cid,
        replay_runtime_evidence=replay_runtime_evidence,
        replay_executor_identity_cid=(
            receipt.replay_executor_identity_cid
        ),
        replay_observer_identity_cid=(
            receipt.replay_observer_identity_cid
        ),
        process_group_started=receipt.process_group_started,
        process_group_reaped=receipt.process_group_reaped,
        active_process_count_after_reap=(
            receipt.active_process_count_after_reap
        ),
        state_namespace_created_exclusive=(
            receipt.state_namespace_created_exclusive
        ),
        state_namespace_finalized=receipt.state_namespace_finalized,
        output_namespace_created_exclusive=(
            receipt.output_namespace_created_exclusive
        ),
        output_namespace_finalized=receipt.output_namespace_finalized,
        cache_namespaces_mounted=receipt.cache_namespaces_mounted,
        detached=receipt.detached,
        attached=receipt.attached,
        holdout_accessed=receipt.holdout_accessed,
    )
    if (
        receipt.replay_run_id == coordinate.run_id
        or receipt.replay_process_namespace_cid
        == source_receipt.process_namespace_cid
        or receipt.replay_state_namespace_cid
        == source_receipt.state_namespace_cid
        or receipt.replay_output_namespace_cid
        == source_receipt.output_namespace_cid
        or set(receipt.replay_cache_namespace_cids.values())
        & set(source_receipt.cache_namespace_cids.values())
        or _plain(receipt.to_dict()) != _plain(rebuilt.to_dict())
    ):
        raise RuntimeNamespaceProvenanceError(
            "G240 detached replay namespace is stale, reused, or rebased"
        )
    return rebuilt


def g240_replay_namespace_request_v2(
    *,
    source_policy: G240NamespacePolicyV2,
    source_receipt: G240RuntimeNamespaceReceiptV2,
    replay_run_id: str,
) -> Mapping[str, object]:
    """Derive launch-time replay namespaces before creating a worktree."""

    try:
        coordinate = source_policy.job_map[
            (source_receipt.plan_cid, source_receipt.job_id)
        ]
    except KeyError as exc:
        raise RuntimeNamespaceProvenanceError(
            "G240 replay request source is absent from the policy"
        ) from exc
    replay_id = _safe_id(replay_run_id, "replay_run_id")
    if replay_id == coordinate.run_id:
        raise RuntimeNamespaceProvenanceError(
            "G240 replay request must use a fresh run"
        )
    context_cid = _replay_context_cid(
        source_policy_cid=str(source_policy.policy_cid),
        source_coordinate_cid=str(coordinate.coordinate_cid),
        source_runtime_evidence_cid=(
            source_receipt.runtime_evidence_cid
        ),
        replay_run_id=replay_id,
    )
    caches = {
        stage: _replay_cache_namespace_cid(
            replay_context_cid=context_cid,
            replay_run_id=replay_id,
            source_coordinate=coordinate,
            stage=stage,
        )
        for stage in coordinate.stages
    }
    value = {
        "schema": G240_REPLAY_NAMESPACE_CONTEXT_SCHEMA_V2,
        "source_policy_cid": source_policy.policy_cid,
        "source_namespace_receipt_cid": source_receipt.receipt_cid,
        "source_coordinate_cid": coordinate.coordinate_cid,
        "replay_run_id": replay_id,
        "replay_context_cid": context_cid,
        "replay_process_namespace_cid": _replay_job_namespace_cid(
            replay_context_cid=context_cid,
            kind="process_group",
            replay_run_id=replay_id,
            source_coordinate=coordinate,
        ),
        "replay_state_namespace_cid": _replay_job_namespace_cid(
            replay_context_cid=context_cid,
            kind="state",
            replay_run_id=replay_id,
            source_coordinate=coordinate,
        ),
        "replay_output_namespace_cid": _replay_job_namespace_cid(
            replay_context_cid=context_cid,
            kind="output",
            replay_run_id=replay_id,
            source_coordinate=coordinate,
        ),
        "replay_cache_namespace_cids": caches,
        "replay_cache_namespace_set_cid": (
            g240_cache_namespace_set_cid(caches)
        ),
    }
    frozen = _freeze(value)
    assert isinstance(frozen, Mapping)
    return frozen


@dataclass(frozen=True, slots=True)
class G240ReplayOrchestrationReceiptV2:
    """Path-free bridge to an actually executed detached replay process."""

    source_policy_cid: str
    runtime_orchestration_policy_cid: str
    command_cid: str
    interpreter_identity_cid: str
    confinement_profile_cid: str
    namespace_receipt_cid: str
    source_runtime_evidence_cid: str
    replay_runtime_evidence_cid: str
    source_commit_cid: str
    recursive_gitlinks_cid: str
    replay_run_id: str
    replay_worktree_cid: str
    replay_process_namespace_cid: str
    replay_state_namespace_cid: str
    replay_output_namespace_cid: str
    replay_cache_namespace_set_cid: str
    replay_request_cid: str
    legacy_replay_receipt_cid: str
    worktree_safety_projection_cid: str
    runtime_preflight_cid: str
    landlock_policy_cid: str | None
    landlock_receipt_cid: str | None
    landlock_receipt_payload_cid: str | None
    evidence_payload_cid: str
    orchestration_observer_identity_cid: str
    detached: bool
    auto_merge: bool
    process_group_reaped: bool
    active_process_count_after_reap: int
    evidence_canonical: bool
    synthetic_test_only: bool
    complete: bool
    holdout_accessed: bool
    schema: str = G240_REPLAY_ORCHESTRATION_RECEIPT_SCHEMA_V2
    receipt_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G240_REPLAY_ORCHESTRATION_RECEIPT_SCHEMA_V2:
            raise RuntimeNamespaceProvenanceError(
                "unsupported G240 replay orchestration-receipt schema"
            )
        for field in (
            "source_policy_cid",
            "runtime_orchestration_policy_cid",
            "command_cid",
            "interpreter_identity_cid",
            "confinement_profile_cid",
            "namespace_receipt_cid",
            "source_runtime_evidence_cid",
            "replay_runtime_evidence_cid",
            "source_commit_cid",
            "recursive_gitlinks_cid",
            "replay_worktree_cid",
            "replay_process_namespace_cid",
            "replay_state_namespace_cid",
            "replay_output_namespace_cid",
            "replay_cache_namespace_set_cid",
            "replay_request_cid",
            "legacy_replay_receipt_cid",
            "worktree_safety_projection_cid",
            "runtime_preflight_cid",
            "evidence_payload_cid",
            "orchestration_observer_identity_cid",
        ):
            object.__setattr__(
                self, field, _cid(getattr(self, field), field)
            )
        if (
            self.confinement_profile_cid
            != G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 replay confinement profile changed"
            )
        for field in (
            "landlock_policy_cid",
            "landlock_receipt_cid",
            "landlock_receipt_payload_cid",
        ):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _cid(value, field))
        object.__setattr__(
            self,
            "replay_run_id",
            _safe_id(self.replay_run_id, "replay_run_id"),
        )
        for field in (
            "detached",
            "auto_merge",
            "process_group_reaped",
            "evidence_canonical",
            "synthetic_test_only",
            "complete",
            "holdout_accessed",
        ):
            if type(getattr(self, field)) is not bool:
                raise RuntimeNamespaceProvenanceError(
                    f"{field} must be an observed boolean"
                )
        if (
            type(self.active_process_count_after_reap) is not int
            or self.active_process_count_after_reap < 0
        ):
            raise RuntimeNamespaceProvenanceError(
                "active_process_count_after_reap must be nonnegative"
            )
        landlock_cids = (
            self.landlock_policy_cid,
            self.landlock_receipt_cid,
            self.landlock_receipt_payload_cid,
        )
        if (
            self.synthetic_test_only
            and any(value is not None for value in landlock_cids)
        ) or (
            not self.synthetic_test_only
            and any(value is None for value in landlock_cids)
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 replay Landlock claims differ from execution mode"
            )
        if not all(
            (
                self.detached,
                not self.auto_merge,
                self.process_group_reaped,
                self.active_process_count_after_reap == 0,
                self.evidence_canonical,
                self.complete,
                not self.holdout_accessed,
            )
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 detached replay orchestration is incomplete"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.receipt_cid is None:
            object.__setattr__(self, "receipt_cid", expected)
        elif _cid(self.receipt_cid, "receipt_cid") != expected:
            raise RuntimeNamespaceProvenanceError(
                "G240 replay orchestration receipt CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "receipt_cid"
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_cid": self.receipt_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G240 replay orchestration receipt")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G240 replay orchestration receipt",
        )
        return cls(**data)  # type: ignore[arg-type]


def g240_worktree_safety_projection_cid(value: object) -> str:
    """Address the public, path-free portion of WorktreeSafetyReceipt."""

    try:
        from .capabilities import WorktreeSafetyReceipt

        worktree = (
            value
            if isinstance(value, WorktreeSafetyReceipt)
            else WorktreeSafetyReceipt.from_dict(value)
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeNamespaceProvenanceError(
            "G240 requires a typed detached worktree safety receipt"
        ) from exc
    return cid_for_dag_json(
        {
            "schema": G240_REPLAY_WORKTREE_PROJECTION_SCHEMA_V2,
            "run_id": worktree.run_id,
            "source_head": worktree.source_head,
            "source_status_cid": cid_for_dag_json(
                {
                    "legacy_sha256": worktree.source_status_sha256,
                    "meaning": "git-status-porcelain-v1-z",
                }
            ),
            "base_commit": worktree.base_commit,
            "worktree_commit": worktree.worktree_commit,
            "submodule_commits": dict(worktree.submodule_commits),
            "detached": worktree.detached,
            "auto_merge": worktree.auto_merge,
            "source_unchanged": worktree.source_unchanged,
        }
    )


def _build_g240_replay_orchestration_receipt_v2(
    *,
    source_policy: G240NamespacePolicyV2,
    source_namespace_receipt: G240RuntimeNamespaceReceiptV2,
    namespace_receipt: G240ReplayNamespaceReceiptV2,
    source_runtime_evidence: CausalRuntimeEvidenceV2,
    replay_runtime_evidence: CausalRuntimeEvidenceV2,
    executor_contract: object,
    replay_request: object,
    replay_receipt: object,
    worktree_safety_receipt: object,
    replay_execution_request: object,
    execution_request_payload: bytes,
    runtime_preflight_payload: bytes,
    landlock_transport_observation: object | None,
    evidence_payload: bytes,
    orchestration_observer_identity_cid: str,
    process_observation: object | None = None,
    active_process_count_after_reap: int = 0,
    holdout_accessed: bool = False,
) -> G240ReplayOrchestrationReceiptV2:
    """Bridge real ``run_detached_replay`` outputs into a G240 receipt.

    The replay command must persist the complete canonical
    ``CausalRuntimeEvidenceV2`` JSON as its evidence payload.  The legacy
    detached runner is used only as OS/Git process authority; its SHA fields
    are wrapped by CID-addressed projections and never become new bare-digest
    public identities.
    """

    try:
        from .capabilities import WorktreeSafetyReceipt
        from .replay import (
            ReplayReceipt,
            ReplayRequest,
            _coerce_g240_executor_contract_v2,
            _validate_g240_replay_runtime_preflight_v2,
            _validate_live_replay_process_observation_v2,
            _validate_g240_executor_entrypoint_v2,
        )
        from .source_executor import (
            validate_g240_execution_request_v2,
        )
        from .source_orchestration import _g240_launch_arguments

        request = (
            replay_request
            if isinstance(replay_request, ReplayRequest)
            else ReplayRequest.from_dict(replay_request)
        )
        replay = (
            replay_receipt
            if isinstance(replay_receipt, ReplayReceipt)
            else ReplayReceipt.from_dict(replay_receipt)
        )
        worktree = (
            worktree_safety_receipt
            if isinstance(
                worktree_safety_receipt, WorktreeSafetyReceipt
            )
            else WorktreeSafetyReceipt.from_dict(
                worktree_safety_receipt
            )
        )
        contract = _coerce_g240_executor_contract_v2(
            executor_contract,
            source_policy=source_policy,
        )
        observed_process = _validate_live_replay_process_observation_v2(
            replay,
            request,
            expected_arguments=_g240_launch_arguments(contract),
        )
        if (
            process_observation is not None
            and process_observation is not observed_process
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 replay process observation differs from the live "
                "receipt capability"
            )
        execution = validate_g240_execution_request_v2(
            replay_execution_request
        )
        if (
            not isinstance(execution_request_payload, bytes)
            or execution_request_payload
            != canonical_dag_json_bytes(execution.to_dict()) + b"\n"
            or request.execution_request_cid != execution.request_cid
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 replay execution request bytes differ from launch"
            )
        (
            runtime_preflight_cid,
            landlock_policy_cid,
            landlock_receipt_cid,
            landlock_receipt_payload_cid,
            synthetic_test_only,
        ) = _validate_g240_replay_runtime_preflight_v2(
            runtime_preflight_payload,
            execution_request=execution,
            contract=contract,
            worktree=worktree,
            landlock_transport_observation=(
                landlock_transport_observation
            ),
            process_observation=observed_process,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeNamespaceProvenanceError(
            "G240 replay orchestration inputs failed typed replay"
        ) from exc
    source_runtime = validate_causal_runtime_evidence_v2(
        source_runtime_evidence.to_dict()
    )
    runtime = validate_causal_runtime_evidence_v2(
        replay_runtime_evidence.to_dict()
    )
    _validate_g240_executor_entrypoint_v2(contract, worktree)
    if not isinstance(evidence_payload, bytes):
        raise RuntimeNamespaceProvenanceError(
            "G240 replay evidence payload must be exact bytes"
        )
    expected_payload = (
        canonical_dag_json_bytes(_plain(runtime.to_dict())) + b"\n"
    )
    try:
        decoded = json.loads(evidence_payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeNamespaceProvenanceError(
            "G240 replay evidence is not canonical runtime JSON"
        ) from exc
    evidence_canonical = (
        evidence_payload == expected_payload
        and _plain(decoded) == _plain(runtime.to_dict())
        and replay.evidence_sha256
        == hashlib.sha256(evidence_payload).hexdigest()
    )
    worktree_projection_cid = g240_worktree_safety_projection_cid(worktree)
    cache_set_cid = g240_cache_namespace_set_cid(
        namespace_receipt.replay_cache_namespace_cids
    )
    source_cache_set_cid = g240_cache_namespace_set_cid(
        source_namespace_receipt.cache_namespace_cids
    )
    request_cid = cid_for_dag_json(
        {
            "schema": "legacy-detached-replay-request-projection.v2",
            "request": request.to_dict(),
        }
    )
    replay_projection_cid = cid_for_dag_json(
        {
            "schema": "legacy-detached-replay-receipt-projection.v2",
            "receipt": replay.to_dict(),
        }
    )
    expected_source_receipt_sha256 = hashlib.sha256(
        canonical_json(
            source_namespace_receipt.to_dict()
        ).encode("utf-8")
    ).hexdigest()
    source_stage_environments = {
        stage.provenance.environment_sha256
        for stage in (
            *source_runtime.semantic_frontend,
            *source_runtime.case_result.stages,
        )
    }
    replay_stage_environments = {
        stage.provenance.environment_sha256
        for stage in (
            *runtime.semantic_frontend,
            *runtime.case_result.stages,
        )
    }
    if (
        namespace_receipt.source_policy_cid != source_policy.policy_cid
        or namespace_receipt.source_namespace_receipt_cid
        != source_namespace_receipt.receipt_cid
        or source_namespace_receipt.policy_cid
        != source_policy.policy_cid
        or namespace_receipt.source_runtime_evidence_cid
        != source_namespace_receipt.runtime_evidence_cid
        or source_namespace_receipt.runtime_evidence_cid
        != source_runtime.receipt_cid
        or namespace_receipt.replay_runtime_evidence_cid
        != runtime.receipt_cid
        or contract.contract_cid
        != source_policy.runtime_orchestration_policy_cid
        or contract.environment_cid != source_policy.environment_cid
        or source_namespace_receipt.executor_identity_cid
        != contract.executor_identity_cid
        or request.command != contract.command_template
        or replay.request_sha256 != request.request_sha256
        or replay.source_execution_receipt_sha256
        != request.source_execution_receipt_sha256
        or request.source_execution_receipt_sha256
        != expected_source_receipt_sha256
        or replay.source_worktree_receipt_sha256
        != request.source_worktree_receipt_sha256
        or request.source_run_id
        != source_policy.run_id
        or request.replay_run_id
        != namespace_receipt.replay_run_id
        or request.source_commit != replay.source_commit
        or request.environment_sha256 != replay.environment_sha256
        or request.environment_sha256 != contract.environment_sha256
        or source_stage_environments != {contract.environment_sha256}
        or replay_stage_environments != {contract.environment_sha256}
        or replay_stage_environments != {request.environment_sha256}
        or request.source_process_namespace
        != source_namespace_receipt.process_namespace_cid
        or request.replay_process_namespace
        != namespace_receipt.replay_process_namespace_cid
        or not all(
            source_cache_set_cid in logical_namespace
            for logical_namespace in request.source_cache_namespaces
        )
        or request.replay_cache_namespace != replay.cache_namespace
        or cache_set_cid not in request.replay_cache_namespace
        or namespace_receipt.replay_run_id != replay.replay_run_id
        or namespace_receipt.replay_run_id != worktree.run_id
        or namespace_receipt.replay_worktree_cid
        != worktree_projection_cid
        or replay.replay_worktree_receipt_sha256 != worktree.sha256
        or replay.process_namespace
        != namespace_receipt.replay_process_namespace_cid
        or replay.source_commit != worktree.worktree_commit
        or replay.source_commit != worktree.base_commit
        or not evidence_canonical
    ):
        raise RuntimeNamespaceProvenanceError(
            "G240 actual replay/worktree outputs differ from namespace "
            "or runtime evidence"
        )
    observer = _cid(
        orchestration_observer_identity_cid,
        "orchestration_observer_identity_cid",
    )
    if observer in {
        source_policy.namespace_authority_cid,
        namespace_receipt.replay_executor_identity_cid,
        namespace_receipt.replay_observer_identity_cid,
    }:
        raise RuntimeNamespaceProvenanceError(
            "G240 orchestration observer must be independent"
        )
    return G240ReplayOrchestrationReceiptV2(
        source_policy_cid=str(source_policy.policy_cid),
        runtime_orchestration_policy_cid=str(contract.contract_cid),
        command_cid=contract.command_template_cid,
        interpreter_identity_cid=contract.interpreter_identity_cid,
        confinement_profile_cid=(
            G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2
        ),
        namespace_receipt_cid=str(namespace_receipt.receipt_cid),
        source_runtime_evidence_cid=(
            namespace_receipt.source_runtime_evidence_cid
        ),
        replay_runtime_evidence_cid=runtime.receipt_cid,
        source_commit_cid=source_policy.source_commit_cid,
        recursive_gitlinks_cid=source_policy.recursive_gitlinks_cid,
        replay_run_id=namespace_receipt.replay_run_id,
        replay_worktree_cid=namespace_receipt.replay_worktree_cid,
        replay_process_namespace_cid=(
            namespace_receipt.replay_process_namespace_cid
        ),
        replay_state_namespace_cid=(
            namespace_receipt.replay_state_namespace_cid
        ),
        replay_output_namespace_cid=(
            namespace_receipt.replay_output_namespace_cid
        ),
        replay_cache_namespace_set_cid=cache_set_cid,
        replay_request_cid=request_cid,
        legacy_replay_receipt_cid=replay_projection_cid,
        worktree_safety_projection_cid=worktree_projection_cid,
        runtime_preflight_cid=runtime_preflight_cid,
        landlock_policy_cid=landlock_policy_cid,
        landlock_receipt_cid=landlock_receipt_cid,
        landlock_receipt_payload_cid=(
            landlock_receipt_payload_cid
        ),
        evidence_payload_cid=cid_for_bytes(evidence_payload),
        orchestration_observer_identity_cid=observer,
        detached=bool(replay.detached and worktree.detached),
        auto_merge=bool(replay.auto_merge or worktree.auto_merge),
        process_group_reaped=observed_process.process_group_reaped,
        active_process_count_after_reap=(
            observed_process.active_process_count_after_reap
        ),
        evidence_canonical=evidence_canonical,
        synthetic_test_only=synthetic_test_only,
        complete=True,
        holdout_accessed=holdout_accessed,
    )


def validate_g240_replay_orchestration_receipt_v2(
    value: object,
    **sources: object,
) -> G240ReplayOrchestrationReceiptV2:
    """Rebuild the path-free receipt from actual replay/worktree outputs."""

    receipt = (
        value
        if isinstance(value, G240ReplayOrchestrationReceiptV2)
        else G240ReplayOrchestrationReceiptV2.from_dict(value)
    )
    rebuilt = _build_g240_replay_orchestration_receipt_v2(
        **sources,  # type: ignore[arg-type]
        orchestration_observer_identity_cid=(
            receipt.orchestration_observer_identity_cid
        ),
        active_process_count_after_reap=(
            receipt.active_process_count_after_reap
        ),
        holdout_accessed=receipt.holdout_accessed,
    )
    if _plain(receipt.to_dict()) != _plain(rebuilt.to_dict()):
        raise RuntimeNamespaceProvenanceError(
            "G240 replay orchestration receipt did not source-recompute"
        )
    return rebuilt


@dataclass(frozen=True, slots=True)
class G240PrivateReplayValidationSourcesV2:
    """Non-serializable sources used to authenticate one replay receipt.

    These values deliberately retain live checkout paths and exact evidence
    bytes.  They are validator inputs only and must never be written into a
    public receipt, task board, or report.
    """

    source_policy: object
    executor_contract: object
    source_namespace_receipt: object
    namespace_receipt: object
    orchestration_receipt: object
    source_worktree_safety_receipt: object
    replay_request: object
    replay_receipt: object
    replay_worktree_safety_receipt: object
    evidence_payload: bytes
    replay_execution_request: object | None = None
    execution_request_payload: bytes | None = None
    runtime_preflight_payload: bytes | None = None
    landlock_policy_sources: object | None = None
    landlock_receipt: object | None = None
    landlock_receipt_payload: bytes | None = None
    landlock_transport_observation: object | None = None

    def __post_init__(self) -> None:
        try:
            from .replay import (
                _G240_REPLAY_PRIVATE_EXECUTION_CAPABILITY_V2,
                _G240ReplayPrivateExecutionSourcesV2,
            )

            bundle = getattr(
                self.replay_receipt,
                "_g240_private_execution_sources",
                None,
            )
        except (AttributeError, ImportError) as exc:
            raise RuntimeNamespaceProvenanceError(
                "G240 private replay launch sources are unavailable"
            ) from exc
        if (
            not isinstance(
                bundle,
                _G240ReplayPrivateExecutionSourcesV2,
            )
            or bundle._capability
            is not _G240_REPLAY_PRIVATE_EXECUTION_CAPABILITY_V2
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 private replay lacks live process/bootstrap authority"
            )
        transport = bundle.landlock_transport_observation
        expected_policy_sources = (
            None if transport is None else transport.policy_sources
        )
        expected_landlock_receipt = (
            None if transport is None else transport.receipt
        )
        expected_landlock_payload = (
            None if transport is None else transport.receipt_payload
        )
        values = {
            "replay_execution_request": bundle.execution_request,
            "execution_request_payload": (
                bundle.execution_request_payload
            ),
            "runtime_preflight_payload": (
                bundle.runtime_preflight_payload
            ),
            "landlock_policy_sources": expected_policy_sources,
            "landlock_receipt": expected_landlock_receipt,
            "landlock_receipt_payload": expected_landlock_payload,
            "landlock_transport_observation": transport,
        }
        for name, expected in values.items():
            observed = getattr(self, name)
            if observed is None:
                object.__setattr__(self, name, expected)
            elif isinstance(expected, bytes):
                if observed != expected:
                    raise RuntimeNamespaceProvenanceError(
                        f"G240 private replay {name} differs from launch"
                    )
            elif observed is not expected:
                raise RuntimeNamespaceProvenanceError(
                    f"G240 private replay {name} differs from launch"
                )
        if (
            not isinstance(self.evidence_payload, bytes)
            or not isinstance(self.execution_request_payload, bytes)
            or not isinstance(self.runtime_preflight_payload, bytes)
            or (
                self.landlock_receipt_payload is not None
                and not isinstance(
                    self.landlock_receipt_payload,
                    bytes,
                )
            )
        ):
            raise RuntimeNamespaceProvenanceError(
                "G240 private replay payloads must be exact bytes"
            )


def validate_g240_private_replay_sources_v2(
    value: G240PrivateReplayValidationSourcesV2,
    *,
    source_runtime_evidence: CausalRuntimeEvidenceV2,
    replay_runtime_evidence: CausalRuntimeEvidenceV2,
) -> tuple[
    G240NamespacePolicyV2,
    G240RuntimeNamespaceReceiptV2,
    G240ReplayNamespaceReceiptV2,
    G240ReplayOrchestrationReceiptV2,
]:
    """Validate one G238 replay against live Git and exact process outputs."""

    if not isinstance(value, G240PrivateReplayValidationSourcesV2):
        raise RuntimeNamespaceProvenanceError(
            "G240 operational replay validation requires private live sources"
        )
    try:
        from .capabilities import WorktreeSafetyReceipt
        from .replay import (
            ReplayReceipt,
            ReplayRequest,
            _coerce_g240_executor_contract_v2,
            _validate_g240_executor_entrypoint_v2,
            _validate_live_worktree,
        )
        from .replay_gate import g238_git_commit_cid
        from .source_reconciliation import (
            _capture_benchmark_bounded_gitlinks,
        )

        policy = (
            value.source_policy
            if isinstance(value.source_policy, G240NamespacePolicyV2)
            else G240NamespacePolicyV2.from_dict(value.source_policy)
        )
        contract = _coerce_g240_executor_contract_v2(
            value.executor_contract,
            source_policy=policy,
        )
        source_receipt = (
            value.source_namespace_receipt
            if isinstance(
                value.source_namespace_receipt,
                G240RuntimeNamespaceReceiptV2,
            )
            else G240RuntimeNamespaceReceiptV2.from_dict(
                value.source_namespace_receipt
            )
        )
        namespace_receipt = (
            value.namespace_receipt
            if isinstance(
                value.namespace_receipt,
                G240ReplayNamespaceReceiptV2,
            )
            else G240ReplayNamespaceReceiptV2.from_dict(
                value.namespace_receipt
            )
        )
        orchestration_receipt = (
            value.orchestration_receipt
            if isinstance(
                value.orchestration_receipt,
                G240ReplayOrchestrationReceiptV2,
            )
            else G240ReplayOrchestrationReceiptV2.from_dict(
                value.orchestration_receipt
            )
        )
        source_worktree = (
            value.source_worktree_safety_receipt
            if isinstance(
                value.source_worktree_safety_receipt,
                WorktreeSafetyReceipt,
            )
            else WorktreeSafetyReceipt.from_dict(
                value.source_worktree_safety_receipt
            )
        )
        replay_request = (
            value.replay_request
            if isinstance(value.replay_request, ReplayRequest)
            else ReplayRequest.from_dict(value.replay_request)
        )
        replay_receipt = (
            value.replay_receipt
            if isinstance(value.replay_receipt, ReplayReceipt)
            else ReplayReceipt.from_dict(value.replay_receipt)
        )
        replay_worktree = (
            value.replay_worktree_safety_receipt
            if isinstance(
                value.replay_worktree_safety_receipt,
                WorktreeSafetyReceipt,
            )
            else WorktreeSafetyReceipt.from_dict(
                value.replay_worktree_safety_receipt
            )
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeNamespaceProvenanceError(
            "G240 private replay sources failed typed validation"
        ) from exc
    source_runtime = validate_causal_runtime_evidence_v2(
        source_runtime_evidence.to_dict()
    )
    replay_runtime = validate_causal_runtime_evidence_v2(
        replay_runtime_evidence.to_dict()
    )
    source_receipt = validate_g240_runtime_namespace_receipt_from_policy_v2(
        source_receipt,
        policy=policy,
        evidence=source_runtime,
    )
    namespace_receipt = validate_g240_replay_namespace_receipt_v2(
        namespace_receipt,
        source_policy=policy,
        source_receipt=source_receipt,
        source_runtime_evidence=source_runtime,
        replay_runtime_evidence=replay_runtime,
    )
    try:
        source_gitlinks = _capture_benchmark_bounded_gitlinks(
            source_worktree.worktree_root,
            source_worktree.worktree_commit,
        )
        replay_gitlinks = _capture_benchmark_bounded_gitlinks(
            replay_worktree.worktree_root,
            replay_worktree.worktree_commit,
        )
        _validate_live_worktree(
            source_worktree,
            source_worktree.worktree_commit,
            source_gitlinks,
        )
        _validate_live_worktree(
            replay_worktree,
            replay_worktree.worktree_commit,
            replay_gitlinks,
        )
        source_entrypoint = _validate_g240_executor_entrypoint_v2(
            contract,
            source_worktree,
        )
        replay_entrypoint = _validate_g240_executor_entrypoint_v2(
            contract,
            replay_worktree,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeNamespaceProvenanceError(
            "G240 replay source or detached worktree is not live and clean"
        ) from exc
    if (
        source_gitlinks != replay_gitlinks
        or source_entrypoint != replay_entrypoint
        or g240_recursive_gitlinks_cid(source_gitlinks)
        != policy.recursive_gitlinks_cid
        or source_worktree.run_id != policy.run_id
        or source_worktree.base_commit
        != source_worktree.worktree_commit
        or g238_git_commit_cid(source_worktree.worktree_commit)
        != policy.source_commit_cid
        or replay_worktree.base_commit
        != source_worktree.worktree_commit
        or replay_worktree.worktree_commit
        != source_worktree.worktree_commit
        or replay_request.source_worktree_receipt_sha256
        != source_worktree.sha256
        or replay_request.source_execution_receipt_sha256
        != hashlib.sha256(
            canonical_json(source_receipt.to_dict()).encode("utf-8")
        ).hexdigest()
        or replay_request.command != contract.command_template
        or source_receipt.executor_identity_cid
        != contract.executor_identity_cid
        or {
            stage.provenance.environment_sha256
            for stage in (
                *source_runtime.semantic_frontend,
                *source_runtime.case_result.stages,
            )
        }
        != {contract.environment_sha256}
        or {
            stage.provenance.environment_sha256
            for stage in (
                *replay_runtime.semantic_frontend,
                *replay_runtime.case_result.stages,
            )
        }
        != {contract.environment_sha256}
        or replay_request.environment_sha256
        != contract.environment_sha256
    ):
        raise RuntimeNamespaceProvenanceError(
            "G240 live source/replay Git evidence differs from policy"
        )
    orchestration_receipt = (
        validate_g240_replay_orchestration_receipt_v2(
            orchestration_receipt,
            source_policy=policy,
            source_namespace_receipt=source_receipt,
            namespace_receipt=namespace_receipt,
            source_runtime_evidence=source_runtime,
            replay_runtime_evidence=replay_runtime,
            executor_contract=contract,
            replay_request=replay_request,
            replay_receipt=replay_receipt,
            worktree_safety_receipt=replay_worktree,
            replay_execution_request=(
                value.replay_execution_request
            ),
            execution_request_payload=(
                value.execution_request_payload
            ),
            runtime_preflight_payload=(
                value.runtime_preflight_payload
            ),
            landlock_transport_observation=(
                value.landlock_transport_observation
            ),
            evidence_payload=value.evidence_payload,
        )
    )
    return (
        policy,
        source_receipt,
        namespace_receipt,
        orchestration_receipt,
    )


__all__ = [
    "G240_CACHE_KEY_OBSERVATION_SCHEMA_V2",
    "G240_CACHE_NAMESPACE_SET_SCHEMA_V2",
    "G240_JOB_NAMESPACE_PLAN_SCHEMA_V2",
    "G240_NAMESPACE_CONTEXT_SCHEMA_V2",
    "G240_NAMESPACE_POLICY_SCHEMA_V2",
    "G240_NAMESPACE_PREIMAGE_SCHEMA_V2",
    "G240_RUNTIME_NAMESPACE_EVIDENCE_SET_SCHEMA_V2",
    "G240_RUNTIME_NAMESPACE_RECEIPT_SCHEMA_V2",
    "G240_REPLAY_NAMESPACE_CONTEXT_SCHEMA_V2",
    "G240_REPLAY_NAMESPACE_RECEIPT_SCHEMA_V2",
    "G240_REPLAY_ORCHESTRATION_RECEIPT_SCHEMA_V2",
    "G240_RECURSIVE_GITLINKS_PROJECTION_SCHEMA_V2",
    "G240_REPLAY_WORKTREE_PROJECTION_SCHEMA_V2",
    "G240JobNamespacePlanV2",
    "G240NamespacePolicyV2",
    "G240PrivateReplayValidationSourcesV2",
    "G240ReplayNamespaceReceiptV2",
    "G240ReplayOrchestrationReceiptV2",
    "G240RuntimeNamespaceEvidenceSetV2",
    "G240RuntimeNamespaceReceiptV2",
    "RuntimeNamespaceProvenanceError",
    "build_g240_namespace_policy_v2",
    "g240_cache_namespace_set_cid",
    "g240_recursive_gitlinks_cid",
    "g240_replay_namespace_request_v2",
    "g240_worktree_safety_projection_cid",
    "validate_g240_namespace_policy_v2",
    "validate_g240_replay_namespace_receipt_v2",
    "validate_g240_replay_orchestration_receipt_v2",
    "validate_g240_private_replay_sources_v2",
    "validate_g240_runtime_namespace_evidence_set_v2",
    "validate_g240_runtime_namespace_population_v2",
    "validate_g240_runtime_namespace_receipt_v2",
    "validate_g240_runtime_namespace_receipt_from_policy_v2",
]
