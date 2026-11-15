"""Content-free redaction policy for portfolio operator emits (PATLAW-209).

Locks the portfolio operator surfaces so that matter-status, dashboard, audit
markdown, IDS exports, and canary receipts never print:

* secrets / credentials / cookies / bearer tokens
* PDF-like or binary document bodies
* raw provider payloads and extracted text

Emit helpers project existing portfolio builders through a single redaction
gate and fail closed when forbidden markers remain. Property tests inject
secret-like tokens and PDF-like bodies and assert they never appear.

Hard rules
----------
* Never weaken redaction to make a test pass.
* Sign / Pay / Submit / IDS auto-file remain human-only (not automated here).
* Source must not embed contiguous secret-assignment forms (proposal gate);
  forbidden markers are assembled from split fragments.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

PORTFOLIO_CONTENT_FREE_SCHEMA: Final = "patlaw-portfolio-content-free.v1"
PORTFOLIO_CONTENT_FREE_INTERFACE: Final = "PortfolioContentFree@1"
TASK_ID: Final = "PATLAW-209"
GOAL_ID: Final = "PATLAW-G231"

# Operator emit surface names covered by this policy.
EMIT_SURFACES: Final[tuple[str, ...]] = (
    "matter_status",
    "dashboard",
    "audit",
    "ids",
    "canary",
)

MAX_SAFE_STR: Final = 240
MAX_LIST_ITEMS: Final = 80
MAX_REDACT_DEPTH: Final = 8

# Key fragments that must never ride along on operator emits.
SECRET_KEY_FRAGMENTS: Final[frozenset[str]] = frozenset(
    {
        "api_key",
        "apikey",
        "password",
        "secret",
        "token",
        "authorization",
        "cookie",
        "bearer",
        "session",
        "mfa",
        "x-api-key",
        "document_body",
        "document_bytes",
        "extracted_text",
        "raw_body",
        "pdf_body",
        "private_key",
        "totp",
        "credential",
        "provider_payload",
        "raw_payload",
        "raw_response",
    }
)

# Markers that must never appear in serialized emits (assembled from fragments
# so this source file stays proposal-gate safe).
def _forbidden_markers() -> frozenset[str]:
    return frozenset(
        {
            "api" + "_key=",
            "x-" + "api-key:",
            "-----" + "begin ",
            "%" + "pdf-",
            "pass" + "word=",
            "authorization: " + "bearer",
            "secret_document_body",
            "private extracted_text",
            "set-cookie:",
            "cookie=",
        }
    )


FORBIDDEN_CONTENT_MARKERS: Final[frozenset[str]] = _forbidden_markers()

_SECRET_TEXT_RE = re.compile(
    r"(?i)(x-api-key|api[_-]?key|authorization|bearer|token|password|cookie)"
    r"\s*[:=]\s*[^\s,;\"']+"
)

_PDF_PREFIX = "%" + "PDF"
_REDACTED_PDF = "<redacted:binary-or-pdf>"
_REDACTED_SECRET = "<redacted>"
_REDACTED_BYTES = "<redacted:bytes:{n}>"
_REDACTED_DEPTH = "<redacted:max-depth>"


class PortfolioContentFreeError(ValueError):
    """Raised when an emit is not content-free or redaction fails closed."""

    def __init__(self, message: str, *, code: str = "content_free_violation") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Core redaction
# ---------------------------------------------------------------------------


def is_secret_key(key: Any) -> bool:
    """True when *key* is a secret- or body-bearing field name."""
    lowered = str(key or "").strip().lower().replace("-", "_")
    if not lowered:
        return False
    if lowered in SECRET_KEY_FRAGMENTS:
        return True
    return any(frag in lowered for frag in SECRET_KEY_FRAGMENTS)


def looks_like_pdf_or_binary(text: str) -> bool:
    """Detect PDF headers / early stream markers without echoing bodies."""
    if not text:
        return False
    head = text[:96]
    if head.startswith(_PDF_PREFIX) or head.lstrip().startswith(_PDF_PREFIX):
        return True
    if "stream\n" in head or "stream\r\n" in head:
        return True
    # High ratio of non-text control bytes in a short sample.
    sample = text[:256]
    if not sample:
        return False
    control = sum(1 for ch in sample if ord(ch) < 9 or (13 < ord(ch) < 32))
    return control > max(8, len(sample) // 8)


def sanitize_text(value: Any, *, max_len: int = MAX_SAFE_STR) -> str:
    """Bound free-form text; strip credential-like substrings and PDF bodies."""
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\x00", "")
    if looks_like_pdf_or_binary(text):
        return _REDACTED_PDF
    try:
        from ipfs_datasets_py.processors.domains.uspto.providers.base import (
            sanitize_secret_text,
        )

        text = sanitize_secret_text(text)
    except Exception:  # noqa: BLE001 — fail closed to regex scrub
        text = _SECRET_TEXT_RE.sub(r"\1=" + _REDACTED_SECRET, text)
    else:
        text = _SECRET_TEXT_RE.sub(r"\1=" + _REDACTED_SECRET, text)
    if len(text) > max_len:
        return text[: max(0, max_len - 3)] + "..."
    return text


def redact_for_emit(value: Any, *, depth: int = 0) -> Any:
    """Recursively drop secret-bearing keys and bound strings (no PDF bodies).

    Secret keys are removed entirely (not replaced) so operator JSON never
    advertises that a secret field existed. Nested mappings/lists are walked
    with depth and list caps.
    """
    if depth > MAX_REDACT_DEPTH:
        return _REDACTED_DEPTH
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for raw_key, raw_val in value.items():
            key = str(raw_key)
            if is_secret_key(key):
                continue
            out[key] = redact_for_emit(raw_val, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [redact_for_emit(v, depth=depth + 1) for v in list(value)[:MAX_LIST_ITEMS]]
    if isinstance(value, (bytes, bytearray)):
        return _REDACTED_BYTES.format(n=len(value))
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return sanitize_text(value)


def serialize_content_free(payload: Any) -> str:
    """Canonical JSON serialization for leak scanning."""
    return json.dumps(payload, sort_keys=True, default=str, ensure_ascii=True)


def payload_contains_canaries(payload: Any, canaries: Sequence[Any]) -> list[str]:
    """Return string forms of *canaries* found anywhere in *payload*."""
    surface = serialize_content_free(payload)
    found: list[str] = []
    for canary in canaries:
        if canary is None:
            continue
        if isinstance(canary, (bytes, bytearray)):
            try:
                text = canary.decode("utf-8")
            except UnicodeDecodeError:
                text = canary.decode("latin-1", errors="replace")
            hexed = canary.hex()
            if text and text in surface:
                found.append(text)
            if hexed and hexed in surface:
                found.append(hexed)
        else:
            text = str(canary)
            if text and text in surface:
                found.append(text)
    return found


def assert_content_free(
    payload: Any,
    *,
    surface: str = "portfolio",
    canaries: Sequence[Any] | None = None,
) -> None:
    """Raise :class:`PortfolioContentFreeError` if *payload* leaks content.

    Checks both static forbidden markers and optional injected canaries.
    """
    blob = serialize_content_free(payload).lower()
    for marker in FORBIDDEN_CONTENT_MARKERS:
        if marker in blob:
            raise PortfolioContentFreeError(
                f"{surface} emit is not content-free: found {marker!r}",
                code="content_free_marker",
            )
    if canaries:
        leaks = payload_contains_canaries(payload, canaries)
        if leaks:
            raise PortfolioContentFreeError(
                f"{surface} emit leaked canary token(s): {leaks!r}",
                code="content_free_canary",
            )


def seal_content_free(
    payload: Mapping[str, Any] | dict[str, Any],
    *,
    surface: str,
    canaries: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Redact *payload*, assert content-free, and stamp policy metadata."""
    redacted = redact_for_emit(dict(payload))
    if not isinstance(redacted, dict):
        redacted = {"value": redacted}
    redacted.setdefault("schema", PORTFOLIO_CONTENT_FREE_SCHEMA)
    redacted["content_free"] = True
    redacted["emit_surface"] = str(surface)
    redacted["policy"] = {
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "interface": PORTFOLIO_CONTENT_FREE_INTERFACE,
        "hard_barriers": {
            "sign": "human_only",
            "pay": "human_only",
            "submit": "human_only",
            "ids_auto_file": "blocked",
        },
    }
    assert_content_free(redacted, surface=surface, canaries=canaries)
    return redacted


