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
The in-process source-revalidated G200 calibration capability is likewise not
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
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Mapping, Sequence, Self

from .cases import ReplacementHoldoutSeal
from .causal_ablation import (
    CausalExecutionProfileV2,
    CausalRescueManifestV2,
)
from .content_addressing import cid_for_dag_json, validate_cid
from .contracts import (
    CAUSAL_PROOF_PROTOCOL_V2_CID,
    CAUSAL_PROOF_VARIANT_PROFILE_V2_CID,
    SEMANTIC_PROTOCOL_V2_CID,
)
from .metrics import validate_causal_rescue_aggregate
from .variants import VARIANT_REGISTRY

if TYPE_CHECKING:
    from .holdout_execution import G230ReplacementHoldoutAuthorization


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
        "source-recomputed G200, G210, and G220 evidence with complete "
        "pilot/development gates and fail-closed replacement authorization"
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
                if (
                    environment is None
                    or case_result.get("environment_sha256") != environment
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
    authorization: G230ReplacementHoldoutAuthorization | None = None

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
    "G210_SPLITS",
    "G210_VARIANT_IDS",
    "G210ReceiptMatrix",
    "G230AuthorizationResult",
    "G230_BOUND_ARTIFACT_KEYS",
    "G230_EXECUTION_IDENTITIES_SCHEMA",
    "G230_GATE_IDS",
    "G230_IDENTITY_KEYS",
    "G230_REVISED_PILOT_DECISION_SCHEMA",
    "G230_SOURCE_FREEZE_SCHEMA",
    "G230ExecutionIdentities",
    "G230RevisedPilotDecision",
    "G230SourceFreezeReceipt",
    "HSSLEV2309D46",
    "RevisedPilotAuthorizationError",
    "evaluate_revised_pilot_authorization",
]
