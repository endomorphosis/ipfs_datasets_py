#!/usr/bin/env python3
"""Seal and audit the exact-51 Open US Law official-source admission matrix.

The committed matrix is the OUL-002 rights and admission contract. Every state
and DC must declare an official authority, rights scope, attribution duty,
frontier method, and typed seed disposition. Georgia, North Carolina,
nonofficial rows, and linkless rows fail closed until official replacement
evidence exists.

Validation gate (no network)::

    python scripts/ops/legal_data/audit_open_us_law_sources.py --require-51 --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

TASK_ID = "OUL-002"
GOAL_ID = "OUL-G010"
PROGRAM_ID = "open-us-law-reindex-v1"
PRODUCER = "audit_open_us_law_sources.py@1"
SCHEMA_VERSION = "open-us-law-source-admission-v1"
REPORT_SCHEMA = "ipfs_datasets_py/open-us-law-source-admission-audit@1"
CODE_VERSION = "1"
SEALED_AT = "2026-08-13T00:00:00Z"

MATRIX_RELPATH = Path("data/legal/open_us_law/source_admission.json")
SCHEMA_RELPATH = Path("data/legal/open_us_law/source_admission.schema.json")
OFFICIAL_CATALOG_RELPATH = Path("data/legal/state_laws/official_source_catalog.json")

JURISDICTION_COUNT = 51
REQUIRED_JURISDICTION_CODES: tuple[str, ...] = (
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
FAIL_CLOSED_JURISDICTION_CODES: tuple[str, ...] = ("GA", "NC")
EXCLUDED_DEFAULT_CODES: frozenset[str] = frozenset({"PR", "US", "FED", "USA"})

DISPOSITION_BLOCKED = "blocked_until_official_replacement"
DISPOSITION_QUARANTINE = "quarantine_or_official_reacquisition"
DISPOSITION_LINK_REPAIR = "source_link_repair_or_typed_quarantine"
DISPOSITION_CANDIDATE = "candidate_seed_pending_frontier_reconciliation"
TYPED_SEED_DISPOSITIONS: frozenset[str] = frozenset(
    {
        DISPOSITION_BLOCKED,
        DISPOSITION_QUARANTINE,
        DISPOSITION_LINK_REPAIR,
        DISPOSITION_CANDIDATE,
    }
)

BLOCKED_CODES: frozenset[str] = frozenset(FAIL_CLOSED_JURISDICTION_CODES)
QUARANTINE_CODES: frozenset[str] = frozenset(
    {"AR", "MS", "NM", "NV", "OR", "TN", "WY"}
)
LINK_REPAIR_CODES: frozenset[str] = frozenset(
    {"AK", "AL", "CA", "LA", "MA", "NJ"}
)

LICENSE_ID = "LicenseRef-US-State-Statutory-Text"
LICENSE_LEGAL_BASIS = "government_edicts_doctrine"
LICENSE_REF_DIGEST = (
    "d48cb14da98ecaa1f06e2ba498b17cadd9f0adaea38ceb28d71759ed049c8508"
)
CONTENT_SCOPE = "statutory_text"

CURRENTNESS_DISCLAIMER = (
    "Acquisition and publication timestamps record when a package was retrieved "
    "or sealed; they are not a claim that the codified text is legally current as "
    "of wall-clock time. Retrieval output is a research aid and is not a "
    "substitute for the official source."
)
MATRIX_DESCRIPTION = (
    "Exact-51 official-source rights and admission matrix for all 50 states and "
    "the District of Columbia. Bucket seed rows are never proof of completeness "
    "or freshness. Georgia and North Carolina, plus any nonofficial or linkless "
    "row, remain fail-closed until official replacement evidence exists."
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)
_CODE_RE = re.compile(r"^[A-Z]{2}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+\-]{0,159}$")
_REQUIRED_ROW_FIELDS: tuple[str, ...] = (
    "jurisdiction_code",
    "name",
    "official_authority",
    "rights_scope",
    "attribution_duty",
    "frontier_method",
    "seed_disposition",
)
_AUTHORITY_FIELDS: tuple[str, ...] = (
    "authority_id",
    "name",
    "authority_class",
    "role",
    "provider",
    "base_url",
    "entry_url",
    "allowed_domains",
)
_RIGHTS_FIELDS: tuple[str, ...] = (
    "content_scope",
    "license_id",
    "legal_basis",
    "license_ref_digest_sha256",
    "annotations_excluded",
    "site_presentation_excluded",
    "database_content_excluded",
    "admissible_for_statutory_text",
)
_ATTRIBUTION_FIELDS: tuple[str, ...] = (
    "required",
    "notice",
    "redistribution",
    "currentness_disclaimer_required",
)
_FRONTIER_FIELDS: tuple[str, ...] = (
    "method_id",
    "discovery_mode",
    "code_family_id",
    "code_family_name",
    "citation_prefix",
    "closed_frontier_required",
    "as_of_fields",
)
_DISPOSITION_FIELDS: tuple[str, ...] = (
    "disposition",
    "fail_closed",
    "bucket_seed_admissible",
    "publication_admissible",
    "official_replacement_evidence_required",
    "official_replacement_evidence_present",
    "official_replacement_evidence",
    "reason",
)
_REPLACEMENT_FIELDS: tuple[str, ...] = (
    "evidence_kind",
    "source_url",
    "observed_at",
    "response_sha256",
    "body_sha256",
    "frontier_digest_sha256",
    "contamination_cleared",
)
_DISCOVERY_MODES: frozenset[str] = frozenset(
    {"api", "hierarchy", "bundle", "pagination", "mixed"}
)
_PROVIDER_TOKEN_OVERRIDES: Mapping[str, str] = {
    "alison": "ALISON",
    "dc": "DC",
    "ilcs": "ILCS",
    "mcl": "MCL",
    "nrs": "NRS",
    "ors": "ORS",
}


class AuditError(RuntimeError):
    """Fail-closed source-admission audit failure."""


def expected_jurisdiction_codes() -> tuple[str, ...]:
    return REQUIRED_JURISDICTION_CODES


def expected_seed_disposition(code: str) -> str:
    if code in BLOCKED_CODES:
        return DISPOSITION_BLOCKED
    if code in QUARANTINE_CODES:
        return DISPOSITION_QUARANTINE
    if code in LINK_REPAIR_CODES:
        return DISPOSITION_LINK_REPAIR
    return DISPOSITION_CANDIDATE


def default_matrix_path() -> Path:
    return REPOSITORY_ROOT / MATRIX_RELPATH


def default_schema_path() -> Path:
    return REPOSITORY_ROOT / SCHEMA_RELPATH


def default_official_catalog_path() -> Path:
    return REPOSITORY_ROOT / OFFICIAL_CATALOG_RELPATH


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def is_official_source_url(url: object) -> bool:
    if not isinstance(url, str):
        return False
    stripped = url.strip()
    if not stripped or stripped != url:
        return False
    parsed = urlparse(stripped)
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc or " " in stripped:
        return False
    return True


def _title_provider(provider: str) -> str:
    parts: list[str] = []
    for token in provider.split("_"):
        parts.append(_PROVIDER_TOKEN_OVERRIDES.get(token, token.title()))
    return " ".join(parts)


def _strict_mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AuditError(f"{context} must be an object")
    return value


def _strict_string(value: object, context: str, *, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value) < minimum:
        raise AuditError(f"{context} must be a non-empty string")
    return value


def _strict_bool(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        raise AuditError(f"{context} must be a boolean")
    return value


def _strict_string_list(value: object, context: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise AuditError(f"{context} must be a non-empty list of strings")
    items: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        text = _strict_string(item, f"{context}[{index}]")
        if text in seen:
            raise AuditError(f"{context} contains a duplicate: {text}")
        seen.add(text)
        items.append(text)
    return items


def load_json(path: Path) -> Any:
    if not path.is_file():
        raise AuditError(f"required file is missing: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuditError(f"invalid JSON in {path}: {exc}") from exc


def load_schema() -> Mapping[str, Any]:
    payload = load_json(default_schema_path())
    if not isinstance(payload, Mapping):
        raise AuditError("source admission schema root must be an object")
    return payload


def load_official_source_catalog() -> Mapping[str, Any]:
    payload = load_json(default_official_catalog_path())
    if not isinstance(payload, Mapping):
        raise AuditError("official source catalog root must be an object")
    return payload


def load_source_admission(path: Path | None = None) -> dict[str, Any]:
    payload = load_json(path or default_matrix_path())
    if not isinstance(payload, dict):
        raise AuditError("source admission matrix root must be an object")
    return payload


def _index_official_catalog(
    catalog: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    rows = catalog.get("jurisdictions")
    if not isinstance(rows, list) or not rows:
        raise AuditError("official source catalog jurisdictions are missing")
    indexed: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        mapping = _strict_mapping(row, f"official_catalog.jurisdictions[{index}]")
        code = _strict_string(mapping.get("postal_code"), f"official_catalog[{index}].postal_code")
        if not _CODE_RE.fullmatch(code):
            raise AuditError(f"official catalog postal_code is invalid: {code}")
        if code in indexed:
            raise AuditError(f"official catalog duplicates jurisdiction {code}")
        indexed[code] = mapping
    return indexed


def _seed_reason(code: str, name: str, disposition: str) -> str:
    if disposition == DISPOSITION_BLOCKED:
        return (
            f"{name} ({code}) statutes were withdrawn from the v2026.07 bucket "
            "because navigation and footer contamination was embedded in section "
            "bodies. The jurisdiction remains fail-closed until clean official "
            "replacement evidence exists."
        )
    if disposition == DISPOSITION_QUARANTINE:
        return (
            f"{name} ({code}) bucket seed material is quarantined. Official "
            "reacquisition or typed quarantine is required before any row may "
            "satisfy the exact-51 gate."
        )
    if disposition == DISPOSITION_LINK_REPAIR:
        return (
            f"{name} ({code}) contains per-row source-link gaps. Unrepaired or "
            "untyped linkless rows remain fail-closed until official replacement "
            "or a typed quarantine exists."
        )
    return (
        f"{name} ({code}) official host is recorded as a candidate seed only. "
        "Fresh closed-frontier reconciliation is required before publication."
    )


def _build_jurisdiction_row(code: str, catalog_row: Mapping[str, Any]) -> dict[str, Any]:
    name = _strict_string(catalog_row.get("name"), f"{code}.name")
    families = catalog_row.get("code_families")
    if not isinstance(families, list) or not families:
        raise AuditError(f"{code} is missing an official code family")
    family = _strict_mapping(families[0], f"{code}.code_families[0]")
    paths = catalog_row.get("acquisition_paths")
    if not isinstance(paths, list) or not paths:
        raise AuditError(f"{code} is missing an official acquisition path")
    path = _strict_mapping(paths[0], f"{code}.acquisition_paths[0]")
    authority_class = _strict_string(
        path.get("authority_class"), f"{code}.authority_class"
    )
    if authority_class != "official":
        raise AuditError(f"{code} official catalog path is not official")
    entry_url = _strict_string(path.get("entry_url"), f"{code}.entry_url")
    if not is_official_source_url(entry_url):
        raise AuditError(f"{code} official catalog entry_url is linkless")
    provider = _strict_string(path.get("provider"), f"{code}.provider")
    disposition = expected_seed_disposition(code)
    fail_closed = disposition != DISPOSITION_CANDIDATE
    replacement_required = disposition in {DISPOSITION_BLOCKED, DISPOSITION_QUARANTINE}
    authority_name = _title_provider(provider)
    return {
        "jurisdiction_code": code,
        "name": name,
        "official_authority": {
            "authority_id": _strict_string(path.get("path_id"), f"{code}.path_id"),
            "name": authority_name,
            "authority_class": "official",
            "role": _strict_string(path.get("role"), f"{code}.role"),
            "provider": provider,
            "base_url": _strict_string(path.get("base_url"), f"{code}.base_url"),
            "entry_url": entry_url,
            "allowed_domains": _strict_string_list(
                path.get("allowed_domains"), f"{code}.allowed_domains"
            ),
        },
        "rights_scope": {
            "content_scope": CONTENT_SCOPE,
            "license_id": LICENSE_ID,
            "legal_basis": LICENSE_LEGAL_BASIS,
            "license_ref_digest_sha256": LICENSE_REF_DIGEST,
            "annotations_excluded": True,
            "site_presentation_excluded": True,
            "database_content_excluded": True,
            "admissible_for_statutory_text": True,
        },
        "attribution_duty": {
            "required": True,
            "notice": (
                f"Source: {authority_name}, "
                f"{_strict_string(family.get('display_name'), f'{code}.display_name')}. "
                "Statutory text is attributed to the official enacting authority. "
                "This corpus is a research aid and is not a substitute for the "
                "official source."
            ),
            "redistribution": "statutory_text_only",
            "currentness_disclaimer_required": True,
        },
        "frontier_method": {
            "method_id": _strict_string(
                family.get("bundle_discovery"), f"{code}.bundle_discovery"
            ),
            "discovery_mode": _strict_string(
                path.get("discovery_mode"), f"{code}.discovery_mode"
            ),
            "code_family_id": _strict_string(
                family.get("code_family_id"), f"{code}.code_family_id"
            ),
            "code_family_name": _strict_string(
                family.get("display_name"), f"{code}.display_name"
            ),
            "citation_prefix": _strict_string(
                family.get("citation_prefix"), f"{code}.citation_prefix"
            ),
            "closed_frontier_required": True,
            "as_of_fields": list(
                path.get("as_of_fields")
                or ["edition", "publication_date", "retrieval_time"]
            ),
        },
        "seed_disposition": {
            "disposition": disposition,
            "fail_closed": fail_closed,
            "bucket_seed_admissible": False,
            "publication_admissible": False,
            "official_replacement_evidence_required": replacement_required,
            "official_replacement_evidence_present": False,
            "official_replacement_evidence": None,
            "reason": _seed_reason(code, name, disposition),
        },
    }


def build_source_admission_payload(
    catalog: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the deterministic exact-51 source-admission matrix."""

    indexed = _index_official_catalog(catalog or load_official_source_catalog())
    missing = [code for code in REQUIRED_JURISDICTION_CODES if code not in indexed]
    if missing:
        raise AuditError(
            "official source catalog is missing required jurisdictions: "
            + ",".join(missing)
        )
    jurisdictions = [
        _build_jurisdiction_row(code, indexed[code])
        for code in REQUIRED_JURISDICTION_CODES
    ]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "sealed_at": SEALED_AT,
        "authorizing_for_publication": False,
        "jurisdiction_count": JURISDICTION_COUNT,
        "required_jurisdiction_codes": list(REQUIRED_JURISDICTION_CODES),
        "fail_closed_jurisdiction_codes": list(FAIL_CLOSED_JURISDICTION_CODES),
        "publication_admitted_jurisdiction_codes": [],
        "description": MATRIX_DESCRIPTION,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "jurisdictions": jurisdictions,
    }
    payload["matrix_digest_sha256"] = sha256_json(
        {key: value for key, value in payload.items() if key != "matrix_digest_sha256"}
    )
    return payload


