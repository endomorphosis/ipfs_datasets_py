#!/usr/bin/env python3
"""Fail-closed verifier for the external DQP DuckDB/Quack release gate (DQK-057).

Invoked by ``ack-release --receipt ...`` through the manual-gate lifecycle:

    python scripts/validation/validate_accelerate_duckdb_quack_release.py \\
        --receipt <path> --accelerate-root <path> --json

Verifies a terminal DQP-039 ``DuckDBControlPlaneReleaseReceipt@1`` joined to a
DQP-038 ``DatabaseCutoverReceipt@1``, binding exact accelerator Git commit/tree,
store generation, schema checksum, Quack compatibility profile, expiry,
signature, and accepted decision. On success emits the strict typed
verification object consumed by the gate CAS:

    ipfs_accelerate_py/agent-supervisor/duckdb-quack-release-verification@1

Markdown board status and process-status JSON cannot satisfy this gate. Missing
canonical receipt query material or machine-readable identity fails closed.
Canonical ``query_identity`` and ``result_identity`` are recomputed from their
bodies (constant-time digest compare via ``hmac.compare_digest``). Authority
objects use closed key sets so free-form status fields cannot smuggle through.
Boolean ``accepted`` flags must be true literals (string ``"true"`` is rejected).
Release and cutover decision CIDs must be distinct; ``issued_at`` must not lie
in the future beyond a one-minute clock skew; nested cutover expiry cannot
outlive the terminal release expiry. A stale, mismatched, expired, unsigned, or
unaccepted cutover receipt is rejected.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Schemas / interfaces
# ---------------------------------------------------------------------------

VERIFICATION_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/duckdb-quack-release-verification@1"
)
RELEASE_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/duckdb-control-plane-release-receipt@1"
)
RELEASE_RECEIPT_INTERFACE: Final[str] = "DuckDBControlPlaneReleaseReceipt@1"
CUTOVER_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/database-cutover-receipt@1"
)
CUTOVER_RECEIPT_INTERFACE: Final[str] = "DatabaseCutoverReceipt@1"
CANONICAL_QUERY_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/canonical-receipt-query@1"
)
PROGRAM_ID: Final[str] = "agent-supervisor-duckdb-quack-control-plane-v1"
RELEASE_TASK_ID: Final[str] = "DQP-039"
CUTOVER_TASK_ID: Final[str] = "DQP-038"
SIGNATURE_ALGORITHM: Final[str] = "content-bound-sha256@1"

_MAX_RECEIPT_BYTES: Final[int] = 2 * 1024 * 1024
_MAX_FIELD_BYTES: Final[int] = 4096
# Allow modest operator/clock skew when rejecting future issued_at stamps.
_ISSUED_AT_FUTURE_SKEW_SECONDS: Final[int] = 60
_GIT_OID: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_SHA256_DIGEST: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTROL_CHARS: Final[frozenset[str]] = frozenset(("\0", "\n", "\r"))

# Fields that are not part of the signed preimage (content-bound digests).
_UNSIGNED_EXCLUDED: Final[frozenset[str]] = frozenset(
    {"signature", "receipt_cid", "cutover_receipt_cid"}
)

_RELEASE_REQUIRED_STRING_FIELDS: Final[tuple[str, ...]] = (
    "program_id",
    "task_id",
    "interface",
    "accelerator_commit",
    "accelerator_tree",
    "store_generation",
    "schema_checksum",
    "quack_profile",
    "decision_cid",
    "decision",
    "expires_at",
    "issued_at",
    "signature_algorithm",
    "signature",
    "receipt_cid",
)

_CUTOVER_REQUIRED_STRING_FIELDS: Final[tuple[str, ...]] = (
    "program_id",
    "task_id",
    "interface",
    "accelerator_commit",
    "accelerator_tree",
    "store_generation",
    "schema_checksum",
    "quack_profile",
    "decision_cid",
    "decision",
    "expires_at",
    "issued_at",
    "signature_algorithm",
    "signature",
    "receipt_cid",
)

_CANONICAL_QUERY_REQUIRED_STRING_FIELDS: Final[tuple[str, ...]] = (
    "program_id",
    "task_id",
    "query_name",
    "query_identity",
    "result_identity",
)

# Closed key sets: unknown keys fail closed so free-form status cannot smuggle in.
_CANONICAL_QUERY_KEYS: Final[frozenset[str]] = frozenset(
    {"schema", *_CANONICAL_QUERY_REQUIRED_STRING_FIELDS}
)
_CUTOVER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "accepted",
        "canonical_query",
        *_CUTOVER_REQUIRED_STRING_FIELDS,
    }
)
_RELEASE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "accepted",
        "canonical_query",
        "cutover",
        "cutover_receipt_cid",
        *_RELEASE_REQUIRED_STRING_FIELDS,
    }
)
_VERIFICATION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "accepted",
        "accelerator_commit",
        "accelerator_tree",
        "release_receipt_cid",
        "cutover_receipt_cid",
        "store_generation",
        "schema_checksum",
        "quack_profile",
        "decision_cid",
        "expires_at",
    }
)

# Shapes that must never satisfy the gate (process status / markdown board).
_PROCESS_STATUS_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "master_alive",
        "master_pid",
        "release_status",
        "lane_status",
        "stale_or_unbound_lanes",
        "active_worker_count",
        "board_path",
    }
)
_MARKDOWN_MARKERS: Final[tuple[str, ...]] = (
    "## DQP-",
    "- Status:",
    "# Agent Supervisor",
    "```markdown",
)


class VerificationError(RuntimeError):
    """Raised when the release receipt fails closed verification."""


# ---------------------------------------------------------------------------
# Strict JSON / identity helpers
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """Return deterministic JSON with sorted keys and no whitespace.

    Rejects non-finite floats (NaN/Infinity) so authority digests stay total.
    """

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise VerificationError(
            "authority payload is not canonical JSON"
        ) from exc


def content_digest(value: Any) -> str:
    """Return ``sha256:<hex>`` of the canonical JSON encoding of *value*."""

    return f"sha256:{hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()}"


def strict_json_object(raw: str | bytes, *, noun: str) -> dict[str, Any]:
    """Decode one bounded authority object without duplicate keys or NaN."""

    if isinstance(raw, bytes):
        if len(raw) > _MAX_RECEIPT_BYTES:
            raise VerificationError(f"{noun} exceeds the {_MAX_RECEIPT_BYTES} byte bound")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise VerificationError(f"{noun} is not UTF-8") from exc
    else:
        if not isinstance(raw, str) or not raw:
            raise VerificationError(f"{noun} must be a non-empty UTF-8 JSON object")
        if len(raw.encode("utf-8")) > _MAX_RECEIPT_BYTES:
            raise VerificationError(f"{noun} exceeds the {_MAX_RECEIPT_BYTES} byte bound")
        text = raw

    stripped = text.lstrip()
    if stripped.startswith("#") or stripped.startswith("##"):
        raise VerificationError(f"{noun} is Markdown and cannot satisfy the gate")
    for marker in _MARKDOWN_MARKERS:
        if marker in text:
            raise VerificationError(f"{noun} contains Markdown board material")

    def object_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise VerificationError(f"{noun} contains duplicate key {key!r}")
            result[key] = item
        return result

    def reject_constant(constant: str) -> Any:
        raise VerificationError(f"{noun} contains non-finite value {constant}")

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise VerificationError(f"{noun} is not strict JSON") from exc
    if not isinstance(decoded, dict):
        raise VerificationError(f"{noun} must be a JSON object")
    return decoded


def _bounded_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise VerificationError(f"{field} must be a string")
    if not value.strip():
        raise VerificationError(f"{field} must be non-empty")
    encoded = value.encode("utf-8")
    if len(encoded) > _MAX_FIELD_BYTES:
        raise VerificationError(f"{field} exceeds the {_MAX_FIELD_BYTES} byte bound")
    if any(character in value for character in _CONTROL_CHARS):
        raise VerificationError(f"{field} contains forbidden control characters")
    return value


def _require_sha256(value: Any, *, field: str) -> str:
    text = _bounded_text(value, field=field)
    if not _SHA256_DIGEST.fullmatch(text):
        raise VerificationError(f"{field} must be sha256:<64 lowercase hex>")
    return text


def _require_git_oid(value: Any, *, field: str) -> str:
    text = _bounded_text(value, field=field).lower()
    if not _GIT_OID.fullmatch(text):
        raise VerificationError(f"{field} must be a complete lowercase Git object id")
    return text


def _parse_aware_datetime(value: Any, *, field: str) -> datetime:
    text = _bounded_text(value, field=field)
    if len(text.encode("utf-8")) > 128:
        raise VerificationError(f"{field} timestamp is unbounded")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerificationError(f"{field} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise VerificationError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _require_accepted_decision(value: Any, *, field: str) -> str:
    text = _bounded_text(value, field=field).lower()
    if text != "accepted":
        raise VerificationError(f"{field} is not an accepted decision")
    return text


def _require_true_accepted_flag(value: Any, *, field: str) -> None:
    """Fail closed unless *value* is the boolean True (string/int truth is rejected)."""

    if value is True:
        return
    if value is False:
        raise VerificationError(f"{field} is unaccepted")
    if isinstance(value, str):
        raise VerificationError(
            f"{field} must be the boolean true literal, not a string"
        )
    if isinstance(value, (int, float)):
        raise VerificationError(
            f"{field} must be the boolean true literal, not a numeric stand-in"
        )
    raise VerificationError(f"{field} must be the boolean true literal")


def _reject_future_issued_at(
    issued_at: datetime, *, now: datetime, field: str
) -> None:
    """Reject authority issued far in the future (beyond modest clock skew)."""

    skew = timedelta(seconds=_ISSUED_AT_FUTURE_SKEW_SECONDS)
    if issued_at > now + skew:
        raise VerificationError(f"{field} is in the future beyond allowed clock skew")


def _require_exact_keys(
    payload: Mapping[str, Any],
    *,
    allowed: frozenset[str],
    noun: str,
) -> None:
    """Fail closed when authority objects carry unknown or incomplete keys."""

    keys = frozenset(payload)
    missing = sorted(allowed - keys)
    extra = sorted(keys - allowed)
    if missing:
        raise VerificationError(
            f"{noun} is missing required machine-readable keys: {','.join(missing)}"
        )
    if extra:
        raise VerificationError(
            f"{noun} contains unsupported keys that cannot satisfy the gate: "
            f"{','.join(extra)}"
        )


def unsigned_preimage(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the signed-body preimage without digest/signature fields."""

    return {
        key: value
        for key, value in payload.items()
        if key not in _UNSIGNED_EXCLUDED
    }


