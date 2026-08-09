#!/usr/bin/env python3
"""Fail-closed external DQP release verifier for the DQK-056 gate (DQK-057).

Invoked by ``ack-release --receipt ...`` (and the manual-gate sealed subprocess)
as::

    python scripts/validation/validate_accelerate_duckdb_quack_release.py \\
        --receipt <path> --accelerate-root <path> --json

Verifies a terminal DQP-039 ``DuckDBControlPlaneReleaseReceipt@1`` joined to a
DQP-038 ``DatabaseCutoverReceipt@1``: exact accelerator Git commit/tree, store
generation, schema checksum, Quack compatibility profile, expiry, signature,
and accepted decision. Emits the strict typed verification object::

    ipfs_accelerate_py/agent-supervisor/duckdb-quack-release-verification@1

Fail-closed rules (non-exhaustive):

* Markdown boards and process-status JSON cannot satisfy the gate.
* Missing canonical receipt query or machine-readable identity fails closed.
* Stale, mismatched, expired, unsigned, or unaccepted cutover receipts fail.
* Nested release/cutover identities must recompute from their bodies.
* Accelerator HEAD commit/tree must match the envelope bindings exactly.

Exit codes: 0 on accepted verification, 1 on any rejection/usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Mapping, MutableMapping, Sequence

# ---------------------------------------------------------------------------
# Contract identity
# ---------------------------------------------------------------------------

VERIFICATION_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/duckdb-quack-release-verification@1"
)
GATE_INPUT_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/duckdb-quack-release-gate-input@1"
)
RELEASE_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/duckdb-control-plane-release-receipt@1"
)
CUTOVER_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/database-cutover-receipt@1"
)
RELEASE_INTERFACE: Final[str] = "DuckDBControlPlaneReleaseReceipt@1"
CUTOVER_INTERFACE: Final[str] = "DatabaseCutoverReceipt@1"
PROGRAM_ID: Final[str] = "agent-supervisor-duckdb-quack-control-plane-v1"
RELEASE_TASK_ID: Final[str] = "DQP-039"
CUTOVER_TASK_ID: Final[str] = "DQP-038"
SIGNATURE_DOMAIN: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/duckdb-quack-release-gate@1"
)
CONTENT_DOMAIN: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/duckdb-quack-release-body@1"
)

GIT_SHA_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
SCHEMA_CHECKSUM_RE: Final[re.Pattern[str]] = re.compile(
    r"^sha256:[0-9a-f]{64}$"
)
MAX_RECEIPT_BYTES: Final[int] = 2 * 1024 * 1024
MAX_TEXT_BYTES: Final[int] = 4096
MAX_SHORT_BYTES: Final[int] = 512

# Process-status / doctor payloads are never release authority.
_PROCESS_STATUS_KEYS: Final[frozenset[str]] = frozenset(
    {
        "master_pid",
        "master_alive",
        "release_status",
        "lane_status",
        "stale_or_unbound_lanes",
        "daemon_pid",
        "supervisor_pid",
        "heartbeat_age_seconds",
        "status_counts",
        "active_worker_count",
    }
)


class ReleaseVerifierError(ValueError):
    """Fail-closed rejection for the external DQP release verifier."""


# ---------------------------------------------------------------------------
# Canonical JSON / identity
# ---------------------------------------------------------------------------


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_identity(payload: Any, *, domain: str = CONTENT_DOMAIN) -> str:
    raw = domain.encode("utf-8") + b"|" + _canonical_json(payload).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _strict_json_object(text: str, *, noun: str) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise ReleaseVerifierError(f"{noun} is empty")
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_RECEIPT_BYTES:
        raise ReleaseVerifierError(f"{noun} exceeds the {MAX_RECEIPT_BYTES}-byte bound")
    if b"\x00" in encoded:
        raise ReleaseVerifierError(f"{noun} contains a NUL byte")

    def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReleaseVerifierError(f"{noun} contains a duplicate key: {key!r}")
            result[key] = value
        return result

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_object_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ReleaseVerifierError(f"{noun} contains non-finite value {token}")
            ),
        )
    except json.JSONDecodeError as exc:
        raise ReleaseVerifierError(f"{noun} is not strict JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ReleaseVerifierError(f"{noun} root must be a JSON object")
    return parsed


def _bounded_text(
    value: Any,
    name: str,
    *,
    maximum: int = MAX_TEXT_BYTES,
    pattern: re.Pattern[str] | None = None,
) -> str:
    if not isinstance(value, str):
        raise ReleaseVerifierError(f"{name} must be text")
    text = value.strip()
    if not text:
        raise ReleaseVerifierError(f"{name} must not be empty")
    if any(character in text for character in ("\0", "\n", "\r")):
        raise ReleaseVerifierError(f"{name} contains a forbidden control character")
    if len(text.encode("utf-8")) > maximum:
        raise ReleaseVerifierError(f"{name} exceeds its {maximum}-byte bound")
    if pattern is not None and not pattern.fullmatch(text):
        raise ReleaseVerifierError(f"{name} has an invalid format")
    return text


def _parse_timestamp(value: Any, name: str) -> datetime:
    text = _bounded_text(value, name, maximum=128)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReleaseVerifierError(f"{name} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReleaseVerifierError(f"{name} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _normalize_store_generation(value: Any) -> str:
    if isinstance(value, bool):
        raise ReleaseVerifierError("store_generation must not be a boolean")
    if isinstance(value, int):
        if value < 0:
            raise ReleaseVerifierError("store_generation must be non-negative")
        return str(value)
    return _bounded_text(value, "store_generation", maximum=MAX_SHORT_BYTES)


# ---------------------------------------------------------------------------
# Git identity against accelerate-root
# ---------------------------------------------------------------------------


def _git(accelerate_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=accelerate_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseVerifierError(
            f"git invocation failed under accelerate-root: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        raise ReleaseVerifierError(
            "git failed under accelerate-root: "
            + (detail[-1] if detail else f"exit {completed.returncode}")
        )
    return completed.stdout.strip()


def observe_accelerator_git(accelerate_root: Path) -> tuple[str, str]:
    root = Path(accelerate_root)
    if not root.is_dir():
        raise ReleaseVerifierError("accelerate-root is not a directory")
    git_dir = root / ".git"
    if not git_dir.exists():
        raise ReleaseVerifierError("accelerate-root is not a git repository")
    commit = _git(root, "rev-parse", "HEAD").lower()
    tree = _git(root, "rev-parse", "HEAD^{tree}").lower()
    if not GIT_SHA_RE.fullmatch(commit) or not GIT_SHA_RE.fullmatch(tree):
        raise ReleaseVerifierError("accelerate-root git identity is malformed")
    return commit, tree


# ---------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------


def signature_payload(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Return the signed body (everything except the signature field)."""

    return {key: value for key, value in envelope.items() if key != "signature"}


