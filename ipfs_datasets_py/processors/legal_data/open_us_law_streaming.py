"""Streaming chunking, jurisdiction checkpoints, and external sort (OUL-025).

Data-independent substrate for corpus-scale Open US Law builders. It
streams structure-aware chunks, spills and merges sorted runs under a
memory bound, and checkpoints work per jurisdiction so a clean resume is
byte-deterministic.

This module proves the reusable software contract only. Fixtures and a
green test run never authorize the exact-51 corpus, a live scrape, or
publication. Production materialization remains gated by OUL-024.

Design invariants
-----------------
* Builders never require the full document, posting, or embedding set in
  RAM. Resident records are bounded by the configured run size / merge
  fan-in.
* Structure-aware chunks obey the pinned GTE token ceiling (512). The
  4,096 value is a physical shard/row bound, never an implicit token
  limit.
* Checkpoints bind ``config_digest`` and are written atomically. Stale or
  config-mismatched checkpoints fail closed. Partial checkpoints cannot
  be sealed or promoted to success.
* External sort spills sorted runs and k-way merges them. Clean resumes
  replay the same spill/merge plan and emit identical output bytes.
* No network I/O. Placeholder vector/posting records are fixture-only
  and cannot authorize production embeddings or BM25.
"""

from __future__ import annotations

import heapq
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
    Final,
    Iterable,
    Iterator,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Union,
)

from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_MODEL_TOKEN_CEILING,
    DocumentKind,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    build_legal_id,
    canonical_json_dumps,
    digest_mapping,
    normalize_jurisdiction_code,
)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "open-us-law-streaming-v1"
SORT_CHECKPOINT_SCHEMA_VERSION: Final = "open-us-law-external-sort-v1"
TASK_ID: Final = "OUL-025"
GOAL_ID: Final = "OUL-G030"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "open_us_law_streaming.py"
RELEASE_PROFILE: Final = "open-us-law-sparse-graphrag/v1"
ADR_PATH: Final = "docs/architecture/OPEN_US_LAW_REINDEX_PLAN.md"

CHECKPOINT_FILENAME: Final = "streaming_checkpoint.json"
SEAL_FILENAME: Final = "streaming_seal.json"
RECEIPT_FILENAME: Final = "streaming_receipt.json"
SORT_CHECKPOINT_FILENAME: Final = "sort_checkpoint.json"

DEFAULT_MODEL_TOKEN_LIMIT: Final = DEFAULT_MODEL_TOKEN_CEILING
DEFAULT_OVERLAP_TOKENS: Final = 32
DEFAULT_MAX_CHUNKS_PER_SECTION: Final = 512
DEFAULT_TOKENIZER_ID: Final = "open-us-law-whitespace-v1"
DEFAULT_MAX_RECORDS_IN_MEMORY: Final = 256
DEFAULT_MERGE_FAN_IN: Final = 32
DEFAULT_CODE_FAMILY: Final = "statutes"
DEFAULT_EDITION: Final = "fixture-v1"
DEFAULT_CONFIGURATION: Final = "state_statutes_exact_51"

DEFAULT_FAMILIES: Final = (
    "chunks",
    "documents",
    "postings",
    "vectors",
)

AUTHORIZES_EXACT_51_CORPUS: Final = False
AUTHORIZES_PUBLICATION: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True

_SUBSEC_MARKER_RE = re.compile(r"\(([0-9A-Za-z]{1,6})\)")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")
_TOKEN_RE = re.compile(r"\S+")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMON_ROMAN_LOWER = frozenset(
    {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"}
)
_COMMON_ROMAN_UPPER = frozenset(s.upper() for s in _COMMON_ROMAN_LOWER)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]
KeyFn = Callable[[Mapping[str, Any]], Any]
DocumentSource = Callable[[str], Iterable[Any]]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OpenUsLawStreamingError(ValueError):
    """Base error for the streaming substrate."""

    code: str = "open_us_law_streaming_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class StreamingConfigError(OpenUsLawStreamingError):
    """Raised when streaming configuration is invalid."""

    code = "streaming_config_invalid"


class StreamingCheckpointError(OpenUsLawStreamingError):
    """Raised when a checkpoint is corrupt, stale, or config-mismatched."""

    code = "checkpoint_invalid"


class ExternalSortError(OpenUsLawStreamingError):
    """Raised when spill/merge cannot complete under the contract."""

    code = "external_sort_failed"


class MemoryBudgetError(OpenUsLawStreamingError):
    """Raised when a builder would exceed the resident-record bound."""

    code = "memory_budget_exceeded"


class SealError(OpenUsLawStreamingError):
    """Raised when sealing is attempted on incomplete work."""

    code = "seal_rejected"


class PartialCheckpointPromotionError(SealError):
    """Raised when a partial checkpoint is treated as success."""

    code = "partial_checkpoint_promoted"


class Exact51AuthorizationError(OpenUsLawStreamingError):
    """Raised when this substrate is asked to authorize exact-51 completion."""

    code = "exact_51_authorization_rejected"


class ProducerError(OpenUsLawStreamingError):
    """Raised when a delegated family producer fails."""

    code = "producer_failed"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StreamingConfigError(f"{name} must be a non-empty string")
    text = value.strip()
    if len(text) > maximum:
        raise StreamingConfigError(f"{name} exceeds maximum length {maximum}")
    return text


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StreamingConfigError(f"{name} must be an integer")
    if value < 0:
        raise StreamingConfigError(f"{name} must be >= 0")
    return value


def _require_positive_int(value: Any, name: str) -> int:
    number = _require_non_negative_int(value, name)
    if number < 1:
        raise StreamingConfigError(f"{name} must be >= 1")
    return number


def canonical_json_bytes(payload: Any) -> bytes:
    return canonical_json_dumps(payload).encode("utf-8")


def file_sha256(path: PathLike) -> str:
    target = Path(path)
    hasher = hashlib.sha256()
    with target.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()