def compute_signature(payload: Mapping[str, Any]) -> str:
    """Compute the content-bound signature for an unsigned body."""

    return content_digest(unsigned_preimage(payload))


def compute_receipt_cid(payload: Mapping[str, Any]) -> str:
    """Compute the content-bound receipt identity including the signature."""

    material = {
        key: value for key, value in payload.items() if key != "receipt_cid"
    }
    return content_digest(material)


def verify_signature(payload: Mapping[str, Any], *, noun: str) -> None:
    """Fail closed when signature algorithm or digest does not match the body."""

    algorithm = _bounded_text(
        payload.get("signature_algorithm"), field=f"{noun}.signature_algorithm"
    )
    if algorithm != SIGNATURE_ALGORITHM:
        raise VerificationError(f"{noun} uses unsupported signature algorithm")
    expected = compute_signature(payload)
    actual = _require_sha256(payload.get("signature"), field=f"{noun}.signature")
    if not hmac.compare_digest(actual, expected):
        raise VerificationError(f"{noun} signature does not match the signed body")
    expected_cid = compute_receipt_cid(payload)
    actual_cid = _require_sha256(payload.get("receipt_cid"), field=f"{noun}.receipt_cid")
    if not hmac.compare_digest(actual_cid, expected_cid):
        raise VerificationError(f"{noun} receipt_cid is not content-bound")