def encode_source_admission(payload: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes(payload)


def write_source_admission(path: Path | None = None) -> Path:
    target = path or default_matrix_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encode_source_admission(build_source_admission_payload()))
    return target


def _validate_schema_with_jsonschema(payload: Mapping[str, Any]) -> None:
    schema = load_schema()
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        _validate_schema_structurally(payload)
        return
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise AuditError(f"schema validation failed at {location}: {first.message}")


def _validate_schema_structurally(payload: Mapping[str, Any]) -> None:
    required_root = (
        "schema_version",
        "producer",
        "program_id",
        "task_id",
        "goal_id",
        "sealed_at",
        "authorizing_for_publication",
        "jurisdiction_count",
        "required_jurisdiction_codes",
        "fail_closed_jurisdiction_codes",
        "publication_admitted_jurisdiction_codes",
        "description",
        "currentness_disclaimer",
        "jurisdictions",
        "matrix_digest_sha256",
    )
    _require_keys(payload, required_root, "source_admission")
    if not isinstance(payload.get("jurisdictions"), list):
        raise AuditError("jurisdictions must be a list")
    if len(payload["jurisdictions"]) != JURISDICTION_COUNT:
        raise AuditError("schema requires exactly 51 jurisdiction rows")


def _require_keys(
    mapping: Mapping[str, Any], required: Sequence[str], context: str
) -> None:
    missing = [key for key in required if key not in mapping]
    extra = [key for key in mapping if key not in required]
    if missing:
        raise AuditError(f"{context} is missing required fields: {','.join(missing)}")
    if extra:
        raise AuditError(f"{context} has unexpected fields: {','.join(sorted(extra))}")