def write_bytes_atomic(path: PathLike, data: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".oul-stream-",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


def write_json_atomic(path: PathLike, payload: Mapping[str, Any]) -> Path:
    """Write *payload* as sorted JSON via temp file + ``os.replace``."""

    text = json.dumps(
        dict(payload),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    return write_bytes_atomic(path, text.encode("utf-8"))


def load_json_mapping(path: PathLike) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        raise StreamingCheckpointError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StreamingCheckpointError(f"invalid JSON at {target}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise StreamingCheckpointError(f"JSON root must be a mapping: {target}")
    return dict(payload)


def iter_jsonl(path: PathLike) -> Iterator[dict[str, Any]]:
    """Yield records from a JSONL file without loading the file into RAM."""

    target = Path(path)
    if not target.is_file():
        raise ExternalSortError(f"JSONL file not found: {target}")
    with target.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ExternalSortError(
                    f"invalid JSONL at {target}:{line_no}: {exc}"
                ) from exc
            if not isinstance(payload, Mapping):
                raise ExternalSortError(
                    f"JSONL record at {target}:{line_no} must be a mapping"
                )
            yield dict(payload)


@dataclass(frozen=True, slots=True)
class JsonlWriteResult:
    path: str
    row_count: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "row_count": self.row_count,
            "sha256": self.sha256,
        }


def write_jsonl_atomic(
    path: PathLike,
    records: Iterable[Mapping[str, Any]],
) -> JsonlWriteResult:
    """Stream *records* to *path* as canonical JSONL (temp file + replace)."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    count = 0
    fd, tmp_name = tempfile.mkstemp(
        prefix=".oul-stream-",
        suffix=".jsonl",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for record in records:
                if not isinstance(record, Mapping):
                    raise ExternalSortError("JSONL records must be mappings")
                line = canonical_json_dumps(dict(record)) + "\n"
                handle.write(line)
                hasher.update(line.encode("utf-8"))
                count += 1
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return JsonlWriteResult(path=str(target), row_count=count, sha256=hasher.hexdigest())


def estimate_record_bytes(record: Mapping[str, Any]) -> int:
    return len(canonical_json_bytes(dict(record)))


def work_unit_key(jurisdiction: str, family: str) -> str:
    return f"{_normalize_jurisdiction(jurisdiction)}/{_normalize_family(family)}"


def _normalize_family(value: Any) -> str:
    text = _require_non_empty_str(value, "family", maximum=64).lower().replace("-", "_")
    aliases = {
        "chunk": "chunks",
        "corpus": "chunks",
        "document": "documents",
        "docs": "documents",
        "posting": "postings",
        "bm25": "postings",
        "embedding": "vectors",
        "embeddings": "vectors",
        "vector": "vectors",
    }
    return aliases.get(text, text)


def _normalize_jurisdiction(value: Any) -> str:
    return normalize_jurisdiction_code(value, allow_non_default=True)


def _normalize_families(values: Sequence[str] | None) -> tuple[str, ...]:
    families = tuple(
        _normalize_family(item) for item in (values or DEFAULT_FAMILIES)
    )
    if not families:
        raise StreamingConfigError("families must be non-empty")
    seen: set[str] = set()
    ordered: list[str] = []
    for family in families:
        if family not in seen:
            seen.add(family)
            ordered.append(family)
    return tuple(ordered)


def _normalize_jurisdictions(values: Sequence[str]) -> tuple[str, ...]:
    if not values:
        raise StreamingConfigError("jurisdictions must be non-empty")
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in values:
        code = _normalize_jurisdiction(raw)
        if code not in seen:
            seen.add(code)
            ordered.append(code)
    return tuple(ordered)


# ---------------------------------------------------------------------------
# Software-contract gate
# ---------------------------------------------------------------------------


def authorizing_for_exact_51_corpus() -> bool:
    """This substrate never certifies exact-51 acquisition."""

    return AUTHORIZES_EXACT_51_CORPUS


def reject_exact_51_authorization(
    claim: Any = True,
    *,
    reason: str = "streaming substrate proves the software contract only",
) -> None:
    """Fail closed when a caller tries to promote this work to exact-51 proof."""

    if claim:
        raise Exact51AuthorizationError(
            "OUL-025 cannot authorize the exact-51 corpus or a release: "
            f"{reason}"
        )


def software_contract_flags() -> dict[str, Any]:
    return {
        "authorizing_for_exact_51": AUTHORIZES_EXACT_51_CORPUS,
        "authorizing_for_publication": AUTHORIZES_PUBLICATION,
        "proves_software_contract_only": PROVES_SOFTWARE_CONTRACT_ONLY,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
    }


def assert_software_contract_only(receipt: Mapping[str, Any]) -> None:
    """Fail closed when a receipt claims exact-51 or publication authority."""

    if receipt.get("authorizing_for_exact_51"):
        raise Exact51AuthorizationError(
            "receipt authorizing_for_exact_51 must be false"
        )
    if receipt.get("authorizing_for_publication"):
        raise Exact51AuthorizationError(
            "receipt authorizing_for_publication must be false"
        )
    if receipt.get("proves_software_contract_only") is False:
        raise Exact51AuthorizationError(
            "receipt must declare proves_software_contract_only=true"
        )


# ---------------------------------------------------------------------------
# Memory budget
# ---------------------------------------------------------------------------


@dataclass
class MemoryBudget:
    """Resident-record / resident-byte bound for streaming builders.

    The budget tracks sorter- and chunker-internal residency. A consumer
    that later materializes the full iterator is outside this bound.
    """

    max_resident_records: int = DEFAULT_MAX_RECORDS_IN_MEMORY
    max_resident_bytes: Optional[int] = None
    resident_records: int = 0
    resident_bytes: int = 0
    peak_resident_records: int = 0
    peak_resident_bytes: int = 0

    def __post_init__(self) -> None:
        self.max_resident_records = _require_positive_int(
            self.max_resident_records, "max_resident_records"
        )
        if self.max_resident_bytes is not None:
            self.max_resident_bytes = _require_positive_int(
                self.max_resident_bytes, "max_resident_bytes"
            )
        self.resident_records = _require_non_negative_int(
            self.resident_records, "resident_records"
        )
        self.resident_bytes = _require_non_negative_int(
            self.resident_bytes, "resident_bytes"
        )
        self.peak_resident_records = max(
            self.peak_resident_records, self.resident_records
        )
        self.peak_resident_bytes = max(self.peak_resident_bytes, self.resident_bytes)

    def acquire(self, records: int = 1, nbytes: int = 0) -> None:
        next_records = self.resident_records + _require_non_negative_int(
            records, "records"
        )
        next_bytes = self.resident_bytes + _require_non_negative_int(nbytes, "nbytes")
        if next_records > self.max_resident_records:
            raise MemoryBudgetError(
                f"resident records {next_records} exceed "
                f"max_resident_records={self.max_resident_records}"
            )
        if (
            self.max_resident_bytes is not None
            and next_bytes > self.max_resident_bytes
        ):
            raise MemoryBudgetError(
                f"resident bytes {next_bytes} exceed "
                f"max_resident_bytes={self.max_resident_bytes}"
            )
        self.resident_records = next_records
        self.resident_bytes = next_bytes
        if next_records > self.peak_resident_records:
            self.peak_resident_records = next_records
        if next_bytes > self.peak_resident_bytes:
            self.peak_resident_bytes = next_bytes

    def release(self, records: int = 1, nbytes: int = 0) -> None:
        self.resident_records = max(
            0, self.resident_records - _require_non_negative_int(records, "records")
        )
        self.resident_bytes = max(
            0, self.resident_bytes - _require_non_negative_int(nbytes, "nbytes")
        )

    def check_materialize(self, total_records: int) -> None:
        if total_records > self.max_resident_records:
            raise MemoryBudgetError(
                f"refusing to materialize {total_records} records under "
                f"max_resident_records={self.max_resident_records}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_resident_bytes": self.max_resident_bytes,
            "max_resident_records": self.max_resident_records,
            "peak_resident_bytes": self.peak_resident_bytes,
            "peak_resident_records": self.peak_resident_records,
            "resident_bytes": self.resident_bytes,
            "resident_records": self.resident_records,
        }


def materialize_records(
    records: Iterable[Mapping[str, Any]],
    *,
    budget: MemoryBudget,
) -> list[dict[str, Any]]:
    """Materialize an iterator only when it fits the budget (fail-closed)."""

    collected: list[dict[str, Any]] = []
    for record in records:
        nbytes = estimate_record_bytes(record)
        budget.acquire(1, nbytes)
        collected.append(dict(record))
    return collected


# ---------------------------------------------------------------------------
# Structure-aware streaming chunker
# ---------------------------------------------------------------------------


class SplitMode(str, Enum):
    STRUCTURE = "structure"
    SENTENCE = "sentence"
    HARD = "hard"
    WHOLE = "whole"


@dataclass(frozen=True, slots=True)
class TokenSpan:
    index: int
    char_start: int
    char_end: int
    text: str


def normalize_chunk_text(text: str) -> str:
    if not isinstance(text, str):
        raise OpenUsLawStreamingError("text must be a string")
    if "\x00" in text:
        raise OpenUsLawStreamingError("text must not contain NUL")
    return unicodedata.normalize("NFKC", text)


def tokenize(text: str) -> list[TokenSpan]:
    if not isinstance(text, str):
        raise OpenUsLawStreamingError("text must be a string")
    spans: list[TokenSpan] = []
    for index, match in enumerate(_TOKEN_RE.finditer(text)):
        spans.append(
            TokenSpan(
                index=index,
                char_start=match.start(),
                char_end=match.end(),
                text=match.group(0),
            )
        )
    return spans


def count_tokens(text: str) -> int:
    return len(tokenize(text))


def validate_model_token_limit(model_token_limit: Any) -> int:
    """Require an explicit positive model token ceiling.

    Rejects ``None``. The 4,096-row shard bound is never an implicit
    default; callers that truly want 4,096 tokens must pass it explicitly.
    """

    if model_token_limit is None:
        raise StreamingConfigError(
            "model_token_limit is required; pass the selected embedding "
            "model's maximum input tokens explicitly (default is "
            f"{DEFAULT_MODEL_TOKEN_LIMIT}, not the "
            f"{MAX_ROWS_PER_PHYSICAL_SHARD}-row storage bound)"
        )
    try:
        value = int(model_token_limit)
    except (TypeError, ValueError) as exc:
        raise StreamingConfigError(
            f"model_token_limit must be a positive integer, got {model_token_limit!r}"
        ) from exc
    if value < 1:
        raise StreamingConfigError(f"model_token_limit must be >= 1, got {value}")
    return value


def _classify_marker_kind(token: str) -> str:
    if token.isdigit():
        return "paragraph"
    if len(token) == 1 and token.isalpha() and token.isupper():
        return "subparagraph"
    if token in _COMMON_ROMAN_UPPER:
        return "subclause"
    if token in _COMMON_ROMAN_LOWER or (
        token.isalpha() and token.islower() and len(token) > 1
    ):
        return "clause"
    if len(token) == 1 and token.isalpha() and token.islower():
        return "subsection"
    return "other"


def find_structural_markers(text: str) -> list[tuple[int, int, str, str]]:
    markers: list[tuple[int, int, str, str]] = []
    for match in _SUBSEC_MARKER_RE.finditer(text):
        token = match.group(1)
        markers.append((match.start(), match.end(), token, _classify_marker_kind(token)))
    return markers


def _sentence_spans(text: str, abs_start: int) -> list[tuple[int, int]]:
    if not text:
        return []
    boundaries = list(_SENTENCE_BOUNDARY_RE.finditer(text))
    if not boundaries:
        if "\n" in text:
            spans: list[tuple[int, int]] = []
            cursor = 0
            for line in text.splitlines(keepends=True):
                spans.append((abs_start + cursor, abs_start + cursor + len(line)))
                cursor += len(line)
            return spans or [(abs_start, abs_start + len(text))]
        return [(abs_start, abs_start + len(text))]
    spans = []
    last = 0
    for match in boundaries:
        end = match.end()
        if end > last:
            spans.append((abs_start + last, abs_start + end))
        last = match.end()
    if last < len(text):
        spans.append((abs_start + last, abs_start + len(text)))
    return spans


def _token_count_in_span(
    tokens: Sequence[TokenSpan], char_start: int, char_end: int
) -> int:
    return sum(1 for tok in tokens if tok.char_end > char_start and tok.char_start < char_end)


def _hard_windows(
    tokens: Sequence[TokenSpan],
    *,
    char_start: int,
    char_end: int,
    model_token_limit: int,
) -> list[tuple[int, int, str]]:
    selected = [
        tok
        for tok in tokens
        if tok.char_end > char_start and tok.char_start < char_end
    ]
    if not selected:
        return [(char_start, char_end, SplitMode.HARD.value)]
    pieces: list[tuple[int, int, str]] = []
    index = 0
    while index < len(selected):
        end_index = min(index + model_token_limit, len(selected))
        window_start = char_start if index == 0 else selected[index].char_start
        window_end = (
            char_end if end_index >= len(selected) else selected[end_index].char_start
        )
        pieces.append((window_start, window_end, SplitMode.HARD.value))
        index = end_index
    return pieces


def _exclusive_pieces(
    source: str,
    tokens: Sequence[TokenSpan],
    model_token_limit: int,
) -> list[tuple[int, int, str]]:
    if _token_count_in_span(tokens, 0, len(source)) <= model_token_limit:
        return [(0, len(source), SplitMode.WHOLE.value)]

    markers = find_structural_markers(source)
    units: list[tuple[int, int, str]] = []
    if markers:
        if markers[0][0] > 0:
            units.append((0, markers[0][0], SplitMode.STRUCTURE.value))
        for idx, (start, _end, _token, _kind) in enumerate(markers):
            next_start = markers[idx + 1][0] if idx + 1 < len(markers) else len(source)
            units.append((start, next_start, SplitMode.STRUCTURE.value))
    else:
        units.append((0, len(source), SplitMode.WHOLE.value))

    pieces: list[tuple[int, int, str]] = []
    for start, end, mode in units:
        if _token_count_in_span(tokens, start, end) <= model_token_limit:
            pieces.append((start, end, mode))
            continue
        fragment = source[start:end]
        sentences = _sentence_spans(fragment, start)
        if len(sentences) > 1:
            for s_start, s_end in sentences:
                if _token_count_in_span(tokens, s_start, s_end) <= model_token_limit:
                    pieces.append((s_start, s_end, SplitMode.SENTENCE.value))
                else:
                    pieces.extend(
                        _hard_windows(
                            tokens,
                            char_start=s_start,
                            char_end=s_end,
                            model_token_limit=model_token_limit,
                        )
                    )
        else:
            pieces.extend(
                _hard_windows(
                    tokens,
                    char_start=start,
                    char_end=end,
                    model_token_limit=model_token_limit,
                )
            )

    repaired: list[tuple[int, int, str]] = []
    cursor = 0
    for start, end, mode in pieces:
        if start > cursor:
            repaired.append((cursor, start, SplitMode.HARD.value))
        if end > start:
            repaired.append((start, end, mode))
            cursor = end
    if cursor < len(source):
        repaired.append((cursor, len(source), SplitMode.HARD.value))
    return repaired or [(0, len(source), SplitMode.WHOLE.value)]


def _pack_pieces(
    pieces: Sequence[tuple[int, int, str]],
    tokens: Sequence[TokenSpan],
    model_token_limit: int,
) -> list[list[tuple[int, int, str]]]:
    groups: list[list[tuple[int, int, str]]] = []
    current: list[tuple[int, int, str]] = []
    current_tokens = 0
    for piece in pieces:
        n_tokens = _token_count_in_span(tokens, piece[0], piece[1])
        if n_tokens > model_token_limit:
            if current:
                groups.append(current)
                current = []
                current_tokens = 0
            groups.append([piece])
            continue
        if current and current_tokens + n_tokens > model_token_limit:
            groups.append(current)
            current = []
            current_tokens = 0
        current.append(piece)
        current_tokens += n_tokens
    if current:
        groups.append(current)
    return groups


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_cid(label: str) -> str:
    return _sha256_hex(label)


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """One streamed statutory document. Never a completeness receipt."""

    jurisdiction_code: str
    text: str
    title: str = "1"
    chapter: str = "1"
    section: str = "1"
    subsection: str = ""
    edition: str = DEFAULT_EDITION
    code_family: str = DEFAULT_CODE_FAMILY
    document_index: int = 0
    heading: str = ""
    source_cid: str = ""
    entry_cid: str = ""
    legal_id: str = ""

    def normalized(self) -> "SourceDocument":
        jurisdiction = _normalize_jurisdiction(self.jurisdiction_code)
        text = normalize_chunk_text(self.text)
        hierarchy = {
            "title": self.title or "1",
            "chapter": self.chapter or "1",
            "section": self.section or str(self.document_index + 1),
        }
        if self.subsection:
            hierarchy["subsection"] = self.subsection
        legal_id = self.legal_id or build_legal_id(
            document_kind=DocumentKind.STATUTE,
            jurisdiction_code=jurisdiction,
            code_family=self.code_family or DEFAULT_CODE_FAMILY,
            hierarchy=hierarchy,
            edition=self.edition or DEFAULT_EDITION,
        )
        source_cid = self.source_cid or _stable_cid(f"source:{legal_id}:{text}")
        entry_cid = self.entry_cid or _stable_cid(f"entry:{legal_id}")
        return SourceDocument(
            jurisdiction_code=jurisdiction,
            text=text,
            title=str(hierarchy["title"]),
            chapter=str(hierarchy["chapter"]),
            section=str(hierarchy["section"]),
            subsection=self.subsection,
            edition=self.edition or DEFAULT_EDITION,
            code_family=self.code_family or DEFAULT_CODE_FAMILY,
            document_index=_require_non_negative_int(
                self.document_index, "document_index"
            ),
            heading=self.heading,
            source_cid=source_cid,
            entry_cid=entry_cid,
            legal_id=legal_id,
        )

    def to_dict(self) -> dict[str, Any]:
        doc = self.normalized()
        return {
            "chapter": doc.chapter,
            "code_family": doc.code_family,
            "document_index": doc.document_index,
            "edition": doc.edition,
            "entry_cid": doc.entry_cid,
            "heading": doc.heading,
            "jurisdiction_code": doc.jurisdiction_code,
            "legal_id": doc.legal_id,
            "section": doc.section,
            "source_cid": doc.source_cid,
            "subsection": doc.subsection,
            "text": doc.text,
            "title": doc.title,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "SourceDocument":
        if isinstance(value, SourceDocument):
            return value.normalized()
        if not isinstance(value, Mapping):
            raise StreamingConfigError("document must be a mapping")
        hierarchy = value.get("hierarchy") if isinstance(value.get("hierarchy"), Mapping) else {}
        return cls(
            jurisdiction_code=str(value.get("jurisdiction_code") or value.get("jurisdiction") or ""),
            text=str(value.get("text") or ""),
            title=str(value.get("title") or hierarchy.get("title") or "1"),
            chapter=str(value.get("chapter") or hierarchy.get("chapter") or "1"),
            section=str(value.get("section") or hierarchy.get("section") or "1"),
            subsection=str(value.get("subsection") or hierarchy.get("subsection") or ""),
            edition=str(value.get("edition") or DEFAULT_EDITION),
            code_family=str(value.get("code_family") or DEFAULT_CODE_FAMILY),
            document_index=int(value.get("document_index") or 0),
            heading=str(value.get("heading") or ""),
            source_cid=str(value.get("source_cid") or ""),
            entry_cid=str(value.get("entry_cid") or ""),
            legal_id=str(value.get("legal_id") or ""),
        ).normalized()


@dataclass(frozen=True, slots=True)
class LegalTextChunk:
    chunk_index: int
    char_start: int
    char_end: int
    token_start: int
    token_end: int
    token_count: int
    exclusive_text: str
    text: str
    split_mode: str
    parent_path: tuple[str, ...]
    legal_id: str
    parent_legal_id: str
    entry_cid: str
    source_cid: str
    chunk_cid: str
    jurisdiction_code: str
    document_index: int
    model_token_limit: int
    tokenizer_id: str
    limit_exempt: bool = False
    heading: str = ""
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "char_end": self.char_end,
            "char_start": self.char_start,
            "chunk_cid": self.chunk_cid,
            "chunk_index": self.chunk_index,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "exclusive_text": self.exclusive_text,
            "heading": self.heading,
            "jurisdiction_code": self.jurisdiction_code,
            "legal_id": self.legal_id,
            "limit_exempt": self.limit_exempt,
            "model_token_limit": self.model_token_limit,
            "parent_legal_id": self.parent_legal_id,
            "parent_path": list(self.parent_path),
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "split_mode": self.split_mode,
            "text": self.text,
            "token_count": self.token_count,
            "token_end": self.token_end,
            "token_start": self.token_start,
            "tokenizer_id": self.tokenizer_id,
        }


@dataclass(frozen=True, slots=True)
class ChunkingResult:
    chunks: tuple[LegalTextChunk, ...]
    source_text: str
    source_token_count: int
    model_token_limit: int
    overlap_tokens: int
    max_chunks_per_section: int
    truncated: bool
    tokenizer_id: str
    parent_legal_id: str
    legal_id: str
    document_index: int
    jurisdiction_code: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_count": len(self.chunks),
            "chunks": [chunk.to_dict() for chunk in self.chunks],
            "document_index": self.document_index,
            "jurisdiction_code": self.jurisdiction_code,
            "legal_id": self.legal_id,
            "max_chunks_per_section": self.max_chunks_per_section,
            "model_token_limit": self.model_token_limit,
            "overlap_tokens": self.overlap_tokens,
            "parent_legal_id": self.parent_legal_id,
            "source_text": self.source_text,
            "source_token_count": self.source_token_count,
            "tokenizer_id": self.tokenizer_id,
            "truncated": self.truncated,
        }


def reconstruct_text(chunks: Sequence[LegalTextChunk | Mapping[str, Any]]) -> str:
    records: list[tuple[int, int, str]] = []
    for chunk in chunks:
        if isinstance(chunk, LegalTextChunk):
            records.append((chunk.char_start, chunk.char_end, chunk.exclusive_text))
        else:
            records.append(
                (
                    int(chunk["char_start"]),
                    int(chunk["char_end"]),
                    str(chunk["exclusive_text"]),
                )
            )
    records.sort(key=lambda item: item[0])
    return "".join(text for _, _, text in records)


def assert_exact_reconstruction(
    source_text: str,
    chunks: Sequence[LegalTextChunk | Mapping[str, Any]],
) -> str:
    rebuilt = reconstruct_text(chunks)
    if rebuilt != source_text:
        raise OpenUsLawStreamingError(
            "exact text reconstruction failed: "
            f"source_len={len(source_text)} rebuilt_len={len(rebuilt)}"
        )
    return rebuilt


def assert_chunks_within_limit(
    chunks: Sequence[LegalTextChunk | Mapping[str, Any]],
    model_token_limit: int,
) -> None:
    limit = validate_model_token_limit(model_token_limit)
    for chunk in chunks:
        if isinstance(chunk, LegalTextChunk):
            exempt = chunk.limit_exempt
            embed_count = count_tokens(chunk.text)
            token_count = chunk.token_count
            idx = chunk.chunk_index
        else:
            exempt = bool(chunk.get("limit_exempt", False))
            embed_count = count_tokens(str(chunk.get("text") or ""))
            token_count = int(chunk.get("token_count") or 0)
            idx = chunk.get("chunk_index")
        if exempt:
            continue
        if embed_count > limit or token_count > limit:
            raise OpenUsLawStreamingError(
                f"non-exempt chunk {idx} exceeds model_token_limit={limit}: "
                f"embed_tokens={embed_count} exclusive_tokens={token_count}"
            )


class OpenUsLawChunker:
    """Structure-aware chunker with an explicit model token ceiling."""

    def __init__(
        self,
        *,
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
        max_chunks_per_section: int = DEFAULT_MAX_CHUNKS_PER_SECTION,
        tokenizer_id: str = DEFAULT_TOKENIZER_ID,
    ) -> None:
        if not isinstance(overlap_tokens, int) or overlap_tokens < 0:
            raise StreamingConfigError("overlap_tokens must be a non-negative integer")
        if not isinstance(max_chunks_per_section, int) or max_chunks_per_section < 1:
            raise StreamingConfigError("max_chunks_per_section must be >= 1")
        if not isinstance(tokenizer_id, str) or not tokenizer_id.strip():
            raise StreamingConfigError("tokenizer_id must be a non-empty string")
        self.overlap_tokens = overlap_tokens
        self.max_chunks_per_section = max_chunks_per_section
        self.tokenizer_id = tokenizer_id.strip()

    def chunk_document(
        self,
        document: SourceDocument | Mapping[str, Any],
        *,
        model_token_limit: int = DEFAULT_MODEL_TOKEN_LIMIT,
        overlap_tokens: Optional[int] = None,
        max_chunks_per_section: Optional[int] = None,
    ) -> ChunkingResult:
        doc = SourceDocument.from_mapping(document)
        limit = validate_model_token_limit(model_token_limit)
        overlap = self.overlap_tokens if overlap_tokens is None else overlap_tokens
        if not isinstance(overlap, int) or overlap < 0:
            raise StreamingConfigError("overlap_tokens must be a non-negative integer")
        max_chunks = (
            self.max_chunks_per_section
            if max_chunks_per_section is None
            else max_chunks_per_section
        )
        if not isinstance(max_chunks, int) or max_chunks < 1:
            raise StreamingConfigError("max_chunks_per_section must be >= 1")
        if overlap >= limit:
            overlap = max(0, limit - 1)

        source = doc.text
        tokens = tokenize(source)
        parent_path = (
            f"jurisdiction:{doc.jurisdiction_code}",
            f"title:{doc.title}",
            f"section:{doc.section}",
        )
        if source == "":
            return ChunkingResult(
                chunks=(),
                source_text=source,
                source_token_count=0,
                model_token_limit=limit,
                overlap_tokens=overlap,
                max_chunks_per_section=max_chunks,
                truncated=False,
                tokenizer_id=self.tokenizer_id,
                parent_legal_id=doc.legal_id,
                legal_id=doc.legal_id,
                document_index=doc.document_index,
                jurisdiction_code=doc.jurisdiction_code,
            )

        pieces = _exclusive_pieces(source, tokens, limit)
        groups = _pack_pieces(pieces, tokens, limit)
        truncated = False
        if len(groups) > max_chunks:
            groups = groups[:max_chunks]
            truncated = True

        chunks: list[LegalTextChunk] = []
        for index, group in enumerate(groups):
            char_start = group[0][0]
            char_end = group[-1][1]
            exclusive = source[char_start:char_end]
            exclusive_tokens = [
                tok
                for tok in tokens
                if tok.char_end > char_start and tok.char_start < char_end
            ]
            token_start = exclusive_tokens[0].index if exclusive_tokens else 0
            token_end = (exclusive_tokens[-1].index + 1) if exclusive_tokens else 0
            embed_text = exclusive
            if index > 0 and overlap > 0:
                prefix_tokens = [
                    tok for tok in tokens if tok.char_end <= char_start
                ][-overlap:]
                if prefix_tokens:
                    candidate = source[prefix_tokens[0].char_start : char_start] + exclusive
                    if count_tokens(candidate) <= limit:
                        embed_text = candidate
            exclusive_count = len(exclusive_tokens)
            limit_exempt = exclusive_count > limit and exclusive_count == 1
            chunk_legal_id = f"{doc.legal_id}#chunk={index}"
            chunk_cid = _stable_cid(
                canonical_json_dumps(
                    {
                        "char_end": char_end,
                        "char_start": char_start,
                        "chunk_index": index,
                        "exclusive_text": exclusive,
                        "parent_legal_id": doc.legal_id,
                        "schema_version": SCHEMA_VERSION,
                        "tokenizer_id": self.tokenizer_id,
                    }
                )
            )
            chunks.append(
                LegalTextChunk(
                    chunk_index=index,
                    char_start=char_start,
                    char_end=char_end,
                    token_start=token_start,
                    token_end=token_end,
                    token_count=exclusive_count,
                    exclusive_text=exclusive,
                    text=embed_text,
                    split_mode=group[0][2] if len(group) == 1 else SplitMode.STRUCTURE.value,
                    parent_path=parent_path,
                    legal_id=chunk_legal_id,
                    parent_legal_id=doc.legal_id,
                    entry_cid=chunk_cid,
                    source_cid=doc.source_cid,
                    chunk_cid=chunk_cid,
                    jurisdiction_code=doc.jurisdiction_code,
                    document_index=doc.document_index,
                    model_token_limit=limit,
                    tokenizer_id=self.tokenizer_id,
                    limit_exempt=limit_exempt,
                    heading=doc.heading,
                )
            )

        if not truncated:
            assert_exact_reconstruction(source, chunks)
        assert_chunks_within_limit(chunks, limit)
        return ChunkingResult(
            chunks=tuple(chunks),
            source_text=source,
            source_token_count=len(tokens),
            model_token_limit=limit,
            overlap_tokens=overlap,
            max_chunks_per_section=max_chunks,
            truncated=truncated,
            tokenizer_id=self.tokenizer_id,
            parent_legal_id=doc.legal_id,
            legal_id=doc.legal_id,
            document_index=doc.document_index,
            jurisdiction_code=doc.jurisdiction_code,
        )


def chunk_statute(
    document: SourceDocument | Mapping[str, Any],
    *,
    model_token_limit: int = DEFAULT_MODEL_TOKEN_LIMIT,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    max_chunks_per_section: int = DEFAULT_MAX_CHUNKS_PER_SECTION,
) -> ChunkingResult:
    return OpenUsLawChunker(
        overlap_tokens=overlap_tokens,
        max_chunks_per_section=max_chunks_per_section,
    ).chunk_document(document, model_token_limit=model_token_limit)


def stream_chunk_documents(
    documents: Iterable[SourceDocument | Mapping[str, Any]],
    *,
    model_token_limit: int = DEFAULT_MODEL_TOKEN_LIMIT,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    max_chunks_per_section: int = DEFAULT_MAX_CHUNKS_PER_SECTION,
    budget: MemoryBudget | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield chunks one source document at a time (one document resident)."""

    chunker = OpenUsLawChunker(
        overlap_tokens=overlap_tokens,
        max_chunks_per_section=max_chunks_per_section,
    )
    resident = budget or MemoryBudget(max_resident_records=1)
    for raw in documents:
        resident.acquire(1)
        try:
            result = chunker.chunk_document(
                raw, model_token_limit=model_token_limit
            )
            for chunk in result.chunks:
                yield chunk.to_dict()
        finally:
            resident.release(1)


# ---------------------------------------------------------------------------
# Sort keys and physical shards
# ---------------------------------------------------------------------------


def document_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(record.get("document_index") or 0),
        str(record.get("entry_cid") or ""),
    )


def chunk_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(record.get("jurisdiction_code") or ""),
        int(record.get("document_index") or 0),
        int(record.get("chunk_index") or 0),
        str(record.get("entry_cid") or record.get("chunk_cid") or ""),
    )


