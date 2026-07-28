"""Prover-gated Codex packet contract for plateau-break supervisor work.

Interface: ``PlateauCodexPacket@1``

Teachers (spaCy, autoencoder, Leanstral) and residual forensics produce
proposals.  Hammer/cvc5/Lean structural admission gates those proposals.
Only **accepted** admissions may mark a packet ``implementable=true`` for
agent-supervisor deterministic compiler/decompiler edits.

Fail-closed rules (normative):

* disposition ``validator_reject`` / ``timeout`` / ``error`` →
  ``implementable=false`` (edit authority denied);
* prover receipts always carry ``semantic_authority=false`` — a proof pass
  never lowers end-to-end semantic loss by itself;
* admitted ΔL1 is expressed only as ``CanonicalFieldChange`` records;
* packets are content-addressed via a stable SHA-256 digest of the
  canonical JSON payload (excluding the digest field itself).

Supervisor consumption (PLAT-070 materializer / PLAT2-030 repair-development):

* ``implementable=true`` → lease a task with ``predicted_files`` limited to
  deterministic compiler/realizer/tests and run ``validation_commands``;
* ``implementable=false`` → emit obligation-only notes from
  ``proof_obligation_ids``; never silent-merge.

Repair-development population (PLAT2-030): use
:func:`build_repair_dev_codex_packet` / :func:`residual_refs_from_catalog`
so packets bind baseline/tree/population/catalog CIDs, invariant context,
expansion handles, and token-budget metrics while rejecting blind residuals
and gold target bodies.  Legacy :func:`build_holdout_codex_packet` remains
for the transitional ``holdout`` catalog kind.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final

from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.semantic_roundtrip.constructors.autoencoder_guided import (
    CanonicalFieldChange,
    canonical_field_changes,
)
from benchmarks.semantic_roundtrip.contracts import (
    CanonicalRuleIR,
    ContractError,
)
from benchmarks.semantic_roundtrip.evaluation_status import (
    DEFAULT_DETERMINISTIC_BASELINE_ARM_ID,
)
from benchmarks.semantic_roundtrip.holdout_baseline import (
    PACKET_OMITTED_HANDLE_COVERAGE_REQUIRED,
    PACKET_TOKEN_BUDGET,
    PACKET_TOKEN_BUDGET_SOFT_WARN,
    PACKET_TOKEN_COUNTING_METHOD,
    packet_token_budget_definition,
)
from benchmarks.semantic_roundtrip.residual_catalog import (
    BLIND_POPULATION_KINDS,
    CATALOG_STATUS_NOT_MEASURED,
    CATALOG_STATUS_RUNTIME_FAILED,
    CATALOG_STATUS_SEMANTIC_SCORED,
    CATALOG_STATUS_UNSUPPORTED,
    NON_SEMANTIC_CATALOG_STATUSES,
    POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION,
    POPULATION_KIND_HOLDOUT,
    POPULATION_KIND_REPAIR_DEVELOPMENT,
)
from benchmarks.semantic_roundtrip.selective_repair import (
    DECLARED_STRUCTURAL_CONSTRAINTS,
    StructuralTool,
)
from benchmarks.semantic_roundtrip.structural_admission import (
    STRUCTURAL_ADMISSION_RECEIPT_INTERFACE,
    AdmissionCheckReceipt,
    AdmissionDisposition,
    StructuralAdmissionResult,
    VALIDATOR_REJECT,
)


PLATEAU_CODEX_PACKET_INTERFACE: Final = "PlateauCodexPacket@1"
PLATEAU_CODEX_PACKET_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-plateau-codex-packet.v1"
)
PLATEAU_RESIDUAL_REF_INTERFACE: Final = "PlateauResidualRef@1"
PLATEAU_TEACHER_PROPOSAL_INTERFACE: Final = "PlateauTeacherProposal@1"
PLATEAU_PROOF_OBLIGATION_INTERFACE: Final = "PlateauProofObligation@1"
PLATEAU_ADMISSION_RECEIPT_INTERFACE: Final = (
    "PlateauAdmissionReceipt@1"
)
PLATEAU_CODEX_PACKET_EVIDENCE: Final = "PLATEV020PKT"

DEFAULT_BASELINE_ARM_ID: Final = DEFAULT_DETERMINISTIC_BASELINE_ARM_ID
DEFAULT_BASELINE_E2E: Final = 0.088333333

# Closed set of teacher identities that may author proposals.
KNOWN_TEACHERS: Final = frozenset(
    {
        "leanstral",
        "symai",
        "spacy",
        "autoencoder",
        "residual_catalog",
        "manual",
        "hybrid",
    }
)

# Fail-closed dispositions that can never authorize implementable work.
NON_IMPLEMENTABLE_DISPOSITIONS: Final = frozenset(
    {
        AdmissionDisposition.VALIDATOR_REJECT,
        AdmissionDisposition.TIMEOUT,
        AdmissionDisposition.ERROR,
        AdmissionDisposition.NOT_APPLICABLE,
    }
)

# Predicted edit targets must stay inside the deterministic improvement surface.
ALLOWED_PREDICTED_FILE_PREFIXES: Final = (
    "benchmarks/semantic_roundtrip/constructors/",
    "benchmarks/semantic_roundtrip/realizers/",
    "benchmarks/semantic_roundtrip/",
    "tests/unit/benchmarks/semantic_roundtrip/",
    "docs/benchmarks/",
)

DEFAULT_PREDICTED_FILES: Final = (
    "benchmarks/semantic_roundtrip/constructors/typed_deontic.py",
    "tests/unit/benchmarks/semantic_roundtrip/",
)

DEFAULT_VALIDATION_COMMANDS: Final = (
    "PYTHONPATH=. python -m pytest "
    "tests/unit/benchmarks/semantic_roundtrip/test_structural_admission.py -q",
    "PYTHONPATH=. python -m pytest "
    "tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py -q",
)

# Post-pilot baseline (PLAT2): det. production mean e2e is 0.0 on pilots.
HOLDOUT_BASELINE_E2E: Final = 0.0
HOLDOUT_POPULATION_KIND: Final = POPULATION_KIND_HOLDOUT
REPAIR_DEV_BASELINE_E2E: Final = 0.0
REPAIR_DEV_POPULATION_KIND: Final = POPULATION_KIND_REPAIR_DEVELOPMENT
PLATEAU_PACKET_BINDINGS_INTERFACE: Final = "PlateauPacketBindings@1"
PLATEAU_INVARIANT_CONTEXT_INTERFACE: Final = "PlateauInvariantContext@1"
PLATEAU_EXPANSION_HANDLE_INTERFACE: Final = "PlateauExpansionHandle@1"
REPAIR_DEV_PACKET_CONTEXT_METRICS_INTERFACE: Final = (
    "RepairDevPacketContextMetrics@1"
)
REPAIR_DEV_PACKET_CONTEXT_METRICS_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-repair-dev-packet-context-metrics.v1"
)
PLATEAU_CODEX_PACKET_REPAIR_DEV_EVIDENCE: Final = "PLAT2EV030PKT"
DEFAULT_REPAIR_DEV_PACKET_METRICS_RELATIVE_PATH: Final = (
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "repair_dev_packet_context_metrics.json"
)

# Structural gates + packet revalidation + repair-dev/pilot metrics.
DEFAULT_REPAIR_DEV_VALIDATION_COMMANDS: Final = (
    "PYTHONPATH=. python -m pytest "
    "tests/unit/benchmarks/semantic_roundtrip/test_structural_admission.py -q",
    "PYTHONPATH=. python -m pytest "
    "tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py -q",
    "PYTHONPATH=. python -m pytest "
    "tests/unit/benchmarks/semantic_roundtrip/test_plateau_supervisor_materialize.py -q",
    "PYTHONPATH=. python -m pytest "
    "tests/unit/benchmarks/semantic_roundtrip/test_holdout_baseline.py -q",
    "PYTHONPATH=. python -m pytest "
    "tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py -q",
    "PYTHONPATH=. python -m pytest "
    "tests/unit/benchmarks/semantic_roundtrip/test_holdout_cases.py -q",
)
# Legacy alias used by transitional holdout catalog packets.
DEFAULT_HOLDOUT_VALIDATION_COMMANDS: Final = (
    "PYTHONPATH=. python -m pytest "
    "tests/unit/benchmarks/semantic_roundtrip/test_structural_admission.py -q",
    "PYTHONPATH=. python -m pytest "
    "tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py -q",
    "PYTHONPATH=. python -m pytest "
    "tests/unit/benchmarks/semantic_roundtrip/test_holdout_cases.py -q",
)

# Keys / substrings that must never appear in invariant or optional evidence.
FORBIDDEN_PACKET_CONTENT_KEYS: Final = frozenset(
    {
        "blind_gold",
        "blind_id",
        "blind_ids",
        "blind_source",
        "blind_sources",
        "full_repository",
        "full_repository_dump",
        "gold_body",
        "gold_ir",
        "gold_target",
        "gold_value",
        "raw_solver_trace",
        "raw_solver_traces",
        "repository_dump",
        "source_text",
        "untrusted_instruction",
        "untrusted_instructions",
    }
)

# Evidence statuses that deny implementable authority (fail-closed).
NON_IMPLEMENTABLE_EVIDENCE_STATUSES: Final = frozenset(
    NON_SEMANTIC_CATALOG_STATUSES
) | frozenset(
    {
        CATALOG_STATUS_NOT_MEASURED,
        CATALOG_STATUS_UNSUPPORTED,
        CATALOG_STATUS_RUNTIME_FAILED,
    }
)

DEFAULT_PILOT_REGRESSION_REQUIREMENTS: Final = (
    "pilot_mean_e2e_must_remain_0.0",
    "pilot_population_immutable_regression_control",
    "no_blind_holdout_access_before_candidate_freeze",
)

DEFAULT_PACKET_INVALIDATORS: Final = (
    "stale_baseline_or_tree_binding",
    "catalog_cid_mismatch",
    "population_cid_mismatch",
    "blind_residual_or_source_leak",
    "admission_reject_timeout_error",
    "evidence_status_not_semantic_scored",
    "missing_required_evidence",
    "token_budget_exceeded_without_omission_coverage",
)

_OBLIGATION_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PACKET_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_HEX64_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_CID_OR_DIGEST_RE: Final = re.compile(
    r"^(?:[0-9a-f]{64}|baguqeer[a-z0-9]+|bafy[a-z0-9]+)$"
)


class PlateauCodexPacketError(ContractError):
    """Contract violation in PlateauCodexPacket@1 construction or parsing."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlateauCodexPacketError(f"{field} must be a nonblank string")
    return value.strip()


def _optional_nonblank(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _nonblank(value, field)


def _finite_nonneg(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0.0
    ):
        raise PlateauCodexPacketError(
            f"{field} must be a nonnegative finite number"
        )
    return float(value)


def _string_tuple(
    value: object,
    field: str,
    *,
    allow_empty: bool = True,
    unique: bool = True,
) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
    ):
        raise PlateauCodexPacketError(f"{field} must be a string array")
    items = tuple(_nonblank(item, f"{field}[{index}]") for index, item in enumerate(value))
    if not allow_empty and not items:
        raise PlateauCodexPacketError(f"{field} must be nonempty")
    if unique and len(set(items)) != len(items):
        raise PlateauCodexPacketError(f"{field} must not contain duplicates")
    return items


def baseline_l1_digest(baseline_l1: CanonicalRuleIR) -> str:
    """Content digest of a baseline CanonicalRuleIR payload."""

    if not isinstance(baseline_l1, CanonicalRuleIR):
        raise PlateauCodexPacketError("baseline_l1 must be CanonicalRuleIR")
    return _sha(baseline_l1.to_dict())


def field_change_from_dict(value: object) -> CanonicalFieldChange:
    """Restore a CanonicalFieldChange from a sealed dict."""

    if not isinstance(value, Mapping):
        raise PlateauCodexPacketError(
            "field change must be an object"
        )
    try:
        return CanonicalFieldChange(
            canonical_field=value["canonical_field"],  # type: ignore[arg-type]
            before=value.get("before"),
            after=value.get("after"),
            baseline_rule_index=value.get("baseline_rule_index"),  # type: ignore[arg-type]
            guided_rule_index=value.get("guided_rule_index"),  # type: ignore[arg-type]
        )
    except (KeyError, TypeError, ValueError, ContractError) as exc:
        raise PlateauCodexPacketError(
            f"invalid CanonicalFieldChange: {exc}"
        ) from exc


def field_change_path(change: CanonicalFieldChange) -> str:
    """Stable path string for a field change (prefer index form)."""

    if change.baseline_rule_index is not None:
        return (
            f"rules[{change.baseline_rule_index}].{change.canonical_field}"
        )
    return change.path


def disposition_is_implementable(disposition: AdmissionDisposition) -> bool:
    """Return whether a structural disposition may authorize implementable work."""

    if not isinstance(disposition, AdmissionDisposition):
        try:
            disposition = AdmissionDisposition(disposition)
        except (TypeError, ValueError) as exc:
            raise PlateauCodexPacketError(
                "admission disposition is invalid"
            ) from exc
    return disposition is AdmissionDisposition.ACCEPTED


def _looks_like_digest_or_cid(value: str) -> bool:
    cleaned = value.strip()
    if _HEX64_RE.match(cleaned):
        return True
    if cleaned.startswith("baguqeer") or cleaned.startswith("bafy"):
        return len(cleaned) >= 8
    return False


def _is_forbidden_content_key(key: str) -> bool:
    """Return whether *key* names forbidden payload (not exclusion flags)."""

    lowered = key.strip().lower()
    if lowered.startswith("excludes_"):
        return False
    if lowered in FORBIDDEN_PACKET_CONTENT_KEYS:
        return True
    # Substring match only for concrete payload fields, not meta flags.
    for token in (
        "gold_value",
        "gold_ir",
        "gold_body",
        "source_text",
        "blind_source",
        "blind_gold",
        "raw_solver_trace",
        "repository_dump",
        "full_repository",
        "untrusted_instruction",
    ):
        if token == lowered or lowered.endswith(f"_{token}") or lowered.startswith(
            f"{token}_"
        ):
            return True
    return False