def _validate_replacement_evidence(
    evidence: object, context: str
) -> Mapping[str, Any]:
    mapping = _strict_mapping(evidence, context)
    _require_keys(mapping, _REPLACEMENT_FIELDS, context)
    if mapping.get("evidence_kind") != "official_replacement":
        raise AuditError(f"{context}.evidence_kind must be official_replacement")
    source_url = _strict_string(mapping.get("source_url"), f"{context}.source_url")
    if not is_official_source_url(source_url):
        raise AuditError(f"{context}.source_url is not an official source URL")
    observed_at = _strict_string(mapping.get("observed_at"), f"{context}.observed_at")
    if not _UTC_RE.fullmatch(observed_at):
        raise AuditError(f"{context}.observed_at is not a UTC timestamp")
    for digest_field in ("response_sha256", "body_sha256", "frontier_digest_sha256"):
        digest = _strict_string(mapping.get(digest_field), f"{context}.{digest_field}")
        if not _SHA256_RE.fullmatch(digest):
            raise AuditError(f"{context}.{digest_field} is not a SHA-256 digest")
    if mapping.get("contamination_cleared") is not True:
        raise AuditError(f"{context}.contamination_cleared must be true")
    return mapping


def _has_valid_replacement_evidence(disposition: Mapping[str, Any], context: str) -> bool:
    present = _strict_bool(
        disposition.get("official_replacement_evidence_present"),
        f"{context}.official_replacement_evidence_present",
    )
    evidence = disposition.get("official_replacement_evidence")
    if not present:
        if evidence is not None:
            raise AuditError(
                f"{context}.official_replacement_evidence must be null when absent"
            )
        return False
    _validate_replacement_evidence(evidence, f"{context}.official_replacement_evidence")
    return True