def posting_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(record.get("term") or ""),
        str(record.get("entry_cid") or ""),
    )


def vector_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    cosine = record.get("cosine_to_centroid")
    try:
        value = float(cosine)
    except (TypeError, ValueError) as exc:
        raise ExternalSortError(
            f"cosine_to_centroid must be a finite float, got {cosine!r}"
        ) from exc
    if value != value or value in {float("inf"), float("-inf")}:
        raise ExternalSortError("cosine_to_centroid must be finite")
    return (-value, str(record.get("entry_cid") or ""))


def sort_key_for_family(family: str) -> KeyFn:
    normalized = _normalize_family(family)
    mapping = {
        "chunks": chunk_sort_key,
        "documents": document_sort_key,
        "postings": posting_sort_key,
        "vectors": vector_sort_key,
    }
    if normalized not in mapping:
        raise StreamingConfigError(f"no sort key for family {family!r}")
    return mapping[normalized]


def total_sort_key(record: Mapping[str, Any], key_fn: KeyFn) -> tuple[Any, ...]:
    primary = key_fn(record)
    if not isinstance(primary, tuple):
        primary = (primary,)
    return tuple(primary) + (canonical_json_dumps(dict(record)),)


def iter_physical_shards(
    records: Iterable[Mapping[str, Any]],
    *,
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD,
) -> Iterator[list[dict[str, Any]]]:
    """Yield physical shards of at most *max_rows* records (one shard resident)."""

    bound = _require_positive_int(max_rows, "max_rows")
    if bound > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise StreamingConfigError(
            f"max_rows must be <= {MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    shard: list[dict[str, Any]] = []
    for record in records:
        shard.append(dict(record))
        if len(shard) >= bound:
            yield shard
            shard = []
    if shard:
        yield shard


# ---------------------------------------------------------------------------
# External sort
# ---------------------------------------------------------------------------


class SortStatus(str, Enum):
    SPILLING = "spilling"
    MERGING = "merging"
    COMPLETE = "complete"
    INTERRUPTED = "interrupted"

    @classmethod
    def coerce(cls, value: Any) -> "SortStatus":
        if isinstance(value, SortStatus):
            return value
        text = str(value or "").strip().lower()
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise ExternalSortError(f"unknown sort status: {value!r}")


@dataclass
class ExternalSortConfig:
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY
    max_bytes_in_memory: Optional[int] = None
    merge_fan_in: int = DEFAULT_MERGE_FAN_IN
    family: str = "documents"
    resume: bool = True
    schema_version: str = SORT_CHECKPOINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.max_records_in_memory = _require_positive_int(
            self.max_records_in_memory, "max_records_in_memory"
        )
        if self.max_records_in_memory < 2:
            raise StreamingConfigError(
                "max_records_in_memory must be >= 2 so k-way merge can "
                "keep one head record per input run"
            )
        if self.max_bytes_in_memory is not None:
            self.max_bytes_in_memory = _require_positive_int(
                self.max_bytes_in_memory, "max_bytes_in_memory"
            )
        self.merge_fan_in = max(
            2,
            min(
                _require_positive_int(self.merge_fan_in, "merge_fan_in"),
                self.max_records_in_memory,
            ),
        )
        self.family = _normalize_family(self.family)
        self.resume = bool(self.resume)
        if self.schema_version != SORT_CHECKPOINT_SCHEMA_VERSION:
            raise StreamingConfigError(
                f"unsupported sort schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "max_bytes_in_memory": self.max_bytes_in_memory,
            "max_records_in_memory": self.max_records_in_memory,
            "merge_fan_in": self.merge_fan_in,
            "resume": self.resume,
            "schema_version": self.schema_version,
        }

    @property
    def digest(self) -> str:
        payload = {
            "family": self.family,
            "max_bytes_in_memory": self.max_bytes_in_memory,
            "max_records_in_memory": self.max_records_in_memory,
            "merge_fan_in": self.merge_fan_in,
            "schema_version": self.schema_version,
        }
        return digest_mapping(payload)


@dataclass
class ExternalSortCheckpoint:
    config_digest: str
    records_consumed: int
    run_paths: list[str]
    run_digests: list[str]
    status: SortStatus
    output_path: str = ""
    output_digest: str = ""
    row_count: int = 0
    peak_resident_records: int = 0
    schema_version: str = SORT_CHECKPOINT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_digest": self.config_digest,
            "output_digest": self.output_digest,
            "output_path": self.output_path,
            "peak_resident_records": self.peak_resident_records,
            "records_consumed": self.records_consumed,
            "row_count": self.row_count,
            "run_digests": list(self.run_digests),
            "run_paths": list(self.run_paths),
            "schema_version": self.schema_version,
            "status": self.status.value,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ExternalSortCheckpoint":
        if not isinstance(value, Mapping):
            raise ExternalSortError("sort checkpoint must be a mapping")
        schema = value.get("schema_version")
        if schema != SORT_CHECKPOINT_SCHEMA_VERSION:
            raise ExternalSortError(f"unsupported sort checkpoint schema: {schema!r}")
        return cls(
            config_digest=str(value.get("config_digest") or ""),
            records_consumed=int(value.get("records_consumed") or 0),
            run_paths=[str(item) for item in (value.get("run_paths") or [])],
            run_digests=[str(item) for item in (value.get("run_digests") or [])],
            status=SortStatus.coerce(value.get("status") or SortStatus.SPILLING),
            output_path=str(value.get("output_path") or ""),
            output_digest=str(value.get("output_digest") or ""),
            row_count=int(value.get("row_count") or 0),
            peak_resident_records=int(value.get("peak_resident_records") or 0),
            schema_version=str(schema),
        )


@dataclass(frozen=True, slots=True)
class ExternalSortReceipt:
    output_path: str
    output_digest: str
    row_count: int
    run_count: int
    records_consumed: int
    peak_resident_records: int
    max_records_in_memory: int
    interrupted: bool
    status: str
    authorizing_for_exact_51: bool = AUTHORIZES_EXACT_51_CORPUS
    proves_software_contract_only: bool = PROVES_SOFTWARE_CONTRACT_ONLY

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizing_for_exact_51": self.authorizing_for_exact_51,
            "interrupted": self.interrupted,
            "max_records_in_memory": self.max_records_in_memory,
            "output_digest": self.output_digest,
            "output_path": self.output_path,
            "peak_resident_records": self.peak_resident_records,
            "proves_software_contract_only": self.proves_software_contract_only,
            "records_consumed": self.records_consumed,
            "row_count": self.row_count,
            "run_count": self.run_count,
            "status": self.status,
        }


