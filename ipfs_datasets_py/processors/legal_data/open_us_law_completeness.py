"""Exhaustive 50-state-plus-DC completeness oracle (OUL-003).

Fail-closed gates for declaring a jurisdiction or exact-51 corpus complete.
Nonzero row counts, requested-scope success flags, fixture transports, and
partial checkpoints are explicitly insufficient.

Gates
-----
1. **Exact set** — the aggregate jurisdiction set must equal the sealed 51
   codes (50 postal states + ``DC``). Puerto Rico, federal, and other
   extras are forbidden in the default configuration. DC is counted once.
2. **Disposition reconciliation** —
   ``discovered = fetched + excluded + quarantined + failed_final``.
3. **Frontier closure** — a closed official bundle **or** a closed
   pagination/TOC/continuation enumerator, with no remaining members or
   unvisited links.
4. **Failed-final** — ``failed_final == 0``.
5. **Replayable hashes** — request, response, and admitted-body SHA-256
   values must be present and equal the replayed hashes (and the replayed
   frontier digest).
6. **No truncation / fixture transport** — full mode forbids sample and
   runtime caps, fixture/synthetic/mock transports, and partial-checkpoint
   promotion.
7. **Aggregate parity** — the aggregate logical-key set and key/body/
   frontier digests must equal the deduplicated union of the jurisdiction
   receipts; corpus/BM25/vector/graph/locator/descriptor key sets match.
8. **Identity and evidence** — official host/path, edition, legal as-of,
   independent observation time, CIDs, unique logical keys, typed
   exclusion/quarantine evidence, and navigation/footer/placeholder
   rejection.

This module performs no network I/O. Downstream scrapers and certifiers
feed typed receipts; the oracle returns structured verdicts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Iterable, Mapping, Optional, Sequence, Union

# ---------------------------------------------------------------------------
# Schema identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "open-us-law-completeness-oracle-v1"
RECEIPT_SCHEMA_VERSION: Final = "open-us-law-full-scrape-receipt-v1"
RECEIPT_SCHEMA_ID: Final = "ipfs_datasets_py/open-us-law-full-scrape-receipt@1"
TASK_ID: Final = "OUL-003"
GOAL_ID: Final = "OUL-G010"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "open_us_law_completeness.py"
EXPECTED_JURISDICTION_COUNT: Final = 51
DEFAULT_CODE_FAMILY: Final = "statutes"
DEFAULT_CONFIGURATION: Final = "state_statutes_exact_51"

DEFAULT_RECEIPT_SCHEMA_RELATIVE_PATH: Final = Path(
    "data/legal/open_us_law/full_scrape_receipt.schema.json"
)

# Name-alpha postal states, then DC last (matches sealed release policy).
CANONICAL_JURISDICTION_ORDER: Final = (
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
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
    "DC",
)
CANONICAL_JURISDICTIONS: Final = frozenset(CANONICAL_JURISDICTION_ORDER)

FORBIDDEN_DEFAULT_JURISDICTIONS: Final = frozenset(
    {"PR", "US", "FED", "USA", "FEDERAL", "GU", "VI", "AS", "MP"}
)
FORBIDDEN_DEFAULT_CODE_FAMILIES: Final = frozenset(
    {
        "federal",
        "uscode",
        "constitution",
        "constitutions",
        "recovery",
        "quarantine",
        "historical",
    }
)

SOURCE_FRONTIER_COMPLETION_BASES: Final = frozenset(
    {"source_frontier", "frontier", "official_frontier"}
)
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
        "fixture",
        "synthetic",
    }
)
FIXTURE_TRANSPORT_KINDS: Final = frozenset(
    {
        "fixture",
        "fixtures",
        "mock",
        "mocked",
        "synthetic",
        "cassette",
        "vcr",
        "recorded_fixture",
        "golden",
        "stub",
        "unit_fixture",
    }
)
ALLOWED_TRANSPORT_KINDS: Final = frozenset(
    {
        "live_https",
        "official_https",
        "official_bundle",
        "bundle_https",
        "https",
    }
)
MUTABLE_TIME_TOKENS: Final = frozenset(
    {"latest", "current", "live", "now", "main", "head", "today"}
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
FAMILY_KEY_FIELDS: Final = (
    "corpus_keys",
    "bm25_keys",
    "vector_keys",
    "graph_keys",
    "locator_keys",
    "descriptor_keys",
)

SHA256_HEX_LENGTH: Final = 64
CID_V1_PREFIX: Final = "b"

GATE_EXACT_SET: Final = "exact_set"
GATE_OPT_IN_DC: Final = "opt_in_dc"
GATE_SUBSET_MANIFEST: Final = "subset_manifest"
GATE_DISPOSITION: Final = "disposition_reconciliation"
GATE_FRONTIER: Final = "frontier_closure"
GATE_SOURCE_QUALITY: Final = "source_quality"
GATE_NO_TRUNCATION: Final = "no_truncation"
GATE_FAILED_FINAL: Final = "failed_final"
GATE_REPLAY: Final = "replay"
GATE_KEY_DIGEST_PARITY: Final = "aggregate_key_digest_parity"
GATE_CHECKPOINT: Final = "checkpoint_promotion"
GATE_FIXTURE_TRANSPORT: Final = "fixture_transport"
GATE_IDENTITY: Final = "identity"
GATE_CIDS: Final = "cids"
GATE_TEXT_QUALITY: Final = "text_quality"
GATE_TYPED_EVIDENCE: Final = "typed_evidence"
GATE_DEFAULT_EXCLUSIONS: Final = "default_exclusions"

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
        GATE_KEY_DIGEST_PARITY,
        GATE_CHECKPOINT,
        GATE_FIXTURE_TRANSPORT,
        GATE_IDENTITY,
        GATE_CIDS,
        GATE_TEXT_QUALITY,
        GATE_TYPED_EVIDENCE,
        GATE_DEFAULT_EXCLUSIONS,
    }
)

JURISDICTION_GATES: Final = frozenset(
    {
        GATE_DISPOSITION,
        GATE_FRONTIER,
        GATE_SOURCE_QUALITY,
        GATE_NO_TRUNCATION,
        GATE_FAILED_FINAL,
        GATE_REPLAY,
        GATE_KEY_DIGEST_PARITY,
        GATE_CHECKPOINT,
        GATE_FIXTURE_TRANSPORT,
        GATE_IDENTITY,
        GATE_CIDS,
        GATE_TEXT_QUALITY,
        GATE_TYPED_EVIDENCE,
        GATE_DEFAULT_EXCLUSIONS,
    }
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OpenUsLawCompletenessError(ValueError):
    """Base error for Open US Law completeness oracle failures."""


class JurisdictionSetError(OpenUsLawCompletenessError):
    """Raised when the jurisdiction set is not exactly the sealed 51-set."""


class CompletenessAdmissionError(OpenUsLawCompletenessError):
    """Raised when require_* helpers reject an incomplete receipt."""


class ReceiptSchemaError(OpenUsLawCompletenessError):
    """Raised when the full-scrape receipt schema or instance is malformed."""


# ---------------------------------------------------------------------------
# Finding kinds
# ---------------------------------------------------------------------------


class FindingKind(str, Enum):
    """Stable finding identifiers emitted by the oracle."""

    SUBSET_MANIFEST = "subset_manifest"
    OPT_IN_DC = "opt_in_dc"
    OPEN_FRONTIER = "open_frontier"
    ENUMERATOR_NOT_CLOSED = "enumerator_not_closed"
    UNVISITED_CONTINUATION_LINKS = "unvisited_continuation_links"
    BUNDLE_FRONTIER_OPEN = "bundle_frontier_open"
    PAGINATION_FRONTIER_OPEN = "pagination_frontier_open"
    FAILED_FINAL_NONZERO = "failed_final_nonzero"
    SAMPLE_CAP_PRESENT = "sample_cap_present"
    RUNTIME_CAP_PRESENT = "runtime_cap_present"
    FIXTURE_TRANSPORT = "fixture_transport"
    SYNTHETIC_RECEIPT = "synthetic_receipt"
    PARTIAL_CHECKPOINT_PROMOTED = "partial_checkpoint_promoted"
    STALE_INDEX_KEYS = "stale_index_keys"
    DERIVED_KEY_PARITY_MISMATCH = "derived_key_parity_mismatch"
    AGGREGATE_KEY_MISMATCH = "aggregate_key_mismatch"
    AGGREGATE_DIGEST_MISMATCH = "aggregate_digest_mismatch"
    FAMILY_KEY_PARITY_MISMATCH = "family_key_parity_mismatch"
    JURISDICTION_SET_MISMATCH = "jurisdiction_set_mismatch"
    DISPOSITION_ARITHMETIC_MISMATCH = "disposition_arithmetic_mismatch"
    UNOFFICIAL_SOURCE = "unofficial_source"
    REPLAY_MISMATCH = "replay_mismatch"
    MISSING_RESPONSE_HASHES = "missing_response_hashes"
    REQUESTED_SCOPE_COMPLETION = "requested_scope_completion"
    SUCCESS_WITHOUT_CLOSURE = "success_without_closure"
    MISSING_BOUNDARY_PROBES = "missing_boundary_probes"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    NONZERO_COUNT_INSUFFICIENT = "nonzero_count_insufficient"
    PR_OR_FEDERAL_IN_DEFAULT = "pr_or_federal_in_default"
    DC_NOT_EXACTLY_ONCE = "dc_not_exactly_once"
    MISSING_IDENTITY = "missing_identity"
    MISSING_CIDS = "missing_cids"
    DUPLICATE_LOGICAL_KEYS = "duplicate_logical_keys"
    MISSING_TYPED_EVIDENCE = "missing_typed_evidence"
    TEXT_QUALITY_FAILURE = "text_quality_failure"
    MUTABLE_TIMESTAMP = "mutable_timestamp"

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
            "fixture": cls.FIXTURE_TRANSPORT,
            "synthetic": cls.SYNTHETIC_RECEIPT,
            "response_hash_mismatch": cls.REPLAY_MISMATCH,
            "digest_mismatch": cls.AGGREGATE_DIGEST_MISMATCH,
            "key_mismatch": cls.AGGREGATE_KEY_MISMATCH,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise OpenUsLawCompletenessError(f"unknown finding kind: {value!r}")


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OpenUsLawCompletenessError(f"{name} must be a mapping")
    return value


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpenUsLawCompletenessError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise OpenUsLawCompletenessError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise OpenUsLawCompletenessError(f"{name} exceeds maximum length {maximum}")
    return text


def _as_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OpenUsLawCompletenessError(f"{name} must be a non-negative integer")
    if value < 0:
        raise OpenUsLawCompletenessError(f"{name} must be a non-negative integer")
    return value


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        raise OpenUsLawCompletenessError("expected a sequence of strings")
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _truthy_cap(value: Any) -> bool:
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


def _looks_sha256(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip().lower()
    return len(text) == SHA256_HEX_LENGTH and all(
        ch in "0123456789abcdef" for ch in text
    )


def _looks_cid_v1(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if len(text) < 21 or not text.startswith(CID_V1_PREFIX):
        return False
    alphabet = set("abcdefghijklmnopqrstuvwxyz234567")
    return all(ch in alphabet for ch in text[1:])


def _normalize_sha256(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    return text if _looks_sha256(text) else (text or None)


def _is_mutable_time(value: Any) -> bool:
    text = str(value or "").strip().lower().replace("-", "_")
    return text in MUTABLE_TIME_TOKENS


def sha256_text(value: str) -> str:
    """Return the SHA-256 hex digest of a UTF-8 string."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json_digest(value: Any) -> str:
    """Return SHA-256 of canonical JSON (sorted keys, compact separators)."""

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256_text(payload)