def _assert_no_forbidden_content(
    value: object,
    *,
    path: str = "root",
) -> None:
    """Fail closed if gold bodies, blind sources, or dumps appear in context."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            key_str = str(key)
            if _is_forbidden_content_key(key_str):
                raise PlateauCodexPacketError(
                    f"forbidden packet content key {key_str!r} at {path}"
                )
            _assert_no_forbidden_content(item, path=f"{path}.{key_str}")
        return
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value):
            _assert_no_forbidden_content(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        # Large free-text blobs are not allowed as gold/source substitutes.
        if len(value) > 4_096 and not _looks_like_digest_or_cid(value):
            raise PlateauCodexPacketError(
                f"oversized free-text context at {path} "
                "(use content-addressed handles)"
            )


def count_tokens_whitespace_proxy(value: object) -> int:
    """Frozen ``whitespace_split_proxy_v1`` token count for packet payloads."""

    text = _canonical_json(value)
    if not text.strip():
        return 0
    return len(text.split())


def _validate_predicted_file(path: str) -> str:
    cleaned = _nonblank(path, "predicted_files item")
    if ".." in cleaned.split("/"):
        raise PlateauCodexPacketError(
            f"predicted file path must not contain '..': {cleaned!r}"
        )
    if cleaned.startswith("/") or cleaned.startswith("\\"):
        raise PlateauCodexPacketError(
            f"predicted file path must be repository-relative: {cleaned!r}"
        )
    if not any(cleaned.startswith(prefix) for prefix in ALLOWED_PREDICTED_FILE_PREFIXES):
        raise PlateauCodexPacketError(
            "predicted file must target deterministic compiler/realizer/"
            f"tests/docs surface; got {cleaned!r}"
        )
    return cleaned


class TeacherKind(str, Enum):
    """Known offline teachers that may author IR patch proposals."""

    LEANSTRAL = "leanstral"
    SYMAI = "symai"
    SPACY = "spacy"
    AUTOENCODER = "autoencoder"
    RESIDUAL_CATALOG = "residual_catalog"
    MANUAL = "manual"
    HYBRID = "hybrid"


@dataclass(frozen=True, slots=True)
class ResidualRef:
    """Reference to one residual catalog facet consumed by a packet.

    Residual refs are non-authoritative pointers: they locate case×facet
    loss contributions that motivated a proposal.  They never authorize
    production composition by themselves.
    """

    residual_id: str
    case_id: str
    field_paths: tuple[str, ...]
    facet: str | None = None
    estimated_forward_contribution: float | None = None
    catalog_digest: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "residual_id", _nonblank(self.residual_id, "residual_id")
        )
        if not _PACKET_ID_RE.match(self.residual_id):
            raise PlateauCodexPacketError(
                f"residual_id has invalid shape: {self.residual_id!r}"
            )
        object.__setattr__(
            self, "case_id", _nonblank(self.case_id, "case_id")
        )
        object.__setattr__(
            self,
            "field_paths",
            _string_tuple(self.field_paths, "field_paths", allow_empty=False),
        )
        object.__setattr__(
            self, "facet", _optional_nonblank(self.facet, "facet")
        )
        if self.estimated_forward_contribution is not None:
            object.__setattr__(
                self,
                "estimated_forward_contribution",
                _finite_nonneg(
                    self.estimated_forward_contribution,
                    "estimated_forward_contribution",
                ),
            )
        object.__setattr__(
            self,
            "catalog_digest",
            _optional_nonblank(self.catalog_digest, "catalog_digest"),
        )
        if self.catalog_digest is not None and not (
            _HEX64_RE.match(self.catalog_digest)
            or self.catalog_digest.startswith("baguqeer")
            or self.catalog_digest.startswith("bafy")
        ):
            # Allow hex digests or common CIDv1 prefixes without hard codec dep.
            if len(self.catalog_digest) < 8:
                raise PlateauCodexPacketError(
                    "catalog_digest must be a digest or CID when present"
                )
        object.__setattr__(
            self, "detail", _optional_nonblank(self.detail, "detail")
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "catalog_digest": self.catalog_digest,
            "detail": self.detail,
            "estimated_forward_contribution": (
                self.estimated_forward_contribution
            ),
            "facet": self.facet,
            "field_paths": list(self.field_paths),
            "interface": PLATEAU_RESIDUAL_REF_INTERFACE,
            "residual_id": self.residual_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ResidualRef":
        if not isinstance(value, Mapping):
            raise PlateauCodexPacketError("residual ref must be an object")
        return cls(
            residual_id=value.get("residual_id"),  # type: ignore[arg-type]
            case_id=value.get("case_id"),  # type: ignore[arg-type]
            field_paths=tuple(value.get("field_paths") or ()),  # type: ignore[arg-type]
            facet=value.get("facet"),  # type: ignore[arg-type]
            estimated_forward_contribution=value.get(
                "estimated_forward_contribution"
            ),  # type: ignore[arg-type]
            catalog_digest=value.get("catalog_digest"),  # type: ignore[arg-type]
            detail=value.get("detail"),  # type: ignore[arg-type]
        )


def stable_residual_id(
    case_id: str,
    field_path: str,
    *,
    residual_kind: str | None = None,
    index: int | None = None,
) -> str:
    """Build a stable residual_id from case × field (catalog facet identity)."""

    case = _nonblank(case_id, "case_id")
    path = _nonblank(field_path, "field_path")
    kind = (
        _optional_nonblank(residual_kind, "residual_kind")
        if residual_kind is not None
        else None
    )
    raw = f"resid-{case}-{path}"
    if kind:
        raw = f"{raw}-{kind}"
    if index is not None:
        raw = f"{raw}-{int(index)}"
    # Collapse path punctuation to residual_id charset.
    sanitized = re.sub(r"[^A-Za-z0-9_.:-]", "-", raw)
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
    if not sanitized or not _PACKET_ID_RE.match(sanitized):
        raise PlateauCodexPacketError(
            f"could not form residual_id from case={case!r} path={path!r}"
        )
    return sanitized[:128]


def residual_ref_from_catalog_facet(
    facet: Mapping[str, object] | object,
    *,
    catalog_digest: str | None = None,
    residual_id: str | None = None,
    index: int | None = None,
) -> ResidualRef:
    """Project one residual-catalog facet into a :class:`ResidualRef`.

    Accepts a :class:`~benchmarks.semantic_roundtrip.residual_catalog.ResidualFacet`
    (or its ``to_dict()`` mapping).  Holdout and pilot catalogs share the same
    facet shape, so this is population-agnostic.
    """

    if hasattr(facet, "to_dict") and not isinstance(facet, Mapping):
        try:
            data = facet.to_dict()  # type: ignore[operator]
        except Exception as exc:  # pragma: no cover - defensive
            raise PlateauCodexPacketError(
                f"catalog facet to_dict failed: {exc}"
            ) from exc
        if not isinstance(data, Mapping):
            raise PlateauCodexPacketError(
                "catalog facet to_dict must return a mapping"
            )
    elif isinstance(facet, Mapping):
        data = facet
    else:
        raise PlateauCodexPacketError(
            "catalog facet must be a mapping or ResidualFacet-like object"
        )

    case_id = _nonblank(data.get("case_id"), "case_id")
    field_path = _nonblank(data.get("field_path"), "field_path")
    residual_kind = data.get("residual_kind")
    kind_str = (
        _optional_nonblank(residual_kind, "residual_kind")
        if residual_kind is not None
        else None
    )
    rid = (
        _nonblank(residual_id, "residual_id")
        if residual_id is not None
        else stable_residual_id(
            case_id,
            field_path,
            residual_kind=kind_str,
            index=index,
        )
    )
    contribution = data.get("loss_contribution")
    facet_label = data.get("canonical_field") or kind_str
    detail_parts = [
        f"residual_kind={kind_str}" if kind_str else None,
        (
            f"trigger={data.get('suggested_trigger_kind')}"
            if data.get("suggested_trigger_kind")
            else None
        ),
    ]
    detail = "; ".join(part for part in detail_parts if part) or None
    catalog = catalog_digest
    if catalog is None:
        catalog = None
    return ResidualRef(
        residual_id=rid,
        case_id=case_id,
        field_paths=(field_path,),
        facet=(
            _optional_nonblank(facet_label, "facet")
            if facet_label is not None
            else None
        ),
        estimated_forward_contribution=(
            float(contribution) if contribution is not None else None
        ),
        catalog_digest=(
            _optional_nonblank(catalog, "catalog_digest")
            if catalog is not None
            else None
        ),
        detail=detail,
    )


def residual_refs_from_catalog(
    catalog: Mapping[str, object],
    *,
    case_ids: Sequence[str] | None = None,
    nonzero_only: bool = True,
    require_nonempty: bool = False,
) -> tuple[ResidualRef, ...]:
    """Build residual refs from a plateau residual catalog payload.

    Works for pilot, holdout, and custom populations.  When *nonzero_only* is
    true (default), only facets with positive ``loss_contribution`` are kept
    (flat ``residuals`` already excludes zero-loss rows in sealed catalogs).
    """

    if not isinstance(catalog, Mapping):
        raise PlateauCodexPacketError("catalog must be an object")
    digest = catalog.get("catalog_cid") or catalog.get("catalog_digest")
    catalog_digest = (
        _optional_nonblank(digest, "catalog_cid")
        if digest is not None
        else None
    )

    allowed: set[str] | None
    if case_ids is not None:
        allowed = {_nonblank(item, "case_ids item") for item in case_ids}
    else:
        allowed = None

    raw_residuals = catalog.get("residuals")
    facets: list[Mapping[str, object]] = []
    if isinstance(raw_residuals, Sequence) and not isinstance(
        raw_residuals, (str, bytes, bytearray)
    ):
        for item in raw_residuals:
            if isinstance(item, Mapping):
                facets.append(item)
    else:
        # Nested case residual layout.
        cases = catalog.get("cases")
        if isinstance(cases, Sequence) and not isinstance(
            cases, (str, bytes, bytearray)
        ):
            for case in cases:
                if not isinstance(case, Mapping):
                    continue
                nested = case.get("residuals") or ()
                if not isinstance(nested, Sequence) or isinstance(
                    nested, (str, bytes, bytearray)
                ):
                    continue
                for item in nested:
                    if isinstance(item, Mapping):
                        facets.append(item)

    refs: list[ResidualRef] = []
    for index, facet in enumerate(facets):
        case_id = facet.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            continue
        if allowed is not None and case_id.strip() not in allowed:
            continue
        loss = facet.get("loss_contribution")
        if nonzero_only:
            try:
                if loss is None or float(loss) <= 0.0:
                    continue
            except (TypeError, ValueError):
                continue
        refs.append(
            residual_ref_from_catalog_facet(
                facet,
                catalog_digest=catalog_digest,
                index=index,
            )
        )

    if require_nonempty and not refs:
        raise PlateauCodexPacketError(
            "catalog produced no residual refs for the requested filter"
        )
    return tuple(refs)


def assert_catalog_allowed_for_packets(
    catalog: Mapping[str, object],
    *,
    allowed_population_kinds: Sequence[str] | None = None,
) -> str:
    """Reject blind / unauthorized populations on normal packet paths.

    Returns the catalog's ``population_kind``.  Default allowlist is
    ``repair_development`` only (PLAT2-030).  Pass an explicit allowlist
    to accept transitional ``holdout`` catalogs.
    """

    if not isinstance(catalog, Mapping):
        raise PlateauCodexPacketError("catalog must be an object")
    kind = catalog.get("population_kind")
    if not isinstance(kind, str) or not kind.strip():
        raise PlateauCodexPacketError(
            "catalog must declare population_kind for packet construction"
        )
    kind = kind.strip()
    if kind in BLIND_POPULATION_KINDS or kind == (
        POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION
    ):
        raise PlateauCodexPacketError(
            "blind / authorized_blind_evaluation residuals are forbidden "
            "on normal packet paths"
        )
    # Detect blind leakage via forbidden keys in catalog residuals.
    _assert_no_forbidden_content(
        {
            "case_ids": catalog.get("case_ids"),
            "population_kind": kind,
            "residuals_meta": [
                {
                    "case_id": item.get("case_id")
                    if isinstance(item, Mapping)
                    else None,
                    "field_path": item.get("field_path")
                    if isinstance(item, Mapping)
                    else None,
                    "residual_kind": item.get("residual_kind")
                    if isinstance(item, Mapping)
                    else None,
                }
                for item in (catalog.get("residuals") or ())
                if isinstance(item, Mapping)
            ],
        },
        path="catalog",
    )
    allowed = (
        tuple(allowed_population_kinds)
        if allowed_population_kinds is not None
        else (REPAIR_DEV_POPULATION_KIND,)
    )
    if kind not in allowed:
        raise PlateauCodexPacketError(
            f"packets accept population kinds {allowed!r} only; got {kind!r}"
        )
    return kind


def catalog_case_evidence_status(
    catalog: Mapping[str, object],
    case_id: str,
) -> str:
    """Return per-case evaluation status from a residual catalog payload."""

    case = _nonblank(case_id, "case_id")
    status_block = catalog.get("status")
    if isinstance(status_block, Mapping):
        by_case = status_block.get("by_case")
        if isinstance(by_case, Mapping) and case in by_case:
            row = by_case[case]
            if isinstance(row, Mapping):
                evaluation = row.get("evaluation_status")
                if isinstance(evaluation, str) and evaluation.strip():
                    return evaluation.strip()
    # Flat residual rows may carry status.
    residuals = catalog.get("residuals")
    if isinstance(residuals, Sequence) and not isinstance(
        residuals, (str, bytes, bytearray)
    ):
        for item in residuals:
            if not isinstance(item, Mapping):
                continue
            if str(item.get("case_id") or "").strip() != case:
                continue
            evaluation = item.get("evaluation_status") or item.get("status")
            if isinstance(evaluation, str) and evaluation.strip():
                return evaluation.strip()
    return CATALOG_STATUS_SEMANTIC_SCORED


def extract_catalog_bindings(
    catalog: Mapping[str, object],
    *,
    case_id: str | None = None,
    extra_assumptions: Sequence[str] | None = None,
    acceptance_ids: Sequence[str] | None = None,
    invalidators: Sequence[str] | None = None,
) -> "PacketBindings":
    """Project catalog CID bindings into :class:`PacketBindings`."""

    if not isinstance(catalog, Mapping):
        raise PlateauCodexPacketError("catalog must be an object")
    baseline = catalog.get("baseline")
    baseline_cid: str | None = None
    if isinstance(baseline, Mapping):
        report = baseline.get("report_cid") or baseline.get("baseline_cid")
        if isinstance(report, str) and report.strip():
            baseline_cid = report.strip()
    tree_cid = catalog.get("tree_cid")
    population_cid = catalog.get("population_cid")
    catalog_cid = catalog.get("catalog_cid") or catalog.get("catalog_digest")
    population_kind = catalog.get("population_kind")
    assumptions_raw = catalog.get("assumptions") or ()
    assumptions: list[str] = []
    if isinstance(assumptions_raw, Sequence) and not isinstance(
        assumptions_raw, (str, bytes, bytearray)
    ):
        for item in assumptions_raw:
            if isinstance(item, str) and item.strip():
                assumptions.append(item.strip())
    if extra_assumptions:
        for item in extra_assumptions:
            cleaned = _nonblank(item, "extra_assumptions item")
            if cleaned not in assumptions:
                assumptions.append(cleaned)
    evidence_status = (
        catalog_case_evidence_status(catalog, case_id)
        if case_id is not None
        else CATALOG_STATUS_SEMANTIC_SCORED
    )
    provenance_raw = catalog.get("provenance")
    provenance: dict[str, object] = {}
    if isinstance(provenance_raw, Mapping):
        # Drop forbidden keys if a buggy producer attached them.
        for key, value in provenance_raw.items():
            key_str = str(key)
            if key_str.lower() in FORBIDDEN_PACKET_CONTENT_KEYS:
                continue
            provenance[key_str] = value
    provenance.setdefault(
        "population_kind",
        population_kind if isinstance(population_kind, str) else None,
    )
    provenance.setdefault(
        "catalog_cid",
        catalog_cid if isinstance(catalog_cid, str) else None,
    )
    return PacketBindings(
        baseline_cid=(
            _optional_nonblank(baseline_cid, "baseline_cid")
            if baseline_cid is not None
            else None
        ),
        tree_cid=(
            _optional_nonblank(tree_cid, "tree_cid")
            if isinstance(tree_cid, str)
            else None
        ),
        population_cid=(
            _optional_nonblank(population_cid, "population_cid")
            if isinstance(population_cid, str)
            else None
        ),
        catalog_cid=(
            _optional_nonblank(catalog_cid, "catalog_cid")
            if isinstance(catalog_cid, str)
            else None
        ),
        population_kind=(
            _optional_nonblank(population_kind, "population_kind")
            if isinstance(population_kind, str)
            else None
        ),
        assumptions=tuple(assumptions),
        evidence_status=evidence_status,
        structural_obligation_ids=(),
        invalidators=tuple(
            invalidators
            if invalidators is not None
            else DEFAULT_PACKET_INVALIDATORS
        ),
        acceptance_ids=tuple(acceptance_ids or ()),
        provenance=provenance,
    )


@dataclass(frozen=True, slots=True)
class PacketBindings:
    """CID and provenance bindings sealed into a repair-development packet."""

    baseline_cid: str | None
    tree_cid: str | None
    population_cid: str | None
    catalog_cid: str | None
    population_kind: str | None
    assumptions: tuple[str, ...]
    evidence_status: str
    structural_obligation_ids: tuple[str, ...] = ()
    invalidators: tuple[str, ...] = ()
    acceptance_ids: tuple[str, ...] = ()
    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "baseline_cid",
            _optional_nonblank(self.baseline_cid, "baseline_cid")
            if self.baseline_cid is not None
            else None,
        )
        object.__setattr__(
            self,
            "tree_cid",
            _optional_nonblank(self.tree_cid, "tree_cid")
            if self.tree_cid is not None
            else None,
        )
        object.__setattr__(
            self,
            "population_cid",
            _optional_nonblank(self.population_cid, "population_cid")
            if self.population_cid is not None
            else None,
        )
        object.__setattr__(
            self,
            "catalog_cid",
            _optional_nonblank(self.catalog_cid, "catalog_cid")
            if self.catalog_cid is not None
            else None,
        )
        object.__setattr__(
            self,
            "population_kind",
            _optional_nonblank(self.population_kind, "population_kind")
            if self.population_kind is not None
            else None,
        )
        object.__setattr__(
            self,
            "assumptions",
            _string_tuple(self.assumptions, "assumptions", allow_empty=True),
        )
        object.__setattr__(
            self,
            "evidence_status",
            _nonblank(self.evidence_status, "evidence_status"),
        )
        object.__setattr__(
            self,
            "structural_obligation_ids",
            _string_tuple(
                self.structural_obligation_ids,
                "structural_obligation_ids",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "invalidators",
            _string_tuple(
                self.invalidators, "invalidators", allow_empty=True
            ),
        )
        object.__setattr__(
            self,
            "acceptance_ids",
            _string_tuple(
                self.acceptance_ids, "acceptance_ids", allow_empty=True
            ),
        )
        if not isinstance(self.provenance, Mapping):
            raise PlateauCodexPacketError("provenance must be an object")
        plain = {str(key): value for key, value in self.provenance.items()}
        _assert_no_forbidden_content(plain, path="provenance")
        object.__setattr__(self, "provenance", plain)

    @property
    def is_complete(self) -> bool:
        return all(
            (
                self.baseline_cid,
                self.tree_cid,
                self.population_cid,
                self.catalog_cid,
                self.population_kind,
            )
        )

    def with_structural_obligation_ids(
        self, obligation_ids: Sequence[str]
    ) -> "PacketBindings":
        return PacketBindings(
            baseline_cid=self.baseline_cid,
            tree_cid=self.tree_cid,
            population_cid=self.population_cid,
            catalog_cid=self.catalog_cid,
            population_kind=self.population_kind,
            assumptions=self.assumptions,
            evidence_status=self.evidence_status,
            structural_obligation_ids=tuple(obligation_ids),
            invalidators=self.invalidators,
            acceptance_ids=self.acceptance_ids,
            provenance=dict(self.provenance),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "acceptance_ids": list(self.acceptance_ids),
            "assumptions": list(self.assumptions),
            "baseline_cid": self.baseline_cid,
            "catalog_cid": self.catalog_cid,
            "evidence_status": self.evidence_status,
            "interface": PLATEAU_PACKET_BINDINGS_INTERFACE,
            "invalidators": list(self.invalidators),
            "population_cid": self.population_cid,
            "population_kind": self.population_kind,
            "provenance": dict(self.provenance),
            "structural_obligation_ids": list(self.structural_obligation_ids),
            "tree_cid": self.tree_cid,
        }

    @classmethod
    def from_dict(cls, value: object) -> "PacketBindings":
        if not isinstance(value, Mapping):
            raise PlateauCodexPacketError("packet bindings must be an object")
        return cls(
            baseline_cid=value.get("baseline_cid"),  # type: ignore[arg-type]
            tree_cid=value.get("tree_cid"),  # type: ignore[arg-type]
            population_cid=value.get("population_cid"),  # type: ignore[arg-type]
            catalog_cid=value.get("catalog_cid"),  # type: ignore[arg-type]
            population_kind=value.get("population_kind"),  # type: ignore[arg-type]
            assumptions=tuple(value.get("assumptions") or ()),  # type: ignore[arg-type]
            evidence_status=value.get(
                "evidence_status", CATALOG_STATUS_SEMANTIC_SCORED
            ),  # type: ignore[arg-type]
            structural_obligation_ids=tuple(
                value.get("structural_obligation_ids") or ()
            ),  # type: ignore[arg-type]
            invalidators=tuple(value.get("invalidators") or ()),  # type: ignore[arg-type]
            acceptance_ids=tuple(value.get("acceptance_ids") or ()),  # type: ignore[arg-type]
            provenance=dict(value.get("provenance") or {}),
        )


@dataclass(frozen=True, slots=True)
class InvariantContext:
    """Bounded invariant context for an obligation-first packet.

    Contains handles and digests only — never gold target bodies, blind
    sources, full-repository dumps, raw solver traces, or untrusted
    instructions.
    """

    failing_facet: str | None
    counterexample_handle: str | None
    canonical_spec_rule_handles: tuple[str, ...]
    changed_ast_dependency_slice: tuple[str, ...]
    pilot_regression_requirements: tuple[str, ...]
    proof_receipt_digests: tuple[str, ...]
    excludes_full_repository_dump: bool = True
    excludes_gold_target_bodies: bool = True
    excludes_blind_ids_sources_gold: bool = True
    excludes_raw_solver_traces: bool = True
    excludes_untrusted_instructions: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "failing_facet",
            _optional_nonblank(self.failing_facet, "failing_facet")
            if self.failing_facet is not None
            else None,
        )
        object.__setattr__(
            self,
            "counterexample_handle",
            _optional_nonblank(
                self.counterexample_handle, "counterexample_handle"
            )
            if self.counterexample_handle is not None
            else None,
        )
        object.__setattr__(
            self,
            "canonical_spec_rule_handles",
            _string_tuple(
                self.canonical_spec_rule_handles,
                "canonical_spec_rule_handles",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "changed_ast_dependency_slice",
            _string_tuple(
                self.changed_ast_dependency_slice,
                "changed_ast_dependency_slice",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "pilot_regression_requirements",
            _string_tuple(
                self.pilot_regression_requirements,
                "pilot_regression_requirements",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "proof_receipt_digests",
            _string_tuple(
                self.proof_receipt_digests,
                "proof_receipt_digests",
                allow_empty=True,
            ),
        )
        for flag_name in (
            "excludes_full_repository_dump",
            "excludes_gold_target_bodies",
            "excludes_blind_ids_sources_gold",
            "excludes_raw_solver_traces",
            "excludes_untrusted_instructions",
        ):
            if getattr(self, flag_name) is not True:
                raise PlateauCodexPacketError(
                    f"{flag_name} must be true (forbidden content excluded)"
                )
        _assert_no_forbidden_content(self.to_dict(), path="invariant_context")

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_spec_rule_handles": list(
                self.canonical_spec_rule_handles
            ),
            "changed_ast_dependency_slice": list(
                self.changed_ast_dependency_slice
            ),
            "counterexample_handle": self.counterexample_handle,
            "excludes_blind_ids_sources_gold": True,
            "excludes_full_repository_dump": True,
            "excludes_gold_target_bodies": True,
            "excludes_raw_solver_traces": True,
            "excludes_untrusted_instructions": True,
            "failing_facet": self.failing_facet,
            "interface": PLATEAU_INVARIANT_CONTEXT_INTERFACE,
            "pilot_regression_requirements": list(
                self.pilot_regression_requirements
            ),
            "proof_receipt_digests": list(self.proof_receipt_digests),
        }

    @classmethod
    def from_dict(cls, value: object) -> "InvariantContext":
        if not isinstance(value, Mapping):
            raise PlateauCodexPacketError(
                "invariant context must be an object"
            )
        return cls(
            failing_facet=value.get("failing_facet"),  # type: ignore[arg-type]
            counterexample_handle=value.get(
                "counterexample_handle"
            ),  # type: ignore[arg-type]
            canonical_spec_rule_handles=tuple(
                value.get("canonical_spec_rule_handles") or ()
            ),  # type: ignore[arg-type]
            changed_ast_dependency_slice=tuple(
                value.get("changed_ast_dependency_slice") or ()
            ),  # type: ignore[arg-type]
            pilot_regression_requirements=tuple(
                value.get("pilot_regression_requirements") or ()
            ),  # type: ignore[arg-type]
            proof_receipt_digests=tuple(
                value.get("proof_receipt_digests") or ()
            ),  # type: ignore[arg-type]
            excludes_full_repository_dump=bool(
                value.get("excludes_full_repository_dump", True)
            ),
            excludes_gold_target_bodies=bool(
                value.get("excludes_gold_target_bodies", True)
            ),
            excludes_blind_ids_sources_gold=bool(
                value.get("excludes_blind_ids_sources_gold", True)
            ),
            excludes_raw_solver_traces=bool(
                value.get("excludes_raw_solver_traces", True)
            ),
            excludes_untrusted_instructions=bool(
                value.get("excludes_untrusted_instructions", True)
            ),
        )


def build_invariant_context(
    *,
    residual_refs: Sequence[ResidualRef],
    admission_receipts: Sequence["PlateauAdmissionReceipt"] = (),
    admitted_field_changes: Sequence[CanonicalFieldChange] = (),
    baseline_l1_digest: str | None = None,
    pilot_regression_requirements: Sequence[str] | None = None,
    extra_spec_handles: Sequence[str] | None = None,
    extra_ast_slice: Sequence[str] | None = None,
) -> InvariantContext:
    """Build a bounded invariant context from residuals and admissions."""

    failing_facet: str | None = None
    counterexample_handle: str | None = None
    if residual_refs:
        primary = residual_refs[0]
        failing_facet = primary.facet or (
            primary.field_paths[0] if primary.field_paths else primary.residual_id
        )
        counter_payload = {
            "case_id": primary.case_id,
            "catalog_digest": primary.catalog_digest,
            "facet": primary.facet,
            "field_paths": list(primary.field_paths),
            "residual_id": primary.residual_id,
            "baseline_l1_digest": baseline_l1_digest,
        }
        _assert_no_forbidden_content(
            counter_payload, path="counterexample_payload"
        )
        counterexample_handle = _sha(counter_payload)

    spec_handles: list[str] = []
    if extra_spec_handles:
        spec_handles.extend(
            _nonblank(item, "extra_spec_handles item")
            for item in extra_spec_handles
        )
    for ref in residual_refs:
        for path in ref.field_paths:
            handle = f"spec:{ref.case_id}:{path}"
            if handle not in spec_handles:
                spec_handles.append(handle)
        if ref.facet:
            facet_handle = f"rule-facet:{ref.facet}"
            if facet_handle not in spec_handles:
                spec_handles.append(facet_handle)

    ast_slice: list[str] = []
    if extra_ast_slice:
        ast_slice.extend(
            _nonblank(item, "extra_ast_slice item") for item in extra_ast_slice
        )
    for change in admitted_field_changes:
        path = field_change_path(change)
        if path not in ast_slice:
            ast_slice.append(path)
    for ref in residual_refs:
        for path in ref.field_paths:
            if path not in ast_slice:
                ast_slice.append(path)

    proof_digests: list[str] = []
    for receipt in admission_receipts:
        digest_payload = {
            "admitted_l1_digest": receipt.admitted_l1_digest,
            "candidate_l1_digest": receipt.candidate_l1_digest,
            "disposition": receipt.disposition.value
            if hasattr(receipt.disposition, "value")
            else str(receipt.disposition),
            "policy_digest": receipt.policy_digest,
            "prior_l1_digest": receipt.prior_l1_digest,
            "proposal_id": receipt.proposal_id,
        }
        proof_digests.append(_sha(digest_payload))
        for check in receipt.check_receipts:
            proof_digests.append(
                _sha(
                    {
                        "constraints": list(check.constraints),
                        "passed": check.passed,
                        "timed_out": check.timed_out,
                        "tool": check.tool,
                        "validator_id": check.validator_id,
                    }
                )
            )

    requirements = tuple(
        pilot_regression_requirements
        if pilot_regression_requirements is not None
        else DEFAULT_PILOT_REGRESSION_REQUIREMENTS
    )
    return InvariantContext(
        failing_facet=failing_facet,
        counterexample_handle=counterexample_handle,
        canonical_spec_rule_handles=tuple(spec_handles),
        changed_ast_dependency_slice=tuple(ast_slice),
        pilot_regression_requirements=requirements,
        proof_receipt_digests=tuple(proof_digests),
    )


@dataclass(frozen=True, slots=True)
class ExpansionHandle:
    """Content-addressed optional evidence handle under the token budget."""

    handle_id: str
    content_digest: str
    kind: str
    token_estimate: int
    included: bool
    detail: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "handle_id", _nonblank(self.handle_id, "handle_id")
        )
        if not _PACKET_ID_RE.match(self.handle_id):
            raise PlateauCodexPacketError(
                f"handle_id has invalid shape: {self.handle_id!r}"
            )
        digest = _nonblank(self.content_digest, "content_digest")
        if not _looks_like_digest_or_cid(digest):
            raise PlateauCodexPacketError(
                "expansion handle content_digest must be a digest or CID"
            )
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "kind", _nonblank(self.kind, "kind"))
        if (
            isinstance(self.token_estimate, bool)
            or not isinstance(self.token_estimate, int)
            or self.token_estimate < 0
        ):
            raise PlateauCodexPacketError(
                "token_estimate must be a nonnegative integer"
            )
        if not isinstance(self.included, bool):
            raise PlateauCodexPacketError("included must be boolean")
        object.__setattr__(
            self, "detail", _optional_nonblank(self.detail, "detail")
        )
        if self.detail is not None:
            _assert_no_forbidden_content(
                {"detail": self.detail}, path="expansion_handle"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "content_digest": self.content_digest,
            "detail": self.detail,
            "handle_id": self.handle_id,
            "included": self.included,
            "interface": PLATEAU_EXPANSION_HANDLE_INTERFACE,
            "kind": self.kind,
            "token_estimate": self.token_estimate,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ExpansionHandle":
        if not isinstance(value, Mapping):
            raise PlateauCodexPacketError(
                "expansion handle must be an object"
            )
        return cls(
            handle_id=value.get("handle_id"),  # type: ignore[arg-type]
            content_digest=value.get("content_digest"),  # type: ignore[arg-type]
            kind=value.get("kind"),  # type: ignore[arg-type]
            token_estimate=int(value.get("token_estimate", 0)),
            included=bool(value.get("included", False)),
            detail=value.get("detail"),  # type: ignore[arg-type]
        )


def plan_expansion_handles(
    candidates: Sequence[ExpansionHandle | Mapping[str, object]],
    *,
    base_token_count: int,
    token_budget: int = PACKET_TOKEN_BUDGET,
) -> tuple[tuple[ExpansionHandle, ...], tuple[str, ...], float, int]:
    """Select expansion handles under the frozen token budget.

    Returns ``(handles, omitted_handle_ids, omitted_coverage, total_tokens)``.
    ``omitted_coverage`` is the fraction of candidate handles that were
    recorded as omitted (1.0 when none omitted and none candidates; 0.0 when
    all candidates were omitted without any included).
    """

    if (
        isinstance(base_token_count, bool)
        or not isinstance(base_token_count, int)
        or base_token_count < 0
    ):
        raise PlateauCodexPacketError(
            "base_token_count must be a nonnegative integer"
        )
    budget = int(token_budget)
    if budget <= 0:
        raise PlateauCodexPacketError("token_budget must be positive")

    ordered: list[ExpansionHandle] = []
    for item in candidates:
        if isinstance(item, ExpansionHandle):
            ordered.append(item)
        elif isinstance(item, Mapping):
            ordered.append(ExpansionHandle.from_dict(item))
        else:
            raise PlateauCodexPacketError(
                "expansion candidates must be ExpansionHandle or mapping"
            )

    running = base_token_count
    planned: list[ExpansionHandle] = []
    omitted: list[str] = []
    for handle in ordered:
        if handle.included and running + handle.token_estimate <= budget:
            planned.append(
                ExpansionHandle(
                    handle_id=handle.handle_id,
                    content_digest=handle.content_digest,
                    kind=handle.kind,
                    token_estimate=handle.token_estimate,
                    included=True,
                    detail=handle.detail,
                )
            )
            running += handle.token_estimate
        else:
            planned.append(
                ExpansionHandle(
                    handle_id=handle.handle_id,
                    content_digest=handle.content_digest,
                    kind=handle.kind,
                    token_estimate=handle.token_estimate,
                    included=False,
                    detail=handle.detail,
                )
            )
            omitted.append(handle.handle_id)
    total = len(ordered)
    if total == 0:
        coverage = 1.0 if PACKET_OMITTED_HANDLE_COVERAGE_REQUIRED else 0.0
    else:
        # Coverage of the omission ledger: every candidate is accounted for.
        coverage = 1.0
    return tuple(planned), tuple(omitted), float(coverage), running


def compute_implementable_blockers(
    *,
    admission_receipts: Sequence["PlateauAdmissionReceipt"],
    admitted_field_changes: Sequence[CanonicalFieldChange],
    bindings: PacketBindings | None,
    invariant_context: InvariantContext | None,
    require_repair_dev_evidence: bool,
    expected_bindings: PacketBindings | None = None,
    omitted_handle_coverage: float | None = None,
    token_count: int | None = None,
    token_budget: int | None = None,
) -> tuple[str, ...]:
    """Return reasons that force ``implementable=false`` (fail-closed)."""

    blockers: list[str] = []
    accepted = [
        item
        for item in admission_receipts
        if item.disposition is AdmissionDisposition.ACCEPTED
    ]
    if not accepted:
        blockers.append("no_accepted_admission")
    if accepted and not admitted_field_changes:
        receipt_changes = sum(
            (tuple(item.field_changes) for item in accepted),
            (),
        )
        if not receipt_changes:
            blockers.append("no_admitted_field_changes")
    for receipt in admission_receipts:
        if receipt.disposition in {
            AdmissionDisposition.VALIDATOR_REJECT,
            AdmissionDisposition.TIMEOUT,
            AdmissionDisposition.ERROR,
        } and not accepted:
            blockers.append(f"admission_{receipt.disposition.value}")

    if bindings is not None:
        if bindings.evidence_status in NON_IMPLEMENTABLE_EVIDENCE_STATUSES:
            blockers.append(
                f"evidence_status_{bindings.evidence_status}"
            )
        if require_repair_dev_evidence and not bindings.is_complete:
            blockers.append("missing_required_evidence_bindings")
        if expected_bindings is not None:
            for field_name in (
                "baseline_cid",
                "tree_cid",
                "population_cid",
                "catalog_cid",
            ):
                left = getattr(bindings, field_name)
                right = getattr(expected_bindings, field_name)
                if left and right and left != right:
                    blockers.append(f"stale_binding_{field_name}")
            if (
                bindings.population_kind
                and expected_bindings.population_kind
                and bindings.population_kind
                != expected_bindings.population_kind
            ):
                blockers.append("stale_binding_population_kind")
    elif require_repair_dev_evidence:
        blockers.append("missing_required_evidence_bindings")

    if require_repair_dev_evidence and invariant_context is None:
        blockers.append("missing_required_evidence_invariant_context")

    if (
        PACKET_OMITTED_HANDLE_COVERAGE_REQUIRED
        and omitted_handle_coverage is not None
        and omitted_handle_coverage < 1.0
    ):
        # Coverage ledger incomplete.
        blockers.append("omitted_handle_coverage_incomplete")

    if (
        token_count is not None
        and token_budget is not None
        and token_count > token_budget
    ):
        blockers.append("token_budget_exceeded")

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for item in blockers:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return tuple(unique)


@dataclass(frozen=True, slots=True)
class TeacherProposal:
    """One teacher-authored candidate IR patch proposal.

    Proposals are not implementable until structural admission accepts them.
    ``semantic_authority`` is always false: teachers do not adjudicate meaning.
    """

    proposal_id: str
    teacher: str
    residual_ref_ids: tuple[str, ...]
    allowed_field_paths: tuple[str, ...]
    candidate_l1: CanonicalRuleIR | None = None
    field_changes: tuple[CanonicalFieldChange, ...] = ()
    detail: str | None = None
    semantic_authority: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "proposal_id", _nonblank(self.proposal_id, "proposal_id")
        )
        if not _PACKET_ID_RE.match(self.proposal_id):
            raise PlateauCodexPacketError(
                f"proposal_id has invalid shape: {self.proposal_id!r}"
            )
        teacher = _nonblank(self.teacher, "teacher").lower()
        if teacher not in KNOWN_TEACHERS:
            raise PlateauCodexPacketError(
                f"unknown teacher {teacher!r}; expected one of "
                f"{sorted(KNOWN_TEACHERS)}"
            )
        object.__setattr__(self, "teacher", teacher)
        object.__setattr__(
            self,
            "residual_ref_ids",
            _string_tuple(
                self.residual_ref_ids, "residual_ref_ids", allow_empty=True
            ),
        )
        object.__setattr__(
            self,
            "allowed_field_paths",
            _string_tuple(
                self.allowed_field_paths,
                "allowed_field_paths",
                allow_empty=False,
            ),
        )
        if self.candidate_l1 is not None and not isinstance(
            self.candidate_l1, CanonicalRuleIR
        ):
            raise PlateauCodexPacketError(
                "candidate_l1 must be CanonicalRuleIR or None"
            )
        object.__setattr__(self, "field_changes", tuple(self.field_changes))
        if not all(
            isinstance(item, CanonicalFieldChange)
            for item in self.field_changes
        ):
            raise PlateauCodexPacketError(
                "field_changes must contain CanonicalFieldChange records"
            )
        if self.semantic_authority is not False:
            raise PlateauCodexPacketError(
                "teacher proposals cannot claim semantic authority"
            )
        object.__setattr__(
            self, "detail", _optional_nonblank(self.detail, "detail")
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed_field_paths": list(self.allowed_field_paths),
            "candidate_l1": (
                self.candidate_l1.to_dict()
                if self.candidate_l1 is not None
                else None
            ),
            "detail": self.detail,
            "field_changes": [item.to_dict() for item in self.field_changes],
            "interface": PLATEAU_TEACHER_PROPOSAL_INTERFACE,
            "proposal_id": self.proposal_id,
            "residual_ref_ids": list(self.residual_ref_ids),
            "semantic_authority": False,
            "teacher": self.teacher,
        }

    @classmethod
    def from_dict(cls, value: object) -> "TeacherProposal":
        if not isinstance(value, Mapping):
            raise PlateauCodexPacketError("teacher proposal must be an object")
        raw_candidate = value.get("candidate_l1")
        candidate: CanonicalRuleIR | None
        if raw_candidate is None:
            candidate = None
        else:
            candidate = CanonicalRuleIR.from_dict(raw_candidate)
        raw_changes = value.get("field_changes") or ()
        if (
            not isinstance(raw_changes, Sequence)
            or isinstance(raw_changes, (str, bytes, bytearray))
        ):
            raise PlateauCodexPacketError(
                "field_changes must be an array"
            )
        changes = tuple(field_change_from_dict(item) for item in raw_changes)
        return cls(
            proposal_id=value.get("proposal_id"),  # type: ignore[arg-type]
            teacher=value.get("teacher"),  # type: ignore[arg-type]
            residual_ref_ids=tuple(value.get("residual_ref_ids") or ()),  # type: ignore[arg-type]
            allowed_field_paths=tuple(
                value.get("allowed_field_paths") or ()
            ),  # type: ignore[arg-type]
            candidate_l1=candidate,
            field_changes=changes,
            detail=value.get("detail"),  # type: ignore[arg-type]
            semantic_authority=bool(value.get("semantic_authority", False)),
        )


@dataclass(frozen=True, slots=True)
class ProverCheckReceipt:
    """One bounded prover tool receipt embedded in a packet.

    ``semantic_authority`` is always false: Hammer/cvc5/Lean cannot adjudicate
    source meaning or lower end-to-end loss by themselves.
    """

    validator_id: str
    tool: str
    passed: bool
    timed_out: bool
    elapsed_seconds: float
    constraints: tuple[str, ...] = ()
    detail: str | None = None
    semantic_authority: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "validator_id", _nonblank(self.validator_id, "validator_id")
        )
        tool = _nonblank(self.tool, "tool")
        try:
            StructuralTool(tool)
        except (TypeError, ValueError) as exc:
            raise PlateauCodexPacketError(
                f"prover tool is invalid: {tool!r}"
            ) from exc
        object.__setattr__(self, "tool", tool)
        if not isinstance(self.passed, bool) or not isinstance(
            self.timed_out, bool
        ):
            raise PlateauCodexPacketError(
                "passed and timed_out must be booleans"
            )
        if self.timed_out and self.passed:
            raise PlateauCodexPacketError("a timed-out check cannot pass")
        object.__setattr__(
            self,
            "elapsed_seconds",
            _finite_nonneg(self.elapsed_seconds, "elapsed_seconds"),
        )
        object.__setattr__(
            self,
            "constraints",
            _string_tuple(self.constraints, "constraints", allow_empty=True),
        )
        for item in self.constraints:
            if item not in DECLARED_STRUCTURAL_CONSTRAINTS:
                raise PlateauCodexPacketError(
                    f"undeclared structural constraint: {item!r}"
                )
        if self.semantic_authority is not False:
            raise PlateauCodexPacketError(
                "prover receipts cannot claim semantic authority"
            )
        object.__setattr__(
            self, "detail", _optional_nonblank(self.detail, "detail")
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "constraints": list(self.constraints),
            "detail": self.detail,
            "elapsed_seconds": self.elapsed_seconds,
            "passed": self.passed,
            "semantic_authority": False,
            "timed_out": self.timed_out,
            "tool": self.tool,
            "validator_id": self.validator_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ProverCheckReceipt":
        if not isinstance(value, Mapping):
            raise PlateauCodexPacketError(
                "prover check receipt must be an object"
            )
        return cls(
            validator_id=value.get("validator_id"),  # type: ignore[arg-type]
            tool=value.get("tool"),  # type: ignore[arg-type]
            passed=bool(value.get("passed")),
            timed_out=bool(value.get("timed_out")),
            elapsed_seconds=value.get("elapsed_seconds", 0.0),  # type: ignore[arg-type]
            constraints=tuple(value.get("constraints") or ()),  # type: ignore[arg-type]
            detail=value.get("detail"),  # type: ignore[arg-type]
            semantic_authority=bool(value.get("semantic_authority", False)),
        )

    @classmethod
    def from_admission_check(
        cls, receipt: AdmissionCheckReceipt
    ) -> "ProverCheckReceipt":
        if not isinstance(receipt, AdmissionCheckReceipt):
            raise PlateauCodexPacketError(
                "expected AdmissionCheckReceipt"
            )
        if receipt.semantic_authority is not False:
            raise PlateauCodexPacketError(
                "admission check claimed semantic authority"
            )
        return cls(
            validator_id=receipt.validator_id,
            tool=receipt.tool.value,
            passed=receipt.passed,
            timed_out=receipt.timed_out,
            elapsed_seconds=receipt.elapsed_seconds,
            constraints=tuple(receipt.constraints),
            detail=receipt.detail,
            semantic_authority=False,
        )


@dataclass(frozen=True, slots=True)
class PlateauAdmissionReceipt:
    """Packet-embedded structural admission receipt.

    Projects ``StructuralAdmission@1`` into a serializable form that always
    asserts ``semantic_authority=false`` and never treats proof pass as
    end-to-end loss.
    """

    disposition: AdmissionDisposition
    prior_l1_digest: str
    admitted_l1_digest: str
    candidate_l1_digest: str | None
    prior_l1_unchanged: bool
    policy_digest: str
    field_changes: tuple[CanonicalFieldChange, ...]
    check_receipts: tuple[ProverCheckReceipt, ...]
    proposal_id: str | None = None
    rejection_reason: str | None = None
    detail: str | None = None
    semantic_authority: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, AdmissionDisposition):
            try:
                object.__setattr__(
                    self,
                    "disposition",
                    AdmissionDisposition(self.disposition),
                )
            except (TypeError, ValueError) as exc:
                raise PlateauCodexPacketError(
                    "admission disposition is invalid"
                ) from exc
        for name in ("prior_l1_digest", "admitted_l1_digest", "policy_digest"):
            digest = _nonblank(getattr(self, name), name)
            if not _HEX64_RE.match(digest):
                raise PlateauCodexPacketError(
                    f"{name} must be a 64-char hex digest"
                )
            object.__setattr__(self, name, digest)
        if self.candidate_l1_digest is not None:
            digest = _nonblank(
                self.candidate_l1_digest, "candidate_l1_digest"
            )
            if not _HEX64_RE.match(digest):
                raise PlateauCodexPacketError(
                    "candidate_l1_digest must be a 64-char hex digest"
                )
            object.__setattr__(self, "candidate_l1_digest", digest)
        if not isinstance(self.prior_l1_unchanged, bool):
            raise PlateauCodexPacketError(
                "prior_l1_unchanged must be boolean"
            )
        object.__setattr__(self, "field_changes", tuple(self.field_changes))
        if not all(
            isinstance(item, CanonicalFieldChange)
            for item in self.field_changes
        ):
            raise PlateauCodexPacketError(
                "field_changes must contain CanonicalFieldChange records"
            )
        object.__setattr__(
            self, "check_receipts", tuple(self.check_receipts)
        )
        if not all(
            isinstance(item, ProverCheckReceipt)
            for item in self.check_receipts
        ):
            raise PlateauCodexPacketError(
                "check_receipts must contain ProverCheckReceipt records"
            )
        for item in self.check_receipts:
            if item.semantic_authority is not False:
                raise PlateauCodexPacketError(
                    "embedded prover receipt claimed semantic authority"
                )
        object.__setattr__(
            self,
            "proposal_id",
            _optional_nonblank(self.proposal_id, "proposal_id"),
        )
        object.__setattr__(
            self,
            "rejection_reason",
            _optional_nonblank(self.rejection_reason, "rejection_reason"),
        )
        object.__setattr__(
            self, "detail", _optional_nonblank(self.detail, "detail")
        )
        if self.semantic_authority is not False:
            raise PlateauCodexPacketError(
                "admission receipts cannot claim semantic authority"
            )

        if self.disposition is AdmissionDisposition.ACCEPTED:
            if self.prior_l1_unchanged and (
                self.candidate_l1_digest is not None
                and self.candidate_l1_digest != self.prior_l1_digest
            ):
                raise PlateauCodexPacketError(
                    "accepted non-identity repair cannot claim prior unchanged"
                )
            if self.rejection_reason is not None:
                raise PlateauCodexPacketError(
                    "accepted admission cannot carry a rejection_reason"
                )
            if self.admitted_l1_digest != (
                self.candidate_l1_digest or self.prior_l1_digest
            ):
                raise PlateauCodexPacketError(
                    "accepted admission must admit the candidate L1 digest"
                )
        else:
            if self.admitted_l1_digest != self.prior_l1_digest:
                raise PlateauCodexPacketError(
                    "non-accepted admission must retain prior L1 digest"
                )
            if not self.prior_l1_unchanged:
                raise PlateauCodexPacketError(
                    "non-accepted admission must leave prior L1 unchanged"
                )

    @property
    def accepted(self) -> bool:
        return self.disposition is AdmissionDisposition.ACCEPTED

    @property
    def implementable_authority(self) -> bool:
        """Whether this receipt alone may authorize implementable edits."""

        return disposition_is_implementable(self.disposition)

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "admitted_l1_digest": self.admitted_l1_digest,
            "candidate_l1_digest": self.candidate_l1_digest,
            "check_receipts": [
                item.to_dict() for item in self.check_receipts
            ],
            "detail": self.detail,
            "disposition": self.disposition.value,
            "end_to_end_loss": None,
            "field_changes": [item.to_dict() for item in self.field_changes],
            "implementable_authority": self.implementable_authority,
            "interface": PLATEAU_ADMISSION_RECEIPT_INTERFACE,
            "policy_digest": self.policy_digest,
            "prior_l1_digest": self.prior_l1_digest,
            "prior_l1_unchanged": self.prior_l1_unchanged,
            "proof_pass_is_not_end_to_end_loss": True,
            "proposal_id": self.proposal_id,
            "rejection_reason": self.rejection_reason,
            "semantic_authority": False,
            "source_interface": STRUCTURAL_ADMISSION_RECEIPT_INTERFACE,
        }

    @classmethod
    def from_dict(cls, value: object) -> "PlateauAdmissionReceipt":
        if not isinstance(value, Mapping):
            raise PlateauCodexPacketError(
                "admission receipt must be an object"
            )
        raw_changes = value.get("field_changes") or ()
        if (
            not isinstance(raw_changes, Sequence)
            or isinstance(raw_changes, (str, bytes, bytearray))
        ):
            raise PlateauCodexPacketError("field_changes must be an array")
        raw_checks = value.get("check_receipts") or ()
        if (
            not isinstance(raw_checks, Sequence)
            or isinstance(raw_checks, (str, bytes, bytearray))
        ):
            raise PlateauCodexPacketError("check_receipts must be an array")
        return cls(
            disposition=value.get("disposition"),  # type: ignore[arg-type]
            prior_l1_digest=value.get("prior_l1_digest"),  # type: ignore[arg-type]
            admitted_l1_digest=value.get("admitted_l1_digest"),  # type: ignore[arg-type]
            candidate_l1_digest=value.get("candidate_l1_digest"),  # type: ignore[arg-type]
            prior_l1_unchanged=bool(value.get("prior_l1_unchanged")),
            policy_digest=value.get("policy_digest"),  # type: ignore[arg-type]
            field_changes=tuple(
                field_change_from_dict(item) for item in raw_changes
            ),
            check_receipts=tuple(
                ProverCheckReceipt.from_dict(item) for item in raw_checks
            ),
            proposal_id=value.get("proposal_id"),  # type: ignore[arg-type]
            rejection_reason=value.get("rejection_reason"),  # type: ignore[arg-type]
            detail=value.get("detail"),  # type: ignore[arg-type]
            semantic_authority=bool(value.get("semantic_authority", False)),
        )

    @classmethod
    def from_structural_admission(
        cls,
        result: StructuralAdmissionResult,
        *,
        proposal_id: str | None = None,
    ) -> "PlateauAdmissionReceipt":
        """Project a live StructuralAdmissionResult into a packet receipt."""

        if not isinstance(result, StructuralAdmissionResult):
            raise PlateauCodexPacketError(
                "expected StructuralAdmissionResult"
            )
        payload = result.to_dict()
        if payload.get("semantic_authority") is not False:
            raise PlateauCodexPacketError(
                "structural admission claimed semantic authority"
            )
        prior_digest = baseline_l1_digest(result.prior_l1)
        admitted_digest = baseline_l1_digest(result.admitted_l1)
        candidate_digest = (
            baseline_l1_digest(result.candidate_l1)
            if result.candidate_l1 is not None
            else None
        )
        checks = tuple(
            ProverCheckReceipt.from_admission_check(item)
            for item in result.check_receipts
        )
        return cls(
            disposition=result.disposition,
            prior_l1_digest=prior_digest,
            admitted_l1_digest=admitted_digest,
            candidate_l1_digest=candidate_digest,
            prior_l1_unchanged=result.prior_l1_unchanged,
            policy_digest=result.policy_digest,
            field_changes=tuple(result.field_changes),
            check_receipts=checks,
            proposal_id=proposal_id,
            rejection_reason=result.rejection_reason,
            detail=result.detail,
            semantic_authority=False,
        )


@dataclass(frozen=True, slots=True)
class ProofObligation:
    """Deterministic-code obligation minted from a failed structural gate.

    Rejected/timeout/error admissions produce obligations that the supervisor
    materializer surfaces as notes or follow-up edit tasks — never as
    silent merges of the rejected candidate.
    """

    obligation_id: str
    constraint: str
    disposition: str
    residual_ref_ids: tuple[str, ...] = ()
    proposal_id: str | None = None
    failed_field_paths: tuple[str, ...] = ()
    detail: str | None = None
    semantic_authority: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "obligation_id",
            _nonblank(self.obligation_id, "obligation_id"),
        )
        if not _OBLIGATION_ID_RE.match(self.obligation_id):
            raise PlateauCodexPacketError(
                f"obligation_id has invalid shape: {self.obligation_id!r}"
            )
        object.__setattr__(
            self, "constraint", _nonblank(self.constraint, "constraint")
        )
        disposition = _nonblank(self.disposition, "disposition").lower()
        allowed = {
            AdmissionDisposition.VALIDATOR_REJECT.value,
            AdmissionDisposition.TIMEOUT.value,
            AdmissionDisposition.ERROR.value,
            VALIDATOR_REJECT,
        }
        if disposition not in allowed:
            raise PlateauCodexPacketError(
                "proof obligation disposition must be reject/timeout/error; "
                f"got {disposition!r}"
            )
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(
            self,
            "residual_ref_ids",
            _string_tuple(
                self.residual_ref_ids, "residual_ref_ids", allow_empty=True
            ),
        )
        object.__setattr__(
            self,
            "proposal_id",
            _optional_nonblank(self.proposal_id, "proposal_id"),
        )
        object.__setattr__(
            self,
            "failed_field_paths",
            _string_tuple(
                self.failed_field_paths,
                "failed_field_paths",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self, "detail", _optional_nonblank(self.detail, "detail")
        )
        if self.semantic_authority is not False:
            raise PlateauCodexPacketError(
                "proof obligations cannot claim semantic authority"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "constraint": self.constraint,
            "detail": self.detail,
            "disposition": self.disposition,
            "failed_field_paths": list(self.failed_field_paths),
            "interface": PLATEAU_PROOF_OBLIGATION_INTERFACE,
            "obligation_id": self.obligation_id,
            "proposal_id": self.proposal_id,
            "residual_ref_ids": list(self.residual_ref_ids),
            "semantic_authority": False,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ProofObligation":
        if not isinstance(value, Mapping):
            raise PlateauCodexPacketError(
                "proof obligation must be an object"
            )
        return cls(
            obligation_id=value.get("obligation_id"),  # type: ignore[arg-type]
            constraint=value.get("constraint"),  # type: ignore[arg-type]
            disposition=value.get("disposition"),  # type: ignore[arg-type]
            residual_ref_ids=tuple(value.get("residual_ref_ids") or ()),  # type: ignore[arg-type]
            proposal_id=value.get("proposal_id"),  # type: ignore[arg-type]
            failed_field_paths=tuple(
                value.get("failed_field_paths") or ()
            ),  # type: ignore[arg-type]
            detail=value.get("detail"),  # type: ignore[arg-type]
            semantic_authority=bool(value.get("semantic_authority", False)),
        )


def mint_proof_obligations(
    admission: PlateauAdmissionReceipt | StructuralAdmissionResult,
    *,
    residual_ref_ids: Sequence[str] = (),
    proposal_id: str | None = None,
    packet_id: str = "packet",
) -> tuple[ProofObligation, ...]:
    """Mint proof obligations from a non-accepted admission.

    Accepted admissions mint no obligations.  Reject/timeout/error produce
    one obligation per failed declared constraint when identifiable, else a
    single disposition-level obligation.
    """

    if isinstance(admission, StructuralAdmissionResult):
        receipt = PlateauAdmissionReceipt.from_structural_admission(
            admission, proposal_id=proposal_id
        )
    elif isinstance(admission, PlateauAdmissionReceipt):
        receipt = admission
    else:
        raise PlateauCodexPacketError(
            "admission must be PlateauAdmissionReceipt or "
            "StructuralAdmissionResult"
        )

    if receipt.disposition is AdmissionDisposition.ACCEPTED:
        return ()
    if receipt.disposition is AdmissionDisposition.NOT_APPLICABLE:
        return ()

    residual_ids = _string_tuple(
        residual_ref_ids, "residual_ref_ids", allow_empty=True
    )
    failed_paths = tuple(
        field_change_path(change) for change in receipt.field_changes
    )
    disposition = receipt.disposition.value
    constraints: list[str] = []
    for check in receipt.check_receipts:
        if not check.passed or check.timed_out:
            constraints.extend(check.constraints)
    if not constraints and receipt.detail:
        # Local structural failures encode constraint tokens in detail.
        lowered = receipt.detail.lower()
        for name in DECLARED_STRUCTURAL_CONSTRAINTS:
            token = name.replace("_", " ")
            if name in lowered or token in lowered:
                constraints.append(name)
            elif name == "non_vacuous_candidate" and "vacuous" in lowered:
                constraints.append(name)
            elif (
                name == "rule_cardinality_preserved"
                and "cardinality" in lowered
            ):
                constraints.append(name)
            elif (
                name == "untriggered_projection_preserved"
                and "untriggered" in lowered
            ):
                constraints.append(name)
    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique_constraints: list[str] = []
    for item in constraints:
        if item not in seen:
            seen.add(item)
            unique_constraints.append(item)
    if not unique_constraints:
        unique_constraints = ["structural_admission_failed"]

    obligations: list[ProofObligation] = []
    for index, constraint in enumerate(unique_constraints):
        obligation_id = (
            f"PO-{packet_id}-{disposition}-{index}-{constraint}"[:128]
        )
        # Sanitize obligation id to the allowed charset.
        obligation_id = re.sub(r"[^A-Za-z0-9_.:-]", "-", obligation_id)
        obligations.append(
            ProofObligation(
                obligation_id=obligation_id,
                constraint=constraint,
                disposition=disposition,
                residual_ref_ids=residual_ids,
                proposal_id=proposal_id or receipt.proposal_id,
                failed_field_paths=failed_paths,
                detail=receipt.detail,
                semantic_authority=False,
            )
        )
    return tuple(obligations)


@dataclass(frozen=True, slots=True)
class PlateauCodexPacket:
    """Prover-gated Codex packet bound for agent-supervisor consumption.

    Required sealed fields:

    * ``baseline_l1`` / ``baseline_l1_digest`` — locked det. plateau L1;
    * ``residual_refs`` — residual catalog facet pointers;
    * ``proposals`` — teacher proposals (non-authoritative);
    * ``admission_receipts`` — structural admission results;
    * ``proof_obligation_ids`` / ``proof_obligations`` — mint from rejects;
    * ``predicted_files`` — det. compiler/realizer/test surface only;
    * ``validation_commands`` — re-run structural admit + packet tests;
    * ``implementable`` — true only when admission disposition is accepted.

    Content addressing: ``packet_digest`` is the SHA-256 of the canonical
    JSON payload with the digest field itself omitted.
    """

    packet_id: str
    baseline_l1: CanonicalRuleIR
    residual_refs: tuple[ResidualRef, ...]
    proposals: tuple[TeacherProposal, ...]
    admission_receipts: tuple[PlateauAdmissionReceipt, ...]
    proof_obligations: tuple[ProofObligation, ...]
    predicted_files: tuple[str, ...]
    validation_commands: tuple[str, ...]
    implementable: bool
    baseline_arm_id: str = DEFAULT_BASELINE_ARM_ID
    case_id: str | None = None
    admitted_field_changes: tuple[CanonicalFieldChange, ...] = ()
    detail: str | None = None
    baseline_e2e: float | None = DEFAULT_BASELINE_E2E
    # PLAT2-030 repair-development / holdout provenance bindings.
    bindings: PacketBindings | None = None
    invariant_context: InvariantContext | None = None
    expansion_handles: tuple[ExpansionHandle, ...] = ()
    omitted_handle_ids: tuple[str, ...] = ()
    omitted_handle_coverage: float | None = None
    token_count: int | None = None
    token_budget: int | None = None
    token_counting_method: str | None = None
    implementable_blockers: tuple[str, ...] = ()
    population_kind: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "packet_id", _nonblank(self.packet_id, "packet_id")
        )
        if not _PACKET_ID_RE.match(self.packet_id):
            raise PlateauCodexPacketError(
                f"packet_id has invalid shape: {self.packet_id!r}"
            )
        if not isinstance(self.baseline_l1, CanonicalRuleIR):
            raise PlateauCodexPacketError(
                "baseline_l1 must be CanonicalRuleIR"
            )
        object.__setattr__(
            self,
            "baseline_arm_id",
            _nonblank(self.baseline_arm_id, "baseline_arm_id"),
        )
        object.__setattr__(
            self, "residual_refs", tuple(self.residual_refs)
        )
        if not all(isinstance(item, ResidualRef) for item in self.residual_refs):
            raise PlateauCodexPacketError(
                "residual_refs must contain ResidualRef records"
            )
        residual_ids = [item.residual_id for item in self.residual_refs]
        if len(set(residual_ids)) != len(residual_ids):
            raise PlateauCodexPacketError(
                "residual_ref ids must be unique within a packet"
            )

        object.__setattr__(self, "proposals", tuple(self.proposals))
        if not all(
            isinstance(item, TeacherProposal) for item in self.proposals
        ):
            raise PlateauCodexPacketError(
                "proposals must contain TeacherProposal records"
            )
        proposal_ids = [item.proposal_id for item in self.proposals]
        if len(set(proposal_ids)) != len(proposal_ids):
            raise PlateauCodexPacketError(
                "proposal ids must be unique within a packet"
            )
        residual_id_set = set(residual_ids)
        for proposal in self.proposals:
            if proposal.semantic_authority is not False:
                raise PlateauCodexPacketError(
                    "proposal claimed semantic authority"
                )
            unknown = set(proposal.residual_ref_ids) - residual_id_set
            if unknown:
                raise PlateauCodexPacketError(
                    "proposal references unknown residual ids: "
                    + ", ".join(sorted(unknown))
                )

        object.__setattr__(
            self, "admission_receipts", tuple(self.admission_receipts)
        )
        if not all(
            isinstance(item, PlateauAdmissionReceipt)
            for item in self.admission_receipts
        ):
            raise PlateauCodexPacketError(
                "admission_receipts must contain PlateauAdmissionReceipt "
                "records"
            )
        if not self.admission_receipts:
            raise PlateauCodexPacketError(
                "packet requires at least one admission receipt"
            )
        for receipt in self.admission_receipts:
            if receipt.semantic_authority is not False:
                raise PlateauCodexPacketError(
                    "admission receipt claimed semantic authority"
                )
            for check in receipt.check_receipts:
                if check.semantic_authority is not False:
                    raise PlateauCodexPacketError(
                        "prover check claimed semantic authority"
                    )
            if (
                receipt.proposal_id is not None
                and receipt.proposal_id not in proposal_ids
                and proposal_ids
            ):
                raise PlateauCodexPacketError(
                    f"admission references unknown proposal_id "
                    f"{receipt.proposal_id!r}"
                )

        object.__setattr__(
            self, "proof_obligations", tuple(self.proof_obligations)
        )
        if not all(
            isinstance(item, ProofObligation)
            for item in self.proof_obligations
        ):
            raise PlateauCodexPacketError(
                "proof_obligations must contain ProofObligation records"
            )
        obligation_ids = [item.obligation_id for item in self.proof_obligations]
        if len(set(obligation_ids)) != len(obligation_ids):
            raise PlateauCodexPacketError(
                "proof_obligation ids must be unique within a packet"
            )
        for obligation in self.proof_obligations:
            if obligation.semantic_authority is not False:
                raise PlateauCodexPacketError(
                    "proof obligation claimed semantic authority"
                )

        predicted = tuple(
            _validate_predicted_file(path)
            for path in self.predicted_files
        )
        if not predicted:
            raise PlateauCodexPacketError(
                "predicted_files must be nonempty"
            )
        object.__setattr__(self, "predicted_files", predicted)

        commands = _string_tuple(
            self.validation_commands,
            "validation_commands",
            allow_empty=False,
            unique=False,
        )
        object.__setattr__(self, "validation_commands", commands)

        if not isinstance(self.implementable, bool):
            raise PlateauCodexPacketError("implementable must be boolean")

        object.__setattr__(
            self, "case_id", _optional_nonblank(self.case_id, "case_id")
        )
        object.__setattr__(
            self,
            "admitted_field_changes",
            tuple(self.admitted_field_changes),
        )
        if not all(
            isinstance(item, CanonicalFieldChange)
            for item in self.admitted_field_changes
        ):
            raise PlateauCodexPacketError(
                "admitted_field_changes must contain CanonicalFieldChange "
                "records"
            )
        object.__setattr__(
            self, "detail", _optional_nonblank(self.detail, "detail")
        )
        if self.baseline_e2e is not None:
            object.__setattr__(
                self,
                "baseline_e2e",
                _finite_nonneg(self.baseline_e2e, "baseline_e2e"),
            )

        if self.bindings is not None and not isinstance(
            self.bindings, PacketBindings
        ):
            raise PlateauCodexPacketError(
                "bindings must be PacketBindings or None"
            )
        if self.invariant_context is not None and not isinstance(
            self.invariant_context, InvariantContext
        ):
            raise PlateauCodexPacketError(
                "invariant_context must be InvariantContext or None"
            )
        object.__setattr__(
            self, "expansion_handles", tuple(self.expansion_handles)
        )
        if not all(
            isinstance(item, ExpansionHandle)
            for item in self.expansion_handles
        ):
            raise PlateauCodexPacketError(
                "expansion_handles must contain ExpansionHandle records"
            )
        object.__setattr__(
            self,
            "omitted_handle_ids",
            _string_tuple(
                self.omitted_handle_ids,
                "omitted_handle_ids",
                allow_empty=True,
            ),
        )
        if self.omitted_handle_coverage is not None:
            coverage = self.omitted_handle_coverage
            if (
                isinstance(coverage, bool)
                or not isinstance(coverage, (int, float))
                or not math.isfinite(float(coverage))
                or float(coverage) < 0.0
                or float(coverage) > 1.0
            ):
                raise PlateauCodexPacketError(
                    "omitted_handle_coverage must be in [0, 1]"
                )
            object.__setattr__(
                self, "omitted_handle_coverage", float(coverage)
            )
        if self.token_count is not None:
            if (
                isinstance(self.token_count, bool)
                or not isinstance(self.token_count, int)
                or self.token_count < 0
            ):
                raise PlateauCodexPacketError(
                    "token_count must be a nonnegative integer"
                )
        if self.token_budget is not None:
            if (
                isinstance(self.token_budget, bool)
                or not isinstance(self.token_budget, int)
                or self.token_budget <= 0
            ):
                raise PlateauCodexPacketError(
                    "token_budget must be a positive integer"
                )
        object.__setattr__(
            self,
            "token_counting_method",
            _optional_nonblank(
                self.token_counting_method, "token_counting_method"
            )
            if self.token_counting_method is not None
            else None,
        )
        object.__setattr__(
            self,
            "implementable_blockers",
            _string_tuple(
                self.implementable_blockers,
                "implementable_blockers",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "population_kind",
            _optional_nonblank(self.population_kind, "population_kind")
            if self.population_kind is not None
            else None,
        )
        if self.population_kind in BLIND_POPULATION_KINDS:
            raise PlateauCodexPacketError(
                "packets must not bind blind population_kind"
            )
        if self.bindings is not None:
            _assert_no_forbidden_content(
                self.bindings.to_dict(), path="bindings"
            )
        if self.invariant_context is not None:
            _assert_no_forbidden_content(
                self.invariant_context.to_dict(), path="invariant_context"
            )
        for handle in self.expansion_handles:
            _assert_no_forbidden_content(
                handle.to_dict(), path="expansion_handles"
            )

        self._assert_implementable_consistency()

    def _assert_implementable_consistency(self) -> None:
        accepted = [
            item
            for item in self.admission_receipts
            if item.disposition is AdmissionDisposition.ACCEPTED
        ]
        blocking = [
            item
            for item in self.admission_receipts
            if item.disposition
            in {
                AdmissionDisposition.VALIDATOR_REJECT,
                AdmissionDisposition.TIMEOUT,
                AdmissionDisposition.ERROR,
            }
        ]
        # Primary disposition: if any blocking disposition is present without
        # a separate accepted receipt for implementable authority, deny.
        # Packet-level implementable requires ≥1 accepted and is forbidden
        # when the governing admissions are exclusively non-accepted.
        if self.implementable:
            if not accepted:
                raise PlateauCodexPacketError(
                    "implementable=true requires at least one accepted "
                    "admission receipt"
                )
            # Explicit fail-closed: a packet that only records reject/timeout/
            # error cannot be implementable.  When mixed, accepted proposals
            # may still authorize implementable work; blocking ones contribute
            # obligations only.
            if not accepted and blocking:
                raise PlateauCodexPacketError(
                    "implementable=false required for reject/timeout/error"
                )
            if not self.admitted_field_changes:
                # Identity accepts are not useful implementable work.
                # Allow empty only if accepted field_changes on receipts are
                # also empty (identity) — still deny implementable.
                receipt_changes = sum(
                    (tuple(item.field_changes) for item in accepted),
                    (),
                )
                if not receipt_changes:
                    raise PlateauCodexPacketError(
                        "implementable=true requires admitted field changes"
                    )
                raise PlateauCodexPacketError(
                    "implementable packet must list admitted_field_changes"
                )
        else:
            # Non-implementable packets must not advertise admitted ΔL1 as
            # authorized edits.
            if self.admitted_field_changes and accepted:
                # Allowed: packet may carry admitted changes for audit while
                # still marking implementable=false only when no accepted?
                # Forbid advertising changes when no accept exists.
                pass
            if self.admitted_field_changes and not accepted:
                raise PlateauCodexPacketError(
                    "non-implementable packet without accepted admission "
                    "cannot list admitted_field_changes"
                )

        # Hard rule from acceptance criteria: reject/timeout/error alone
        # cannot yield implementable=true (covered above).  Additionally,
        # if *all* receipts are non-accepted, implementable must be false.
        if not accepted and self.implementable:
            raise PlateauCodexPacketError(
                "implementable=false when disposition is "
                "reject/timeout/error/not_applicable"
            )

        # Stale / unsupported / not_measured / missing evidence blockers.
        if self.implementable_blockers and self.implementable:
            raise PlateauCodexPacketError(
                "implementable=false required when implementable_blockers "
                "are present: " + ", ".join(self.implementable_blockers)
            )
        if self.bindings is not None:
            if (
                self.bindings.evidence_status
                in NON_IMPLEMENTABLE_EVIDENCE_STATUSES
                and self.implementable
            ):
                raise PlateauCodexPacketError(
                    "implementable=false when evidence_status is "
                    f"{self.bindings.evidence_status}"
                )

        # baseline digest cross-check against admission prior digests when present
        baseline_digest = self.baseline_l1_digest
        for receipt in self.admission_receipts:
            if receipt.prior_l1_digest != baseline_digest:
                raise PlateauCodexPacketError(
                    "admission prior_l1_digest must match packet "
                    "baseline_l1_digest"
                )

    @property
    def baseline_l1_digest(self) -> str:
        return baseline_l1_digest(self.baseline_l1)

    @property
    def proof_obligation_ids(self) -> tuple[str, ...]:
        return tuple(item.obligation_id for item in self.proof_obligations)

    @property
    def primary_disposition(self) -> AdmissionDisposition:
        """Governing disposition for supervisor routing.

        Prefer accepted when present; otherwise the first non-accepted
        disposition (reject/timeout/error before not_applicable).
        """

        for item in self.admission_receipts:
            if item.disposition is AdmissionDisposition.ACCEPTED:
                return AdmissionDisposition.ACCEPTED
        priority = (
            AdmissionDisposition.ERROR,
            AdmissionDisposition.TIMEOUT,
            AdmissionDisposition.VALIDATOR_REJECT,
            AdmissionDisposition.NOT_APPLICABLE,
        )
        present = {item.disposition for item in self.admission_receipts}
        for disposition in priority:
            if disposition in present:
                return disposition
        return self.admission_receipts[0].disposition

    def payload_for_digest(self) -> dict[str, object]:
        """Canonical payload used for content addressing (no digest field)."""

        return {
            "admission_receipts": [
                item.to_dict() for item in self.admission_receipts
            ],
            "admitted_field_changes": [
                item.to_dict() for item in self.admitted_field_changes
            ],
            "baseline_arm_id": self.baseline_arm_id,
            "baseline_e2e": self.baseline_e2e,
            "baseline_l1": self.baseline_l1.to_dict(),
            "baseline_l1_digest": self.baseline_l1_digest,
            "bindings": (
                self.bindings.to_dict() if self.bindings is not None else None
            ),
            "case_id": self.case_id,
            "detail": self.detail,
            "evidence": PLATEAU_CODEX_PACKET_EVIDENCE,
            "expansion_handles": [
                item.to_dict() for item in self.expansion_handles
            ],
            "implementable": self.implementable,
            "implementable_blockers": list(self.implementable_blockers),
            "interface": PLATEAU_CODEX_PACKET_INTERFACE,
            "invariant_context": (
                self.invariant_context.to_dict()
                if self.invariant_context is not None
                else None
            ),
            "omitted_handle_coverage": self.omitted_handle_coverage,
            "omitted_handle_ids": list(self.omitted_handle_ids),
            "packet_id": self.packet_id,
            "population_kind": self.population_kind,
            "predicted_files": list(self.predicted_files),
            "primary_disposition": self.primary_disposition.value,
            "proof_obligation_ids": list(self.proof_obligation_ids),
            "proof_obligations": [
                item.to_dict() for item in self.proof_obligations
            ],
            "proposals": [item.to_dict() for item in self.proposals],
            "residual_refs": [item.to_dict() for item in self.residual_refs],
            "schema": PLATEAU_CODEX_PACKET_SCHEMA,
            "semantic_authority": False,
            "token_budget": self.token_budget,
            "token_count": self.token_count,
            "token_counting_method": self.token_counting_method,
            "validation_commands": list(self.validation_commands),
        }

    @property
    def packet_digest(self) -> str:
        return _sha(self.payload_for_digest())

    def to_dict(self) -> dict[str, object]:
        payload = self.payload_for_digest()
        payload["packet_digest"] = self.packet_digest
        return payload

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> "PlateauCodexPacket":
        if not isinstance(value, Mapping):
            raise PlateauCodexPacketError("packet must be an object")
        interface = value.get("interface")
        if interface is not None and interface != PLATEAU_CODEX_PACKET_INTERFACE:
            raise PlateauCodexPacketError(
                f"unexpected packet interface: {interface!r}"
            )
        schema = value.get("schema")
        if schema is not None and schema != PLATEAU_CODEX_PACKET_SCHEMA:
            raise PlateauCodexPacketError(
                f"unexpected packet schema: {schema!r}"
            )

        residual_raw = value.get("residual_refs") or ()
        proposals_raw = value.get("proposals") or ()
        admissions_raw = value.get("admission_receipts") or ()
        obligations_raw = value.get("proof_obligations") or ()
        admitted_raw = value.get("admitted_field_changes") or ()
        expansion_raw = value.get("expansion_handles") or ()
        for name, raw in (
            ("residual_refs", residual_raw),
            ("proposals", proposals_raw),
            ("admission_receipts", admissions_raw),
            ("proof_obligations", obligations_raw),
            ("admitted_field_changes", admitted_raw),
            ("expansion_handles", expansion_raw),
        ):
            if (
                not isinstance(raw, Sequence)
                or isinstance(raw, (str, bytes, bytearray))
            ):
                raise PlateauCodexPacketError(f"{name} must be an array")

        bindings_raw = value.get("bindings")
        bindings = (
            PacketBindings.from_dict(bindings_raw)
            if bindings_raw is not None
            else None
        )
        invariant_raw = value.get("invariant_context")
        invariant_context = (
            InvariantContext.from_dict(invariant_raw)
            if invariant_raw is not None
            else None
        )

        packet = cls(
            packet_id=value.get("packet_id"),  # type: ignore[arg-type]
            baseline_l1=CanonicalRuleIR.from_dict(value.get("baseline_l1")),
            residual_refs=tuple(
                ResidualRef.from_dict(item) for item in residual_raw
            ),
            proposals=tuple(
                TeacherProposal.from_dict(item) for item in proposals_raw
            ),
            admission_receipts=tuple(
                PlateauAdmissionReceipt.from_dict(item)
                for item in admissions_raw
            ),
            proof_obligations=tuple(
                ProofObligation.from_dict(item) for item in obligations_raw
            ),
            predicted_files=tuple(value.get("predicted_files") or ()),  # type: ignore[arg-type]
            validation_commands=tuple(
                value.get("validation_commands") or ()
            ),  # type: ignore[arg-type]
            implementable=bool(value.get("implementable")),
            baseline_arm_id=value.get(
                "baseline_arm_id", DEFAULT_BASELINE_ARM_ID
            ),  # type: ignore[arg-type]
            case_id=value.get("case_id"),  # type: ignore[arg-type]
            admitted_field_changes=tuple(
                field_change_from_dict(item) for item in admitted_raw
            ),
            detail=value.get("detail"),  # type: ignore[arg-type]
            baseline_e2e=value.get("baseline_e2e", DEFAULT_BASELINE_E2E),  # type: ignore[arg-type]
            bindings=bindings,
            invariant_context=invariant_context,
            expansion_handles=tuple(
                ExpansionHandle.from_dict(item) for item in expansion_raw
            ),
            omitted_handle_ids=tuple(
                value.get("omitted_handle_ids") or ()
            ),  # type: ignore[arg-type]
            omitted_handle_coverage=value.get(
                "omitted_handle_coverage"
            ),  # type: ignore[arg-type]
            token_count=value.get("token_count"),  # type: ignore[arg-type]
            token_budget=value.get("token_budget"),  # type: ignore[arg-type]
            token_counting_method=value.get(
                "token_counting_method"
            ),  # type: ignore[arg-type]
            implementable_blockers=tuple(
                value.get("implementable_blockers") or ()
            ),  # type: ignore[arg-type]
            population_kind=value.get("population_kind"),  # type: ignore[arg-type]
        )

        sealed_digest = value.get("packet_digest")
        if sealed_digest is not None:
            sealed = _nonblank(sealed_digest, "packet_digest")
            if sealed != packet.packet_digest:
                raise PlateauCodexPacketError(
                    "packet_digest mismatch: content-address integrity failed"
                )
        sealed_baseline = value.get("baseline_l1_digest")
        if sealed_baseline is not None:
            sealed_b = _nonblank(sealed_baseline, "baseline_l1_digest")
            if sealed_b != packet.baseline_l1_digest:
                raise PlateauCodexPacketError(
                    "baseline_l1_digest mismatch"
                )
        sealed_obligation_ids = value.get("proof_obligation_ids")
        if sealed_obligation_ids is not None:
            if list(sealed_obligation_ids) != list(packet.proof_obligation_ids):
                raise PlateauCodexPacketError(
                    "proof_obligation_ids must match proof_obligations"
                )
        return packet

    @classmethod
    def from_json(cls, text: str) -> "PlateauCodexPacket":
        if not isinstance(text, str) or not text.strip():
            raise PlateauCodexPacketError("packet JSON must be nonblank")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PlateauCodexPacketError(
                f"packet JSON is invalid: {exc}"
            ) from exc
        return cls.from_dict(payload)


def build_plateau_codex_packet(
    *,
    packet_id: str,
    baseline_l1: CanonicalRuleIR,
    residual_refs: Sequence[ResidualRef],
    proposals: Sequence[TeacherProposal],
    admission_results: Sequence[
        StructuralAdmissionResult | PlateauAdmissionReceipt
    ],
    predicted_files: Sequence[str] | None = None,
    validation_commands: Sequence[str] | None = None,
    baseline_arm_id: str = DEFAULT_BASELINE_ARM_ID,
    case_id: str | None = None,
    detail: str | None = None,
    baseline_e2e: float | None = DEFAULT_BASELINE_E2E,
    proposal_ids_for_admissions: Sequence[str | None] | None = None,
    bindings: PacketBindings | None = None,
    invariant_context: InvariantContext | None = None,
    expansion_handles: Sequence[ExpansionHandle] | None = None,
    omitted_handle_ids: Sequence[str] | None = None,
    omitted_handle_coverage: float | None = None,
    token_count: int | None = None,
    token_budget: int | None = None,
    token_counting_method: str | None = None,
    population_kind: str | None = None,
    require_repair_dev_evidence: bool = False,
    expected_bindings: PacketBindings | None = None,
    auto_invariant_context: bool = False,
    auto_token_metrics: bool = False,
) -> PlateauCodexPacket:
    """Build a sealed packet from residuals, proposals, and admissions.

    ``implementable`` is derived fail-closed:

    * true only when at least one admission is ``accepted`` and yields
      nonempty admitted field changes;
    * false for reject / timeout / error / not_applicable governing paths;
    * false for stale bindings, unsupported/not_measured evidence, or
      missing required repair-development evidence.
    """

    if not isinstance(baseline_l1, CanonicalRuleIR):
        raise PlateauCodexPacketError("baseline_l1 must be CanonicalRuleIR")
    residual_tuple = tuple(residual_refs)
    proposal_tuple = tuple(proposals)
    if not admission_results:
        raise PlateauCodexPacketError(
            "admission_results must be nonempty"
        )

    proposal_id_hints: list[str | None]
    if proposal_ids_for_admissions is None:
        # Pair admissions to proposals by index when lengths match.
        if len(admission_results) == len(proposal_tuple):
            proposal_id_hints = [item.proposal_id for item in proposal_tuple]
        elif len(proposal_tuple) == 1:
            proposal_id_hints = [proposal_tuple[0].proposal_id] * len(
                admission_results
            )
        else:
            proposal_id_hints = [None] * len(admission_results)
    else:
        proposal_id_hints = list(proposal_ids_for_admissions)
        if len(proposal_id_hints) != len(admission_results):
            raise PlateauCodexPacketError(
                "proposal_ids_for_admissions length must match "
                "admission_results"
            )

    receipts: list[PlateauAdmissionReceipt] = []
    for index, result in enumerate(admission_results):
        hint = proposal_id_hints[index]
        if isinstance(result, PlateauAdmissionReceipt):
            if hint is not None and result.proposal_id is None:
                receipts.append(
                    PlateauAdmissionReceipt(
                        disposition=result.disposition,
                        prior_l1_digest=result.prior_l1_digest,
                        admitted_l1_digest=result.admitted_l1_digest,
                        candidate_l1_digest=result.candidate_l1_digest,
                        prior_l1_unchanged=result.prior_l1_unchanged,
                        policy_digest=result.policy_digest,
                        field_changes=result.field_changes,
                        check_receipts=result.check_receipts,
                        proposal_id=hint,
                        rejection_reason=result.rejection_reason,
                        detail=result.detail,
                        semantic_authority=False,
                    )
                )
            else:
                receipts.append(result)
        elif isinstance(result, StructuralAdmissionResult):
            receipts.append(
                PlateauAdmissionReceipt.from_structural_admission(
                    result, proposal_id=hint
                )
            )
        else:
            raise PlateauCodexPacketError(
                "admission_results must contain StructuralAdmissionResult "
                "or PlateauAdmissionReceipt records"
            )

    residual_ids = [item.residual_id for item in residual_tuple]
    obligations: list[ProofObligation] = []
    for receipt in receipts:
        linked_residual_ids: list[str] = list(residual_ids)
        if receipt.proposal_id:
            for proposal in proposal_tuple:
                if proposal.proposal_id == receipt.proposal_id:
                    linked_residual_ids = list(proposal.residual_ref_ids) or list(
                        residual_ids
                    )
                    break
        obligations.extend(
            mint_proof_obligations(
                receipt,
                residual_ref_ids=linked_residual_ids,
                proposal_id=receipt.proposal_id,
                packet_id=packet_id,
            )
        )

    accepted_receipts = [
        item
        for item in receipts
        if item.disposition is AdmissionDisposition.ACCEPTED
    ]
    admitted_changes: list[CanonicalFieldChange] = []
    for receipt in accepted_receipts:
        for change in receipt.field_changes:
            admitted_changes.append(change)
    # De-dupe by path+before+after while preserving order.
    seen_keys: set[tuple[object, ...]] = set()
    unique_changes: list[CanonicalFieldChange] = []
    for change in admitted_changes:
        key = (
            change.canonical_field,
            change.baseline_rule_index,
            change.guided_rule_index,
            json.dumps(change.before, sort_keys=True, default=str),
            json.dumps(change.after, sort_keys=True, default=str),
        )
        if key not in seen_keys:
            seen_keys.add(key)
            unique_changes.append(change)

    implementable = bool(accepted_receipts) and bool(unique_changes)
    # Fail-closed: if every receipt is reject/timeout/error, force false.
    if not accepted_receipts:
        implementable = False
    if any(
        item.disposition
        in {
            AdmissionDisposition.VALIDATOR_REJECT,
            AdmissionDisposition.TIMEOUT,
            AdmissionDisposition.ERROR,
        }
        for item in receipts
    ) and not accepted_receipts:
        implementable = False

    files = tuple(predicted_files) if predicted_files is not None else DEFAULT_PREDICTED_FILES
    commands = (
        tuple(validation_commands)
        if validation_commands is not None
        else DEFAULT_VALIDATION_COMMANDS
    )

    active_bindings = bindings
    if active_bindings is not None:
        active_bindings = active_bindings.with_structural_obligation_ids(
            [item.obligation_id for item in obligations]
        )

    active_invariant = invariant_context
    if active_invariant is None and auto_invariant_context:
        active_invariant = build_invariant_context(
            residual_refs=residual_tuple,
            admission_receipts=tuple(receipts),
            admitted_field_changes=tuple(unique_changes),
            baseline_l1_digest=baseline_l1_digest(baseline_l1),
        )

    handle_tuple = (
        tuple(expansion_handles) if expansion_handles is not None else ()
    )
    omitted_ids = (
        tuple(omitted_handle_ids) if omitted_handle_ids is not None else ()
    )
    active_token_budget = (
        int(token_budget) if token_budget is not None else None
    )
    active_token_count = token_count
    active_token_method = token_counting_method
    active_coverage = omitted_handle_coverage

    if auto_token_metrics:
        active_token_budget = (
            PACKET_TOKEN_BUDGET
            if active_token_budget is None
            else active_token_budget
        )
        active_token_method = (
            PACKET_TOKEN_COUNTING_METHOD
            if active_token_method is None
            else active_token_method
        )
        # Provisional payload without token fields for counting.
        provisional = {
            "admission_receipts": [item.to_dict() for item in receipts],
            "admitted_field_changes": [
                item.to_dict() for item in unique_changes
            ],
            "baseline_arm_id": baseline_arm_id,
            "baseline_e2e": baseline_e2e,
            "baseline_l1": baseline_l1.to_dict(),
            "bindings": (
                active_bindings.to_dict()
                if active_bindings is not None
                else None
            ),
            "case_id": case_id,
            "detail": detail,
            "expansion_handles": [
                item.to_dict() for item in handle_tuple if item.included
            ],
            "invariant_context": (
                active_invariant.to_dict()
                if active_invariant is not None
                else None
            ),
            "packet_id": packet_id,
            "population_kind": population_kind,
            "predicted_files": list(files),
            "proof_obligations": [item.to_dict() for item in obligations],
            "proposals": [item.to_dict() for item in proposal_tuple],
            "residual_refs": [item.to_dict() for item in residual_tuple],
            "validation_commands": list(commands),
        }
        active_token_count = count_tokens_whitespace_proxy(provisional)
        if active_coverage is None:
            total_handles = len(handle_tuple)
            active_coverage = 1.0 if total_handles == 0 else 1.0
        if not omitted_ids:
            omitted_ids = tuple(
                item.handle_id
                for item in handle_tuple
                if not item.included
            )

    blockers = compute_implementable_blockers(
        admission_receipts=tuple(receipts),
        admitted_field_changes=tuple(unique_changes),
        bindings=active_bindings,
        invariant_context=active_invariant,
        require_repair_dev_evidence=require_repair_dev_evidence,
        expected_bindings=expected_bindings,
        omitted_handle_coverage=active_coverage,
        token_count=active_token_count,
        token_budget=active_token_budget,
    )
    if blockers:
        implementable = False

    return PlateauCodexPacket(
        packet_id=packet_id,
        baseline_l1=baseline_l1,
        residual_refs=residual_tuple,
        proposals=proposal_tuple,
        admission_receipts=tuple(receipts),
        proof_obligations=tuple(obligations),
        predicted_files=files,
        validation_commands=commands,
        implementable=implementable,
        baseline_arm_id=baseline_arm_id,
        case_id=case_id,
        admitted_field_changes=tuple(unique_changes) if implementable else (),
        detail=detail,
        baseline_e2e=baseline_e2e,
        bindings=active_bindings,
        invariant_context=active_invariant,
        expansion_handles=handle_tuple,
        omitted_handle_ids=omitted_ids,
        omitted_handle_coverage=active_coverage,
        token_count=active_token_count,
        token_budget=active_token_budget,
        token_counting_method=active_token_method,
        implementable_blockers=blockers,
        population_kind=population_kind,
    )


def build_packet_from_proposal_admission(
    *,
    packet_id: str,
    baseline_l1: CanonicalRuleIR,
    residual_ref: ResidualRef,
    proposal: TeacherProposal,
    admission: StructuralAdmissionResult,
    predicted_files: Sequence[str] | None = None,
    validation_commands: Sequence[str] | None = None,
    case_id: str | None = None,
    detail: str | None = None,
) -> PlateauCodexPacket:
    """Convenience builder for the common single-proposal admission path.

    When the proposal lacks field_changes but carries a candidate L1, fill
    field_changes from the canonical diff so admission receipts stay aligned.
    """

    if not isinstance(admission, StructuralAdmissionResult):
        raise PlateauCodexPacketError(
            "admission must be StructuralAdmissionResult"
        )
    active_proposal = proposal
    if (
        not proposal.field_changes
        and proposal.candidate_l1 is not None
        and proposal.candidate_l1 != baseline_l1
    ):
        changes = canonical_field_changes(baseline_l1, proposal.candidate_l1)
        active_proposal = TeacherProposal(
            proposal_id=proposal.proposal_id,
            teacher=proposal.teacher,
            residual_ref_ids=proposal.residual_ref_ids
            or (residual_ref.residual_id,),
            allowed_field_paths=proposal.allowed_field_paths,
            candidate_l1=proposal.candidate_l1,
            field_changes=changes,
            detail=proposal.detail,
            semantic_authority=False,
        )
    elif not proposal.residual_ref_ids:
        active_proposal = TeacherProposal(
            proposal_id=proposal.proposal_id,
            teacher=proposal.teacher,
            residual_ref_ids=(residual_ref.residual_id,),
            allowed_field_paths=proposal.allowed_field_paths,
            candidate_l1=proposal.candidate_l1,
            field_changes=proposal.field_changes,
            detail=proposal.detail,
            semantic_authority=False,
        )

    return build_plateau_codex_packet(
        packet_id=packet_id,
        baseline_l1=baseline_l1,
        residual_refs=(residual_ref,),
        proposals=(active_proposal,),
        admission_results=(admission,),
        predicted_files=predicted_files,
        validation_commands=validation_commands,
        case_id=case_id or residual_ref.case_id,
        detail=detail,
        proposal_ids_for_admissions=(active_proposal.proposal_id,),
    )


def build_holdout_codex_packet(
    *,
    packet_id: str,
    baseline_l1: CanonicalRuleIR,
    residual_refs: Sequence[ResidualRef],
    proposals: Sequence[TeacherProposal],
    admission_results: Sequence[
        StructuralAdmissionResult | PlateauAdmissionReceipt
    ],
    predicted_files: Sequence[str] | None = None,
    validation_commands: Sequence[str] | None = None,
    baseline_arm_id: str = DEFAULT_BASELINE_ARM_ID,
    case_id: str | None = None,
    detail: str | None = None,
    baseline_e2e: float | None = HOLDOUT_BASELINE_E2E,
    proposal_ids_for_admissions: Sequence[str | None] | None = None,
    bindings: PacketBindings | None = None,
    invariant_context: InvariantContext | None = None,
    expansion_handles: Sequence[ExpansionHandle] | None = None,
) -> PlateauCodexPacket:
    """Build a sealed PlateauCodexPacket@1 for a transitional **holdout** residual.

    Same fail-closed implementable rules as :func:`build_plateau_codex_packet`.
    Prefer :func:`build_repair_dev_codex_packet` for the normative PLAT2-030
    repair-development population.
    """

    if not residual_refs:
        raise PlateauCodexPacketError(
            "holdout packet requires at least one residual_ref"
        )
    files = (
        tuple(predicted_files)
        if predicted_files is not None
        else DEFAULT_PREDICTED_FILES
    )
    commands = (
        tuple(validation_commands)
        if validation_commands is not None
        else DEFAULT_HOLDOUT_VALIDATION_COMMANDS
    )
    resolved_case = case_id
    if resolved_case is None and len({ref.case_id for ref in residual_refs}) == 1:
        resolved_case = residual_refs[0].case_id
    holdout_detail = detail
    if holdout_detail is None:
        holdout_detail = (
            f"holdout residual packet ({HOLDOUT_POPULATION_KIND})"
        )
    elif HOLDOUT_POPULATION_KIND not in holdout_detail.lower():
        holdout_detail = f"{holdout_detail} [holdout]"

    return build_plateau_codex_packet(
        packet_id=packet_id,
        baseline_l1=baseline_l1,
        residual_refs=residual_refs,
        proposals=proposals,
        admission_results=admission_results,
        predicted_files=files,
        validation_commands=commands,
        baseline_arm_id=baseline_arm_id,
        case_id=resolved_case,
        detail=holdout_detail,
        baseline_e2e=baseline_e2e,
        proposal_ids_for_admissions=proposal_ids_for_admissions,
        bindings=bindings,
        invariant_context=invariant_context,
        expansion_handles=expansion_handles,
        population_kind=HOLDOUT_POPULATION_KIND,
        auto_invariant_context=invariant_context is None,
        auto_token_metrics=True,
    )


def build_holdout_packet_from_proposal_admission(
    *,
    packet_id: str,
    baseline_l1: CanonicalRuleIR,
    residual_ref: ResidualRef,
    proposal: TeacherProposal,
    admission: StructuralAdmissionResult,
    predicted_files: Sequence[str] | None = None,
    validation_commands: Sequence[str] | None = None,
    case_id: str | None = None,
    detail: str | None = None,
    baseline_e2e: float | None = HOLDOUT_BASELINE_E2E,
) -> PlateauCodexPacket:
    """Holdout convenience builder for the single-proposal admission path.

    Reject / timeout / error admissions produce ``implementable=false`` packets
    with minted proof obligations (same fail-closed contract as pilot).
    """

    # Reuse the pilot convenience path for field-change alignment, then rebuild
    # with holdout defaults so baseline_e2e / validation_commands stick.
    intermediate = build_packet_from_proposal_admission(
        packet_id=packet_id,
        baseline_l1=baseline_l1,
        residual_ref=residual_ref,
        proposal=proposal,
        admission=admission,
        predicted_files=predicted_files,
        validation_commands=validation_commands
        if validation_commands is not None
        else DEFAULT_HOLDOUT_VALIDATION_COMMANDS,
        case_id=case_id,
        detail=detail,
    )
    # Rebuild to force holdout baseline_e2e when the intermediate used pilot
    # DEFAULT_BASELINE_E2E via build_plateau_codex_packet defaults.
    return build_holdout_codex_packet(
        packet_id=intermediate.packet_id,
        baseline_l1=intermediate.baseline_l1,
        residual_refs=intermediate.residual_refs,
        proposals=intermediate.proposals,
        admission_results=intermediate.admission_receipts,
        predicted_files=intermediate.predicted_files,
        validation_commands=intermediate.validation_commands,
        baseline_arm_id=intermediate.baseline_arm_id,
        case_id=intermediate.case_id,
        detail=intermediate.detail,
        baseline_e2e=baseline_e2e,
        proposal_ids_for_admissions=tuple(
            item.proposal_id for item in intermediate.admission_receipts
        ),
    )


def build_holdout_packets_from_residual_catalog(
    catalog: Mapping[str, object],
    *,
    baseline_l1_by_case: Mapping[str, CanonicalRuleIR],
    proposals_by_case: Mapping[str, TeacherProposal | Sequence[TeacherProposal]],
    admissions_by_case: Mapping[
        str,
        StructuralAdmissionResult
        | PlateauAdmissionReceipt
        | Sequence[StructuralAdmissionResult | PlateauAdmissionReceipt],
    ],
    case_ids: Sequence[str] | None = None,
    predicted_files: Sequence[str] | None = None,
    validation_commands: Sequence[str] | None = None,
    packet_id_prefix: str = "holdout-pkt",
) -> tuple[PlateauCodexPacket, ...]:
    """Build one holdout packet per case that has residual refs + admissions.

    Cases without residuals, proposals, or admissions are skipped (not
    implementable work).  Each packet uses det.-only predicted files and
    holdout validation commands by default.
    """

    refs = residual_refs_from_catalog(
        catalog, case_ids=case_ids, nonzero_only=True
    )
    by_case: dict[str, list[ResidualRef]] = {}
    for ref in refs:
        by_case.setdefault(ref.case_id, []).append(ref)

    packets: list[PlateauCodexPacket] = []
    for case_id, case_refs in by_case.items():
        if case_id not in baseline_l1_by_case:
            raise PlateauCodexPacketError(
                f"missing baseline_l1 for holdout case {case_id!r}"
            )
        if case_id not in proposals_by_case:
            continue
        if case_id not in admissions_by_case:
            continue
        baseline = baseline_l1_by_case[case_id]
        raw_proposals = proposals_by_case[case_id]
        if isinstance(raw_proposals, TeacherProposal):
            proposal_seq: tuple[TeacherProposal, ...] = (raw_proposals,)
        else:
            proposal_seq = tuple(raw_proposals)
        raw_admissions = admissions_by_case[case_id]
        if isinstance(
            raw_admissions, (StructuralAdmissionResult, PlateauAdmissionReceipt)
        ):
            admission_seq: tuple[
                StructuralAdmissionResult | PlateauAdmissionReceipt, ...
            ] = (raw_admissions,)
        else:
            admission_seq = tuple(raw_admissions)
        if not proposal_seq or not admission_seq:
            continue
        # Align proposal residual_ref_ids to this case's refs when empty.
        aligned: list[TeacherProposal] = []
        for proposal in proposal_seq:
            if proposal.residual_ref_ids:
                aligned.append(proposal)
            else:
                aligned.append(
                    TeacherProposal(
                        proposal_id=proposal.proposal_id,
                        teacher=proposal.teacher,
                        residual_ref_ids=tuple(
                            ref.residual_id for ref in case_refs
                        ),
                        allowed_field_paths=proposal.allowed_field_paths,
                        candidate_l1=proposal.candidate_l1,
                        field_changes=proposal.field_changes,
                        detail=proposal.detail,
                        semantic_authority=False,
                    )
                )
        packet = build_holdout_codex_packet(
            packet_id=f"{packet_id_prefix}-{case_id}",
            baseline_l1=baseline,
            residual_refs=tuple(case_refs),
            proposals=tuple(aligned),
            admission_results=admission_seq,
            predicted_files=predicted_files,
            validation_commands=validation_commands,
            case_id=case_id,
            detail=f"holdout residual packet for {case_id}",
        )
        packets.append(packet)
    return tuple(packets)


def build_repair_dev_codex_packet(
    *,
    packet_id: str,
    baseline_l1: CanonicalRuleIR,
    residual_refs: Sequence[ResidualRef],
    proposals: Sequence[TeacherProposal],
    admission_results: Sequence[
        StructuralAdmissionResult | PlateauAdmissionReceipt
    ],
    predicted_files: Sequence[str] | None = None,
    validation_commands: Sequence[str] | None = None,
    baseline_arm_id: str = DEFAULT_BASELINE_ARM_ID,
    case_id: str | None = None,
    detail: str | None = None,
    baseline_e2e: float | None = REPAIR_DEV_BASELINE_E2E,
    proposal_ids_for_admissions: Sequence[str | None] | None = None,
    bindings: PacketBindings | None = None,
    invariant_context: InvariantContext | None = None,
    expansion_handles: Sequence[ExpansionHandle] | None = None,
    catalog: Mapping[str, object] | None = None,
    acceptance_ids: Sequence[str] | None = None,
    require_repair_dev_evidence: bool = True,
) -> PlateauCodexPacket:
    """Build a sealed PlateauCodexPacket@1 for a **repair-development** residual.

    Accepts repair-development residuals only (when *catalog* is provided).
    Binds baseline/tree/population/catalog CIDs, residual facets, assumptions,
    evidence status, structural-obligation IDs, invalidators, acceptance IDs,
    provenance, invariant context, and token-budget metrics.
    """

    if not residual_refs:
        raise PlateauCodexPacketError(
            "repair-development packet requires at least one residual_ref"
        )

    expected_bindings: PacketBindings | None = None
    active_bindings = bindings
    if catalog is not None:
        assert_catalog_allowed_for_packets(
            catalog,
            allowed_population_kinds=(REPAIR_DEV_POPULATION_KIND,),
        )
        resolved_case = case_id
        if (
            resolved_case is None
            and len({ref.case_id for ref in residual_refs}) == 1
        ):
            resolved_case = residual_refs[0].case_id
        expected_bindings = extract_catalog_bindings(
            catalog,
            case_id=resolved_case,
            acceptance_ids=acceptance_ids,
        )
        if active_bindings is None:
            active_bindings = expected_bindings
        elif acceptance_ids and not active_bindings.acceptance_ids:
            active_bindings = PacketBindings(
                baseline_cid=active_bindings.baseline_cid,
                tree_cid=active_bindings.tree_cid,
                population_cid=active_bindings.population_cid,
                catalog_cid=active_bindings.catalog_cid,
                population_kind=active_bindings.population_kind,
                assumptions=active_bindings.assumptions,
                evidence_status=active_bindings.evidence_status,
                structural_obligation_ids=(
                    active_bindings.structural_obligation_ids
                ),
                invalidators=active_bindings.invalidators,
                acceptance_ids=tuple(acceptance_ids),
                provenance=dict(active_bindings.provenance),
            )

    files = (
        tuple(predicted_files)
        if predicted_files is not None
        else DEFAULT_PREDICTED_FILES
    )
    commands = (
        tuple(validation_commands)
        if validation_commands is not None
        else DEFAULT_REPAIR_DEV_VALIDATION_COMMANDS
    )
    resolved_case = case_id
    if resolved_case is None and len({ref.case_id for ref in residual_refs}) == 1:
        resolved_case = residual_refs[0].case_id
    repair_detail = detail
    if repair_detail is None:
        repair_detail = (
            f"repair_development residual packet "
            f"({REPAIR_DEV_POPULATION_KIND})"
        )
    elif REPAIR_DEV_POPULATION_KIND not in repair_detail.lower():
        repair_detail = f"{repair_detail} [repair_development]"

    return build_plateau_codex_packet(
        packet_id=packet_id,
        baseline_l1=baseline_l1,
        residual_refs=residual_refs,
        proposals=proposals,
        admission_results=admission_results,
        predicted_files=files,
        validation_commands=commands,
        baseline_arm_id=baseline_arm_id,
        case_id=resolved_case,
        detail=repair_detail,
        baseline_e2e=baseline_e2e,
        proposal_ids_for_admissions=proposal_ids_for_admissions,
        bindings=active_bindings,
        invariant_context=invariant_context,
        expansion_handles=expansion_handles,
        population_kind=REPAIR_DEV_POPULATION_KIND,
        require_repair_dev_evidence=require_repair_dev_evidence,
        expected_bindings=expected_bindings,
        auto_invariant_context=invariant_context is None,
        auto_token_metrics=True,
    )


def build_repair_dev_packet_from_proposal_admission(
    *,
    packet_id: str,
    baseline_l1: CanonicalRuleIR,
    residual_ref: ResidualRef,
    proposal: TeacherProposal,
    admission: StructuralAdmissionResult,
    predicted_files: Sequence[str] | None = None,
    validation_commands: Sequence[str] | None = None,
    case_id: str | None = None,
    detail: str | None = None,
    baseline_e2e: float | None = REPAIR_DEV_BASELINE_E2E,
    bindings: PacketBindings | None = None,
    catalog: Mapping[str, object] | None = None,
    acceptance_ids: Sequence[str] | None = None,
    expansion_handles: Sequence[ExpansionHandle] | None = None,
    require_repair_dev_evidence: bool = True,
) -> PlateauCodexPacket:
    """Repair-development convenience builder for single-proposal admission."""

    if not isinstance(admission, StructuralAdmissionResult):
        raise PlateauCodexPacketError(
            "admission must be StructuralAdmissionResult"
        )
    intermediate = build_packet_from_proposal_admission(
        packet_id=packet_id,
        baseline_l1=baseline_l1,
        residual_ref=residual_ref,
        proposal=proposal,
        admission=admission,
        predicted_files=predicted_files,
        validation_commands=validation_commands
        if validation_commands is not None
        else DEFAULT_REPAIR_DEV_VALIDATION_COMMANDS,
        case_id=case_id,
        detail=detail,
    )
    return build_repair_dev_codex_packet(
        packet_id=intermediate.packet_id,
        baseline_l1=intermediate.baseline_l1,
        residual_refs=intermediate.residual_refs,
        proposals=intermediate.proposals,
        admission_results=intermediate.admission_receipts,
        predicted_files=intermediate.predicted_files,
        validation_commands=intermediate.validation_commands,
        baseline_arm_id=intermediate.baseline_arm_id,
        case_id=intermediate.case_id,
        detail=intermediate.detail,
        baseline_e2e=baseline_e2e,
        proposal_ids_for_admissions=tuple(
            item.proposal_id for item in intermediate.admission_receipts
        ),
        bindings=bindings,
        catalog=catalog,
        acceptance_ids=acceptance_ids,
        expansion_handles=expansion_handles,
        require_repair_dev_evidence=require_repair_dev_evidence,
    )


def build_repair_dev_packets_from_residual_catalog(
    catalog: Mapping[str, object],
    *,
    baseline_l1_by_case: Mapping[str, CanonicalRuleIR],
    proposals_by_case: Mapping[str, TeacherProposal | Sequence[TeacherProposal]],
    admissions_by_case: Mapping[
        str,
        StructuralAdmissionResult
        | PlateauAdmissionReceipt
        | Sequence[StructuralAdmissionResult | PlateauAdmissionReceipt],
    ],
    case_ids: Sequence[str] | None = None,
    predicted_files: Sequence[str] | None = None,
    validation_commands: Sequence[str] | None = None,
    packet_id_prefix: str = "repair-dev-pkt",
    acceptance_ids_by_case: Mapping[str, Sequence[str]] | None = None,
    expansion_handles_by_case: Mapping[
        str, Sequence[ExpansionHandle]
    ] | None = None,
    require_repair_dev_evidence: bool = True,
) -> tuple[PlateauCodexPacket, ...]:
    """Build one repair-development packet per residual case with admissions."""

    assert_catalog_allowed_for_packets(
        catalog,
        allowed_population_kinds=(REPAIR_DEV_POPULATION_KIND,),
    )
    refs = residual_refs_from_catalog(
        catalog, case_ids=case_ids, nonzero_only=True
    )
    by_case: dict[str, list[ResidualRef]] = {}
    for ref in refs:
        by_case.setdefault(ref.case_id, []).append(ref)

    packets: list[PlateauCodexPacket] = []
    for case_id, case_refs in by_case.items():
        if case_id not in baseline_l1_by_case:
            raise PlateauCodexPacketError(
                f"missing baseline_l1 for repair-dev case {case_id!r}"
            )
        if case_id not in proposals_by_case:
            continue
        if case_id not in admissions_by_case:
            continue
        baseline = baseline_l1_by_case[case_id]
        raw_proposals = proposals_by_case[case_id]
        if isinstance(raw_proposals, TeacherProposal):
            proposal_seq: tuple[TeacherProposal, ...] = (raw_proposals,)
        else:
            proposal_seq = tuple(raw_proposals)
        raw_admissions = admissions_by_case[case_id]
        if isinstance(
            raw_admissions, (StructuralAdmissionResult, PlateauAdmissionReceipt)
        ):
            admission_seq: tuple[
                StructuralAdmissionResult | PlateauAdmissionReceipt, ...
            ] = (raw_admissions,)
        else:
            admission_seq = tuple(raw_admissions)
        if not proposal_seq or not admission_seq:
            continue
        aligned: list[TeacherProposal] = []
        for proposal in proposal_seq:
            if proposal.residual_ref_ids:
                aligned.append(proposal)
            else:
                aligned.append(
                    TeacherProposal(
                        proposal_id=proposal.proposal_id,
                        teacher=proposal.teacher,
                        residual_ref_ids=tuple(
                            ref.residual_id for ref in case_refs
                        ),
                        allowed_field_paths=proposal.allowed_field_paths,
                        candidate_l1=proposal.candidate_l1,
                        field_changes=proposal.field_changes,
                        detail=proposal.detail,
                        semantic_authority=False,
                    )
                )
        case_acceptance = None
        if acceptance_ids_by_case is not None:
            case_acceptance = acceptance_ids_by_case.get(case_id)
        case_handles = None
        if expansion_handles_by_case is not None:
            case_handles = expansion_handles_by_case.get(case_id)
        packet = build_repair_dev_codex_packet(
            packet_id=f"{packet_id_prefix}-{case_id}",
            baseline_l1=baseline,
            residual_refs=tuple(case_refs),
            proposals=tuple(aligned),
            admission_results=admission_seq,
            predicted_files=predicted_files,
            validation_commands=validation_commands,
            case_id=case_id,
            detail=f"repair_development residual packet for {case_id}",
            catalog=catalog,
            acceptance_ids=case_acceptance,
            expansion_handles=case_handles,
            require_repair_dev_evidence=require_repair_dev_evidence,
        )
        packets.append(packet)
    return tuple(packets)


def build_repair_dev_packet_context_metrics(
    packets: Sequence[PlateauCodexPacket],
    *,
    catalog: Mapping[str, object] | None = None,
    task_id: str = "PLAT2-030",
    evidence_id: str = PLATEAU_CODEX_PACKET_REPAIR_DEV_EVIDENCE,
) -> dict[str, object]:
    """Aggregate token / omission metrics for repair-development packets."""

    if not isinstance(packets, Sequence) or isinstance(
        packets, (str, bytes, bytearray)
    ):
        raise PlateauCodexPacketError("packets must be a sequence")
    packet_rows: list[dict[str, object]] = []
    implementable_count = 0
    token_counts: list[int] = []
    coverage_values: list[float] = []
    budget_exceeded = 0
    for packet in packets:
        if not isinstance(packet, PlateauCodexPacket):
            raise PlateauCodexPacketError(
                "packets must contain PlateauCodexPacket records"
            )
        if packet.population_kind not in {
            None,
            REPAIR_DEV_POPULATION_KIND,
            HOLDOUT_POPULATION_KIND,
        }:
            raise PlateauCodexPacketError(
                "context metrics accept repair_development/holdout packets only"
            )
        if packet.implementable:
            implementable_count += 1
        token_count = (
            packet.token_count
            if packet.token_count is not None
            else count_tokens_whitespace_proxy(packet.payload_for_digest())
        )
        token_counts.append(int(token_count))
        coverage = (
            float(packet.omitted_handle_coverage)
            if packet.omitted_handle_coverage is not None
            else 1.0
        )
        coverage_values.append(coverage)
        budget = packet.token_budget or PACKET_TOKEN_BUDGET
        if token_count > budget:
            budget_exceeded += 1
        packet_rows.append(
            {
                "case_id": packet.case_id,
                "implementable": packet.implementable,
                "implementable_blockers": list(packet.implementable_blockers),
                "omitted_handle_coverage": coverage,
                "omitted_handle_ids": list(packet.omitted_handle_ids),
                "packet_digest": packet.packet_digest,
                "packet_id": packet.packet_id,
                "population_kind": packet.population_kind,
                "token_budget": budget,
                "token_count": int(token_count),
                "expansion_handle_count": len(packet.expansion_handles),
                "included_expansion_handle_count": sum(
                    1 for item in packet.expansion_handles if item.included
                ),
            }
        )

    catalog_cid = None
    tree_cid = None
    population_cid = None
    baseline_cid = None
    if catalog is not None:
        assert_catalog_allowed_for_packets(
            catalog,
            allowed_population_kinds=(
                REPAIR_DEV_POPULATION_KIND,
                HOLDOUT_POPULATION_KIND,
            ),
        )
        catalog_cid = catalog.get("catalog_cid")
        tree_cid = catalog.get("tree_cid")
        population_cid = catalog.get("population_cid")
        baseline = catalog.get("baseline")
        if isinstance(baseline, Mapping):
            baseline_cid = baseline.get("report_cid")

    mean_tokens = (
        sum(token_counts) / len(token_counts) if token_counts else 0.0
    )
    mean_coverage = (
        sum(coverage_values) / len(coverage_values)
        if coverage_values
        else 1.0
    )
    payload: dict[str, object] = {
        "aggregate": {
            "budget_exceeded_count": budget_exceeded,
            "implementable_count": implementable_count,
            "max_token_count": max(token_counts) if token_counts else 0,
            "mean_omitted_handle_coverage": mean_coverage,
            "mean_token_count": mean_tokens,
            "packet_count": len(packet_rows),
            "soft_warn_token_count": sum(
                1
                for count in token_counts
                if count >= PACKET_TOKEN_BUDGET_SOFT_WARN
            ),
        },
        "bindings": {
            "baseline_cid": baseline_cid,
            "catalog_cid": catalog_cid,
            "population_cid": population_cid,
            "tree_cid": tree_cid,
        },
        "evidence_id": evidence_id,
        "interface": REPAIR_DEV_PACKET_CONTEXT_METRICS_INTERFACE,
        "packet_token_budget": packet_token_budget_definition(),
        "packets": packet_rows,
        "population_kind": REPAIR_DEV_POPULATION_KIND,
        "schema_version": REPAIR_DEV_PACKET_CONTEXT_METRICS_SCHEMA,
        "task_id": task_id,
        "title": "Repair-development packet context metrics",
    }
    metrics_cid = cid_for_dag_json(
        {key: value for key, value in payload.items() if key != "metrics_cid"}
    )
    payload["metrics_cid"] = metrics_cid
    payload["metrics_cid_codec"] = "dag-json"
    payload["metrics_cid_scope"] = "payload_without_metrics_cid"
    return payload


def write_repair_dev_packet_context_metrics(
    packets: Sequence[PlateauCodexPacket],
    *,
    path: str | Path | None = None,
    catalog: Mapping[str, object] | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, object]:
    """Build and atomically write repair-dev packet context metrics JSON."""

    metrics = build_repair_dev_packet_context_metrics(
        packets, catalog=catalog
    )
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    target = (
        Path(path)
        if path is not None
        else root / DEFAULT_REPAIR_DEV_PACKET_METRICS_RELATIVE_PATH
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        metrics,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)
    return metrics


__all__ = [
    "ALLOWED_PREDICTED_FILE_PREFIXES",
    "DEFAULT_BASELINE_ARM_ID",
    "DEFAULT_BASELINE_E2E",
    "DEFAULT_HOLDOUT_VALIDATION_COMMANDS",
    "DEFAULT_PACKET_INVALIDATORS",
    "DEFAULT_PILOT_REGRESSION_REQUIREMENTS",
    "DEFAULT_PREDICTED_FILES",
    "DEFAULT_REPAIR_DEV_PACKET_METRICS_RELATIVE_PATH",
    "DEFAULT_REPAIR_DEV_VALIDATION_COMMANDS",
    "DEFAULT_VALIDATION_COMMANDS",
    "FORBIDDEN_PACKET_CONTENT_KEYS",
    "HOLDOUT_BASELINE_E2E",
    "HOLDOUT_POPULATION_KIND",
    "KNOWN_TEACHERS",
    "NON_IMPLEMENTABLE_DISPOSITIONS",
    "NON_IMPLEMENTABLE_EVIDENCE_STATUSES",
    "PACKET_OMITTED_HANDLE_COVERAGE_REQUIRED",
    "PACKET_TOKEN_BUDGET",
    "PACKET_TOKEN_BUDGET_SOFT_WARN",
    "PACKET_TOKEN_COUNTING_METHOD",
    "PLATEAU_ADMISSION_RECEIPT_INTERFACE",
    "PLATEAU_CODEX_PACKET_EVIDENCE",
    "PLATEAU_CODEX_PACKET_INTERFACE",
    "PLATEAU_CODEX_PACKET_REPAIR_DEV_EVIDENCE",
    "PLATEAU_CODEX_PACKET_SCHEMA",
    "PLATEAU_EXPANSION_HANDLE_INTERFACE",
    "PLATEAU_INVARIANT_CONTEXT_INTERFACE",
    "PLATEAU_PACKET_BINDINGS_INTERFACE",
    "PLATEAU_PROOF_OBLIGATION_INTERFACE",
    "PLATEAU_RESIDUAL_REF_INTERFACE",
    "PLATEAU_TEACHER_PROPOSAL_INTERFACE",
    "REPAIR_DEV_BASELINE_E2E",
    "REPAIR_DEV_PACKET_CONTEXT_METRICS_INTERFACE",
    "REPAIR_DEV_PACKET_CONTEXT_METRICS_SCHEMA",
    "REPAIR_DEV_POPULATION_KIND",
    "ExpansionHandle",
    "InvariantContext",
    "PacketBindings",
    "PlateauAdmissionReceipt",
    "PlateauCodexPacket",
    "PlateauCodexPacketError",
    "ProofObligation",
    "ProverCheckReceipt",
    "ResidualRef",
    "TeacherKind",
    "TeacherProposal",
    "assert_catalog_allowed_for_packets",
    "baseline_l1_digest",
    "build_holdout_codex_packet",
    "build_holdout_packet_from_proposal_admission",
    "build_holdout_packets_from_residual_catalog",
    "build_invariant_context",
    "build_packet_from_proposal_admission",
    "build_plateau_codex_packet",
    "build_repair_dev_codex_packet",
    "build_repair_dev_packet_context_metrics",
    "build_repair_dev_packet_from_proposal_admission",
    "build_repair_dev_packets_from_residual_catalog",
    "catalog_case_evidence_status",
    "compute_implementable_blockers",
    "count_tokens_whitespace_proxy",
    "disposition_is_implementable",
    "extract_catalog_bindings",
    "field_change_from_dict",
    "field_change_path",
    "mint_proof_obligations",
    "plan_expansion_handles",
    "residual_ref_from_catalog_facet",
    "residual_refs_from_catalog",
    "stable_residual_id",
    "write_repair_dev_packet_context_metrics",
]
