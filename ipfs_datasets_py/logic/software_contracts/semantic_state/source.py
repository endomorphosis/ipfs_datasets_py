"""Exact producer-bound raw-source admission (ProducerBoundSource@1).

Retrieves verified source bytes for a stable symbol only through a sealed
snapshot/tree-bound ISI view.  Never reads ambient ``Path`` targets, never
imports target code, and never treats heuristic/capsule text as exact source.

Corrupt, missing, wrong-state, TOCTOU-mismatched, or unavailable source yields a
typed failure that requires rescan.  Successful materializations bind exact
bytes and spans to the expected producer state CID via
:class:`VerifiedSourceEvidence`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Final, Protocol, runtime_checkable

from ipfs_datasets_py.logic.software_contracts.content import (
    ContentIdentityError,
    decode_and_recompute_source,
    validate_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    RepositoryState,
    SourceSpan,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    SemanticStateModelError,
    VerifiedSourceEvidence,
)


# ---------------------------------------------------------------------------
# Interface constants
# ---------------------------------------------------------------------------

PRODUCER_BOUND_SOURCE_INTERFACE: Final[str] = "ProducerBoundSource@1"
PRODUCER_BOUND_SOURCE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-producer-bound-source@1"
)


class SourceAdmissionError(ValueError):
    """Base class for producer-bound source admission failures."""

    kind: str = "source_admission_error"
    requires_rescan: bool = True

    def __init__(self, message: str, *, kind: str | None = None) -> None:
        super().__init__(message)
        if kind is not None:
            self.kind = kind


class SourceUnavailableError(SourceAdmissionError):
    """Source blob or symbol is missing/corrupt and requires rescan."""

    kind = "source_unavailable"
    requires_rescan = True


class SourceBindingMismatchError(SourceAdmissionError):
    """TOCTOU or producer-state binding mismatch; requires rescan."""

    kind = "source_binding_mismatch"
    requires_rescan = True


class SourceWrongStateError(SourceBindingMismatchError):
    """Semantic index state CID does not match expected producer state."""

    kind = "source_wrong_state"


class SourceCorruptError(SourceUnavailableError):
    """Returned bytes fail raw CID reverify."""

    kind = "source_corrupt"


class SourceFailureKind(str, Enum):
    """Closed vocabulary for source admission failure kinds."""

    UNAVAILABLE = "source_unavailable"
    BINDING_MISMATCH = "source_binding_mismatch"
    WRONG_STATE = "source_wrong_state"
    CORRUPT = "source_corrupt"
    MISSING_SYMBOL = "source_missing_symbol"
    MISSING_SOURCE_CID = "source_missing_source_cid"
    MISSING_BLOB = "source_missing_blob"
    SPAN_OUT_OF_RANGE = "source_span_out_of_range"
    UNSAFE_VIEW = "source_unsafe_view"
    INVALID_ARGUMENT = "source_invalid_argument"


@runtime_checkable
class ProducerBoundSourceView(Protocol):
    """Sealed snapshot/tree-bound ISI view used for raw-source admission.

    Implementations must never fall back to ambient filesystem reads.  Blob
    bytes are returned only for CIDs already bound by the sealed producer
    snapshot; callers reverify with :func:`decode_and_recompute_source`.
    """

    @property
    def state_cid(self) -> str: ...

    def symbol(self, stable_symbol_id: str) -> SymbolRecord: ...

    def read_source_blob(self, source_cid: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class SourceSliceRef:
    """Lightweight public reference to a symbol's source slice (no bytes)."""

    stable_symbol_id: str
    source_cid: str
    source_slice_path: str
    span: SourceSpan | None
    extractor_name: str
    extractor_version: str
    producer_state_cid: str

    def to_dict(self) -> dict[str, object]:
        return {
            "stable_symbol_id": self.stable_symbol_id,
            "source_cid": self.source_cid,
            "source_slice_path": self.source_slice_path,
            "span": None if self.span is None else self.span.to_dict(),
            "extractor_name": self.extractor_name,
            "extractor_version": self.extractor_version,
            "producer_state_cid": self.producer_state_cid,
        }


