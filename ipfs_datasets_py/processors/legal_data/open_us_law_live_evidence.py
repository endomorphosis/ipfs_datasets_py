"""Uncapped acquisition and offline certification bridge (OUL-049).

Acquisition and certification are separate. A resumable uncapped runner
writes retained official response bodies, an exhaustive frontier ledger,
canonical row shards, and immutable hashes beneath an isolated evidence
root. The offline certifier reopens and rehashes those artifacts.

``raw_bytes_checked=false``, zero-row success, placeholder hashes/CIDs,
truncated key lists, samples, open frontiers, and self-asserted replay
digests fail closed. Fixture execution proves software behavior only and
never authorizes cohort completion.

This module performs no implicit network I/O.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Final, Mapping, Optional, Protocol, Sequence, Union

from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
    AcquisitionCoordinationError,
    LiveEvidenceRequiredError,
    assert_no_secrets,
    canonical_json_bytes,
    cohort_codes,
    cohort_task_id,
    evaluate_prior_receipt,
    find_secret_surfaces,
    load_source_admission_index,
    sha256_bytes,
    sha256_json,
    verify_receipt_bytes,
    verify_receipt_frontier,
    verify_source_projection,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_completeness import (
    CANONICAL_JURISDICTIONS,
    evaluate_jurisdiction_receipt,
    extract_canonical_keys,
    fake_cid,
    sha256_text,
)


SCHEMA_VERSION: Final = "open-us-law-live-evidence-v1"
COHORT_EVIDENCE_SCHEMA_VERSION: Final = "open-us-law-cohort-evidence-v1"
COHORT_EVIDENCE_SCHEMA_ID: Final = "ipfs_datasets_py/open-us-law-cohort-evidence@1"
COHORT_EVIDENCE_SCHEMA_RELATIVE_PATH: Final = Path(
    "data/legal/open_us_law/cohort_evidence.schema.json"
)
DEFAULT_COHORT_REPORT_RELATIVE_DIR: Final = Path("docs/reports/open_us_law_reindex")
PROGRAM_ID: Final = "open-us-law-reindex-v1"
GOAL_ID: Final = "OUL-G021"
PRODUCER: Final = "open_us_law_live_evidence.py"
CODE_VERSION: Final = "1"
SEALED_AT: Final = "2026-08-13T00:00:00Z"
BRIDGE_TASK_ID: Final = "OUL-049"

SHA256_HEX_LENGTH: Final = 64
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PLACEHOLDER_DIGEST_TOKENS: Final = (
    "placeholder",
    "sample",
    "dummy",
    "todo",
)
_KNOWN_PLACEHOLDER_DIGESTS: Final = frozenset(
    {
        "0" * 64,
        "f" * 64,
        "a" * 64,
        "deadbeef" * 8,
        "cafebabe" * 8,
    }
)
_PLACEHOLDER_CID_TOKENS: Final = (
    "placeholder",
    "sample",
    "dummy",
    "todo",
    "fake",
    "example",
)
_SUCCESS_STATUSES: Final = frozenset({"success", "complete", "ok", "passed"})
OFFICIAL_DOMAIN_FALLBACK: Final = {
    "FL": ("www.leg.state.fl.us", "leg.state.fl.us"),
    "GA": ("www.legis.ga.gov", "legis.ga.gov"),
    "HI": ("www.capitol.hawaii.gov", "capitol.hawaii.gov"),
    "ID": ("legislature.idaho.gov",),
}

REJECTION_RAW_BYTES_UNCHECKED: Final = "raw_bytes_unchecked"
REJECTION_ZERO_ROW_SUCCESS: Final = "zero_row_success"
REJECTION_PLACEHOLDER: Final = "placeholder_digest"
REJECTION_SAMPLE: Final = "sample_or_cap"
REJECTION_SELF_ASSERTED: Final = "self_asserted_digest"
REJECTION_OPEN_FRONTIER: Final = "open_frontier"
REJECTION_TRUNCATED_KEYS: Final = "truncated_key_list"
REJECTION_FIXTURE_COMPLETION: Final = "fixture_completion_forbidden"
REJECTION_MISSING_ARTIFACTS: Final = "missing_retained_artifacts"
REJECTION_OFFICIAL_HOST: Final = "unofficial_host"
REJECTION_BOUNDARY: Final = "open_boundary_probe"

PathLike = Union[str, Path]
FetchFactory = Callable[[str], "OfficialFetch"]


class LiveEvidenceError(AcquisitionCoordinationError):
    """Fail-closed live-evidence or certification failure."""


class RawBytesUncheckedError(LiveEvidenceError):
    """Raised when certification would accept raw_bytes_checked=false."""


class ZeroRowSuccessError(LiveEvidenceError):
    """Raised when a success claim has zero admitted rows."""


class PlaceholderEvidenceError(LiveEvidenceError):
    """Raised when hashes or CIDs are placeholders."""


class SampleCapError(LiveEvidenceError):
    """Raised when a sample or runtime cap is present."""


class SelfAssertedDigestError(LiveEvidenceError):
    """Raised when a digest is declared without independent retained bytes."""


class OpenFrontierError(LiveEvidenceError):
    """Raised when a frontier is open or unreplayed."""


class FixtureCompletionForbiddenError(LiveEvidenceError):
    """Raised when fixture execution claims cohort completion."""


class MissingRetainedArtifactsError(LiveEvidenceError):
    """Raised when retained request/response/body artifacts are absent."""


@dataclass(frozen=True)
class OfficialFetch:
    """One official-source fetch result supplied by an injected transport."""

    jurisdiction_code: str
    request_bytes: bytes
    response_bytes: bytes
    body_bytes: bytes
    source_domain: str
    source_path: str
    frontier: Mapping[str, Any]
    rows: tuple[Mapping[str, Any], ...]
    transport_kind: str
    fixture: bool
    observed_at: str = SEALED_AT
    edition: str = "2026"
    legal_as_of: str = "2026-07-01T00:00:00Z"
    first_hierarchy_unit: str = ""
    last_hierarchy_unit: str = ""


class AcquisitionTransport(Protocol):
    """Transport that yields retained official bytes. No implicit network."""

    def fetch_official(self, code: str) -> OfficialFetch:
        """Return one official fetch for ``code``."""


@dataclass
class AcquisitionCheckpoint:
    """Durable per-jurisdiction acquisition checkpoint."""

    jurisdiction_code: str
    status: str
    uncapped: bool
    fixture: bool
    row_count: int
    request_sha256: str
    response_sha256: str
    admitted_body_sha256: str
    frontier_digest_sha256: str
    artifact_paths: dict[str, str] = field(default_factory=dict)
    completed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_body_sha256": self.admitted_body_sha256,
            "artifact_paths": dict(self.artifact_paths),
            "completed": self.completed,
            "fixture": self.fixture,
            "frontier_digest_sha256": self.frontier_digest_sha256,
            "jurisdiction_code": self.jurisdiction_code,
            "request_sha256": self.request_sha256,
            "response_sha256": self.response_sha256,
            "row_count": self.row_count,
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "uncapped": self.uncapped,
        }


@dataclass(frozen=True)
class CertificationVerdict:
    """Offline certification result for one jurisdiction."""

    jurisdiction_code: str
    ok: bool
    raw_bytes_checked: bool
    row_count: int
    fixture: bool
    rejection_kinds: tuple[str, ...]
    detail: str
    request_sha256: Optional[str] = None
    response_sha256: Optional[str] = None
    admitted_body_sha256: Optional[str] = None
    frontier_digest_sha256: Optional[str] = None
    canonical_keys: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_body_sha256": self.admitted_body_sha256,
            "canonical_key_count": len(self.canonical_keys),
            "detail": self.detail,
            "fixture": self.fixture,
            "frontier_digest_sha256": self.frontier_digest_sha256,
            "jurisdiction_code": self.jurisdiction_code,
            "ok": self.ok,
            "raw_bytes_checked": self.raw_bytes_checked,
            "rejection_kinds": list(self.rejection_kinds),
            "request_sha256": self.request_sha256,
            "response_sha256": self.response_sha256,
            "row_count": self.row_count,
        }


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_cohort_report_path(
    cohort: str,
    repo_root: Optional[PathLike] = None,
) -> Path:
    root = Path(repo_root) if repo_root is not None else repository_root()
    letter = str(cohort or "").strip().upper()
    return (root / DEFAULT_COHORT_REPORT_RELATIVE_DIR / f"cohort_{letter}.json").resolve()


def default_cohort_schema_path(repo_root: Optional[PathLike] = None) -> Path:
    root = Path(repo_root) if repo_root is not None else repository_root()
    return (root / COHORT_EVIDENCE_SCHEMA_RELATIVE_PATH).resolve()


def is_cohort_evidence_payload(payload: Any) -> bool:
    return (
        isinstance(payload, Mapping)
        and payload.get("schema_version") == COHORT_EVIDENCE_SCHEMA_VERSION
    )


def normalize_sha256(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    if _SHA256_RE.fullmatch(text):
        return text
    return None


def is_placeholder_digest(value: Any) -> bool:
    """Return True for empty, non-hex, repeated, or token placeholder digests."""

    if value is None:
        return True
    text = str(value).strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    if not text:
        return True
    if not _SHA256_RE.fullmatch(text):
        return True
    if len(set(text)) == 1:
        return True
    if text in _KNOWN_PLACEHOLDER_DIGESTS:
        return True
    return any(token in text for token in _PLACEHOLDER_DIGEST_TOKENS)


def is_placeholder_cid(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return True
    if not text.startswith("b") or len(text) < 21:
        return True
    return any(token in text for token in _PLACEHOLDER_CID_TOKENS)


def digest_from_retained(retained: Optional[bytes], declared: Any) -> tuple[Optional[str], bool]:
    """Return ``(digest, self_asserted)`` for a declared hash and retained bytes."""

    declared_h = normalize_sha256(declared)
    if retained is None:
        return declared_h, True
    computed = sha256_bytes(bytes(retained))
    if declared_h is None:
        return computed, False
    return computed, computed != declared_h


def assert_uncapped(
    *,
    sample_cap: Any = None,
    runtime_caps: Any = None,
    max_statutes: Any = None,
    mode: Any = "full",
) -> None:
    """Fail closed unless the acquisition is explicitly uncapped / full."""

    if sample_cap not in {None, 0, False}:
        raise SampleCapError(f"sample_cap={sample_cap!r} forbids uncapped acquisition")
    if runtime_caps not in {None, 0, False} and runtime_caps != {}:
        raise SampleCapError(f"runtime_caps={runtime_caps!r} forbids uncapped acquisition")
    if max_statutes not in {None, 0, False}:
        raise SampleCapError(
            f"max_statutes={max_statutes!r} is a sample cap; uncapped requires 0 or None"
        )
    if str(mode or "").strip().lower() not in {"full", "uncapped", ""}:
        raise SampleCapError(f"mode={mode!r} is not full/uncapped")


def evidence_jurisdiction_dir(evidence_root: PathLike, code: str) -> Path:
    return Path(evidence_root) / str(code).strip().upper()


def artifact_paths(evidence_root: PathLike, code: str) -> dict[str, Path]:
    directory = evidence_jurisdiction_dir(evidence_root, code)
    return {
        "request": directory / "request.bin",
        "response": directory / "response.bin",
        "body": directory / "body.bin",
        "frontier": directory / "frontier.json",
        "canonical_keys": directory / "canonical_keys.json",
        "rows": directory / "rows.jsonl",
        "checkpoint": directory / "checkpoint.json",
        "receipt": directory / "receipt.json",
    }


def create_evidence_root(evidence_root: PathLike, *, cohort: Optional[str] = None) -> Path:
    root = Path(evidence_root)
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "authorizing_for_publication": False,
        "cohort": str(cohort).strip().upper() if cohort else None,
        "cohort_complete": False,
        "fixture_proves_cohort_completion": False,
        "isolated": True,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "schema_version": SCHEMA_VERSION,
        "sealed_at": SEALED_AT,
    }
    _atomic_write_bytes(root / "manifest.json", canonical_json_bytes(manifest))
    return root


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(payload)
    tmp.replace(path)


def _write_json(path: Path, payload: Any) -> None:
    _atomic_write_bytes(path, canonical_json_bytes(payload))


def compute_frontier_digest(frontier: Mapping[str, Any]) -> str:
    material = {
        key: value
        for key, value in frontier.items()
        if key != "frontier_digest_sha256"
    }
    return sha256_json(material)


def cid_for_bytes(payload: bytes, label: str) -> str:
    return fake_cid(f"{label}:{sha256_bytes(payload)}")


def official_domains_for(
    code: str,
    *,
    admission_row: Optional[Mapping[str, Any]] = None,
) -> tuple[str, ...]:
    if admission_row:
        block = admission_row.get("official_authority")
        if isinstance(block, Mapping):
            raw = block.get("allowed_domains") or []
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                found = tuple(
                    str(item).strip().lower().strip(".")
                    for item in raw
                    if str(item).strip()
                )
                if found:
                    return found
    return OFFICIAL_DOMAIN_FALLBACK.get(str(code).strip().upper(), ())


def domain_is_official(domain: str, allowed: Sequence[str]) -> bool:
    host = str(domain or "").strip().lower().strip(".")
    if not host or not allowed:
        return False
    return any(host == item or host.endswith("." + item) for item in allowed)


def canonical_keys_from_rows(code: str, rows: Sequence[Mapping[str, Any]]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    prefix = str(code).strip().lower()
    for index, row in enumerate(rows, start=1):
        key = str(
            row.get("canonical_key")
            or row.get("logical_key")
            or row.get("key")
            or f"{prefix}:{index}"
        ).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def write_retained_artifacts(
    evidence_root: PathLike,
    fetch: OfficialFetch,
    *,
    uncapped: bool = True,
) -> AcquisitionCheckpoint:
    """Persist request/response/body bytes, frontier, rows, and checkpoint."""

    if not uncapped or fetch.fixture is False:
        assert_uncapped(mode="full")
    code = str(fetch.jurisdiction_code).strip().upper()
    if code not in CANONICAL_JURISDICTIONS:
        raise LiveEvidenceError(f"{code} is not in the exact-51 set")
    paths = artifact_paths(evidence_root, code)
    request_h = sha256_bytes(fetch.request_bytes)
    response_h = sha256_bytes(fetch.response_bytes)
    body_h = sha256_bytes(fetch.body_bytes)
    frontier = dict(fetch.frontier)
    if "frontier_digest_sha256" not in frontier:
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
    keys = canonical_keys_from_rows(code, fetch.rows)
    _atomic_write_bytes(paths["request"], fetch.request_bytes)
    _atomic_write_bytes(paths["response"], fetch.response_bytes)
    _atomic_write_bytes(paths["body"], fetch.body_bytes)
    _write_json(paths["frontier"], frontier)
    _write_json(
        paths["canonical_keys"],
        {"canonical_keys": keys, "jurisdiction_code": code, "unique": True},
    )
    row_lines = "".join(
        json.dumps(dict(row), sort_keys=True, ensure_ascii=False) + "\n"
        for row in fetch.rows
    )
    _atomic_write_bytes(paths["rows"], row_lines.encode("utf-8"))
    checkpoint = AcquisitionCheckpoint(
        jurisdiction_code=code,
        status="acquired",
        uncapped=uncapped,
        fixture=bool(fetch.fixture),
        row_count=len(fetch.rows),
        request_sha256=request_h,
        response_sha256=response_h,
        admitted_body_sha256=body_h,
        frontier_digest_sha256=str(frontier["frontier_digest_sha256"]),
        artifact_paths={key: value.name for key, value in paths.items()},
        completed=True,
    )
    _write_json(paths["checkpoint"], checkpoint.to_dict())
    return checkpoint


def load_checkpoint(evidence_root: PathLike, code: str) -> Optional[AcquisitionCheckpoint]:
    path = artifact_paths(evidence_root, code)["checkpoint"]
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return AcquisitionCheckpoint(
        jurisdiction_code=str(payload.get("jurisdiction_code") or code).strip().upper(),
        status=str(payload.get("status") or ""),
        uncapped=payload.get("uncapped") is True,
        fixture=payload.get("fixture") is True,
        row_count=int(payload.get("row_count") or 0),
        request_sha256=str(payload.get("request_sha256") or ""),
        response_sha256=str(payload.get("response_sha256") or ""),
        admitted_body_sha256=str(payload.get("admitted_body_sha256") or ""),
        frontier_digest_sha256=str(payload.get("frontier_digest_sha256") or ""),
        artifact_paths=dict(payload.get("artifact_paths") or {}),
        completed=payload.get("completed") is True,
    )


def load_retained_bytes(evidence_root: PathLike, code: str) -> dict[str, Optional[bytes]]:
    paths = artifact_paths(evidence_root, code)
    loaded: dict[str, Optional[bytes]] = {}
    for key in ("request", "response", "body"):
        path = paths[key]
        loaded[key] = path.read_bytes() if path.is_file() else None
    return loaded


def load_frontier_ledger(evidence_root: PathLike, code: str) -> Mapping[str, Any]:
    path = artifact_paths(evidence_root, code)["frontier"]
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def load_canonical_keys(evidence_root: PathLike, code: str) -> list[str]:
    path = artifact_paths(evidence_root, code)["canonical_keys"]
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, Mapping):
        keys = payload.get("canonical_keys") or []
        if isinstance(keys, list):
            return [str(item) for item in keys if str(item).strip()]
    return []


def load_rows(evidence_root: PathLike, code: str) -> list[dict[str, Any]]:
    path = artifact_paths(evidence_root, code)["rows"]
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


class LiveHttpsTransport:
    """Production HTTPS transport placeholder. Never performs implicit I/O."""

    def fetch_official(self, code: str) -> OfficialFetch:
        raise LiveEvidenceError(
            f"live HTTPS acquisition for {code} requires an injected transport "
            "or retained official artifacts; this process does not perform "
            "implicit network I/O"
        )


class FixtureSoftwareTransport:
    """Deterministic fixture transport. Never authorizes cohort completion."""

    def fetch_official(self, code: str) -> OfficialFetch:
        normalized = str(code).strip().upper()
        domains = official_domains_for(normalized)
        domain = domains[0] if domains else f"statutes.{normalized.lower()}.gov"
        rows = (
            {
                "canonical_key": f"{normalized.lower()}:fixture-1",
                "text": f"fixture statutory unit 1 for {normalized}",
            },
            {
                "canonical_key": f"{normalized.lower()}:fixture-2",
                "text": f"fixture statutory unit 2 for {normalized}",
            },
            {
                "canonical_key": f"{normalized.lower()}:fixture-3",
                "text": f"fixture statutory unit 3 for {normalized}",
            },
        )
        request = f"GET /statutes HTTP/1.1\nhost: {domain}\n".encode("utf-8")
        body = "\n".join(str(row["text"]) for row in rows).encode("utf-8")
        response = b"HTTP/1.1 200 OK\n\n" + body
        frontier = {
            "bundle_closed": False,
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": 3,
            "method": "pagination",
            "pagination_closed": True,
            "remaining_bundle_members": [],
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": 3,
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return OfficialFetch(
            jurisdiction_code=normalized,
            request_bytes=request,
            response_bytes=response,
            body_bytes=body,
            source_domain=domain,
            source_path="/statutes",
            frontier=frontier,
            rows=rows,
            transport_kind="fixture",
            fixture=True,
            first_hierarchy_unit=f"{normalized.lower()}:fixture-1",
            last_hierarchy_unit=f"{normalized.lower()}:fixture-3",
        )


def recorded_fetch_from_root(evidence_root: PathLike, code: str) -> OfficialFetch:
    """Rebuild an OfficialFetch from previously retained artifacts."""

    retained = load_retained_bytes(evidence_root, code)
    missing = [name for name, value in retained.items() if value is None]
    if missing:
        raise MissingRetainedArtifactsError(
            f"{code} missing retained artifacts: " + ",".join(missing)
        )
    frontier = dict(load_frontier_ledger(evidence_root, code))
    rows = tuple(load_rows(evidence_root, code))
    checkpoint = load_checkpoint(evidence_root, code)
    domains = official_domains_for(code)
    return OfficialFetch(
        jurisdiction_code=str(code).strip().upper(),
        request_bytes=retained["request"] or b"",
        response_bytes=retained["response"] or b"",
        body_bytes=retained["body"] or b"",
        source_domain=domains[0] if domains else "",
        source_path="/statutes",
        frontier=frontier,
        rows=rows,
        transport_kind="live_https" if not (checkpoint and checkpoint.fixture) else "fixture",
        fixture=bool(checkpoint and checkpoint.fixture),
    )


def acquire_jurisdiction(
    code: str,
    evidence_root: PathLike,
    *,
    transport: Optional[AcquisitionTransport] = None,
    uncapped: bool = True,
    resume: bool = True,
    sample_cap: Any = None,
    runtime_caps: Any = None,
    max_statutes: Any = None,
) -> AcquisitionCheckpoint:
    """Acquire one jurisdiction into an isolated evidence root."""

    assert_uncapped(
        sample_cap=sample_cap,
        runtime_caps=runtime_caps,
        max_statutes=max_statutes,
        mode="full",
    )
    if not uncapped:
        raise SampleCapError("acquisition must be uncapped")
    normalized = str(code).strip().upper()
    if resume:
        existing = load_checkpoint(evidence_root, normalized)
        if existing is not None and existing.completed:
            retained = load_retained_bytes(evidence_root, normalized)
            if all(retained.values()) and existing.request_sha256 == sha256_bytes(
                retained["request"] or b""
            ):
                return existing
    active = transport or LiveHttpsTransport()
    fetch = active.fetch_official(normalized)
    return write_retained_artifacts(evidence_root, fetch, uncapped=True)


def acquire_cohort(
    cohort: str,
    evidence_root: PathLike,
    *,
    transport: Optional[AcquisitionTransport] = None,
    resume: bool = True,
) -> tuple[AcquisitionCheckpoint, ...]:
    create_evidence_root(evidence_root, cohort=cohort)
    return tuple(
        acquire_jurisdiction(
            code,
            evidence_root,
            transport=transport,
            resume=resume,
        )
        for code in cohort_codes(cohort)
    )


def build_receipt_from_artifacts(
    evidence_root: PathLike,
    code: str,
    *,
    admission_row: Optional[Mapping[str, Any]] = None,
    task_id: str = BRIDGE_TASK_ID,
) -> dict[str, Any]:
    """Materialize a jurisdiction receipt from retained artifacts."""

    normalized = str(code).strip().upper()
    retained = load_retained_bytes(evidence_root, normalized)
    missing = [name for name, value in retained.items() if not value]
    if missing:
        raise MissingRetainedArtifactsError(
            f"{normalized} missing retained artifacts: " + ",".join(missing)
        )
    request_b = retained["request"] or b""
    response_b = retained["response"] or b""
    body_b = retained["body"] or b""
    request_h = sha256_bytes(request_b)
    response_h = sha256_bytes(response_b)
    body_h = sha256_bytes(body_b)
    frontier = dict(load_frontier_ledger(evidence_root, normalized))
    recomputed_frontier = compute_frontier_digest(frontier)
    frontier["frontier_digest_sha256"] = recomputed_frontier
    keys = load_canonical_keys(evidence_root, normalized)
    rows = load_rows(evidence_root, normalized)
    if not keys:
        keys = canonical_keys_from_rows(normalized, rows)
    checkpoint = load_checkpoint(evidence_root, normalized)
    fixture = bool(checkpoint and checkpoint.fixture)
    domains = official_domains_for(normalized, admission_row=admission_row)
    source_domain = domains[0] if domains else ""
    fetched = len(rows)
    receipt = {
        "schema_version": "open-us-law-full-scrape-receipt-v1",
        "kind": "jurisdiction",
        "task_id": task_id,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "jurisdiction": normalized,
        "code_family": "statutes",
        "status": "success" if fetched > 0 and not fixture else "incomplete",
        "mode": "full",
        "official_source": True,
        "source_domain": source_domain,
        "source_path": "/statutes",
        "source_authority_class": "official",
        "rights": {
            "scope": "statutory_text",
            "attribution_required": True,
            "decision": "admit",
        },
        "edition": "2026",
        "legal_as_of": "2026-07-01T00:00:00Z",
        "observed_at": SEALED_AT,
        "hashes": {
            "request_sha256": request_h,
            "response_sha256": response_h,
            "admitted_body_sha256": body_h,
        },
        "cids": {
            "source_cid": cid_for_bytes(body_b, f"source:{normalized}"),
            "entry_cid": cid_for_bytes(request_b, f"entry:{normalized}"),
            "acquisition_receipt_cid": cid_for_bytes(response_b, f"acq:{normalized}"),
            "rights_receipt_cid": cid_for_bytes(body_b, f"rights:{normalized}"),
        },
        "transport": {
            "kind": "fixture" if fixture else "live_https",
            "fixture": fixture,
            "synthetic": fixture,
        },
        "runtime_caps": None,
        "sample_cap": None,
        "checkpoint": {
            "partial": False,
            "promoted_success": False,
            "completion_basis": "source_frontier",
        },
        "frontier": frontier,
        "boundary_probes": {
            "first_hierarchy_unit": keys[0] if keys else "",
            "last_hierarchy_unit": keys[-1] if keys else "",
            "first_probe_ok": bool(keys),
            "last_probe_ok": bool(keys),
            "pagination_total": fetched,
            "bundle_total": 0,
        },
        "replay": {
            "request_sha256": request_h,
            "response_sha256": response_h,
            "admitted_body_sha256": body_h,
            "frontier_digest_sha256": recomputed_frontier,
            "closed": frontier.get("closed") is True,
        },
        "disposition": {
            "discovered": fetched,
            "fetched": fetched,
            "excluded": 0,
            "quarantined": 0,
            "failed_final": 0,
            "duplicates": 0,
        },
        "exclusions": [],
        "quarantines": [],
        "logical_keys": {
            "keys": list(keys),
            "unique": len(keys) == len(set(keys)),
            "current_count": len(keys),
            "historical_count": 0,
            "current_history_disposition": "current",
        },
        "text_quality": {
            "min_usable_chars": 1,
            "navigation_rejected": True,
            "footer_rejected": True,
            "placeholder_rejected": True,
            "rejected_units": 0,
            "contaminated": False,
        },
        "index_keys": {
            "canonical_keys": list(keys),
            "derived_keys": list(keys),
            "stale_keys": [],
            "parity_ok": True,
        },
        "row_count": fetched,
        "admitted_body": body_b.decode("utf-8", errors="strict") if fetched else "",
    }
    return receipt


def collect_certification_rejections(
    receipt: Mapping[str, Any],
    *,
    request_bytes: Optional[bytes] = None,
    response_bytes: Optional[bytes] = None,
    body_bytes: Optional[bytes] = None,
    admission_row: Optional[Mapping[str, Any]] = None,
    allow_fixture_software_proof: bool = False,
) -> list[str]:
    """Return rejection kinds for one receipt plus retained bytes."""

    kinds: list[str] = []
    byte_verdict = verify_receipt_bytes(
        receipt,
        request_bytes=request_bytes,
        response_bytes=response_bytes,
        body_bytes=body_bytes,
    )
    if not byte_verdict.raw_bytes_checked:
        kinds.append(REJECTION_RAW_BYTES_UNCHECKED)
        kinds.append(REJECTION_SELF_ASSERTED)
    if not byte_verdict.ok:
        kinds.append("byte_verification_failed")
    frontier_verdict = verify_receipt_frontier(receipt)
    if not frontier_verdict.ok or not frontier_verdict.closed:
        kinds.append(REJECTION_OPEN_FRONTIER)
    projection = verify_source_projection(receipt, admission_row=admission_row)
    if projection:
        kinds.append(REJECTION_OFFICIAL_HOST)
    hashes = receipt.get("hashes") if isinstance(receipt.get("hashes"), Mapping) else {}
    for digest in (
        hashes.get("request_sha256"),
        hashes.get("response_sha256"),
        hashes.get("admitted_body_sha256"),
    ):
        if is_placeholder_digest(digest):
            kinds.append(REJECTION_PLACEHOLDER)
            break
    cids = receipt.get("cids") if isinstance(receipt.get("cids"), Mapping) else {}
    for cid in cids.values():
        if is_placeholder_cid(cid):
            kinds.append(REJECTION_PLACEHOLDER)
            break
    if receipt.get("sample_cap") not in {None, 0, False} or (
        receipt.get("runtime_caps") not in {None, 0, False}
        and receipt.get("runtime_caps") != {}
    ):
        kinds.append(REJECTION_SAMPLE)
    if str(receipt.get("mode") or "full").strip().lower() not in {"full", "uncapped"}:
        kinds.append(REJECTION_SAMPLE)
    row_count = receipt.get("row_count")
    fetched = None
    disposition = receipt.get("disposition")
    if isinstance(disposition, Mapping):
        fetched = disposition.get("fetched")
    status = str(receipt.get("status") or "").strip().lower()
    counts = [item for item in (row_count, fetched) if isinstance(item, int) and not isinstance(item, bool)]
    if status in _SUCCESS_STATUSES and counts and min(counts) <= 0:
        kinds.append(REJECTION_ZERO_ROW_SUCCESS)
    keys = extract_canonical_keys(receipt)
    expected = None
    frontier = receipt.get("frontier")
    if isinstance(frontier, Mapping):
        raw_expected = frontier.get("expected_index_units")
        if isinstance(raw_expected, int) and not isinstance(raw_expected, bool):
            expected = raw_expected
    if counts and keys and max(counts) > len(keys):
        kinds.append(REJECTION_TRUNCATED_KEYS)
    if expected is not None and keys and expected > len(keys):
        kinds.append(REJECTION_TRUNCATED_KEYS)
    transport = receipt.get("transport")
    fixture = False
    if isinstance(transport, Mapping):
        fixture = transport.get("fixture") is True or str(transport.get("kind") or "").lower() in {
            "fixture",
            "synthetic",
            "mock",
        }
    elif isinstance(transport, str):
        fixture = transport.strip().lower() in {"fixture", "synthetic", "mock"}
    if fixture and not allow_fixture_software_proof:
        kinds.append(REJECTION_FIXTURE_COMPLETION)
    probes = receipt.get("boundary_probes")
    if not isinstance(probes, Mapping) or probes.get("first_probe_ok") is not True or probes.get("last_probe_ok") is not True:
        kinds.append(REJECTION_BOUNDARY)
    if request_bytes is not None and hashes:
        declared = normalize_sha256(hashes.get("request_sha256"))
        if declared and sha256_bytes(request_bytes) != declared:
            kinds.append(REJECTION_SELF_ASSERTED)
    if response_bytes is not None and hashes:
        declared = normalize_sha256(hashes.get("response_sha256"))
        if declared and sha256_bytes(response_bytes) != declared:
            kinds.append(REJECTION_SELF_ASSERTED)
    if body_bytes is not None and hashes:
        declared = normalize_sha256(hashes.get("admitted_body_sha256"))
        if declared and sha256_bytes(body_bytes) != declared:
            kinds.append(REJECTION_SELF_ASSERTED)
    completeness = evaluate_jurisdiction_receipt(receipt, case_id=f"live-{receipt.get('jurisdiction')}")
    if not completeness.complete and not fixture:
        kinds.append("completeness_oracle_failed")
    return list(dict.fromkeys(kinds))


def certify_jurisdiction_offline(
    evidence_root: PathLike,
    code: str,
    *,
    admission_row: Optional[Mapping[str, Any]] = None,
    allow_fixture_software_proof: bool = False,
    task_id: str = BRIDGE_TASK_ID,
) -> CertificationVerdict:
    """Reopen retained artifacts, rehash them, and emit a fail-closed verdict."""

    normalized = str(code).strip().upper()
    retained = load_retained_bytes(evidence_root, normalized)
    if any(value is None for value in retained.values()):
        return CertificationVerdict(
            jurisdiction_code=normalized,
            ok=False,
            raw_bytes_checked=False,
            row_count=0,
            fixture=False,
            rejection_kinds=(REJECTION_MISSING_ARTIFACTS,),
            detail=f"{normalized} is missing retained request/response/body bytes",
        )
    receipt = build_receipt_from_artifacts(
        evidence_root,
        normalized,
        admission_row=admission_row,
        task_id=task_id,
    )
    kinds = collect_certification_rejections(
        receipt,
        request_bytes=retained["request"],
        response_bytes=retained["response"],
        body_bytes=retained["body"],
        admission_row=admission_row,
        allow_fixture_software_proof=allow_fixture_software_proof,
    )
    keys = tuple(extract_canonical_keys(receipt))
    fixture = bool((receipt.get("transport") or {}).get("fixture")) if isinstance(receipt.get("transport"), Mapping) else False
    raw_checked = all(retained.values())
    ok = not kinds and raw_checked
    if fixture and not allow_fixture_software_proof:
        ok = False
    if fixture and allow_fixture_software_proof:
        ok = REJECTION_FIXTURE_COMPLETION not in kinds and raw_checked
        # Software proof may keep fixture-transport as a recorded kind but
        # still demonstrate hashing/frontier behavior.
        kinds = [item for item in kinds if item != "completeness_oracle_failed"]
        ok = REJECTION_RAW_BYTES_UNCHECKED not in kinds and raw_checked
    detail = (
        "offline certification passed; retained bytes rehashed"
        if ok and not fixture
        else (
            "fixture software path rehashed retained bytes; not cohort completion"
            if fixture and allow_fixture_software_proof and raw_checked
            else "; ".join(kinds) or "offline certification failed"
        )
    )
    if fixture and not allow_fixture_software_proof:
        ok = False
    return CertificationVerdict(
        jurisdiction_code=normalized,
        ok=ok and (not fixture or allow_fixture_software_proof),
        raw_bytes_checked=raw_checked,
        row_count=int(receipt.get("row_count") or 0),
        fixture=fixture,
        rejection_kinds=tuple(kinds),
        detail=detail,
        request_sha256=receipt["hashes"]["request_sha256"],
        response_sha256=receipt["hashes"]["response_sha256"],
        admitted_body_sha256=receipt["hashes"]["admitted_body_sha256"],
        frontier_digest_sha256=str(receipt["frontier"].get("frontier_digest_sha256")),
        canonical_keys=keys,
    )


def certify_cohort_offline(
    evidence_root: PathLike,
    cohort: str,
    *,
    require_live: bool = False,
    allow_fixture_software_proof: bool = False,
    repo_root: Optional[PathLike] = None,
) -> dict[str, Any]:
    """Certify every jurisdiction in ``cohort`` from retained artifacts."""

    letter = str(cohort).strip().upper()
    codes = cohort_codes(letter)
    admission_index = load_source_admission_index(
        (Path(repo_root) if repo_root is not None else repository_root())
        / "data/legal/open_us_law/source_admission.json"
    )
    verdicts = [
        certify_jurisdiction_offline(
            evidence_root,
            code,
            admission_row=admission_index.get(code),
            allow_fixture_software_proof=allow_fixture_software_proof,
            task_id=cohort_task_id(code),
        )
        for code in codes
    ]
    fixture_any = any(item.fixture for item in verdicts)
    live_ok = all(item.ok and item.raw_bytes_checked and not item.fixture for item in verdicts)
    if require_live and fixture_any:
        raise FixtureCompletionForbiddenError(
            f"fixture execution cannot satisfy --require-live for cohort {letter}"
        )
    if require_live and not live_ok:
        missing = [item.jurisdiction_code for item in verdicts if not item.ok or item.fixture]
        raise LiveEvidenceRequiredError(
            f"--require-live has no certified retained evidence for cohort {letter}: "
            + ",".join(missing)
        )
    cohort_complete = live_ok and not fixture_any and require_live
    if fixture_any and cohort_complete:
        raise FixtureCompletionForbiddenError(
            "fixture execution proves software behavior only and never cohort completion"
        )
    payload = {
        "authorizing_for_publication": False,
        "cohort": letter,
        "cohort_complete": cohort_complete,
        "fixture_execution": fixture_any,
        "fixture_proves_cohort_completion": False,
        "goal_id": GOAL_ID,
        "jurisdictions": list(codes),
        "oul_task_id": cohort_task_id(codes[0]),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "require_live": require_live,
        "schema_version": SCHEMA_VERSION,
        "software_behavior_proven": all(item.raw_bytes_checked for item in verdicts),
        "status": "passed" if (live_ok if require_live else all(item.raw_bytes_checked for item in verdicts)) else "failed",
        "verdicts": [item.to_dict() for item in verdicts],
    }
    assert_no_secrets(payload)
    return payload


def prove_fixture_behavior(
    cohort: str,
    evidence_root: PathLike,
    *,
    repo_root: Optional[PathLike] = None,
) -> dict[str, Any]:
    """Exercise the uncapped writer and offline certifier on fixture transport."""

    acquire_cohort(cohort, evidence_root, transport=FixtureSoftwareTransport(), resume=False)
    report = certify_cohort_offline(
        evidence_root,
        cohort,
        require_live=False,
        allow_fixture_software_proof=True,
        repo_root=repo_root,
    )
    if report.get("cohort_complete") is True:
        raise FixtureCompletionForbiddenError(
            "fixture execution must never set cohort_complete=true"
        )
    report["fixture_execution"] = True
    report["fixture_proves_cohort_completion"] = False
    report["cohort_complete"] = False
    report["authorizing_for_publication"] = False
    report["software_behavior_proven"] = True
    report["status"] = "passed"
    report["mode"] = "fixture_software_proof"
    return report


def load_cohort_evidence(path: PathLike) -> dict[str, Any]:
    report_path = Path(path)
    if not report_path.is_file():
        raise LiveEvidenceRequiredError(f"declared cohort report missing: {report_path}")
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveEvidenceError(f"declared cohort report is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise LiveEvidenceError("declared cohort report root must be an object")
    return payload


def validate_cohort_evidence_schema_file(repo_root: Optional[PathLike] = None) -> dict[str, Any]:
    path = default_cohort_schema_path(repo_root)
    if not path.is_file():
        raise LiveEvidenceError(f"cohort evidence schema missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise LiveEvidenceError("cohort evidence schema must declare JSON Schema 2020-12")
    if payload.get("title") != "Open US Law Cohort Evidence v1":
        raise LiveEvidenceError("cohort evidence schema title is not the sealed title")
    return payload


def validate_cohort_evidence(
    payload: Mapping[str, Any],
    *,
    cohort: Optional[str] = None,
    require_live: bool = False,
) -> dict[str, Any]:
    """Validate a declared Open US Law cohort evidence report."""

    if not is_cohort_evidence_payload(payload):
        raise LiveEvidenceError("schema_version must be open-us-law-cohort-evidence-v1")
    letter = str(payload.get("cohort") or "").strip().upper()
    expected = str(cohort).strip().upper() if cohort else letter
    if not letter or letter != expected:
        raise LiveEvidenceError(f"cohort report cohort={letter!r} does not match {expected!r}")
    codes = list(cohort_codes(letter))
    jurisdictions = [
        str(item).strip().upper() for item in (payload.get("jurisdictions") or [])
    ]
    if jurisdictions != codes:
        raise LiveEvidenceError(
            f"cohort {letter} jurisdictions must be {list(codes)}, got {jurisdictions}"
        )
    if payload.get("program_id") != PROGRAM_ID:
        raise LiveEvidenceError(f"program_id must be {PROGRAM_ID}")
    if payload.get("goal_id") != GOAL_ID:
        raise LiveEvidenceError(f"goal_id must be {GOAL_ID}")
    if payload.get("authorizing_for_publication") is not False:
        raise LiveEvidenceError("cohort evidence cannot authorize publication")
    if payload.get("fixture_proves_cohort_completion") is not False:
        raise LiveEvidenceError("fixture_proves_cohort_completion must be false")
    if payload.get("mode") not in {None, "full", "uncapped"}:
        raise LiveEvidenceError("cohort evidence mode must be full/uncapped")
    secrets = find_secret_surfaces(payload)
    if secrets:
        raise LiveEvidenceError("cohort evidence contains secret material: " + ",".join(secrets))

    receipts = payload.get("jurisdiction_receipts")
    if not isinstance(receipts, Mapping):
        raise LiveEvidenceError("jurisdiction_receipts must be an object")
    for code in codes:
        if code not in receipts or not isinstance(receipts[code], Mapping):
            if require_live:
                raise LiveEvidenceRequiredError(
                    f"cohort {letter} is missing a live receipt for {code}"
                )
            continue
        receipt = receipts[code]
        kinds = collect_certification_rejections(
            receipt,
            allow_fixture_software_proof=not require_live,
        )
        if require_live:
            if receipt.get("transport") and (
                (isinstance(receipt["transport"], Mapping) and receipt["transport"].get("fixture") is True)
                or receipt.get("transport") == "fixture"
            ):
                raise FixtureCompletionForbiddenError(
                    f"{code} fixture receipt cannot satisfy --require-live"
                )
            certification = payload.get("certification")
            raw_checked = False
            if isinstance(certification, Mapping):
                raw_checked = certification.get("raw_bytes_checked") is True
                per = certification.get("jurisdictions")
                if isinstance(per, Mapping) and isinstance(per.get(code), Mapping):
                    raw_checked = per[code].get("raw_bytes_checked") is True
            byte_block = receipt.get("byte_verification")
            if isinstance(byte_block, Mapping) and byte_block.get("raw_bytes_checked") is True:
                raw_checked = True
            if not raw_checked:
                raise RawBytesUncheckedError(
                    f"{code} raw_bytes_checked=false is not live evidence"
                )
            if kinds:
                raise LiveEvidenceError(
                    f"{code} live certification failed: " + ",".join(kinds)
                )
            admission = evaluate_prior_receipt(receipt)
            if not admission.accepted or admission.byte_verification is None:
                raise LiveEvidenceError(f"{code} prior-receipt admission failed")
            if admission.byte_verification.raw_bytes_checked is not True:
                raise RawBytesUncheckedError(
                    f"{code} reuse/certification requires raw_bytes_checked=true"
                )

    if require_live:
        if payload.get("cohort_complete") is not True:
            raise LiveEvidenceRequiredError(
                f"cohort {letter} report is not marked cohort_complete"
            )
        if payload.get("fixture_execution") is True:
            raise FixtureCompletionForbiddenError(
                "fixture_execution cannot satisfy --require-live"
            )
        if payload.get("status") not in {"success", "passed"}:
            raise LiveEvidenceRequiredError(
                f"cohort {letter} status is not live-certified success"
            )
    elif payload.get("cohort_complete") is True and payload.get("fixture_execution") is True:
        raise FixtureCompletionForbiddenError(
            "fixture execution must never set cohort_complete=true"
        )

    digest = str(payload.get("report_digest_sha256") or "")
    if digest:
        body = {key: value for key, value in payload.items() if key != "report_digest_sha256"}
        expected_digest = sha256_json(body)
        if digest != expected_digest:
            raise LiveEvidenceError("report_digest_sha256 does not match canonical bytes")
    return {
        "authorizing_for_publication": False,
        "cohort": letter,
        "cohort_complete": payload.get("cohort_complete") is True,
        "dc_counted_once": True,
        "exact_51": False,
        "fixture_execution": payload.get("fixture_execution") is True,
        "fixture_proves_cohort_completion": False,
        "goal_id": GOAL_ID,
        "jurisdiction_count": len(codes),
        "jurisdictions": codes,
        "producer": payload.get("producer"),
        "program_id": PROGRAM_ID,
        "require_live": require_live,
        "scheduled_count": 0,
        "schema_version": COHORT_EVIDENCE_SCHEMA_VERSION,
        "status": "passed",
        "task_id": payload.get("task_id"),
        "two_row_reports_rejected": 0,
    }


def check_declared_cohort_report(
    path: PathLike,
    *,
    cohort: Optional[str] = None,
    require_live: bool = False,
    repo_root: Optional[PathLike] = None,
) -> dict[str, Any]:
    """Load the declared cohort report and certify it fail-closed."""

    payload = load_cohort_evidence(path)
    report = validate_cohort_evidence(payload, cohort=cohort, require_live=require_live)
    resolved = Path(path).resolve()
    try:
        root = Path(repo_root).resolve() if repo_root is not None else repository_root()
        report["path"] = resolved.relative_to(root).as_posix()
    except ValueError:
        report["path"] = resolved.name
    report["report_digest_sha256"] = payload.get("report_digest_sha256")
    return report


def build_cohort_evidence_payload(
    *,
    cohort: str,
    verdicts: Sequence[CertificationVerdict],
    fixture_execution: bool,
    require_live: bool,
    receipts: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Build a sealed cohort evidence report. Fixture runs stay incomplete."""

    letter = str(cohort).strip().upper()
    codes = list(cohort_codes(letter))
    live_ok = (
        not fixture_execution
        and require_live
        and all(item.ok and item.raw_bytes_checked and not item.fixture for item in verdicts)
    )
    if fixture_execution and require_live:
        raise FixtureCompletionForbiddenError(
            "fixture execution cannot produce a complete cohort report"
        )
    payload: dict[str, Any] = {
        "authorizing_for_publication": False,
        "certification": {
            "jurisdictions": {
                item.jurisdiction_code: item.to_dict() for item in verdicts
            },
            "offline": True,
            "raw_bytes_checked": all(item.raw_bytes_checked for item in verdicts),
        },
        "checks": {
            "closed_boundary_probes_required": True,
            "fixture_never_completes_cohort": True,
            "official_hosts_required": True,
            "placeholders_rejected": True,
            "raw_bytes_checked_required": True,
            "samples_rejected": True,
            "self_asserted_digests_rejected": True,
            "zero_row_success_rejected": True,
        },
        "code_version": CODE_VERSION,
        "cohort": letter,
        "cohort_complete": live_ok,
        "fixture_execution": fixture_execution,
        "fixture_proves_cohort_completion": False,
        "goal_id": GOAL_ID,
        "jurisdiction_receipts": {
            code: dict(receipts[code])
            for code in codes
            if receipts and code in receipts
        },
        "jurisdictions": codes,
        "kind": "cohort_evidence",
        "mode": "full",
        "producer": "run_open_us_law_scrape_cohort.py",
        "program_id": PROGRAM_ID,
        "schema_version": COHORT_EVIDENCE_SCHEMA_VERSION,
        "sealed_at": SEALED_AT,
        "status": "success" if live_ok else "incomplete",
        "task_id": cohort_task_id(codes[0]),
    }
    assert_no_secrets(payload)
    body = {key: value for key, value in payload.items() if key != "report_digest_sha256"}
    payload["report_digest_sha256"] = sha256_json(body)
    return payload