def _validate_rights_scope(scope: Mapping[str, Any], context: str) -> None:
    _require_keys(scope, _RIGHTS_FIELDS, context)
    if scope.get("content_scope") != CONTENT_SCOPE:
        raise AuditError(f"{context}.content_scope must be {CONTENT_SCOPE}")
    if scope.get("license_id") != LICENSE_ID:
        raise AuditError(f"{context}.license_id must be {LICENSE_ID}")
    if scope.get("legal_basis") != LICENSE_LEGAL_BASIS:
        raise AuditError(f"{context}.legal_basis must be {LICENSE_LEGAL_BASIS}")
    digest = _strict_string(
        scope.get("license_ref_digest_sha256"), f"{context}.license_ref_digest_sha256"
    )
    if digest != LICENSE_REF_DIGEST:
        raise AuditError(f"{context}.license_ref_digest_sha256 does not match the sealed LicenseRef")
    for flag in (
        "annotations_excluded",
        "site_presentation_excluded",
        "database_content_excluded",
        "admissible_for_statutory_text",
    ):
        if scope.get(flag) is not True:
            raise AuditError(f"{context}.{flag} must be true")


def _validate_attribution_duty(
    duty: Mapping[str, Any], context: str, authority_name: str
) -> None:
    _require_keys(duty, _ATTRIBUTION_FIELDS, context)
    if duty.get("required") is not True:
        raise AuditError(f"{context}.required must be true")
    if duty.get("currentness_disclaimer_required") is not True:
        raise AuditError(f"{context}.currentness_disclaimer_required must be true")
    if duty.get("redistribution") != "statutory_text_only":
        raise AuditError(f"{context}.redistribution must be statutory_text_only")
    notice = _strict_string(duty.get("notice"), f"{context}.notice")
    if authority_name not in notice:
        raise AuditError(f"{context}.notice must name the official authority")