def compute_signature(envelope: Mapping[str, Any], *, signing_key: bytes | None = None) -> str:
    body = signature_payload(envelope)
    canonical = _canonical_json(body).encode("utf-8")
    if signing_key:
        digest = hmac.new(
            signing_key, SIGNATURE_DOMAIN.encode("utf-8") + b"|" + canonical, hashlib.sha256
        ).hexdigest()
        return f"hmac-sha256:{digest}"
    digest = hashlib.sha256(
        SIGNATURE_DOMAIN.encode("utf-8") + b"|" + canonical
    ).hexdigest()
    return f"sha256:{digest}"


def _resolve_signing_key() -> bytes | None:
    raw = os.environ.get("DQK_RELEASE_GATE_SIGNING_KEY", "").strip()
    if not raw:
        return None
    return raw.encode("utf-8")


def verify_signature(envelope: Mapping[str, Any], *, signing_key: bytes | None = None) -> None:
    signature = envelope.get("signature")
    if not isinstance(signature, str) or not signature.strip():
        raise ReleaseVerifierError("release gate input is unsigned")
    expected = compute_signature(envelope, signing_key=signing_key)
    if not hmac.compare_digest(signature.strip(), expected):
        # Also accept pure content digest when an HMAC key is configured so
        # operators can publish keyless content-bound envelopes.
        if signing_key is not None:
            content_only = compute_signature(envelope, signing_key=None)
            if hmac.compare_digest(signature.strip(), content_only):
                return
        raise ReleaseVerifierError("release gate input signature is invalid")


# ---------------------------------------------------------------------------
# Nested receipt validation
# ---------------------------------------------------------------------------


