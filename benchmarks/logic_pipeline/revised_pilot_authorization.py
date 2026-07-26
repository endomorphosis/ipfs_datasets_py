"""Data-free, fail-closed HSSL-G230 readiness validation.

G230 is the only intended bridge from revised pilot/development evidence to
the replacement-holdout authorization type in :mod:`holdout_execution`.
This module deliberately does **not** construct that authorization yet.

The G210 implementation now has authoritative, replayable contracts:
:class:`CausalRescueManifestV2`, :class:`CausalExecutionProfileV2`, and the
full causal case/aggregate receipts validated by :mod:`metrics`.  This module
consumes those contracts directly and derives matrix completeness, compiler
reference failure, equal exposure, and receipt coverage.  It does not create
a second rescue-manifest schema and it never accepts opaque receipt CIDs or
caller-supplied ``complete``/``passed`` claims as evidence.

Revision-2 source-recomputed validators for every paired efficacy, cost,
safety, replay, reliability, routing, and Pareto gate do not exist yet.
The in-process source-revalidated G201 calibration capability is likewise not
an input to this scaffold; a raw calibration artifact is retained only as an
integrity-checked dependency reference.
Until they do, even an otherwise complete input graph produces a frozen empty
shortlist, the stable ``source_recomputed_gate_validator_unavailable`` reason,
and no authorization CID.  This is safer than allowing content addressing
(which proves integrity, not truth) to be mistaken for experimental authority.

No function in this module opens a corpus, manifest path, or holdout.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Mapping, Sequence, Self

from .cases import ReplacementHoldoutSeal
from .causal_ablation import (
    CausalExecutionProfileV2,
    CausalRescueCaseV2,
    CausalRescueManifestV2,
)
from .causal_runtime import (
    CausalRuntimeEvidenceV2,
    validate_causal_runtime_evidence_v2,
)
from .content_addressing import cid_for_dag_json, validate_cid
from .contracts import (
    CAUSAL_PROOF_PROTOCOL_V2_CID,
    CAUSAL_PROOF_VARIANT_PROFILE_V2_CID,
    CaseResultRecord,
    OutcomeStatus,
    SEMANTIC_PROTOCOL_V2_CID,
)
from .metrics import validate_causal_rescue_aggregate
from .variants import (
    VARIANT_REGISTRY,
    get_causal_proof_variant_profile,
)

if TYPE_CHECKING:
    from .holdout_execution import G232ReplacementHoldoutAuthorization


G230_SOURCE_FREEZE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.g230-source-freeze.v2"
)
G230_EXECUTION_IDENTITIES_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.g230-execution-identities.v2"
)
G210_RECEIPT_MATRIX_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g210-validated-receipt-matrix.v2"
)
G210_RUNTIME_RECEIPT_MATRIX_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g210-runtime-receipt-matrix.v2"
)
G234_RUNTIME_GATE_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g234-runtime-gate-receipt.v2"
)
G234_PAIRED_EFFICACY_PAIR_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g234-paired-efficacy-pair.v2"
)
G234_PAIRED_EFFICACY_COMPARISON_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g234-paired-efficacy-comparison.v2"
)
G230_RECEIPT_REPLAY_ASSESSMENT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g230-receipt-replay-assessment.v2"
)
G230_REVISED_PILOT_DECISION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g230-revised-pilot-decision.v2"
)

G230_IDENTITY_KEYS: Final = (
    "environment",
    "capability",
    "resource_policy",
    "prompt_bundle",
    "model_identity",
    "cache_policy",
)
G230_BOUND_ARTIFACT_KEYS: Final = (
    "semantic_calibration",
    "causal_receipt_matrix",
    "replacement_holdout_seal",
)
G230_GATE_IDS: Final = (
    "semantic_quality",
    "efficacy",
    "paired_statistics",
    "cost",
    "reliability",
    "routing",
    "pareto",
    "safety",
    "replay",
)
G234_GATE_IDS: Final = (
    "efficacy",
    "reliability",
    "routing",
)
G230_DEPENDENCY_KEYS: Final = (
    "semantic_protocol",
    "semantic_calibration",
    "causal_protocol",
    "causal_variant_profile",
    "causal_rescue_manifest_set",
    "causal_receipt_matrix",
    "replacement_holdout_seal",
    "source_freeze",
    "execution_identities",
)
G210_VARIANT_IDS: Final = tuple(f"A{index}" for index in range(13))
G210_CACHE_MODES: Final = ("cold", "warm")
G210_SPLITS: Final = ("pilot", "development")
_MEASURED_EFFICACY_STATUSES: Final = frozenset(
    {
        OutcomeStatus.VERIFIED,
        OutcomeStatus.NOT_VERIFIED,
        OutcomeStatus.REJECTED,
    }
)

_SAFE_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_COMMIT: Final = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST: Final = re.compile(r"[0-9a-f]{64}\Z")
_SEMANTIC_CALIBRATION_REPORT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.semantic-calibration-report.v2"
)


class RevisedPilotAuthorizationError(ValueError):
    """Raised for malformed typed evidence, never for a negative decision."""


def HSSLEV2309D46() -> str:
    """Return AST-verifiable evidence for the revised pilot trust boundary."""

    return (
        "source-recomputed G200/G201, G210/G212, and G220 evidence with complete "
        "pilot/development gates and fail-closed replacement authorization"
    )


def HSSLEV2343B16() -> str:
    """Return evidence for the bounded full-runtime positive-gate family."""

    return (
        "source-recomputed full-runtime paired efficacy, reliability, "
        "and routing validators"
    )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise RevisedPilotAuthorizationError(
            f"{field} must be an object with string keys"
        )
    return value


def _exact(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    if set(value) != expected:
        raise RevisedPilotAuthorizationError(
            f"{field} fields changed: expected {sorted(expected)!r}"
        )


def _array(value: object, field: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, bytearray, Mapping)) or not isinstance(
        value, Sequence
    ):
        raise RevisedPilotAuthorizationError(f"{field} must be an array")
    return tuple(value)


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise RevisedPilotAuthorizationError(
            f"{field} must be a safe nonempty identifier"
        )
    return value


def _commit(value: object, field: str = "source_commit") -> str:
    if not isinstance(value, str) or not _COMMIT.fullmatch(value):
        raise RevisedPilotAuthorizationError(
            f"{field} must be a full lowercase 40-character Git commit"
        )
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise RevisedPilotAuthorizationError(
            f"{field} must be a lowercase SHA-256 compatibility digest"
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
        raise RevisedPilotAuthorizationError(
            f"{field} must be a canonical CIDv1/base32/sha2-256 CID"
        ) from exc


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise RevisedPilotAuthorizationError(f"{field} must be boolean")
    return value


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _plain(item)
            for key, item in sorted(value.items())
        }
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise RevisedPilotAuthorizationError(
        f"unsupported DAG-JSON value: {type(value).__name__}"
    )


def _freeze_json(value: object) -> object:
    """Deeply detach and freeze one validated DAG-JSON value."""

    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise RevisedPilotAuthorizationError(
                "DAG-JSON object keys must be strings"
            )
        return MappingProxyType(
            {
                str(key): _freeze_json(item)
                for key, item in sorted(value.items())
            }
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise RevisedPilotAuthorizationError(
        f"unsupported DAG-JSON value: {type(value).__name__}"
    )


def _candidate_ids(value: object, field: str) -> tuple[str, ...]:
    candidates = tuple(
        _safe_id(item, f"{field}[]") for item in _array(value, field)
    )
    if (
        not 1 <= len(candidates) <= 4
        or len(candidates) != len(set(candidates))
        or any(
            item not in VARIANT_REGISTRY or item in {"A0", "S1"}
            for item in candidates
        )
    ):
        raise RevisedPilotAuthorizationError(
            f"{field} must contain one to four distinct registered "
            "nonbaseline, nondiagnostic arms"
        )
    return candidates


def _manifest_split(manifest: CausalRescueManifestV2) -> str:
    splits = {case.split.value for case in manifest.cases}
    if len(splits) != 1:
        raise RevisedPilotAuthorizationError(
            "one causal rescue manifest cannot mix pilot and development"
        )
    split = next(iter(splits))
    if split not in G210_SPLITS:
        raise RevisedPilotAuthorizationError(
            "causal rescue manifest contains a non-selection split"
        )
    return split


def _validate_semantic_calibration_reference(value: object) -> str:
    """Validate integrity only; this is deliberately not G200 authority."""

    report = _mapping(value, "semantic calibration reference")
    if (
        report.get("schema") != _SEMANTIC_CALIBRATION_REPORT_SCHEMA_V2
        or report.get("semantic_protocol_cid") != SEMANTIC_PROTOCOL_V2_CID
    ):
        raise RevisedPilotAuthorizationError(
            "semantic calibration reference identity changed"
        )
    artifact_cid = _cid(
        report.get("artifact_cid"),
        "semantic calibration artifact_cid",
    )
    body = {
        key: _plain(item)
        for key, item in report.items()
        if key != "artifact_cid"
    }
    if cid_for_dag_json(body) != artifact_cid:
        raise RevisedPilotAuthorizationError(
            "semantic calibration reference CID changed from its body"
        )
    return artifact_cid


@dataclass(frozen=True, slots=True)
class G230SourceFreezeReceipt:
    """Public receipt for one clean, detached source tree."""

    schema: str
    source_commit: str
    source_tree_cid: str
    detached_head: bool
    worktree_clean: bool
    submodules_clean: bool
    receipt_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G230_SOURCE_FREEZE_SCHEMA:
            raise RevisedPilotAuthorizationError(
                "unsupported G230 source-freeze schema"
            )
        object.__setattr__(self, "source_commit", _commit(self.source_commit))
        object.__setattr__(
            self,
            "source_tree_cid",
            _cid(self.source_tree_cid, "source_tree_cid"),
        )
        for field in (
            "detached_head",
            "worktree_clean",
            "submodules_clean",
        ):
            _boolean(getattr(self, field), field)
        expected = cid_for_dag_json(self.identity_payload())
        if self.receipt_cid is None:
            object.__setattr__(self, "receipt_cid", expected)
        elif _cid(self.receipt_cid, "receipt_cid") != expected:
            raise RevisedPilotAuthorizationError(
                "source-freeze receipt CID does not match its body"
            )

    @property
    def ready(self) -> bool:
        return (
            self.detached_head
            and self.worktree_clean
            and self.submodules_clean
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "source_commit": self.source_commit,
            "source_tree_cid": self.source_tree_cid,
            "detached_head": self.detached_head,
            "worktree_clean": self.worktree_clean,
            "submodules_clean": self.submodules_clean,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_cid": self.receipt_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "source freeze")
        _exact(data, set(cls.__dataclass_fields__), "source freeze")
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            source_commit=data["source_commit"],  # type: ignore[arg-type]
            source_tree_cid=data["source_tree_cid"],  # type: ignore[arg-type]
            detached_head=data["detached_head"],  # type: ignore[arg-type]
            worktree_clean=data["worktree_clean"],  # type: ignore[arg-type]
            submodules_clean=data["submodules_clean"],  # type: ignore[arg-type]
            receipt_cid=data["receipt_cid"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class G230ExecutionIdentities:
    """CID bundle for frozen environment/model/prompt/cache identities."""

    schema: str
    source_commit: str
    source_freeze_receipt_cid: str
    legacy_environment_sha256: str
    identity_cids: Mapping[str, str]
    bound_artifact_cids: Mapping[str, str]
    frozen: bool
    bundle_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G230_EXECUTION_IDENTITIES_SCHEMA:
            raise RevisedPilotAuthorizationError(
                "unsupported G230 execution-identities schema"
            )
        object.__setattr__(self, "source_commit", _commit(self.source_commit))
        object.__setattr__(
            self,
            "source_freeze_receipt_cid",
            _cid(
                self.source_freeze_receipt_cid,
                "source_freeze_receipt_cid",
            ),
        )
        object.__setattr__(
            self,
            "legacy_environment_sha256",
            _digest(
                self.legacy_environment_sha256,
                "legacy_environment_sha256",
            ),
        )
        identities = _mapping(self.identity_cids, "identity_cids")
        if set(identities) != set(G230_IDENTITY_KEYS):
            raise RevisedPilotAuthorizationError(
                "execution identity set must exactly bind environment, "
                "capability, resource, prompt, model, and cache identities"
            )
        object.__setattr__(
            self,
            "identity_cids",
            MappingProxyType(
                {
                    key: _cid(
                        identities[key],
                        f"identity_cids.{key}",
                    )
                    for key in G230_IDENTITY_KEYS
                }
            ),
        )
        artifacts = _mapping(
            self.bound_artifact_cids, "bound_artifact_cids"
        )
        if set(artifacts) != set(G230_BOUND_ARTIFACT_KEYS):
            raise RevisedPilotAuthorizationError(
                "source bundle must bind the exact semantic, causal, and "
                "replacement-seal artifacts"
            )
        object.__setattr__(
            self,
            "bound_artifact_cids",
            MappingProxyType(
                {
                    key: _cid(
                        artifacts[key],
                        f"bound_artifact_cids.{key}",
                    )
                    for key in G230_BOUND_ARTIFACT_KEYS
                }
            ),
        )
        _boolean(self.frozen, "frozen")
        expected = cid_for_dag_json(self.identity_payload())
        if self.bundle_cid is None:
            object.__setattr__(self, "bundle_cid", expected)
        elif _cid(self.bundle_cid, "bundle_cid") != expected:
            raise RevisedPilotAuthorizationError(
                "execution-identity bundle CID does not match its body"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "source_commit": self.source_commit,
            "source_freeze_receipt_cid": self.source_freeze_receipt_cid,
            "legacy_environment_sha256": self.legacy_environment_sha256,
            "identity_cids": dict(self.identity_cids),
            "bound_artifact_cids": dict(self.bound_artifact_cids),
            "frozen": self.frozen,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "bundle_cid": self.bundle_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "execution identities")
        _exact(data, set(cls.__dataclass_fields__), "execution identities")
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            source_commit=data["source_commit"],  # type: ignore[arg-type]
            source_freeze_receipt_cid=data[
                "source_freeze_receipt_cid"
            ],  # type: ignore[arg-type]
            legacy_environment_sha256=data[
                "legacy_environment_sha256"
            ],  # type: ignore[arg-type]
            identity_cids=_mapping(
                data["identity_cids"], "identity_cids"
            ),  # type: ignore[arg-type]
            bound_artifact_cids=_mapping(
                data["bound_artifact_cids"], "bound_artifact_cids"
            ),  # type: ignore[arg-type]
            frozen=data["frozen"],  # type: ignore[arg-type]
            bundle_cid=data["bundle_cid"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class G210ReceiptMatrix:
    """Wrapper over authoritative G210 manifests, profiles, and aggregates.

    Partial matrices are representable so readiness can report what is
    missing.  ``complete`` and ``validation_issues`` are derived properties;
    callers cannot set them.
    """

    semantic_calibration_artifact_cid: str
    rescue_manifests: tuple[CausalRescueManifestV2, ...]
    execution_profiles: tuple[CausalExecutionProfileV2, ...]
    causal_aggregates: tuple[Mapping[str, object], ...]
    schema: str = G210_RECEIPT_MATRIX_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != G210_RECEIPT_MATRIX_SCHEMA:
            raise RevisedPilotAuthorizationError(
                "unsupported G210 receipt-matrix schema"
            )
        object.__setattr__(
            self,
            "semantic_calibration_artifact_cid",
            _cid(
                self.semantic_calibration_artifact_cid,
                "semantic_calibration_artifact_cid",
            ),
        )
        manifests = tuple(self.rescue_manifests)
        if any(
            not isinstance(item, CausalRescueManifestV2)
            for item in manifests
        ):
            raise RevisedPilotAuthorizationError(
                "matrix rescue manifests must use CausalRescueManifestV2"
            )
        manifest_splits = tuple(_manifest_split(item) for item in manifests)
        if (
            len(manifest_splits) != len(set(manifest_splits))
            or tuple(sorted(manifest_splits)) != manifest_splits
        ):
            raise RevisedPilotAuthorizationError(
                "rescue manifests must be unique and sorted by split"
            )
        object.__setattr__(self, "rescue_manifests", manifests)

        profiles = tuple(self.execution_profiles)
        if any(
            not isinstance(item, CausalExecutionProfileV2)
            for item in profiles
        ):
            raise RevisedPilotAuthorizationError(
                "matrix profiles must use CausalExecutionProfileV2"
            )
        if (
            len({item.rescue_manifest_cid for item in profiles})
            != len(profiles)
            or tuple(
                sorted(item.rescue_manifest_cid for item in profiles)
            )
            != tuple(item.rescue_manifest_cid for item in profiles)
        ):
            raise RevisedPilotAuthorizationError(
                "execution profiles must be unique and CID-sorted"
            )
        object.__setattr__(self, "execution_profiles", profiles)

        aggregates: list[Mapping[str, object]] = []
        for value in self.causal_aggregates:
            try:
                validated = validate_causal_rescue_aggregate(value)
            except (TypeError, ValueError) as exc:
                raise RevisedPilotAuthorizationError(
                    "matrix contains a causal aggregate that does not replay"
                ) from exc
            frozen = _freeze_json(validated)
            if not isinstance(frozen, Mapping):
                raise RevisedPilotAuthorizationError(
                    "validated causal aggregate must remain an object"
                )
            aggregates.append(frozen)
        aggregate_keys = tuple(_aggregate_key(item) for item in aggregates)
        if (
            len(aggregate_keys) != len(set(aggregate_keys))
            or tuple(sorted(aggregate_keys)) != aggregate_keys
        ):
            raise RevisedPilotAuthorizationError(
                "causal aggregates must have unique sorted split/variant/cache "
                "coordinates"
            )
        object.__setattr__(self, "causal_aggregates", tuple(aggregates))

    @property
    def rescue_manifest_set_cid(self) -> str:
        return cid_for_dag_json(
            {
                "schema": (
                    "ipfs-datasets.logic-pipeline-benchmark."
                    "causal-rescue-manifest-set.v2"
                ),
                "manifest_cids": [
                    item.manifest_cid for item in self.rescue_manifests
                ],
            }
        )

    @property
    def validation_issues(self) -> tuple[str, ...]:
        issues: set[str] = set()
        manifests = {
            _manifest_split(item): item for item in self.rescue_manifests
        }
        if set(manifests) != set(G210_SPLITS):
            issues.add("missing_pilot_or_development_rescue_manifest")
        profiles_by_manifest = {
            item.rescue_manifest_cid: item for item in self.execution_profiles
        }
        if set(profiles_by_manifest) != {
            item.manifest_cid for item in self.rescue_manifests
        }:
            issues.add("execution_profile_manifest_coverage_mismatch")
        for manifest in self.rescue_manifests:
            profile = profiles_by_manifest.get(manifest.manifest_cid)
            if profile is None:
                continue
            if (
                profile.plan_cid != manifest.plan_cid
                or profile.source_manifest_cid
                != manifest.source_manifest_cid
                or profile.semantic_calibration_artifact_cid
                != self.semantic_calibration_artifact_cid
            ):
                issues.add("execution_profile_source_binding_mismatch")

        aggregates = {
            _aggregate_key(item): item for item in self.causal_aggregates
        }
        run_ids = {
            item.get("run_id") for item in self.causal_aggregates
        }
        if self.causal_aggregates and (
            len(run_ids) != 1
            or not isinstance(next(iter(run_ids)), str)
        ):
            issues.add("aggregate_run_identity_mismatch")
        profile_environments = {
            item.environment_sha256 for item in self.execution_profiles
        }
        if self.execution_profiles and len(profile_environments) != 1:
            issues.add("execution_profile_environment_mismatch")
        expected = {
            (split, variant_id, cache_mode)
            for split in G210_SPLITS
            for variant_id in G210_VARIANT_IDS
            for cache_mode in G210_CACHE_MODES
        }
        if set(aggregates) != expected:
            issues.add("incomplete_pilot_development_receipt_cartesian")

        reference_exposure: dict[
            tuple[str, str, str],
            tuple[object, object, object, object],
        ] = {}
        profile_environment_by_split = {
            _manifest_split(manifest): profiles_by_manifest[
                manifest.manifest_cid
            ].environment_sha256
            for manifest in self.rescue_manifests
            if manifest.manifest_cid in profiles_by_manifest
        }
        for (split, variant_id, cache_mode), aggregate in aggregates.items():
            manifest = manifests.get(split)
            if manifest is None:
                issues.add("aggregate_split_has_no_rescue_manifest")
                continue
            expected_cases = {case.case_id: case for case in manifest.cases}
            case_receipts = aggregate.get("case_receipts")
            if not isinstance(case_receipts, (list, tuple)):
                # The metrics validator above should make this unreachable.
                issues.add("aggregate_case_receipts_missing")
                continue
            actual_cases: set[str] = set()
            for raw_receipt in case_receipts:
                receipt = _mapping(raw_receipt, "causal case receipt")
                case_result = _mapping(
                    receipt.get("case_result"), "causal case result"
                )
                selection = _mapping(
                    receipt.get("selection_receipt"),
                    "causal selection receipt",
                )
                case_id = str(receipt.get("case_id"))
                actual_cases.add(case_id)
                manifest_case = expected_cases.get(case_id)
                if (
                    manifest_case is None
                    or receipt.get("source_cid")
                    != manifest_case.source_cid
                    or case_result.get("split") != split
                    or case_result.get("cache_mode") != cache_mode
                    or case_result.get("variant_id") != variant_id
                    or receipt.get("variant_id") != variant_id
                    or case_result.get("case_manifest_sha256")
                    != manifest.case_manifest_sha256
                    or receipt.get("protocol_cid")
                    != CAUSAL_PROOF_PROTOCOL_V2_CID
                    or receipt.get("variant_profile_cid")
                    != CAUSAL_PROOF_VARIANT_PROFILE_V2_CID
                ):
                    issues.add("aggregate_case_source_or_coordinate_mismatch")
                environment = profile_environment_by_split.get(split)
                if "stages" in case_result:
                    restored_result = CaseResultRecord.from_dict(
                        _plain(case_result)
                    )
                    environment_matches = {
                        stage.provenance.environment_sha256
                        for stage in restored_result.stages
                    } == {environment}
                else:
                    # Compatibility for shallow validator test doubles. Real
                    # aggregate receipts have already passed the causal
                    # aggregate validator and always include full case stages.
                    environment_matches = (
                        case_result.get("environment_sha256") == environment
                    )
                if (
                    environment is None
                    or not environment_matches
                ):
                    issues.add("aggregate_environment_binding_mismatch")
                compiler_state = receipt.get("compiler_reference_state")
                if compiler_state not in {"absent", "rejected"}:
                    issues.add("compiler_reference_not_failed")
                compiler = _mapping(
                    selection.get("compiler_reference"),
                    "compiler reference",
                )
                exposure = (
                    compiler.get("state"),
                    compiler.get("candidate_cid"),
                    compiler.get("artifact_cid"),
                    compiler.get("kernel_checked"),
                )
                exposure_key = (split, case_id, cache_mode)
                previous = reference_exposure.setdefault(
                    exposure_key, exposure
                )
                if previous != exposure:
                    issues.add("unequal_compiler_reference_exposure")
                optional = selection.get("optional_candidates")
                if not isinstance(optional, (list, tuple)):
                    issues.add("optional_candidate_receipts_missing")
                elif manifest_case is not None and any(
                    not isinstance(item, Mapping)
                    or item.get("source")
                    not in manifest_case.optional_components
                    for item in optional
                ):
                    issues.add("optional_route_outside_rescue_manifest")
            if actual_cases != set(expected_cases):
                issues.add("aggregate_case_population_incomplete")
        return tuple(sorted(issues))

    @property
    def complete(self) -> bool:
        return not self.validation_issues

    @property
    def matrix_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "causal_proof_protocol_cid": CAUSAL_PROOF_PROTOCOL_V2_CID,
            "variant_profile_cid": CAUSAL_PROOF_VARIANT_PROFILE_V2_CID,
            "semantic_calibration_artifact_cid": (
                self.semantic_calibration_artifact_cid
            ),
            "rescue_manifests": [
                item.to_dict() for item in self.rescue_manifests
            ],
            "execution_profiles": [
                item.to_dict() for item in self.execution_profiles
            ],
            "causal_aggregates": [
                _plain(item) for item in self.causal_aggregates
            ],
            "derived_validation_issues": list(self.validation_issues),
            "derived_complete": self.complete,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "matrix_cid": self.matrix_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G210 receipt matrix")
        expected = {
            "schema",
            "semantic_protocol_cid",
            "causal_proof_protocol_cid",
            "variant_profile_cid",
            "semantic_calibration_artifact_cid",
            "rescue_manifests",
            "execution_profiles",
            "causal_aggregates",
            "derived_validation_issues",
            "derived_complete",
            "matrix_cid",
        }
        _exact(data, expected, "G210 receipt matrix")
        if (
            data["semantic_protocol_cid"] != SEMANTIC_PROTOCOL_V2_CID
            or data["causal_proof_protocol_cid"]
            != CAUSAL_PROOF_PROTOCOL_V2_CID
            or data["variant_profile_cid"]
            != CAUSAL_PROOF_VARIANT_PROFILE_V2_CID
        ):
            raise RevisedPilotAuthorizationError(
                "G210 matrix protocol identity drifted"
            )
        result = cls(
            schema=data["schema"],  # type: ignore[arg-type]
            semantic_calibration_artifact_cid=data[
                "semantic_calibration_artifact_cid"
            ],  # type: ignore[arg-type]
            rescue_manifests=tuple(
                CausalRescueManifestV2.from_dict(item)
                for item in _array(
                    data["rescue_manifests"], "rescue_manifests"
                )
            ),
            execution_profiles=tuple(
                CausalExecutionProfileV2.from_dict(item)
                for item in _array(
                    data["execution_profiles"], "execution_profiles"
                )
            ),
            causal_aggregates=tuple(
                _mapping(item, "causal aggregate")
                for item in _array(
                    data["causal_aggregates"], "causal_aggregates"
                )
            ),
        )
        if _plain(data) != result.to_dict():
            raise RevisedPilotAuthorizationError(
                "G210 receipt matrix derived fields or CID changed"
            )
        return result


def _aggregate_key(
    aggregate: Mapping[str, object],
) -> tuple[str, str, str]:
    case_receipts = aggregate.get("case_receipts")
    if (
        not isinstance(case_receipts, (list, tuple))
        or not case_receipts
    ):
        raise RevisedPilotAuthorizationError(
            "causal aggregate must embed complete case receipts"
        )
    coordinates: set[tuple[str, str, str]] = set()
    for raw in case_receipts:
        receipt = _mapping(raw, "causal aggregate case receipt")
        case_result = _mapping(
            receipt.get("case_result"), "causal aggregate case result"
        )
        split = case_result.get("split")
        variant_id = case_result.get("variant_id")
        cache_mode = case_result.get("cache_mode")
        if (
            split not in G210_SPLITS
            or variant_id not in G210_VARIANT_IDS
            or cache_mode not in G210_CACHE_MODES
        ):
            raise RevisedPilotAuthorizationError(
                "causal aggregate embeds an unsupported coordinate"
            )
        coordinates.add(
            (str(split), str(variant_id), str(cache_mode))
        )
    if len(coordinates) != 1:
        raise RevisedPilotAuthorizationError(
            "one causal aggregate cannot mix split, variant, or cache mode"
        )
    return next(iter(coordinates))


def _runtime_coordinate(
    evidence: CausalRuntimeEvidenceV2,
) -> tuple[str, str, str, str]:
    result = evidence.case_result
    return (
        result.split.value,
        result.variant_id,
        result.cache_mode.value,
        result.case_id,
    )


@dataclass(frozen=True, slots=True)
class G210RuntimeReceiptMatrixV2:
    """Full-runtime authority layered over the reduced G210 aggregates.

    ``G210ReceiptMatrix`` remains useful for causal rates and cost summaries,
    but those reduced receipts cannot prove the exact compiler exposure,
    semantic frontend, proof context, or per-check kernel telemetry.  This
    wrapper replays every :class:`CausalRuntimeEvidenceV2` and joins it back to
    the corresponding reduced aggregate without granting either representation
    authority on its own.

    Partial matrices remain representable for diagnostics.  Completeness is
    derived exclusively from the embedded source evidence.
    """

    receipt_matrix: G210ReceiptMatrix
    runtime_evidence: tuple[CausalRuntimeEvidenceV2, ...]
    schema: str = G210_RUNTIME_RECEIPT_MATRIX_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != G210_RUNTIME_RECEIPT_MATRIX_SCHEMA:
            raise RevisedPilotAuthorizationError(
                "unsupported G210 runtime-receipt matrix schema"
            )
        if not isinstance(self.receipt_matrix, G210ReceiptMatrix):
            raise RevisedPilotAuthorizationError(
                "runtime matrix requires the reduced G210ReceiptMatrix"
            )
        try:
            reduced = G210ReceiptMatrix.from_dict(
                self.receipt_matrix.to_dict()
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise RevisedPilotAuthorizationError(
                "runtime matrix reduced evidence failed replay"
            ) from exc
        object.__setattr__(self, "receipt_matrix", reduced)

        replayed: list[CausalRuntimeEvidenceV2] = []
        for value in self.runtime_evidence:
            if not isinstance(value, CausalRuntimeEvidenceV2):
                raise RevisedPilotAuthorizationError(
                    "runtime matrix entries must be CausalRuntimeEvidenceV2"
                )
            try:
                replayed.append(
                    validate_causal_runtime_evidence_v2(value.to_dict())
                )
            except (TypeError, ValueError, KeyError) as exc:
                raise RevisedPilotAuthorizationError(
                    "runtime matrix contains evidence that does not replay"
                ) from exc
        replayed.sort(key=_runtime_coordinate)
        coordinates = tuple(_runtime_coordinate(item) for item in replayed)
        receipt_cids = tuple(item.receipt_cid for item in replayed)
        if len(coordinates) != len(set(coordinates)):
            raise RevisedPilotAuthorizationError(
                "runtime matrix contains a duplicate execution coordinate"
            )
        if len(receipt_cids) != len(set(receipt_cids)):
            raise RevisedPilotAuthorizationError(
                "runtime matrix contains a duplicate evidence receipt"
            )
        object.__setattr__(self, "runtime_evidence", tuple(replayed))

    @property
    def validation_issues(self) -> tuple[str, ...]:
        issues = {
            f"reduced:{item}"
            for item in self.receipt_matrix.validation_issues
        }
        manifests = {
            _manifest_split(manifest): manifest
            for manifest in self.receipt_matrix.rescue_manifests
        }
        profiles = {
            _manifest_split(manifest): next(
                (
                    profile
                    for profile in self.receipt_matrix.execution_profiles
                    if profile.rescue_manifest_cid == manifest.manifest_cid
                ),
                None,
            )
            for manifest in self.receipt_matrix.rescue_manifests
        }
        expected = {
            (
                split,
                variant_id,
                cache_mode,
                case.case_id,
            )
            for split, manifest in manifests.items()
            for case in manifest.cases
            for variant_id in G210_VARIANT_IDS
            for cache_mode in G210_CACHE_MODES
        }
        evidence_by_coordinate = {
            _runtime_coordinate(item): item
            for item in self.runtime_evidence
        }
        if set(evidence_by_coordinate) != expected:
            issues.add("runtime_receipt_cartesian_incomplete")

        aggregate_receipts: dict[
            tuple[str, str, str, str], Mapping[str, object]
        ] = {}
        aggregate_runs: set[object] = set()
        for aggregate in self.receipt_matrix.causal_aggregates:
            split, variant_id, cache_mode = _aggregate_key(aggregate)
            aggregate_runs.add(aggregate.get("run_id"))
            raw_receipts = aggregate.get("case_receipts")
            if not isinstance(raw_receipts, (list, tuple)):
                issues.add("aggregate_case_receipts_missing")
                continue
            for raw in raw_receipts:
                receipt = _mapping(raw, "causal aggregate case receipt")
                key = (
                    split,
                    variant_id,
                    cache_mode,
                    str(receipt.get("case_id")),
                )
                if key in aggregate_receipts:
                    issues.add("aggregate_case_receipt_duplicated")
                aggregate_receipts[key] = receipt
        if set(aggregate_receipts) != set(evidence_by_coordinate):
            issues.add("runtime_aggregate_coordinate_mismatch")

        run_ids = {
            evidence.case_result.run_id
            for evidence in self.runtime_evidence
        }
        if self.runtime_evidence and (
            len(run_ids) != 1 or run_ids != aggregate_runs
        ):
            issues.add("runtime_run_identity_mismatch")

        exposure_by_reference: dict[
            tuple[str, str, str], str
        ] = {}
        for coordinate, evidence in evidence_by_coordinate.items():
            split, variant_id, cache_mode, case_id = coordinate
            manifest = manifests.get(split)
            case = (
                None
                if manifest is None
                else next(
                    (
                        item
                        for item in manifest.cases
                        if item.case_id == case_id
                    ),
                    None,
                )
            )
            profile = profiles.get(split)
            environment = (
                None if profile is None else profile.environment_sha256
            )
            result = evidence.case_result
            if (
                case is None
                or evidence.compiler_exposure.source_cid != case.source_cid
                or _plain(evidence.proof_context)
                != _plain(case.proof_context)
                or result.case_manifest_sha256
                != manifest.case_manifest_sha256  # type: ignore[union-attr]
                or result.split.value != split
                or result.variant_id != variant_id
                or result.cache_mode.value != cache_mode
                or result.case_id != case_id
            ):
                issues.add("runtime_rescue_source_binding_mismatch")
            stage_environments = {
                stage.provenance.environment_sha256
                for stage in result.stages
            }
            if (
                environment is None
                or stage_environments != {environment}
            ):
                issues.add("runtime_environment_binding_mismatch")
            reduced = aggregate_receipts.get(coordinate)
            if (
                reduced is None
                or _plain(reduced)
                != _plain(evidence.causal_case_receipt)
            ):
                issues.add("runtime_reduced_receipt_join_mismatch")
            reference_key = (split, case_id, cache_mode)
            exposure_cid = evidence.compiler_exposure.receipt_cid
            previous = exposure_by_reference.setdefault(
                reference_key, exposure_cid
            )
            if previous != exposure_cid:
                issues.add("runtime_unequal_compiler_exposure")
        return tuple(sorted(issues))

    @property
    def complete(self) -> bool:
        return not self.validation_issues

    @property
    def runtime_matrix_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "causal_proof_protocol_cid": CAUSAL_PROOF_PROTOCOL_V2_CID,
            "reduced_receipt_matrix": self.receipt_matrix.to_dict(),
            "runtime_evidence": [
                item.to_dict() for item in self.runtime_evidence
            ],
            "derived_validation_issues": list(self.validation_issues),
            "derived_complete": self.complete,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "runtime_matrix_cid": self.runtime_matrix_cid,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G210 runtime receipt matrix")
        expected = {
            "schema",
            "semantic_protocol_cid",
            "causal_proof_protocol_cid",
            "reduced_receipt_matrix",
            "runtime_evidence",
            "derived_validation_issues",
            "derived_complete",
            "runtime_matrix_cid",
        }
        _exact(data, expected, "G210 runtime receipt matrix")
        if (
            data.get("semantic_protocol_cid") != SEMANTIC_PROTOCOL_V2_CID
            or data.get("causal_proof_protocol_cid")
            != CAUSAL_PROOF_PROTOCOL_V2_CID
        ):
            raise RevisedPilotAuthorizationError(
                "G210 runtime matrix protocol identity drifted"
            )
        raw_evidence = _array(
            data["runtime_evidence"], "runtime_evidence"
        )
        result = cls(
            schema=data["schema"],  # type: ignore[arg-type]
            receipt_matrix=G210ReceiptMatrix.from_dict(
                data["reduced_receipt_matrix"]
            ),
            runtime_evidence=tuple(
                validate_causal_runtime_evidence_v2(item)
                for item in raw_evidence
            ),
        )
        if _plain(data) != result.to_dict():
            raise RevisedPilotAuthorizationError(
                "G210 runtime matrix derived fields or CID changed"
            )
        return result


def build_g210_runtime_receipt_matrix_v2(
    pilot_batch: object,
    development_batch: object,
) -> G210RuntimeReceiptMatrixV2:
    """Join two persisted G211 batches into one authoritative G210 matrix.

    Both batches are re-read from their immutable namespaces before their
    reduced aggregates and full runtime receipts are combined.  The function
    returns only a complete A0--A12, cold/warm, pilot/development Cartesian;
    partial evidence remains available through direct construction of
    :class:`G210RuntimeReceiptMatrixV2` for diagnostics.
    """

    from .causal_batch import (
        CausalRuntimeBatchResultV2,
        validate_causal_runtime_batch_v2,
    )

    if not isinstance(pilot_batch, CausalRuntimeBatchResultV2) or not isinstance(
        development_batch, CausalRuntimeBatchResultV2
    ):
        raise RevisedPilotAuthorizationError(
            "G210 runtime matrix builder requires two persisted G211 batches"
        )
    supplied = (pilot_batch, development_batch)
    replayed = tuple(
        validate_causal_runtime_batch_v2(
            batch.plan,
            batch.rescue_manifest,
            batch.execution_profile,
            output_root=batch.output_root,
        )
        for batch in supplied
    )
    by_split = {batch.plan.split.value: batch for batch in replayed}
    if set(by_split) != set(G210_SPLITS) or len(by_split) != len(replayed):
        raise RevisedPilotAuthorizationError(
            "G210 runtime matrix requires exact pilot and development batches"
        )
    ordered = tuple(by_split[split] for split in G210_SPLITS)
    calibration_cids = {
        batch.execution_profile.semantic_calibration_artifact_cid
        for batch in ordered
    }
    environments = {
        batch.execution_profile.environment_sha256
        for batch in ordered
    }
    run_ids = {batch.plan.run_id for batch in ordered}
    if (
        len(calibration_cids) != 1
        or len(environments) != 1
        or len(run_ids) != 1
    ):
        raise RevisedPilotAuthorizationError(
            "G211 batches differ in calibration, environment, or run identity"
        )
    reduced = G210ReceiptMatrix(
        semantic_calibration_artifact_cid=next(iter(calibration_cids)),
        rescue_manifests=tuple(
            sorted(
                (batch.rescue_manifest for batch in ordered),
                key=_manifest_split,
            )
        ),
        execution_profiles=tuple(
            sorted(
                (batch.execution_profile for batch in ordered),
                key=lambda item: item.rescue_manifest_cid,
            )
        ),
        causal_aggregates=tuple(
            sorted(
                (
                    aggregate
                    for batch in ordered
                    for aggregate in batch.causal_aggregates
                ),
                key=_aggregate_key,
            )
        ),
    )
    result = G210RuntimeReceiptMatrixV2(
        receipt_matrix=reduced,
        runtime_evidence=tuple(
            item
            for batch in ordered
            for item in batch.evidence
        ),
    )
    if not result.complete:
        raise RevisedPilotAuthorizationError(
            "persisted G211 batches do not form an authoritative G210 matrix: "
            + ", ".join(result.validation_issues)
        )
    return result


def _gate_candidates(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)):
        raise RevisedPilotAuthorizationError(
            "candidate_variant_ids must be an array"
        )
    candidates = tuple(
        _safe_id(item, "candidate_variant_ids[]") for item in value
    )
    if (
        not candidates
        or len(candidates) != len(set(candidates))
        or any(
            item not in VARIANT_REGISTRY
            or item in {"A0", "S1"}
            or VARIANT_REGISTRY[item].paired_against != "A0"
            or VARIANT_REGISTRY[item].primary_candidate is not True
            or VARIANT_REGISTRY[item].safety_diagnostic_only is True
            for item in candidates
        )
    ):
        raise RevisedPilotAuthorizationError(
            "candidate_variant_ids must contain distinct primary "
            "A0-paired arms"
        )
    candidate_set = set(candidates)
    return tuple(
        variant_id
        for variant_id in G210_VARIANT_IDS
        if variant_id in candidate_set
    )


def _scoped_runtime_evidence(
    matrix: G210RuntimeReceiptMatrixV2,
    candidate_variant_ids: Sequence[str],
) -> tuple[tuple[str, ...], tuple[CausalRuntimeEvidenceV2, ...]]:
    if not isinstance(matrix, G210RuntimeReceiptMatrixV2):
        raise RevisedPilotAuthorizationError(
            "source gate requires a G210RuntimeReceiptMatrixV2"
        )
    candidates = _gate_candidates(candidate_variant_ids)
    selected = {"A0", *candidates}
    evidence = tuple(
        item
        for item in matrix.runtime_evidence
        if item.case_result.variant_id in selected
    )
    return candidates, evidence


def _g234_runtime_gate_receipt(
    *,
    gate_id: str,
    matrix: G210RuntimeReceiptMatrixV2,
    candidates: tuple[str, ...],
    evidence: Sequence[CausalRuntimeEvidenceV2],
    status: str,
    failure_codes: Sequence[str],
    gate_evidence: Mapping[str, object],
    source_index_cid: str | None = None,
) -> dict[str, object]:
    if gate_id not in G234_GATE_IDS:
        raise RevisedPilotAuthorizationError("unknown G234 gate identifier")
    if status not in {"passed", "failed", "incomplete"}:
        raise RevisedPilotAuthorizationError("invalid source-gate status")
    failures = tuple(sorted(set(failure_codes)))
    complete = status != "incomplete"
    passed = status == "passed"
    if (passed and failures) or (not passed and not failures):
        raise RevisedPilotAuthorizationError(
            "source-gate status and failure codes disagree"
        )
    bound_source_index_cid = (
        matrix.runtime_matrix_cid
        if source_index_cid is None
        else _cid(source_index_cid, "source_index_cid")
    )
    body = {
        "schema": G234_RUNTIME_GATE_RECEIPT_SCHEMA,
        "gate_id": gate_id,
        "source_index_cid": bound_source_index_cid,
        "candidate_variant_ids": list(candidates),
        "input_receipt_cids": sorted(
            item.receipt_cid for item in evidence
        ),
        "status": status,
        "complete": complete,
        "passed": passed,
        "failure_codes": list(failures),
        "evidence": _plain(gate_evidence),
    }
    return {**body, "receipt_cid": cid_for_dag_json(body)}


def _g230_receipt_replay_assessment_receipt(
    *,
    matrix: G210RuntimeReceiptMatrixV2,
    candidates: tuple[str, ...],
    evidence: Sequence[CausalRuntimeEvidenceV2],
    failure_codes: Sequence[str],
    assessment_evidence: Mapping[str, object],
) -> dict[str, object]:
    """Build the explicitly incomplete receipt-only G230 assessment."""

    failures = tuple(sorted(set(failure_codes)))
    if not failures:
        raise RevisedPilotAuthorizationError(
            "incomplete G230 replay assessment requires failure codes"
        )
    body = {
        "schema": G230_RECEIPT_REPLAY_ASSESSMENT_SCHEMA,
        "gate_id": "replay",
        "source_index_cid": matrix.runtime_matrix_cid,
        "candidate_variant_ids": list(candidates),
        "input_receipt_cids": sorted(
            item.receipt_cid for item in evidence
        ),
        "status": "incomplete",
        "complete": False,
        "passed": False,
        "failure_codes": list(failures),
        "evidence": _plain(assessment_evidence),
    }
    return {**body, "receipt_cid": cid_for_dag_json(body)}


def _case_result_cid(result: CaseResultRecord) -> str:
    return cid_for_dag_json(_plain(result.to_dict()))


def _paired_efficacy_pair(
    *,
    source_index_cid: str,
    manifest: CausalRescueManifestV2,
    rescue_case: CausalRescueCaseV2,
    candidate_variant_id: str,
    cache_mode: str,
    baseline: CausalRuntimeEvidenceV2 | None,
    candidate: CausalRuntimeEvidenceV2 | None,
) -> dict[str, object]:
    case_id = rescue_case.case_id
    source_cid = rescue_case.source_cid
    expected_context_cid = cid_for_dag_json(
        _plain(rescue_case.proof_context)
    )
    baseline_result = None if baseline is None else baseline.case_result
    candidate_result = None if candidate is None else candidate.case_result
    missing_reasons: list[str] = []
    if baseline is None:
        missing_reasons.append("baseline_runtime_receipt_missing")
    if candidate is None:
        missing_reasons.append("candidate_runtime_receipt_missing")

    identity_valid = baseline is not None and candidate is not None
    if baseline is not None and candidate is not None:
        identity_valid = (
            baseline_result is not None
            and candidate_result is not None
            and baseline_result.variant_id == "A0"
            and candidate_result.variant_id == candidate_variant_id
            and baseline_result.run_id == candidate_result.run_id
            and baseline_result.protocol_sha256
            == candidate_result.protocol_sha256
            and baseline_result.case_id == candidate_result.case_id == case_id
            and baseline_result.split.value
            == candidate_result.split.value
            == rescue_case.split.value
            and baseline_result.cache_mode.value
            == candidate_result.cache_mode.value
            == cache_mode
            and baseline_result.case_manifest_sha256
            == candidate_result.case_manifest_sha256
            == manifest.case_manifest_sha256
            and baseline.compiler_exposure.source_cid
            == candidate.compiler_exposure.source_cid
            == source_cid
            and baseline.proof_context_cid
            == candidate.proof_context_cid
            == expected_context_cid
            and baseline.compiler_exposure.receipt_cid
            == candidate.compiler_exposure.receipt_cid
        )
        if not identity_valid:
            missing_reasons.append("pair_identity_mismatch")

    baseline_status = (
        None if baseline_result is None else baseline_result.status
    )
    candidate_status = (
        None if candidate_result is None else candidate_result.status
    )
    statuses_measured = (
        baseline_status in _MEASURED_EFFICACY_STATUSES
        and candidate_status in _MEASURED_EFFICACY_STATUSES
    )
    if (
        baseline_status is not None
        and baseline_status not in _MEASURED_EFFICACY_STATUSES
    ):
        missing_reasons.append(
            f"baseline_status_not_measured:{baseline_status.value}"
        )
    if (
        candidate_status is not None
        and candidate_status not in _MEASURED_EFFICACY_STATUSES
    ):
        missing_reasons.append(
            f"candidate_status_not_measured:{candidate_status.value}"
        )
    measured = identity_valid and statuses_measured
    baseline_value = (
        int(baseline_status is OutcomeStatus.VERIFIED)
        if measured
        else None
    )
    candidate_value = (
        int(candidate_status is OutcomeStatus.VERIFIED)
        if measured
        else None
    )
    body = {
        "schema": G234_PAIRED_EFFICACY_PAIR_SCHEMA,
        "source_index_cid": source_index_cid,
        "baseline_variant_id": "A0",
        "candidate_variant_id": candidate_variant_id,
        "split": rescue_case.split.value,
        "cache_mode": cache_mode,
        "case_id": case_id,
        "rescue_manifest_cid": manifest.manifest_cid,
        "case_manifest_sha256": manifest.case_manifest_sha256,
        "source_cid": source_cid,
        "proof_context_cid": expected_context_cid,
        "baseline_runtime_receipt_cid": (
            None if baseline is None else baseline.receipt_cid
        ),
        "candidate_runtime_receipt_cid": (
            None if candidate is None else candidate.receipt_cid
        ),
        "baseline_case_result_cid": (
            None
            if baseline_result is None
            else _case_result_cid(baseline_result)
        ),
        "candidate_case_result_cid": (
            None
            if candidate_result is None
            else _case_result_cid(candidate_result)
        ),
        "baseline_compiler_reference_exposure_cid": (
            None
            if baseline is None
            else baseline.compiler_exposure.receipt_cid
        ),
        "candidate_compiler_reference_exposure_cid": (
            None
            if candidate is None
            else candidate.compiler_exposure.receipt_cid
        ),
        "baseline_status": (
            None if baseline_status is None else baseline_status.value
        ),
        "candidate_status": (
            None if candidate_status is None else candidate_status.value
        ),
        "baseline_value": baseline_value,
        "candidate_value": candidate_value,
        "identity_valid": identity_valid,
        "measured": measured,
        "missing_reasons": sorted(set(missing_reasons)),
    }
    return {**body, "pair_cid": cid_for_dag_json(body)}


def _paired_efficacy_comparison(
    *,
    source_index_cid: str,
    manifest: CausalRescueManifestV2,
    candidate_variant_id: str,
    cache_mode: str,
    evidence_by_coordinate: Mapping[
        tuple[str, str, str, str], CausalRuntimeEvidenceV2
    ],
) -> dict[str, object]:
    split = _manifest_split(manifest)
    pairs = [
        _paired_efficacy_pair(
            source_index_cid=source_index_cid,
            manifest=manifest,
            rescue_case=rescue_case,
            candidate_variant_id=candidate_variant_id,
            cache_mode=cache_mode,
            baseline=evidence_by_coordinate.get(
                (split, "A0", cache_mode, rescue_case.case_id)
            ),
            candidate=evidence_by_coordinate.get(
                (
                    split,
                    candidate_variant_id,
                    cache_mode,
                    rescue_case.case_id,
                )
            ),
        )
        for rescue_case in manifest.cases
    ]
    measured = [pair for pair in pairs if pair["measured"] is True]
    candidate_only = [
        str(pair["case_id"])
        for pair in measured
        if pair["baseline_value"] == 0 and pair["candidate_value"] == 1
    ]
    baseline_only = [
        str(pair["case_id"])
        for pair in measured
        if pair["baseline_value"] == 1 and pair["candidate_value"] == 0
    ]
    both = [
        str(pair["case_id"])
        for pair in measured
        if pair["baseline_value"] == pair["candidate_value"] == 1
    ]
    neither = [
        str(pair["case_id"])
        for pair in measured
        if pair["baseline_value"] == pair["candidate_value"] == 0
    ]
    net = len(candidate_only) - len(baseline_only)
    body = {
        "schema": G234_PAIRED_EFFICACY_COMPARISON_SCHEMA,
        "source_index_cid": source_index_cid,
        "baseline_variant_id": "A0",
        "candidate_variant_id": candidate_variant_id,
        "baseline_variant_profile_cid": cid_for_dag_json(
            _plain(VARIANT_REGISTRY["A0"].to_dict())
        ),
        "candidate_variant_profile_cid": cid_for_dag_json(
            _plain(VARIANT_REGISTRY[candidate_variant_id].to_dict())
        ),
        "paired_against": VARIANT_REGISTRY[
            candidate_variant_id
        ].paired_against,
        "split": split,
        "cache_mode": cache_mode,
        "rescue_manifest_cid": manifest.manifest_cid,
        "scheduled_pair_count": len(pairs),
        "measured_pair_count": len(measured),
        "missing_pair_count": len(pairs) - len(measured),
        "identity_mismatch_count": sum(
            pair["identity_valid"] is False
            and pair["baseline_runtime_receipt_cid"] is not None
            and pair["candidate_runtime_receipt_cid"] is not None
            for pair in pairs
        ),
        "baseline_verified_count": sum(
            pair["baseline_value"] == 1 for pair in measured
        ),
        "candidate_verified_count": sum(
            pair["candidate_value"] == 1 for pair in measured
        ),
        "candidate_only_verified_count": len(candidate_only),
        "baseline_only_verified_count": len(baseline_only),
        "concordant_verified_count": len(both),
        "concordant_nonverified_count": len(neither),
        "net_verified_gain_count": net,
        "net_verified_delta": (
            None
            if len(measured) != len(pairs)
            else net / len(measured)
        ),
        "candidate_only_verified_case_ids": candidate_only,
        "baseline_only_verified_case_ids": baseline_only,
        "concordant_verified_case_ids": both,
        "concordant_nonverified_case_ids": neither,
        "pair_cids": [str(pair["pair_cid"]) for pair in pairs],
        "pairs": pairs,
    }
    return {**body, "comparison_cid": cid_for_dag_json(body)}


def build_g234_efficacy_gate_v2(
    matrix: G210RuntimeReceiptMatrixV2,
    candidate_variant_ids: Sequence[str],
) -> Mapping[str, object]:
    """Recompute complete A0-paired kernel efficacy from runtime receipts.

    This gate establishes source-bound measurement availability, not a
    favorable performance threshold.  Measured logical failures remain real
    zeroes, while capability and infrastructure missingness remain null.
    """

    candidates, evidence = _scoped_runtime_evidence(
        matrix, candidate_variant_ids
    )
    source_index_cid = matrix.runtime_matrix_cid
    evidence_by_coordinate = {
        _runtime_coordinate(item): item for item in evidence
    }
    comparisons = [
        _paired_efficacy_comparison(
            source_index_cid=source_index_cid,
            manifest=manifest,
            candidate_variant_id=candidate,
            cache_mode=cache_mode,
            evidence_by_coordinate=evidence_by_coordinate,
        )
        for candidate in candidates
        for manifest in matrix.receipt_matrix.rescue_manifests
        for cache_mode in G210_CACHE_MODES
    ]
    expected_comparison_count = (
        len(candidates) * len(G210_SPLITS) * len(G210_CACHE_MODES)
    )
    scheduled_pair_count = sum(
        int(item["scheduled_pair_count"]) for item in comparisons
    )
    measured_pair_count = sum(
        int(item["measured_pair_count"]) for item in comparisons
    )
    missing_pair_count = sum(
        int(item["missing_pair_count"]) for item in comparisons
    )
    identity_mismatch_count = sum(
        int(item["identity_mismatch_count"]) for item in comparisons
    )
    missing_coordinate_count = sum(
        pair["baseline_runtime_receipt_cid"] is None
        or pair["candidate_runtime_receipt_cid"] is None
        for comparison in comparisons
        for pair in comparison["pairs"]  # type: ignore[union-attr]
    )

    failures: list[str] = []
    if not matrix.complete:
        failures.append("source_runtime_matrix_incomplete")
    if (
        len(comparisons) != expected_comparison_count
        or missing_coordinate_count
    ):
        failures.append("paired_efficacy_population_incomplete")
    if identity_mismatch_count:
        failures.append("paired_efficacy_identity_mismatch")
    if missing_pair_count:
        failures.append("paired_efficacy_outcomes_missing")
    incomplete_failures = {
        "source_runtime_matrix_incomplete",
        "paired_efficacy_population_incomplete",
        "paired_efficacy_outcomes_missing",
    }
    status = (
        "incomplete"
        if incomplete_failures.intersection(failures)
        else ("failed" if failures else "passed")
    )
    gate = _g234_runtime_gate_receipt(
        gate_id="efficacy",
        matrix=matrix,
        candidates=candidates,
        evidence=evidence,
        status=status,
        failure_codes=failures,
        source_index_cid=source_index_cid,
        gate_evidence={
            "expected_comparison_count": expected_comparison_count,
            "comparison_count": len(comparisons),
            "scheduled_pair_count": scheduled_pair_count,
            "measured_pair_count": measured_pair_count,
            "missing_pair_count": missing_pair_count,
            "missing_coordinate_count": missing_coordinate_count,
            "identity_mismatch_count": identity_mismatch_count,
            "comparisons": comparisons,
            "source_recomputed": True,
            "missing_is_never_zero": True,
            "split_cache_results_separate": True,
            "performance_threshold_applied": False,
        },
    )
    return _freeze_json(gate)  # type: ignore[return-value]


def validate_g234_efficacy_gate_v2(
    value: object,
    matrix: G210RuntimeReceiptMatrixV2,
) -> Mapping[str, object]:
    """Rebuild a G234 efficacy gate from its full runtime source matrix."""

    data = _mapping(value, "G234 efficacy gate")
    candidates = _array(
        data.get("candidate_variant_ids"),
        "candidate_variant_ids",
    )
    rebuilt = build_g234_efficacy_gate_v2(
        matrix, tuple(str(item) for item in candidates)
    )
    if _plain(data) != _plain(rebuilt):
        raise RevisedPilotAuthorizationError(
            "G234 efficacy gate did not source-recompute"
        )
    return rebuilt


def build_g234_reliability_gate_v2(
    matrix: G210RuntimeReceiptMatrixV2,
    candidate_variant_ids: Sequence[str],
) -> Mapping[str, object]:
    """Recompute terminal and typed-failure reliability from full receipts."""

    candidates, evidence = _scoped_runtime_evidence(
        matrix, candidate_variant_ids
    )
    statuses = {status.value: 0 for status in OutcomeStatus}
    typed_failures: dict[str, int] = {}
    recovered_failures: dict[str, int] = {}
    retries = 0
    for item in evidence:
        result = item.case_result
        statuses[result.status.value] += 1
        if result.failure_code is not None:
            code = result.failure_code.value
            typed_failures[code] = typed_failures.get(code, 0) + 1
        for code in result.recovered_failure_codes:
            recovered_failures[code.value] = (
                recovered_failures.get(code.value, 0) + 1
            )
        retries += sum(stage.telemetry.retries for stage in result.stages)

    failures: list[str] = []
    if not matrix.complete:
        failures.append("source_runtime_matrix_incomplete")
    if statuses[OutcomeStatus.INFRASTRUCTURE_FAILURE.value]:
        failures.append("infrastructure_failures_present")
    if (
        statuses[OutcomeStatus.UNAVAILABLE.value]
        or statuses[OutcomeStatus.EXCLUDED.value]
    ):
        failures.append("excluded_or_unavailable_results_present")
    status = (
        "incomplete"
        if "source_runtime_matrix_incomplete" in failures
        else ("failed" if failures else "passed")
    )
    gate = _g234_runtime_gate_receipt(
        gate_id="reliability",
        matrix=matrix,
        candidates=candidates,
        evidence=evidence,
        status=status,
        failure_codes=failures,
        gate_evidence={
            "terminal_receipt_count": len(evidence),
            "status_counts": statuses,
            "typed_terminal_failure_counts": dict(
                sorted(typed_failures.items())
            ),
            "recovered_failure_counts": dict(
                sorted(recovered_failures.items())
            ),
            "retry_count": retries,
            "infrastructure_or_exclusion_count": (
                statuses[OutcomeStatus.INFRASTRUCTURE_FAILURE.value]
                + statuses[OutcomeStatus.UNAVAILABLE.value]
                + statuses[OutcomeStatus.EXCLUDED.value]
            ),
            "source_recomputed": True,
        },
    )
    return _freeze_json(gate)  # type: ignore[return-value]


def validate_g234_reliability_gate_v2(
    value: object,
    matrix: G210RuntimeReceiptMatrixV2,
) -> Mapping[str, object]:
    data = _mapping(value, "G234 reliability gate")
    candidates = _array(
        data.get("candidate_variant_ids"),
        "candidate_variant_ids",
    )
    rebuilt = build_g234_reliability_gate_v2(
        matrix, tuple(str(item) for item in candidates)
    )
    if _plain(data) != _plain(rebuilt):
        raise RevisedPilotAuthorizationError(
            "G234 reliability gate did not source-recompute"
        )
    return rebuilt


def build_g234_routing_gate_v2(
    matrix: G210RuntimeReceiptMatrixV2,
    candidate_variant_ids: Sequence[str],
) -> Mapping[str, object]:
    """Recompute optional-route denominators and substitution checks."""

    candidates, evidence = _scoped_runtime_evidence(
        matrix, candidate_variant_ids
    )
    counters = {
        source: {
            "scheduled": 0,
            "eligible": 0,
            "invoked": 0,
            "suppressed": 0,
            "kernel_checked": 0,
            "accepted": 0,
            "causal_rescue": 0,
            "overlap": 0,
            "unnecessary": 0,
        }
        for source in ("hammer", "leanstral")
    }
    route_violation_cids: list[str] = []
    for runtime in evidence:
        result = runtime.case_result
        expected = tuple(
            stage.value
            for stage in get_causal_proof_variant_profile(
                result.variant_id
            ).optional_order
        )
        selection = _mapping(
            runtime.selection_result.receipt,
            "causal selection receipt",
        )
        raw_candidates = selection.get("optional_candidates")
        raw_measurements = runtime.causal_case_receipt.get(
            "component_measurements"
        )
        if (
            not isinstance(raw_candidates, (list, tuple))
            or not isinstance(raw_measurements, (list, tuple))
        ):
            route_violation_cids.append(runtime.receipt_cid)
            continue
        optional = tuple(
            _mapping(item, "optional candidate")
            for item in raw_candidates
        )
        actual = tuple(str(item.get("source")) for item in optional)
        measurement_rows = tuple(
            _mapping(raw, "component measurement")
            for raw in raw_measurements
        )
        measurement_ids = tuple(
            str(item.get("component_id")) for item in measurement_rows
        )
        measurements = {
            component_id: item
            for component_id, item in zip(
                measurement_ids, measurement_rows, strict=True
            )
            if component_id in counters
        }
        unexpected_measurements = (
            set(measurement_ids) - set(expected) - {"compiler"}
        )
        duplicate_optional_measurements = any(
            measurement_ids.count(component_id) != 1
            for component_id in expected
        )
        if (
            actual != expected
            or set(measurements) != set(expected)
            or unexpected_measurements
            or duplicate_optional_measurements
        ):
            route_violation_cids.append(runtime.receipt_cid)
        for candidate in optional:
            source = str(candidate.get("source"))
            if source not in counters:
                route_violation_cids.append(runtime.receipt_cid)
                continue
            measurement = measurements.get(source, {})
            count = counters[source]
            count["scheduled"] += 1
            count["eligible"] += int(
                candidate.get("trigger_eligible") is True
            )
            count["invoked"] += int(candidate.get("invoked") is True)
            count["suppressed"] += int(candidate.get("invoked") is False)
            count["kernel_checked"] += int(
                measurement.get("kernel_checks") == 1
            )
            count["accepted"] += int(candidate.get("accepted") is True)
            count["causal_rescue"] += int(
                candidate.get("causal_rescue") is True
            )
            count["overlap"] += int(candidate.get("overlap") is True)
            count["unnecessary"] += int(
                measurement.get("unnecessary_work") is True
            )

    failures: list[str] = []
    if not matrix.complete:
        failures.append("source_runtime_matrix_incomplete")
    if route_violation_cids:
        failures.append("route_or_measurement_substitution")
    if "runtime_unequal_compiler_exposure" in matrix.validation_issues:
        failures.append("unequal_compiler_reference_exposure")
    status = (
        "incomplete"
        if "source_runtime_matrix_incomplete" in failures
        else ("failed" if failures else "passed")
    )
    gate = _g234_runtime_gate_receipt(
        gate_id="routing",
        matrix=matrix,
        candidates=candidates,
        evidence=evidence,
        status=status,
        failure_codes=failures,
        gate_evidence={
            "component_counts": counters,
            "route_violation_receipt_cids": sorted(
                set(route_violation_cids)
            ),
            "fallback_or_substitution_count": len(
                set(route_violation_cids)
            ),
            "compiler_exposure_equal": (
                "runtime_unequal_compiler_exposure"
                not in matrix.validation_issues
            ),
            "source_recomputed": True,
        },
    )
    return _freeze_json(gate)  # type: ignore[return-value]


def validate_g234_routing_gate_v2(
    value: object,
    matrix: G210RuntimeReceiptMatrixV2,
) -> Mapping[str, object]:
    data = _mapping(value, "G234 routing gate")
    candidates = _array(
        data.get("candidate_variant_ids"),
        "candidate_variant_ids",
    )
    rebuilt = build_g234_routing_gate_v2(
        matrix, tuple(str(item) for item in candidates)
    )
    if _plain(data) != _plain(rebuilt):
        raise RevisedPilotAuthorizationError(
            "G234 routing gate did not source-recompute"
        )
    return rebuilt


def build_g230_receipt_replay_assessment_v2(
    matrix: G210RuntimeReceiptMatrixV2,
    candidate_variant_ids: Sequence[str],
) -> Mapping[str, object]:
    """Prove receipt replay while explicitly withholding detached replay."""

    candidates, evidence = _scoped_runtime_evidence(
        matrix, candidate_variant_ids
    )
    rebuilt_cids = [
        validate_causal_runtime_evidence_v2(item.to_dict()).receipt_cid
        for item in evidence
    ]
    failures = ["detached_execution_replay_unavailable"]
    if not matrix.complete:
        failures.append("source_runtime_matrix_incomplete")
    gate = _g230_receipt_replay_assessment_receipt(
        matrix=matrix,
        candidates=candidates,
        evidence=evidence,
        failure_codes=failures,
        assessment_evidence={
            "receipt_replay_complete": (
                matrix.complete
                and rebuilt_cids
                == [item.receipt_cid for item in evidence]
            ),
            "receipt_replay_count": len(rebuilt_cids),
            "rebuilt_receipt_cids": rebuilt_cids,
            "detached_execution_replay_complete": False,
            "detached_execution_receipt_cids": [],
            "source_recomputed": True,
        },
    )
    return _freeze_json(gate)  # type: ignore[return-value]


def validate_g230_receipt_replay_assessment_v2(
    value: object,
    matrix: G210RuntimeReceiptMatrixV2,
) -> Mapping[str, object]:
    data = _mapping(value, "G230 receipt replay assessment")
    candidates = _array(
        data.get("candidate_variant_ids"),
        "candidate_variant_ids",
    )
    rebuilt = build_g230_receipt_replay_assessment_v2(
        matrix, tuple(str(item) for item in candidates)
    )
    if _plain(data) != _plain(rebuilt):
        raise RevisedPilotAuthorizationError(
            "G230 receipt replay assessment did not source-recompute"
        )
    return rebuilt


@dataclass(frozen=True, slots=True)
class G230RevisedPilotDecision:
    """Persistable, currently negative-only G230 readiness artifact."""

    schema: str
    goal_id: str
    source_commit: str | None
    dependency_cids: Mapping[str, str | None]
    gate_receipt_cids: Mapping[str, str | None]
    requested_candidate_ids: tuple[str, ...]
    failures: tuple[str, ...]
    artifact_cid: str | None = None

    def __post_init__(self) -> None:
        if (
            self.schema != G230_REVISED_PILOT_DECISION_SCHEMA
            or self.goal_id != "HSSL-G230"
        ):
            raise RevisedPilotAuthorizationError(
                "unsupported revised-pilot decision identity"
            )
        if self.source_commit is not None:
            _commit(self.source_commit)
        dependencies = _mapping(self.dependency_cids, "dependency_cids")
        if set(dependencies) != set(G230_DEPENDENCY_KEYS):
            raise RevisedPilotAuthorizationError(
                "decision dependency identity set changed"
            )
        object.__setattr__(
            self,
            "dependency_cids",
            MappingProxyType(
                {
                    key: (
                        None
                        if dependencies[key] is None
                        else _cid(
                            dependencies[key],
                            f"dependency_cids.{key}",
                        )
                    )
                    for key in G230_DEPENDENCY_KEYS
                }
            ),
        )
        gates = _mapping(self.gate_receipt_cids, "gate_receipt_cids")
        if set(gates) != set(G230_GATE_IDS) or any(
            value is not None for value in gates.values()
        ):
            raise RevisedPilotAuthorizationError(
                "unvalidated G230 gate receipts cannot enter a decision"
            )
        object.__setattr__(
            self,
            "gate_receipt_cids",
            MappingProxyType({key: None for key in G230_GATE_IDS}),
        )
        requested = tuple(self.requested_candidate_ids)
        if requested:
            requested = _candidate_ids(requested, "requested_candidate_ids")
        object.__setattr__(self, "requested_candidate_ids", requested)
        failures = tuple(sorted(set(self.failures)))
        if not failures or any(
            not isinstance(item, str) or not item
            for item in failures
        ):
            raise RevisedPilotAuthorizationError(
                "negative G230 decision requires stable failure codes"
            )
        if "source_recomputed_gate_validator_unavailable" not in failures:
            raise RevisedPilotAuthorizationError(
                "this revision cannot represent a positive G230 decision"
            )
        object.__setattr__(self, "failures", failures)
        expected = cid_for_dag_json(self.identity_payload())
        if self.artifact_cid is None:
            object.__setattr__(self, "artifact_cid", expected)
        elif _cid(self.artifact_cid, "artifact_cid") != expected:
            raise RevisedPilotAuthorizationError(
                "G230 decision artifact CID does not match its body"
            )

    @property
    def complete(self) -> bool:
        return False

    @property
    def passed(self) -> bool:
        return False

    @property
    def selected_candidate_ids(self) -> tuple[str, ...]:
        return ()

    @property
    def holdout_authorized(self) -> bool:
        return False

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "goal_id": self.goal_id,
            "evidence": "HSSLEV2309D46",
            "evidence_statement": HSSLEV2309D46(),
            "source_commit": self.source_commit,
            "dependency_cids": dict(self.dependency_cids),
            "gate_receipt_cids": dict(self.gate_receipt_cids),
            "requested_candidate_ids": list(self.requested_candidate_ids),
            "selected_candidate_ids": [],
            "authorized_variant_ids": [],
            "cache_modes": list(G210_CACHE_MODES),
            "failures": list(self.failures),
            "complete": False,
            "passed": False,
            "shortlist_frozen": True,
            "holdout_authorized": False,
            "holdout_outcomes_inspected": False,
            "production_promotion_authorized": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "artifact_cid": self.artifact_cid}


@dataclass(frozen=True, slots=True)
class G230AuthorizationResult:
    """Negative readiness decision; authorization is structurally absent."""

    decision: G230RevisedPilotDecision
    authorization: G232ReplacementHoldoutAuthorization | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.decision, G230RevisedPilotDecision):
            raise RevisedPilotAuthorizationError(
                "authorization result requires a G230 decision"
            )
        if self.authorization is not None:
            raise RevisedPilotAuthorizationError(
                "authorization construction is disabled until every "
                "revision-2 gate has a source recomputation validator"
            )

    @property
    def authorization_cid(self) -> None:
        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision.to_dict(),
            "authorization": None,
        }


def evaluate_revised_pilot_authorization(
    *,
    semantic_calibration_artifact: object | None,
    causal_receipt_matrix: G210ReceiptMatrix | Mapping[str, object] | None,
    replacement_holdout_seal: ReplacementHoldoutSeal
    | Mapping[str, object]
    | None,
    source_freeze_receipt: G230SourceFreezeReceipt
    | Mapping[str, object]
    | None,
    execution_identities: G230ExecutionIdentities
    | Mapping[str, object]
    | None,
    gate_receipts: Mapping[str, object] | None,
    candidate_variant_ids: Sequence[str],
) -> G230AuthorizationResult:
    """Recompute public readiness evidence and always fail closed for now.

    ``gate_receipts`` is intentionally not trusted.  It remains in the API so
    callers can discover that their legacy/self-asserted gate artifacts are
    insufficient, but no CID from it enters the decision.  A future positive
    implementation must replace this boundary with concrete source validators
    for all :data:`G230_GATE_IDS`; removing the stable unavailable reason will
    then require changing the decision type and tests explicitly.
    """

    failures: set[str] = {
        "semantic_source_revalidation_capability_unavailable",
        "source_recomputed_gate_validator_unavailable",
    }
    dependencies: dict[str, str | None] = {
        key: None for key in G230_DEPENDENCY_KEYS
    }
    dependencies["semantic_protocol"] = SEMANTIC_PROTOCOL_V2_CID
    dependencies["causal_protocol"] = CAUSAL_PROOF_PROTOCOL_V2_CID
    dependencies["causal_variant_profile"] = (
        CAUSAL_PROOF_VARIANT_PROFILE_V2_CID
    )

    try:
        requested = _candidate_ids(
            candidate_variant_ids, "candidate_variant_ids"
        )
    except (RevisedPilotAuthorizationError, TypeError, ValueError):
        requested = ()
        failures.add("invalid_shortlist")

    semantic_cid: str | None = None
    try:
        semantic_cid = _validate_semantic_calibration_reference(
            semantic_calibration_artifact
        )
        dependencies["semantic_calibration"] = semantic_cid
    except (TypeError, ValueError, KeyError):
        failures.add("invalid_g200_semantic_calibration")

    matrix: G210ReceiptMatrix | None = None
    try:
        matrix = G210ReceiptMatrix.from_dict(
            causal_receipt_matrix.to_dict()
            if isinstance(causal_receipt_matrix, G210ReceiptMatrix)
            else causal_receipt_matrix
        )
        dependencies["causal_rescue_manifest_set"] = (
            matrix.rescue_manifest_set_cid
        )
        dependencies["causal_receipt_matrix"] = matrix.matrix_cid
        if semantic_cid is None or (
            matrix.semantic_calibration_artifact_cid != semantic_cid
        ):
            failures.add("causal_semantic_calibration_mismatch")
        if not matrix.complete:
            failures.add("g210_receipt_matrix_incomplete")
            failures.update(
                f"g210:{item}" for item in matrix.validation_issues
            )
    except (RevisedPilotAuthorizationError, TypeError, ValueError, KeyError):
        failures.add("invalid_g210_causal_receipt_matrix")

    seal: ReplacementHoldoutSeal | None = None
    try:
        seal = ReplacementHoldoutSeal.from_dict(
            replacement_holdout_seal.to_dict()
            if isinstance(
                replacement_holdout_seal, ReplacementHoldoutSeal
            )
            else replacement_holdout_seal
        )
        dependencies["replacement_holdout_seal"] = seal.seal_contract_cid
        if (
            seal.protocol_cids["semantic"] != SEMANTIC_PROTOCOL_V2_CID
            or seal.protocol_cids["causal_proof"]
            != CAUSAL_PROOF_PROTOCOL_V2_CID
        ):
            failures.add("replacement_seal_protocol_mismatch")
    except (TypeError, ValueError, KeyError):
        failures.add("invalid_replacement_holdout_seal")

    source: G230SourceFreezeReceipt | None = None
    try:
        source = G230SourceFreezeReceipt.from_dict(
            source_freeze_receipt.to_dict()
            if isinstance(source_freeze_receipt, G230SourceFreezeReceipt)
            else source_freeze_receipt
        )
        dependencies["source_freeze"] = source.receipt_cid
        if not source.ready:
            failures.add("source_not_detached_clean")
    except (RevisedPilotAuthorizationError, TypeError, ValueError, KeyError):
        failures.add("invalid_source_freeze")

    identities: G230ExecutionIdentities | None = None
    try:
        identities = G230ExecutionIdentities.from_dict(
            execution_identities.to_dict()
            if isinstance(execution_identities, G230ExecutionIdentities)
            else execution_identities
        )
        dependencies["execution_identities"] = identities.bundle_cid
        if identities.frozen is not True:
            failures.add("execution_identities_not_frozen")
    except (RevisedPilotAuthorizationError, TypeError, ValueError, KeyError):
        failures.add("invalid_execution_identities")

    source_commit = None if source is None else source.source_commit
    if source is not None and identities is not None and (
        identities.source_commit != source.source_commit
        or identities.source_freeze_receipt_cid != source.receipt_cid
    ):
        failures.add("execution_source_commit_mismatch")
    if matrix is not None and identities is not None:
        environments = {
            profile.environment_sha256
            for profile in matrix.execution_profiles
        }
        if (
            len(environments) != 1
            or identities.legacy_environment_sha256
            not in environments
        ):
            failures.add("execution_environment_mismatch")
    if (
        identities is not None
        and semantic_cid is not None
        and matrix is not None
        and seal is not None
    ):
        expected_artifacts = {
            "semantic_calibration": semantic_cid,
            "causal_receipt_matrix": matrix.matrix_cid,
            "replacement_holdout_seal": seal.seal_contract_cid,
        }
        if dict(identities.bound_artifact_cids) != expected_artifacts:
            failures.add("source_artifact_binding_mismatch")

    if gate_receipts is not None:
        try:
            supplied_gates = _mapping(gate_receipts, "gate_receipts")
        except RevisedPilotAuthorizationError:
            failures.add("invalid_gate_receipt_set")
        else:
            if supplied_gates:
                failures.add("unvalidated_gate_receipts_ignored")

    decision = G230RevisedPilotDecision(
        schema=G230_REVISED_PILOT_DECISION_SCHEMA,
        goal_id="HSSL-G230",
        source_commit=source_commit,
        dependency_cids=dependencies,
        gate_receipt_cids={key: None for key in G230_GATE_IDS},
        requested_candidate_ids=requested,
        failures=tuple(failures),
    )
    return G230AuthorizationResult(decision=decision)


__all__ = [
    "G210_CACHE_MODES",
    "G210_RECEIPT_MATRIX_SCHEMA",
    "G210_RUNTIME_RECEIPT_MATRIX_SCHEMA",
    "G210_SPLITS",
    "G210_VARIANT_IDS",
    "G210ReceiptMatrix",
    "G210RuntimeReceiptMatrixV2",
    "G230AuthorizationResult",
    "G230_BOUND_ARTIFACT_KEYS",
    "G230_EXECUTION_IDENTITIES_SCHEMA",
    "G230_GATE_IDS",
    "G230_IDENTITY_KEYS",
    "G230_RECEIPT_REPLAY_ASSESSMENT_SCHEMA",
    "G230_REVISED_PILOT_DECISION_SCHEMA",
    "G230_SOURCE_FREEZE_SCHEMA",
    "G234_GATE_IDS",
    "G234_PAIRED_EFFICACY_COMPARISON_SCHEMA",
    "G234_PAIRED_EFFICACY_PAIR_SCHEMA",
    "G234_RUNTIME_GATE_RECEIPT_SCHEMA",
    "G230ExecutionIdentities",
    "G230RevisedPilotDecision",
    "G230SourceFreezeReceipt",
    "HSSLEV2309D46",
    "HSSLEV2343B16",
    "RevisedPilotAuthorizationError",
    "build_g210_runtime_receipt_matrix_v2",
    "build_g230_receipt_replay_assessment_v2",
    "build_g234_efficacy_gate_v2",
    "build_g234_reliability_gate_v2",
    "build_g234_routing_gate_v2",
    "evaluate_revised_pilot_authorization",
    "validate_g230_receipt_replay_assessment_v2",
    "validate_g234_efficacy_gate_v2",
    "validate_g234_reliability_gate_v2",
    "validate_g234_routing_gate_v2",
]