def _assert_sort_checkpoint_compatible(
    checkpoint: ExternalSortCheckpoint,
    config: ExternalSortConfig,
) -> None:
    if checkpoint.config_digest != config.digest:
        raise ExternalSortError(
            "sort checkpoint config_digest does not match active sort configuration"
        )


class ExternalSorter:
    """Spill sorted runs and k-way merge them under a memory bound."""

    def __init__(
        self,
        work_dir: PathLike,
        *,
        key_fn: KeyFn | None = None,
        config: ExternalSortConfig | None = None,
        budget: MemoryBudget | None = None,
    ) -> None:
        self.work_dir = Path(work_dir)
        self.config = config or ExternalSortConfig()
        self.key_fn = key_fn or sort_key_for_family(self.config.family)
        self.budget = budget or MemoryBudget(
            max_resident_records=self.config.max_records_in_memory,
            max_resident_bytes=self.config.max_bytes_in_memory,
        )
        self.checkpoint_path = self.work_dir / SORT_CHECKPOINT_FILENAME
        self.runs_dir = self.work_dir / "runs"

    def _load_checkpoint(self) -> ExternalSortCheckpoint | None:
        if not self.checkpoint_path.is_file():
            return None
        return ExternalSortCheckpoint.from_mapping(load_json_mapping(self.checkpoint_path))

    def _write_checkpoint(self, checkpoint: ExternalSortCheckpoint) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.checkpoint_path, checkpoint.to_dict())

    def _spill_buffer(
        self,
        buffer: list[dict[str, Any]],
        run_index: int,
    ) -> JsonlWriteResult:
        buffer.sort(key=lambda record: total_sort_key(record, self.key_fn))
        path = self.runs_dir / f"run-{run_index:06d}.jsonl"
        result = write_jsonl_atomic(path, buffer)
        released = list(buffer)
        buffer.clear()
        for record in released:
            self.budget.release(1, estimate_record_bytes(record))
        return result

    def _iter_merge(self, run_paths: Sequence[Path]) -> Iterator[dict[str, Any]]:
        if not run_paths:
            return
            yield  # pragma: no cover — keep this a generator
        fan_in = self.config.merge_fan_in
        current = [Path(path) for path in run_paths]
        pass_index = 0
        while len(current) > fan_in:
            next_paths: list[Path] = []
            for group_index in range(0, len(current), fan_in):
                group = current[group_index : group_index + fan_in]
                merged_path = self.work_dir / f"merge-{pass_index:03d}-{group_index:06d}.jsonl"
                write_jsonl_atomic(
                    merged_path,
                    heapq.merge(
                        *(iter_jsonl(path) for path in group),
                        key=lambda record: total_sort_key(record, self.key_fn),
                    ),
                )
                next_paths.append(merged_path)
            current = next_paths
            pass_index += 1
        heads = 0
        try:
            for _ in current:
                self.budget.acquire(1)
                heads += 1
            yield from heapq.merge(
                *(iter_jsonl(path) for path in current),
                key=lambda record: total_sort_key(record, self.key_fn),
            )
        finally:
            if heads:
                self.budget.release(heads)

    def sort_to_file(
        self,
        records: Iterable[Mapping[str, Any]],
        output_path: PathLike,
        *,
        interrupt_after_runs: int | None = None,
    ) -> ExternalSortReceipt:
        """Spill, merge, and write a byte-deterministic JSONL artifact."""

        config = self.config
        existing = self._load_checkpoint() if config.resume else None
        if existing is not None:
            _assert_sort_checkpoint_compatible(existing, config)
            if existing.status is SortStatus.COMPLETE and existing.output_digest:
                output = Path(existing.output_path or output_path)
                if output.is_file() and file_sha256(output) == existing.output_digest:
                    return ExternalSortReceipt(
                        output_path=str(output),
                        output_digest=existing.output_digest,
                        row_count=existing.row_count,
                        run_count=len(existing.run_paths),
                        records_consumed=existing.records_consumed,
                        peak_resident_records=max(
                            existing.peak_resident_records,
                            self.budget.peak_resident_records,
                        ),
                        max_records_in_memory=config.max_records_in_memory,
                        interrupted=False,
                        status=SortStatus.COMPLETE.value,
                    )
                raise ExternalSortError(
                    "completed sort checkpoint output digest does not match file"
                )

        skip_until = existing.records_consumed if existing else 0
        records_consumed = skip_until
        run_paths = list(existing.run_paths) if existing else []
        run_digests = list(existing.run_digests) if existing else []
        status = existing.status if existing else SortStatus.SPILLING

        if status is SortStatus.SPILLING or existing is None:
            skipped = 0
            buffer: list[dict[str, Any]] = []
            for record in records:
                if skipped < skip_until:
                    skipped += 1
                    continue
                payload = dict(record)
                nbytes = estimate_record_bytes(payload)
                self.budget.acquire(1, nbytes)
                buffer.append(payload)
                records_consumed += 1
                if len(buffer) >= config.max_records_in_memory:
                    spilled = self._spill_buffer(buffer, len(run_paths))
                    run_paths.append(spilled.path)
                    run_digests.append(spilled.sha256)
                    status = SortStatus.SPILLING
                    self._write_checkpoint(
                        ExternalSortCheckpoint(
                            config_digest=config.digest,
                            records_consumed=records_consumed,
                            run_paths=run_paths,
                            run_digests=run_digests,
                            status=status,
                            peak_resident_records=self.budget.peak_resident_records,
                        )
                    )
                    if (
                        interrupt_after_runs is not None
                        and len(run_paths) >= interrupt_after_runs
                    ):
                        return ExternalSortReceipt(
                            output_path="",
                            output_digest="",
                            row_count=0,
                            run_count=len(run_paths),
                            records_consumed=records_consumed,
                            peak_resident_records=self.budget.peak_resident_records,
                            max_records_in_memory=config.max_records_in_memory,
                            interrupted=True,
                            status=SortStatus.INTERRUPTED.value,
                        )
            if buffer:
                spilled = self._spill_buffer(buffer, len(run_paths))
                run_paths.append(spilled.path)
                run_digests.append(spilled.sha256)

        for path, digest in zip(run_paths, run_digests):
            if not Path(path).is_file():
                raise ExternalSortError(f"missing spilled run: {path}")
            if file_sha256(path) != digest:
                raise ExternalSortError(f"spilled run digest mismatch: {path}")

        status = SortStatus.MERGING
        self._write_checkpoint(
            ExternalSortCheckpoint(
                config_digest=config.digest,
                records_consumed=records_consumed,
                run_paths=run_paths,
                run_digests=run_digests,
                status=status,
                peak_resident_records=self.budget.peak_resident_records,
            )
        )

        output = Path(output_path)
        if run_paths:
            written = write_jsonl_atomic(output, self._iter_merge([Path(p) for p in run_paths]))
        else:
            written = write_jsonl_atomic(output, ())

        complete = ExternalSortCheckpoint(
            config_digest=config.digest,
            records_consumed=records_consumed,
            run_paths=run_paths,
            run_digests=run_digests,
            status=SortStatus.COMPLETE,
            output_path=written.path,
            output_digest=written.sha256,
            row_count=written.row_count,
            peak_resident_records=self.budget.peak_resident_records,
        )
        self._write_checkpoint(complete)
        return ExternalSortReceipt(
            output_path=written.path,
            output_digest=written.sha256,
            row_count=written.row_count,
            run_count=len(run_paths),
            records_consumed=records_consumed,
            peak_resident_records=self.budget.peak_resident_records,
            max_records_in_memory=config.max_records_in_memory,
            interrupted=False,
            status=SortStatus.COMPLETE.value,
        )