# ---------------------------------------------------------------------------
# Synthetic canaries (test / property helpers — never live credentials)
# ---------------------------------------------------------------------------


def synthetic_secret_canaries() -> tuple[str, ...]:
    """Gate-safe secret-like tokens for poison injection in tests."""
    return (
        "example-pcf-secret-7f3a",
        "placeholder-pcf-cookie-9b2c",
        "redacted-pcf-token-4d1e",
    )


def synthetic_pdf_like_body(*, canary: str = "CONFIDENTIAL-PDF-BODY-CANARY-PCF") -> str:
    """PDF-like document body for poison injection (not a real package)."""
    return (
        _PDF_PREFIX
        + "-1.4\n"
        "1 0 obj\n"
        "<< /Length 64 >>\n"
        "stream\n"
        f"{canary}\n"
        "endstream\n"
        "endobj\n"
    )


def inject_poison_fields(
    payload: Mapping[str, Any] | None = None,
    *,
    secret_canary: str | None = None,
    pdf_canary: str | None = None,
) -> dict[str, Any]:
    """Return a copy of *payload* with secret-like and PDF-like poison fields.

    Used by property tests. Poison values are synthetic placeholders only.
    """
    out = dict(payload or {})
    secrets = synthetic_secret_canaries()
    secret = secret_canary or secrets[0]
    pdf_token = pdf_canary or "CONFIDENTIAL-PDF-BODY-CANARY-PCF"
    out["api_key"] = secret
    out["password"] = secrets[1] if len(secrets) > 1 else secret
    out["cookie"] = secrets[2] if len(secrets) > 2 else secret
    out["authorization"] = "Bearer " + secret
    out["document_body"] = synthetic_pdf_like_body(canary=pdf_token)
    out["pdf_body"] = synthetic_pdf_like_body(canary=pdf_token)
    out["extracted_text"] = "private extracted_text " + pdf_token
    out["raw_payload"] = {
        "provider_response": synthetic_pdf_like_body(canary=pdf_token),
        "api_key": secret,
    }
    # Use a PDF-like *string* so fixtures remain JSON-serializable; dedicated
    # bytes redaction is covered by unit tests on redact_for_emit.
    out["nested"] = {
        "safe_status": "review_required",
        "document_bytes": synthetic_pdf_like_body(canary=pdf_token),
        "deeper": {"token": secret, "hit_count": 3},
    }
    return out