def _validate_frontier_method(method: Mapping[str, Any], context: str) -> None:
    _require_keys(method, _FRONTIER_FIELDS, context)
    method_id = _strict_string(method.get("method_id"), f"{context}.method_id")
    if not _IDENTIFIER_RE.fullmatch(method_id):
        raise AuditError(f"{context}.method_id is not a typed identifier")
    discovery = _strict_string(method.get("discovery_mode"), f"{context}.discovery_mode")
    if discovery not in _DISCOVERY_MODES:
        raise AuditError(f"{context}.discovery_mode is not a typed frontier method")
    _strict_string(method.get("code_family_id"), f"{context}.code_family_id")
    _strict_string(method.get("code_family_name"), f"{context}.code_family_name")
    _strict_string(method.get("citation_prefix"), f"{context}.citation_prefix")
    if method.get("closed_frontier_required") is not True:
        raise AuditError(f"{context}.closed_frontier_required must be true")
    _strict_string_list(method.get("as_of_fields"), f"{context}.as_of_fields")


def _validate_official_authority(authority: Mapping[str, Any], context: str) -> None:
    _require_keys(authority, _AUTHORITY_FIELDS, context)
    _strict_string(authority.get("authority_id"), f"{context}.authority_id")
    _strict_string(authority.get("name"), f"{context}.name")
    _strict_string(authority.get("role"), f"{context}.role")
    _strict_string(authority.get("provider"), f"{context}.provider")
    _strict_string_list(authority.get("allowed_domains"), f"{context}.allowed_domains")
    if not is_official_source_url(authority.get("base_url")):
        raise AuditError(f"{context}.base_url is not an official source URL")