@dataclass(frozen=True, slots=True)
class VerifiedSourceMaterialization:
    """Verified raw source bytes plus serializable evidence.

    Intentionally not a single structured content-identity object: the byte
    payload retains the already-authoritative raw CID while the evidence record
    is serializable DAG-JSON.
    """

    evidence: VerifiedSourceEvidence
    source_bytes: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, VerifiedSourceEvidence):
            raise SourceAdmissionError(
                "evidence must be a VerifiedSourceEvidence",
                kind=SourceFailureKind.INVALID_ARGUMENT.value,
            )
        if type(self.source_bytes) is not bytes:
            raise SourceAdmissionError(
                "source_bytes must be exact bytes",
                kind=SourceFailureKind.INVALID_ARGUMENT.value,
            )
        # Bind bytes to the evidence source CID (TOCTOU closed).
        try:
            decode_and_recompute_source(self.evidence.source_cid, self.source_bytes)
        except ContentIdentityError as exc:
            raise SourceCorruptError(
                f"{SourceFailureKind.CORRUPT.value}: materialization bytes do not "
                f"match evidence source_cid {self.evidence.source_cid}"
            ) from exc
        if self.evidence.end_offset > len(self.source_bytes):
            raise SourceUnavailableError(
                f"{SourceFailureKind.SPAN_OUT_OF_RANGE.value}: end_offset exceeds "
                f"source length {len(self.source_bytes)}"
            )
        if self.evidence.start_offset > self.evidence.end_offset:
            raise SourceUnavailableError(
                f"{SourceFailureKind.SPAN_OUT_OF_RANGE.value}: start_offset after end_offset"
            )

    @property
    def source_cid(self) -> str:
        return self.evidence.source_cid

    @property
    def producer_state_cid(self) -> str:
        return self.evidence.producer_state_cid

    @property
    def stable_symbol_id(self) -> str:
        return self.evidence.stable_symbol_id

    @property
    def span_bytes(self) -> bytes:
        """Exact byte slice for the bound span offsets."""
        return self.source_bytes[
            self.evidence.start_offset : self.evidence.end_offset
        ]

    @property
    def evidence_cid(self) -> str:
        return self.evidence.evidence_cid

    def to_evidence_dict(self) -> dict[str, object]:
        """Return the serializable evidence record (no raw bytes)."""
        return self.evidence.to_dict()


def _state_cid_of(index: object) -> str:
    if hasattr(index, "state_cid"):
        value = index.state_cid  # type: ignore[attr-defined]
        if callable(value):
            value = value()
        if type(value) is str and value:
            return value
    raise SourceWrongStateError(
        f"{SourceFailureKind.WRONG_STATE.value}: semantic_index lacks state_cid"
    )


def _resolve_symbol(index: object, stable_symbol_id: str) -> SymbolRecord:
    if hasattr(index, "symbol") and callable(getattr(index, "symbol")):
        try:
            symbol = index.symbol(stable_symbol_id)  # type: ignore[attr-defined]
        except Exception as exc:
            raise SourceUnavailableError(
                f"{SourceFailureKind.MISSING_SYMBOL.value}: {stable_symbol_id!r}"
            ) from exc
        if not isinstance(symbol, SymbolRecord):
            raise SourceUnavailableError(
                f"{SourceFailureKind.MISSING_SYMBOL.value}: symbol() did not return SymbolRecord"
            )
        if symbol.stable_id != stable_symbol_id:
            raise SourceBindingMismatchError(
                f"{SourceFailureKind.BINDING_MISMATCH.value}: symbol stable_id mismatch"
            )
        return symbol

    symbols = getattr(index, "symbols", None)
    if symbols is None:
        raise SourceUnavailableError(
            f"{SourceFailureKind.UNSAFE_VIEW.value}: semantic_index has no symbols or symbol()"
        )
    try:
        items = list(symbols)
    except Exception as exc:
        raise SourceUnavailableError(
            f"{SourceFailureKind.UNSAFE_VIEW.value}: cannot iterate symbols"
        ) from exc
    match: SymbolRecord | None = None
    for item in items:
        if not isinstance(item, SymbolRecord):
            raise SourceUnavailableError(
                f"{SourceFailureKind.UNSAFE_VIEW.value}: symbols must be SymbolRecord values"
            )
        if item.stable_id == stable_symbol_id:
            if match is not None:
                raise SourceBindingMismatchError(
                    f"{SourceFailureKind.BINDING_MISMATCH.value}: duplicate stable_id"
                )
            match = item
    if match is None:
        raise SourceUnavailableError(
            f"{SourceFailureKind.MISSING_SYMBOL.value}: {stable_symbol_id!r}"
        )
    return match


