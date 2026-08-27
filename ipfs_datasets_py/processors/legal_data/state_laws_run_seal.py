"""Fail-closed final seals for state-law acquisition runs.

Normalized source receipts produced by the refresh runner are selectable only
after a seal binds the quiescent active-state set, exact start/end producer
identities, canonical JSON-LD bytes, and normalized receipt bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Final
from urllib.parse import urlsplit

from ipfs_datasets_py.processors.web_archiving.wayback_machine_engine import (
    parse_wayback_archive_url,
)


RUN_SEAL_SCHEMA: Final = "ipfs_datasets_py.state_laws_refresh.run_seal.v2"
RUN_SEAL_SUFFIX: Final = ".state-laws-run-seal.json"
PENDING_NORMALIZED_RECEIPT_SUFFIX: Final = ".pending-normalized.json"
NONQUIESCENT_EVIDENCE_MARKER: Final = (
    "state-laws-evidence-permanently-nonauthorizing.json"
)
IN_PROGRESS_EVIDENCE_MARKER: Final = (
    "state-laws-acquisition-in-progress-nonauthorizing.json"
)
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")


class StateLawsRunSealError(ValueError):
    """A run seal is malformed or cannot authorize its bound receipts."""


def validate_authorizing_transport_projection(
    normalized_receipt: Mapping[str, Any],
) -> None:
    """Reject legacy archival leaves that lack exact transport identity.

    The ordinary receipt verifier deliberately retains compatibility with
    historical evidence.  A newly issued run seal is stricter: a Wayback leaf
    must name the exact identity replay, Common Crawl must name its WARC byte
    range (never a relabelled Wayback URL), and the legacy archive.is adapter
    is non-authorizing until it reports the observed original/final locator.
    """

    if not isinstance(normalized_receipt, Mapping):
        raise StateLawsRunSealError("normalized receipt must be a mapping")
    payload = normalized_receipt.get("payload")
    if not isinstance(payload, Mapping):
        raise StateLawsRunSealError("normalized receipt payload must be a mapping")
    raw_verified = payload.get("verified_transport_receipts")
    if not isinstance(raw_verified, Sequence) or isinstance(
        raw_verified,
        (str, bytes, bytearray),
    ):
        raise StateLawsRunSealError(
            "normalized receipt verified_transport_receipts must be a sequence"
        )
    requires_binding = payload.get("requires_verified_transport_binding")
    if not isinstance(requires_binding, bool):
        raise StateLawsRunSealError(
            "normalized receipt transport-binding requirement is missing"
        )
    if requires_binding and payload.get("verified_transport_receipts_trusted") is not True:
        raise StateLawsRunSealError(
            "archival/cache transport receipts are not trusted"
        )

    for index, raw_transport in enumerate(raw_verified):
        if not isinstance(raw_transport, Mapping):
            raise StateLawsRunSealError(
                f"verified transport receipt {index} must be a mapping"
            )
        leaf = str(raw_transport.get("leaf_transport") or "").strip().lower()
        if not leaf:
            raise StateLawsRunSealError(
                f"verified transport receipt {index} omits leaf_transport"
            )
        if leaf == "wayback":
            try:
                parse_wayback_archive_url(
                    raw_transport.get("archive_url"),
                    allowed_modifiers=("id_",),
                    require_identity_modifier=True,
                )
            except ValueError as exc:
                raise StateLawsRunSealError(
                    "authorizing Wayback evidence must bind an exact id_ replay"
                ) from exc
        elif leaf.startswith("common_crawl"):
            archive_url = str(raw_transport.get("archive_url") or "").strip()
            parsed = urlsplit(archive_url)
            required_pointer_fields = (
                "common_crawl_indexed_url",
                "common_crawl_warc_filename",
                "common_crawl_warc_offset",
                "common_crawl_warc_length",
                "common_crawl_collection",
            )
            if (
                parsed.scheme != "https"
                or (parsed.hostname or "").lower() != "data.commoncrawl.org"
                or not re.search(r"\.warc(?:\.gz)?$", parsed.path, re.IGNORECASE)
                or any(raw_transport.get(field) in (None, "") for field in required_pointer_fields)
            ):
                raise StateLawsRunSealError(
                    "authorizing Common Crawl evidence must bind an exact WARC byte range"
                )
        elif leaf == "archive_is":
            raise StateLawsRunSealError(
                "legacy archive.is evidence lacks an observed original/final locator"
            )


def canonical_run_seal_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def run_seal_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_run_seal_bytes(payload)).hexdigest()


def _sha256(value: Any, *, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if _SHA256_RE.fullmatch(normalized) is None:
        raise StateLawsRunSealError(f"{label} must be a lowercase SHA-256 digest")
    return normalized


def _identity_map(
    value: Any,
    *,
    states: Sequence[str],
    label: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise StateLawsRunSealError(f"{label} must be a mapping")
    expected = set(states)
    if set(value) != expected:
        raise StateLawsRunSealError(
            f"{label} must bind the exact active-state set"
        )
    normalized: dict[str, str] = {}
    for state in states:
        identity = str(value.get(state) or "").strip()
        prefix, marker, digest = identity.rpartition("@sha256:")
        if not prefix or not marker or _SHA256_RE.fullmatch(digest) is None:
            raise StateLawsRunSealError(
                f"{label}.{state} must be a content-addressed source identity"
            )
        normalized[state] = identity
    return normalized


def _source_identity(value: Any, *, label: str) -> str:
    identity = str(value or "").strip()
    prefix, marker, digest = identity.rpartition("@sha256:")
    if not prefix or not marker or _SHA256_RE.fullmatch(digest) is None:
        raise StateLawsRunSealError(
            f"{label} must be a content-addressed source identity"
        )
    return identity


def validate_state_laws_run_seal(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one authorizing run-final seal."""

    if not isinstance(payload, Mapping):
        raise StateLawsRunSealError("run seal must be a mapping")
    if payload.get("schema") != RUN_SEAL_SCHEMA:
        raise StateLawsRunSealError("run seal schema is not supported")
    if payload.get("authorizing_for_publication") is not True:
        raise StateLawsRunSealError("run seal is not authorizing")
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id or not re.fullmatch(r"[0-9a-f-]{16,64}", run_id):
        raise StateLawsRunSealError("run_id is invalid")
    active_states_raw = payload.get("active_states")
    if not isinstance(active_states_raw, Sequence) or isinstance(
        active_states_raw,
        (str, bytes, bytearray),
    ):
        raise StateLawsRunSealError("active_states must be a sequence")
    active_states = tuple(
        str(item or "").strip().upper() for item in active_states_raw
    )
    if (
        not active_states
        or any(not re.fullmatch(r"[A-Z]{2}", state) for state in active_states)
        or len(set(active_states)) != len(active_states)
    ):
        raise StateLawsRunSealError("active_states must be unique postal codes")
    start_identities = _identity_map(
        payload.get("start_identities"),
        states=active_states,
        label="start_identities",
    )
    end_identities = _identity_map(
        payload.get("end_identities"),
        states=active_states,
        label="end_identities",
    )
    if start_identities != end_identities:
        raise StateLawsRunSealError("start/end producer identities differ")
    runner_start_identity = _source_identity(
        payload.get("runner_start_identity"),
        label="runner_start_identity",
    )
    runner_end_identity = _source_identity(
        payload.get("runner_end_identity"),
        label="runner_end_identity",
    )
    if runner_start_identity != runner_end_identity:
        raise StateLawsRunSealError("start/end refresh-runner identities differ")

    worker_quiescence = payload.get("worker_quiescence")
    if not isinstance(worker_quiescence, Mapping) or set(worker_quiescence) != set(
        active_states
    ):
        raise StateLawsRunSealError(
            "worker_quiescence must bind the exact active-state set"
        )
    for state in active_states:
        attestation = worker_quiescence.get(state)
        if not isinstance(attestation, Mapping) or not (
            attestation.get("attested") is True
            and attestation.get("quiescent") is True
        ):
            raise StateLawsRunSealError(
                f"worker quiescence is not proven for {state}"
            )

    raw_states = payload.get("states")
    if not isinstance(raw_states, Mapping) or set(raw_states) != set(active_states):
        raise StateLawsRunSealError(
            "run seal states must bind the exact active-state set"
        )
    states: dict[str, dict[str, str]] = {}
    for state in active_states:
        raw_state = raw_states.get(state)
        if not isinstance(raw_state, Mapping):
            raise StateLawsRunSealError(f"run seal state {state} is invalid")
        source_identity = str(raw_state.get("source_software_version") or "").strip()
        if source_identity != start_identities[state]:
            raise StateLawsRunSealError(
                f"run seal state {state} source identity differs from run start"
            )
        states[state] = {
            "canonical_jsonld_sha256": _sha256(
                raw_state.get("canonical_jsonld_sha256"),
                label=f"states.{state}.canonical_jsonld_sha256",
            ),
            "normalized_source_receipt_sha256": _sha256(
                raw_state.get("normalized_source_receipt_sha256"),
                label=f"states.{state}.normalized_source_receipt_sha256",
            ),
            "source_software_version": source_identity,
        }
    created_at = str(payload.get("created_at") or "").strip()
    if not created_at:
        raise StateLawsRunSealError("created_at must be explicit")
    return {
        "schema": RUN_SEAL_SCHEMA,
        "run_id": run_id,
        "created_at": created_at,
        "active_states": list(active_states),
        "start_identities": start_identities,
        "end_identities": end_identities,
        "runner_start_identity": runner_start_identity,
        "runner_end_identity": runner_end_identity,
        "worker_quiescence": {
            state: dict(worker_quiescence[state]) for state in active_states
        },
        "states": states,
        "authorizing_for_publication": True,
    }