def _row_is_nonofficial(authority: Mapping[str, Any]) -> bool:
    return authority.get("authority_class") != "official"


def _row_is_linkless(authority: Mapping[str, Any]) -> bool:
    return not is_official_source_url(authority.get("entry_url"))


def _validate_seed_disposition(
    *,
    code: str,
    disposition: Mapping[str, Any],
    context: str,
    nonofficial: bool,
    linkless: bool,
) -> None:
    _require_keys(disposition, _DISPOSITION_FIELDS, context)
    typed = _strict_string(disposition.get("disposition"), f"{context}.disposition")
    if typed not in TYPED_SEED_DISPOSITIONS:
        raise AuditError(f"{context}.disposition is not a typed seed disposition")
    expected = expected_seed_disposition(code)
    has_replacement = _has_valid_replacement_evidence(disposition, context)
    fail_closed = _strict_bool(disposition.get("fail_closed"), f"{context}.fail_closed")
    bucket_ok = _strict_bool(
        disposition.get("bucket_seed_admissible"), f"{context}.bucket_seed_admissible"
    )
    publication_ok = _strict_bool(
        disposition.get("publication_admissible"), f"{context}.publication_admissible"
    )
    required = _strict_bool(
        disposition.get("official_replacement_evidence_required"),
        f"{context}.official_replacement_evidence_required",
    )
    _strict_string(disposition.get("reason"), f"{context}.reason")

    blocked = code in BLOCKED_CODES
    if blocked and typed != DISPOSITION_BLOCKED and not has_replacement:
        raise AuditError(
            f"{code} must use {DISPOSITION_BLOCKED} until official replacement "
            "evidence exists"
        )
    if not blocked and typed != expected:
        raise AuditError(f"{code} seed disposition must be {expected}")
    if expected in {DISPOSITION_BLOCKED, DISPOSITION_QUARANTINE} and not required:
        raise AuditError(f"{code} official replacement evidence is required")

    must_fail_closed = blocked or nonofficial or linkless or not has_replacement and typed != DISPOSITION_CANDIDATE
    if (blocked or nonofficial or linkless) and not has_replacement:
        if not fail_closed:
            raise AuditError(
                f"{code} must fail closed until official replacement evidence exists"
            )
        if bucket_ok or publication_ok:
            raise AuditError(
                f"{code} cannot admit bucket or publication rows until official "
                "replacement evidence exists"
            )
    if must_fail_closed and typed == DISPOSITION_CANDIDATE and (blocked or nonofficial or linkless):
        raise AuditError(f"{code} candidate disposition cannot cover a fail-closed row")
    if publication_ok and (blocked or nonofficial or linkless) and not has_replacement:
        raise AuditError(f"{code} publication admission is fail-closed")


def validate_jurisdiction_row(row: Mapping[str, Any], *, index: int) -> str:
    context = f"jurisdictions[{index}]"
    mapping = _strict_mapping(row, context)
    _require_keys(mapping, _REQUIRED_ROW_FIELDS, context)
    code = _strict_string(mapping.get("jurisdiction_code"), f"{context}.jurisdiction_code")
    if not _CODE_RE.fullmatch(code):
        raise AuditError(f"{context}.jurisdiction_code is invalid: {code}")
    if code in EXCLUDED_DEFAULT_CODES:
        raise AuditError(f"{code} is excluded from the exact-51 default set")
    _strict_string(mapping.get("name"), f"{context}.name")
    authority = _strict_mapping(
        mapping.get("official_authority"), f"{context}.official_authority"
    )
    _validate_official_authority(authority, f"{context}.official_authority")
    nonofficial = _row_is_nonofficial(authority)
    linkless = _row_is_linkless(authority)
    rights = _strict_mapping(mapping.get("rights_scope"), f"{context}.rights_scope")
    _validate_rights_scope(rights, f"{context}.rights_scope")
    duty = _strict_mapping(
        mapping.get("attribution_duty"), f"{context}.attribution_duty"
    )
    _validate_attribution_duty(
        duty, f"{context}.attribution_duty", _strict_string(authority.get("name"), f"{context}.official_authority.name")
    )
    frontier = _strict_mapping(
        mapping.get("frontier_method"), f"{context}.frontier_method"
    )
    _validate_frontier_method(frontier, f"{context}.frontier_method")
    disposition = _strict_mapping(
        mapping.get("seed_disposition"), f"{context}.seed_disposition"
    )
    has_replacement = False
    if disposition.get("official_replacement_evidence_present") is True:
        has_replacement = _has_valid_replacement_evidence(
            disposition, f"{context}.seed_disposition"
        )
    if nonofficial and not has_replacement:
        raise AuditError(
            f"{code} is nonofficial and fails closed until official replacement "
            "evidence exists"
        )
    if linkless and not has_replacement:
        raise AuditError(
            f"{code} is linkless and fails closed until official replacement "
            "evidence exists"
        )
    _validate_seed_disposition(
        code=code,
        disposition=disposition,
        context=f"{context}.seed_disposition",
        nonofficial=nonofficial,
        linkless=linkless,
    )
    return code