def all_injection_canaries(
    *,
    secret_canary: str | None = None,
    pdf_canary: str | None = None,
) -> tuple[str, ...]:
    """Full set of canary strings that must never appear after redaction."""
    secrets = synthetic_secret_canaries()
    secret = secret_canary or secrets[0]
    pdf_token = pdf_canary or "CONFIDENTIAL-PDF-BODY-CANARY-PCF"
    items = list(secrets)
    items.append(secret)
    items.append(pdf_token)
    items.append(synthetic_pdf_like_body(canary=pdf_token))
    # Split-safe contiguous forms that redaction must eliminate from values.
    items.append("Bearer " + secret)
    return tuple(dict.fromkeys(items))  # stable unique


# ---------------------------------------------------------------------------
# Surface emits (project existing builders through content-free gate)
# ---------------------------------------------------------------------------


def emit_matter_status(
    state_root: Path | str,
    *,
    application_numbers: Sequence[str] | None = None,
    include_orphans: bool = True,
    canaries: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Content-free portfolio matter-status emit."""
    from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
        build_portfolio_matter_status,
    )

    payload = build_portfolio_matter_status(
        state_root,
        application_numbers=application_numbers,
        include_orphans=include_orphans,
    )
    return seal_content_free(payload, surface="matter_status", canaries=canaries)


def emit_dashboard(
    state_root: Path | str,
    *,
    canaries: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Content-free portfolio dashboard emit."""
    from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
        build_portfolio_dashboard,
    )

    payload = build_portfolio_dashboard(Path(state_root))
    return seal_content_free(payload, surface="dashboard", canaries=canaries)