def external_sort_to_file(
    records: Iterable[Mapping[str, Any]],
    output_path: PathLike,
    *,
    work_dir: PathLike,
    key_fn: KeyFn | None = None,
    family: str = "documents",
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY,
    max_bytes_in_memory: int | None = None,
    budget: MemoryBudget | None = None,
    resume: bool = True,
    interrupt_after_runs: int | None = None,
) -> ExternalSortReceipt:
    sorter = ExternalSorter(
        work_dir,
        key_fn=key_fn,
        config=ExternalSortConfig(
            max_records_in_memory=max_records_in_memory,
            max_bytes_in_memory=max_bytes_in_memory,
            family=family,
            resume=resume,
        ),
        budget=budget,
    )
    return sorter.sort_to_file(
        records,
        output_path,
        interrupt_after_runs=interrupt_after_runs,
    )


def external_sort(
    records: Iterable[Mapping[str, Any]],
    *,
    work_dir: PathLike,
    key_fn: KeyFn | None = None,
    family: str = "documents",
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY,
    budget: MemoryBudget | None = None,
) -> Iterator[dict[str, Any]]:
    """Externally sort *records* and yield the merged stream."""

    work = Path(work_dir)
    output = work / "sorted.jsonl"
    receipt = external_sort_to_file(
        records,
        output,
        work_dir=work / "sort-work",
        key_fn=key_fn,
        family=family,
        max_records_in_memory=max_records_in_memory,
        budget=budget,
    )
    if receipt.interrupted:
        raise ExternalSortError("external sort interrupted before merge")
    yield from iter_jsonl(output)


def spill_sorted_run(
    records: Sequence[Mapping[str, Any]],
    path: PathLike,
    *,
    key_fn: KeyFn,
) -> JsonlWriteResult:
    ordered = sorted((dict(item) for item in records), key=lambda rec: total_sort_key(rec, key_fn))
    return write_jsonl_atomic(path, ordered)


def merge_sorted_runs(
    run_paths: Sequence[PathLike],
    output_path: PathLike,
    *,
    key_fn: KeyFn,
) -> JsonlWriteResult:
    return write_jsonl_atomic(
        output_path,
        heapq.merge(
            *(iter_jsonl(path) for path in run_paths),
            key=lambda record: total_sort_key(record, key_fn),
        ),
    )


# ---------------------------------------------------------------------------
# Derived fixture streams (documents / postings / placeholder vectors)
# ---------------------------------------------------------------------------


def stream_document_records(
    documents: Iterable[SourceDocument | Mapping[str, Any]],
    *,
    budget: MemoryBudget | None = None,
) -> Iterator[dict[str, Any]]:
    resident = budget or MemoryBudget(max_resident_records=1)
    for raw in documents:
        resident.acquire(1)
        try:
            doc = SourceDocument.from_mapping(raw)
            payload = doc.to_dict()
            payload["text_hash"] = _sha256_hex(doc.text)
            payload["production_materialization"] = False
            yield payload
        finally:
            resident.release(1)


def stream_postings_from_chunks(
    chunks: Iterable[Mapping[str, Any]],
    *,
    budget: MemoryBudget | None = None,
) -> Iterator[dict[str, Any]]:
    """Emit per-chunk term frequencies without a global postings map."""

    resident = budget or MemoryBudget(max_resident_records=1)
    for raw in chunks:
        resident.acquire(1)
        try:
            chunk = dict(raw)
            counts: dict[str, int] = {}
            for token in tokenize(str(chunk.get("text") or "")):
                term = token.text.casefold()
                counts[term] = counts.get(term, 0) + 1
            entry_cid = str(chunk.get("entry_cid") or chunk.get("chunk_cid") or "")
            jurisdiction = str(chunk.get("jurisdiction_code") or "")
            for term in sorted(counts):
                yield {
                    "entry_cid": entry_cid,
                    "jurisdiction_code": jurisdiction,
                    "term": term,
                    "tf": counts[term],
                }
        finally:
            resident.release(1)


