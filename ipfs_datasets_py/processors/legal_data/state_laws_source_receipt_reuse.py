"""Fail-closed reuse bridge for existing state-law acquisition receipts.

This module does not create acquisition evidence.  It joins two existing
production contracts only when the caller retains every byte needed to prove
the join:

* :mod:`open_us_law_acquisition_coordinator` verifies the request, response,
  admitted body, and closed/replayed source frontier; and
* :mod:`state_laws_legacy_v2_adapter` verifies the official-source policy,
  exact canonical-artifact binding, and adapter row-count contract.

A scraper checkpoint, completion ledger, or local rematerialization receipt is
not sufficient input.  In particular, hashing one of those artifacts after the
scrape cannot reconstruct missing request/response or frontier evidence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
    evaluate_prior_receipt,
)
from ipfs_datasets_py.processors.legal_data.state_laws_legacy_v2_adapter import (
    NormalizedSourceReceipt,
    file_sha256,
    legacy_input_row_count,
    normalize_source_receipt,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    OfficialSourceCatalog,
)

SCHEMA_VERSION: Final = "state-laws-source-receipt-reuse-v1"

# These constants deliberately fence recovery/materialization artifacts away
# from the publication-capable source-receipt path.
AUTHORIZES_RECEIPT_FROM_CHECKPOINT: Final = False
REQUIRES_RETAINED_REQUEST_RESPONSE_BODY: Final = True


class StateLawsSourceReceiptReuseError(ValueError):
    """Existing evidence cannot be reused as a canonical source receipt."""


def _required_bytes(value: object, *, name: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise StateLawsSourceReceiptReuseError(
            f"{name} must be retained bytes, not a digest or receipt claim"
        )
    body = bytes(value)
    if not body:
        raise StateLawsSourceReceiptReuseError(f"{name} must be non-empty")
    return body


def qualify_existing_source_receipt(
    receipt: Mapping[str, Any],
    *,
    input_path: str | Path,
    jurisdiction: str,
    release_point: str,
    request_bytes: bytes,
    response_bytes: bytes,
    body_bytes: bytes,
    relative_path: str | None = None,
    catalog: OfficialSourceCatalog | None = None,
    admission_row: Mapping[str, Any] | None = None,
    source_kind: str = "caller",
    source_label: str = "caller",
) -> NormalizedSourceReceipt:
    """Reuse a receipt only when shared byte/frontier and adapter gates agree.

    ``body_bytes`` must be the exact canonical artifact at ``input_path``.
    This prevents a valid inventory receipt (for example a title catalog) from
    being relabeled as evidence for a different, much larger statute corpus.
    The receipt must already contain all fields required by
    :func:`normalize_source_receipt`; this function never infers an official
    URL, acquisition path, release point, verification result, or count.
    """

    if not isinstance(receipt, Mapping):
        raise StateLawsSourceReceiptReuseError("receipt must be a mapping")

    unresolved_target = Path(input_path).expanduser()
    if unresolved_target.is_symlink():
        raise StateLawsSourceReceiptReuseError(
            "input_path must be a regular non-symlink canonical artifact"
        )
    target = unresolved_target.resolve()
    if not target.is_file():
        raise StateLawsSourceReceiptReuseError(
            "input_path must be a regular non-symlink canonical artifact"
        )

    retained_request = _required_bytes(request_bytes, name="request_bytes")
    retained_response = _required_bytes(response_bytes, name="response_bytes")
    retained_body = _required_bytes(body_bytes, name="body_bytes")
    input_digest = file_sha256(target)
    retained_body_digest = hashlib.sha256(retained_body).hexdigest()
    if retained_body_digest != input_digest:
        raise StateLawsSourceReceiptReuseError(
            "retained admitted body does not match the canonical input artifact"
        )

    admission = evaluate_prior_receipt(
        receipt,
        source_kind=source_kind,
        source_label=source_label,
        request_bytes=retained_request,
        response_bytes=retained_response,
        body_bytes=retained_body,
        admission_row=admission_row,
    )
    if not admission.accepted:
        kinds = ",".join(admission.rejection_kinds) or "rejected"
        raise StateLawsSourceReceiptReuseError(
            f"shared acquisition gate rejected receipt ({kinds}): {admission.detail}"
        )
    if admission.byte_verification is None or not (
        admission.byte_verification.ok
        and admission.byte_verification.raw_bytes_checked
    ):
        raise StateLawsSourceReceiptReuseError(
            "shared acquisition gate did not recheck retained bytes"
        )
    if admission.frontier_verification is None or not (
        admission.frontier_verification.ok
        and admission.frontier_verification.closed
        and admission.frontier_verification.replay_matched
    ):
        raise StateLawsSourceReceiptReuseError(
            "shared acquisition gate did not verify a closed replayed frontier"
        )

    input_rows = legacy_input_row_count(target)
    if admission.row_count is None or int(admission.row_count) != input_rows:
        raise StateLawsSourceReceiptReuseError(
            "receipt row count does not match the canonical input artifact: "
            f"receipt={admission.row_count!r} artifact={input_rows}"
        )

    normalized = normalize_source_receipt(
        receipt,
        input_path=target,
        jurisdiction=jurisdiction,
        release_point=release_point,
        relative_path=relative_path,
        catalog=catalog,
    )
    if not normalized.admission_eligible or normalized.qualification_reasons:
        reasons = ",".join(normalized.qualification_reasons) or "ineligible"
        raise StateLawsSourceReceiptReuseError(
            f"canonical source-receipt normalizer rejected receipt ({reasons})"
        )
    if normalized.expected_row_count != input_rows:
        raise StateLawsSourceReceiptReuseError(
            "normalized receipt lacks exact canonical row-count parity"
        )
    if normalized.input_sha256 != input_digest:
        raise StateLawsSourceReceiptReuseError(
            "normalized receipt input digest changed during verification"
        )

    gate_evidence = {
        "accepted": True,
        "byte_verification": admission.byte_verification.to_dict(),
        "canonical_artifact_sha256": input_digest,
        "canonical_row_count": input_rows,
        "frontier_verification": admission.frontier_verification.to_dict(),
        "raw_artifacts_checked": ["request", "response", "body"],
        "schema_version": SCHEMA_VERSION,
        "source_kind": admission.source_kind,
        "source_label": admission.source_label,
    }
    payload = dict(normalized.record.payload)
    payload["shared_acquisition_reuse_gate"] = gate_evidence
    record = replace(normalized.record, payload=payload)
    return replace(normalized, record=record)


__all__ = [
    "AUTHORIZES_RECEIPT_FROM_CHECKPOINT",
    "REQUIRES_RETAINED_REQUEST_RESPONSE_BODY",
    "SCHEMA_VERSION",
    "StateLawsSourceReceiptReuseError",
    "qualify_existing_source_receipt",
]