def validate_source_admission(
    payload: Mapping[str, Any], *, require_51: bool = True
) -> dict[str, Any]:
    mapping = _strict_mapping(payload, "source_admission")
    if mapping.get("schema_version") != SCHEMA_VERSION:
        raise AuditError("schema_version must be open-us-law-source-admission-v1")
    if mapping.get("producer") != PRODUCER:
        raise AuditError(f"producer must be {PRODUCER}")
    if mapping.get("program_id") != PROGRAM_ID:
        raise AuditError(f"program_id must be {PROGRAM_ID}")
    if mapping.get("task_id") != TASK_ID:
        raise AuditError(f"task_id must be {TASK_ID}")
    if mapping.get("goal_id") != GOAL_ID:
        raise AuditError(f"goal_id must be {GOAL_ID}")
    sealed_at = _strict_string(mapping.get("sealed_at"), "sealed_at")
    if not _UTC_RE.fullmatch(sealed_at):
        raise AuditError("sealed_at is not a UTC timestamp")
    if mapping.get("authorizing_for_publication") is not False:
        raise AuditError("matrix cannot authorize publication")
    _strict_string(mapping.get("description"), "description")
    _strict_string(mapping.get("currentness_disclaimer"), "currentness_disclaimer")

    required_codes = _strict_string_list(
        mapping.get("required_jurisdiction_codes"), "required_jurisdiction_codes"
    )
    fail_closed_codes = _strict_string_list(
        mapping.get("fail_closed_jurisdiction_codes"), "fail_closed_jurisdiction_codes"
    )
    admitted = mapping.get("publication_admitted_jurisdiction_codes")
    if not isinstance(admitted, list):
        raise AuditError("publication_admitted_jurisdiction_codes must be a list")
    admitted_codes = [
        _strict_string(item, f"publication_admitted_jurisdiction_codes[{index}]")
        for index, item in enumerate(admitted)
    ]
    if len(admitted_codes) != len(set(admitted_codes)):
        raise AuditError("publication_admitted_jurisdiction_codes contains duplicates")

    rows = mapping.get("jurisdictions")
    if not isinstance(rows, list):
        raise AuditError("jurisdictions must be a list")
    observed: list[str] = []
    fail_closed_observed: list[str] = []
    for index, row in enumerate(rows):
        code = validate_jurisdiction_row(_strict_mapping(row, f"jurisdictions[{index}]"), index=index)
        observed.append(code)
        disposition = _strict_mapping(
            row.get("seed_disposition"), f"jurisdictions[{index}].seed_disposition"
        )
        if disposition.get("fail_closed") is True:
            fail_closed_observed.append(code)
    if len(observed) != len(set(observed)):
        raise AuditError("jurisdiction rows are not unique")
    if observed.count("DC") != 1:
        raise AuditError("DC must appear exactly once")
    extra_default = [code for code in observed if code in EXCLUDED_DEFAULT_CODES]
    if extra_default:
        raise AuditError(
            "default set includes excluded jurisdictions: " + ",".join(extra_default)
        )

    expected = list(REQUIRED_JURISDICTION_CODES)
    if require_51:
        if mapping.get("jurisdiction_count") != JURISDICTION_COUNT:
            raise AuditError("jurisdiction_count must be 51")
        if required_codes != expected:
            raise AuditError("required_jurisdiction_codes must be the exact-51 allowlist")
        if observed != expected:
            missing = [code for code in expected if code not in observed]
            extra = [code for code in observed if code not in expected]
            raise AuditError(
                "jurisdiction set is not exact-51; "
                f"missing={missing or '[]'} extra={extra or '[]'}"
            )
        if set(fail_closed_codes) < set(FAIL_CLOSED_JURISDICTION_CODES):
            raise AuditError("fail_closed_jurisdiction_codes must include GA and NC")

    blocked_without_evidence = [
        code
        for code in FAIL_CLOSED_JURISDICTION_CODES
        if code in observed
    ]
    for code in blocked_without_evidence:
        row = next(item for item in rows if item.get("jurisdiction_code") == code)
        disposition = _strict_mapping(row.get("seed_disposition"), f"{code}.seed_disposition")
        has_replacement = disposition.get("official_replacement_evidence_present") is True
        if not has_replacement and code in admitted_codes:
            raise AuditError(
                f"{code} cannot be publication-admitted until official replacement "
                "evidence exists"
            )

    body = {key: value for key, value in mapping.items() if key != "matrix_digest_sha256"}
    expected_digest = sha256_json(body)
    digest = _strict_string(mapping.get("matrix_digest_sha256"), "matrix_digest_sha256")
    if not _SHA256_RE.fullmatch(digest):
        raise AuditError("matrix_digest_sha256 is not a SHA-256 digest")
    if digest != expected_digest:
        raise AuditError("matrix_digest_sha256 does not match the canonical matrix bytes")

    _validate_schema_with_jsonschema(mapping)
    return {
        "jurisdiction_count": len(observed),
        "jurisdiction_codes": observed,
        "fail_closed_jurisdiction_codes": fail_closed_observed,
        "publication_admitted_jurisdiction_codes": admitted_codes,
        "matrix_digest_sha256": digest,
    }