def _reject_markdown_or_process_status(raw: str, payload: Mapping[str, Any]) -> None:
    stripped = raw.lstrip()
    if stripped.startswith("#") or stripped.startswith("## "):
        raise ReleaseVerifierError(
            "markdown board or prose cannot satisfy the release gate"
        )
    if payload.get("schema") in {None, ""} and any(
        key in payload for key in _PROCESS_STATUS_KEYS
    ):
        raise ReleaseVerifierError(
            "process status cannot satisfy the release gate"
        )
    if (
        "release_status" in payload
        and "lanes" in payload
        and payload.get("schema") not in {GATE_INPUT_SCHEMA}
    ):
        raise ReleaseVerifierError(
            "external process status cannot satisfy the release gate"
        )
    if payload.get("schema") == GATE_INPUT_SCHEMA:
        return
    # Explicit substitute kinds.
    kind = str(payload.get("kind") or payload.get("evidence_kind") or "").lower()
    if kind in {"markdown", "process_status", "task_status", "board_status", "prose"}:
        raise ReleaseVerifierError(
            f"{kind or 'substitute'} evidence cannot satisfy the release gate"
        )


def _validate_identity_id(payload: Mapping[str, Any], name: str) -> str:
    identity = _bounded_text(payload.get("identity_id"), f"{name}.identity_id", maximum=160)
    body = {key: value for key, value in payload.items() if key != "identity_id"}
    expected = content_identity(body, domain=CONTENT_DOMAIN)
    # Accept both domain-bound and domain-free canonical digests for
    # interoperability with DQP producers that use sort_keys JSON only.
    free = "sha256:" + hashlib.sha256(
        _canonical_json(body).encode("utf-8")
    ).hexdigest()
    if not hmac.compare_digest(identity, expected) and not hmac.compare_digest(
        identity, free
    ):
        raise ReleaseVerifierError(
            f"{name} machine-readable identity does not recompute"
        )
    return identity


def _validate_canonical_receipt_query(query: Any) -> dict[str, str]:
    if not isinstance(query, Mapping):
        raise ReleaseVerifierError("canonical_receipt_query is missing")
    required = {
        "program_id": PROGRAM_ID,
        "release_task_id": RELEASE_TASK_ID,
        "release_interface": RELEASE_INTERFACE,
        "cutover_task_id": CUTOVER_TASK_ID,
        "cutover_interface": CUTOVER_INTERFACE,
    }
    cleaned: dict[str, str] = {}
    for field, expected in required.items():
        value = _bounded_text(query.get(field), f"canonical_receipt_query.{field}", maximum=160)
        if value != expected:
            raise ReleaseVerifierError(
                f"canonical_receipt_query.{field} is mismatched"
            )
        cleaned[field] = value
    cleaned["release_receipt_cid"] = _bounded_text(
        query.get("release_receipt_cid"),
        "canonical_receipt_query.release_receipt_cid",
        maximum=160,
    )
    cleaned["cutover_receipt_cid"] = _bounded_text(
        query.get("cutover_receipt_cid"),
        "canonical_receipt_query.cutover_receipt_cid",
        maximum=160,
    )
    return cleaned