def digest_sorted_strings(values: Iterable[str]) -> str:
    """Return SHA-256 of the sorted unique string list."""

    unique = sorted({str(item) for item in values if str(item)})
    return canonical_json_digest(unique)


def fake_cid(label: str) -> str:
    """Return a deterministic CIDv1-shaped token for builders and tests."""

    digest = sha256_text(label)
    mapped: list[str] = []
    for ch in digest:
        if ch.isdigit():
            mapped.append("abcdefghij"[int(ch)])
        else:
            mapped.append(ch)
    return "b" + "".join(mapped) + "aaaa"


# ---------------------------------------------------------------------------
# Path / schema loading
# ---------------------------------------------------------------------------


def repository_root() -> Path:
    """Return the repository root that contains ``data/legal``."""

    return Path(__file__).resolve().parents[3]


def receipt_schema_path(repo_root: Optional[PathLike] = None) -> Path:
    """Return the sealed full-scrape receipt schema path."""

    root = Path(repo_root) if repo_root is not None else repository_root()
    return (root / DEFAULT_RECEIPT_SCHEMA_RELATIVE_PATH).resolve()


def load_receipt_schema(path: Optional[PathLike] = None) -> dict[str, Any]:
    """Load the sealed full-scrape receipt JSON Schema."""

    schema_path = Path(path).expanduser().resolve() if path else receipt_schema_path()
    if not schema_path.is_file():
        raise ReceiptSchemaError(f"full-scrape receipt schema missing: {schema_path}")
    try:
        payload = json.loads(schema_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReceiptSchemaError(f"invalid receipt schema JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReceiptSchemaError("receipt schema root must be a JSON object")
    if payload.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise ReceiptSchemaError("receipt schema must declare JSON Schema 2020-12")
    if payload.get("title") != "Open US Law Full Scrape Receipt v1":
        raise ReceiptSchemaError("receipt schema title is not the sealed OUL title")
    return payload


def validate_receipt_schema(
    receipt: Mapping[str, Any],
    *,
    schema: Optional[Mapping[str, Any]] = None,
) -> None:
    """Validate *receipt* against the sealed JSON Schema.

    Uses ``jsonschema.Draft202012Validator`` when available. A missing
    library is reported as a capability gap rather than a silent skip.
    """

    payload = _require_mapping(receipt, "receipt")
    resolved = schema if schema is not None else load_receipt_schema()
    try:
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import SchemaError, ValidationError
    except ImportError as exc:  # pragma: no cover - validation env ships jsonschema
        raise ReceiptSchemaError(
            "jsonschema is required to validate full-scrape receipts"
        ) from exc
    try:
        Draft202012Validator.check_schema(resolved)
        Draft202012Validator(resolved).validate(payload)
    except SchemaError as exc:
        raise ReceiptSchemaError(f"receipt schema itself is invalid: {exc}") from exc
    except ValidationError as exc:
        raise ReceiptSchemaError(f"receipt failed schema validation: {exc.message}") from exc


# ---------------------------------------------------------------------------
# Jurisdiction set
# ---------------------------------------------------------------------------


def canonical_jurisdiction_codes() -> tuple[str, ...]:
    """Return the exact 51-jurisdiction set in canonical order (states then DC)."""

    codes = CANONICAL_JURISDICTION_ORDER
    if len(codes) != EXPECTED_JURISDICTION_COUNT:
        raise JurisdictionSetError(
            f"jurisdiction set invariant broken: expected "
            f"{EXPECTED_JURISDICTION_COUNT}, got {len(codes)}"
        )
    if codes.count("DC") != 1 or codes[-1] != "DC":
        raise JurisdictionSetError("jurisdiction set must include DC exactly once, last")
    if len(set(codes)) != len(codes):
        raise JurisdictionSetError("jurisdiction set contains duplicates")
    if set(codes) & FORBIDDEN_DEFAULT_JURISDICTIONS:
        raise JurisdictionSetError("canonical set must not include PR/federal extras")
    return codes


def is_forbidden_default_jurisdiction(code: str) -> bool:
    """Return True when *code* is forbidden in the exact-51 default set."""

    return str(code or "").strip().upper() in FORBIDDEN_DEFAULT_JURISDICTIONS


def normalize_postal_code(value: Any, *, name: str = "postal_code") -> str:
    """Normalize and validate a postal code against the exact 51-set."""

    text = _require_non_empty_str(value, name, maximum=8).upper()
    if len(text) != 2 or not text.isalpha():
        raise JurisdictionSetError(f"{name}={text!r} is not a two-letter postal code")
    if is_forbidden_default_jurisdiction(text):
        raise JurisdictionSetError(
            f"{name}={text!r} is forbidden in the exact-51 default set"
        )
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
    extras: list[str] = []
    for raw in codes:
        raw_text = str(raw or "").strip().upper()
        if is_forbidden_default_jurisdiction(raw_text):
            extras.append(raw_text)
            continue
        try:
            code = normalize_postal_code(raw, name=name)
        except JurisdictionSetError:
            extras.append(raw_text or str(raw))
            continue
        if code in seen:
            raise JurisdictionSetError(f"{name} contains duplicate postal code {code!r}")
        seen.add(code)
        normalized.append(code)
    actual = frozenset(normalized)
    if extras or actual != CANONICAL_JURISDICTIONS:
        missing = sorted(CANONICAL_JURISDICTIONS - actual)
        extra = sorted(set(extras) | (actual - CANONICAL_JURISDICTIONS))
        raise JurisdictionSetError(
            f"{name} must equal the exact 51-jurisdiction set; "
            f"missing={missing!r} extra={extra!r}"
        )
    if normalized.count("DC") != 1:
        raise JurisdictionSetError(f"{name} must count DC exactly once")
    if len(normalized) != EXPECTED_JURISDICTION_COUNT:
        raise JurisdictionSetError(
            f"{name} must contain exactly {EXPECTED_JURISDICTION_COUNT} unique codes, "
            f"got {len(normalized)}"
        )
    return tuple(canonical_jurisdiction_codes())


def is_opt_in_dc_policy(payload: Mapping[str, Any]) -> bool:
    """Return True when DC is treated as optional rather than required."""

    dc_policy = (
        str(payload.get("dc_policy") or payload.get("district_of_columbia_policy") or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
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
    states_token = str(payload.get("states_token") or payload.get("states") or "").strip().lower()
    include_dc = payload.get("include_dc")
    if states_token in {"all", "50", "states"} and include_dc is False:
        return True
    jurisdictions = payload.get("jurisdictions") or payload.get("jurisdiction_codes")
    if isinstance(jurisdictions, Sequence) and not isinstance(jurisdictions, (str, bytes)):
        codes = {str(c).strip().upper() for c in jurisdictions if str(c).strip()}
        if "DC" not in codes and payload.get("includes_dc") is False:
            if payload.get("dc_optional") is True or payload.get("opt_in_dc") is True:
                return True
            if dc_policy or states_token in {"all", "50", "states"}:
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
    """Oracle outcome for one receipt, manifest, or aggregate."""

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
# Disposition and digest helpers
# ---------------------------------------------------------------------------


def reconcile_disposition(disposition: Mapping[str, Any]) -> tuple[bool, str]:
    """Return ``(ok, detail)`` for disposition reconciliation."""

    if not isinstance(disposition, Mapping):
        return False, "disposition object missing"
    try:
        discovered = _as_non_negative_int(disposition.get("discovered"), "discovered")
        fetched = _as_non_negative_int(disposition.get("fetched"), "fetched")
        excluded = _as_non_negative_int(disposition.get("excluded"), "excluded")
        quarantined = _as_non_negative_int(disposition.get("quarantined"), "quarantined")
        failed_final = _as_non_negative_int(disposition.get("failed_final"), "failed_final")
    except OpenUsLawCompletenessError as exc:
        return False, str(exc)
    if "duplicates" in disposition and disposition.get("duplicates") is not None:
        try:
            _as_non_negative_int(disposition.get("duplicates"), "duplicates")
        except OpenUsLawCompletenessError as exc:
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


def _hash_block(receipt: Mapping[str, Any]) -> Mapping[str, Any]:
    block = receipt.get("hashes")
    if isinstance(block, Mapping):
        return block
    return receipt


def extract_request_hash(receipt: Mapping[str, Any]) -> Optional[str]:
    block = _hash_block(receipt)
    return _normalize_sha256(
        block.get("request_sha256") or receipt.get("request_hash") or receipt.get("request_sha256")
    )


def extract_response_hash(receipt: Mapping[str, Any]) -> Optional[str]:
    block = _hash_block(receipt)
    return _normalize_sha256(
        block.get("response_sha256")
        or receipt.get("response_hash")
        or receipt.get("response_sha256")
    )


def extract_body_hash(receipt: Mapping[str, Any]) -> Optional[str]:
    block = _hash_block(receipt)
    return _normalize_sha256(
        block.get("admitted_body_sha256")
        or receipt.get("admitted_body_hash")
        or receipt.get("body_hash")
        or receipt.get("admitted_body_sha256")
    )


def extract_frontier_digest(receipt: Mapping[str, Any]) -> Optional[str]:
    frontier = receipt.get("frontier")
    if isinstance(frontier, Mapping):
        digest = _normalize_sha256(
            frontier.get("frontier_digest_sha256") or frontier.get("digest")
        )
        if digest:
            return digest
    return _normalize_sha256(receipt.get("frontier_digest_sha256"))


def extract_canonical_keys(receipt: Mapping[str, Any]) -> list[str]:
    logical = receipt.get("logical_keys")
    if isinstance(logical, Mapping):
        keys = _as_str_list(logical.get("keys"))
        if keys:
            return keys
    block = receipt.get("index_keys")
    if isinstance(block, Mapping):
        keys = _as_str_list(block.get("canonical_keys") or block.get("logical_keys"))
        if keys:
            return keys
    return _as_str_list(receipt.get("canonical_keys") or receipt.get("logical_keys"))


def extract_jurisdiction_label(receipt: Mapping[str, Any]) -> str:
    raw = receipt.get("jurisdiction")
    return str(raw).strip().upper() if raw is not None else ""


def compute_aggregate_key_digest(receipts: Sequence[Mapping[str, Any]]) -> str:
    """Digest of the sorted unique union of jurisdiction logical keys."""

    keys: list[str] = []
    for item in receipts:
        keys.extend(extract_canonical_keys(item))
    return digest_sorted_strings(keys)


def compute_aggregate_body_digest(receipts: Sequence[Mapping[str, Any]]) -> str:
    """Digest of sorted ``(jurisdiction, admitted_body_sha256)`` pairs."""

    pairs: list[list[str]] = []
    for item in receipts:
        label = extract_jurisdiction_label(item)
        body = extract_body_hash(item) or ""
        pairs.append([label, body])
    pairs.sort()
    return canonical_json_digest(pairs)


def compute_aggregate_frontier_digest(receipts: Sequence[Mapping[str, Any]]) -> str:
    """Digest of sorted ``(jurisdiction, frontier_digest)`` pairs."""

    pairs: list[list[str]] = []
    for item in receipts:
        label = extract_jurisdiction_label(item)
        digest = extract_frontier_digest(item) or ""
        pairs.append([label, digest])
    pairs.sort()
    return canonical_json_digest(pairs)


def union_jurisdiction_keys(receipts: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return the sorted unique union of per-jurisdiction canonical keys."""

    keys: set[str] = set()
    for item in receipts:
        keys.update(extract_canonical_keys(item))
    return sorted(keys)


# ---------------------------------------------------------------------------
# Gate evaluators
# ---------------------------------------------------------------------------


def _evaluate_identity(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    code_family = str(receipt.get("code_family") or receipt.get("code_family_id") or "").strip()
    edition = receipt.get("edition")
    legal_as_of = receipt.get("legal_as_of") or receipt.get("as_of")
    observed_at = receipt.get("observed_at") or receipt.get("observation_time")
    missing: list[str] = []
    if not code_family:
        missing.append("code_family")
    if not edition or not str(edition).strip():
        missing.append("edition")
    if not legal_as_of or not str(legal_as_of).strip():
        missing.append("legal_as_of")
    if not observed_at or not str(observed_at).strip():
        missing.append("observed_at")
    if missing:
        collector.add(
            FindingKind.MISSING_IDENTITY,
            GATE_IDENTITY,
            f"missing identity fields: {missing}",
        )
    if code_family.lower() in FORBIDDEN_DEFAULT_CODE_FAMILIES:
        collector.add(
            FindingKind.PR_OR_FEDERAL_IN_DEFAULT,
            GATE_DEFAULT_EXCLUSIONS,
            f"code_family={code_family!r} is not admitted in the default exact-51 set",
        )
    for label, value in (("legal_as_of", legal_as_of), ("observed_at", observed_at), ("edition", edition)):
        if _is_mutable_time(value):
            collector.add(
                FindingKind.MUTABLE_TIMESTAMP,
                GATE_IDENTITY,
                f"{label} uses mutable token {value!r}",
            )


def _evaluate_source_quality(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    official = receipt.get("official_source")
    source_domain = str(receipt.get("source_domain") or "").strip().lower()
    authority = str(
        receipt.get("source_authority_class") or receipt.get("authority_class") or ""
    ).strip().lower()
    if official is False or authority in {"secondary", "unofficial", "mirror"}:
        collector.add(
            FindingKind.UNOFFICIAL_SOURCE,
            GATE_SOURCE_QUALITY,
            f"non-official source cannot admit success: domain={source_domain or '<missing>'}",
        )
        return
    if source_domain and _host_looks_secondary(source_domain):
        collector.add(
            FindingKind.UNOFFICIAL_SOURCE,
            GATE_SOURCE_QUALITY,
            f"source domain is secondary/mirror: {source_domain}",
        )
    source_path = receipt.get("source_path") or receipt.get("official_path")
    if not str(source_path or "").strip():
        collector.add(
            FindingKind.MISSING_REQUIRED_FIELD,
            GATE_SOURCE_QUALITY,
            "official source_path is required",
        )
    rights = receipt.get("rights") or receipt.get("source_rights")
    if not isinstance(rights, Mapping) or not str(rights.get("decision") or "").strip():
        collector.add(
            FindingKind.MISSING_REQUIRED_FIELD,
            GATE_SOURCE_QUALITY,
            "source-rights/attribution decision is required",
        )


def _evaluate_transport_and_caps(
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

    transport = receipt.get("transport")
    kind = ""
    fixture_flag = False
    synthetic_flag = False
    if isinstance(transport, str):
        kind = transport.strip().lower().replace("-", "_")
    elif isinstance(transport, Mapping):
        kind = str(transport.get("kind") or transport.get("type") or "").strip().lower()
        fixture_flag = transport.get("fixture") is True
        synthetic_flag = transport.get("synthetic") is True
    if receipt.get("synthetic") is True or receipt.get("synthetic_receipt") is True:
        synthetic_flag = True
    if receipt.get("fixture_transport") is True:
        fixture_flag = True
    if kind in FIXTURE_TRANSPORT_KINDS or fixture_flag:
        collector.add(
            FindingKind.FIXTURE_TRANSPORT,
            GATE_FIXTURE_TRANSPORT,
            f"fixture/mock transport is forbidden: kind={kind or '<flagged>'}",
        )
    if synthetic_flag:
        collector.add(
            FindingKind.SYNTHETIC_RECEIPT,
            GATE_FIXTURE_TRANSPORT,
            "synthetic receipts cannot satisfy full-scrape completeness",
        )
    if kind and kind not in ALLOWED_TRANSPORT_KINDS and kind not in FIXTURE_TRANSPORT_KINDS:
        collector.add(
            FindingKind.FIXTURE_TRANSPORT,
            GATE_FIXTURE_TRANSPORT,
            f"transport kind {kind!r} is not an allowed live official transport",
        )

    probes = receipt.get("boundary_probes")
    if not isinstance(probes, Mapping):
        collector.add(
            FindingKind.MISSING_BOUNDARY_PROBES,
            GATE_NO_TRUNCATION,
            "boundary_probes object missing",
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
        if probes.get("first_probe_ok") is False or probes.get("last_probe_ok") is False:
            collector.add(
                FindingKind.MISSING_BOUNDARY_PROBES,
                GATE_NO_TRUNCATION,
                "boundary probes did not succeed at both ends of the hierarchy",
            )


def _evaluate_checkpoint(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    checkpoint = receipt.get("checkpoint")
    status = str(receipt.get("status") or "").strip().lower()
    if not isinstance(checkpoint, Mapping):
        collector.add(
            FindingKind.PARTIAL_CHECKPOINT_PROMOTED,
            GATE_CHECKPOINT,
            "receipt missing checkpoint block",
        )
        return
    partial = bool(checkpoint.get("partial"))
    promoted = bool(checkpoint.get("promoted_success"))
    completion_basis = str(checkpoint.get("completion_basis") or "").strip().lower()
    if partial and promoted:
        collector.add(
            FindingKind.PARTIAL_CHECKPOINT_PROMOTED,
            GATE_CHECKPOINT,
            "partial checkpoint was promoted to success",
        )
        return
    if completion_basis in UNSAFE_COMPLETION_BASES:
        collector.add(
            FindingKind.PARTIAL_CHECKPOINT_PROMOTED,
            GATE_CHECKPOINT,
            f"completion_basis is not source frontier: {completion_basis}",
        )
    elif completion_basis and completion_basis not in SOURCE_FRONTIER_COMPLETION_BASES:
        collector.add(
            FindingKind.PARTIAL_CHECKPOINT_PROMOTED,
            GATE_CHECKPOINT,
            f"completion_basis is not source frontier: {completion_basis}",
        )
    elif not completion_basis:
        collector.add(
            FindingKind.PARTIAL_CHECKPOINT_PROMOTED,
            GATE_CHECKPOINT,
            "receipt missing checkpoint.completion_basis",
        )
    if status == "success" and partial:
        collector.add(
            FindingKind.PARTIAL_CHECKPOINT_PROMOTED,
            GATE_CHECKPOINT,
            "status=success with a partial checkpoint",
        )


def _declared_frontier_method(frontier: Mapping[str, Any]) -> str:
    method = str(frontier.get("method") or frontier.get("frontier_method") or "").strip().lower()
    method = method.replace("-", "_").replace(" ", "_")
    if method in {"bundle", "official_bundle"}:
        return "bundle"
    if method in {"pagination", "toc", "continuation", "page"}:
        return "pagination"
    if method in {"bundle_and_pagination", "both"}:
        return "both"
    if frontier.get("bundle_closed") is True and frontier.get("pagination_closed") is not True:
        return "bundle"
    if frontier.get("pagination_closed") is True:
        return "pagination"
    if frontier.get("closed") is True and frontier.get("enumerator_closed") is True:
        return "pagination"
    return ""


def _evaluate_frontier(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    frontier = receipt.get("frontier")
    status = str(receipt.get("status") or "").strip().lower()
    if not isinstance(frontier, Mapping):
        collector.add(
            FindingKind.OPEN_FRONTIER,
            GATE_FRONTIER,
            "receipt missing frontier block",
        )
        if status == "success":
            collector.add(
                FindingKind.SUCCESS_WITHOUT_CLOSURE,
                GATE_FRONTIER,
                "status=success with missing frontier",
            )
        return

    closed = frontier.get("closed")
    enumerator_closed = frontier.get("enumerator_closed")
    unvisited = _as_str_list(frontier.get("unvisited_continuation_links"))
    remaining_bundle = _as_str_list(
        frontier.get("remaining_bundle_members") or frontier.get("unvisited_bundle_members")
    )
    bundle_closed = frontier.get("bundle_closed")
    pagination_closed = frontier.get("pagination_closed")
    method = _declared_frontier_method(frontier)

    pagination_ok = (
        pagination_closed is True
        or (
            closed is True
            and enumerator_closed is True
            and not unvisited
            and method in {"", "pagination", "both"}
        )
    )
    if pagination_ok and enumerator_closed is False:
        pagination_ok = False
    if pagination_ok and unvisited:
        pagination_ok = False

    bundle_ok = bundle_closed is True and not remaining_bundle
    if bundle_ok:
        expected_members = frontier.get("bundle_member_count")
        enumerated = frontier.get("enumerated_member_count")
        if (
            isinstance(expected_members, int)
            and not isinstance(expected_members, bool)
            and isinstance(enumerated, int)
            and not isinstance(enumerated, bool)
            and enumerated < expected_members
        ):
            bundle_ok = False

    if method == "bundle":
        if not bundle_ok:
            collector.add(
                FindingKind.BUNDLE_FRONTIER_OPEN,
                GATE_FRONTIER,
                "declared bundle frontier is not closed",
            )
    elif method == "pagination":
        if not pagination_ok:
            collector.add(
                FindingKind.PAGINATION_FRONTIER_OPEN,
                GATE_FRONTIER,
                "declared pagination frontier is not closed",
            )
    elif method == "both":
        if not (bundle_ok or pagination_ok):
            collector.add(
                FindingKind.OPEN_FRONTIER,
                GATE_FRONTIER,
                "neither bundle nor pagination frontier is closed",
            )
    elif not (bundle_ok or pagination_ok):
        collector.add(
            FindingKind.OPEN_FRONTIER,
            GATE_FRONTIER,
            "frontier is not closed via bundle or pagination",
        )

    if closed is not True:
        collector.add(
            FindingKind.OPEN_FRONTIER,
            GATE_FRONTIER,
            "frontier.closed is not true",
        )
    if method in {"pagination", "both", ""} and enumerator_closed is not True:
        if FindingKind.ENUMERATOR_NOT_CLOSED.value not in collector.kinds():
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
    if remaining_bundle:
        collector.add(
            FindingKind.BUNDLE_FRONTIER_OPEN,
            GATE_FRONTIER,
            f"remaining bundle members: {remaining_bundle}",
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

    if status == "success" and (
        closed is not True or not (bundle_ok or pagination_ok)
    ):
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


def _evaluate_replay_hashes(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    request_h = extract_request_hash(receipt)
    response_h = extract_response_hash(receipt)
    body_h = extract_body_hash(receipt)
    frontier_d = extract_frontier_digest(receipt)
    missing: list[str] = []
    if not request_h:
        missing.append("request_sha256")
    if not response_h:
        missing.append("response_sha256")
    if not body_h:
        missing.append("admitted_body_sha256")
    if missing:
        collector.add(
            FindingKind.MISSING_RESPONSE_HASHES,
            GATE_REPLAY,
            f"replayable hashes missing: {missing}",
        )

    replay = receipt.get("replay")
    if not isinstance(replay, Mapping):
        collector.add(
            FindingKind.REPLAY_MISMATCH,
            GATE_REPLAY,
            "replay block required for replayable response hashes",
        )
        return
    if replay.get("upstream_change_delta") or replay.get("explicit_upstream_change"):
        return

    replay_request = _normalize_sha256(
        replay.get("request_sha256") or replay.get("request_hash")
    )
    replay_response = _normalize_sha256(
        replay.get("response_sha256")
        or replay.get("second_response_hash")
        or replay.get("second_digest")
        or replay.get("response_hash")
    )
    replay_body = _normalize_sha256(
        replay.get("admitted_body_sha256") or replay.get("body_hash")
    )
    replay_frontier = _normalize_sha256(
        replay.get("frontier_digest_sha256")
        or replay.get("second_frontier_digest")
        or replay.get("second_digest")
    )
    if not replay_request or not replay_response or not replay_body:
        collector.add(
            FindingKind.REPLAY_MISMATCH,
            GATE_REPLAY,
            "replay block present but request/response/body hashes missing",
        )
        return
    if request_h and replay_request != request_h:
        collector.add(
            FindingKind.REPLAY_MISMATCH,
            GATE_REPLAY,
            f"replay request hash differs: {replay_request!r} != {request_h!r}",
        )
    if response_h and replay_response != response_h:
        collector.add(
            FindingKind.REPLAY_MISMATCH,
            GATE_REPLAY,
            f"replay response hash differs: {replay_response!r} != {response_h!r}",
        )
    if body_h and replay_body != body_h:
        collector.add(
            FindingKind.REPLAY_MISMATCH,
            GATE_REPLAY,
            f"replay admitted-body hash differs: {replay_body!r} != {body_h!r}",
        )
    first_frontier = _normalize_sha256(
        replay.get("first_frontier_digest") or frontier_d
    )
    if first_frontier and replay_frontier and first_frontier != replay_frontier:
        collector.add(
            FindingKind.REPLAY_MISMATCH,
            GATE_REPLAY,
            f"replay frontier digests differ: {first_frontier!r} != {replay_frontier!r}",
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
        raise OpenUsLawCompletenessError(f"{name} must be a sequence of keys")
    out: set[str] = set()
    for item in value:
        text = str(item).strip()
        if text:
            out.add(text)
    return out


def _evaluate_logical_and_derived_keys(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    logical = receipt.get("logical_keys")
    if isinstance(logical, Mapping):
        keys = _as_str_list(logical.get("keys"))
        if len(keys) != len(set(keys)):
            collector.add(
                FindingKind.DUPLICATE_LOGICAL_KEYS,
                GATE_KEY_DIGEST_PARITY,
                "logical keys are not unique",
            )
        if logical.get("unique") is False:
            collector.add(
                FindingKind.DUPLICATE_LOGICAL_KEYS,
                GATE_KEY_DIGEST_PARITY,
                "logical_keys.unique is false",
            )
        disposition = str(logical.get("current_history_disposition") or "").strip().lower()
        if not disposition:
            collector.add(
                FindingKind.MISSING_REQUIRED_FIELD,
                GATE_KEY_DIGEST_PARITY,
                "logical keys missing current/history disposition",
            )

    block = receipt.get("index_keys")
    if block is None:
        if not any(
            key in receipt
            for key in ("canonical_keys", "derived_keys", "stale_keys", "logical_keys")
        ):
            if not isinstance(logical, Mapping):
                collector.add(
                    FindingKind.DERIVED_KEY_PARITY_MISMATCH,
                    GATE_KEY_DIGEST_PARITY,
                    "index_keys / logical_keys missing",
                )
            return
        block = receipt
    if not isinstance(block, Mapping):
        collector.add(
            FindingKind.DERIVED_KEY_PARITY_MISMATCH,
            GATE_KEY_DIGEST_PARITY,
            "index_keys must be a mapping",
        )
        return
    try:
        canonical = _normalize_key_set(
            block.get("canonical_keys") or block.get("logical_keys") or (
                logical.get("keys") if isinstance(logical, Mapping) else None
            ),
            name="canonical_keys",
        )
        derived = _normalize_key_set(
            block.get("derived_keys") or block.get("index_keys"),
            name="derived_keys",
        )
        stale = _normalize_key_set(block.get("stale_keys"), name="stale_keys")
    except OpenUsLawCompletenessError as exc:
        collector.add(
            FindingKind.DERIVED_KEY_PARITY_MISMATCH,
            GATE_KEY_DIGEST_PARITY,
            str(exc),
        )
        return
    if stale:
        collector.add(
            FindingKind.STALE_INDEX_KEYS,
            GATE_KEY_DIGEST_PARITY,
            f"stale index keys present: {sorted(stale)}",
        )
    if canonical or derived:
        if not canonical and derived:
            collector.add(
                FindingKind.DERIVED_KEY_PARITY_MISMATCH,
                GATE_KEY_DIGEST_PARITY,
                "derived_keys present without canonical_keys",
            )
        elif canonical and not derived:
            collector.add(
                FindingKind.DERIVED_KEY_PARITY_MISMATCH,
                GATE_KEY_DIGEST_PARITY,
                "canonical_keys present without derived_keys",
            )
        elif canonical != derived:
            missing = sorted(canonical - derived)
            extra = sorted(derived - canonical)
            collector.add(
                FindingKind.DERIVED_KEY_PARITY_MISMATCH,
                GATE_KEY_DIGEST_PARITY,
                (
                    "derived key set does not match canonical keys; "
                    f"missing_from_derived={missing!r} extra_in_derived={extra!r}"
                ),
            )
            if extra and FindingKind.STALE_INDEX_KEYS.value not in collector.kinds():
                collector.add(
                    FindingKind.STALE_INDEX_KEYS,
                    GATE_KEY_DIGEST_PARITY,
                    f"derived keys not in canonical set (stale/drift): {extra}",
                )
    if block.get("parity_ok") is False:
        if FindingKind.DERIVED_KEY_PARITY_MISMATCH.value not in collector.kinds():
            collector.add(
                FindingKind.DERIVED_KEY_PARITY_MISMATCH,
                GATE_KEY_DIGEST_PARITY,
                "index_keys.parity_ok is false",
            )


def _evaluate_cids(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    block = receipt.get("cids")
    source = None
    entry = None
    acquisition = None
    rights = None
    if isinstance(block, Mapping):
        source = block.get("source_cid")
        entry = block.get("entry_cid")
        acquisition = block.get("acquisition_receipt_cid")
        rights = block.get("rights_receipt_cid")
    else:
        source = receipt.get("source_cid")
        entry = receipt.get("entry_cid")
        acquisition = receipt.get("acquisition_receipt_cid")
        rights = receipt.get("rights_receipt_cid")
    missing: list[str] = []
    for label, value in (
        ("source_cid", source),
        ("entry_cid", entry),
        ("acquisition_receipt_cid", acquisition),
        ("rights_receipt_cid", rights),
    ):
        if not _looks_cid_v1(value) and not (
            isinstance(value, str) and value.startswith("sha256:") and _looks_sha256(value[7:])
        ):
            missing.append(label)
    if missing:
        collector.add(
            FindingKind.MISSING_CIDS,
            GATE_CIDS,
            f"required CIDs missing or malformed: {missing}",
        )


def _evaluate_text_quality(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    block = receipt.get("text_quality")
    if not isinstance(block, Mapping):
        collector.add(
            FindingKind.TEXT_QUALITY_FAILURE,
            GATE_TEXT_QUALITY,
            "text_quality block missing",
        )
        return
    if block.get("navigation_rejected") is not True:
        collector.add(
            FindingKind.TEXT_QUALITY_FAILURE,
            GATE_TEXT_QUALITY,
            "navigation chrome was not rejected",
        )
    if block.get("footer_rejected") is not True:
        collector.add(
            FindingKind.TEXT_QUALITY_FAILURE,
            GATE_TEXT_QUALITY,
            "footer chrome was not rejected",
        )
    if block.get("placeholder_rejected") is not True:
        collector.add(
            FindingKind.TEXT_QUALITY_FAILURE,
            GATE_TEXT_QUALITY,
            "placeholder text was not rejected",
        )
    if block.get("contaminated") is True:
        collector.add(
            FindingKind.TEXT_QUALITY_FAILURE,
            GATE_TEXT_QUALITY,
            "text_quality.contaminated is true",
        )
    min_chars = block.get("min_usable_chars")
    if (
        not isinstance(min_chars, int)
        or isinstance(min_chars, bool)
        or min_chars < 1
    ):
        collector.add(
            FindingKind.TEXT_QUALITY_FAILURE,
            GATE_TEXT_QUALITY,
            "min_usable_chars must be a positive integer",
        )


def _evaluate_typed_evidence(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    disposition = receipt.get("disposition")
    if not isinstance(disposition, Mapping):
        return
    excluded = disposition.get("excluded")
    quarantined = disposition.get("quarantined")
    exclusions = receipt.get("exclusions") or receipt.get("exclusion_evidence")
    quarantines = receipt.get("quarantines") or receipt.get("quarantine_evidence")

    def _valid_units(value: Any) -> bool:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return False
        if not value:
            return False
        for item in value:
            if not isinstance(item, Mapping):
                return False
            if not str(item.get("unit_id") or "").strip():
                return False
            if not str(item.get("reason") or "").strip():
                return False
            if not _looks_sha256(item.get("evidence_sha256") or item.get("evidence_hash")):
                return False
        return True

    if (
        isinstance(excluded, int)
        and not isinstance(excluded, bool)
        and excluded > 0
        and not _valid_units(exclusions)
    ):
        collector.add(
            FindingKind.MISSING_TYPED_EVIDENCE,
            GATE_TYPED_EVIDENCE,
            f"excluded={excluded} requires typed exclusion evidence",
        )
    if (
        isinstance(quarantined, int)
        and not isinstance(quarantined, bool)
        and quarantined > 0
        and not _valid_units(quarantines)
    ):
        collector.add(
            FindingKind.MISSING_TYPED_EVIDENCE,
            GATE_TYPED_EVIDENCE,
            f"quarantined={quarantined} requires typed quarantine evidence",
        )


def _evaluate_requested_scope_insufficiency(
    collector: _FindingCollector,
    receipt: Mapping[str, Any],
) -> None:
    status = str(receipt.get("status") or "").strip().lower()
    completion_claim = (
        str(receipt.get("completion_claim") or receipt.get("completion_proof") or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    if completion_claim in {
        "nonzero_count",
        "row_count",
        "requested_scope",
        "filename",
        "registry_success",
        "requested_scope_is_complete",
        "fixture",
        "synthetic",
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
    if receipt.get("nonzero_count_proves_completeness") is True:
        collector.add(
            FindingKind.NONZERO_COUNT_INSUFFICIENT,
            GATE_NO_TRUNCATION,
            "nonzero row counts are not authoritative completion proof",
        )
    if status == "success" and completion_claim in UNSAFE_COMPLETION_BASES:
        if FindingKind.REQUESTED_SCOPE_COMPLETION.value not in collector.kinds():
            collector.add(
                FindingKind.REQUESTED_SCOPE_COMPLETION,
                GATE_NO_TRUNCATION,
                f"status=success with insufficient completion_claim={completion_claim!r}",
            )


# ---------------------------------------------------------------------------
# Public evaluators
# ---------------------------------------------------------------------------


def evaluate_jurisdiction_receipt(
    receipt: Mapping[str, Any],
    *,
    case_id: str = "jurisdiction_receipt",
    expected_status: Optional[str] = None,
) -> CompletenessVerdict:
    """Evaluate one jurisdiction scrape receipt for full-scrape completion."""

    payload = _require_mapping(receipt, "receipt")
    jurisdiction: Optional[str] = None
    raw_jurisdiction = payload.get("jurisdiction")
    if raw_jurisdiction is not None and str(raw_jurisdiction).strip():
        raw_text = str(raw_jurisdiction).strip().upper()
        if is_forbidden_default_jurisdiction(raw_text):
            collector = _FindingCollector(case_id=case_id, jurisdiction=raw_text)
            collector.add(
                FindingKind.PR_OR_FEDERAL_IN_DEFAULT,
                GATE_DEFAULT_EXCLUSIONS,
                f"jurisdiction={raw_text!r} is forbidden in the default exact-51 set",
            )
            collector.add(
                FindingKind.JURISDICTION_SET_MISMATCH,
                GATE_EXACT_SET,
                f"jurisdiction={raw_text!r} is not in the exact 51-jurisdiction set",
            )
            return collector.verdict(
                expected_status=expected_status,
                relevant_gates=JURISDICTION_GATES | {GATE_EXACT_SET},
            )
        try:
            jurisdiction = normalize_postal_code(raw_jurisdiction, name="jurisdiction")
        except JurisdictionSetError as exc:
            collector = _FindingCollector(case_id=case_id, jurisdiction=raw_text)
            collector.add(
                FindingKind.JURISDICTION_SET_MISMATCH,
                GATE_EXACT_SET,
                str(exc),
                jurisdiction=raw_text,
            )
            return collector.verdict(
                expected_status=expected_status,
                relevant_gates=JURISDICTION_GATES | {GATE_EXACT_SET},
            )
    else:
        collector = _FindingCollector(case_id=case_id)
        collector.add(
            FindingKind.MISSING_IDENTITY,
            GATE_IDENTITY,
            "jurisdiction is required",
        )
        return collector.verdict(
            expected_status=expected_status,
            relevant_gates=JURISDICTION_GATES,
        )

    collector = _FindingCollector(case_id=case_id, jurisdiction=jurisdiction)
    _evaluate_identity(collector, payload)
    _evaluate_source_quality(collector, payload)
    _evaluate_transport_and_caps(collector, payload)
    _evaluate_checkpoint(collector, payload)
    _evaluate_frontier(collector, payload)
    _evaluate_disposition(collector, payload)
    _evaluate_replay_hashes(collector, payload)
    _evaluate_logical_and_derived_keys(collector, payload)
    _evaluate_cids(collector, payload)
    _evaluate_text_quality(collector, payload)
    _evaluate_typed_evidence(collector, payload)
    _evaluate_requested_scope_insufficiency(collector, payload)
    return collector.verdict(
        expected_status=expected_status,
        relevant_gates=JURISDICTION_GATES,
    )


def _extract_codes(payload: Mapping[str, Any]) -> list[str]:
    codes_raw = (
        payload.get("jurisdictions")
        or payload.get("jurisdiction_codes")
        or payload.get("states")
    )
    if isinstance(codes_raw, Sequence) and not isinstance(codes_raw, (str, bytes)):
        return [str(c).strip().upper() for c in codes_raw if str(c).strip()]
    receipts = payload.get("jurisdiction_receipts") or payload.get("receipts")
    codes: list[str] = []
    if isinstance(receipts, Sequence) and not isinstance(receipts, (str, bytes)):
        for item in receipts:
            if isinstance(item, Mapping) and item.get("jurisdiction"):
                codes.append(str(item.get("jurisdiction")).strip().upper())
    return codes


def evaluate_jurisdiction_set_receipt(
    receipt: Mapping[str, Any],
    *,
    case_id: str = "jurisdiction_set",
    expected_status: Optional[str] = None,
) -> CompletenessVerdict:
    """Evaluate a corpus-level jurisdiction set / DC policy receipt."""

    payload = _require_mapping(receipt, "receipt")
    collector = _FindingCollector(case_id=case_id)
    relevant = {
        GATE_EXACT_SET,
        GATE_OPT_IN_DC,
        GATE_SUBSET_MANIFEST,
        GATE_DEFAULT_EXCLUSIONS,
    }
    if is_opt_in_dc_policy(payload):
        collector.add(
            FindingKind.OPT_IN_DC,
            GATE_OPT_IN_DC,
            "DC must be a required member of the exact 51-set; opt-in DC is forbidden",
        )
    codes = _extract_codes(payload)
    if not codes and payload.get("jurisdictions") is None and payload.get("jurisdiction_codes") is None:
        collector.add(
            FindingKind.JURISDICTION_SET_MISMATCH,
            GATE_EXACT_SET,
            "jurisdictions list missing",
        )
        return collector.verdict(expected_status=expected_status, relevant_gates=relevant)
    dc_count = codes.count("DC")
    declared_dc = payload.get("dc_count")
    if declared_dc is not None:
        try:
            declared_dc_i = _as_non_negative_int(declared_dc, "dc_count")
        except OpenUsLawCompletenessError:
            declared_dc_i = -1
        if declared_dc_i != 1 or dc_count != 1:
            collector.add(
                FindingKind.DC_NOT_EXACTLY_ONCE,
                GATE_EXACT_SET,
                f"DC must be counted exactly once (list={dc_count}, dc_count={declared_dc})",
            )
    elif dc_count != 1:
        collector.add(
            FindingKind.DC_NOT_EXACTLY_ONCE,
            GATE_EXACT_SET,
            f"DC must be counted exactly once, found {dc_count}",
        )
    extras = sorted({code for code in codes if is_forbidden_default_jurisdiction(code)})
    if extras:
        collector.add(
            FindingKind.PR_OR_FEDERAL_IN_DEFAULT,
            GATE_DEFAULT_EXCLUSIONS,
            f"default configuration contains forbidden codes: {extras}",
        )
    try:
        validate_jurisdiction_set(codes)
    except JurisdictionSetError as exc:
        unique = {c for c in codes if c}
        if unique < CANONICAL_JURISDICTIONS and not (unique - CANONICAL_JURISDICTIONS):
            collector.add(
                FindingKind.SUBSET_MANIFEST,
                GATE_SUBSET_MANIFEST,
                (
                    f"jurisdiction set is a subset of the sealed 51 "
                    f"(count={len(unique)}): {exc}"
                ),
            )
        collector.add(
            FindingKind.JURISDICTION_SET_MISMATCH,
            GATE_EXACT_SET,
            str(exc),
        )
    if payload.get("includes_dc") is False and "DC" not in set(codes):
        if FindingKind.OPT_IN_DC.value not in collector.kinds():
            if payload.get("include_dc") is False or str(
                payload.get("states_token") or ""
            ).lower() in {"all", "50", "states"}:
                collector.add(
                    FindingKind.OPT_IN_DC,
                    GATE_OPT_IN_DC,
                    "includes_dc=false rejects production completion",
                )
    return collector.verdict(expected_status=expected_status, relevant_gates=relevant)


def _evaluate_aggregate_parity(
    collector: _FindingCollector,
    payload: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
) -> None:
    if not receipts:
        collector.add(
            FindingKind.AGGREGATE_KEY_MISMATCH,
            GATE_KEY_DIGEST_PARITY,
            "aggregate has no jurisdiction receipts to reconcile",
        )
        return

    union_keys = union_jurisdiction_keys(receipts)
    expected_key_digest = compute_aggregate_key_digest(receipts)
    expected_body_digest = compute_aggregate_body_digest(receipts)
    expected_frontier_digest = compute_aggregate_frontier_digest(receipts)

    provided_keys = payload.get("aggregate_keys")
    if provided_keys is None:
        provided_keys = payload.get("canonical_keys")
    try:
        provided_set = _normalize_key_set(provided_keys, name="aggregate_keys")
    except OpenUsLawCompletenessError as exc:
        collector.add(
            FindingKind.AGGREGATE_KEY_MISMATCH,
            GATE_KEY_DIGEST_PARITY,
            str(exc),
        )
        provided_set = set()
    if provided_keys is None:
        collector.add(
            FindingKind.AGGREGATE_KEY_MISMATCH,
            GATE_KEY_DIGEST_PARITY,
            "aggregate_keys missing",
        )
    elif provided_set != set(union_keys):
        missing = sorted(set(union_keys) - provided_set)
        extra = sorted(provided_set - set(union_keys))
        collector.add(
            FindingKind.AGGREGATE_KEY_MISMATCH,
            GATE_KEY_DIGEST_PARITY,
            (
                "aggregate keys != jurisdiction union; "
                f"missing={missing!r} extra={extra!r}"
            ),
        )

    seen_keys: dict[str, str] = {}
    for item in receipts:
        label = extract_jurisdiction_label(item)
        for key in extract_canonical_keys(item):
            owner = seen_keys.get(key)
            if owner and owner != label:
                collector.add(
                    FindingKind.DUPLICATE_LOGICAL_KEYS,
                    GATE_KEY_DIGEST_PARITY,
                    f"logical key {key!r} appears in both {owner} and {label}",
                )
                break
            seen_keys[key] = label

    digest_block = payload.get("aggregate_digests")
    if not isinstance(digest_block, Mapping):
        digest_block = payload
    provided_key_digest = _normalize_sha256(
        digest_block.get("key_digest_sha256") or digest_block.get("key_digest")
    )
    provided_body_digest = _normalize_sha256(
        digest_block.get("body_digest_sha256") or digest_block.get("body_digest")
    )
    provided_frontier_digest = _normalize_sha256(
        digest_block.get("frontier_digest_sha256") or digest_block.get("frontier_digest")
    )
    if not provided_key_digest or not provided_body_digest or not provided_frontier_digest:
        collector.add(
            FindingKind.AGGREGATE_DIGEST_MISMATCH,
            GATE_KEY_DIGEST_PARITY,
            "aggregate key/body/frontier digests missing",
        )
    else:
        mismatches: list[str] = []
        if provided_key_digest != expected_key_digest:
            mismatches.append("key_digest_sha256")
        if provided_body_digest != expected_body_digest:
            mismatches.append("body_digest_sha256")
        if provided_frontier_digest != expected_frontier_digest:
            mismatches.append("frontier_digest_sha256")
        if mismatches:
            collector.add(
                FindingKind.AGGREGATE_DIGEST_MISMATCH,
                GATE_KEY_DIGEST_PARITY,
                f"aggregate digests do not match jurisdiction union: {mismatches}",
            )

    family = payload.get("family_parity") or payload.get("index_families")
    if not isinstance(family, Mapping):
        collector.add(
            FindingKind.FAMILY_KEY_PARITY_MISMATCH,
            GATE_KEY_DIGEST_PARITY,
            "family_parity block missing (corpus/BM25/vector/graph/locator/descriptor)",
        )
    else:
        expected = set(union_keys) if union_keys else provided_set
        for field_name in FAMILY_KEY_FIELDS:
            if field_name not in family:
                collector.add(
                    FindingKind.FAMILY_KEY_PARITY_MISMATCH,
                    GATE_KEY_DIGEST_PARITY,
                    f"family_parity.{field_name} missing",
                )
                continue
            try:
                family_set = _normalize_key_set(family.get(field_name), name=field_name)
            except OpenUsLawCompletenessError as exc:
                collector.add(
                    FindingKind.FAMILY_KEY_PARITY_MISMATCH,
                    GATE_KEY_DIGEST_PARITY,
                    str(exc),
                )
                continue
            if family_set != expected:
                collector.add(
                    FindingKind.FAMILY_KEY_PARITY_MISMATCH,
                    GATE_KEY_DIGEST_PARITY,
                    (
                        f"{field_name} does not equal aggregate/jurisdiction key union"
                    ),
                )

    if isinstance(payload.get("disposition"), Mapping):
        sums = {
            "discovered": 0,
            "fetched": 0,
            "excluded": 0,
            "quarantined": 0,
            "failed_final": 0,
        }
        for item in receipts:
            child = item.get("disposition")
            if not isinstance(child, Mapping):
                continue
            for key in sums:
                value = child.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    sums[key] += value
        agg = payload["disposition"]
        for key, expected_sum in sums.items():
            actual = agg.get(key)
            if (
                isinstance(actual, int)
                and not isinstance(actual, bool)
                and actual != expected_sum
            ):
                collector.add(
                    FindingKind.DISPOSITION_ARITHMETIC_MISMATCH,
                    GATE_DISPOSITION,
                    f"aggregate {key}={actual} != sum of jurisdictions {expected_sum}",
                )


def evaluate_aggregate_receipt(
    receipt: Mapping[str, Any],
    *,
    case_id: str = "aggregate_receipt",
    expected_status: Optional[str] = None,
) -> CompletenessVerdict:
    """Evaluate an exact-51 aggregate full-scrape receipt."""

    payload = _require_mapping(receipt, "receipt")
    collector = _FindingCollector(case_id=case_id)
    relevant = set(ALL_GATES)

    set_verdict = evaluate_jurisdiction_set_receipt(
        payload, case_id=f"{case_id}/jurisdiction_set"
    )
    for finding in set_verdict.findings:
        if finding.severity == "error":
            collector.findings.append(finding)

    if payload.get("requested_scope_is_complete") is True:
        collector.add(
            FindingKind.REQUESTED_SCOPE_COMPLETION,
            GATE_SUBSET_MANIFEST,
            "requested_scope_is_complete cannot authorize full-corpus admission",
        )
    codes = _extract_codes(payload)
    if payload.get("is_complete") is True and codes:
        if set(codes) != CANONICAL_JURISDICTIONS:
            collector.add(
                FindingKind.SUBSET_MANIFEST,
                GATE_SUBSET_MANIFEST,
                "is_complete=true on a non-exact-51 jurisdiction set",
            )

    if isinstance(payload.get("disposition"), Mapping):
        ok, detail = reconcile_disposition(payload["disposition"])
        if not ok:
            collector.add(
                FindingKind.DISPOSITION_ARITHMETIC_MISMATCH,
                GATE_DISPOSITION,
                detail,
            )
        failed_final = payload["disposition"].get("failed_final")
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

    raw_receipts = payload.get("jurisdiction_receipts") or payload.get("receipts") or []
    receipts: list[Mapping[str, Any]] = []
    if isinstance(raw_receipts, Sequence) and not isinstance(raw_receipts, (str, bytes)):
        for idx, item in enumerate(raw_receipts):
            if not isinstance(item, Mapping):
                collector.add(
                    FindingKind.MISSING_REQUIRED_FIELD,
                    GATE_DISPOSITION,
                    f"jurisdiction_receipts[{idx}] must be a mapping",
                )
                continue
            receipts.append(item)
            sub = evaluate_jurisdiction_receipt(
                item,
                case_id=f"{case_id}/jurisdiction_receipts[{idx}]",
            )
            for finding in sub.findings:
                if finding.severity == "error":
                    collector.findings.append(finding)
    else:
        collector.add(
            FindingKind.MISSING_REQUIRED_FIELD,
            GATE_KEY_DIGEST_PARITY,
            "jurisdiction_receipts must be a list",
        )

    _evaluate_aggregate_parity(collector, payload, receipts)
    return collector.verdict(expected_status=expected_status, relevant_gates=relevant)


def evaluate_corpus_manifest(
    manifest: Mapping[str, Any],
    *,
    case_id: str = "corpus_manifest",
    expected_status: Optional[str] = None,
) -> CompletenessVerdict:
    """Evaluate a multi-jurisdiction completion / admission manifest."""

    return evaluate_aggregate_receipt(
        manifest, case_id=case_id, expected_status=expected_status
    )


def evaluate_full_scrape_receipt(
    receipt: Mapping[str, Any],
    *,
    kind: Optional[str] = None,
    case_id: str = "full_scrape_receipt",
    expected_status: Optional[str] = None,
) -> CompletenessVerdict:
    """Dispatch a full-scrape receipt by kind to the appropriate evaluator."""

    payload = _require_mapping(receipt, "receipt")
    resolved_kind = (
        str(kind or payload.get("kind") or "").strip().lower().replace("-", "_")
    )
    if not resolved_kind:
        if "jurisdiction" in payload and not any(
            key in payload
            for key in ("jurisdictions", "jurisdiction_codes", "jurisdiction_receipts")
        ):
            resolved_kind = "jurisdiction"
        else:
            resolved_kind = "aggregate"
    if resolved_kind in {"jurisdiction_set", "exact_set", "jurisdiction_set_receipt"}:
        return evaluate_jurisdiction_set_receipt(
            payload, case_id=case_id, expected_status=expected_status
        )
    if resolved_kind in {
        "jurisdiction",
        "jurisdiction_receipt",
        "state",
        "single",
    }:
        return evaluate_jurisdiction_receipt(
            payload, case_id=case_id, expected_status=expected_status
        )
    return evaluate_aggregate_receipt(
        payload, case_id=case_id, expected_status=expected_status
    )


def evaluate_completion_receipt(
    receipt: Mapping[str, Any],
    *,
    kind: Optional[str] = None,
    case_id: str = "completion_receipt",
    expected_status: Optional[str] = None,
) -> CompletenessVerdict:
    """Alias for :func:`evaluate_full_scrape_receipt`."""

    return evaluate_full_scrape_receipt(
        receipt, kind=kind, case_id=case_id, expected_status=expected_status
    )


def require_complete(
    receipt: Mapping[str, Any],
    *,
    kind: Optional[str] = None,
    case_id: str = "require_complete",
) -> CompletenessVerdict:
    """Evaluate *receipt* and raise if it is not complete/admitted."""

    verdict = evaluate_full_scrape_receipt(receipt, kind=kind, case_id=case_id)
    if not verdict.complete:
        kinds = ", ".join(verdict.kinds) if verdict.kinds else "incomplete"
        raise CompletenessAdmissionError(
            f"{case_id} failed completion admission ({kinds})"
        )
    return verdict


def require_schema_valid(receipt: Mapping[str, Any]) -> None:
    """Raise if *receipt* does not validate against the sealed schema."""

    validate_receipt_schema(receipt)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _typed_units(count: int, prefix: str) -> list[dict[str, str]]:
    units: list[dict[str, str]] = []
    for idx in range(count):
        unit_id = f"{prefix}-{idx + 1}"
        units.append(
            {
                "unit_id": unit_id,
                "reason": f"{prefix}_reason",
                "evidence_sha256": sha256_text(f"{prefix}:{unit_id}"),
            }
        )
    return units


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
    source_domain: str = "www.revisor.mn.gov",
    source_path: str = "/statutes",
    sample_cap: Any = None,
    runtime_caps: Any = None,
    frontier_method: str = "pagination",
    frontier_closed: bool = True,
    bundle_closed: Optional[bool] = None,
    pagination_closed: Optional[bool] = None,
    partial_checkpoint: bool = False,
    promoted_success: bool = False,
    completion_basis: str = "source_frontier",
    status: str = "success",
    canonical_keys: Optional[Sequence[str]] = None,
    derived_keys: Optional[Sequence[str]] = None,
    stale_keys: Optional[Sequence[str]] = None,
    replay: Optional[Mapping[str, Any]] = None,
    transport_kind: str = "live_https",
    **extra: Any,
) -> dict[str, Any]:
    """Build a jurisdiction receipt with defaults that pass the oracle."""

    code = str(jurisdiction).strip().upper()
    keys = (
        list(canonical_keys)
        if canonical_keys is not None
        else [f"{code.lower()}:1", f"{code.lower()}:2", f"{code.lower()}:3"]
    )
    dkeys = list(derived_keys) if derived_keys is not None else list(keys)
    request_h = sha256_text(f"request:{code}")
    response_h = sha256_text(f"response:{code}")
    body_h = sha256_text(f"body:{code}")
    frontier_h = sha256_text(f"frontier:{code}")
    method = frontier_method.replace("-", "_")
    if bundle_closed is None:
        bundle_closed = method in {"bundle", "bundle_and_pagination"} and frontier_closed
    if pagination_closed is None:
        pagination_closed = method in {"pagination", "bundle_and_pagination", ""} and frontier_closed
    if method == "bundle" and bundle_closed is None:
        bundle_closed = frontier_closed
    payload: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "kind": "jurisdiction",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "jurisdiction": code,
        "code_family": DEFAULT_CODE_FAMILY,
        "status": status,
        "mode": "full",
        "official_source": official_source,
        "source_domain": source_domain,
        "source_path": source_path,
        "source_authority_class": "official" if official_source else "secondary",
        "rights": {
            "scope": "public_domain",
            "attribution_required": False,
            "decision": "admit",
        },
        "edition": "2026",
        "legal_as_of": "2026-07-01T00:00:00Z",
        "observed_at": "2026-08-13T21:00:00Z",
        "hashes": {
            "request_sha256": request_h,
            "response_sha256": response_h,
            "admitted_body_sha256": body_h,
        },
        "cids": {
            "source_cid": fake_cid(f"source:{code}"),
            "entry_cid": fake_cid(f"entry:{code}"),
            "acquisition_receipt_cid": fake_cid(f"acq:{code}"),
            "rights_receipt_cid": fake_cid(f"rights:{code}"),
        },
        "transport": {
            "kind": transport_kind,
            "fixture": False,
            "synthetic": False,
        },
        "runtime_caps": runtime_caps,
        "sample_cap": sample_cap,
        "checkpoint": {
            "partial": partial_checkpoint,
            "promoted_success": promoted_success,
            "completion_basis": completion_basis,
        },
        "frontier": {
            "method": method if method in {"bundle", "pagination", "bundle_and_pagination"} else "pagination",
            "closed": frontier_closed,
            "bundle_closed": bundle_closed,
            "pagination_closed": pagination_closed,
            "enumerator_closed": frontier_closed,
            "toc_exhausted": frontier_closed,
            "unvisited_continuation_links": [],
            "remaining_bundle_members": [],
            "expected_index_units": 3,
            "visited_index_units": 3 if frontier_closed else 1,
            "bundle_member_count": 3 if method == "bundle" else 0,
            "enumerated_member_count": 3 if method == "bundle" and frontier_closed else 0,
            "frontier_digest_sha256": frontier_h,
        },
        "boundary_probes": {
            "first_hierarchy_unit": "title-1",
            "last_hierarchy_unit": "title-3",
            "first_probe_ok": True,
            "last_probe_ok": True,
            "pagination_total": 3,
            "bundle_total": 1 if method == "bundle" else 0,
        },
        "replay": {
            "request_sha256": request_h,
            "response_sha256": response_h,
            "admitted_body_sha256": body_h,
            "frontier_digest_sha256": frontier_h,
            "closed": True,
        },
        "disposition": {
            "discovered": discovered,
            "fetched": fetched,
            "excluded": excluded,
            "quarantined": quarantined,
            "failed_final": failed_final,
            "duplicates": duplicates,
        },
        "exclusions": _typed_units(excluded, f"{code.lower()}-excl"),
        "quarantines": _typed_units(quarantined, f"{code.lower()}-quar"),
        "logical_keys": {
            "keys": list(keys),
            "unique": len(keys) == len(set(keys)),
            "current_count": len(keys),
            "historical_count": 0,
            "current_history_disposition": "current",
        },
        "text_quality": {
            "min_usable_chars": 40,
            "navigation_rejected": True,
            "footer_rejected": True,
            "placeholder_rejected": True,
            "rejected_units": 0,
            "contaminated": False,
        },
        "index_keys": {
            "canonical_keys": list(keys),
            "derived_keys": list(dkeys),
            "stale_keys": list(stale_keys or []),
            "parity_ok": set(keys) == set(dkeys) and not stale_keys,
        },
        "row_count": fetched,
    }
    if replay is not None:
        payload["replay"] = dict(replay)
    payload.update(extra)
    return payload


def exact_51_aggregate_receipt(
    *,
    status: str = "success",
    include_dc: bool = True,
    dc_policy: str = "required",
    is_complete: bool = True,
    requested_scope_is_complete: bool = False,
    jurisdictions: Optional[Sequence[str]] = None,
    jurisdiction_receipts: Optional[Sequence[Mapping[str, Any]]] = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build an aggregate receipt defaulting to the exact sealed 51-set."""

    codes = (
        list(jurisdictions)
        if jurisdictions is not None
        else list(canonical_jurisdiction_codes())
    )
    if not include_dc:
        codes = [c for c in codes if c != "DC"]
    if jurisdiction_receipts is not None:
        receipts = [dict(item) for item in jurisdiction_receipts]
    else:
        receipts = [
            closed_jurisdiction_receipt(
                code,
                source_domain=f"statutes.{code.lower()}.gov",
                source_path="/statutes",
            )
            for code in codes
        ]
    union_keys = union_jurisdiction_keys(receipts)
    sums = {
        "discovered": 0,
        "fetched": 0,
        "excluded": 0,
        "quarantined": 0,
        "failed_final": 0,
        "duplicates": 0,
    }
    for item in receipts:
        child = item.get("disposition")
        if isinstance(child, Mapping):
            for key in sums:
                value = child.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    sums[key] += value
    payload: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "kind": "aggregate",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "status": status,
        "mode": "full",
        "jurisdictions": list(codes),
        "includes_dc": "DC" in codes,
        "include_dc": include_dc,
        "dc_count": codes.count("DC"),
        "dc_policy": dc_policy,
        "default_configuration": DEFAULT_CONFIGURATION,
        "forbidden_in_default": ["PR", "US", "FED"],
        "is_complete": is_complete,
        "requested_scope_is_complete": requested_scope_is_complete,
        "jurisdiction_count": len(codes),
        "states_token": "all",
        "jurisdiction_receipts": receipts,
        "aggregate_keys": list(union_keys),
        "aggregate_digests": {
            "key_digest_sha256": compute_aggregate_key_digest(receipts),
            "body_digest_sha256": compute_aggregate_body_digest(receipts),
            "frontier_digest_sha256": compute_aggregate_frontier_digest(receipts),
        },
        "family_parity": {field: list(union_keys) for field in FAMILY_KEY_FIELDS},
        "disposition": sums,
    }
    payload.update(extra)
    return payload


def exact_51_manifest(**kwargs: Any) -> dict[str, Any]:
    """Alias for :func:`exact_51_aggregate_receipt`."""

    return exact_51_aggregate_receipt(**kwargs)


__all__ = [
    "SCHEMA_VERSION",
    "RECEIPT_SCHEMA_VERSION",
    "RECEIPT_SCHEMA_ID",
    "TASK_ID",
    "GOAL_ID",
    "PROGRAM_ID",
    "PRODUCER",
    "EXPECTED_JURISDICTION_COUNT",
    "DEFAULT_CODE_FAMILY",
    "DEFAULT_CONFIGURATION",
    "CANONICAL_JURISDICTIONS",
    "CANONICAL_JURISDICTION_ORDER",
    "FORBIDDEN_DEFAULT_JURISDICTIONS",
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
    "GATE_KEY_DIGEST_PARITY",
    "GATE_CHECKPOINT",
    "GATE_FIXTURE_TRANSPORT",
    "GATE_IDENTITY",
    "GATE_CIDS",
    "GATE_TEXT_QUALITY",
    "GATE_TYPED_EVIDENCE",
    "GATE_DEFAULT_EXCLUSIONS",
    "OpenUsLawCompletenessError",
    "JurisdictionSetError",
    "CompletenessAdmissionError",
    "ReceiptSchemaError",
    "FindingKind",
    "CompletenessFinding",
    "CompletenessVerdict",
    "repository_root",
    "receipt_schema_path",
    "load_receipt_schema",
    "validate_receipt_schema",
    "canonical_jurisdiction_codes",
    "normalize_postal_code",
    "validate_jurisdiction_set",
    "is_opt_in_dc_policy",
    "is_forbidden_default_jurisdiction",
    "reconcile_disposition",
    "sha256_text",
    "canonical_json_digest",
    "digest_sorted_strings",
    "fake_cid",
    "compute_aggregate_key_digest",
    "compute_aggregate_body_digest",
    "compute_aggregate_frontier_digest",
    "union_jurisdiction_keys",
    "evaluate_jurisdiction_receipt",
    "evaluate_jurisdiction_set_receipt",
    "evaluate_aggregate_receipt",
    "evaluate_corpus_manifest",
    "evaluate_full_scrape_receipt",
    "evaluate_completion_receipt",
    "require_complete",
    "require_schema_valid",
    "closed_jurisdiction_receipt",
    "exact_51_aggregate_receipt",
    "exact_51_manifest",
]