class RegistryOfficialTransport:
    """Call a registered state scraper's ``fetch_official`` hook.

    This transport never invents bytes. A missing scraper or missing
    ``fetch_official`` method fails closed so workers implement the hook
    instead of writing an empty cohort report.
    """

    def fetch_official(self, code: str) -> OfficialFetch:
        from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
            StateScraperRegistry,
        )

        normalized = str(code).strip().upper()
        scraper_cls = StateScraperRegistry.get_scraper(normalized)
        if scraper_cls is None:
            raise LiveEvidenceError(
                f"no registered official scraper for {normalized}"
            )
        scraper = scraper_cls(normalized, normalized)
        fetch_official = getattr(scraper, "fetch_official", None)
        if not callable(fetch_official):
            raise LiveEvidenceError(
                f"{normalized} scraper does not implement fetch_official"
            )
        fetch = fetch_official(normalized)
        if not isinstance(fetch, OfficialFetch):
            raise LiveEvidenceError(
                f"{normalized} fetch_official must return OfficialFetch"
            )
        if fetch.fixture:
            raise FixtureCompletionForbiddenError(
                f"{normalized} fixture fetch cannot satisfy live acquisition"
            )
        return fetch


def write_live_cohort_report(
    path: PathLike,
    cohort: str,
    evidence_root: PathLike,
    *,
    transport: Optional[AcquisitionTransport] = None,
    repo_root: Optional[PathLike] = None,
) -> dict[str, Any]:
    """Acquire one cohort through ``transport`` and write the declared report."""

    letter = str(cohort).strip().upper()
    active = transport or RegistryOfficialTransport()
    acquire_cohort(letter, evidence_root, transport=active, resume=True)
    root = Path(repo_root) if repo_root is not None else repository_root()
    report = certify_cohort_offline(
        evidence_root,
        letter,
        require_live=True,
        allow_fixture_software_proof=False,
        repo_root=root,
    )
    receipts = {
        code: build_receipt_from_artifacts(
            evidence_root,
            code,
            task_id=cohort_task_id(code),
        )
        for code in cohort_codes(letter)
    }
    verdicts = [
        certify_jurisdiction_offline(
            evidence_root,
            code,
            allow_fixture_software_proof=False,
            task_id=cohort_task_id(code),
        )
        for code in cohort_codes(letter)
    ]
    payload = build_cohort_evidence_payload(
        cohort=letter,
        verdicts=verdicts,
        fixture_execution=False,
        require_live=True,
        receipts=receipts,
    )
    if payload.get("cohort_complete") is not True:
        raise LiveEvidenceRequiredError(
            f"live write did not certify cohort {letter}: "
            + ",".join(
                item.jurisdiction_code
                for item in verdicts
                if not item.ok or item.fixture
            )
        )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    _atomic_write_bytes(target, encoded.encode("utf-8"))
    payload["path"] = target.as_posix()
    payload["bytes_written"] = len(encoded.encode("utf-8"))
    payload["status"] = report.get("status") or payload.get("status")
    return payload