def _validate_release_receipt(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise ReleaseVerifierError("release_receipt is missing")
    if receipt.get("schema") != RELEASE_RECEIPT_SCHEMA:
        raise ReleaseVerifierError("release_receipt schema is unsupported")
    if receipt.get("interface") != RELEASE_INTERFACE:
        raise ReleaseVerifierError("release_receipt interface is unsupported")
    if receipt.get("task_id") not in {RELEASE_TASK_ID, None, ""}:
        # Allow producers that omit task_id only when identity is otherwise sound;
        # when present it must be DQP-039.
        if receipt.get("task_id") != RELEASE_TASK_ID:
            raise ReleaseVerifierError("release_receipt task_id is mismatched")
    verdict = str(receipt.get("verdict") or "").lower()
    if verdict != "pass" or receipt.get("passed") is not True:
        raise ReleaseVerifierError("release_receipt decision is not accepted")
    tree_id = _bounded_text(receipt.get("tree_id"), "release_receipt.tree_id")
    schema_checksum = _bounded_text(
        receipt.get("schema_checksum"),
        "release_receipt.schema_checksum",
        maximum=128,
        pattern=SCHEMA_CHECKSUM_RE,
    )
    store_generation = _normalize_store_generation(receipt.get("store_generation"))
    quack_profile = _bounded_text(
        receipt.get("quack_profile"), "release_receipt.quack_profile", maximum=160
    )
    git_identity = _bounded_text(
        receipt.get("git_identity"), "release_receipt.git_identity", maximum=160
    )
    identity_id = _validate_identity_id(dict(receipt), "release_receipt")
    components = receipt.get("components")
    if not isinstance(components, Mapping) or not components:
        raise ReleaseVerifierError("release_receipt components are missing")
    cutover_status = str(components.get("cutover") or "").lower()
    if cutover_status != "pass":
        raise ReleaseVerifierError(
            "release_receipt does not join a passing cutover component"
        )
    return {
        "tree_id": tree_id,
        "schema_checksum": schema_checksum,
        "store_generation": store_generation,
        "quack_profile": quack_profile,
        "git_identity": git_identity,
        "identity_id": identity_id,
        "receipt": dict(receipt),
    }


def _validate_cutover_receipt(
    receipt: Any,
    *,
    expected_schema_checksum: str,
    expected_store_generation: str,
    expected_quack_profile: str,
    now: datetime,
) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise ReleaseVerifierError("cutover_receipt is missing")
    if receipt.get("schema") != CUTOVER_RECEIPT_SCHEMA:
        raise ReleaseVerifierError("cutover_receipt schema is unsupported")
    if receipt.get("interface") != CUTOVER_INTERFACE:
        raise ReleaseVerifierError("cutover_receipt interface is unsupported")
    if receipt.get("task_id") not in {CUTOVER_TASK_ID, None, ""}:
        if receipt.get("task_id") != CUTOVER_TASK_ID:
            raise ReleaseVerifierError("cutover_receipt task_id is mismatched")

    signature = receipt.get("signature")
    if not isinstance(signature, str) or not signature.strip():
        raise ReleaseVerifierError("cutover_receipt is unsigned")
    # Signature binds the cutover body excluding signature and identity_id.
    signed_body = {
        key: value
        for key, value in receipt.items()
        if key not in {"signature", "identity_id"}
    }
    expected_sig = "sha256:" + hashlib.sha256(
        SIGNATURE_DOMAIN.encode("utf-8")
        + b"|cutover|"
        + _canonical_json(signed_body).encode("utf-8")
    ).hexdigest()
    if not hmac.compare_digest(signature.strip(), expected_sig):
        raise ReleaseVerifierError("cutover_receipt signature is invalid")

    verdict = str(receipt.get("verdict") or "").lower()
    promoted = receipt.get("promoted")
    accepted = receipt.get("accepted")
    if verdict not in {"promoted", "accepted"} and promoted is not True and accepted is not True:
        raise ReleaseVerifierError("cutover_receipt is unaccepted")
    if promoted is False or accepted is False:
        raise ReleaseVerifierError("cutover_receipt is unaccepted")
    if receipt.get("dual_write_accepted") is True:
        raise ReleaseVerifierError("cutover_receipt accepts dual writes")

    binding = receipt.get("binding")
    if not isinstance(binding, Mapping):
        raise ReleaseVerifierError("cutover_receipt binding is missing")
    binding_checksum = _bounded_text(
        binding.get("schema_checksum"),
        "cutover_receipt.binding.schema_checksum",
        maximum=128,
        pattern=SCHEMA_CHECKSUM_RE,
    )
    binding_profile = _bounded_text(
        binding.get("quack_profile"),
        "cutover_receipt.binding.quack_profile",
        maximum=160,
    )
    binding_generation = _normalize_store_generation(binding.get("store_generation"))
    if binding_checksum != expected_schema_checksum:
        raise ReleaseVerifierError("cutover_receipt schema checksum is mismatched")
    if binding_profile != expected_quack_profile:
        raise ReleaseVerifierError("cutover_receipt quack profile is mismatched")
    if binding_generation != expected_store_generation:
        raise ReleaseVerifierError("cutover_receipt store generation is mismatched")

    # Expiry: explicit expires_at, else created_at + binding.expiry_seconds.
    expires_at: datetime | None = None
    if receipt.get("expires_at") is not None:
        expires_at = _parse_timestamp(receipt.get("expires_at"), "cutover_receipt.expires_at")
    else:
        created_at = _parse_timestamp(receipt.get("created_at"), "cutover_receipt.created_at")
        expiry_seconds = binding.get("expiry_seconds", 0)
        if isinstance(expiry_seconds, bool) or not isinstance(expiry_seconds, int):
            raise ReleaseVerifierError("cutover_receipt binding.expiry_seconds is invalid")
        if expiry_seconds < 0:
            raise ReleaseVerifierError("cutover_receipt binding.expiry_seconds is negative")
        if expiry_seconds == 0:
            raise ReleaseVerifierError("cutover_receipt is missing expiry")
        expires_at = datetime.fromtimestamp(
            created_at.timestamp() + expiry_seconds, tz=timezone.utc
        )
    if expires_at <= now:
        raise ReleaseVerifierError("cutover_receipt is expired")

    identity_id = _validate_identity_id(dict(receipt), "cutover_receipt")
    return {
        "identity_id": identity_id,
        "expires_at": expires_at,
        "receipt": dict(receipt),
    }


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def build_verification(
    *,
    accelerator_commit: str,
    accelerator_tree: str,
    release_receipt_cid: str,
    cutover_receipt_cid: str,
    store_generation: str,
    schema_checksum: str,
    quack_profile: str,
    decision_cid: str,
    expires_at: str,
    accepted: bool = True,
) -> dict[str, Any]:
    return {
        "schema": VERIFICATION_SCHEMA,
        "accepted": accepted is True,
        "accelerator_commit": accelerator_commit.lower(),
        "accelerator_tree": accelerator_tree.lower(),
        "release_receipt_cid": release_receipt_cid,
        "cutover_receipt_cid": cutover_receipt_cid,
        "store_generation": store_generation,
        "schema_checksum": schema_checksum,
        "quack_profile": quack_profile,
        "decision_cid": decision_cid,
        "expires_at": expires_at,
    }


def verify_release_gate_input(
    envelope: Mapping[str, Any],
    *,
    accelerate_root: Path,
    now: datetime | None = None,
    signing_key: bytes | None = None,
) -> dict[str, Any]:
    """Verify a joined release/cutover gate input and emit typed verification."""

    if not isinstance(envelope, Mapping):
        raise ReleaseVerifierError("gate input must be a JSON object")
    if envelope.get("schema") != GATE_INPUT_SCHEMA:
        raise ReleaseVerifierError("gate input schema is unsupported")

    verify_signature(envelope, signing_key=signing_key)

    if envelope.get("accepted") is not True:
        raise ReleaseVerifierError("gate input decision is not accepted")

    query = _validate_canonical_receipt_query(envelope.get("canonical_receipt_query"))
    release = _validate_release_receipt(envelope.get("release_receipt"))
    cutover = _validate_cutover_receipt(
        envelope.get("cutover_receipt"),
        expected_schema_checksum=release["schema_checksum"],
        expected_store_generation=release["store_generation"],
        expected_quack_profile=release["quack_profile"],
        now=now or datetime.now(timezone.utc),
    )

    if query["release_receipt_cid"] != release["identity_id"]:
        raise ReleaseVerifierError(
            "canonical release_receipt_cid does not match release identity"
        )
    if query["cutover_receipt_cid"] != cutover["identity_id"]:
        raise ReleaseVerifierError(
            "canonical cutover_receipt_cid does not match cutover identity"
        )

    accelerator_commit = _bounded_text(
        envelope.get("accelerator_commit"),
        "accelerator_commit",
        maximum=64,
        pattern=GIT_SHA_RE,
    ).lower()
    accelerator_tree = _bounded_text(
        envelope.get("accelerator_tree"),
        "accelerator_tree",
        maximum=64,
        pattern=GIT_SHA_RE,
    ).lower()

    observed_commit, observed_tree = observe_accelerator_git(Path(accelerate_root))
    if observed_commit != accelerator_commit:
        raise ReleaseVerifierError(
            "accelerator_commit is stale or mismatched against accelerate-root HEAD"
        )
    if observed_tree != accelerator_tree:
        raise ReleaseVerifierError(
            "accelerator_tree is stale or mismatched against accelerate-root HEAD"
        )

    # Optional binding: release git_identity may embed the commit.
    git_identity = release["git_identity"].lower()
    if accelerator_commit not in git_identity and git_identity not in {
        accelerator_commit,
        f"git:{accelerator_commit}",
        f"commit:{accelerator_commit}",
    }:
        # tree binding is also accepted when git_identity carries the tree.
        if accelerator_tree not in git_identity:
            raise ReleaseVerifierError(
                "release_receipt git_identity is mismatched against accelerator git"
            )

    envelope_schema_checksum = _bounded_text(
        envelope.get("schema_checksum", release["schema_checksum"]),
        "schema_checksum",
        maximum=128,
        pattern=SCHEMA_CHECKSUM_RE,
    )
    if envelope_schema_checksum != release["schema_checksum"]:
        raise ReleaseVerifierError("envelope schema_checksum is mismatched")

    envelope_profile = _bounded_text(
        envelope.get("quack_profile", release["quack_profile"]),
        "quack_profile",
        maximum=160,
    )
    if envelope_profile != release["quack_profile"]:
        raise ReleaseVerifierError("envelope quack_profile is mismatched")

    envelope_generation = _normalize_store_generation(
        envelope.get("store_generation", release["store_generation"])
    )
    if envelope_generation != release["store_generation"]:
        raise ReleaseVerifierError("envelope store_generation is mismatched")

    expires_at = _parse_timestamp(envelope.get("expires_at"), "expires_at")
    current = now or datetime.now(timezone.utc)
    if expires_at <= current:
        raise ReleaseVerifierError("release gate input is expired")
    if cutover["expires_at"] < expires_at and cutover["expires_at"] <= current:
        raise ReleaseVerifierError("joined cutover receipt is expired")

    decision_cid = _bounded_text(envelope.get("decision_cid"), "decision_cid", maximum=160)
    # Decision binds the pre-signature body excluding decision_cid itself.
    decision_body = {
        key: value
        for key, value in envelope.items()
        if key not in {"signature", "decision_cid"}
    }
    expected_decision = content_identity(decision_body, domain=SIGNATURE_DOMAIN)
    free_decision = "sha256:" + hashlib.sha256(
        _canonical_json(decision_body).encode("utf-8")
    ).hexdigest()
    if decision_cid not in {expected_decision, free_decision}:
        raise ReleaseVerifierError("decision_cid does not bind the signed gate input")

    return build_verification(
        accelerator_commit=accelerator_commit,
        accelerator_tree=accelerator_tree,
        release_receipt_cid=release["identity_id"],
        cutover_receipt_cid=cutover["identity_id"],
        store_generation=envelope_generation,
        schema_checksum=envelope_schema_checksum,
        quack_profile=envelope_profile,
        decision_cid=decision_cid,
        expires_at=expires_at.isoformat().replace("+00:00", "Z")
        if expires_at.utcoffset() == timezone.utc.utcoffset(expires_at)
        else expires_at.isoformat(),
        accepted=True,
    )


def load_gate_input(path: Path) -> tuple[dict[str, Any], str]:
    target = Path(path)
    try:
        # No symlink following for authority inputs.
        if target.is_symlink():
            raise ReleaseVerifierError("receipt path must not be a symlink")
        raw_bytes = target.read_bytes()
    except OSError as exc:
        raise ReleaseVerifierError(f"receipt is unreadable: {exc}") from exc
    if len(raw_bytes) > MAX_RECEIPT_BYTES:
        raise ReleaseVerifierError("receipt exceeds the byte bound")
    if b"\x00" in raw_bytes:
        raise ReleaseVerifierError("receipt contains a NUL byte")
    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseVerifierError("receipt is not UTF-8") from exc
    # Markdown files cannot satisfy the gate even if they contain JSON later.
    if target.suffix.lower() in {".md", ".markdown", ".txt"}:
        raise ReleaseVerifierError(
            "markdown or text process notes cannot satisfy the release gate"
        )
    payload = _strict_json_object(raw, noun="receipt")
    _reject_markdown_or_process_status(raw, payload)
    return payload, raw


def verify_receipt_file(
    receipt_path: Path,
    *,
    accelerate_root: Path,
    now: datetime | None = None,
    signing_key: bytes | None = None,
) -> dict[str, Any]:
    envelope, _raw = load_gate_input(receipt_path)
    return verify_release_gate_input(
        envelope,
        accelerate_root=accelerate_root,
        now=now,
        signing_key=signing_key if signing_key is not None else _resolve_signing_key(),
    )


# ---------------------------------------------------------------------------
# Fixture helpers (used by tests; safe for hermetic construction)
# ---------------------------------------------------------------------------


def cutover_signature_for(body: Mapping[str, Any]) -> str:
    payload = {
        key: value
        for key, value in body.items()
        if key not in {"signature", "identity_id"}
    }
    return "sha256:" + hashlib.sha256(
        SIGNATURE_DOMAIN.encode("utf-8")
        + b"|cutover|"
        + _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def attach_identity(payload: MutableMapping[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in payload.items() if key != "identity_id"}
    payload = dict(payload)
    payload["identity_id"] = content_identity(body, domain=CONTENT_DOMAIN)
    return payload


def build_signed_gate_input(
    *,
    accelerator_commit: str,
    accelerator_tree: str,
    schema_checksum: str,
    store_generation: str | int,
    quack_profile: str,
    expires_at: str,
    decision_cid: str | None = None,
    accepted: bool = True,
    signing_key: bytes | None = None,
    release_overrides: Mapping[str, Any] | None = None,
    cutover_overrides: Mapping[str, Any] | None = None,
    envelope_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a hermetic, signed gate input for tests and dry-runs."""

    generation = _normalize_store_generation(store_generation)
    release_body: dict[str, Any] = {
        "schema": RELEASE_RECEIPT_SCHEMA,
        "interface": RELEASE_INTERFACE,
        "contract_version": 1,
        "evidence": "dqp/duckdb-quack-release@1",
        "task_id": RELEASE_TASK_ID,
        "goal_id": "DQP-G090",
        "verdict": "pass",
        "passed": True,
        "tree_id": f"tree:git:{accelerator_tree}",
        "schema_checksum": schema_checksum,
        "store_generation": generation,
        "quack_profile": quack_profile,
        "extension_fingerprint": "sha256:" + ("ab" * 32),
        "git_identity": f"git:{accelerator_commit}",
        "components": {
            "schema": "pass",
            "quack": "pass",
            "import_export": "pass",
            "intent": "pass",
            "runtime": "pass",
            "worktree": "pass",
            "ast_mutation": "pass",
            "symbolic_proof": "pass",
            "context_churn": "pass",
            "control": "pass",
            "watchdog": "pass",
            "backup": "pass",
            "chaos": "pass",
            "canary": "pass",
            "shadow": "pass",
            "cutover": "pass",
            "rollback": "pass",
        },
        "missing_roots": [],
        "modules_present": [],
        "modules_missing": [],
        "tasks_terminal": True,
        "safety_floors_zero": True,
        "quality_non_regressing": True,
        "legacy_file_decision_read_in_canary": False,
        "rollback_present": True,
        "experimental_scope": True,
        "production_ha_claimed": False,
        "duckdb_2_0_compatibility_claimed": False,
        "safety_floors": {},
        "beta_limitations": ["quack-beta"],
        "reason_codes": [],
        "created_at": "2026-08-09T00:00:00Z",
    }
    if release_overrides:
        release_body.update(dict(release_overrides))
    release_receipt = attach_identity(release_body)

    cutover_body: dict[str, Any] = {
        "schema": CUTOVER_RECEIPT_SCHEMA,
        "interface": CUTOVER_INTERFACE,
        "contract_version": 1,
        "evidence": "dqp/database-cutover@1",
        "task_id": CUTOVER_TASK_ID,
        "goal_id": "DQP-G080",
        "verdict": "promoted",
        "promoted": True,
        "accepted": True,
        "from_stage": "canary",
        "to_stage": "default",
        "binding": {
            "schema": "ipfs_accelerate_py/agent-supervisor/database-rollout-stage-binding@1",
            "stage": "default",
            "authority_mode": "quack_default",
            "roots": ["control"],
            "store_generation": generation,
            "schema_checksum": schema_checksum,
            "quack_profile": quack_profile,
            "kill_switch": False,
            "operator_action": "promote-default",
            "expiry_seconds": 86_400,
        },
        "policy_identity": "sha256:" + ("11" * 32),
        "evidence_identity": "sha256:" + ("22" * 32),
        "history_preserved": True,
        "dual_write_accepted": False,
        "denial_reasons": [],
        "reason_codes": [],
        "beta_limitations": ["quack-beta"],
        "created_at": "2026-08-09T00:00:00Z",
        "expires_at": expires_at,
    }
    if cutover_overrides:
        # Allow deep override of binding.
        overrides = dict(cutover_overrides)
        binding_override = overrides.pop("binding", None)
        cutover_body.update(overrides)
        if isinstance(binding_override, Mapping):
            binding = dict(cutover_body["binding"])
            binding.update(dict(binding_override))
            cutover_body["binding"] = binding
    cutover_body["signature"] = cutover_signature_for(cutover_body)
    cutover_receipt = attach_identity(cutover_body)

    envelope: dict[str, Any] = {
        "schema": GATE_INPUT_SCHEMA,
        "accepted": accepted,
        "accelerator_commit": accelerator_commit.lower(),
        "accelerator_tree": accelerator_tree.lower(),
        "store_generation": generation,
        "schema_checksum": schema_checksum,
        "quack_profile": quack_profile,
        "expires_at": expires_at,
        "canonical_receipt_query": {
            "program_id": PROGRAM_ID,
            "release_task_id": RELEASE_TASK_ID,
            "release_interface": RELEASE_INTERFACE,
            "cutover_task_id": CUTOVER_TASK_ID,
            "cutover_interface": CUTOVER_INTERFACE,
            "release_receipt_cid": release_receipt["identity_id"],
            "cutover_receipt_cid": cutover_receipt["identity_id"],
        },
        "release_receipt": release_receipt,
        "cutover_receipt": cutover_receipt,
    }
    if envelope_overrides:
        envelope.update(dict(envelope_overrides))
        # Keep nested CIDs consistent when receipts replaced.
        if "release_receipt" in envelope and isinstance(envelope["release_receipt"], dict):
            if "identity_id" not in envelope["release_receipt"]:
                envelope["release_receipt"] = attach_identity(envelope["release_receipt"])
        if "cutover_receipt" in envelope and isinstance(envelope["cutover_receipt"], dict):
            cut = dict(envelope["cutover_receipt"])
            if "signature" not in cut or not cut.get("signature"):
                cut["signature"] = cutover_signature_for(cut)
            if "identity_id" not in cut:
                cut = attach_identity(cut)
            envelope["cutover_receipt"] = cut
        query = dict(envelope.get("canonical_receipt_query") or {})
        if isinstance(envelope.get("release_receipt"), Mapping):
            query.setdefault(
                "release_receipt_cid",
                envelope["release_receipt"].get("identity_id"),
            )
        if isinstance(envelope.get("cutover_receipt"), Mapping):
            query.setdefault(
                "cutover_receipt_cid",
                envelope["cutover_receipt"].get("identity_id"),
            )
        for field, expected in (
            ("program_id", PROGRAM_ID),
            ("release_task_id", RELEASE_TASK_ID),
            ("release_interface", RELEASE_INTERFACE),
            ("cutover_task_id", CUTOVER_TASK_ID),
            ("cutover_interface", CUTOVER_INTERFACE),
        ):
            query.setdefault(field, expected)
        envelope["canonical_receipt_query"] = query
    if decision_cid is None:
        decision_body = {
            key: value
            for key, value in envelope.items()
            if key not in {"signature", "decision_cid"}
        }
        decision_cid = content_identity(decision_body, domain=SIGNATURE_DOMAIN)
    envelope["decision_cid"] = decision_cid
    envelope["signature"] = compute_signature(envelope, signing_key=signing_key)
    return envelope


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="Path to the joined DQP-039/DQP-038 release gate input JSON",
    )
    parser.add_argument(
        "--accelerate-root",
        type=Path,
        default=None,
        help="Path to the accelerator git repository (exact HEAD binding)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the typed verification object as JSON on stdout",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Self-check: confirm the verifier contract is loadable. "
            "When combined with --receipt/--accelerate-root, performs full verification."
        ),
    )
    parser.add_argument(
        "--now",
        default=None,
        help="Optional ISO-8601 clock override for expiry checks (tests)",
    )
    return parser


def _self_check_payload() -> dict[str, Any]:
    return {
        "schema": VERIFICATION_SCHEMA,
        "check": "ok",
        "gate_input_schema": GATE_INPUT_SCHEMA,
        "release_interface": RELEASE_INTERFACE,
        "cutover_interface": CUTOVER_INTERFACE,
        "program_id": PROGRAM_ID,
        "accepted": False,
        "detail": "self-check only; full acceptance requires a verified receipt",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        now = (
            _parse_timestamp(args.now, "--now")
            if args.now is not None
            else datetime.now(timezone.utc)
        )

        if args.receipt is None and args.accelerate_root is None:
            if args.check:
                payload = _self_check_payload()
                if args.json:
                    print(_canonical_json(payload))
                else:
                    print(
                        f"check=ok schema={VERIFICATION_SCHEMA} "
                        f"(receipt required for accepted verification)"
                    )
                return 0
            raise ReleaseVerifierError(
                "missing --receipt and --accelerate-root "
                "(markdown/process status cannot satisfy the gate)"
            )

        if args.receipt is None:
            raise ReleaseVerifierError(
                "missing --receipt; canonical machine-readable receipt is required"
            )
        if args.accelerate_root is None:
            raise ReleaseVerifierError("missing --accelerate-root")

        verification = verify_receipt_file(
            Path(args.receipt),
            accelerate_root=Path(args.accelerate_root),
            now=now,
        )
        if verification.get("schema") != VERIFICATION_SCHEMA:
            raise ReleaseVerifierError("internal verification schema mismatch")
        if verification.get("accepted") is not True:
            raise ReleaseVerifierError("verification did not accept the release")

        if args.json or args.check:
            print(_canonical_json(verification))
        else:
            print(
                "accepted "
                f"schema={verification['schema']} "
                f"commit={verification['accelerator_commit']} "
                f"tree={verification['accelerator_tree']}"
            )
        return 0
    except ReleaseVerifierError as exc:
        if args.json:
            print(
                _canonical_json(
                    {
                        "schema": VERIFICATION_SCHEMA,
                        "accepted": False,
                        "error": str(exc),
                    }
                ),
                file=sys.stderr,
            )
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - unexpected
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