def _read_blob(
    index: object,
    source_cid: str,
    read_source_blob: Callable[[str], bytes] | None,
) -> bytes:
    """Read raw blob bytes only through the sealed view or injected reader."""
    reader: Callable[[str], bytes] | None = read_source_blob
    if reader is None and hasattr(index, "read_source_blob"):
        method = getattr(index, "read_source_blob")
        if callable(method):
            reader = method
    if reader is None:
        raise SourceUnavailableError(
            f"{SourceFailureKind.UNSAFE_VIEW.value}: no sealed read_source_blob; "
            "ambient Path fallback is forbidden"
        )
    try:
        data = reader(source_cid)
    except SourceAdmissionError:
        raise
    except Exception as exc:
        raise SourceUnavailableError(
            f"{SourceFailureKind.MISSING_BLOB.value}: read_source_blob failed for {source_cid}"
        ) from exc
    if type(data) is not bytes:
        raise SourceCorruptError(
            f"{SourceFailureKind.CORRUPT.value}: read_source_blob must return bytes"
        )
    return data


def line_col_to_byte_offset(source: bytes, line: int, column: int) -> int:
    """Convert 1-based line / 0-based column to a byte offset into ``source``.

    Matches CPython AST span conventions used by the ISI ``SourceSpan``.
    """
    if type(source) is not bytes:
        raise SourceAdmissionError(
            "source must be bytes",
            kind=SourceFailureKind.INVALID_ARGUMENT.value,
        )
    if type(line) is not int or type(column) is not int:
        raise SourceAdmissionError(
            "line and column must be int",
            kind=SourceFailureKind.INVALID_ARGUMENT.value,
        )
    if line < 1 or column < 0:
        raise SourceUnavailableError(
            f"{SourceFailureKind.SPAN_OUT_OF_RANGE.value}: line/column out of range"
        )
    current_line = 1
    offset = 0
    length = len(source)
    while current_line < line:
        nl = source.find(b"\n", offset)
        if nl < 0:
            raise SourceUnavailableError(
                f"{SourceFailureKind.SPAN_OUT_OF_RANGE.value}: line {line} past end of source"
            )
        offset = nl + 1
        current_line += 1
    end = offset + column
    if end > length:
        raise SourceUnavailableError(
            f"{SourceFailureKind.SPAN_OUT_OF_RANGE.value}: column past end of line/source"
        )
    return end


def span_to_byte_offsets(
    source: bytes, span: SourceSpan | None
) -> tuple[int, int]:
    """Return ``(start_offset, end_offset)`` for ``span`` against ``source``.

    When ``span`` is None the full blob is admitted (``0 .. len(source)``).
    """
    if span is None:
        return 0, len(source)
    if not isinstance(span, SourceSpan):
        raise SourceAdmissionError(
            "span must be a SourceSpan or None",
            kind=SourceFailureKind.INVALID_ARGUMENT.value,
        )
    start = line_col_to_byte_offset(source, span.start_line, span.start_column)
    end = line_col_to_byte_offset(source, span.end_line, span.end_column)
    if end < start:
        raise SourceUnavailableError(
            f"{SourceFailureKind.SPAN_OUT_OF_RANGE.value}: span end precedes start"
        )
    return start, end


