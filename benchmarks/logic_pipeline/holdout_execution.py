"""Fail-closed authorized execution for the frozen paired holdout.

The generic ablation executor deliberately refuses ``Split.HOLDOUT``.  This
module is the only supported bridge across that boundary.  It validates a
content-addressed, source-bound pilot authorization and every per-contract
holdout access audit before it creates a file or invokes an adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Final, Mapping, Sequence

from .ablation import (
    AblationPlan,
    AblationRunResult,
    ResourceLimits,
    _execute_ablation,
    build_ablation_plan,
)
from .capabilities import ResourceScheduler
from .cases import (
    HoldoutAccessAudit,
    ReviewedCorpus,
    build_split_integrity_manifest,
    validate_holdout_access_log,
)
from .contracts import (
    DEFAULT_PROTOCOL_SHA256,
    CacheMode,
    Split,
    canonical_json,
)
from .variants import VARIANT_REGISTRY, get_variant_definition


PILOT_AUTHORIZATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.pilot-holdout-authorization.v1"
)
HOLDOUT_EXECUTION_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.authorized-holdout-execution.v1"
)
HOLDOUT_AUTHORIZATION_FILE: Final = "holdout-authorization.json"
HOLDOUT_EXECUTION_RECEIPT_FILE: Final = "holdout-execution-receipt.json"
HOLDOUT_ACCESS_AUDITS_FILE: Final = "holdout-access-audits.json"
MAX_SHORTLIST_SIZE: Final = 4
_SAFE_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_DIGEST: Final = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT: Final = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")


class HoldoutExecutionError(ValueError):
    """Raised before an unauthorized or drifted holdout can execute."""


def HSSLEV1167A17() -> str:
    """Return AST-verifiable evidence for authorized holdout and replay."""

    return (
        "source-bound fail-closed holdout authorization and fresh detached "
        "replay orchestration with isolated run, process, and cache namespaces"
    )


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise HoldoutExecutionError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _commit(value: object, field: str) -> str:
    if not isinstance(value, str) or not _COMMIT.fullmatch(value):
        raise HoldoutExecutionError(
            f"{field} must be a full lowercase Git commit id"
        )
    return value


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise HoldoutExecutionError(f"{field} must be a safe nonempty identifier")
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise HoldoutExecutionError(f"{field} must be an object with string keys")
    return value


def _exact(
    value: Mapping[str, object], expected: set[str], field: str
) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise HoldoutExecutionError(
            f"{field} fields changed (missing={missing}, extra={extra})"
        )


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _authorization_payload(
    *,
    schema: str,
    authorization_id: str,
    pilot_run_id: str,
    pilot_gate_sha256: str,
    source_commit: str,
    environment_sha256: str,
    protocol_sha256: str,
    corpus_manifest_sha256: str,
    holdout_split_sha256: str,
    shortlist_variant_ids: tuple[str, ...],
    configuration_sha256s: Mapping[str, str],
    prompts_sha256: str,
    policy_sha256: str,
    model_identities_sha256: str,
    thresholds_sha256: str,
    passed: bool,
    shortlist_frozen: bool,
    holdout_authorized: bool,
    outcomes_inspected: bool,
    tuning_permitted: bool,
) -> dict[str, object]:
    return {
        "schema": schema,
        "authorization_id": authorization_id,
        "pilot_run_id": pilot_run_id,
        "pilot_gate_sha256": pilot_gate_sha256,
        "source_commit": source_commit,
        "environment_sha256": environment_sha256,
        "protocol_sha256": protocol_sha256,
        "corpus_manifest_sha256": corpus_manifest_sha256,
        "holdout_split_sha256": holdout_split_sha256,
        "shortlist_variant_ids": list(shortlist_variant_ids),
        "configuration_sha256s": dict(configuration_sha256s),
        "prompts_sha256": prompts_sha256,
        "policy_sha256": policy_sha256,
        "model_identities_sha256": model_identities_sha256,
        "thresholds_sha256": thresholds_sha256,
        "passed": passed,
        "shortlist_frozen": shortlist_frozen,
        "holdout_authorized": holdout_authorized,
        "outcomes_inspected": outcomes_inspected,
        "tuning_permitted": tuning_permitted,
    }


@dataclass(frozen=True, slots=True)
class PilotAuthorizationReceipt:
    """Immutable handoff from a completed source-bound pilot gate."""

    schema: str
    authorization_id: str
    pilot_run_id: str
    pilot_gate_sha256: str
    source_commit: str
    environment_sha256: str
    protocol_sha256: str
    corpus_manifest_sha256: str
    holdout_split_sha256: str
    shortlist_variant_ids: tuple[str, ...]
    configuration_sha256s: Mapping[str, str]
    prompts_sha256: str
    policy_sha256: str
    model_identities_sha256: str
    thresholds_sha256: str
    passed: bool
    shortlist_frozen: bool
    holdout_authorized: bool
    outcomes_inspected: bool
    tuning_permitted: bool
    authorization_sha256: str

    def __post_init__(self) -> None:
        if self.schema != PILOT_AUTHORIZATION_SCHEMA:
            raise HoldoutExecutionError("unsupported pilot authorization schema")
        _safe_id(self.authorization_id, "authorization_id")
        _safe_id(self.pilot_run_id, "pilot_run_id")
        _digest(self.pilot_gate_sha256, "pilot_gate_sha256")
        _commit(self.source_commit, "source_commit")
        for name in (
            "environment_sha256",
            "protocol_sha256",
            "corpus_manifest_sha256",
            "holdout_split_sha256",
            "prompts_sha256",
            "policy_sha256",
            "model_identities_sha256",
            "thresholds_sha256",
            "authorization_sha256",
        ):
            _digest(getattr(self, name), name)
        if self.protocol_sha256 != DEFAULT_PROTOCOL_SHA256:
            raise HoldoutExecutionError(
                "authorization does not bind frozen protocol revision 1"
            )
        shortlist = tuple(self.shortlist_variant_ids)
        if (
            not shortlist
            or len(shortlist) > MAX_SHORTLIST_SIZE
            or len(shortlist) != len(set(shortlist))
            or any(
                item not in VARIANT_REGISTRY or item in {"A0", "S1"}
                for item in shortlist
            )
        ):
            raise HoldoutExecutionError(
                "shortlist must contain one to four distinct candidate arms"
            )
        object.__setattr__(self, "shortlist_variant_ids", shortlist)
        configurations = _mapping(
            self.configuration_sha256s, "configuration_sha256s"
        )
        expected_variants = {"A0", *shortlist}
        if set(configurations) != expected_variants:
            raise HoldoutExecutionError(
                "authorization configurations must exactly cover A0 and shortlist"
            )
        normalized: dict[str, str] = {}
        for variant_id, value in configurations.items():
            digest = _digest(value, f"configuration_sha256s.{variant_id}")
            if digest != get_variant_definition(variant_id).digest:
                raise HoldoutExecutionError(
                    f"frozen configuration drifted for {variant_id}"
                )
            normalized[variant_id] = digest
        object.__setattr__(
            self,
            "configuration_sha256s",
            MappingProxyType(dict(sorted(normalized.items()))),
        )
        for name, expected in (
            ("passed", True),
            ("shortlist_frozen", True),
            ("holdout_authorized", True),
            ("outcomes_inspected", False),
            ("tuning_permitted", False),
        ):
            if getattr(self, name) is not expected:
                raise HoldoutExecutionError(
                    f"pilot authorization requires {name}={expected!r}"
                )
        if self.authorization_sha256 != _sha(self.identity_payload()):
            raise HoldoutExecutionError(
                "authorization_sha256 does not match authorization content"
            )

    def identity_payload(self) -> dict[str, object]:
        return _authorization_payload(
            schema=self.schema,
            authorization_id=self.authorization_id,
            pilot_run_id=self.pilot_run_id,
            pilot_gate_sha256=self.pilot_gate_sha256,
            source_commit=self.source_commit,
            environment_sha256=self.environment_sha256,
            protocol_sha256=self.protocol_sha256,
            corpus_manifest_sha256=self.corpus_manifest_sha256,
            holdout_split_sha256=self.holdout_split_sha256,
            shortlist_variant_ids=self.shortlist_variant_ids,
            configuration_sha256s=self.configuration_sha256s,
            prompts_sha256=self.prompts_sha256,
            policy_sha256=self.policy_sha256,
            model_identities_sha256=self.model_identities_sha256,
            thresholds_sha256=self.thresholds_sha256,
            passed=self.passed,
            shortlist_frozen=self.shortlist_frozen,
            holdout_authorized=self.holdout_authorized,
            outcomes_inspected=self.outcomes_inspected,
            tuning_permitted=self.tuning_permitted,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "authorization_sha256": self.authorization_sha256,
        }

    @classmethod
    def create(
        cls,
        *,
        authorization_id: str,
        pilot_run_id: str,
        pilot_gate_sha256: str,
        source_commit: str,
        environment_sha256: str,
        corpus_manifest_sha256: str,
        holdout_split_sha256: str,
        shortlist_variant_ids: Sequence[str],
        prompts_sha256: str,
        policy_sha256: str,
        model_identities_sha256: str,
        thresholds_sha256: str,
        protocol_sha256: str = DEFAULT_PROTOCOL_SHA256,
    ) -> "PilotAuthorizationReceipt":
        """Create the strict handoff after an upstream pilot validator passes."""

        shortlist = tuple(shortlist_variant_ids)
        configurations = {
            variant_id: get_variant_definition(variant_id).digest
            for variant_id in ("A0", *shortlist)
            if variant_id in VARIANT_REGISTRY
        }
        payload = _authorization_payload(
            schema=PILOT_AUTHORIZATION_SCHEMA,
            authorization_id=authorization_id,
            pilot_run_id=pilot_run_id,
            pilot_gate_sha256=pilot_gate_sha256,
            source_commit=source_commit,
            environment_sha256=environment_sha256,
            protocol_sha256=protocol_sha256,
            corpus_manifest_sha256=corpus_manifest_sha256,
            holdout_split_sha256=holdout_split_sha256,
            shortlist_variant_ids=shortlist,
            configuration_sha256s=configurations,
            prompts_sha256=prompts_sha256,
            policy_sha256=policy_sha256,
            model_identities_sha256=model_identities_sha256,
            thresholds_sha256=thresholds_sha256,
            passed=True,
            shortlist_frozen=True,
            holdout_authorized=True,
            outcomes_inspected=False,
            tuning_permitted=False,
        )
        return cls(
            **payload,  # type: ignore[arg-type]
            authorization_sha256=_sha(payload),
        )

    @classmethod
    def from_dict(cls, value: object) -> "PilotAuthorizationReceipt":
        data = _mapping(value, "pilot authorization")
        _exact(data, set(cls.__dataclass_fields__), "pilot authorization")
        shortlist = data["shortlist_variant_ids"]
        if not isinstance(shortlist, list):
            raise HoldoutExecutionError("shortlist_variant_ids must be an array")
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            authorization_id=data["authorization_id"],  # type: ignore[arg-type]
            pilot_run_id=data["pilot_run_id"],  # type: ignore[arg-type]
            pilot_gate_sha256=data["pilot_gate_sha256"],  # type: ignore[arg-type]
            source_commit=data["source_commit"],  # type: ignore[arg-type]
            environment_sha256=data["environment_sha256"],  # type: ignore[arg-type]
            protocol_sha256=data["protocol_sha256"],  # type: ignore[arg-type]
            corpus_manifest_sha256=data["corpus_manifest_sha256"],  # type: ignore[arg-type]
            holdout_split_sha256=data["holdout_split_sha256"],  # type: ignore[arg-type]
            shortlist_variant_ids=tuple(shortlist),  # type: ignore[arg-type]
            configuration_sha256s=_mapping(
                data["configuration_sha256s"], "configuration_sha256s"
            ),  # type: ignore[arg-type]
            prompts_sha256=data["prompts_sha256"],  # type: ignore[arg-type]
            policy_sha256=data["policy_sha256"],  # type: ignore[arg-type]
            model_identities_sha256=data["model_identities_sha256"],  # type: ignore[arg-type]
            thresholds_sha256=data["thresholds_sha256"],  # type: ignore[arg-type]
            passed=data["passed"],  # type: ignore[arg-type]
            shortlist_frozen=data["shortlist_frozen"],  # type: ignore[arg-type]
            holdout_authorized=data["holdout_authorized"],  # type: ignore[arg-type]
            outcomes_inspected=data["outcomes_inspected"],  # type: ignore[arg-type]
            tuning_permitted=data["tuning_permitted"],  # type: ignore[arg-type]
            authorization_sha256=data["authorization_sha256"],  # type: ignore[arg-type]
        )


def build_authorized_holdout_plan(
    authorization: PilotAuthorizationReceipt,
    corpus: ReviewedCorpus,
    *,
    run_id: str,
    seed: int,
    access_ledger_id: str,
    limits: ResourceLimits = ResourceLimits(),
) -> AblationPlan:
    """Build the exact A0/shortlist cold/warm holdout schedule."""

    if not isinstance(authorization, PilotAuthorizationReceipt):
        raise HoldoutExecutionError(
            "authorization must be a PilotAuthorizationReceipt"
        )
    if not isinstance(corpus, ReviewedCorpus):
        raise HoldoutExecutionError("corpus must be a ReviewedCorpus")
    _safe_id(access_ledger_id, "access_ledger_id")
    integrity = build_split_integrity_manifest(corpus)
    if (
        corpus.manifest_sha256 != authorization.corpus_manifest_sha256
        or integrity.holdout.split_sha256
        != authorization.holdout_split_sha256
    ):
        raise HoldoutExecutionError(
            "authorization corpus or holdout split identity is stale"
        )
    positions = {case.case_id: case for case in corpus.cases}
    holdout_cases = tuple(
        positions[case_id] for case_id in integrity.holdout.case_ids
    )
    return build_ablation_plan(
        run_id,
        holdout_cases,
        case_manifest_sha256=corpus.manifest_sha256,
        split=Split.HOLDOUT,
        seed=seed,
        variant_ids=("A0", *authorization.shortlist_variant_ids),
        cache_modes=(CacheMode.COLD, CacheMode.WARM),
        limits=limits,
        environment_sha256=authorization.environment_sha256,
        holdout_access_log_id=access_ledger_id,
    )


def build_holdout_access_audits(
    authorization: PilotAuthorizationReceipt,
    corpus: ReviewedCorpus,
    plan: AblationPlan,
    *,
    prompt_examples: Mapping[str, str],
    purpose: str = "evaluation",
) -> tuple[HoldoutAccessAudit, ...]:
    """Build one ordered, unique, no-tuning audit per run contract."""

    audits = tuple(
        HoldoutAccessAudit.from_run_contract(
            corpus,
            contract,
            prompts_sha256=authorization.prompts_sha256,
            policy_sha256=authorization.policy_sha256,
            model_identities_sha256=authorization.model_identities_sha256,
            thresholds_sha256=authorization.thresholds_sha256,
            prompt_examples=prompt_examples,
            sequence=sequence,
            purpose=purpose,
        )
        for sequence, contract in enumerate(plan.run_contracts)
    )
    validate_holdout_access_log(corpus, audits)
    return audits


def _validate_execution_boundary(
    authorization: PilotAuthorizationReceipt,
    corpus: ReviewedCorpus,
    plan: AblationPlan,
    access_audits: Sequence[HoldoutAccessAudit],
    *,
    source_commit: str,
    environment_sha256: str,
    output_root: str | Path,
    purpose: str,
) -> tuple[HoldoutAccessAudit, ...]:
    """Validate the complete boundary without causing filesystem side effects."""

    try:
        authorization = PilotAuthorizationReceipt.from_dict(
            authorization.to_dict()
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise HoldoutExecutionError("pilot authorization is invalid") from exc
    if not isinstance(corpus, ReviewedCorpus):
        raise HoldoutExecutionError("corpus must be a ReviewedCorpus")
    if not isinstance(plan, AblationPlan):
        raise HoldoutExecutionError("plan must be an AblationPlan")
    if plan.split is not Split.HOLDOUT:
        raise HoldoutExecutionError("authorized execution requires a holdout plan")
    if (
        _commit(source_commit, "source_commit") != authorization.source_commit
        or _digest(environment_sha256, "environment_sha256")
        != authorization.environment_sha256
        or plan.environment_sha256 != authorization.environment_sha256
        or plan.protocol_sha256 != authorization.protocol_sha256
        or plan.case_manifest_sha256 != authorization.corpus_manifest_sha256
    ):
        raise HoldoutExecutionError(
            "source, environment, protocol, or corpus identity drifted"
        )
    integrity = build_split_integrity_manifest(corpus)
    if (
        corpus.manifest_sha256 != authorization.corpus_manifest_sha256
        or integrity.holdout.split_sha256
        != authorization.holdout_split_sha256
        or plan.case_ids != integrity.holdout.case_ids
    ):
        raise HoldoutExecutionError(
            "plan does not use the complete frozen holdout manifest in order"
        )
    if plan.variant_ids != ("A0", *authorization.shortlist_variant_ids):
        raise HoldoutExecutionError(
            "plan must schedule only A0 and the exact frozen shortlist"
        )
    if plan.cache_modes != (CacheMode.COLD, CacheMode.WARM):
        raise HoldoutExecutionError(
            "holdout must keep complete, separate cold and warm pairs"
        )
    if plan.holdout_access_log_id is None:
        raise HoldoutExecutionError("holdout plan has no access ledger identity")

    contracts = plan.run_contracts
    audits: tuple[HoldoutAccessAudit, ...]
    try:
        audits = tuple(
            HoldoutAccessAudit.from_dict(item.to_dict())
            for item in access_audits
        )
        validate_holdout_access_log(corpus, audits)
    except (AttributeError, TypeError, ValueError) as exc:
        raise HoldoutExecutionError("holdout access audit log is invalid") from exc
    if len(audits) != len(contracts):
        raise HoldoutExecutionError(
            "one holdout access audit is required per run contract"
        )
    for sequence, (contract, audit) in enumerate(zip(contracts, audits)):
        expected_run_digest = _sha(contract.to_dict())
        if (
            audit.sequence != sequence
            or audit.purpose != purpose
            or audit.audit_id != contract.holdout_access_log_id
            or audit.run_contract_sha256 != expected_run_digest
            or audit.run_id != contract.run_id
            or audit.protocol_sha256 != contract.protocol_sha256
            or audit.variant_id != contract.requested_variant_id
            or audit.cache_namespace != contract.cache_namespace
            or audit.cache_mode != contract.cache_mode.value
            or audit.configuration_sha256 != contract.configuration_sha256
            or audit.configuration_sha256
            != authorization.configuration_sha256s[
                contract.requested_variant_id
            ]
            or audit.prompts_sha256 != authorization.prompts_sha256
            or audit.policy_sha256 != authorization.policy_sha256
            or audit.model_identities_sha256
            != authorization.model_identities_sha256
            or audit.thresholds_sha256 != authorization.thresholds_sha256
            or audit.accessed_case_ids != integrity.holdout.case_ids
            or audit.tuning_permitted is not False
        ):
            raise HoldoutExecutionError(
                "holdout access audit differs from its frozen run contract"
            )

    root = Path(output_root)
    if isinstance(output_root, str) and not output_root.strip():
        raise HoldoutExecutionError("output_root must not be empty")
    if root.exists() or root.is_symlink():
        raise HoldoutExecutionError(
            "holdout output namespace must be fresh; resume is forbidden"
        )
    return audits


@dataclass(frozen=True, slots=True)
class HoldoutExecutionReceipt:
    """Content-addressed completion receipt for one authorized holdout run."""

    schema: str
    evidence: str
    run_id: str
    source_commit: str
    environment_sha256: str
    authorization_sha256: str
    pilot_gate_sha256: str
    plan_sha256: str
    access_audit_sha256s: tuple[str, ...]
    result_sha256s: tuple[str, ...]
    cache_namespaces: tuple[str, ...]
    executed_job_ids: tuple[str, ...]
    complete: bool
    receipt_sha256: str

    def __post_init__(self) -> None:
        if self.schema != HOLDOUT_EXECUTION_RECEIPT_SCHEMA:
            raise HoldoutExecutionError("unsupported holdout execution receipt")
        if self.evidence != HSSLEV1167A17():
            raise HoldoutExecutionError("holdout evidence marker changed")
        _safe_id(self.run_id, "run_id")
        _commit(self.source_commit, "source_commit")
        for name in (
            "environment_sha256",
            "authorization_sha256",
            "pilot_gate_sha256",
            "plan_sha256",
            "receipt_sha256",
        ):
            _digest(getattr(self, name), name)
        for name in ("access_audit_sha256s", "result_sha256s"):
            values = tuple(getattr(self, name))
            if not values or any(
                not isinstance(value, str) or not _DIGEST.fullmatch(value)
                for value in values
            ):
                raise HoldoutExecutionError(f"{name} must contain SHA-256 digests")
            object.__setattr__(self, name, values)
        namespaces = tuple(self.cache_namespaces)
        jobs = tuple(self.executed_job_ids)
        if (
            not namespaces
            or len(namespaces) != len(set(namespaces))
            or not jobs
            or len(jobs) != len(set(jobs))
        ):
            raise HoldoutExecutionError(
                "execution receipt requires distinct cache and job identities"
            )
        object.__setattr__(self, "cache_namespaces", namespaces)
        object.__setattr__(self, "executed_job_ids", jobs)
        if self.complete is not True:
            raise HoldoutExecutionError("holdout execution receipt must be complete")
        if self.receipt_sha256 != _sha(self.identity_payload()):
            raise HoldoutExecutionError("holdout receipt digest changed")

    def identity_payload(self) -> dict[str, object]:
        return {
            name: (
                list(getattr(self, name))
                if name
                in {
                    "access_audit_sha256s",
                    "result_sha256s",
                    "cache_namespaces",
                    "executed_job_ids",
                }
                else getattr(self, name)
            )
            for name in self.__dataclass_fields__
            if name != "receipt_sha256"
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_sha256": self.receipt_sha256}

    @classmethod
    def from_dict(cls, value: object) -> "HoldoutExecutionReceipt":
        data = _mapping(value, "holdout execution receipt")
        _exact(data, set(cls.__dataclass_fields__), "holdout execution receipt")
        for name in (
            "access_audit_sha256s",
            "result_sha256s",
            "cache_namespaces",
            "executed_job_ids",
        ):
            if not isinstance(data[name], list):
                raise HoldoutExecutionError(f"{name} must be an array")
        return cls(
            **{
                name: (
                    tuple(data[name]) if isinstance(data[name], list) else data[name]
                )
                for name in cls.__dataclass_fields__
            }  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class AuthorizedHoldoutRun:
    """Execution result paired with its immutable authorization receipt."""

    execution: AblationRunResult
    receipt: HoldoutExecutionReceipt


def _write_once(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(value))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise HoldoutExecutionError(
            f"refusing to overwrite immutable holdout record: {path}"
        ) from exc


def execute_authorized_holdout(
    authorization: PilotAuthorizationReceipt,
    corpus: ReviewedCorpus,
    plan: AblationPlan,
    access_audits: Sequence[HoldoutAccessAudit],
    adapters: Mapping[object, object],
    *,
    source_commit: str,
    environment_sha256: str,
    output_root: str | Path,
    resource_scheduler: ResourceScheduler | None = None,
) -> AuthorizedHoldoutRun:
    """Validate every gate and audit, then execute once in a fresh namespace."""

    if not isinstance(adapters, Mapping):
        raise HoldoutExecutionError("adapters must be a mapping")
    if resource_scheduler is not None and not isinstance(
        resource_scheduler, ResourceScheduler
    ):
        raise HoldoutExecutionError(
            "resource_scheduler must be a ResourceScheduler"
        )
    audits = _validate_execution_boundary(
        authorization,
        corpus,
        plan,
        access_audits,
        source_commit=source_commit,
        environment_sha256=environment_sha256,
        output_root=output_root,
        purpose="evaluation",
    )
    root = Path(output_root)
    authorization_record = {
        "schema": PILOT_AUTHORIZATION_SCHEMA,
        "evidence": HSSLEV1167A17(),
        "authorization": authorization.to_dict(),
        "plan_sha256": plan.digest,
        "access_audit_sha256s": [item.audit_sha256 for item in audits],
        "source_commit": source_commit,
        "environment_sha256": environment_sha256,
        "resume_permitted": False,
    }
    _write_once(
        root / "state" / HOLDOUT_AUTHORIZATION_FILE,
        authorization_record,
    )
    _write_once(
        root / "state" / HOLDOUT_ACCESS_AUDITS_FILE,
        {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark."
                "holdout-access-ledger.v1"
            ),
            "evidence": HSSLEV1167A17(),
            "run_id": plan.run_id,
            "plan_sha256": plan.digest,
            "authorization_sha256": authorization.authorization_sha256,
            "audits": [item.to_dict() for item in audits],
        },
    )
    execution = _execute_ablation(
        plan,
        adapters,
        output_root=root,
        resume=False,
        resource_scheduler=resource_scheduler,
        authorized_holdout=True,
    )
    payload = {
        "schema": HOLDOUT_EXECUTION_RECEIPT_SCHEMA,
        "evidence": HSSLEV1167A17(),
        "run_id": plan.run_id,
        "source_commit": source_commit,
        "environment_sha256": environment_sha256,
        "authorization_sha256": authorization.authorization_sha256,
        "pilot_gate_sha256": authorization.pilot_gate_sha256,
        "plan_sha256": plan.digest,
        "access_audit_sha256s": tuple(
            item.audit_sha256 for item in audits
        ),
        "result_sha256s": tuple(item.digest for item in execution.results),
        "cache_namespaces": tuple(
            contract.cache_namespace for contract in execution.contracts
        ),
        "executed_job_ids": execution.executed_job_ids,
        "complete": execution.complete,
    }
    receipt = HoldoutExecutionReceipt(
        **payload,  # type: ignore[arg-type]
        receipt_sha256=_sha(
            {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in payload.items()
            }
        ),
    )
    _write_once(
        root / "receipts" / HOLDOUT_EXECUTION_RECEIPT_FILE,
        receipt.to_dict(),
    )
    return AuthorizedHoldoutRun(execution, receipt)


__all__ = [
    "HOLDOUT_ACCESS_AUDITS_FILE",
    "HOLDOUT_AUTHORIZATION_FILE",
    "HOLDOUT_EXECUTION_RECEIPT_FILE",
    "HOLDOUT_EXECUTION_RECEIPT_SCHEMA",
    "MAX_SHORTLIST_SIZE",
    "PILOT_AUTHORIZATION_SCHEMA",
    "AuthorizedHoldoutRun",
    "HSSLEV1167A17",
    "HoldoutExecutionError",
    "HoldoutExecutionReceipt",
    "PilotAuthorizationReceipt",
    "build_authorized_holdout_plan",
    "build_holdout_access_audits",
    "execute_authorized_holdout",
]