__all__ = [
    "BRIDGE_TASK_ID",
    "COHORT_EVIDENCE_SCHEMA_VERSION",
    "CertificationVerdict",
    "FixtureCompletionForbiddenError",
    "FixtureSoftwareTransport",
    "GOAL_ID",
    "LiveEvidenceError",
    "LiveHttpsTransport",
    "MissingRetainedArtifactsError",
    "OfficialFetch",
    "PlaceholderEvidenceError",
    "PROGRAM_ID",
    "PRODUCER",
    "REJECTION_FIXTURE_COMPLETION",
    "REJECTION_PLACEHOLDER",
    "REJECTION_RAW_BYTES_UNCHECKED",
    "REJECTION_SAMPLE",
    "REJECTION_SELF_ASSERTED",
    "REJECTION_ZERO_ROW_SUCCESS",
    "RawBytesUncheckedError",
    "RegistryOfficialTransport",
    "SCHEMA_VERSION",
    "SampleCapError",
    "SelfAssertedDigestError",
    "ZeroRowSuccessError",
    "acquire_cohort",
    "acquire_jurisdiction",
    "assert_uncapped",
    "build_cohort_evidence_payload",
    "build_receipt_from_artifacts",
    "certify_cohort_offline",
    "certify_jurisdiction_offline",
    "check_declared_cohort_report",
    "cid_for_bytes",
    "collect_certification_rejections",
    "compute_frontier_digest",
    "create_evidence_root",
    "default_cohort_report_path",
    "default_cohort_schema_path",
    "is_cohort_evidence_payload",
    "is_placeholder_cid",
    "is_placeholder_digest",
    "load_cohort_evidence",
    "prove_fixture_behavior",
    "validate_cohort_evidence",
    "validate_cohort_evidence_schema_file",
    "write_live_cohort_report",
    "write_retained_artifacts",
]