def stream_placeholder_vectors(
    chunks: Iterable[Mapping[str, Any]],
    *,
    budget: MemoryBudget | None = None,
) -> Iterator[dict[str, Any]]:
    """Emit fixture-only vector locators. Not production GTE inference."""

    resident = budget or MemoryBudget(max_resident_records=1)
    for raw in chunks:
        resident.acquire(1)
        try:
            chunk = dict(raw)
            entry_cid = str(chunk.get("entry_cid") or chunk.get("chunk_cid") or "")
            digest = hashlib.sha256(entry_cid.encode("utf-8")).digest()
            cosine = int.from_bytes(digest[:4], "big") / float(2**32)
            yield {
                "backend": "fixture_placeholder",
                "cosine_to_centroid": cosine,
                "dimension": DEFAULT_EMBEDDING_DIMENSION,
                "entry_cid": entry_cid,
                "jurisdiction_code": str(chunk.get("jurisdiction_code") or ""),
                "production_inference": False,
            }
        finally:
            resident.release(1)


# ---------------------------------------------------------------------------
# Jurisdiction checkpoints
# ---------------------------------------------------------------------------


class WorkUnitStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    VERIFIED = "verified"
    FAILED = "failed"

    @classmethod
    def coerce(cls, value: Any) -> "WorkUnitStatus":
        if isinstance(value, WorkUnitStatus):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise StreamingCheckpointError(f"unknown work unit status: {value!r}")


@dataclass
class StreamingConfig:
    """Bound into checkpoints. Fixtures cannot flip authorization flags."""

    jurisdictions: tuple[str, ...]
    families: tuple[str, ...] = DEFAULT_FAMILIES
    model_token_limit: int = DEFAULT_MODEL_TOKEN_LIMIT
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY
    edition: str = DEFAULT_EDITION
    resume: bool = True
    validation_only: bool = False
    claim_exact_51: bool = False
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "jurisdictions", _normalize_jurisdictions(self.jurisdictions)
        )
        object.__setattr__(self, "families", _normalize_families(self.families))
        object.__setattr__(
            self,
            "model_token_limit",
            validate_model_token_limit(self.model_token_limit),
        )
        object.__setattr__(
            self,
            "max_rows_per_shard",
            _require_positive_int(self.max_rows_per_shard, "max_rows_per_shard"),
        )
        if self.max_rows_per_shard > MAX_ROWS_PER_PHYSICAL_SHARD:
            raise StreamingConfigError(
                f"max_rows_per_shard must be <= {MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
        max_in_memory = _require_positive_int(
            self.max_records_in_memory, "max_records_in_memory"
        )
        if max_in_memory < 2:
            raise StreamingConfigError(
                "max_records_in_memory must be >= 2 so k-way merge can "
                "keep one head record per input run"
            )
        object.__setattr__(self, "max_records_in_memory", max_in_memory)
        object.__setattr__(
            self, "edition", _require_non_empty_str(self.edition, "edition", maximum=128)
        )
        lowered = self.edition.strip().lower()
        if lowered in {"latest", "main", "head", "master", "current", "live"}:
            raise StreamingConfigError(
                f"edition must be an exact pin, not {self.edition!r}"
            )
        object.__setattr__(self, "resume", bool(self.resume))
        object.__setattr__(self, "validation_only", bool(self.validation_only))
        object.__setattr__(self, "claim_exact_51", bool(self.claim_exact_51))
        if self.schema_version != SCHEMA_VERSION:
            raise StreamingConfigError(
                f"unsupported schema_version {self.schema_version!r}"
            )
        reject_exact_51_authorization(self.claim_exact_51)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_exact_51": False,
            "edition": self.edition,
            "families": list(self.families),
            "jurisdictions": list(self.jurisdictions),
            "max_records_in_memory": self.max_records_in_memory,
            "max_rows_per_shard": self.max_rows_per_shard,
            "model_token_limit": self.model_token_limit,
            "resume": self.resume,
            "schema_version": self.schema_version,
            "uses_shard_bound_as_token_limit": (
                self.model_token_limit == MAX_ROWS_PER_PHYSICAL_SHARD
            ),
            "validation_only": self.validation_only,
        }

    @property
    def digest(self) -> str:
        payload = {
            "edition": self.edition,
            "families": list(self.families),
            "jurisdictions": list(self.jurisdictions),
            "max_records_in_memory": self.max_records_in_memory,
            "max_rows_per_shard": self.max_rows_per_shard,
            "model_token_limit": self.model_token_limit,
            "schema_version": self.schema_version,
        }
        return digest_mapping(payload)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StreamingConfig":
        if not isinstance(value, Mapping):
            raise StreamingConfigError("streaming config must be a mapping")
        return cls(
            jurisdictions=tuple(value.get("jurisdictions") or ()),
            families=tuple(value.get("families") or DEFAULT_FAMILIES),
            model_token_limit=int(
                value.get("model_token_limit", DEFAULT_MODEL_TOKEN_LIMIT)
            ),
            max_rows_per_shard=int(
                value.get("max_rows_per_shard", MAX_ROWS_PER_PHYSICAL_SHARD)
            ),
            max_records_in_memory=int(
                value.get("max_records_in_memory", DEFAULT_MAX_RECORDS_IN_MEMORY)
            ),
            edition=str(value.get("edition") or DEFAULT_EDITION),
            resume=bool(value.get("resume", True)),
            validation_only=bool(value.get("validation_only", False)),
            claim_exact_51=bool(value.get("claim_exact_51", False)),
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
        )


@dataclass
class JurisdictionUnitRecord:
    jurisdiction: str
    family: str
    status: WorkUnitStatus
    input_hash: str
    output_digest: str = ""
    artifact_path: str = ""
    row_count: int = 0
    peak_resident_records: int = 0
    attempt_count: int = 0
    error: str = ""
    verified: bool = False

    def __post_init__(self) -> None:
        self.jurisdiction = _normalize_jurisdiction(self.jurisdiction)
        self.family = _normalize_family(self.family)
        self.status = WorkUnitStatus.coerce(self.status)
        self.input_hash = _require_non_empty_str(self.input_hash, "input_hash", maximum=128)
        self.output_digest = str(self.output_digest or "")
        self.artifact_path = str(self.artifact_path or "")
        self.row_count = _require_non_negative_int(self.row_count, "row_count")
        self.peak_resident_records = _require_non_negative_int(
            self.peak_resident_records, "peak_resident_records"
        )
        self.attempt_count = _require_non_negative_int(
            self.attempt_count, "attempt_count"
        )
        self.error = str(self.error or "")
        self.verified = bool(self.verified)
        if self.status is WorkUnitStatus.VERIFIED:
            self.verified = True
        if self.verified and self.status is not WorkUnitStatus.VERIFIED:
            self.status = WorkUnitStatus.VERIFIED

    @property
    def key(self) -> str:
        return work_unit_key(self.jurisdiction, self.family)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "attempt_count": self.attempt_count,
            "error": self.error,
            "family": self.family,
            "input_hash": self.input_hash,
            "jurisdiction": self.jurisdiction,
            "output_digest": self.output_digest,
            "peak_resident_records": self.peak_resident_records,
            "row_count": self.row_count,
            "status": self.status.value,
            "verified": self.verified,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "JurisdictionUnitRecord":
        if not isinstance(value, Mapping):
            raise StreamingCheckpointError("work unit record must be a mapping")
        return cls(
            jurisdiction=str(value.get("jurisdiction") or ""),
            family=str(value.get("family") or ""),
            status=WorkUnitStatus.coerce(value.get("status") or WorkUnitStatus.PENDING),
            input_hash=str(value.get("input_hash") or ""),
            output_digest=str(value.get("output_digest") or ""),
            artifact_path=str(value.get("artifact_path") or ""),
            row_count=int(value.get("row_count") or 0),
            peak_resident_records=int(value.get("peak_resident_records") or 0),
            attempt_count=int(value.get("attempt_count") or 0),
            error=str(value.get("error") or ""),
            verified=bool(value.get("verified", False)),
        )


@dataclass
class StreamingCheckpoint:
    config_digest: str
    build_id: str
    units: dict[str, JurisdictionUnitRecord]
    sealed: bool = False
    seal_digest: str = ""
    schema_version: str = SCHEMA_VERSION
    producer: str = PRODUCER
    task_id: str = TASK_ID

    def __post_init__(self) -> None:
        self.config_digest = _require_non_empty_str(
            self.config_digest, "config_digest", maximum=128
        )
        self.build_id = _require_non_empty_str(self.build_id, "build_id", maximum=128)
        if not isinstance(self.units, dict):
            raise StreamingCheckpointError("units must be a dict")
        normalized: dict[str, JurisdictionUnitRecord] = {}
        for key, record in self.units.items():
            if isinstance(record, JurisdictionUnitRecord):
                rec = record
            elif isinstance(record, Mapping):
                rec = JurisdictionUnitRecord.from_mapping(record)
            else:
                raise StreamingCheckpointError(f"invalid unit record for {key!r}")
            normalized[rec.key] = rec
        self.units = normalized
        self.sealed = bool(self.sealed)
        self.seal_digest = str(self.seal_digest or "")
        if self.schema_version != SCHEMA_VERSION:
            raise StreamingCheckpointError(
                f"unsupported checkpoint schema_version: {self.schema_version!r}"
            )
        if self.sealed and not self.all_verified:
            raise PartialCheckpointPromotionError(
                "checkpoint marked sealed but units are incomplete"
            )

    @property
    def all_verified(self) -> bool:
        if not self.units:
            return False
        return all(
            rec.verified and rec.status is WorkUnitStatus.VERIFIED
            for rec in self.units.values()
        )

    @property
    def verified_count(self) -> int:
        return sum(1 for rec in self.units.values() if rec.verified)

    @property
    def total_count(self) -> int:
        return len(self.units)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "all_verified": self.all_verified,
            "authorizing_for_exact_51": AUTHORIZES_EXACT_51_CORPUS,
            "authorizing_for_publication": AUTHORIZES_PUBLICATION,
            "build_id": self.build_id,
            "config_digest": self.config_digest,
            "producer": self.producer,
            "proves_software_contract_only": PROVES_SOFTWARE_CONTRACT_ONLY,
            "schema_version": self.schema_version,
            "seal_digest": self.seal_digest,
            "sealed": self.sealed,
            "task_id": self.task_id,
            "total_count": self.total_count,
            "units": {
                key: rec.to_dict()
                for key, rec in sorted(self.units.items(), key=lambda item: item[0])
            },
            "verified_count": self.verified_count,
        }
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StreamingCheckpoint":
        if not isinstance(value, Mapping):
            raise StreamingCheckpointError("checkpoint must be a mapping")
        schema = value.get("schema_version")
        if schema != SCHEMA_VERSION:
            raise StreamingCheckpointError(
                f"unsupported checkpoint schema_version: {schema!r}"
            )
        units_raw = value.get("units") or {}
        if not isinstance(units_raw, Mapping):
            raise StreamingCheckpointError("checkpoint units must be a mapping")
        return cls(
            config_digest=str(value.get("config_digest") or ""),
            build_id=str(value.get("build_id") or ""),
            units={
                str(key): JurisdictionUnitRecord.from_mapping(record)  # type: ignore[arg-type]
                for key, record in units_raw.items()
            },
            sealed=bool(value.get("sealed", False)),
            seal_digest=str(value.get("seal_digest") or ""),
            schema_version=str(schema),
            producer=str(value.get("producer") or PRODUCER),
            task_id=str(value.get("task_id") or TASK_ID),
        )