def source_slice(
    semantic_index: object,
    stable_symbol_id: str,
    *,
    expected_producer_state_cid: str,
) -> SourceSliceRef:
    """Return the public source-slice reference without materializing bytes."""
    if type(stable_symbol_id) is not str or not stable_symbol_id:
        raise SourceAdmissionError(
            "stable_symbol_id must be a nonempty string",
            kind=SourceFailureKind.INVALID_ARGUMENT.value,
        )
    if type(expected_producer_state_cid) is not str or not expected_producer_state_cid:
        raise SourceAdmissionError(
            "expected_producer_state_cid must be a nonempty string",
            kind=SourceFailureKind.INVALID_ARGUMENT.value,
        )
    try:
        expected = validate_cid(expected_producer_state_cid)
    except Exception as exc:
        raise SourceBindingMismatchError(
            f"{SourceFailureKind.BINDING_MISMATCH.value}: invalid expected_producer_state_cid"
        ) from exc

    actual = _state_cid_of(semantic_index)
    try:
        actual_cid = validate_cid(actual)
    except Exception as exc:
        raise SourceWrongStateError(
            f"{SourceFailureKind.WRONG_STATE.value}: invalid semantic_index state_cid"
        ) from exc
    if actual_cid != expected:
        raise SourceWrongStateError(
            f"{SourceFailureKind.WRONG_STATE.value}: state_cid {actual_cid} != "
            f"expected {expected}"
        )

    symbol = _resolve_symbol(semantic_index, stable_symbol_id)
    if symbol.source_cid is None:
        raise SourceUnavailableError(
            f"{SourceFailureKind.MISSING_SOURCE_CID.value}: symbol has no source_cid"
        )
    try:
        source_cid = validate_cid(symbol.source_cid)
    except Exception as exc:
        raise SourceCorruptError(
            f"{SourceFailureKind.CORRUPT.value}: symbol source_cid is invalid"
        ) from exc

    return SourceSliceRef(
        stable_symbol_id=symbol.stable_id,
        source_cid=source_cid,
        source_slice_path=symbol.module_path,
        span=symbol.span,
        extractor_name=symbol.extractor_name,
        extractor_version=symbol.extractor_version,
        producer_state_cid=expected,
    )


def read_source_span(
    source_bytes: bytes,
    span: SourceSpan | None,
    *,
    expected_source_cid: str,
) -> bytes:
    """Return the verified span slice after reverify of full ``source_bytes``."""
    try:
        decode_and_recompute_source(expected_source_cid, source_bytes)
    except ContentIdentityError as exc:
        raise SourceCorruptError(
            f"{SourceFailureKind.CORRUPT.value}: TOCTOU source CID mismatch"
        ) from exc
    start, end = span_to_byte_offsets(source_bytes, span)
    return source_bytes[start:end]


