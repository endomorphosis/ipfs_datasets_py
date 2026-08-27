"""Full-scrape completion and admission oracle for state laws (LCR-003).

Fail-closed gates for declaring a jurisdiction or 51-jurisdiction corpus
complete. Nonzero row counts and requested-scope ``success`` flags are
explicitly insufficient.

Gates
-----
1. **Exact set** — jurisdiction set must equal the sealed 51 codes (50
   postal states + ``DC``). Opt-in DC and any other set are rejected.
2. **Disposition reconciliation** —
   ``discovered = fetched + excluded + quarantined + failed_final``
   (duplicates tracked separately).
3. **Frontier closure** — closed enumerator, no unvisited continuation
   links, expected index units visited.
4. **Source quality** — official source authority required for success
   admission.
5. **No truncation** — full mode forbids sample/runtime caps; partial
   checkpoints cannot promote success; completion basis must be the
   source frontier.
6. **Failed-final** — publication/success admission requires
   ``failed_final == 0``.
7. **Replay** — optional second frontier traversal must match the first
   closed digest (or record an explicit upstream-change delta).
8. **Derived-key parity** — derived index keys must equal the current
   canonical key set; stale keys block admission.
9. **Subset rejection** — corpus manifests that cover fewer than 51
   jurisdictions, or mark requested-scope completion as full, fail.

This module performs no network I/O. Downstream scrapers and certifiers
feed typed receipts; the oracle returns structured verdicts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Iterable, Mapping, Optional, Sequence, Union

# ---------------------------------------------------------------------------
# Schema identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "state-laws-completeness-oracle-v1"
FIXTURE_SCHEMA: Final = "ipfs_datasets_py/state-laws-completion-receipts@1"
TASK_ID: Final = "LCR-003"
GOAL_ID: Final = "LCR-G010"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
EXPECTED_JURISDICTION_COUNT: Final = 51

DEFAULT_FIXTURE_RELATIVE_PATH: Final = Path(
    "tests/fixtures/legal_ir/state_laws_completion_receipts.json"
)

# Exact jurisdiction set: 50 postal state codes + DC (no extras, no omissions).
CANONICAL_JURISDICTIONS: Final = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "DC",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
    }
)

CANONICAL_JURISDICTION_ORDER: Final = tuple(
    sorted(code for code in CANONICAL_JURISDICTIONS if code != "DC")
) + ("DC",)

# Completion bases that may authorize full-mode success.
SOURCE_FRONTIER_COMPLETION_BASES: Final = frozenset(
    {
        "source_frontier",
        "frontier",
        "official_frontier",
    }
)

# Bases that never authorize full-mode success promotion.
UNSAFE_COMPLETION_BASES: Final = frozenset(
    {
        "partial_checkpoint",
        "filename",
        "registry",
        "requested_scope",
        "nonzero_count",
        "row_count",
        "sample",
        "opt_in_dc",
        "success_flag",
    }
)

SECONDARY_SOURCE_DOMAIN_MARKERS: Final = frozenset(
    {
        "justia.com",
        "findlaw.com",
        "casetext.com",
        "law.cornell.edu",
        "wikipedia.org",
        "huggingface.co",
        "lexisnexis.com",
        "westlaw.com",
        "bloomberglaw.com",
    }
)

# Gate identifiers used in findings and fixture expected_kinds.
GATE_EXACT_SET: Final = "exact_set"
GATE_OPT_IN_DC: Final = "opt_in_dc"
GATE_SUBSET_MANIFEST: Final = "subset_manifest"
GATE_DISPOSITION: Final = "disposition_reconciliation"
GATE_FRONTIER: Final = "frontier_closure"
GATE_SOURCE_QUALITY: Final = "source_quality"
GATE_NO_TRUNCATION: Final = "no_truncation"
GATE_FAILED_FINAL: Final = "failed_final"
GATE_REPLAY: Final = "replay"
GATE_DERIVED_KEY_PARITY: Final = "derived_key_parity"
GATE_CHECKPOINT: Final = "checkpoint_promotion"

ALL_GATES: Final = frozenset(
    {
        GATE_EXACT_SET,
        GATE_OPT_IN_DC,
        GATE_SUBSET_MANIFEST,
        GATE_DISPOSITION,
        GATE_FRONTIER,
        GATE_SOURCE_QUALITY,
        GATE_NO_TRUNCATION,
        GATE_FAILED_FINAL,
        GATE_REPLAY,
        GATE_DERIVED_KEY_PARITY,
        GATE_CHECKPOINT,
    }
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StateLawsCompletenessError(ValueError):
    """Base error for completion / admission oracle failures."""


class JurisdictionSetError(StateLawsCompletenessError):
    """Raised when the jurisdiction set is not exactly the sealed 51-set."""


class CompletenessAdmissionError(StateLawsCompletenessError):
    """Raised when require_* helpers reject an incomplete receipt."""


class FixtureSchemaError(StateLawsCompletenessError):
    """Raised when the sealed completion-receipts fixture is malformed."""


# ---------------------------------------------------------------------------
# Finding kinds (stable strings for fixtures and callers)
# ---------------------------------------------------------------------------


class FindingKind(str, Enum):
    """Stable finding identifiers emitted by the oracle."""

    SUBSET_MANIFEST = "subset_manifest"
    OPT_IN_DC = "opt_in_dc"
    OPEN_FRONTIER = "open_frontier"
    ENUMERATOR_NOT_CLOSED = "enumerator_not_closed"
    UNVISITED_CONTINUATION_LINKS = "unvisited_continuation_links"
    FAILED_FINAL_NONZERO = "failed_final_nonzero"
    SAMPLE_CAP_PRESENT = "sample_cap_present"
    RUNTIME_CAP_PRESENT = "runtime_cap_present"
    PARTIAL_CHECKPOINT_PROMOTED = "partial_checkpoint_promoted"
    STALE_INDEX_KEYS = "stale_index_keys"
    DERIVED_KEY_PARITY_MISMATCH = "derived_key_parity_mismatch"
    JURISDICTION_SET_MISMATCH = "jurisdiction_set_mismatch"
    DISPOSITION_ARITHMETIC_MISMATCH = "disposition_arithmetic_mismatch"
    UNOFFICIAL_SOURCE = "unofficial_source"
    REPLAY_MISMATCH = "replay_mismatch"
    REQUESTED_SCOPE_COMPLETION = "requested_scope_completion"
    SUCCESS_WITHOUT_CLOSURE = "success_without_closure"
    MISSING_BOUNDARY_PROBES = "missing_boundary_probes"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    NONZERO_COUNT_INSUFFICIENT = "nonzero_count_insufficient"

    @classmethod
    def coerce(cls, value: Any) -> "FindingKind":
        if isinstance(value, FindingKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "exact_state_set_mismatch": cls.JURISDICTION_SET_MISMATCH,
            "exact_set_mismatch": cls.JURISDICTION_SET_MISMATCH,
            "stale_keys": cls.STALE_INDEX_KEYS,
            "derived_key_mismatch": cls.DERIVED_KEY_PARITY_MISMATCH,
            "key_parity_mismatch": cls.DERIVED_KEY_PARITY_MISMATCH,
            "unofficial_source_domain": cls.UNOFFICIAL_SOURCE,
            "source_quality": cls.UNOFFICIAL_SOURCE,
            "partial_success_promoted": cls.PARTIAL_CHECKPOINT_PROMOTED,
            "dc_opt_in": cls.OPT_IN_DC,
            "include_dc_optional": cls.OPT_IN_DC,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise StateLawsCompletenessError(f"unknown finding kind: {value!r}")


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StateLawsCompletenessError(f"{name} must be a mapping")
    return value


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StateLawsCompletenessError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise StateLawsCompletenessError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise StateLawsCompletenessError(f"{name} exceeds maximum length {maximum}")
    return text


def _as_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StateLawsCompletenessError(f"{name} must be a non-negative integer")
    if value < 0:
        raise StateLawsCompletenessError(f"{name} must be a non-negative integer")
    return value


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        raise StateLawsCompletenessError("expected a sequence of strings")
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _truthy_cap(value: Any) -> bool:
    """Return True when a sample/runtime cap is actively constraining."""

    if value is None or value is False:
        return False
    if value == 0 or value == {} or value == [] or value == "":
        return False
    return True


def _host_looks_secondary(host: str) -> bool:
    h = (host or "").lower().strip().strip(".")
    if not h:
        return False
    for marker in SECONDARY_SOURCE_DOMAIN_MARKERS:
        if h == marker or h.endswith("." + marker) or marker in h:
            return True
    return False


def repository_root() -> Path:
    """Return the repository root that contains ``tests/fixtures``."""

    return Path(__file__).resolve().parents[3]


def default_fixture_path(repo_root: Optional[PathLike] = None) -> Path:
    """Return the sealed completion-receipts fixture path."""

    root = Path(repo_root) if repo_root is not None else repository_root()
    return (root / DEFAULT_FIXTURE_RELATIVE_PATH).resolve()


def canonical_jurisdiction_codes() -> tuple[str, ...]:
    """Return the exact 51-jurisdiction set in canonical order (states then DC)."""

    codes = CANONICAL_JURISDICTION_ORDER
    if len(codes) != EXPECTED_JURISDICTION_COUNT:
        raise JurisdictionSetError(
            f"jurisdiction set invariant broken: expected "
            f"{EXPECTED_JURISDICTION_COUNT}, got {len(codes)}"
        )
    if "DC" not in codes:
        raise JurisdictionSetError("jurisdiction set must include DC")
    if len(set(codes)) != len(codes):
        raise JurisdictionSetError("jurisdiction set contains duplicates")
    return codes


def normalize_postal_code(value: Any, *, name: str = "postal_code") -> str:
    """Normalize and validate a postal code against the exact 51-set."""

    text = _require_non_empty_str(value, name, maximum=8).upper()
    if len(text) != 2 or not text.isalpha():
        raise JurisdictionSetError(f"{name}={text!r} is not a two-letter postal code")
    if text not in CANONICAL_JURISDICTIONS:
        raise JurisdictionSetError(
            f"{name}={text!r} is not in the exact 51-jurisdiction set "
            f"(expected {EXPECTED_JURISDICTION_COUNT} codes including DC)"
        )
    return text


def validate_jurisdiction_set(
    codes: Iterable[Any],
    *,
    name: str = "jurisdictions",
) -> tuple[str, ...]:
    """Require the exact 51-jurisdiction set (no missing, no extra, no dupes)."""

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in codes:
        code = normalize_postal_code(raw, name=name)
        if code in seen:
            raise JurisdictionSetError(f"{name} contains duplicate postal code {code!r}")
        seen.add(code)
        normalized.append(code)
    actual = frozenset(normalized)
    if actual != CANONICAL_JURISDICTIONS:
        missing = sorted(CANONICAL_JURISDICTIONS - actual)
        extra = sorted(actual - CANONICAL_JURISDICTIONS)
        raise JurisdictionSetError(
            f"{name} must equal the exact 51-jurisdiction set; "
            f"missing={missing!r} extra={extra!r}"
        )
    if len(normalized) != EXPECTED_JURISDICTION_COUNT:
        raise JurisdictionSetError(
            f"{name} must contain exactly {EXPECTED_JURISDICTION_COUNT} unique codes, "
            f"got {len(normalized)}"
        )
    return tuple(sorted(normalized))


def is_opt_in_dc_policy(payload: Mapping[str, Any]) -> bool:
    """Return True when DC is treated as optional rather than required.

    Legacy runners defined ``all`` as 50 states with ``--include-dc`` opt-in.
    The completion oracle forbids that contract for any production candidate.
    """

    dc_policy = str(
        payload.get("dc_policy")
        or payload.get("district_of_columbia_policy")
        or ""
    ).strip().lower().replace("-", "_").replace(" ", "_")
    if dc_policy in {
        "opt_in",
        "optional",
        "include_dc_flag",
        "legacy_50_plus_flag",
        "all_without_dc",
    }:
        return True

    if payload.get("dc_optional") is True or payload.get("opt_in_dc") is True:
        return True

    # Explicit include_dc=false with states_token=all is the legacy opt-in path.
    states_token = str(payload.get("states_token") or payload.get("states") or "").strip().lower()
    include_dc = payload.get("include_dc")
    if states_token in {"all", "50", "states"} and include_dc is False:
        return True

    # includes_dc=false on a claimed-complete set without DC.
    jurisdictions = payload.get("jurisdictions") or payload.get("jurisdiction_codes")
    if isinstance(jurisdictions, Sequence) and not isinstance(jurisdictions, (str, bytes)):
        codes = {str(c).strip().upper() for c in jurisdictions if str(c).strip()}
        if "DC" not in codes and payload.get("includes_dc") is False:
            # Missing DC alone is jurisdiction_set_mismatch; opt-in only when
            # the payload also signals optional DC semantics.
            if payload.get("dc_optional") is True or payload.get("opt_in_dc") is True:
                return True
            if dc_policy:
                return True
            if states_token in {"all", "50", "states"}:
                return True

    return False


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompletenessFinding:
    """One fail-closed gate finding."""

    kind: FindingKind
    gate: str
    detail: str
    jurisdiction: Optional[str] = None
    severity: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "gate": self.gate,
            "detail": self.detail,
            "jurisdiction": self.jurisdiction,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class CompletenessVerdict:
    """Oracle outcome for one receipt, manifest, or fixture case."""

    complete: bool
    admitted: bool
    case_id: str
    status: str
    kinds: tuple[str, ...]
    findings: tuple[CompletenessFinding, ...]
    gates_passed: tuple[str, ...]
    gates_failed: tuple[str, ...]
    jurisdiction: Optional[str] = None
    expected_status: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "admitted": self.admitted,
            "case_id": self.case_id,
            "status": self.status,
            "kinds": list(self.kinds),
            "findings": [item.to_dict() for item in self.findings],
            "gates_passed": list(self.gates_passed),
            "gates_failed": list(self.gates_failed),
            "jurisdiction": self.jurisdiction,
            "expected_status": self.expected_status,
        }


@dataclass
class _FindingCollector:
    """Mutable collector used while evaluating a single oracle subject."""

    case_id: str
    jurisdiction: Optional[str] = None
    findings: list[CompletenessFinding] = field(default_factory=list)

    def add(
        self,
        kind: FindingKind,
        gate: str,
        detail: str,
        *,
        jurisdiction: Optional[str] = None,
        severity: str = "error",
    ) -> None:
        self.findings.append(
            CompletenessFinding(
                kind=kind,
                gate=gate,
                detail=detail,
                jurisdiction=jurisdiction if jurisdiction is not None else self.jurisdiction,
                severity=severity,
            )
        )

    def kinds(self) -> list[str]:
        out: list[str] = []
        for item in self.findings:
            if item.kind.value not in out:
                out.append(item.kind.value)
        return out

    def gates_failed(self) -> list[str]:
        out: list[str] = []
        for item in self.findings:
            if item.severity == "error" and item.gate not in out:
                out.append(item.gate)
        return out

    def verdict(
        self,
        *,
        expected_status: Optional[str] = None,
        relevant_gates: Optional[Iterable[str]] = None,
    ) -> CompletenessVerdict:
        error_findings = [item for item in self.findings if item.severity == "error"]
        failed = self.gates_failed()
        relevant = set(relevant_gates) if relevant_gates is not None else set(ALL_GATES)
        passed = tuple(sorted(g for g in relevant if g not in failed))
        complete = not error_findings
        return CompletenessVerdict(
            complete=complete,
            admitted=complete,
            case_id=self.case_id,
            status="pass" if complete else "fail",
            kinds=tuple(self.kinds()),
            findings=tuple(self.findings),
            gates_passed=passed,
            gates_failed=tuple(failed),
            jurisdiction=self.jurisdiction,
            expected_status=expected_status,
        )


# ---------------------------------------------------------------------------
# Disposition arithmetic
# ---------------------------------------------------------------------------


def reconcile_disposition(disposition: Mapping[str, Any]) -> tuple[bool, str]:
    """Return ``(ok, detail)`` for disposition reconciliation.

    Required identity:

        discovered = fetched + excluded + quarantined + failed_final

    Duplicates are tracked separately and must be non-negative when present.
    """

    if not isinstance(disposition, Mapping):
        return False, "disposition object missing"

    try:
        discovered = _as_non_negative_int(disposition.get("discovered"), "discovered")
        fetched = _as_non_negative_int(disposition.get("fetched"), "fetched")
        excluded = _as_non_negative_int(disposition.get("excluded"), "excluded")
        quarantined = _as_non_negative_int(disposition.get("quarantined"), "quarantined")
        failed_final = _as_non_negative_int(disposition.get("failed_final"), "failed_final")
    except StateLawsCompletenessError as exc:
        return False, str(exc)

    if "duplicates" in disposition and disposition.get("duplicates") is not None:
        try:
            _as_non_negative_int(disposition.get("duplicates"), "duplicates")
        except StateLawsCompletenessError as exc:
            return False, str(exc)

    accounted = fetched + excluded + quarantined + failed_final
    if discovered != accounted:
        return (
            False,
            (
                f"discovered={discovered} != "
                f"fetched+excluded+quarantined+failed_final={accounted}"
            ),
        )
    return True, (
        f"discovered={discovered} reconciles "
        f"(fetched={fetched}, excluded={excluded}, "
        f"quarantined={quarantined}, failed_final={failed_final})"
    )


# ---------------------------------------------------------------------------
# Gate evaluators (jurisdiction receipt)
# ---------------------------------------------------------------------------


def _evaluate_source_quality(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    source_domain = str(receipt.get("source_domain") or "").strip().lower()
    authority = source_authority_class(receipt)

    if not has_explicit_official_source_authority(receipt):
        collector.add(
            FindingKind.UNOFFICIAL_SOURCE,
            GATE_SOURCE_QUALITY,
            (
                "explicit official source authority is required for admission: "
                f"official_source={receipt.get('official_source')!r}, "
                f"source_authority_class={authority or '<missing>'}, "
                f"domain={source_domain or '<missing>'}"
            ),
        )
        return
    if source_domain and _host_looks_secondary(source_domain):
        collector.add(
            FindingKind.UNOFFICIAL_SOURCE,
            GATE_SOURCE_QUALITY,
            f"source domain is secondary/mirror: {source_domain}",
        )


def source_authority_class(receipt: Mapping[str, Any]) -> str:
    """Return the normalized explicit authority class from a receipt."""

    return str(
        receipt.get("source_authority_class") or receipt.get("authority_class") or ""
    ).strip().lower()


def has_explicit_official_source_authority(receipt: Mapping[str, Any]) -> bool:
    """Whether a live/full receipt explicitly claims verified official authority.

    ``official_source`` and the authority class are independent assertions. A
    source URL may point at an official locator while its acquired bytes came
    from recovery, an unverified cache, or an insecure transport. Full-corpus
    admission therefore requires both fields and never infers authority from a
    URL or from the absence of a negative marker.
    """

    return (
        receipt.get("official_source") is True
        and source_authority_class(receipt) == "official"
    )


def _evaluate_no_truncation(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    mode = str(receipt.get("mode") or "").strip().lower()
    runtime_caps = receipt.get("runtime_caps")
    sample_cap = receipt.get("sample_cap")

    if mode == "full" and _truthy_cap(runtime_caps):
        collector.add(
            FindingKind.RUNTIME_CAP_PRESENT,
            GATE_NO_TRUNCATION,
            f"full-mode receipt has runtime_caps={runtime_caps!r}",
        )
    if _truthy_cap(sample_cap):
        collector.add(
            FindingKind.SAMPLE_CAP_PRESENT,
            GATE_NO_TRUNCATION,
            f"sample_cap present: {sample_cap!r}",
        )

    # Boundary probes are required for full-mode success claims.
    status = str(receipt.get("status") or "").strip().lower()
    probes = receipt.get("boundary_probes")
    if status == "success" and mode in {"", "full"}:
        if not isinstance(probes, Mapping):
            collector.add(
                FindingKind.MISSING_BOUNDARY_PROBES,
                GATE_NO_TRUNCATION,
                "boundary_probes object missing on success receipt",
            )
        else:
            first_unit = probes.get("first_hierarchy_unit")
            last_unit = probes.get("last_hierarchy_unit")
            if not first_unit or not last_unit:
                collector.add(
                    FindingKind.MISSING_BOUNDARY_PROBES,
                    GATE_NO_TRUNCATION,
                    "boundary probes require first_hierarchy_unit and last_hierarchy_unit",
                )


def _evaluate_checkpoint(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    checkpoint = receipt.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        # Checkpoint block is required when claiming success in full mode.
        if str(receipt.get("status") or "").lower() == "success":
            collector.add(
                FindingKind.PARTIAL_CHECKPOINT_PROMOTED,
                GATE_CHECKPOINT,
                "success receipt missing checkpoint block",
            )
        return

    partial = bool(checkpoint.get("partial"))
    promoted = bool(checkpoint.get("promoted_success"))
    completion_basis = str(checkpoint.get("completion_basis") or "").strip().lower()
    status = str(receipt.get("status") or "").strip().lower()

    if partial and promoted:
        collector.add(
            FindingKind.PARTIAL_CHECKPOINT_PROMOTED,
            GATE_CHECKPOINT,
            "partial checkpoint was promoted to success",
        )
        return

    if status == "success":
        if completion_basis in UNSAFE_COMPLETION_BASES:
            collector.add(
                FindingKind.PARTIAL_CHECKPOINT_PROMOTED,
                GATE_CHECKPOINT,
                f"success completion_basis is not source frontier: {completion_basis}",
            )
        elif completion_basis and completion_basis not in SOURCE_FRONTIER_COMPLETION_BASES:
            # Unknown bases are fail-closed when success is claimed.
            collector.add(
                FindingKind.PARTIAL_CHECKPOINT_PROMOTED,
                GATE_CHECKPOINT,
                f"success completion_basis is not source frontier: {completion_basis}",
            )
        elif not completion_basis:
            collector.add(
                FindingKind.PARTIAL_CHECKPOINT_PROMOTED,
                GATE_CHECKPOINT,
                "success receipt missing checkpoint.completion_basis",
            )


def _evaluate_frontier(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    frontier = receipt.get("frontier")
    status = str(receipt.get("status") or "").strip().lower()
    if not isinstance(frontier, Mapping):
        if status == "success":
            collector.add(
                FindingKind.OPEN_FRONTIER,
                GATE_FRONTIER,
                "success receipt missing frontier block",
            )
        return

    closed = frontier.get("closed")
    enumerator_closed = frontier.get("enumerator_closed")
    unvisited = _as_str_list(frontier.get("unvisited_continuation_links"))

    if closed is not True:
        collector.add(
            FindingKind.OPEN_FRONTIER,
            GATE_FRONTIER,
            "frontier.closed is not true",
        )
    if enumerator_closed is not True:
        collector.add(
            FindingKind.ENUMERATOR_NOT_CLOSED,
            GATE_FRONTIER,
            "frontier.enumerator_closed is not true",
        )
    if unvisited:
        collector.add(
            FindingKind.UNVISITED_CONTINUATION_LINKS,
            GATE_FRONTIER,
            f"unvisited continuation links: {unvisited}",
        )

    expected_units = frontier.get("expected_index_units")
    visited_units = frontier.get("visited_index_units")
    if (
        isinstance(expected_units, int)
        and not isinstance(expected_units, bool)
        and isinstance(visited_units, int)
        and not isinstance(visited_units, bool)
        and visited_units < expected_units
    ):
        collector.add(
            FindingKind.ENUMERATOR_NOT_CLOSED,
            GATE_FRONTIER,
            (
                f"visited_index_units ({visited_units}) < "
                f"expected_index_units ({expected_units})"
            ),
        )

    # Claiming success with an open frontier is a dedicated failure mode.
    if status == "success" and closed is not True:
        if FindingKind.SUCCESS_WITHOUT_CLOSURE.value not in collector.kinds():
            collector.add(
                FindingKind.SUCCESS_WITHOUT_CLOSURE,
                GATE_FRONTIER,
                "status=success with open frontier",
            )


def _evaluate_disposition(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    disposition = receipt.get("disposition")
    status = str(receipt.get("status") or "").strip().lower()
    if not isinstance(disposition, Mapping):
        collector.add(
            FindingKind.DISPOSITION_ARITHMETIC_MISMATCH,
            GATE_DISPOSITION,
            "disposition object missing",
        )
        return

    ok, detail = reconcile_disposition(disposition)
    if not ok:
        collector.add(
            FindingKind.DISPOSITION_ARITHMETIC_MISMATCH,
            GATE_DISPOSITION,
            detail,
        )

    failed_final = disposition.get("failed_final")
    if (
        isinstance(failed_final, int)
        and not isinstance(failed_final, bool)
        and failed_final > 0
    ):
        collector.add(
            FindingKind.FAILED_FINAL_NONZERO,
            GATE_FAILED_FINAL,
            f"failed_final={failed_final} blocks success admission",
        )
        if status == "success":
            collector.add(
                FindingKind.SUCCESS_WITHOUT_CLOSURE,
                GATE_FAILED_FINAL,
                f"status=success with failed_final={failed_final}",
            )


def _evaluate_replay(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    replay = receipt.get("replay")
    if replay is None:
        return
    if not isinstance(replay, Mapping):
        collector.add(
            FindingKind.REPLAY_MISMATCH,
            GATE_REPLAY,
            "replay block must be a mapping",
        )
        return

    # Explicit upstream-change deltas are allowed when documented.
    if replay.get("upstream_change_delta") or replay.get("explicit_upstream_change"):
        return

    first = replay.get("first_frontier_digest") or replay.get("first_digest")
    second = replay.get("second_frontier_digest") or replay.get("second_digest")
    if first is None and second is None:
        # Presence of a replay block without digests is incomplete evidence.
        if str(receipt.get("status") or "").lower() == "success":
            collector.add(
                FindingKind.REPLAY_MISMATCH,
                GATE_REPLAY,
                "replay block present but frontier digests missing",
            )
        return

    first_s = str(first or "").strip()
    second_s = str(second or "").strip()
    if not first_s or not second_s:
        collector.add(
            FindingKind.REPLAY_MISMATCH,
            GATE_REPLAY,
            "replay digests must both be non-empty",
        )
        return
    if first_s != second_s:
        collector.add(
            FindingKind.REPLAY_MISMATCH,
            GATE_REPLAY,
            f"replay frontier digests differ: {first_s!r} != {second_s!r}",
        )
    if replay.get("closed") is False:
        collector.add(
            FindingKind.REPLAY_MISMATCH,
            GATE_REPLAY,
            "replay.closed is false",
        )


def _normalize_key_set(value: Any, *, name: str) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        text = value.strip()
        return {text} if text else set()
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        raise StateLawsCompletenessError(f"{name} must be a sequence of keys")
    out: set[str] = set()
    for item in value:
        text = str(item).strip()
        if text:
            out.add(text)
    return out


def _evaluate_derived_key_parity(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    """Reject stale or drifted derived index keys.

    Accepts either a nested ``index_keys`` object or top-level
    ``canonical_keys`` / ``derived_keys`` / ``stale_keys`` fields.
    """

    block = receipt.get("index_keys")
    if block is None:
        # Flat layout.
        if not any(
            key in receipt
            for key in ("canonical_keys", "derived_keys", "stale_keys", "logical_keys")
        ):
            return
        block = receipt
    if not isinstance(block, Mapping):
        collector.add(
            FindingKind.DERIVED_KEY_PARITY_MISMATCH,
            GATE_DERIVED_KEY_PARITY,
            "index_keys must be a mapping",
        )
        return

    try:
        canonical = _normalize_key_set(
            block.get("canonical_keys") or block.get("logical_keys"),
            name="canonical_keys",
        )
        derived = _normalize_key_set(
            block.get("derived_keys") or block.get("index_keys"),
            name="derived_keys",
        )
        stale = _normalize_key_set(block.get("stale_keys"), name="stale_keys")
    except StateLawsCompletenessError as exc:
        collector.add(
            FindingKind.DERIVED_KEY_PARITY_MISMATCH,
            GATE_DERIVED_KEY_PARITY,
            str(exc),
        )
        return

    if stale:
        collector.add(
            FindingKind.STALE_INDEX_KEYS,
            GATE_DERIVED_KEY_PARITY,
            f"stale index keys present: {sorted(stale)}",
        )

    # When both sides are provided, require exact set equality.
    if canonical or derived:
        if not canonical and derived:
            collector.add(
                FindingKind.DERIVED_KEY_PARITY_MISMATCH,
                GATE_DERIVED_KEY_PARITY,
                "derived_keys present without canonical_keys",
            )
        elif canonical and not derived:
            collector.add(
                FindingKind.DERIVED_KEY_PARITY_MISMATCH,
                GATE_DERIVED_KEY_PARITY,
                "canonical_keys present without derived_keys",
            )
        elif canonical != derived:
            missing = sorted(canonical - derived)
            extra = sorted(derived - canonical)
            collector.add(
                FindingKind.DERIVED_KEY_PARITY_MISMATCH,
                GATE_DERIVED_KEY_PARITY,
                (
                    "derived key set does not match canonical keys; "
                    f"missing_from_derived={missing!r} extra_in_derived={extra!r}"
                ),
            )
            # Extra keys that are not in canonical are also stale.
            if extra and FindingKind.STALE_INDEX_KEYS.value not in collector.kinds():
                collector.add(
                    FindingKind.STALE_INDEX_KEYS,
                    GATE_DERIVED_KEY_PARITY,
                    f"derived keys not in canonical set (stale/drift): {extra}",
                )

    if block.get("parity_ok") is False:
        if FindingKind.DERIVED_KEY_PARITY_MISMATCH.value not in collector.kinds():
            collector.add(
                FindingKind.DERIVED_KEY_PARITY_MISMATCH,
                GATE_DERIVED_KEY_PARITY,
                "index_keys.parity_ok is false",
            )


def _evaluate_requested_scope_insufficiency(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    """Reject completion claims that rest only on nonzero/requested-scope flags."""

    status = str(receipt.get("status") or "").strip().lower()
    if status != "success":
        return

    completion_claim = str(
        receipt.get("completion_claim")
        or receipt.get("completion_proof")
        or ""
    ).strip().lower().replace("-", "_").replace(" ", "_")
    if completion_claim in {
        "nonzero_count",
        "row_count",
        "requested_scope",
        "filename",
        "registry_success",
        "requested_scope_is_complete",
    }:
        collector.add(
            FindingKind.REQUESTED_SCOPE_COMPLETION,
            GATE_NO_TRUNCATION,
            f"completion_claim={completion_claim!r} is insufficient for full scrape",
        )

    if receipt.get("requested_scope_only") is True:
        collector.add(
            FindingKind.REQUESTED_SCOPE_COMPLETION,
            GATE_NO_TRUNCATION,
            "requested_scope_only success is not full-corpus completion",
        )

    # Nonzero row_count alone never proves completeness when other gates fail;
    # emit an explicit finding when the receipt advertises that proof.
    if receipt.get("nonzero_count_proves_completeness") is True:
        collector.add(
            FindingKind.NONZERO_COUNT_INSUFFICIENT,
            GATE_NO_TRUNCATION,
            "nonzero row counts are not authoritative completion proof",
        )


# ---------------------------------------------------------------------------
# Public jurisdiction / corpus evaluators
# ---------------------------------------------------------------------------


def evaluate_jurisdiction_receipt(
    receipt: Mapping[str, Any],
    *,
    case_id: str = "jurisdiction_receipt",
    expected_status: Optional[str] = None,
) -> CompletenessVerdict:
    """Evaluate one jurisdiction scrape receipt for full-scrape completion.

    Success admission requires every gate to pass. Nonzero counts without
    frontier closure, official source, and disposition reconciliation fail.
    """

    payload = _require_mapping(receipt, "receipt")
    jurisdiction: Optional[str] = None
    raw_jurisdiction = payload.get("jurisdiction")
    if raw_jurisdiction is not None and str(raw_jurisdiction).strip():
        try:
            jurisdiction = normalize_postal_code(raw_jurisdiction, name="jurisdiction")
        except JurisdictionSetError as exc:
            collector = _FindingCollector(case_id=case_id, jurisdiction=str(raw_jurisdiction))
            collector.add(
                FindingKind.JURISDICTION_SET_MISMATCH,
                GATE_EXACT_SET,
                str(exc),
                jurisdiction=str(raw_jurisdiction).strip().upper(),
            )
            return collector.verdict(
                expected_status=expected_status,
                relevant_gates={
                    GATE_EXACT_SET,
                    GATE_DISPOSITION,
                    GATE_FRONTIER,
                    GATE_SOURCE_QUALITY,
                    GATE_NO_TRUNCATION,
                    GATE_FAILED_FINAL,
                    GATE_REPLAY,
                    GATE_DERIVED_KEY_PARITY,
                    GATE_CHECKPOINT,
                },
            )

    collector = _FindingCollector(case_id=case_id, jurisdiction=jurisdiction)
    relevant = {
        GATE_DISPOSITION,
        GATE_FRONTIER,
        GATE_SOURCE_QUALITY,
        GATE_NO_TRUNCATION,
        GATE_FAILED_FINAL,
        GATE_REPLAY,
        GATE_DERIVED_KEY_PARITY,
        GATE_CHECKPOINT,
    }

    _evaluate_source_quality(collector, payload)
    _evaluate_no_truncation(collector, payload)
    _evaluate_checkpoint(collector, payload)
    _evaluate_frontier(collector, payload)
    _evaluate_disposition(collector, payload)
    _evaluate_replay(collector, payload)
    _evaluate_derived_key_parity(collector, payload)
    _evaluate_requested_scope_insufficiency(collector, payload)

    return collector.verdict(expected_status=expected_status, relevant_gates=relevant)


def evaluate_jurisdiction_set_receipt(
    receipt: Mapping[str, Any],
    *,
    case_id: str = "jurisdiction_set",
    expected_status: Optional[str] = None,
) -> CompletenessVerdict:
    """Evaluate a corpus-level jurisdiction set / DC policy receipt."""

    payload = _require_mapping(receipt, "receipt")
    collector = _FindingCollector(case_id=case_id)
    relevant = {GATE_EXACT_SET, GATE_OPT_IN_DC, GATE_SUBSET_MANIFEST}

    if is_opt_in_dc_policy(payload):
        collector.add(
            FindingKind.OPT_IN_DC,
            GATE_OPT_IN_DC,
            "DC must be a required member of the exact 51-set; opt-in DC is forbidden",
        )

    codes_raw = payload.get("jurisdictions") or payload.get("jurisdiction_codes")
    if codes_raw is None:
        collector.add(
            FindingKind.JURISDICTION_SET_MISMATCH,
            GATE_EXACT_SET,
            "jurisdictions list missing",
        )
        return collector.verdict(expected_status=expected_status, relevant_gates=relevant)

    if not isinstance(codes_raw, Sequence) or isinstance(codes_raw, (str, bytes)):
        collector.add(
            FindingKind.JURISDICTION_SET_MISMATCH,
            GATE_EXACT_SET,
            "jurisdictions must be a list of postal codes",
        )
        return collector.verdict(expected_status=expected_status, relevant_gates=relevant)

    try:
        validate_jurisdiction_set(codes_raw)
    except JurisdictionSetError as exc:
        codes = {str(c).strip().upper() for c in codes_raw if str(c).strip()}
        # Subset of the sealed set (missing codes, no extras outside the set).
        if codes < CANONICAL_JURISDICTIONS:
            collector.add(
                FindingKind.SUBSET_MANIFEST,
                GATE_SUBSET_MANIFEST,
                (
                    f"jurisdiction set is a subset of the sealed 51 "
                    f"(count={len(codes)}): {exc}"
                ),
            )
        collector.add(
            FindingKind.JURISDICTION_SET_MISMATCH,
            GATE_EXACT_SET,
            str(exc),
        )

    # Claimed complete with includes_dc=false is always opt-in / incomplete.
    if payload.get("includes_dc") is False and "DC" not in {
        str(c).strip().upper() for c in codes_raw if str(c).strip()
    }:
        if FindingKind.OPT_IN_DC.value not in collector.kinds():
            # Prefer opt-in labeling when the payload used the legacy flag path.
            if payload.get("include_dc") is False or str(
                payload.get("states_token") or ""
            ).lower() in {"all", "50", "states"}:
                collector.add(
                    FindingKind.OPT_IN_DC,
                    GATE_OPT_IN_DC,
                    "includes_dc=false rejects production completion",
                )

    return collector.verdict(expected_status=expected_status, relevant_gates=relevant)


def evaluate_corpus_manifest(
    manifest: Mapping[str, Any],
    *,
    case_id: str = "corpus_manifest",
    expected_status: Optional[str] = None,
) -> CompletenessVerdict:
    """Evaluate a multi-jurisdiction completion / admission manifest.

    Rejects subset coverage, opt-in DC, requested-scope ``is_complete``, and
    any jurisdiction set other than the exact sealed 51.
    """

    payload = _require_mapping(manifest, "manifest")
    collector = _FindingCollector(case_id=case_id)
    relevant = {
        GATE_EXACT_SET,
        GATE_OPT_IN_DC,
        GATE_SUBSET_MANIFEST,
        GATE_DISPOSITION,
        GATE_FRONTIER,
        GATE_SOURCE_QUALITY,
        GATE_NO_TRUNCATION,
        GATE_FAILED_FINAL,
        GATE_REPLAY,
        GATE_DERIVED_KEY_PARITY,
        GATE_CHECKPOINT,
    }

    # DC / exact-set policy at the manifest root.
    if is_opt_in_dc_policy(payload):
        collector.add(
            FindingKind.OPT_IN_DC,
            GATE_OPT_IN_DC,
            "manifest uses opt-in DC policy; DC is required in the sealed 51-set",
        )

    codes_raw = (
        payload.get("jurisdictions")
        or payload.get("jurisdiction_codes")
        or payload.get("states")
    )
    jurisdiction_receipts = payload.get("jurisdiction_receipts") or payload.get("receipts")

    codes: list[str] = []
    if isinstance(codes_raw, Sequence) and not isinstance(codes_raw, (str, bytes)):
        codes = [str(c).strip().upper() for c in codes_raw if str(c).strip()]
    elif isinstance(jurisdiction_receipts, Sequence) and not isinstance(
        jurisdiction_receipts, (str, bytes)
    ):
        for item in jurisdiction_receipts:
            if isinstance(item, Mapping) and item.get("jurisdiction"):
                codes.append(str(item.get("jurisdiction")).strip().upper())

    if not codes:
        collector.add(
            FindingKind.JURISDICTION_SET_MISMATCH,
            GATE_EXACT_SET,
            "manifest has no jurisdictions list",
        )
    else:
        unique = list(dict.fromkeys(codes))
        code_set = set(unique)
        if code_set != CANONICAL_JURISDICTIONS:
            if code_set < CANONICAL_JURISDICTIONS:
                collector.add(
                    FindingKind.SUBSET_MANIFEST,
                    GATE_SUBSET_MANIFEST,
                    (
                        f"manifest covers {len(code_set)} jurisdictions; "
                        f"exact {EXPECTED_JURISDICTION_COUNT} required"
                    ),
                )
            try:
                validate_jurisdiction_set(unique)
            except JurisdictionSetError as exc:
                collector.add(
                    FindingKind.JURISDICTION_SET_MISMATCH,
                    GATE_EXACT_SET,
                    str(exc),
                )

    # Requested-scope / incomplete publish claims.
    if payload.get("requested_scope_is_complete") is True:
        collector.add(
            FindingKind.REQUESTED_SCOPE_COMPLETION,
            GATE_SUBSET_MANIFEST,
            "requested_scope_is_complete cannot authorize full-corpus admission",
        )
    if payload.get("is_complete") is True and codes:
        code_set = {c for c in codes}
        if code_set != CANONICAL_JURISDICTIONS:
            collector.add(
                FindingKind.SUBSET_MANIFEST,
                GATE_SUBSET_MANIFEST,
                "is_complete=true on a non-exact-51 jurisdiction set",
            )

    # Optional aggregate disposition.
    if isinstance(payload.get("disposition"), Mapping):
        ok, detail = reconcile_disposition(payload["disposition"])  # type: ignore[index]
        if not ok:
            collector.add(
                FindingKind.DISPOSITION_ARITHMETIC_MISMATCH,
                GATE_DISPOSITION,
                detail,
            )
        failed_final = payload["disposition"].get("failed_final")  # type: ignore[index]
        if (
            isinstance(failed_final, int)
            and not isinstance(failed_final, bool)
            and failed_final > 0
        ):
            collector.add(
                FindingKind.FAILED_FINAL_NONZERO,
                GATE_FAILED_FINAL,
                f"aggregate failed_final={failed_final} blocks corpus admission",
            )

    # Nested per-jurisdiction receipts.
    if isinstance(jurisdiction_receipts, Sequence) and not isinstance(
        jurisdiction_receipts, (str, bytes)
    ):
        for idx, item in enumerate(jurisdiction_receipts):
            if not isinstance(item, Mapping):
                collector.add(
                    FindingKind.MISSING_REQUIRED_FIELD,
                    GATE_DISPOSITION,
                    f"jurisdiction_receipts[{idx}] must be a mapping",
                )
                continue
            sub = evaluate_jurisdiction_receipt(
                item,
                case_id=f"{case_id}/jurisdiction_receipts[{idx}]",
            )
            for finding in sub.findings:
                if finding.severity != "error":
                    continue
                # Avoid duplicating kinds that the parent already recorded for set policy.
                collector.findings.append(finding)

    # Derived-key parity at corpus level.
    _evaluate_derived_key_parity(collector, payload)

    return collector.verdict(expected_status=expected_status, relevant_gates=relevant)


def evaluate_completion_receipt(
    receipt: Mapping[str, Any],
    *,
    kind: Optional[str] = None,
    case_id: str = "completion_receipt",
    expected_status: Optional[str] = None,
) -> CompletenessVerdict:
    """Dispatch a completion receipt by kind to the appropriate evaluator."""

    payload = _require_mapping(receipt, "receipt")
    resolved_kind = (
        str(kind or payload.get("kind") or "").strip().lower().replace("-", "_")
    )
    if not resolved_kind:
        # Heuristic: multi-jurisdiction manifests vs single jurisdiction.
        if any(
            key in payload
            for key in (
                "jurisdictions",
                "jurisdiction_codes",
                "jurisdiction_receipts",
                "states",
                "dc_policy",
                "include_dc",
            )
        ) and "jurisdiction" not in payload:
            resolved_kind = "corpus_manifest"
        elif "jurisdiction" in payload:
            resolved_kind = "jurisdiction_receipt"
        else:
            resolved_kind = "corpus_manifest"

    if resolved_kind in {"jurisdiction_set", "exact_set", "jurisdiction_set_receipt"}:
        return evaluate_jurisdiction_set_receipt(
            payload, case_id=case_id, expected_status=expected_status
        )
    if resolved_kind in {
        "corpus_manifest",
        "manifest",
        "subset_manifest",
        "corpus",
        "aggregate",
    }:
        return evaluate_corpus_manifest(
            payload, case_id=case_id, expected_status=expected_status
        )
    return evaluate_jurisdiction_receipt(
        payload, case_id=case_id, expected_status=expected_status
    )


def evaluate_fixture_case(case: Mapping[str, Any]) -> CompletenessVerdict:
    """Evaluate one sealed completion-receipts fixture case."""

    payload = _require_mapping(case, "case")
    case_id = str(payload.get("case_id") or "unknown")
    kind = str(payload.get("kind") or "").strip().lower()
    expected_status = payload.get("expected_status")
    expected_status_s = str(expected_status) if expected_status is not None else None
    receipt = _require_mapping(payload.get("receipt"), f"cases[{case_id}].receipt")
    return evaluate_completion_receipt(
        receipt,
        kind=kind or None,
        case_id=case_id,
        expected_status=expected_status_s,
    )


def require_complete(
    receipt: Mapping[str, Any],
    *,
    kind: Optional[str] = None,
    case_id: str = "require_complete",
) -> CompletenessVerdict:
    """Evaluate *receipt* and raise if it is not complete/admitted."""

    verdict = evaluate_completion_receipt(receipt, kind=kind, case_id=case_id)
    if not verdict.complete:
        kinds = ", ".join(verdict.kinds) if verdict.kinds else "incomplete"
        raise CompletenessAdmissionError(
            f"{case_id} failed completion admission ({kinds})"
        )
    return verdict


# ---------------------------------------------------------------------------
# Fixture load / expand
# ---------------------------------------------------------------------------


def load_completion_receipts_fixture(
    path: Optional[PathLike] = None,
) -> dict[str, Any]:
    """Load and minimally validate the sealed completion-receipts fixture."""

    fixture_path = Path(path).expanduser().resolve() if path else default_fixture_path()
    if not fixture_path.is_file():
        raise FixtureSchemaError(f"completion receipts fixture missing: {fixture_path}")
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureSchemaError(f"invalid fixture JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise FixtureSchemaError("fixture root must be a JSON object")
    schema = payload.get("schema")
    if schema != FIXTURE_SCHEMA:
        raise FixtureSchemaError(
            f"fixture schema must be {FIXTURE_SCHEMA!r}, got {schema!r}"
        )
    if payload.get("task_id") != TASK_ID:
        raise FixtureSchemaError(
            f"fixture task_id must be {TASK_ID!r}, got {payload.get('task_id')!r}"
        )
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise FixtureSchemaError("fixture cases must be a non-empty list")
    for idx, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise FixtureSchemaError(f"cases[{idx}] must be a mapping")
        if not case.get("case_id"):
            raise FixtureSchemaError(f"cases[{idx}].case_id is required")
        if not isinstance(case.get("receipt"), Mapping):
            raise FixtureSchemaError(f"cases[{idx}].receipt must be a mapping")
    return payload


def run_fixture_oracle(
    path: Optional[PathLike] = None,
) -> dict[str, Any]:
    """Evaluate every sealed fixture case and return a structured report."""

    payload = load_completion_receipts_fixture(path)
    results: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    for case in payload["cases"]:
        verdict = evaluate_fixture_case(case)
        results.append(verdict.to_dict())
        expected_status = case.get("expected_status")
        expected_kinds = case.get("expected_kinds") or []
        if expected_status is not None and verdict.status != str(expected_status):
            mismatches.append(
                {
                    "case_id": verdict.case_id,
                    "problem": "status_mismatch",
                    "expected": expected_status,
                    "actual": verdict.status,
                }
            )
        if expected_kinds:
            expected_set = {FindingKind.coerce(k).value for k in expected_kinds}
            actual_set = set(verdict.kinds)
            missing = sorted(expected_set - actual_set)
            if missing:
                mismatches.append(
                    {
                        "case_id": verdict.case_id,
                        "problem": "missing_expected_kinds",
                        "missing": missing,
                        "actual": list(verdict.kinds),
                    }
                )
    return {
        "schema": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "fixture_schema": FIXTURE_SCHEMA,
        "case_count": len(results),
        "results": results,
        "mismatches": mismatches,
        "ok": not mismatches,
    }


def assert_fixture_oracle(path: Optional[PathLike] = None) -> dict[str, Any]:
    """Run the sealed fixture oracle and raise if any case mismatches."""

    report = run_fixture_oracle(path)
    if not report["ok"]:
        raise CompletenessAdmissionError(
            f"completion fixture oracle mismatches: {report['mismatches']!r}"
        )
    return report


# ---------------------------------------------------------------------------
# Convenience builders for tests
# ---------------------------------------------------------------------------


def closed_jurisdiction_receipt(
    jurisdiction: str = "MN",
    *,
    discovered: int = 10,
    fetched: int = 8,
    excluded: int = 1,
    quarantined: int = 1,
    failed_final: int = 0,
    duplicates: int = 0,
    official_source: bool = True,
    source_authority_class: str = "official",
    source_domain: str = "www.revisor.mn.gov",
    sample_cap: Any = None,
    runtime_caps: Any = None,
    frontier_closed: bool = True,
    partial_checkpoint: bool = False,
    promoted_success: bool = False,
    completion_basis: str = "source_frontier",
    status: str = "success",
    canonical_keys: Optional[Sequence[str]] = None,
    derived_keys: Optional[Sequence[str]] = None,
    stale_keys: Optional[Sequence[str]] = None,
    replay: Optional[Mapping[str, Any]] = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a jurisdiction receipt with defaults that pass the oracle."""

    keys = list(canonical_keys) if canonical_keys is not None else ["k1", "k2", "k3"]
    dkeys = list(derived_keys) if derived_keys is not None else list(keys)
    payload: dict[str, Any] = {
        "jurisdiction": jurisdiction,
        "status": status,
        "source_domain": source_domain,
        "official_source": official_source,
        "source_authority_class": source_authority_class,
        "mode": "full",
        "runtime_caps": runtime_caps,
        "sample_cap": sample_cap,
        "checkpoint": {
            "partial": partial_checkpoint,
            "promoted_success": promoted_success,
            "completion_basis": completion_basis,
        },
        "frontier": {
            "closed": frontier_closed,
            "enumerator_closed": frontier_closed,
            "unvisited_continuation_links": [],
            "expected_index_units": 3,
            "visited_index_units": 3 if frontier_closed else 1,
        },
        "boundary_probes": {
            "first_hierarchy_unit": "title-1",
            "last_hierarchy_unit": "title-3",
            "pagination_total": 3,
            "bundle_total": 1,
        },
        "disposition": {
            "discovered": discovered,
            "fetched": fetched,
            "excluded": excluded,
            "quarantined": quarantined,
            "failed_final": failed_final,
            "duplicates": duplicates,
        },
        "row_count": fetched,
        "index_keys": {
            "canonical_keys": keys,
            "derived_keys": dkeys,
            "stale_keys": list(stale_keys or []),
            "parity_ok": set(keys) == set(dkeys) and not stale_keys,
        },
    }
    if replay is not None:
        payload["replay"] = dict(replay)
    payload.update(extra)
    return payload