def audit_source_admission(
    payload: Mapping[str, Any] | None = None, *, require_51: bool = True
) -> dict[str, Any]:
    matrix = payload if payload is not None else load_source_admission()
    projection = validate_source_admission(matrix, require_51=require_51)
    report = {
        "report_schema": REPORT_SCHEMA,
        "code_version": CODE_VERSION,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "status": "passed",
        "require_51": require_51,
        "authorizing_for_publication": False,
        "exact_51": projection["jurisdiction_codes"] == list(REQUIRED_JURISDICTION_CODES),
        "dc_counted_once": projection["jurisdiction_codes"].count("DC") == 1,
        **projection,
    }
    report["report_digest_sha256"] = sha256_json(report)
    return report


def check_committed_matrix(*, require_51: bool = True) -> dict[str, Any]:
    committed_path = default_matrix_path()
    committed_bytes = committed_path.read_bytes() if committed_path.is_file() else b""
    generated = build_source_admission_payload()
    generated_bytes = encode_source_admission(generated)
    if committed_bytes != generated_bytes:
        raise AuditError(
            "committed source_admission.json differs from the deterministic "
            "exact-51 builder; regenerate and commit the sealed matrix"
        )
    return audit_source_admission(generated, require_51=require_51)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit the exact-51 Open US Law source admission matrix"
    )
    parser.add_argument(
        "--require-51",
        dest="require_51",
        action="store_true",
        help="Require exact set equality with the 50-state-plus-DC allowlist.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the committed matrix against the sealed builder and schema.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the audit report as JSON.")
    return parser


def _print_json(value: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.check:
        sys.stderr.write("audit_open_us_law_sources: FAILED: --check is required\n")
        return 2
    if not args.require_51:
        sys.stderr.write("audit_open_us_law_sources: FAILED: --require-51 is required\n")
        return 2
    try:
        report = check_committed_matrix(require_51=True)
    except AuditError as exc:
        if args.json:
            _print_json(
                {
                    "status": "failed",
                    "producer": PRODUCER,
                    "program_id": PROGRAM_ID,
                    "task_id": TASK_ID,
                    "authorizing_for_publication": False,
                    "error": str(exc),
                }
            )
        else:
            sys.stderr.write(f"audit_open_us_law_sources: FAILED: {exc}\n")
        return 1
    if args.json:
        _print_json(report)
    else:
        sys.stdout.write(
            "audit_open_us_law_sources: PASSED "
            f"(jurisdictions={report['jurisdiction_count']} "
            f"exact_51={report['exact_51']} "
            f"dc_counted_once={report['dc_counted_once']})\n"
            f"  fail_closed={','.join(FAIL_CLOSED_JURISDICTION_CODES)}\n"
            f"  matrix_digest={report['matrix_digest_sha256']}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