def read_required_source(
    semantic_index: RepositoryState | object,
    stable_symbol_id: str,
    *,
    expected_producer_state_cid: str,
    read_source_blob: Callable[[str], bytes] | None = None,
) -> VerifiedSourceMaterialization:
    """Materialize exact producer-bound source for ``stable_symbol_id``.

    Parameters
    ----------
    semantic_index:
        Sealed ISI view (``RepositoryState`` or duck-typed index / 
        :class:`ProducerBoundSourceView`) whose ``state_cid`` must equal
        ``expected_producer_state_cid``.
    stable_symbol_id:
        Producer stable symbol identity.
    expected_producer_state_cid:
        Authoritative producer repository-state CID the bytes must bind.
    read_source_blob:
        Optional sealed blob reader ``source_cid -> bytes``.  When omitted the
        index must expose ``read_source_blob``.  Ambient ``Path`` fallback is
        never used.

    Returns
    -------
    VerifiedSourceMaterialization
        Evidence plus exact raw bytes.  Span offsets bind the symbol span when
        present, otherwise the full blob.

    Raises
    ------
    SourceWrongStateError
        Index state does not match the expected producer state.
    SourceBindingMismatchError
        Symbol/CID identity does not bind.
    SourceUnavailableError / SourceCorruptError
        Missing, corrupt, or TOCTOU-mismatched bytes — requires rescan.
    """
    slice_ref = source_slice(
        semantic_index,
        stable_symbol_id,
        expected_producer_state_cid=expected_producer_state_cid,
    )

    # First read.
    data = _read_blob(semantic_index, slice_ref.source_cid, read_source_blob)

    # Reverify raw CID (decode-and-recompute) — primary TOCTOU gate.
    try:
        verified_cid = decode_and_recompute_source(slice_ref.source_cid, data)
    except ContentIdentityError as exc:
        raise SourceCorruptError(
            f"{SourceFailureKind.CORRUPT.value}: source bytes do not match "
            f"source_cid {slice_ref.source_cid} (TOCTOU/mismatch); rescan required"
        ) from exc

    # Second read when the view supports it — detect races between check and use.
    if hasattr(semantic_index, "read_source_blob") or read_source_blob is not None:
        data_again = _read_blob(semantic_index, slice_ref.source_cid, read_source_blob)
        if data_again != data:
            raise SourceBindingMismatchError(
                f"{SourceFailureKind.BINDING_MISMATCH.value}: TOCTOU source bytes changed "
                f"between reads for {slice_ref.source_cid}; rescan required"
            )
        try:
            decode_and_recompute_source(verified_cid, data_again)
        except ContentIdentityError as exc:
            raise SourceCorruptError(
                f"{SourceFailureKind.CORRUPT.value}: second-read CID reverify failed"
            ) from exc
        data = data_again

    try:
        start, end = span_to_byte_offsets(data, slice_ref.span)
    except SourceAdmissionError:
        raise
    except Exception as exc:
        raise SourceUnavailableError(
            f"{SourceFailureKind.SPAN_OUT_OF_RANGE.value}: cannot bind span"
        ) from exc

    # Path consistency: when span is present, span.path must match module path.
    if slice_ref.span is not None and slice_ref.span.path != slice_ref.source_slice_path:
        raise SourceBindingMismatchError(
            f"{SourceFailureKind.BINDING_MISMATCH.value}: span.path "
            f"{slice_ref.span.path!r} != module_path {slice_ref.source_slice_path!r}"
        )

    try:
        evidence = VerifiedSourceEvidence(
            stable_symbol_id=slice_ref.stable_symbol_id,
            producer_state_cid=slice_ref.producer_state_cid,
            source_cid=verified_cid,
            source_slice_path=slice_ref.source_slice_path,
            start_offset=start,
            end_offset=end,
            extractor_name=slice_ref.extractor_name,
            extractor_version=slice_ref.extractor_version,
        )
    except SemanticStateModelError as exc:
        raise SourceBindingMismatchError(
            f"{SourceFailureKind.BINDING_MISMATCH.value}: evidence construction failed: {exc}"
        ) from exc

    return VerifiedSourceMaterialization(evidence=evidence, source_bytes=data)


__all__ = [
    "PRODUCER_BOUND_SOURCE_INTERFACE",
    "PRODUCER_BOUND_SOURCE_SCHEMA",
    "ProducerBoundSourceView",
    "SourceAdmissionError",
    "SourceBindingMismatchError",
    "SourceCorruptError",
    "SourceFailureKind",
    "SourceSliceRef",
    "SourceUnavailableError",
    "SourceWrongStateError",
    "VerifiedSourceMaterialization",
    "line_col_to_byte_offset",
    "read_required_source",
    "read_source_span",
    "source_slice",
    "span_to_byte_offsets",
]