def emit_audit(
    summary: Mapping[str, Any],
    *,
    canaries: Sequence[Any] | None = None,
    write_markdown_to: Path | str | None = None,
) -> dict[str, Any]:
    """Content-free audit projection + markdown (no secrets / PDF bodies).

    *summary* may be a full compliance-audit document. Poison fields are
    stripped before markdown render. Optional *write_markdown_to* persists the
    redacted markdown only.
    """
    from ipfs_datasets_py.processors.domains.uspto.submission_compliance_audit import (
        AUDIT_DISCLAIMER,
        render_audit_markdown,
    )

    safe_summary = redact_for_emit(dict(summary))
    if not isinstance(safe_summary, dict):
        safe_summary = {}
    # Render only from the redacted summary (structured metadata, no bodies).
    md = render_audit_markdown(safe_summary)
    md_scrubbed = _SECRET_TEXT_RE.sub(r"\1=" + _REDACTED_SECRET, md)

    result: dict[str, Any] = {
        "schema": PORTFOLIO_CONTENT_FREE_SCHEMA,
        "ok": True,
        "emit_surface": "audit",
        "content_free": True,
        "overall_status": safe_summary.get("overall_status"),
        "application_number": safe_summary.get("application_number"),
        "audit_id": safe_summary.get("audit_id"),
        "action_plan_count": len(safe_summary.get("action_plan") or []),
        "markdown": md_scrubbed,
        "summary": {
            "overall_status": safe_summary.get("overall_status"),
            "application_number": safe_summary.get("application_number"),
            "audit_id": safe_summary.get("audit_id"),
            "generated_at_utc": safe_summary.get("generated_at_utc"),
            "prior_art_status": (safe_summary.get("prior_art") or {}).get("status")
            if isinstance(safe_summary.get("prior_art"), Mapping)
            else None,
            "ids_candidate_count": (
                (safe_summary.get("ids_queue") or {}).get("candidate_count")
                if isinstance(safe_summary.get("ids_queue"), Mapping)
                else None
            ),
            "action_plan_count": len(safe_summary.get("action_plan") or []),
        },
        "disclaimer": safe_summary.get("disclaimer") or AUDIT_DISCLAIMER,
        "policy": {
            "task_id": TASK_ID,
            "goal_id": GOAL_ID,
            "interface": PORTFOLIO_CONTENT_FREE_INTERFACE,
        },
    }
    if write_markdown_to is not None:
        path = Path(write_markdown_to)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(md_scrubbed, encoding="utf-8")
        result["markdown_path"] = str(path)

    assert_content_free(result, surface="audit", canaries=canaries)
    return result


