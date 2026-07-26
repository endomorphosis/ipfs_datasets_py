"""Authoritative, source-safe persistence for complete HSSL-G211 evidence.

This module does not execute a model, solver, semantic producer, or native
kernel.  Its caller supplies already-derived :class:`CausalRuntimeEvidenceV2`
values for one complete non-holdout :class:`AblationPlan`.  G211 independently
replays every value, binds it to the exact plan, rescue manifest, and execution
profile, derives the shared compiler-reference population and causal
aggregates, and only then writes immutable canonical envelopes.

The distinction is deliberate: G210 owns live causal execution, while G211
owns durable batch completeness and resume/race validation.  The retired
selection-only batch executor remains disabled.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import fcntl
import json
import os
from pathlib import Path
import stat
from types import MappingProxyType
from typing import Final, Iterator, Mapping, Sequence

from .ablation import AblationPlan, ScheduledCase
from .causal_ablation import (
    CausalExecutionProfileV2,
    CausalRescueCaseV2,
    CausalRescueManifestV2,
)
from .causal_runtime import (
    CausalRuntimeEvidenceV2,
    validate_causal_runtime_evidence_v2,
)
from .content_addressing import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
)
from .contracts import (
    CAUSAL_PROOF_PROTOCOL_V2_CID,
    CAUSAL_PROOF_VARIANT_PROFILE_V2_CID,
    SEMANTIC_PROTOCOL_V2_CID,
    CacheMode,
    Split,
)
from .metrics import (
    aggregate_causal_rescue_receipts,
    validate_causal_rescue_aggregate,
)
from .namespace_provenance import (
    G240RuntimeNamespaceEvidenceSetV2,
    G240RuntimeNamespaceReceiptV2,
    RuntimeNamespaceProvenanceError,
    validate_g240_runtime_namespace_evidence_set_v2,
)
from .source_orchestration import (
    G240PrivateSourceValidationSourcesV2,
    G240SourceOrchestrationEvidenceSetV2,
    SourceRuntimeOrchestrationError,
    validate_g240_source_orchestration_evidence_set_v2,
)


G211_COMPILER_REFERENCE_POPULATION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g211-compiler-reference-population.v2"
)
G211_CAUSAL_RUNTIME_ENVELOPE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g211-causal-runtime-envelope.v2"
)
G211_CAUSAL_RUNTIME_BATCH_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g211-causal-runtime-batch.v2"
)
_SOURCE_WORKTREE_ROOT: Final = Path(__file__).resolve().parents[2]


class CausalRuntimeBatchError(ValueError):
    """Raised when G211 evidence is incomplete, conflicting, or not durable."""


def HSSLEV2116C82() -> str:
    """Return AST-verifiable evidence for full G211 batch persistence."""

    return (
        "write-once full causal runtime evidence with exact plan coordinate "
        "resume race replay compiler exposure equality and derived aggregates"
    )


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise CausalRuntimeBatchError(
                "G211 DAG-JSON objects require string keys"
            )
        return {
            str(key): _plain(member)
            for key, member in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_plain(member) for member in value]
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise CausalRuntimeBatchError(
        f"G211 value is not DAG-JSON: {type(value).__name__}"
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
        raise CausalRuntimeBatchError(f"{field} must be an object")
    return value


def _exact(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    if set(value) != expected:
        raise CausalRuntimeBatchError(
            f"{field} fields changed: "
            f"missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CausalRuntimeBatchError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_canonical(path: Path, field: str) -> object:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise CausalRuntimeBatchError(
                f"{field} must be a regular non-symlink file"
            )
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except CausalRuntimeBatchError:
        raise
    except (OSError, UnicodeError) as exc:
        raise CausalRuntimeBatchError(
            f"cannot read {field}: {path}"
        ) from exc
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise CausalRuntimeBatchError(
            f"{field} is not canonical newline JSON"
        )
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise CausalRuntimeBatchError(
            f"{field} is not strict JSON"
        ) from exc
    if raw != canonical_dag_json_bytes(value) + b"\n":
        raise CausalRuntimeBatchError(
            f"{field} is not canonical DAG-JSON"
        )
    return value


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _is_inside_git_worktree(path: Path) -> bool:
    if path == _SOURCE_WORKTREE_ROOT or _SOURCE_WORKTREE_ROOT in path.parents:
        return True
    for ancestor in (path, *path.parents):
        marker = ancestor / ".git"
        try:
            marker.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise CausalRuntimeBatchError(
                "cannot inspect G211 output_root Git boundary"
            ) from exc
        return True
    return False


def _validate_private_directory(path: Path, field: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CausalRuntimeBatchError(
            f"cannot inspect {field}: {path}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise CausalRuntimeBatchError(
            f"{field} must be a real directory, not a symlink"
        )
    if not stat.S_ISDIR(metadata.st_mode):
        raise CausalRuntimeBatchError(f"{field} must be a directory")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise CausalRuntimeBatchError(
            f"{field} must not be accessible to group or others"
        )


def _coerce_root(output_root: str | Path) -> Path:
    if isinstance(output_root, str) and not output_root.strip():
        raise CausalRuntimeBatchError(
            "G211 output_root must not be empty"
        )
    try:
        root = Path(output_root)
    except (TypeError, ValueError) as exc:
        raise CausalRuntimeBatchError(
            "G211 output_root must be a filesystem path"
        ) from exc
    if not root.is_absolute():
        raise CausalRuntimeBatchError(
            "G211 output_root must be absolute"
        )
    try:
        metadata = root.lstat()
    except FileNotFoundError:
        metadata = None
    except OSError as exc:
        raise CausalRuntimeBatchError(
            f"cannot inspect G211 output_root: {root}"
        ) from exc
    if metadata is not None:
        if stat.S_ISLNK(metadata.st_mode):
            raise CausalRuntimeBatchError(
                "G211 output_root must be a real directory, not a symlink"
            )
        if not stat.S_ISDIR(metadata.st_mode):
            raise CausalRuntimeBatchError(
                "G211 output_root must be a directory"
            )
    try:
        root = root.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise CausalRuntimeBatchError(
            "G211 output_root could not be resolved safely"
        ) from exc
    if _is_inside_git_worktree(root):
        raise CausalRuntimeBatchError(
            "G211 output_root must not be inside a Git repository or worktree"
        )
    if metadata is not None:
        _validate_private_directory(root, "G211 output_root")
    return root


def _prepare_output_root(root: Path) -> None:
    missing: list[Path] = []
    current = root
    while True:
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            missing.append(current)
            parent = current.parent
            if parent == current:
                raise CausalRuntimeBatchError(
                    "G211 output_root has no existing directory ancestor"
                )
            current = parent
            continue
        except OSError as exc:
            raise CausalRuntimeBatchError(
                f"cannot inspect G211 output directory ancestor: {current}"
            ) from exc
        if not stat.S_ISDIR(metadata.st_mode):
            raise CausalRuntimeBatchError(
                "G211 output_root ancestor must be a real directory"
            )
        break
    for directory in reversed(missing):
        try:
            os.mkdir(directory, 0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise CausalRuntimeBatchError(
                f"cannot create private G211 output directory: {directory}"
            ) from exc
        _validate_private_directory(directory, "G211 output directory")
    _validate_private_directory(root, "G211 output_root")


def _ensure_private_run_directory(root: Path, directory: Path) -> None:
    try:
        relative = directory.relative_to(root)
    except ValueError as exc:
        raise CausalRuntimeBatchError(
            "G211 run directory escaped output_root"
        ) from exc
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise CausalRuntimeBatchError(
            "G211 run directory escaped output_root"
        )
    _validate_private_directory(root, "G211 output_root")
    current = root
    for part in relative.parts:
        current /= part
        try:
            os.mkdir(current, 0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise CausalRuntimeBatchError(
                f"cannot create private G211 run directory: {current}"
            ) from exc
        _validate_private_directory(current, "G211 run directory")


def _write_exclusive(
    root: Path,
    path: Path,
    value: object,
) -> bool:
    _ensure_private_run_directory(root, path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        return False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_dag_json_bytes(_plain(value)) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(path.parent)
    except Exception:
        # A partial exclusive file is evidence of an interrupted write.  It is
        # intentionally retained so resume fails closed instead of silently
        # replacing or "healing" an ambiguous record.
        raise
    return True


def _ensure_exact_record(
    root: Path,
    path: Path,
    value: object,
    *,
    resume: bool,
    field: str,
) -> bool:
    expected = _plain(value)
    if path.exists() or path.is_symlink():
        if not resume:
            raise CausalRuntimeBatchError(
                f"{field} exists with resume disabled: {path}"
            )
        if _read_canonical(path, field) != expected:
            raise CausalRuntimeBatchError(
                f"{field} conflicts with the immutable G211 namespace"
            )
        return False
    created = _write_exclusive(root, path, expected)
    if created:
        if _read_canonical(path, field) != expected:
            raise CausalRuntimeBatchError(
                f"persisted {field} failed exact replay"
            )
        return True
    if not resume:
        raise CausalRuntimeBatchError(
            f"{field} was concurrently created with resume disabled"
        )
    if _read_canonical(path, f"concurrent {field}") != expected:
        raise CausalRuntimeBatchError(
            f"concurrent {field} differs from the exact G211 record"
        )
    return False


@contextmanager
def _job_lock(root: Path, job_id: str) -> Iterator[None]:
    lock_path = root / "state" / "locks" / f"{job_id}.lock"
    _ensure_private_run_directory(root, lock_path.parent)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise CausalRuntimeBatchError(
                "G211 job lock must be a regular file"
            )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _plan_cid(plan: AblationPlan) -> str:
    return cid_for_dag_json(_plain(plan.to_dict()))


def _result_path(root: Path, job: ScheduledCase) -> Path:
    return (
        root
        / "results"
        / job.case.split.value
        / job.cache_mode.value
        / job.variant_id
        / f"{job.case.case_id}.json"
    )


def _validate_plan(plan: AblationPlan) -> None:
    if not isinstance(plan, AblationPlan):
        raise CausalRuntimeBatchError("G211 plan must be an AblationPlan")
    if plan.split not in {Split.PILOT, Split.DEVELOPMENT}:
        raise CausalRuntimeBatchError(
            "G211 batch persistence is pilot/development only"
        )
    if "A0" not in plan.variant_ids or "S1" in plan.variant_ids:
        raise CausalRuntimeBatchError(
            "G211 requires A0 and forbids the legacy S1 diagnostic"
        )
    if plan.environment_sha256 is None:
        raise CausalRuntimeBatchError(
            "G211 requires one pinned plan environment"
        )
    for job in plan.jobs:
        source = job.case.input_data
        if (
            not isinstance(source, Mapping)
            or set(source) != {"text"}
            or not isinstance(source.get("text"), str)
            or not str(source["text"]).strip()
        ):
            raise CausalRuntimeBatchError(
                "G211 plan must contain exact source-only inputs"
            )


def _validate_evidence_coordinate(
    plan: AblationPlan,
    job: ScheduledCase,
    evidence: CausalRuntimeEvidenceV2,
) -> CausalRuntimeEvidenceV2:
    if not isinstance(evidence, CausalRuntimeEvidenceV2):
        raise CausalRuntimeBatchError(
            f"{job.job_id} requires typed CausalRuntimeEvidenceV2"
        )
    try:
        restored = validate_causal_runtime_evidence_v2(
            evidence.to_dict()
        )
    except (TypeError, ValueError) as exc:
        raise CausalRuntimeBatchError(
            f"{job.job_id} causal runtime evidence failed replay"
        ) from exc
    source = job.case.input_data
    assert isinstance(source, Mapping)
    source_text = source["text"]
    assert isinstance(source_text, str)
    result = restored.case_result
    if (
        result.run_id != plan.run_id
        or result.case_id != job.case.case_id
        or result.variant_id != job.variant_id
        or result.split is not plan.split
        or result.cache_mode is not job.cache_mode
        or result.case_manifest_sha256 != plan.case_manifest_sha256
        or restored.source_text != source_text
        or restored.compiler_exposure.source_cid
        != cid_for_bytes(source_text.encode("utf-8"))
        or any(
            stage.provenance.input_sha256 != job.input_sha256
            for stage in result.stages
        )
    ):
        raise CausalRuntimeBatchError(
            f"{job.job_id} evidence differs from its exact plan coordinate"
        )
    environments = {
        stage.provenance.environment_sha256
        for stage in result.stages
    }
    if environments != {plan.environment_sha256}:
        raise CausalRuntimeBatchError(
            f"{job.job_id} evidence environment differs from the plan"
        )
    return restored


def _ordered_evidence(
    plan: AblationPlan,
    evidence_by_job_id: Mapping[
        str, CausalRuntimeEvidenceV2
    ],
) -> tuple[CausalRuntimeEvidenceV2, ...]:
    _validate_plan(plan)
    if not isinstance(evidence_by_job_id, Mapping) or not all(
        isinstance(key, str) for key in evidence_by_job_id
    ):
        raise CausalRuntimeBatchError(
            "G211 evidence must be a job-id mapping"
        )
    expected = {job.job_id for job in plan.jobs}
    if set(evidence_by_job_id) != expected:
        raise CausalRuntimeBatchError(
            "G211 evidence must exactly cover every scheduled job"
        )
    restored = tuple(
        _validate_evidence_coordinate(
            plan,
            job,
            evidence_by_job_id[job.job_id],
        )
        for job in plan.jobs
    )
    shared: dict[
        tuple[str, CacheMode],
        str,
    ] = {}
    for job, evidence in zip(plan.jobs, restored, strict=True):
        key = (job.case.case_id, job.cache_mode)
        exposure_cid = evidence.compiler_exposure.receipt_cid
        previous = shared.setdefault(key, exposure_cid)
        if previous != exposure_cid:
            raise CausalRuntimeBatchError(
                "variants received unequal shared compiler-reference exposure"
            )
    return restored


def _compiler_reference_population(
    plan: AblationPlan,
    evidence: Sequence[CausalRuntimeEvidenceV2],
) -> Mapping[str, object]:
    by_coordinate: dict[
        tuple[str, CacheMode],
        CausalRuntimeEvidenceV2,
    ] = {}
    for job, item in zip(plan.jobs, evidence, strict=True):
        by_coordinate.setdefault(
            (job.case.case_id, job.cache_mode),
            item,
        )
    entries: list[dict[str, object]] = []
    for case_id, cache_mode in sorted(
        by_coordinate,
        key=lambda key: (key[0], key[1].value),
    ):
        exposure = by_coordinate[(case_id, cache_mode)].compiler_exposure
        candidate = exposure.compiler_candidate
        entries.append(
            {
                "case_id": case_id,
                "cache_mode": cache_mode.value,
                "source_cid": exposure.source_cid,
                "compiler_reference_exposure_cid": exposure.receipt_cid,
                "compiler_record_cid": cid_for_dag_json(
                    _plain(exposure.compiler_record.to_dict())
                ),
                "candidate_state": (
                    "absent" if candidate is None else "present"
                ),
                "candidate_cid": (
                    None if candidate is None else candidate.candidate_cid
                ),
                "artifact_cid": (
                    None if candidate is None else candidate.artifact_cid
                ),
            }
        )
    body: dict[str, object] = {
        "schema": G211_COMPILER_REFERENCE_POPULATION_SCHEMA_V2,
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "causal_proof_protocol_cid": CAUSAL_PROOF_PROTOCOL_V2_CID,
        "variant_profile_cid": CAUSAL_PROOF_VARIANT_PROFILE_V2_CID,
        "plan_cid": _plan_cid(plan),
        "run_id": plan.run_id,
        "split": plan.split.value,
        "case_manifest_sha256": plan.case_manifest_sha256,
        "environment_sha256": plan.environment_sha256,
        "coordinate_count": len(entries),
        "coordinates": entries,
    }
    value = {
        **body,
        "population_cid": cid_for_dag_json(body),
    }
    frozen = _freeze(value)
    assert isinstance(frozen, Mapping)
    return frozen


def build_g211_compiler_reference_population_v2(
    plan: AblationPlan,
    evidence_by_job_id: Mapping[
        str, CausalRuntimeEvidenceV2
    ],
) -> Mapping[str, object]:
    """Build the complete shared-exposure population from replayed evidence."""

    evidence = _ordered_evidence(plan, evidence_by_job_id)
    return _compiler_reference_population(plan, evidence)


def _validate_manifest_and_profile(
    plan: AblationPlan,
    manifest: CausalRescueManifestV2,
    profile: CausalExecutionProfileV2,
    evidence: tuple[CausalRuntimeEvidenceV2, ...],
) -> Mapping[str, object]:
    if not isinstance(manifest, CausalRescueManifestV2):
        raise CausalRuntimeBatchError(
            "G211 requires a CausalRescueManifestV2"
        )
    if not isinstance(profile, CausalExecutionProfileV2):
        raise CausalRuntimeBatchError(
            "G211 requires a CausalExecutionProfileV2"
        )
    plan_cid = _plan_cid(plan)
    if (
        manifest.plan_cid != plan_cid
        or manifest.case_manifest_sha256 != plan.case_manifest_sha256
        or profile.plan_cid != plan_cid
        or profile.source_manifest_cid != manifest.source_manifest_cid
        or profile.rescue_manifest_cid != manifest.manifest_cid
        or profile.environment_sha256 != plan.environment_sha256
    ):
        raise CausalRuntimeBatchError(
            "G211 manifest/profile differs from the exact plan"
        )
    manifest_cases = {case.case_id: case for case in manifest.cases}
    if set(manifest_cases) != set(plan.case_ids):
        raise CausalRuntimeBatchError(
            "G211 rescue population differs from the plan cases"
        )
    population = _compiler_reference_population(plan, evidence)
    if (
        profile.compiler_reference_population_cid
        != population["population_cid"]
    ):
        raise CausalRuntimeBatchError(
            "G211 execution profile does not bind the derived compiler "
            "reference population"
        )
    for job, item in zip(plan.jobs, evidence, strict=True):
        rescue_case: CausalRescueCaseV2 = manifest_cases[
            job.case.case_id
        ]
        optional = item.selection_result.receipt.get(
            "optional_candidates"
        )
        if not isinstance(optional, (list, tuple)):
            raise CausalRuntimeBatchError(
                f"{job.job_id} selection optional route is invalid"
            )
        optional_sources = {
            str(_mapping(value, "optional candidate").get("source"))
            for value in optional
        }
        if (
            rescue_case.split is not plan.split
            or rescue_case.source_cid
            != item.compiler_exposure.source_cid
            or _plain(rescue_case.proof_context)
            != _plain(item.proof_context)
            or not optional_sources.issubset(
                set(rescue_case.optional_components)
            )
        ):
            raise CausalRuntimeBatchError(
                f"{job.job_id} evidence crosses its reviewed rescue boundary"
            )
    return population


def _derive_aggregates(
    plan: AblationPlan,
    evidence: Sequence[CausalRuntimeEvidenceV2],
) -> tuple[Mapping[str, object], ...]:
    groups: dict[
        tuple[str, CacheMode],
        list[Mapping[str, object]],
    ] = {}
    for job, item in zip(plan.jobs, evidence, strict=True):
        receipt = _plain(item.causal_case_receipt)
        if not isinstance(receipt, Mapping):
            raise CausalRuntimeBatchError(
                "G211 causal case receipt did not remain an object"
            )
        groups.setdefault(
            (job.variant_id, job.cache_mode), []
        ).append(receipt)
    aggregates: list[Mapping[str, object]] = []
    for coordinate in sorted(
        groups,
        key=lambda key: (key[0], key[1].value),
    ):
        try:
            aggregate = validate_causal_rescue_aggregate(
                aggregate_causal_rescue_receipts(groups[coordinate])
            )
        except (TypeError, ValueError) as exc:
            raise CausalRuntimeBatchError(
                "G211 causal aggregate failed independent replay"
            ) from exc
        frozen = _freeze(aggregate)
        assert isinstance(frozen, Mapping)
        aggregates.append(frozen)
    return tuple(aggregates)


def _result_envelope(
    *,
    plan: AblationPlan,
    manifest: CausalRescueManifestV2,
    profile: CausalExecutionProfileV2,
    job: ScheduledCase,
    rescue_case: CausalRescueCaseV2,
    evidence: CausalRuntimeEvidenceV2,
    namespace_receipt: G240RuntimeNamespaceReceiptV2 | None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema": G211_CAUSAL_RUNTIME_ENVELOPE_SCHEMA_V2,
        "plan_cid": _plan_cid(plan),
        "execution_profile_cid": profile.profile_cid,
        "rescue_manifest_cid": manifest.manifest_cid,
        "rescue_case_cid": rescue_case.case_cid,
        "job": job.to_dict(),
        "causal_runtime_evidence": evidence.to_dict(),
        "causal_runtime_evidence_cid": evidence.receipt_cid,
        "runtime_namespace_receipt": (
            None
            if namespace_receipt is None
            else namespace_receipt.to_dict()
        ),
        "runtime_namespace_receipt_cid": (
            None
            if namespace_receipt is None
            else namespace_receipt.receipt_cid
        ),
    }
    return {**body, "envelope_cid": cid_for_dag_json(body)}


def _validate_result_envelope(
    value: object,
    *,
    plan: AblationPlan,
    manifest: CausalRescueManifestV2,
    profile: CausalExecutionProfileV2,
    job: ScheduledCase,
) -> tuple[
    CausalRuntimeEvidenceV2,
    G240RuntimeNamespaceReceiptV2 | None,
]:
    data = _mapping(value, "G211 result envelope")
    expected = {
        "schema",
        "plan_cid",
        "execution_profile_cid",
        "rescue_manifest_cid",
        "rescue_case_cid",
        "job",
        "causal_runtime_evidence",
        "causal_runtime_evidence_cid",
        "runtime_namespace_receipt",
        "runtime_namespace_receipt_cid",
        "envelope_cid",
    }
    _exact(data, expected, "G211 result envelope")
    body = {
        key: _plain(member)
        for key, member in data.items()
        if key != "envelope_cid"
    }
    rescue_cases = {case.case_id: case for case in manifest.cases}
    rescue_case = rescue_cases.get(job.case.case_id)
    try:
        persisted_job = ScheduledCase.from_dict(data["job"])
        evidence = validate_causal_runtime_evidence_v2(
            data["causal_runtime_evidence"]
        )
        namespace_value = data["runtime_namespace_receipt"]
        namespace_cid = data["runtime_namespace_receipt_cid"]
        if namespace_value is None:
            if namespace_cid is not None:
                raise CausalRuntimeBatchError(
                    f"{job.job_id} namespace receipt CID lacks a receipt"
                )
            namespace_receipt = None
        else:
            namespace_receipt = (
                G240RuntimeNamespaceReceiptV2.from_dict(namespace_value)
            )
            if namespace_cid != namespace_receipt.receipt_cid:
                raise CausalRuntimeBatchError(
                    f"{job.job_id} namespace receipt CID changed"
                )
    except (TypeError, ValueError) as exc:
        raise CausalRuntimeBatchError(
            f"{job.job_id} G211 envelope failed typed replay"
        ) from exc
    if (
        rescue_case is None
        or data["schema"] != G211_CAUSAL_RUNTIME_ENVELOPE_SCHEMA_V2
        or data["plan_cid"] != _plan_cid(plan)
        or data["execution_profile_cid"] != profile.profile_cid
        or data["rescue_manifest_cid"] != manifest.manifest_cid
        or data["rescue_case_cid"] != rescue_case.case_cid
        or persisted_job != job
        or data["causal_runtime_evidence_cid"] != evidence.receipt_cid
        or (
            namespace_receipt is not None
            and (
                namespace_receipt.plan_cid != _plan_cid(plan)
                or namespace_receipt.job_id != job.job_id
                or namespace_receipt.runtime_evidence_cid
                != evidence.receipt_cid
            )
        )
        or data["envelope_cid"] != cid_for_dag_json(body)
    ):
        raise CausalRuntimeBatchError(
            f"{job.job_id} G211 envelope identity changed"
        )
    return evidence, namespace_receipt


@dataclass(frozen=True, slots=True)
class CausalRuntimeBatchResultV2:
    """One complete, independently replayed G211 persisted batch."""

    plan: AblationPlan
    rescue_manifest: CausalRescueManifestV2
    execution_profile: CausalExecutionProfileV2
    compiler_reference_population: Mapping[str, object]
    evidence: tuple[CausalRuntimeEvidenceV2, ...]
    causal_aggregates: tuple[Mapping[str, object], ...]
    envelope_cids: tuple[str, ...]
    runtime_namespace_evidence_set: (
        G240RuntimeNamespaceEvidenceSetV2 | None
    )
    source_orchestration_evidence_set: (
        G240SourceOrchestrationEvidenceSetV2 | None
    )
    executed_job_ids: tuple[str, ...]
    resumed_job_ids: tuple[str, ...]
    output_root: Path

    def __post_init__(self) -> None:
        frozen_population = _freeze(self.compiler_reference_population)
        if not isinstance(frozen_population, Mapping):
            raise CausalRuntimeBatchError(
                "compiler population did not remain an object"
            )
        frozen_aggregates = tuple(
            _freeze(item) for item in self.causal_aggregates
        )
        if not all(
            isinstance(item, Mapping) for item in frozen_aggregates
        ):
            raise CausalRuntimeBatchError(
                "causal aggregates did not remain objects"
            )
        object.__setattr__(
            self,
            "compiler_reference_population",
            frozen_population,
        )
        object.__setattr__(
            self,
            "causal_aggregates",
            frozen_aggregates,
        )

    @property
    def complete(self) -> bool:
        return len(self.evidence) == len(self.plan.jobs)

    def identity_body(self) -> dict[str, object]:
        return {
            "schema": G211_CAUSAL_RUNTIME_BATCH_SCHEMA_V2,
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "causal_proof_protocol_cid": (
                CAUSAL_PROOF_PROTOCOL_V2_CID
            ),
            "variant_profile_cid": (
                CAUSAL_PROOF_VARIANT_PROFILE_V2_CID
            ),
            "plan_cid": _plan_cid(self.plan),
            "execution_profile_cid": (
                self.execution_profile.profile_cid
            ),
            "rescue_manifest_cid": self.rescue_manifest.manifest_cid,
            "semantic_calibration_artifact_cid": (
                self.execution_profile.semantic_calibration_artifact_cid
            ),
            "compiler_reference_population_cid": (
                self.compiler_reference_population["population_cid"]
            ),
            "run_id": self.plan.run_id,
            "split": self.plan.split.value,
            "environment_sha256": self.plan.environment_sha256,
            "job_ids": [job.job_id for job in self.plan.jobs],
            "causal_runtime_evidence_cids": [
                item.receipt_cid for item in self.evidence
            ],
            "envelope_cids": list(self.envelope_cids),
            "causal_aggregate_cids": [
                item["aggregate_cid"]
                for item in self.causal_aggregates
            ],
            "runtime_namespace_policy_cid": (
                None
                if self.runtime_namespace_evidence_set is None
                else self.runtime_namespace_evidence_set.policy.policy_cid
            ),
            "runtime_namespace_evidence_set_cid": (
                None
                if self.runtime_namespace_evidence_set is None
                else (
                    self.runtime_namespace_evidence_set.evidence_set_cid
                )
            ),
            "source_orchestration_evidence_set_cid": (
                None
                if self.source_orchestration_evidence_set is None
                else (
                    self.source_orchestration_evidence_set.evidence_set_cid
                )
            ),
            "causal_aggregates": [
                _plain(item) for item in self.causal_aggregates
            ],
            "complete": self.complete,
            "holdout_included": False,
        }

    @property
    def receipt_cid(self) -> str:
        return cid_for_dag_json(self.identity_body())

    @property
    def receipt(self) -> Mapping[str, object]:
        frozen = _freeze(
            {**self.identity_body(), "receipt_cid": self.receipt_cid}
        )
        assert isinstance(frozen, Mapping)
        return frozen


def _batch_from_validated(
    *,
    plan: AblationPlan,
    manifest: CausalRescueManifestV2,
    profile: CausalExecutionProfileV2,
    population: Mapping[str, object],
    evidence: tuple[CausalRuntimeEvidenceV2, ...],
    causal_aggregates: tuple[Mapping[str, object], ...] | None = None,
    runtime_namespace_evidence_set: (
        G240RuntimeNamespaceEvidenceSetV2 | None
    ),
    source_orchestration_evidence_set: (
        G240SourceOrchestrationEvidenceSetV2 | None
    ),
    executed: tuple[str, ...],
    resumed: tuple[str, ...],
    root: Path,
) -> CausalRuntimeBatchResultV2:
    rescue_cases = {case.case_id: case for case in manifest.cases}
    namespace_receipts = (
        {}
        if runtime_namespace_evidence_set is None
        else runtime_namespace_evidence_set.receipt_map
    )
    plan_cid = _plan_cid(plan)
    envelope_cids = tuple(
        str(
            _result_envelope(
                plan=plan,
                manifest=manifest,
                profile=profile,
                job=job,
                rescue_case=rescue_cases[job.case.case_id],
                evidence=item,
                namespace_receipt=namespace_receipts.get(
                    (plan_cid, job.job_id)
                ),
            )["envelope_cid"]
        )
        for job, item in zip(plan.jobs, evidence, strict=True)
    )
    return CausalRuntimeBatchResultV2(
        plan=plan,
        rescue_manifest=manifest,
        execution_profile=profile,
        compiler_reference_population=population,
        evidence=evidence,
        causal_aggregates=(
            _derive_aggregates(plan, evidence)
            if causal_aggregates is None
            else causal_aggregates
        ),
        envelope_cids=envelope_cids,
        runtime_namespace_evidence_set=(
            runtime_namespace_evidence_set
        ),
        source_orchestration_evidence_set=(
            source_orchestration_evidence_set
        ),
        executed_job_ids=executed,
        resumed_job_ids=resumed,
        output_root=root,
    )


def _reject_foreign_json(
    root: Path,
    plan: AblationPlan,
    *,
    namespace_evidence_expected: bool | None = None,
    source_orchestration_expected: bool | None = None,
) -> None:
    expected_results = {
        _result_path(root, job) for job in plan.jobs
    }
    results_root = root / "results"
    actual_results = (
        set(results_root.rglob("*.json"))
        if results_root.exists()
        else set()
    )
    foreign_results = actual_results - expected_results
    if foreign_results:
        raise CausalRuntimeBatchError(
            "G211 namespace contains foreign result records"
        )
    expected_state = {
        root / "state" / "ablation-plan.json",
        root / "state" / "causal-rescue-manifest.json",
        root / "state" / "causal-execution-profile.json",
        root / "state" / "compiler-reference-population.json",
        root / "state" / "causal-runtime-batch.json",
    }
    namespace_path = (
        root / "state" / "runtime-namespace-evidence-set.json"
    )
    if namespace_evidence_expected is True or (
        namespace_evidence_expected is None
        and (namespace_path.exists() or namespace_path.is_symlink())
    ):
        expected_state.add(namespace_path)
    source_orchestration_path = (
        root
        / "state"
        / "source-runtime-orchestration-evidence-set.json"
    )
    if source_orchestration_expected is True or (
        source_orchestration_expected is None
        and (
            source_orchestration_path.exists()
            or source_orchestration_path.is_symlink()
        )
    ):
        expected_state.add(source_orchestration_path)
    state_root = root / "state"
    actual_state = (
        {
            path
            for path in state_root.rglob("*.json")
            if "locks" not in path.parts
        }
        if state_root.exists()
        else set()
    )
    if actual_state - expected_state:
        raise CausalRuntimeBatchError(
            "G211 namespace contains foreign state records"
        )


def persist_causal_runtime_batch_v2(
    plan: AblationPlan,
    rescue_manifest: CausalRescueManifestV2,
    execution_profile: CausalExecutionProfileV2,
    evidence_by_job_id: Mapping[
        str, CausalRuntimeEvidenceV2
    ],
    *,
    output_root: str | Path,
    runtime_namespace_evidence_set: (
        G240RuntimeNamespaceEvidenceSetV2 | None
    ) = None,
    source_orchestration_evidence_set: (
        G240SourceOrchestrationEvidenceSetV2 | None
    ) = None,
    source_orchestration_validation_sources: Sequence[
        G240PrivateSourceValidationSourcesV2
    ] = (),
    resume: bool = True,
) -> CausalRuntimeBatchResultV2:
    """Persist one complete supplied G210 evidence matrix exactly once.

    Every supplied value is independently replayed and the entire batch is
    preflighted before the output namespace is created.  Existing records are
    accepted only when their complete canonical envelope is byte-equivalent
    to the requested evidence.
    """

    if type(resume) is not bool:
        raise CausalRuntimeBatchError("resume must be boolean")
    root = _coerce_root(output_root)
    evidence = _ordered_evidence(plan, evidence_by_job_id)
    population = _validate_manifest_and_profile(
        plan,
        rescue_manifest,
        execution_profile,
        evidence,
    )
    # Derive and replay every aggregate before the first filesystem write.
    causal_aggregates = _derive_aggregates(plan, evidence)
    namespace_evidence: G240RuntimeNamespaceEvidenceSetV2 | None
    if runtime_namespace_evidence_set is None:
        namespace_evidence = None
    else:
        try:
            namespace_evidence = (
                validate_g240_runtime_namespace_evidence_set_v2(
                    runtime_namespace_evidence_set,
                    plans=(plan,),
                    evidence_by_plan_and_job={
                        (_plan_cid(plan), job.job_id): item
                        for job, item in zip(
                            plan.jobs, evidence, strict=True
                        )
                    },
                )
            )
        except (RuntimeNamespaceProvenanceError, TypeError, ValueError) as exc:
            raise CausalRuntimeBatchError(
                "G211 runtime namespace evidence failed source replay"
            ) from exc
    orchestration_evidence: (
        G240SourceOrchestrationEvidenceSetV2 | None
    )
    private_sources = tuple(source_orchestration_validation_sources)
    if source_orchestration_evidence_set is None:
        if private_sources:
            raise CausalRuntimeBatchError(
                "G211 source orchestration validation sources require "
                "an evidence set"
            )
        orchestration_evidence = None
    else:
        if namespace_evidence is None or not private_sources:
            raise CausalRuntimeBatchError(
                "G211 source orchestration persistence requires runtime "
                "namespace evidence and private validation sources"
            )
        try:
            orchestration_evidence = (
                validate_g240_source_orchestration_evidence_set_v2(
                    source_orchestration_evidence_set,
                    runtime_namespace_evidence_set=namespace_evidence,
                    validation_sources=private_sources,
                )
            )
        except (
            SourceRuntimeOrchestrationError,
            TypeError,
            ValueError,
        ) as exc:
            raise CausalRuntimeBatchError(
                "G211 source orchestration evidence failed live source "
                "replay"
            ) from exc
    if root.exists() and not resume:
        raise CausalRuntimeBatchError(
            "G211 output namespace exists with resume disabled"
        )
    _prepare_output_root(root)
    _reject_foreign_json(
        root,
        plan,
        namespace_evidence_expected=namespace_evidence is not None,
        source_orchestration_expected=(
            orchestration_evidence is not None
        ),
    )
    state = root / "state"
    with _job_lock(root, "g211-state"):
        for path, value, field in (
            (
                state / "ablation-plan.json",
                plan.to_dict(),
                "G211 plan",
            ),
            (
                state / "causal-rescue-manifest.json",
                rescue_manifest.to_dict(),
                "G211 rescue manifest",
            ),
            (
                state / "causal-execution-profile.json",
                execution_profile.to_dict(),
                "G211 execution profile",
            ),
            (
                state / "compiler-reference-population.json",
                population,
                "G211 compiler-reference population",
            ),
            *(
                ()
                if namespace_evidence is None
                else (
                    (
                        state
                        / "runtime-namespace-evidence-set.json",
                        namespace_evidence.to_dict(),
                        "G211 runtime namespace evidence set",
                    ),
                )
            ),
            *(
                ()
                if orchestration_evidence is None
                else (
                    (
                        state
                        / (
                            "source-runtime-orchestration-"
                            "evidence-set.json"
                        ),
                        orchestration_evidence.to_dict(),
                        "G211 source orchestration evidence set",
                    ),
                )
            ),
        ):
            _ensure_exact_record(
                root,
                path,
                value,
                resume=resume,
                field=field,
            )
    rescue_cases = {
        case.case_id: case for case in rescue_manifest.cases
    }
    executed: list[str] = []
    resumed: list[str] = []
    namespace_receipts = (
        {}
        if namespace_evidence is None
        else namespace_evidence.receipt_map
    )
    plan_cid = _plan_cid(plan)
    for job, item in zip(plan.jobs, evidence, strict=True):
        envelope = _result_envelope(
            plan=plan,
            manifest=rescue_manifest,
            profile=execution_profile,
            job=job,
            rescue_case=rescue_cases[job.case.case_id],
            evidence=item,
            namespace_receipt=namespace_receipts.get(
                (plan_cid, job.job_id)
            ),
        )
        path = _result_path(root, job)
        with _job_lock(root, job.job_id):
            created = _ensure_exact_record(
                root,
                path,
                envelope,
                resume=resume,
                field=f"G211 result {job.job_id}",
            )
        if created:
            executed.append(job.job_id)
        else:
            resumed.append(job.job_id)
    result = _batch_from_validated(
        plan=plan,
        manifest=rescue_manifest,
        profile=execution_profile,
        population=population,
        evidence=evidence,
        causal_aggregates=causal_aggregates,
        runtime_namespace_evidence_set=namespace_evidence,
        source_orchestration_evidence_set=orchestration_evidence,
        executed=tuple(executed),
        resumed=tuple(resumed),
        root=root,
    )
    with _job_lock(root, "g211-state"):
        _ensure_exact_record(
            root,
            state / "causal-runtime-batch.json",
            result.receipt,
            resume=resume,
            field="G211 batch receipt",
        )
    return validate_causal_runtime_batch_v2(
        plan,
        rescue_manifest,
        execution_profile,
        output_root=root,
        _executed_job_ids=tuple(executed),
    )


def validate_causal_runtime_batch_v2(
    plan: AblationPlan,
    rescue_manifest: CausalRescueManifestV2,
    execution_profile: CausalExecutionProfileV2,
    *,
    output_root: str | Path,
    _executed_job_ids: tuple[str, ...] = (),
) -> CausalRuntimeBatchResultV2:
    """Read-only replay of one complete persisted G211 batch."""

    root = _coerce_root(output_root)
    _validate_plan(plan)
    namespace_path = (
        root / "state" / "runtime-namespace-evidence-set.json"
    )
    namespace_present = (
        namespace_path.exists() or namespace_path.is_symlink()
    )
    orchestration_path = (
        root
        / "state"
        / "source-runtime-orchestration-evidence-set.json"
    )
    orchestration_present = (
        orchestration_path.exists() or orchestration_path.is_symlink()
    )
    _reject_foreign_json(
        root,
        plan,
        namespace_evidence_expected=namespace_present,
        source_orchestration_expected=orchestration_present,
    )
    state = root / "state"
    try:
        persisted_plan = AblationPlan.from_dict(
            _read_canonical(
                state / "ablation-plan.json",
                "G211 plan",
            )
        )
        persisted_manifest = CausalRescueManifestV2.from_dict(
            _read_canonical(
                state / "causal-rescue-manifest.json",
                "G211 rescue manifest",
            )
        )
        persisted_profile = CausalExecutionProfileV2.from_dict(
            _read_canonical(
                state / "causal-execution-profile.json",
                "G211 execution profile",
            )
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, CausalRuntimeBatchError):
            raise
        raise CausalRuntimeBatchError(
            "G211 state failed typed replay"
        ) from exc
    if (
        persisted_plan != plan
        or persisted_manifest != rescue_manifest
        or persisted_profile != execution_profile
    ):
        raise CausalRuntimeBatchError(
            "G211 persisted state conflicts with the requested batch"
        )
    expected_paths = {
        _result_path(root, job) for job in plan.jobs
    }
    actual_paths = (
        set((root / "results").rglob("*.json"))
        if (root / "results").exists()
        else set()
    )
    if actual_paths != expected_paths:
        raise CausalRuntimeBatchError(
            "G211 persisted result set is incomplete or foreign"
        )
    namespace_evidence: G240RuntimeNamespaceEvidenceSetV2 | None
    if namespace_present:
        try:
            namespace_evidence = (
                G240RuntimeNamespaceEvidenceSetV2.from_dict(
                    _read_canonical(
                        namespace_path,
                        "G211 runtime namespace evidence set",
                    )
                )
            )
        except (
            RuntimeNamespaceProvenanceError,
            TypeError,
            ValueError,
        ) as exc:
            raise CausalRuntimeBatchError(
                "G211 runtime namespace evidence failed typed replay"
            ) from exc
    else:
        namespace_evidence = None
    orchestration_evidence: (
        G240SourceOrchestrationEvidenceSetV2 | None
    )
    if orchestration_present:
        if namespace_evidence is None:
            raise CausalRuntimeBatchError(
                "G211 source orchestration evidence lacks runtime "
                "namespace evidence"
            )
        try:
            orchestration_evidence = (
                G240SourceOrchestrationEvidenceSetV2.from_dict(
                    _read_canonical(
                        orchestration_path,
                        "G211 source orchestration evidence set",
                    )
                )
            )
        except (
            SourceRuntimeOrchestrationError,
            TypeError,
            ValueError,
        ) as exc:
            raise CausalRuntimeBatchError(
                "G211 source orchestration evidence failed typed replay"
            ) from exc
    else:
        orchestration_evidence = None
    namespace_receipts = (
        {}
        if namespace_evidence is None
        else namespace_evidence.receipt_map
    )
    plan_cid = _plan_cid(plan)
    evidence_by_job: dict[str, CausalRuntimeEvidenceV2] = {}
    for job in plan.jobs:
        item, embedded_namespace_receipt = _validate_result_envelope(
            _read_canonical(
                _result_path(root, job),
                f"G211 result {job.job_id}",
            ),
            plan=plan,
            manifest=rescue_manifest,
            profile=execution_profile,
            job=job,
        )
        expected_namespace_receipt = namespace_receipts.get(
            (plan_cid, job.job_id)
        )
        if (
            (
                expected_namespace_receipt is None
                and embedded_namespace_receipt is not None
            )
            or (
                expected_namespace_receipt is not None
                and embedded_namespace_receipt is None
            )
            or (
                expected_namespace_receipt is not None
                and embedded_namespace_receipt is not None
                and _plain(expected_namespace_receipt.to_dict())
                != _plain(embedded_namespace_receipt.to_dict())
            )
        ):
            raise CausalRuntimeBatchError(
                f"{job.job_id} embedded namespace receipt differs from "
                "the G211 evidence set"
            )
        evidence_by_job[job.job_id] = item
    evidence = _ordered_evidence(plan, evidence_by_job)
    if namespace_evidence is not None:
        try:
            namespace_evidence = (
                validate_g240_runtime_namespace_evidence_set_v2(
                    namespace_evidence,
                    plans=(plan,),
                    evidence_by_plan_and_job={
                        (plan_cid, job.job_id): evidence_by_job[
                            job.job_id
                        ]
                        for job in plan.jobs
                    },
                )
            )
        except (RuntimeNamespaceProvenanceError, TypeError, ValueError) as exc:
            raise CausalRuntimeBatchError(
                "G211 persisted namespace evidence failed source replay"
            ) from exc
    if orchestration_evidence is not None:
        assert namespace_evidence is not None
        orchestration_receipts = orchestration_evidence.receipt_map
        namespace_receipts = namespace_evidence.receipt_map
        expected_keys = {
            (plan_cid, job.job_id) for job in plan.jobs
        }
        if (
            orchestration_evidence.policy_cid
            != namespace_evidence.policy.policy_cid
            or orchestration_evidence.runtime_namespace_evidence_set_cid
            != namespace_evidence.evidence_set_cid
            or orchestration_evidence.plan_cids != (plan_cid,)
            or set(orchestration_receipts) != expected_keys
            or any(
                orchestration_receipts[key]
                .runtime_namespace_receipt_cid
                != namespace_receipts[key].receipt_cid
                or orchestration_receipts[key].runtime_evidence_cid
                != evidence_by_job[key[1]].receipt_cid
                for key in expected_keys
            )
        ):
            raise CausalRuntimeBatchError(
                "G211 source orchestration evidence differs from the "
                "persisted runtime namespace population"
            )
    population = _validate_manifest_and_profile(
        plan,
        rescue_manifest,
        execution_profile,
        evidence,
    )
    persisted_population = _read_canonical(
        state / "compiler-reference-population.json",
        "G211 compiler-reference population",
    )
    if persisted_population != _plain(population):
        raise CausalRuntimeBatchError(
            "G211 compiler-reference population changed"
        )
    executed_set = set(_executed_job_ids)
    expected_job_ids = {job.job_id for job in plan.jobs}
    if not executed_set.issubset(expected_job_ids):
        raise CausalRuntimeBatchError(
            "G211 executed-job accounting contains a foreign job"
        )
    result = _batch_from_validated(
        plan=plan,
        manifest=rescue_manifest,
        profile=execution_profile,
        population=population,
        evidence=evidence,
        runtime_namespace_evidence_set=namespace_evidence,
        source_orchestration_evidence_set=orchestration_evidence,
        executed=tuple(
            job.job_id
            for job in plan.jobs
            if job.job_id in executed_set
        ),
        resumed=tuple(
            job.job_id
            for job in plan.jobs
            if job.job_id not in executed_set
        ),
        root=root,
    )
    if _read_canonical(
        state / "causal-runtime-batch.json",
        "G211 batch receipt",
    ) != _plain(result.receipt):
        raise CausalRuntimeBatchError(
            "G211 batch receipt differs from replayed evidence"
        )
    return result


__all__ = [
    "G211_CAUSAL_RUNTIME_BATCH_SCHEMA_V2",
    "G211_CAUSAL_RUNTIME_ENVELOPE_SCHEMA_V2",
    "G211_COMPILER_REFERENCE_POPULATION_SCHEMA_V2",
    "CausalRuntimeBatchError",
    "CausalRuntimeBatchResultV2",
    "HSSLEV2116C82",
    "build_g211_compiler_reference_population_v2",
    "persist_causal_runtime_batch_v2",
    "validate_causal_runtime_batch_v2",
]