def exact_51_manifest(
    *,
    status: str = "success",
    include_dc: bool = True,
    dc_policy: str = "required",
    is_complete: bool = True,
    requested_scope_is_complete: bool = False,
    jurisdictions: Optional[Sequence[str]] = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a corpus manifest defaulting to the exact sealed 51-set."""

    codes = (
        list(jurisdictions)
        if jurisdictions is not None
        else list(canonical_jurisdiction_codes())
    )
    if not include_dc:
        codes = [c for c in codes if c != "DC"]
    payload: dict[str, Any] = {
        "status": status,
        "jurisdictions": codes,
        "includes_dc": "DC" in codes,
        "include_dc": include_dc,
        "dc_policy": dc_policy,
        "states_token": "all",
        "is_complete": is_complete,
        "requested_scope_is_complete": requested_scope_is_complete,
        "jurisdiction_count": len(codes),
    }
    payload.update(extra)
    return payload


__all__ = [
    "SCHEMA_VERSION",
    "FIXTURE_SCHEMA",
    "TASK_ID",
    "GOAL_ID",
    "PROGRAM_ID",
    "EXPECTED_JURISDICTION_COUNT",
    "CANONICAL_JURISDICTIONS",
    "CANONICAL_JURISDICTION_ORDER",
    "SOURCE_FRONTIER_COMPLETION_BASES",
    "UNSAFE_COMPLETION_BASES",
    "ALL_GATES",
    "GATE_EXACT_SET",
    "GATE_OPT_IN_DC",
    "GATE_SUBSET_MANIFEST",
    "GATE_DISPOSITION",
    "GATE_FRONTIER",
    "GATE_SOURCE_QUALITY",
    "GATE_NO_TRUNCATION",
    "GATE_FAILED_FINAL",
    "GATE_REPLAY",
    "GATE_DERIVED_KEY_PARITY",
    "GATE_CHECKPOINT",
    "StateLawsCompletenessError",
    "JurisdictionSetError",
    "CompletenessAdmissionError",
    "FixtureSchemaError",
    "FindingKind",
    "CompletenessFinding",
    "CompletenessVerdict",
    "repository_root",
    "default_fixture_path",
    "canonical_jurisdiction_codes",
    "normalize_postal_code",
    "validate_jurisdiction_set",
    "is_opt_in_dc_policy",
    "reconcile_disposition",
    "source_authority_class",
    "has_explicit_official_source_authority",
    "evaluate_jurisdiction_receipt",
    "evaluate_jurisdiction_set_receipt",
    "evaluate_corpus_manifest",
    "evaluate_completion_receipt",
    "evaluate_fixture_case",
    "require_complete",
    "load_completion_receipts_fixture",
    "run_fixture_oracle",
    "assert_fixture_oracle",
    "closed_jurisdiction_receipt",
    "exact_51_manifest",
]