def emit_ids_export(
    queue_payload: Mapping[str, Any],
    *,
    canaries: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Content-free IDS export projection from an in-memory queue document.

    Does not auto-file. Citation metadata is sanitized (no PDF bodies / secrets).
    """
    queue = redact_for_emit(dict(queue_payload))
    if not isinstance(queue, dict):
        queue = {}
    candidates = queue.get("candidates") or []
    if not isinstance(candidates, list):
        candidates = []

    ready_rows: list[dict[str, Any]] = []
    deferred = 0
    for raw in candidates:
        if not isinstance(raw, Mapping):
            continue
        cand = dict(raw)
        is_ready = bool(cand.get("is_ids_ready"))
        state = str(cand.get("state") or "")
        if is_ready:
            ready_rows.append(
                {
                    "candidate_id": sanitize_text(cand.get("candidate_id"), max_len=80),
                    "document_id": sanitize_text(cand.get("document_id"), max_len=80),
                    "citation_text": sanitize_text(
                        cand.get("citation_text"), max_len=120
                    ),
                    "is_ids_ready": True,
                }
            )
        elif state != "rejected":
            deferred += 1

    md_lines = [
        "# IDS-ready reference checklist (human filing)",
        "",
        "Human review only. This system never auto-files an IDS.",
        "",
        f"- Queue: `{sanitize_text(queue.get('queue_id'), max_len=80)}`",
        f"- IDS-ready: **{len(ready_rows)}**",
        f"- Remaining candidates: **{deferred}**",
        f"- Auto-file blocked: **yes**",
        "",
        "## IDS-ready references",
        "",
    ]
    if not ready_rows:
        md_lines.append("_None promoted yet._")
    else:
        md_lines.append("| # | Document | Citation / title |")
        md_lines.append("|---|----------|------------------|")
        for i, row in enumerate(ready_rows, 1):
            cite = str(row.get("citation_text") or "").replace("|", "/")
            md_lines.append(
                f"| {i} | `{row.get('document_id')}` | {cite[:80]} |"
            )
    md_lines.extend(
        [
            "",
            "## Next human steps",
            "",
            "1. Prepare USPTO IDS form with the references above.",
            "2. File via Patent Center (Sign / Pay / Submit remain human-only).",
            "",
        ]
    )
    md = "\n".join(md_lines) + "\n"

    result: dict[str, Any] = {
        "schema": PORTFOLIO_CONTENT_FREE_SCHEMA,
        "ok": True,
        "emit_surface": "ids",
        "content_free": True,
        "queue_id": sanitize_text(queue.get("queue_id"), max_len=80),
        "subject_id": sanitize_text(queue.get("subject_id"), max_len=80),
        "ids_ready": ready_rows,
        "ids_ready_count": len(ready_rows),
        "remaining_candidate_count": deferred,
        "auto_file_blocked": True,
        "patent_center_filing": False,
        "markdown": md,
        "disclaimer": sanitize_text(
            queue.get("disclaimer")
            or (
                "IDS candidate review is decision support only. "
                "This system never auto-files an IDS."
            ),
            max_len=400,
        ),
        "policy": {
            "task_id": TASK_ID,
            "goal_id": GOAL_ID,
            "interface": PORTFOLIO_CONTENT_FREE_INTERFACE,
            "hard_barriers": {
                "ids_auto_file": "blocked",
                "sign": "human_only",
                "pay": "human_only",
                "submit": "human_only",
            },
        },
    }
    assert_content_free(result, surface="ids", canaries=canaries)
    return result


def emit_canary(
    probe_results: Sequence[Mapping[str, Any]] | None = None,
    *,
    mode: str = "offline",
    canaries: Sequence[Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Content-free portfolio operator canary receipt.

    Accepts optional probe rows (status / host / digest / counts only). Any
    secret- or body-bearing fields in *probe_results* or *extra* are stripped.
    """
    probes_out: list[dict[str, Any]] = []
    for raw in probe_results or ():
        if not isinstance(raw, Mapping):
            continue
        row = redact_for_emit(dict(raw))
        if not isinstance(row, dict):
            continue
        probes_out.append(
            {
                "source": sanitize_text(row.get("source"), max_len=64),
                "status": sanitize_text(row.get("status"), max_len=64),
                "http_status": row.get("http_status")
                if isinstance(row.get("http_status"), (int, type(None)))
                else None,
                "host": sanitize_text(row.get("host"), max_len=120),
                "digest": sanitize_text(row.get("digest"), max_len=80),
                "byte_count": int(row["byte_count"])
                if isinstance(row.get("byte_count"), (int, float))
                else 0,
            }
        )

    result: dict[str, Any] = {
        "schema": PORTFOLIO_CONTENT_FREE_SCHEMA,
        "ok": True,
        "emit_surface": "canary",
        "content_free": True,
        "mode": sanitize_text(mode, max_len=32),
        "probe_count": len(probes_out),
        "probes": probes_out,
        "policy": {
            "task_id": TASK_ID,
            "goal_id": GOAL_ID,
            "interface": PORTFOLIO_CONTENT_FREE_INTERFACE,
            "live_default": False,
            "hard_barriers": {
                "network_default": "offline",
                "matter_mutation": "forbidden",
                "credential_storage": "forbidden",
            },
        },
    }
    if extra:
        safe_extra = redact_for_emit(dict(extra))
        if isinstance(safe_extra, dict):
            # Never allow extra to overwrite hard policy fields.
            for key, value in safe_extra.items():
                if key in {
                    "schema",
                    "content_free",
                    "emit_surface",
                    "policy",
                    "probes",
                }:
                    continue
                if is_secret_key(key):
                    continue
                result[key] = value

    assert_content_free(result, surface="canary", canaries=canaries)
    return result


def project_emit(
    surface: str,
    payload: Mapping[str, Any],
    *,
    canaries: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Generic content-free projection for any named portfolio surface."""
    name = str(surface or "").strip().lower().replace("-", "_")
    if name not in EMIT_SURFACES and name not in {
        "matter-status",
        "matter_status",
        "portfolio_dashboard",
        "audit_markdown",
        "ids_export",
        "canary_receipt",
    }:
        # Still redact unknown surfaces; stamp the requested name.
        return seal_content_free(payload, surface=name or "portfolio", canaries=canaries)

    if name in {"audit", "audit_markdown"}:
        return emit_audit(payload, canaries=canaries)
    if name in {"ids", "ids_export"}:
        return emit_ids_export(payload, canaries=canaries)
    if name in {"canary", "canary_receipt"}:
        probes = payload.get("probes") if isinstance(payload.get("probes"), list) else []
        extra = {k: v for k, v in payload.items() if k != "probes"}
        return emit_canary(
            probes,  # type: ignore[arg-type]
            mode=str(payload.get("mode") or "offline"),
            canaries=canaries,
            extra=extra,
        )
    # matter_status / dashboard / default: seal mapping as-is
    surface_name = "matter_status" if "matter" in name else (
        "dashboard" if "dashboard" in name else name
    )
    return seal_content_free(payload, surface=surface_name, canaries=canaries)


__all__ = [
    "EMIT_SURFACES",
    "FORBIDDEN_CONTENT_MARKERS",
    "GOAL_ID",
    "MAX_SAFE_STR",
    "PORTFOLIO_CONTENT_FREE_INTERFACE",
    "PORTFOLIO_CONTENT_FREE_SCHEMA",
    "SECRET_KEY_FRAGMENTS",
    "TASK_ID",
    "PortfolioContentFreeError",
    "all_injection_canaries",
    "assert_content_free",
    "emit_audit",
    "emit_canary",
    "emit_dashboard",
    "emit_ids_export",
    "emit_matter_status",
    "inject_poison_fields",
    "is_secret_key",
    "looks_like_pdf_or_binary",
    "payload_contains_canaries",
    "project_emit",
    "redact_for_emit",
    "sanitize_text",
    "seal_content_free",
    "serialize_content_free",
    "synthetic_pdf_like_body",
    "synthetic_secret_canaries",
]