@dataclass(frozen=True, slots=True)
class StreamingSeal:
    seal_digest: str
    config_digest: str
    build_id: str
    unit_count: int
    verified_count: int
    authorizing_for_exact_51: bool = AUTHORIZES_EXACT_51_CORPUS
    authorizing_for_publication: bool = AUTHORIZES_PUBLICATION
    proves_software_contract_only: bool = PROVES_SOFTWARE_CONTRACT_ONLY
    schema_version: str = SCHEMA_VERSION
    task_id: str = TASK_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizing_for_exact_51": self.authorizing_for_exact_51,
            "authorizing_for_publication": self.authorizing_for_publication,
            "build_id": self.build_id,
            "config_digest": self.config_digest,
            "proves_software_contract_only": self.proves_software_contract_only,
            "schema_version": self.schema_version,
            "seal_digest": self.seal_digest,
            "task_id": self.task_id,
            "unit_count": self.unit_count,
            "verified_count": self.verified_count,
        }


@dataclass
class ProducerResult:
    output_digest: str
    artifact_path: str
    row_count: int = 0
    peak_resident_records: int = 0
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "output_digest": self.output_digest,
            "peak_resident_records": self.peak_resident_records,
            "row_count": self.row_count,
            "skipped": self.skipped,
        }


class FamilyProducer(Protocol):
    def __call__(
        self,
        jurisdiction: str,
        family: str,
        config: StreamingConfig,
        output_dir: Path,
        documents: Iterable[Any],
    ) -> ProducerResult: ...


@dataclass
class StreamingResult:
    checkpoint: StreamingCheckpoint
    seal: Optional[StreamingSeal]
    executed_keys: tuple[str, ...]
    resumed_keys: tuple[str, ...]
    validation_only: bool
    interrupted: bool
    receipt_path: str = ""
    checkpoint_path: str = ""
    seal_path: str = ""
    artifact_digests: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "artifact_digests": dict(sorted(self.artifact_digests.items())),
            "checkpoint": self.checkpoint.to_dict(),
            "checkpoint_path": self.checkpoint_path,
            "executed_keys": list(self.executed_keys),
            "interrupted": self.interrupted,
            "receipt_path": self.receipt_path,
            "resumed_keys": list(self.resumed_keys),
            "seal": None if self.seal is None else self.seal.to_dict(),
            "seal_path": self.seal_path,
            "validation_only": self.validation_only,
        }
        payload.update(software_contract_flags())
        return payload


def load_checkpoint(path: PathLike) -> StreamingCheckpoint:
    return StreamingCheckpoint.from_mapping(load_json_mapping(path))


def write_checkpoint_atomic(
    path: PathLike, checkpoint: StreamingCheckpoint
) -> Path:
    return write_json_atomic(path, checkpoint.to_dict())


def assert_checkpoint_compatible(
    checkpoint: StreamingCheckpoint,
    config: StreamingConfig,
) -> None:
    if checkpoint.schema_version != SCHEMA_VERSION:
        raise StreamingCheckpointError(
            f"checkpoint schema_version {checkpoint.schema_version!r} "
            f"!= {SCHEMA_VERSION!r}"
        )
    if checkpoint.config_digest != config.digest:
        raise StreamingCheckpointError(
            "checkpoint config_digest does not match active build configuration"
        )
    if checkpoint.task_id != TASK_ID:
        raise StreamingCheckpointError(
            f"checkpoint task_id {checkpoint.task_id!r} != {TASK_ID!r}"
        )


def compute_seal(checkpoint: StreamingCheckpoint) -> StreamingSeal:
    if not checkpoint.all_verified:
        raise PartialCheckpointPromotionError(
            "cannot seal partial output: "
            f"{checkpoint.verified_count}/{checkpoint.total_count} verified"
        )
    if checkpoint.sealed and checkpoint.seal_digest:
        digest = checkpoint.seal_digest
    else:
        payload = {
            "build_id": checkpoint.build_id,
            "config_digest": checkpoint.config_digest,
            "schema_version": checkpoint.schema_version,
            "task_id": checkpoint.task_id,
            "units": {
                key: {
                    "input_hash": rec.input_hash,
                    "output_digest": rec.output_digest,
                    "row_count": rec.row_count,
                }
                for key, rec in sorted(checkpoint.units.items(), key=lambda item: item[0])
            },
        }
        digest = digest_mapping(payload)
    return StreamingSeal(
        seal_digest=digest,
        config_digest=checkpoint.config_digest,
        build_id=checkpoint.build_id,
        unit_count=checkpoint.total_count,
        verified_count=checkpoint.verified_count,
    )


def plan_build_id(config: StreamingConfig) -> str:
    return digest_mapping(
        {
            "config_digest": config.digest,
            "producer": PRODUCER,
            "task_id": TASK_ID,
        }
    )


def document_set_hash(
    jurisdiction: str,
    documents: Iterable[SourceDocument | Mapping[str, Any]],
) -> str:
    """Digest document identities without retaining bodies after each row."""

    hasher = hashlib.sha256()
    hasher.update(jurisdiction.encode("utf-8"))
    count = 0
    for raw in documents:
        doc = SourceDocument.from_mapping(raw)
        row = canonical_json_dumps(
            {
                "document_index": doc.document_index,
                "entry_cid": doc.entry_cid,
                "legal_id": doc.legal_id,
                "source_cid": doc.source_cid,
                "text_hash": _sha256_hex(doc.text),
            }
        )
        hasher.update(row.encode("utf-8"))
        count += 1
    hasher.update(str(count).encode("utf-8"))
    return hasher.hexdigest()


def default_family_producer(
    jurisdiction: str,
    family: str,
    config: StreamingConfig,
    output_dir: Path,
    documents: Iterable[Any],
) -> ProducerResult:
    """Offline producer: stream, externally sort, never load the full family."""

    family_name = _normalize_family(family)
    work_root = output_dir / jurisdiction / family_name
    artifact = work_root / "sorted.jsonl"
    sort_work = work_root / ".sort"
    budget = MemoryBudget(max_resident_records=config.max_records_in_memory)
    if family_name == "documents":
        stream: Iterable[Mapping[str, Any]] = stream_document_records(
            documents, budget=MemoryBudget(max_resident_records=1)
        )
    elif family_name == "chunks":
        stream = stream_chunk_documents(
            documents,
            model_token_limit=config.model_token_limit,
            budget=MemoryBudget(max_resident_records=1),
        )
    elif family_name == "postings":
        stream = stream_postings_from_chunks(
            stream_chunk_documents(
                documents,
                model_token_limit=config.model_token_limit,
                budget=MemoryBudget(max_resident_records=1),
            ),
            budget=MemoryBudget(max_resident_records=1),
        )
    elif family_name == "vectors":
        stream = stream_placeholder_vectors(
            stream_chunk_documents(
                documents,
                model_token_limit=config.model_token_limit,
                budget=MemoryBudget(max_resident_records=1),
            ),
            budget=MemoryBudget(max_resident_records=1),
        )
    else:
        raise StreamingConfigError(f"unsupported family {family!r}")

    if config.validation_only:
        count = 0
        for _record in stream:
            count += 1
        return ProducerResult(
            output_digest=digest_mapping(
                {"family": family_name, "jurisdiction": jurisdiction, "rows": count}
            ),
            artifact_path="",
            row_count=count,
            peak_resident_records=budget.peak_resident_records,
        )

    receipt = external_sort_to_file(
        stream,
        artifact,
        work_dir=sort_work,
        key_fn=sort_key_for_family(family_name),
        family=family_name,
        max_records_in_memory=config.max_records_in_memory,
        budget=budget,
        resume=False,
    )
    if receipt.interrupted:
        raise ExternalSortError(f"producer sort interrupted for {jurisdiction}/{family_name}")
    return ProducerResult(
        output_digest=receipt.output_digest,
        artifact_path=receipt.output_path,
        row_count=receipt.row_count,
        peak_resident_records=max(
            receipt.peak_resident_records, budget.peak_resident_records
        ),
    )