# ---------------------------------------------------------------------------
# Accelerate-root inspection
# ---------------------------------------------------------------------------


def _git(accelerate_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=accelerate_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git failed").strip()
        raise VerificationError(
            f"accelerate-root git inspection failed ({' '.join(args)}): {detail}"
        )
    return result.stdout.strip()


def inspect_accelerate_root(accelerate_root: Path) -> tuple[str, str]:
    """Return (commit, tree) for the accelerator checkout HEAD."""

    if not accelerate_root.is_dir():
        raise VerificationError("accelerate-root is not a directory")
    if accelerate_root.is_symlink():
        raise VerificationError("accelerate-root must not be a symlink")
    git_dir = accelerate_root / ".git"
    if not git_dir.exists():
        raise VerificationError("accelerate-root is not a Git repository")
    commit = _git(accelerate_root, "rev-parse", "HEAD").lower()
    tree = _git(accelerate_root, "rev-parse", "HEAD^{tree}").lower()
    if not _GIT_OID.fullmatch(commit) or not _GIT_OID.fullmatch(tree):
        raise VerificationError("accelerate-root Git identities are malformed")
    return commit, tree


# ---------------------------------------------------------------------------
# Receipt validation
# ---------------------------------------------------------------------------


def _reject_process_status(payload: Mapping[str, Any], *, noun: str) -> None:
    keys = set(payload)
    if keys & _PROCESS_STATUS_MARKERS:
        raise VerificationError(
            f"{noun} looks like process status and cannot satisfy the gate"
        )
    # Explicit external DQP status projection shape.
    if (
        payload.get("program_id") == PROGRAM_ID
        and "release_status" in payload
        and "master_alive" in payload
    ):
        raise VerificationError(
            f"{noun} is external process status and cannot satisfy the gate"
        )


def _validate_canonical_query(
    query: Any,
    *,
    expected_task_id: str,
    noun: str,
    result_material: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and recompute canonical query/result identities (fail closed)."""

    if not isinstance(query, Mapping):
        raise VerificationError(
            f"{noun} is missing a canonical receipt query (fails closed)"
        )
    if query.get("schema") != CANONICAL_QUERY_SCHEMA:
        raise VerificationError(
            f"{noun}.canonical_query schema is not the canonical receipt query type"
        )
    _require_exact_keys(
        query, allowed=_CANONICAL_QUERY_KEYS, noun=f"{noun}.canonical_query"
    )
    for field in _CANONICAL_QUERY_REQUIRED_STRING_FIELDS:
        _bounded_text(query.get(field), field=f"{noun}.canonical_query.{field}")
    if query.get("program_id") != PROGRAM_ID:
        raise VerificationError(f"{noun}.canonical_query program_id is foreign")
    if query.get("task_id") != expected_task_id:
        raise VerificationError(
            f"{noun}.canonical_query task_id does not match {expected_task_id}"
        )
    query_name = _bounded_text(
        query.get("query_name"), field=f"{noun}.canonical_query.query_name"
    )
    claimed_query_identity = _require_sha256(
        query.get("query_identity"), field=f"{noun}.canonical_query.query_identity"
    )
    claimed_result_identity = _require_sha256(
        query.get("result_identity"),
        field=f"{noun}.canonical_query.result_identity",
    )
    # Recompute both identities from their signed bodies so free-form digests
    # cannot satisfy the gate.
    query_body = {
        "schema": CANONICAL_QUERY_SCHEMA,
        "program_id": PROGRAM_ID,
        "task_id": expected_task_id,
        "query_name": query_name,
    }
    expected_query_identity = content_digest(query_body)
    if not hmac.compare_digest(claimed_query_identity, expected_query_identity):
        raise VerificationError(
            f"{noun}.canonical_query query_identity does not recompute from the query body"
        )
    if result_material is not None:
        expected_result_identity = content_digest(result_material)
        if not hmac.compare_digest(
            claimed_result_identity, expected_result_identity
        ):
            raise VerificationError(
                f"{noun}.canonical_query result_identity does not recompute "
                "from the receipt material"
            )
    return dict(query)


def _validate_cutover_receipt(
    cutover: Any,
    *,
    release: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    if not isinstance(cutover, Mapping):
        raise VerificationError("joined DatabaseCutoverReceipt@1 is missing")
    _reject_process_status(cutover, noun="cutover receipt")
    if cutover.get("schema") != CUTOVER_RECEIPT_SCHEMA:
        raise VerificationError(
            "cutover receipt schema is not DatabaseCutoverReceipt@1"
        )
    if cutover.get("interface") != CUTOVER_RECEIPT_INTERFACE:
        raise VerificationError(
            "cutover receipt interface is not DatabaseCutoverReceipt@1"
        )
    _require_exact_keys(cutover, allowed=_CUTOVER_KEYS, noun="cutover receipt")
    for field in _CUTOVER_REQUIRED_STRING_FIELDS:
        _bounded_text(cutover.get(field), field=f"cutover.{field}")
    if cutover.get("program_id") != PROGRAM_ID:
        raise VerificationError("cutover receipt program_id is foreign")
    if cutover.get("task_id") != CUTOVER_TASK_ID:
        raise VerificationError("cutover receipt task_id is not DQP-038")
    _require_true_accepted_flag(cutover.get("accepted"), field="cutover.accepted")
    _require_accepted_decision(cutover.get("decision"), field="cutover.decision")

    commit = _require_git_oid(
        cutover.get("accelerator_commit"), field="cutover.accelerator_commit"
    )
    tree = _require_git_oid(
        cutover.get("accelerator_tree"), field="cutover.accelerator_tree"
    )
    store_generation = _bounded_text(
        cutover.get("store_generation"), field="cutover.store_generation"
    )
    schema_checksum = _require_sha256(
        cutover.get("schema_checksum"), field="cutover.schema_checksum"
    )
    quack_profile = _bounded_text(
        cutover.get("quack_profile"), field="cutover.quack_profile"
    )
    _bounded_text(cutover.get("decision_cid"), field="cutover.decision_cid")
    issued_at = _parse_aware_datetime(
        cutover.get("issued_at"), field="cutover.issued_at"
    )
    expires_at = _parse_aware_datetime(
        cutover.get("expires_at"), field="cutover.expires_at"
    )
    if issued_at > expires_at:
        raise VerificationError("cutover receipt issued_at is after expires_at")
    if expires_at <= now:
        raise VerificationError("cutover receipt is expired")
    _reject_future_issued_at(issued_at, now=now, field="cutover.issued_at")

    release_expires_at = _parse_aware_datetime(
        release.get("expires_at"), field="release.expires_at"
    )
    if expires_at > release_expires_at:
        raise VerificationError(
            "cutover receipt expiry outlives the terminal release expiry"
        )

    # Join invariants: cutover must match the terminal release binding.
    for field, expected in (
        ("accelerator_commit", release["accelerator_commit"]),
        ("accelerator_tree", release["accelerator_tree"]),
        ("store_generation", release["store_generation"]),
        ("schema_checksum", release["schema_checksum"]),
        ("quack_profile", release["quack_profile"]),
    ):
        actual = cutover.get(field)
        if not isinstance(actual, str) or not isinstance(expected, str):
            raise VerificationError(
                f"cutover receipt {field} is mismatched against the release receipt"
            )
        if not hmac.compare_digest(actual, expected):
            raise VerificationError(
                f"cutover receipt {field} is mismatched against the release receipt"
            )

    release_decision = _bounded_text(
        release.get("decision_cid"), field="release.decision_cid"
    )
    cutover_decision = _bounded_text(
        cutover.get("decision_cid"), field="cutover.decision_cid"
    )
    if release_decision == cutover_decision:
        raise VerificationError(
            "release and cutover decision_cid values must be distinct"
        )

    if not cutover.get("signature"):
        raise VerificationError("cutover receipt is unsigned")
    verify_signature(cutover, noun="cutover receipt")
    cutover_material = {
        "accelerator_commit": commit,
        "accelerator_tree": tree,
        "store_generation": store_generation,
        "schema_checksum": schema_checksum,
        "quack_profile": quack_profile,
        "decision_cid": _bounded_text(
            cutover.get("decision_cid"), field="cutover.decision_cid"
        ),
    }
    _validate_canonical_query(
        cutover.get("canonical_query"),
        expected_task_id=CUTOVER_TASK_ID,
        noun="cutover receipt",
        result_material=cutover_material,
    )
    return dict(cutover)


def _pin_is_ancestor_of_checkout(
    accelerate_root: Path,
    *,
    pin_commit: str,
    checkout_commit: str,
) -> bool:
    """True when the release pin remains first-parent-reachable from checkout."""

    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", pin_commit, checkout_commit],
        cwd=accelerate_root,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _validate_release_receipt(
    release: Mapping[str, Any],
    *,
    accelerate_commit: str,
    accelerate_tree: str,
    now: datetime,
    accelerate_root: Path | None = None,
) -> dict[str, Any]:
    _reject_process_status(release, noun="release receipt")
    if release.get("schema") != RELEASE_RECEIPT_SCHEMA:
        raise VerificationError(
            "release receipt schema is not DuckDBControlPlaneReleaseReceipt@1"
        )
    if release.get("interface") != RELEASE_RECEIPT_INTERFACE:
        raise VerificationError(
            "release receipt interface is not DuckDBControlPlaneReleaseReceipt@1"
        )
    _require_exact_keys(release, allowed=_RELEASE_KEYS, noun="release receipt")
    for field in _RELEASE_REQUIRED_STRING_FIELDS:
        _bounded_text(release.get(field), field=f"release.{field}")
    if release.get("program_id") != PROGRAM_ID:
        raise VerificationError("release receipt program_id is foreign")
    if release.get("task_id") != RELEASE_TASK_ID:
        raise VerificationError("release receipt task_id is not DQP-039")
    _require_true_accepted_flag(release.get("accepted"), field="release.accepted")
    _require_accepted_decision(release.get("decision"), field="release.decision")

    commit = _require_git_oid(
        release.get("accelerator_commit"), field="release.accelerator_commit"
    )
    tree = _require_git_oid(
        release.get("accelerator_tree"), field="release.accelerator_tree"
    )
    # Exact HEAD match is preferred.  After DQK-056 the accelerate checkout may
    # advance with control-plane fixes while the durable pin remains an ancestor
    # of HEAD; restart authentication accepts that tip advance when the pin
    # tree still matches the receipt.
    if hmac.compare_digest(commit, accelerate_commit):
        if not hmac.compare_digest(tree, accelerate_tree):
            raise VerificationError(
                "release receipt accelerator_tree is stale for --accelerate-root"
            )
    elif (
        accelerate_root is not None
        and _pin_is_ancestor_of_checkout(
            accelerate_root,
            pin_commit=commit,
            checkout_commit=accelerate_commit,
        )
    ):
        pin_tree = _git(accelerate_root, "rev-parse", f"{commit}^{{tree}}").lower()
        if not hmac.compare_digest(tree, pin_tree):
            raise VerificationError(
                "release receipt accelerator_tree does not match the pin commit"
            )
    else:
        raise VerificationError(
            "release receipt accelerator_commit is stale for --accelerate-root"
        )

    _bounded_text(release.get("store_generation"), field="release.store_generation")
    _require_sha256(release.get("schema_checksum"), field="release.schema_checksum")
    _bounded_text(release.get("quack_profile"), field="release.quack_profile")
    _bounded_text(release.get("decision_cid"), field="release.decision_cid")
    issued_at = _parse_aware_datetime(release.get("issued_at"), field="release.issued_at")
    expires_at = _parse_aware_datetime(
        release.get("expires_at"), field="release.expires_at"
    )
    if issued_at > expires_at:
        raise VerificationError("release receipt issued_at is after expires_at")
    if expires_at <= now:
        raise VerificationError("release receipt is expired")
    _reject_future_issued_at(issued_at, now=now, field="release.issued_at")

    if not release.get("signature"):
        raise VerificationError("release receipt is unsigned")
    verify_signature(release, noun="release receipt")

    cutover = _validate_cutover_receipt(
        release.get("cutover"), release=release, now=now
    )
    cutover_cid = _require_sha256(
        release.get("cutover_receipt_cid"), field="release.cutover_receipt_cid"
    )
    joined_cutover_cid = _require_sha256(
        cutover.get("receipt_cid"), field="cutover.receipt_cid"
    )
    if not hmac.compare_digest(cutover_cid, joined_cutover_cid):
        raise VerificationError(
            "release cutover_receipt_cid does not match the joined cutover receipt"
        )
    release_material = {
        "accelerator_commit": commit,
        "accelerator_tree": tree,
        "store_generation": _bounded_text(
            release.get("store_generation"), field="release.store_generation"
        ),
        "schema_checksum": _require_sha256(
            release.get("schema_checksum"), field="release.schema_checksum"
        ),
        "quack_profile": _bounded_text(
            release.get("quack_profile"), field="release.quack_profile"
        ),
        "decision_cid": _bounded_text(
            release.get("decision_cid"), field="release.decision_cid"
        ),
        "cutover_receipt_cid": cutover_cid,
    }
    _validate_canonical_query(
        release.get("canonical_query"),
        expected_task_id=RELEASE_TASK_ID,
        noun="release receipt",
        result_material=release_material,
    )
    return dict(release)


# Fields the gate CAS binds as nonempty strings on a successful verification.
_VERIFICATION_REQUIRED_STRING_FIELDS: Final[tuple[str, ...]] = (
    "accelerator_commit",
    "accelerator_tree",
    "release_receipt_cid",
    "cutover_receipt_cid",
    "store_generation",
    "schema_checksum",
    "quack_profile",
    "decision_cid",
    "expires_at",
)


def build_verification(
    release: Mapping[str, Any],
    *,
    cutover: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the strict typed verification object consumed by the gate CAS."""

    verification: dict[str, Any] = {
        "schema": VERIFICATION_SCHEMA,
        "accepted": True,
        "accelerator_commit": str(release["accelerator_commit"]).lower(),
        "accelerator_tree": str(release["accelerator_tree"]).lower(),
        "release_receipt_cid": str(release["receipt_cid"]),
        "cutover_receipt_cid": str(cutover["receipt_cid"]),
        "store_generation": str(release["store_generation"]),
        "schema_checksum": str(release["schema_checksum"]),
        "quack_profile": str(release["quack_profile"]),
        "decision_cid": str(release["decision_cid"]),
        "expires_at": str(release["expires_at"]),
    }
    _require_exact_keys(
        verification, allowed=_VERIFICATION_KEYS, noun="verification object"
    )
    for field in _VERIFICATION_REQUIRED_STRING_FIELDS:
        value = verification.get(field)
        if not isinstance(value, str) or not value.strip():
            raise VerificationError(
                f"verification object is missing required field {field}"
            )
        if any(character in value for character in _CONTROL_CHARS):
            raise VerificationError(
                f"verification object field {field} contains forbidden control characters"
            )
        if len(value.encode("utf-8")) > _MAX_FIELD_BYTES:
            raise VerificationError(
                f"verification object field {field} exceeds the "
                f"{_MAX_FIELD_BYTES} byte bound"
            )
    if verification.get("accepted") is not True:
        raise VerificationError("verification object must report accepted=true")
    if not _GIT_OID.fullmatch(str(verification["accelerator_commit"])):
        raise VerificationError("verification accelerator_commit is malformed")
    if not _GIT_OID.fullmatch(str(verification["accelerator_tree"])):
        raise VerificationError("verification accelerator_tree is malformed")
    _require_sha256(
        verification["schema_checksum"], field="verification.schema_checksum"
    )
    _require_sha256(
        verification["release_receipt_cid"], field="verification.release_receipt_cid"
    )
    _require_sha256(
        verification["cutover_receipt_cid"], field="verification.cutover_receipt_cid"
    )
    # Bind the same timezone-aware expiry the gate CAS will re-check at use.
    _parse_aware_datetime(
        verification["expires_at"], field="verification.expires_at"
    )
    return verification


def verify_release_receipt(
    receipt_payload: Mapping[str, Any] | str | bytes,
    *,
    accelerate_root: Path | str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify a joined DQP release/cutover receipt and return the gate object."""

    if isinstance(receipt_payload, (str, bytes)):
        release = strict_json_object(receipt_payload, noun="release receipt")
    elif isinstance(receipt_payload, Mapping):
        release = dict(receipt_payload)
    else:
        raise VerificationError("release receipt payload type is unsupported")

    root = Path(accelerate_root)
    accelerate_commit, accelerate_tree = inspect_accelerate_root(root)
    clock = now if now is not None else datetime.now(timezone.utc)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise VerificationError("verification clock must be timezone-aware")
    clock = clock.astimezone(timezone.utc)

    validated = _validate_release_receipt(
        release,
        accelerate_commit=accelerate_commit,
        accelerate_tree=accelerate_tree,
        now=clock,
        accelerate_root=root,
    )
    cutover = validated["cutover"]
    if not isinstance(cutover, Mapping):
        raise VerificationError("validated release is missing joined cutover")
    return build_verification(validated, cutover=cutover)


def load_and_verify(
    receipt_path: Path | str,
    *,
    accelerate_root: Path | str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Load a receipt file and verify it against the accelerator checkout."""

    path = Path(receipt_path)
    # The DQK-056 manual-gate lifecycle seals the receipt into a memfd and
    # publishes it only as /proc/self/fd/<n>.  That path is always a procfs
    # symlink; allow it while still rejecting operator-controlled symlinks.
    sealed_memfd = re.fullmatch(r"/proc/self/fd/\d+", str(path)) is not None
    if path.is_symlink() and not sealed_memfd:
        raise VerificationError("receipt path must not be a symlink")
    if not sealed_memfd and not path.is_file():
        raise VerificationError("receipt path is not a regular file")
    try:
        if sealed_memfd:
            with open(path, "rb") as handle:
                raw = handle.read(_MAX_RECEIPT_BYTES + 1)
        else:
            raw = path.read_bytes()
    except OSError as exc:
        raise VerificationError(f"receipt path is unreadable: {exc}") from exc
    if len(raw) > _MAX_RECEIPT_BYTES:
        raise VerificationError(
            f"receipt exceeds the {_MAX_RECEIPT_BYTES} byte bound"
        )
    return verify_release_receipt(
        raw, accelerate_root=accelerate_root, now=now
    )


# ---------------------------------------------------------------------------
# Fixture builders (used by tests and --check self-test)
# ---------------------------------------------------------------------------


def build_canonical_query(
    *,
    task_id: str,
    query_name: str,
    result_material: Mapping[str, Any],
) -> dict[str, Any]:
    """Construct a content-bound canonical receipt query object."""

    query_body = {
        "schema": CANONICAL_QUERY_SCHEMA,
        "program_id": PROGRAM_ID,
        "task_id": task_id,
        "query_name": query_name,
    }
    query_identity = content_digest(query_body)
    result_identity = content_digest(result_material)
    return {
        **query_body,
        "query_identity": query_identity,
        "result_identity": result_identity,
    }


def seal_receipt(body: Mapping[str, Any]) -> dict[str, Any]:
    """Attach content-bound signature and receipt_cid to a receipt body."""

    sealed = dict(body)
    sealed["signature_algorithm"] = SIGNATURE_ALGORITHM
    sealed["signature"] = compute_signature(sealed)
    sealed["receipt_cid"] = compute_receipt_cid(sealed)
    return sealed


def build_cutover_receipt(
    *,
    accelerator_commit: str,
    accelerator_tree: str,
    store_generation: str,
    schema_checksum: str,
    quack_profile: str,
    decision_cid: str,
    issued_at: datetime,
    expires_at: datetime,
    accepted: bool = True,
    decision: str = "accepted",
) -> dict[str, Any]:
    """Build a sealed DatabaseCutoverReceipt@1 for tests and self-check."""

    material = {
        "accelerator_commit": accelerator_commit.lower(),
        "accelerator_tree": accelerator_tree.lower(),
        "store_generation": store_generation,
        "schema_checksum": schema_checksum,
        "quack_profile": quack_profile,
        "decision_cid": decision_cid,
    }
    body: dict[str, Any] = {
        "schema": CUTOVER_RECEIPT_SCHEMA,
        "interface": CUTOVER_RECEIPT_INTERFACE,
        "program_id": PROGRAM_ID,
        "task_id": CUTOVER_TASK_ID,
        "accepted": accepted,
        "decision": decision,
        "accelerator_commit": accelerator_commit.lower(),
        "accelerator_tree": accelerator_tree.lower(),
        "store_generation": store_generation,
        "schema_checksum": schema_checksum,
        "quack_profile": quack_profile,
        "decision_cid": decision_cid,
        "issued_at": issued_at.astimezone(timezone.utc).isoformat(),
        "expires_at": expires_at.astimezone(timezone.utc).isoformat(),
        "canonical_query": build_canonical_query(
            task_id=CUTOVER_TASK_ID,
            query_name="select_database_cutover_receipt",
            result_material=material,
        ),
    }
    return seal_receipt(body)


def build_release_receipt(
    *,
    accelerator_commit: str,
    accelerator_tree: str,
    store_generation: str,
    schema_checksum: str,
    quack_profile: str,
    decision_cid: str,
    issued_at: datetime,
    expires_at: datetime,
    cutover: Mapping[str, Any] | None = None,
    accepted: bool = True,
    decision: str = "accepted",
) -> dict[str, Any]:
    """Build a sealed DuckDBControlPlaneReleaseReceipt@1 joined to cutover."""

    if cutover is None:
        cutover = build_cutover_receipt(
            accelerator_commit=accelerator_commit,
            accelerator_tree=accelerator_tree,
            store_generation=store_generation,
            schema_checksum=schema_checksum,
            quack_profile=quack_profile,
            decision_cid=f"{decision_cid}:cutover",
            issued_at=issued_at,
            expires_at=expires_at,
            accepted=accepted,
            decision=decision,
        )
    material = {
        "accelerator_commit": accelerator_commit.lower(),
        "accelerator_tree": accelerator_tree.lower(),
        "store_generation": store_generation,
        "schema_checksum": schema_checksum,
        "quack_profile": quack_profile,
        "decision_cid": decision_cid,
        "cutover_receipt_cid": cutover["receipt_cid"],
    }
    body: dict[str, Any] = {
        "schema": RELEASE_RECEIPT_SCHEMA,
        "interface": RELEASE_RECEIPT_INTERFACE,
        "program_id": PROGRAM_ID,
        "task_id": RELEASE_TASK_ID,
        "accepted": accepted,
        "decision": decision,
        "accelerator_commit": accelerator_commit.lower(),
        "accelerator_tree": accelerator_tree.lower(),
        "store_generation": store_generation,
        "schema_checksum": schema_checksum,
        "quack_profile": quack_profile,
        "decision_cid": decision_cid,
        "cutover_receipt_cid": cutover["receipt_cid"],
        "cutover": dict(cutover),
        "issued_at": issued_at.astimezone(timezone.utc).isoformat(),
        "expires_at": expires_at.astimezone(timezone.utc).isoformat(),
        "canonical_query": build_canonical_query(
            task_id=RELEASE_TASK_ID,
            query_name="select_terminal_joined_release_receipt",
            result_material=material,
        ),
    }
    return seal_receipt(body)


def self_check() -> dict[str, Any]:
    """Return a machine-readable integrity report for ``--check``."""

    required = {
        "verification_schema": VERIFICATION_SCHEMA,
        "release_receipt_schema": RELEASE_RECEIPT_SCHEMA,
        "release_receipt_interface": RELEASE_RECEIPT_INTERFACE,
        "cutover_receipt_schema": CUTOVER_RECEIPT_SCHEMA,
        "cutover_receipt_interface": CUTOVER_RECEIPT_INTERFACE,
        "canonical_query_schema": CANONICAL_QUERY_SCHEMA,
        "program_id": PROGRAM_ID,
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "release_task_id": RELEASE_TASK_ID,
        "cutover_task_id": CUTOVER_TASK_ID,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise VerificationError(f"self-check missing constants: {','.join(missing)}")
    # Round-trip a synthetic sealed pair through signature verification only.
    issued = datetime(2030, 1, 1, tzinfo=timezone.utc)
    expires = datetime(2030, 1, 2, tzinfo=timezone.utc)
    commit = "a" * 40
    tree = "b" * 40
    receipt = build_release_receipt(
        accelerator_commit=commit,
        accelerator_tree=tree,
        store_generation="generation:self-check",
        schema_checksum="sha256:" + "c" * 64,
        quack_profile="quack-profile:self-check",
        decision_cid="decision:self-check",
        issued_at=issued,
        expires_at=expires,
    )
    verify_signature(receipt, noun="self-check release")
    verify_signature(receipt["cutover"], noun="self-check cutover")
    release_material = {
        "accelerator_commit": commit,
        "accelerator_tree": tree,
        "store_generation": "generation:self-check",
        "schema_checksum": "sha256:" + "c" * 64,
        "quack_profile": "quack-profile:self-check",
        "decision_cid": "decision:self-check",
        "cutover_receipt_cid": receipt["cutover"]["receipt_cid"],
    }
    _validate_canonical_query(
        receipt.get("canonical_query"),
        expected_task_id=RELEASE_TASK_ID,
        noun="self-check release",
        result_material=release_material,
    )
    cutover_material = {
        "accelerator_commit": commit,
        "accelerator_tree": tree,
        "store_generation": "generation:self-check",
        "schema_checksum": "sha256:" + "c" * 64,
        "quack_profile": "quack-profile:self-check",
        "decision_cid": f"decision:self-check:cutover",
    }
    _validate_canonical_query(
        receipt["cutover"].get("canonical_query"),
        expected_task_id=CUTOVER_TASK_ID,
        noun="self-check cutover",
        result_material=cutover_material,
    )
    verification = build_verification(receipt, cutover=receipt["cutover"])
    if verification["schema"] != VERIFICATION_SCHEMA or verification["accepted"] is not True:
        raise VerificationError("self-check verification object is malformed")
    missing_fields = [
        field
        for field in _VERIFICATION_REQUIRED_STRING_FIELDS
        if not isinstance(verification.get(field), str)
        or not str(verification.get(field) or "").strip()
    ]
    if missing_fields:
        raise VerificationError(
            "self-check verification object missing gate fields: "
            + ",".join(missing_fields)
        )
    # Fail closed when free-form process markers could pass as a release body.
    try:
        _reject_process_status(
            {
                "program_id": PROGRAM_ID,
                "master_alive": True,
                "release_status": "completed",
            },
            noun="self-check process status",
        )
    except VerificationError:
        pass
    else:
        raise VerificationError("self-check did not reject process status")
    return {
        "schema": "ipfs_accelerate_py/agent-supervisor/duckdb-quack-release-verifier-check@1",
        "ok": True,
        "verification_schema": VERIFICATION_SCHEMA,
        "release_receipt_schema": RELEASE_RECEIPT_SCHEMA,
        "cutover_receipt_schema": CUTOVER_RECEIPT_SCHEMA,
        "canonical_query_schema": CANONICAL_QUERY_SCHEMA,
        "program_id": PROGRAM_ID,
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "verification_required_fields": list(_VERIFICATION_REQUIRED_STRING_FIELDS),
        "closed_key_sets": {
            "release": sorted(_RELEASE_KEYS),
            "cutover": sorted(_CUTOVER_KEYS),
            "canonical_query": sorted(_CANONICAL_QUERY_KEYS),
            "verification": sorted(_VERIFICATION_KEYS),
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="path to the joined DQP-039/DQP-038 release receipt JSON",
    )
    parser.add_argument(
        "--accelerate-root",
        type=Path,
        default=None,
        help="path to the accelerator Git checkout to bind against",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the typed verification object as strict JSON on success",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="run the verifier self-check without requiring a live receipt",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.check:
            report = self_check()
            if args.json:
                print(canonical_json(report))
            else:
                print(
                    f"ok verification_schema={report['verification_schema']} "
                    f"program_id={report['program_id']}"
                )
            return 0
        if args.receipt is None:
            raise VerificationError("--receipt is required unless --check is set")
        if args.accelerate_root is None:
            raise VerificationError(
                "--accelerate-root is required unless --check is set"
            )
        verification = load_and_verify(
            args.receipt,
            accelerate_root=args.accelerate_root,
        )
        if args.json:
            print(canonical_json(verification))
        else:
            print(
                f"accepted={verification['accepted']} "
                f"schema={verification['schema']} "
                f"accelerator_commit={verification['accelerator_commit']} "
                f"release_receipt_cid={verification['release_receipt_cid']}"
            )
        return 0
    except VerificationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - unexpected failures fail closed
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