def build_state_laws_run_seal(
    *,
    run_id: str,
    created_at: str,
    active_states: Sequence[str],
    start_identities: Mapping[str, str],
    end_identities: Mapping[str, str],
    runner_start_identity: str,
    runner_end_identity: str,
    worker_quiescence: Mapping[str, Mapping[str, Any]],
    states: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    candidate = {
        "schema": RUN_SEAL_SCHEMA,
        "run_id": str(run_id),
        "created_at": str(created_at),
        "active_states": [str(state).upper() for state in active_states],
        "start_identities": dict(start_identities),
        "end_identities": dict(end_identities),
        "runner_start_identity": str(runner_start_identity),
        "runner_end_identity": str(runner_end_identity),
        "worker_quiescence": {
            str(state).upper(): dict(value)
            for state, value in worker_quiescence.items()
        },
        "states": {
            str(state).upper(): dict(value) for state, value in states.items()
        },
        "authorizing_for_publication": True,
    }
    return validate_state_laws_run_seal(candidate)


__all__ = [
    "NONQUIESCENT_EVIDENCE_MARKER",
    "PENDING_NORMALIZED_RECEIPT_SUFFIX",
    "RUN_SEAL_SCHEMA",
    "RUN_SEAL_SUFFIX",
    "StateLawsRunSealError",
    "build_state_laws_run_seal",
    "canonical_run_seal_bytes",
    "run_seal_sha256",
    "validate_authorizing_transport_projection",
    "validate_state_laws_run_seal",
]