class StreamingBuildOrchestrator:
    """Jurisdiction-checkpointed streaming builder."""

    def __init__(
        self,
        *,
        output_dir: PathLike,
        checkpoint_dir: PathLike | None = None,
        producer: FamilyProducer | None = None,
        document_source: DocumentSource | Mapping[str, Iterable[Any]] | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.checkpoint_dir = Path(
            checkpoint_dir
            if checkpoint_dir is not None
            else self.output_dir / ".checkpoints"
        )
        self.producer: FamilyProducer = producer or default_family_producer
        self.document_source = document_source
        self.checkpoint_path = self.checkpoint_dir / CHECKPOINT_FILENAME
        self.seal_path = self.checkpoint_dir / SEAL_FILENAME
        self.receipt_path = self.checkpoint_dir / RECEIPT_FILENAME

    def documents_for(self, jurisdiction: str) -> Iterable[Any]:
        if self.document_source is None:
            raise StreamingConfigError("document_source is required")
        if callable(self.document_source):
            return self.document_source(jurisdiction)
        if isinstance(self.document_source, Mapping):
            return self.document_source[jurisdiction]
        raise StreamingConfigError("document_source must be a callable or mapping")

    def load_checkpoint(self) -> StreamingCheckpoint | None:
        if not self.checkpoint_path.is_file():
            return None
        return load_checkpoint(self.checkpoint_path)

    def write_checkpoint(self, checkpoint: StreamingCheckpoint) -> Path:
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        return write_checkpoint_atomic(self.checkpoint_path, checkpoint)

    def run(
        self,
        config: StreamingConfig,
        *,
        interrupt_after_units: int | None = None,
    ) -> StreamingResult:
        reject_exact_51_authorization(config.claim_exact_51)
        existing = self.load_checkpoint() if config.resume else None
        if existing is not None:
            assert_checkpoint_compatible(existing, config)

        build_id = plan_build_id(config)
        records: dict[str, JurisdictionUnitRecord] = {}
        resumed_keys: list[str] = []
        executed_keys: list[str] = []
        input_hashes: dict[str, str] = {}

        for jurisdiction in config.jurisdictions:
            input_hashes[jurisdiction] = document_set_hash(
                jurisdiction, self.documents_for(jurisdiction)
            )
            for family in config.families:
                key = work_unit_key(jurisdiction, family)
                prior = existing.units.get(key) if existing else None
                input_hash = input_hashes[jurisdiction]
                if (
                    prior is not None
                    and prior.verified
                    and prior.status is WorkUnitStatus.VERIFIED
                    and prior.input_hash == input_hash
                    and prior.output_digest
                ):
                    records[key] = JurisdictionUnitRecord(
                        jurisdiction=jurisdiction,
                        family=family,
                        status=WorkUnitStatus.VERIFIED,
                        input_hash=input_hash,
                        output_digest=prior.output_digest,
                        artifact_path=prior.artifact_path,
                        row_count=prior.row_count,
                        peak_resident_records=prior.peak_resident_records,
                        attempt_count=prior.attempt_count,
                        verified=True,
                    )
                    resumed_keys.append(key)
                else:
                    records[key] = JurisdictionUnitRecord(
                        jurisdiction=jurisdiction,
                        family=family,
                        status=WorkUnitStatus.PENDING,
                        input_hash=input_hash,
                        attempt_count=prior.attempt_count if prior is not None else 0,
                    )

        checkpoint = StreamingCheckpoint(
            config_digest=config.digest,
            build_id=build_id,
            units=records,
            sealed=False,
        )
        if not config.validation_only:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.write_checkpoint(checkpoint)

        newly_executed = 0
        interrupted = False
        pending_keys = sorted(
            key for key, rec in checkpoint.units.items() if not rec.verified
        )
        artifact_digests: dict[str, str] = {
            key: rec.output_digest
            for key, rec in checkpoint.units.items()
            if rec.output_digest
        }

        for key in pending_keys:
            if (
                interrupt_after_units is not None
                and newly_executed >= interrupt_after_units
            ):
                interrupted = True
                break
            rec = checkpoint.units[key]
            rec.status = WorkUnitStatus.IN_PROGRESS
            rec.attempt_count += 1
            if not config.validation_only:
                self.write_checkpoint(checkpoint)
            try:
                result = self.producer(
                    rec.jurisdiction,
                    rec.family,
                    config,
                    self.output_dir,
                    self.documents_for(rec.jurisdiction),
                )
            except OpenUsLawStreamingError:
                rec.status = WorkUnitStatus.FAILED
                rec.error = "producer raised OpenUsLawStreamingError"
                if not config.validation_only:
                    self.write_checkpoint(checkpoint)
                raise
            except Exception as exc:  # noqa: BLE001 — surface as producer failure
                rec.status = WorkUnitStatus.FAILED
                rec.error = f"{type(exc).__name__}: {exc}"
                if not config.validation_only:
                    self.write_checkpoint(checkpoint)
                raise ProducerError(f"producer failed for {key}: {exc}") from exc

            rec.status = WorkUnitStatus.VERIFIED
            rec.verified = True
            rec.output_digest = result.output_digest
            rec.artifact_path = result.artifact_path
            rec.row_count = result.row_count
            rec.peak_resident_records = result.peak_resident_records
            rec.error = ""
            artifact_digests[key] = result.output_digest
            if not result.skipped:
                executed_keys.append(key)
                newly_executed += 1
            if not config.validation_only:
                self.write_checkpoint(checkpoint)

        seal: StreamingSeal | None = None
        seal_path = ""
        if interrupted:
            if checkpoint.sealed:
                raise SealError("internal error: interrupted checkpoint is sealed")
        elif checkpoint.all_verified:
            seal = compute_seal(checkpoint)
            checkpoint.sealed = True
            checkpoint.seal_digest = seal.seal_digest
            if not config.validation_only:
                self.write_checkpoint(checkpoint)
                write_json_atomic(self.seal_path, seal.to_dict())
                seal_path = str(self.seal_path)

        receipt = {
            "artifact_digests": dict(sorted(artifact_digests.items())),
            "build_id": build_id,
            "config": config.to_dict(),
            "config_digest": config.digest,
            "executed_keys": executed_keys,
            "interrupted": interrupted,
            "peak_resident_records": max(
                (rec.peak_resident_records for rec in checkpoint.units.values()),
                default=0,
            ),
            "producer": PRODUCER,
            "resumed_keys": resumed_keys,
            "schema_version": SCHEMA_VERSION,
            "seal_digest": "" if seal is None else seal.seal_digest,
            "sealed": checkpoint.sealed,
            "task_id": TASK_ID,
            "total_count": checkpoint.total_count,
            "validation_only": config.validation_only,
            "verified_count": checkpoint.verified_count,
        }
        receipt.update(software_contract_flags())
        assert_software_contract_only(receipt)
        receipt_path = ""
        if not config.validation_only:
            write_json_atomic(self.receipt_path, receipt)
            receipt_path = str(self.receipt_path)

        return StreamingResult(
            checkpoint=checkpoint,
            seal=seal,
            executed_keys=tuple(executed_keys),
            resumed_keys=tuple(resumed_keys),
            validation_only=config.validation_only,
            interrupted=interrupted,
            receipt_path=receipt_path,
            checkpoint_path="" if config.validation_only else str(self.checkpoint_path),
            seal_path=seal_path,
            artifact_digests=artifact_digests,
        )

    def seal_existing(self, config: StreamingConfig) -> StreamingSeal:
        checkpoint = self.load_checkpoint()
        if checkpoint is None:
            raise SealError("no checkpoint to seal")
        assert_checkpoint_compatible(checkpoint, config)
        return compute_seal(checkpoint)


# ---------------------------------------------------------------------------
# Fixture helpers (software-contract only)
# ---------------------------------------------------------------------------


def fixture_statute_text(jurisdiction: str, section: int, *, extra_tokens: int = 0) -> str:
    body = (
        f"{jurisdiction} statute section {section}. "
        f"(a) Operative provision {section} for {jurisdiction}. "
        f"(b) Companion provision. "
        f"(1) Nested paragraph one. (2) Nested paragraph two. "
    )
    if extra_tokens > 0:
        body += " ".join(f"tok{index}" for index in range(extra_tokens))
    return body


def fixture_jurisdiction_documents(
    jurisdiction: str,
    *,
    count: int = 8,
    extra_tokens: int = 0,
    edition: str = DEFAULT_EDITION,
) -> list[SourceDocument]:
    code = _normalize_jurisdiction(jurisdiction)
    documents: list[SourceDocument] = []
    for index in range(count):
        section = str(index + 1)
        documents.append(
            SourceDocument(
                jurisdiction_code=code,
                text=fixture_statute_text(
                    code, index + 1, extra_tokens=extra_tokens + (index % 5)
                ),
                title="1",
                chapter="1",
                section=section,
                edition=edition,
                document_index=index,
                heading=f"{code} § {section}",
            ).normalized()
        )
    return documents


def fixture_document_source(
    jurisdictions: Sequence[str],
    *,
    docs_per_jurisdiction: int = 8,
    extra_tokens: int = 0,
    edition: str = DEFAULT_EDITION,
) -> tuple[dict[str, list[SourceDocument]], "InstrumentedDocumentSource"]:
    store = {
        _normalize_jurisdiction(code): fixture_jurisdiction_documents(
            code,
            count=docs_per_jurisdiction,
            extra_tokens=extra_tokens,
            edition=edition,
        )
        for code in jurisdictions
    }
    return store, InstrumentedDocumentSource(store)


class InstrumentedDocumentSource:
    """Test double that records which jurisdictions were streamed."""

    def __init__(self, store: Mapping[str, Sequence[Any]]) -> None:
        self.store = {
            _normalize_jurisdiction(key): list(value) for key, value in store.items()
        }
        self.loads: list[str] = []

    def __call__(self, jurisdiction: str) -> Iterator[SourceDocument]:
        code = _normalize_jurisdiction(jurisdiction)
        self.loads.append(code)
        for document in self.store[code]:
            yield document


def run_fixture_streaming_build(
    output_dir: PathLike,
    *,
    jurisdictions: Sequence[str] = ("AL", "AK"),
    families: Sequence[str] = DEFAULT_FAMILIES,
    docs_per_jurisdiction: int = 6,
    extra_tokens: int = 0,
    resume: bool = True,
    validation_only: bool = False,
    interrupt_after_units: int | None = None,
    max_records_in_memory: int = 8,
    model_token_limit: int = DEFAULT_MODEL_TOKEN_LIMIT,
    checkpoint_dir: PathLike | None = None,
    producer: FamilyProducer | None = None,
    document_source: DocumentSource | Mapping[str, Iterable[Any]] | None = None,
) -> StreamingResult:
    """Offline fixture entry point. Never an exact-51 completeness proof."""

    codes = _normalize_jurisdictions(jurisdictions)
    config = StreamingConfig(
        jurisdictions=codes,
        families=tuple(families),
        model_token_limit=model_token_limit,
        max_records_in_memory=max_records_in_memory,
        resume=resume,
        validation_only=validation_only,
    )
    if document_source is None:
        _store, document_source = fixture_document_source(
            codes,
            docs_per_jurisdiction=docs_per_jurisdiction,
            extra_tokens=extra_tokens,
            edition=config.edition,
        )
    orchestrator = StreamingBuildOrchestrator(
        output_dir=output_dir,
        checkpoint_dir=checkpoint_dir,
        producer=producer,
        document_source=document_source,
    )
    return orchestrator.run(config, interrupt_after_units=interrupt_after_units)


def content_fingerprint(paths: Sequence[PathLike]) -> str:
    hasher = hashlib.sha256()
    for path in paths:
        target = Path(path)
        hasher.update(target.name.encode("utf-8"))
        if target.is_file():
            hasher.update(file_sha256(target).encode("utf-8"))
    return hasher.hexdigest()


__all__ = [
    "AUTHORIZES_EXACT_51_CORPUS",
    "AUTHORIZES_PUBLICATION",
    "DEFAULT_FAMILIES",
    "DEFAULT_MAX_RECORDS_IN_MEMORY",
    "DEFAULT_MODEL_TOKEN_LIMIT",
    "GOAL_ID",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "PROVES_SOFTWARE_CONTRACT_ONLY",
    "SCHEMA_VERSION",
    "TASK_ID",
    "ChunkingResult",
    "Exact51AuthorizationError",
    "ExternalSortError",
    "ExternalSortReceipt",
    "ExternalSorter",
    "InstrumentedDocumentSource",
    "JurisdictionUnitRecord",
    "LegalTextChunk",
    "MemoryBudget",
    "MemoryBudgetError",
    "OpenUsLawChunker",
    "OpenUsLawStreamingError",
    "PartialCheckpointPromotionError",
    "SealError",
    "SourceDocument",
    "StreamingBuildOrchestrator",
    "StreamingCheckpoint",
    "StreamingCheckpointError",
    "StreamingConfig",
    "StreamingConfigError",
    "StreamingResult",
    "WorkUnitStatus",
    "assert_checkpoint_compatible",
    "assert_chunks_within_limit",
    "assert_exact_reconstruction",
    "assert_software_contract_only",
    "authorizing_for_exact_51_corpus",
    "chunk_sort_key",
    "chunk_statute",
    "compute_seal",
    "document_sort_key",
    "external_sort",
    "external_sort_to_file",
    "fixture_jurisdiction_documents",
    "iter_jsonl",
    "iter_physical_shards",
    "load_checkpoint",
    "materialize_records",
    "merge_sorted_runs",
    "posting_sort_key",
    "reconstruct_text",
    "reject_exact_51_authorization",
    "run_fixture_streaming_build",
    "spill_sorted_run",
    "stream_chunk_documents",
    "stream_document_records",
    "stream_placeholder_vectors",
    "stream_postings_from_chunks",
    "validate_model_token_limit",
    "vector_sort_key",
    "write_checkpoint_atomic",
    "write_json_atomic",
    "write_jsonl_atomic",
]
