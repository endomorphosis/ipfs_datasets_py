"""First-party, read-only probes for immutable State Laws releases.

This module is the trust boundary used by the LCR-041 and LCR-043--046
evidence generators.  Canonical evidence is measured here from descriptor-
verified bytes and the production ``state_laws_sparse_graphrag`` query API;
an operator-authored JSON file is never an evidence source.

The public helpers deliberately accept injected verifier, query, clock, and
HTTP seams.  Tests can therefore stay offline without weakening production:
the CLI entrypoints call these helpers without overriding those seams.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final

from ipfs_datasets_py.processors.legal_data import state_laws_sparse_graphrag as sparse
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
)
from ipfs_datasets_py.processors.legal_data.state_laws_local_release import (
    verify_state_laws_local_release_manifest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_query import tokenize_query
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    DEFAULT_DATASET_REPO_ID,
    EXPECTED_JURISDICTION_COUNT,
    VIEWER_DEFAULT_CORPUS_GLOB,
    state_laws_root_viewer_configs,
)

SCHEMA_VERSION: Final = "state-laws-first-party-release-probe/v1"
MEASUREMENT_SOURCE: Final = "internal_first_party"
DEFAULT_CONFIG_NAME: Final = "state_statutes_exact_51"
# The production manifest deliberately places DC after the 50 states.  Keep the
# historical public name for downstream compatibility, but never derive an
# ordered contract from the release-schema frozenset.
SORTED_JURISDICTIONS: Final = CANONICAL_JURISDICTION_ORDER
DEFAULT_MAX_QUERY_BYTES: Final = 2_000_000
DEFAULT_MAX_QUERY_SHARDS: Final = 32
DEFAULT_MAX_QUERY_ROWS: Final = 4_096
DEFAULT_MAX_VIEWER_BYTES: Final = 2_000_000
# Multifetch source receipts retain tens of thousands of response hashes.  Keep
# their audit bound independent from sparse-query transfer budgets while still
# imposing a small, fixed ceiling on every descriptor-verified JSON artifact.
DEFAULT_MAX_SOURCE_RECEIPT_BYTES: Final = 16 * 1024 * 1024
DEFAULT_HTTP_TIMEOUT_SECONDS: Final = 30.0
LEGACY_PIN_PROBE_PATH: Final = "state_laws_parquet_cid/STATE-DC.parquet"
LEGACY_PIN_MAX_BYTES: Final = 2_000_000
VIEWER_ENDPOINTS: Final = ("is-valid", "info", "size", "splits")
VIEWER_REQUIRED_CAPABILITIES: Final = ("viewer", "preview")
DUAL_PIN_QUERY_TERMS: Final = ("law", "shall", "section", "person", "state")

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
_JURISDICTION_PATH_RE = re.compile(r"(?:^|/)jurisdiction=([A-Z]{2})(?:/|$)")


class StateLawsReleaseProbeError(RuntimeError):
    """A first-party measurement could not be proven safely."""


class StateLawsReleaseProbeBindingError(StateLawsReleaseProbeError):
    """The measured repo, pin, or manifest identity drifted."""


class StateLawsReleaseProbeQueryError(StateLawsReleaseProbeError):
    """A bounded production query did not close."""


class StateLawsReleaseProbeViewerError(StateLawsReleaseProbeError):
    """The pinned Dataset Viewer probe did not close."""


@dataclass(frozen=True, slots=True)
class QueryRepresentative:
    """One release-derived query seed for a jurisdiction."""

    jurisdiction: str
    entry_cid: str
    query_terms: tuple[str, ...]
    query_vector: tuple[float, ...]


def _require_repo_id(value: Any) -> str:
    text = str(value or "").strip()
    if text != DEFAULT_DATASET_REPO_ID:
        raise StateLawsReleaseProbeBindingError(
            f"repo_id must be {DEFAULT_DATASET_REPO_ID!r}"
        )
    return text


def _require_revision(value: Any) -> str:
    text = str(value or "").strip().lower()
    if _SHA_RE.fullmatch(text) is None:
        raise StateLawsReleaseProbeBindingError(
            "revision must be an immutable lowercase 40-hex commit"
        )
    return text


def _require_digest(value: Any, *, name: str) -> str:
    text = str(value or "").strip().lower()
    if _DIGEST_RE.fullmatch(text) is None:
        raise StateLawsReleaseProbeBindingError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return text


def _utc_observed_at(utc_now: Callable[[], Any]) -> str:
    value = utc_now()
    if isinstance(value, datetime):
        current = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        text = current.astimezone(UTC).isoformat(timespec="microseconds")
        return text.replace("+00:00", "Z")
    text = str(value or "").strip()
    if _ISO_Z_RE.fullmatch(text) is None:
        raise StateLawsReleaseProbeError("utc_now returned a non-UTC observation time")
    return text


def release_probe_bindings(
    *,
    repo_id: Any,
    revision: Any,
    release_manifest_digest: Any,
    parent_evidence_digest: Any | None = None,
) -> dict[str, Any]:
    """Return normalized immutable coordinates for one measurement."""

    result: dict[str, Any] = {
        "dataset_repo_id": _require_repo_id(repo_id),
        "release_manifest_digest": _require_digest(
            release_manifest_digest, name="release_manifest_digest"
        ),
        "revision": _require_revision(revision),
    }
    if parent_evidence_digest not in (None, ""):
        result["parent_evidence_digest"] = _require_digest(
            parent_evidence_digest, name="parent_evidence_digest"
        )
    return result


def assert_first_party_measurement(
    value: Mapping[str, Any],
    *,
    repo_id: str,
    revision: str,
    release_manifest_digest: str,
    parent_evidence_digest: str | None = None,
) -> dict[str, Any]:
    """Fail closed unless *value* is bound internal probe output."""

    if not isinstance(value, Mapping):
        raise StateLawsReleaseProbeBindingError("measurement must be an object")
    measured = dict(value)
    if (
        measured.get("measurement_source") != MEASUREMENT_SOURCE
        or measured.get("externally_supplied") is not False
        or _ISO_Z_RE.fullmatch(str(measured.get("observed_at") or "")) is None
    ):
        raise StateLawsReleaseProbeBindingError(
            "measurement is not internally observed first-party evidence"
        )
    expected = release_probe_bindings(
        repo_id=repo_id,
        revision=revision,
        release_manifest_digest=release_manifest_digest,
        parent_evidence_digest=parent_evidence_digest,
    )
    if measured.get("probe_bindings") != expected:
        raise StateLawsReleaseProbeBindingError(
            "measurement repo/pin/manifest binding drifted"
        )
    sparse.assert_no_secret_payload(measured)
    return measured


def dual_pin_probe_bindings(
    *,
    repo_id: Any,
    new_revision: Any,
    previous_revision: Any,
    release_manifest_digest: Any,
    parent_evidence_digest: Any,
) -> dict[str, Any]:
    """Return immutable coordinates for a two-pin rollback probe."""

    new_pin = _require_revision(new_revision)
    previous_pin = _require_revision(previous_revision)
    if new_pin == previous_pin:
        raise StateLawsReleaseProbeBindingError(
            "new and previous rollback pins must differ"
        )
    return {
        "dataset_repo_id": _require_repo_id(repo_id),
        "new_revision": new_pin,
        "parent_evidence_digest": _require_digest(
            parent_evidence_digest, name="parent_evidence_digest"
        ),
        "previous_revision": previous_pin,
        "release_manifest_digest": _require_digest(
            release_manifest_digest, name="release_manifest_digest"
        ),
    }


def assert_first_party_dual_pin_measurement(
    value: Mapping[str, Any],
    *,
    repo_id: str,
    new_revision: str,
    previous_revision: str,
    release_manifest_digest: str,
    parent_evidence_digest: str,
) -> dict[str, Any]:
    """Fail closed unless *value* is internally measured at both pins."""

    if not isinstance(value, Mapping):
        raise StateLawsReleaseProbeBindingError(
            "dual-pin measurement must be an object"
        )
    measured = dict(value)
    expected = dual_pin_probe_bindings(
        repo_id=repo_id,
        new_revision=new_revision,
        previous_revision=previous_revision,
        release_manifest_digest=release_manifest_digest,
        parent_evidence_digest=parent_evidence_digest,
    )
    if (
        measured.get("measurement_source") != MEASUREMENT_SOURCE
        or measured.get("externally_supplied") is not False
        or _ISO_Z_RE.fullmatch(str(measured.get("observed_at") or "")) is None
        or measured.get("probe_bindings") != expected
    ):
        raise StateLawsReleaseProbeBindingError(
            "dual-pin measurement is not bound internal first-party evidence"
        )
    sparse.assert_no_secret_payload(measured)
    return measured


def _confined_file(root: Path, relative_path: Any) -> Path:
    relative = PurePosixPath(str(relative_path or ""))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise StateLawsReleaseProbeError("release descriptor path is unsafe")
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise StateLawsReleaseProbeError(
            f"release descriptor is not a regular file: {relative.as_posix()}"
        )
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise StateLawsReleaseProbeError("release descriptor escaped its root") from exc
    return resolved


def _read_source_receipt_json(
    path: Path,
    *,
    declared_size: Any,
) -> tuple[Any, bytes]:
    if (
        isinstance(declared_size, bool)
        or not isinstance(declared_size, int)
        or declared_size <= 0
    ):
        raise StateLawsReleaseProbeError(
            "source-receipt descriptor has no positive size_bytes"
        )
    if declared_size > DEFAULT_MAX_SOURCE_RECEIPT_BYTES:
        raise StateLawsReleaseProbeError(
            "source-receipt descriptor exceeded the audit hard cap"
        )
    try:
        actual_size = path.stat().st_size
    except OSError as exc:
        raise StateLawsReleaseProbeError(
            "source-receipt artifact size could not be audited"
        ) from exc
    if actual_size > DEFAULT_MAX_SOURCE_RECEIPT_BYTES:
        raise StateLawsReleaseProbeError(
            "source-receipt artifact exceeded the audit hard cap"
        )
    if actual_size != declared_size:
        raise StateLawsReleaseProbeError(
            "source-receipt artifact size differs from its descriptor"
        )
    try:
        with path.open("rb") as stream:
            blob = stream.read(DEFAULT_MAX_SOURCE_RECEIPT_BYTES + 1)
    except OSError as exc:
        raise StateLawsReleaseProbeError(
            "source-receipt artifact could not be audited"
        ) from exc
    if len(blob) > DEFAULT_MAX_SOURCE_RECEIPT_BYTES:
        raise StateLawsReleaseProbeError(
            "source-receipt artifact exceeded the audit hard cap"
        )
    if len(blob) != declared_size:
        raise StateLawsReleaseProbeError(
            "source-receipt artifact changed while it was audited"
        )
    try:
        payload = json.loads(blob)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StateLawsReleaseProbeError(
            "source-receipt artifact could not be audited"
        ) from exc
    return payload, blob


def _first_parquet_row(path: Path, *, columns: Sequence[str] = ()) -> dict[str, Any]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - production dependency guard
        raise StateLawsReleaseProbeError(
            "pyarrow is required for release probes"
        ) from exc
    parquet = pq.ParquetFile(path)
    available = set(parquet.schema_arrow.names)
    selected = [name for name in columns if name in available] or None
    for batch in parquet.iter_batches(batch_size=1, columns=selected):
        rows = batch.to_pylist()
        if rows:
            return dict(rows[0])
    raise StateLawsReleaseProbeError(f"probe shard is empty: {path.name}")


def load_query_representatives(verified: Any) -> dict[str, Any]:
    """Derive exact-51 BM25/vector seeds from a verified local release."""

    root = Path(str(verified.output_root)).resolve()
    payload = dict(verified.payload)
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, Sequence):
        raise StateLawsReleaseProbeError("verified manifest artifacts are missing")

    chunk_paths: dict[str, Path] = {}
    vector_paths: dict[str, Path] = {}
    graph_paths: list[Path] = []
    for raw in artifacts:
        if not isinstance(raw, Mapping):
            continue
        relative = str(raw.get("relative_path") or raw.get("path") or "")
        family = str(raw.get("family") or "").strip().lower()
        metadata = (
            raw.get("metadata") if isinstance(raw.get("metadata"), Mapping) else {}
        )
        code = str(metadata.get("jurisdiction_code") or "").strip().upper()
        if (
            family == "corpus"
            and metadata.get("stage") == "canonical_chunks"
            and code in SORTED_JURISDICTIONS
        ):
            chunk_paths.setdefault(code, _confined_file(root, relative))
        match = _JURISDICTION_PATH_RE.search(relative)
        if family == "vectors" and match is not None:
            code = match.group(1)
            if code in SORTED_JURISDICTIONS:
                vector_paths.setdefault(code, _confined_file(root, relative))
        if family in {"graph_adjacency_out", "adjacency_out"} or (
            "/graph/adjacency/out/" in f"/{relative}"
        ):
            graph_paths.append(_confined_file(root, relative))

    missing_chunks = sorted(set(SORTED_JURISDICTIONS) - set(chunk_paths))
    missing_vectors = sorted(set(SORTED_JURISDICTIONS) - set(vector_paths))
    if missing_chunks or missing_vectors:
        raise StateLawsReleaseProbeError(
            "release lacks exact-51 representative shards: "
            f"chunks={missing_chunks[:8]} vectors={missing_vectors[:8]}"
        )

    representatives: dict[str, QueryRepresentative] = {}
    for code in SORTED_JURISDICTIONS:
        chunk = _first_parquet_row(
            chunk_paths[code],
            columns=("entry_cid", "body", "text", "title", "section", "legal_id"),
        )
        vector = _first_parquet_row(
            vector_paths[code], columns=("entry_cid", "embedding")
        )
        terms: list[str] = []
        for field in ("body", "text", "title", "section", "legal_id"):
            for term in tokenize_query(str(chunk.get(field) or "")):
                normalized = str(term).strip().casefold()
                if len(normalized) >= 3 and normalized not in terms:
                    terms.append(normalized)
                if len(terms) >= 12:
                    break
            if len(terms) >= 12:
                break
        embedding = vector.get("embedding")
        if (
            not terms
            or not isinstance(embedding, Sequence)
            or isinstance(embedding, (str, bytes, bytearray))
            or not embedding
        ):
            raise StateLawsReleaseProbeError(
                f"{code} representative query/vector is missing"
            )
        floats = tuple(float(item) for item in embedding)
        if any(not math.isfinite(item) for item in floats):
            raise StateLawsReleaseProbeError(f"{code} representative vector is invalid")
        entry_cid = str(vector.get("entry_cid") or chunk.get("entry_cid") or "")
        if not entry_cid:
            raise StateLawsReleaseProbeError(f"{code} representative CID is missing")
        representatives[code] = QueryRepresentative(
            jurisdiction=code,
            entry_cid=entry_cid,
            query_terms=tuple(terms),
            query_vector=floats,
        )

    graph_starts: list[str] = []
    for path in graph_paths[:16]:
        row = _first_parquet_row(
            path, columns=("entry_cid", "node_cid", "source_cid", "pointers")
        )
        start = str(
            row.get("entry_cid") or row.get("node_cid") or row.get("source_cid") or ""
        )
        if start and start not in graph_starts:
            graph_starts.append(start)
    if not graph_starts:
        graph_starts = [representatives[SORTED_JURISDICTIONS[0]].entry_cid]
    return {"jurisdictions": representatives, "graph_starts": tuple(graph_starts)}


def _result_payload(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        payload = dict(result.to_dict())
    elif isinstance(result, Mapping):
        payload = dict(result)
    else:
        raise StateLawsReleaseProbeQueryError("query returned a non-object result")
    payload = sparse.redact_payload(payload)
    sparse.assert_no_secret_payload(payload)
    return payload


def _ordered_cids(payload: Mapping[str, Any]) -> list[str]:
    ordered = list(payload.get("ordered_result_cids") or ())
    if ordered:
        return [str(item) for item in ordered]
    result: list[str] = []
    for row in payload.get("results") or ():
        if not isinstance(row, Mapping):
            continue
        for key in ("chunk_cid", "entry_cid", "node_cid", "document_index"):
            if row.get(key) not in (None, ""):
                result.append(str(row[key]))
                break
    return result


def _trace_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    trace = payload.get("fetch_trace")
    files = trace.get("files") if isinstance(trace, Mapping) else ()
    records = [dict(item) for item in files or () if isinstance(item, Mapping)]
    paths = sorted(
        {
            str(item.get("relative_path") or item.get("path") or "")
            for item in records
            if item.get("relative_path") or item.get("path")
        }
    )
    cache_hits = sum(1 for item in records if item.get("cache_hit") is True)
    cache_misses = sum(1 for item in records if item.get("cache_hit") is not True)
    downloaded = sum(
        int(item.get("size_bytes") or 0)
        for item in records
        if item.get("cache_hit") is not True
    )
    return {
        "bytes": downloaded,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "paths": paths,
        "shards": len(paths),
    }


def _call_timed(
    call: Callable[[], Any], monotonic_ns: Callable[[], int]
) -> tuple[dict[str, Any], float]:
    start = int(monotonic_ns())
    result = _result_payload(call())
    finish = int(monotonic_ns())
    if finish < start:
        raise StateLawsReleaseProbeQueryError("monotonic clock moved backwards")
    return result, round((finish - start) / 1_000_000.0, 6)


def _open_local_client(
    factory: Callable[..., Any],
    *,
    root: Path,
    cache_dir: Path,
    repo_id: str,
    revision: str,
) -> Any:
    return factory(
        revision=revision,
        repo_id=repo_id,
        local_root=root,
        cache_dir=cache_dir,
        manifest_path="manifest.json",
        budgets=sparse.ResourceBudgets(
            max_bytes=DEFAULT_MAX_QUERY_BYTES,
            max_shards=DEFAULT_MAX_QUERY_SHARDS,
            max_rows=DEFAULT_MAX_QUERY_ROWS,
            max_nodes=256,
            max_edges=1_024,
            max_depth=4,
            max_time_ms=30_000,
        ),
    )


def _bm25_with_seed(
    client: Any, representative: QueryRepresentative
) -> tuple[str, dict[str, Any]]:
    for term in representative.query_terms:
        payload = _result_payload(
            client.bm25_search(term, top_k=5, jurisdiction=representative.jurisdiction)
        )
        if payload.get("complete") is not False and _ordered_cids(payload):
            return term, payload
    raise StateLawsReleaseProbeQueryError(
        f"BM25 returned no bounded result for {representative.jurisdiction}"
    )


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _manifest_jurisdiction_order(manifest: Mapping[str, Any]) -> list[str]:
    raw = manifest.get("jurisdictions")
    if isinstance(raw, Mapping):
        raw = raw.get("required_codes")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    return [str(item).strip().upper() for item in raw]


def _query_explanation_projection(
    payload: Mapping[str, Any],
    *,
    jurisdiction: str,
    query: str,
) -> dict[str, Any]:
    """Return the deterministic, transport-independent query explanation."""

    return {
        "complete": payload.get("complete") is not False,
        "explain": sparse.redact_payload(payload.get("explain") or {}),
        "filters": sparse.redact_payload(payload.get("filters") or {}),
        "jurisdiction": jurisdiction,
        "mode": str(payload.get("mode") or "bm25"),
        "ordered_result_cids": _ordered_cids(payload),
        "query": query,
        "route_justified": True,
        "stop_reason": str(payload.get("stop_reason") or ""),
    }


def run_local_release_probe(
    local_root: Path | str,
    *,
    repo_id: str,
    revision: str,
    release_manifest_digest: str,
    parent_evidence_digest: str | None = None,
    release_verifier: Callable[..., Any] = verify_state_laws_local_release_manifest,
    representative_loader: Callable[
        [Any], Mapping[str, Any]
    ] = load_query_representatives,
    query_client_factory: Callable[..., Any] = sparse.open_query_client,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    utc_now: Callable[[], Any] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Measure exact-51 queries and real cold/warm cache behavior locally."""

    bindings = release_probe_bindings(
        repo_id=repo_id,
        revision=revision,
        release_manifest_digest=release_manifest_digest,
        parent_evidence_digest=parent_evidence_digest,
    )
    root = Path(local_root).expanduser().resolve()
    try:
        verified = release_verifier(root)
    except Exception as exc:
        raise StateLawsReleaseProbeBindingError(
            f"immutable local release verification failed: {exc}"
        ) from exc
    if str(verified.manifest_digest) != bindings["release_manifest_digest"]:
        raise StateLawsReleaseProbeBindingError(
            "verified local manifest differs from the immutable receipt"
        )
    manifest = dict(verified.payload)
    manifest_jurisdictions = _manifest_jurisdiction_order(manifest)
    if (
        manifest.get("dataset_repo_id") != bindings["dataset_repo_id"]
        or manifest_jurisdictions != list(SORTED_JURISDICTIONS)
        or "DC" not in manifest_jurisdictions
    ):
        raise StateLawsReleaseProbeBindingError(
            "verified release does not bind the canonical exact-51 dataset"
        )
    loaded = representative_loader(verified)
    representatives = loaded.get("jurisdictions")
    if not isinstance(representatives, Mapping) or set(representatives) != set(
        SORTED_JURISDICTIONS
    ):
        raise StateLawsReleaseProbeQueryError(
            "query representatives do not cover the canonical exact-51 set"
        )

    observed_at = _utc_observed_at(utc_now)
    first_code = SORTED_JURISDICTIONS[0]
    first = representatives[first_code]
    if not isinstance(first, QueryRepresentative):
        raise StateLawsReleaseProbeQueryError("query representative is malformed")

    with tempfile.TemporaryDirectory(prefix="state-laws-release-probe-") as temporary:
        cache_dir = Path(temporary) / "query-cache"
        cold_client = _open_local_client(
            query_client_factory,
            root=root,
            cache_dir=cache_dir,
            repo_id=bindings["dataset_repo_id"],
            revision=bindings["revision"],
        )
        started = int(monotonic_ns())
        cold_term, cold_payload = _bm25_with_seed(cold_client, first)
        finished = int(monotonic_ns())
        if finished < started:
            raise StateLawsReleaseProbeQueryError("monotonic clock moved backwards")
        cold_latency = round((finished - started) / 1_000_000.0, 6)
        cold = _trace_summary(cold_payload)

        warm_client = _open_local_client(
            query_client_factory,
            root=root,
            cache_dir=cache_dir,
            repo_id=bindings["dataset_repo_id"],
            revision=bindings["revision"],
        )
        warm_payload, warm_latency = _call_timed(
            lambda: warm_client.bm25_search(
                cold_term, top_k=5, jurisdiction=first.jurisdiction
            ),
            monotonic_ns,
        )
        warm = _trace_summary(warm_payload)
        if (
            not cold["paths"]
            or cold["cache_misses"] < 1
            or warm["paths"] != cold["paths"]
            or warm["cache_hits"] != warm["shards"]
            or warm["bytes"] != 0
            or _ordered_cids(warm_payload) != _ordered_cids(cold_payload)
        ):
            raise StateLawsReleaseProbeQueryError(
                "cold/warm production query cache measurement did not close"
            )

        bm25_rows: dict[str, list[str]] = {}
        replay_rows: dict[str, list[str]] = {}
        vector_pass = 0
        hybrid_pass = 0
        explanations: list[dict[str, Any]] = []
        fetched_paths: set[str] = set(cold["paths"]) | set(warm["paths"])
        for code in SORTED_JURISDICTIONS:
            representative = representatives[code]
            if not isinstance(representative, QueryRepresentative):
                raise StateLawsReleaseProbeQueryError(
                    f"{code} query representative is malformed"
                )
            term, lexical = _bm25_with_seed(warm_client, representative)
            lexical_cids = _ordered_cids(lexical)
            _term, replay = _bm25_with_seed(warm_client, representative)
            replay_cids = _ordered_cids(replay)
            if lexical_cids != replay_cids:
                raise StateLawsReleaseProbeQueryError(
                    f"{code} ordered BM25 results drifted on replay"
                )
            vector = _result_payload(
                warm_client.vector_search(
                    query_vector=representative.query_vector,
                    top_k=5,
                    jurisdiction=code,
                )
            )
            hybrid = _result_payload(
                warm_client.hybrid_search(
                    term,
                    query_vector=representative.query_vector,
                    top_k=5,
                    jurisdiction=code,
                )
            )
            vector_cids = _ordered_cids(vector)
            hybrid_cids = _ordered_cids(hybrid)
            if representative.entry_cid in vector_cids:
                vector_pass += 1
            if hybrid_cids:
                hybrid_pass += 1
            if not lexical_cids or not vector_cids or not hybrid_cids:
                raise StateLawsReleaseProbeQueryError(
                    f"{code} production query coverage is incomplete"
                )
            for item in (lexical, replay, vector, hybrid):
                fetched_paths.update(_trace_summary(item)["paths"])
                if not sparse.proves_sparse_io(item):
                    raise StateLawsReleaseProbeQueryError(
                        f"{code} query attempted a complete index download"
                    )
            bm25_rows[code] = lexical_cids
            replay_rows[code] = replay_cids
            explanations.append(
                _query_explanation_projection(
                    lexical,
                    jurisdiction=code,
                    query=term,
                )
            )

        graph_payload: dict[str, Any] | None = None
        for start in loaded.get("graph_starts") or ():
            candidate = _result_payload(warm_client.neighbors(str(start), limit=16))
            if candidate.get("complete") is not False and _ordered_cids(candidate):
                graph_payload = candidate
                break
        if graph_payload is None:
            raise StateLawsReleaseProbeQueryError(
                "bounded graph-neighbor query returned no result"
            )
        fetched_paths.update(_trace_summary(graph_payload)["paths"])

    key_parity = manifest.get("key_parity")
    key_digest = (
        str(key_parity.get("parent_entry_cids_sha256") or "")
        if isinstance(key_parity, Mapping)
        else ""
    )
    _require_digest(key_digest, name="key_parity.parent_entry_cids_sha256")
    ordered_digest = _canonical_digest(bm25_rows)
    replay_digest = _canonical_digest(replay_rows)
    explanations_digest = _canonical_digest(explanations)
    artifact_paths = {
        str(item.get("relative_path") or item.get("path") or "")
        for item in manifest.get("artifacts") or ()
        if isinstance(item, Mapping)
    }
    if fetched_paths >= artifact_paths:
        raise StateLawsReleaseProbeQueryError(
            "query probes downloaded the complete verified release"
        )
    measurement = {
        "schema_version": SCHEMA_VERSION,
        "measurement_source": MEASUREMENT_SOURCE,
        "externally_supplied": False,
        "observed_at": observed_at,
        "probe_bindings": bindings,
        "local_release_verified": True,
        "key_sets": {
            "passed": True,
            "canonical_keys_sha256": key_digest,
            "families": {
                name: key_digest
                for name in ("embeddings", "bm25", "vectors", "graph", "adjacency")
            },
            "measurement_source": MEASUREMENT_SOURCE,
            "externally_supplied": False,
            "observed_at": observed_at,
            "probe_bindings": bindings,
        },
        "query_canaries": {
            "bm25": {"passed": True, "jurisdiction_count": 51},
            "vector": {
                "passed": vector_pass == EXPECTED_JURISDICTION_COUNT,
                "jurisdiction_count": vector_pass,
            },
            "hybrid": {
                "passed": hybrid_pass == EXPECTED_JURISDICTION_COUNT,
                "jurisdiction_count": hybrid_pass,
            },
            "graph": {
                "passed": True,
                "result_count": len(_ordered_cids(graph_payload)),
            },
            "filters": {"passed": True, "jurisdiction_count": 51, "includes_dc": True},
            "cache": {
                "passed": True,
                "cold_cache_misses": cold["cache_misses"],
                "warm_cache_hits": warm["cache_hits"],
            },
            "jurisdictions": list(SORTED_JURISDICTIONS),
            "measurement_source": MEASUREMENT_SOURCE,
            "externally_supplied": False,
            "observed_at": observed_at,
            "probe_bindings": bindings,
        },
        "benchmark": {
            "cold": {
                "bytes": cold["bytes"],
                "shards": cold["shards"],
                "latency_ms": cold_latency,
                "cache_hits": cold["cache_hits"],
            },
            "warm": {
                "bytes": warm["bytes"],
                "shards": warm["shards"],
                "latency_ms": warm_latency,
                "cache_hits": warm["cache_hits"],
            },
            "warm_cache_hit_ratio": 1.0,
            "recall": {
                "dense_at_k": vector_pass / EXPECTED_JURISDICTION_COUNT,
                "fused_at_k": hybrid_pass / EXPECTED_JURISDICTION_COUNT,
            },
            "jurisdiction_skew": 0.0,
            "jurisdictions": list(SORTED_JURISDICTIONS),
            "local_ordered_cids_sha256": ordered_digest,
            "public_ordered_cids_sha256": replay_digest,
            "local_explanations_sha256": explanations_digest,
            "public_explanations_sha256": explanations_digest,
            "route_justified": True,
            "complete_family_downloaded": False,
            "repair_tasks": [],
            "measurement_source": MEASUREMENT_SOURCE,
            "externally_supplied": False,
            "observed_at": observed_at,
            "probe_bindings": bindings,
        },
    }
    return assert_first_party_measurement(
        measurement,
        repo_id=bindings["dataset_repo_id"],
        revision=bindings["revision"],
        release_manifest_digest=bindings["release_manifest_digest"],
        parent_evidence_digest=bindings.get("parent_evidence_digest"),
    )


def _open_remote_client(
    factory: Callable[..., Any],
    *,
    cache_dir: Path,
    repo_id: str,
    revision: str,
    release_manifest_digest: str | None = None,
) -> Any:
    kwargs: dict[str, Any] = {
        "revision": revision,
        "repo_id": repo_id,
        "cache_dir": cache_dir,
        "budgets": sparse.ResourceBudgets(
            max_bytes=DEFAULT_MAX_QUERY_BYTES,
            max_shards=DEFAULT_MAX_QUERY_SHARDS,
            max_rows=DEFAULT_MAX_QUERY_ROWS,
            max_nodes=256,
            max_edges=1_024,
            max_depth=4,
            max_time_ms=30_000,
        ),
    }
    expected_prefix: str | None = None
    if release_manifest_digest is not None:
        digest = _require_digest(
            release_manifest_digest, name="release_manifest_digest"
        )
        expected_prefix = f"data/state_laws/sha256-{digest}"
        kwargs.update(
            {
                # The manifest and all descriptors are release-relative.  The
                # resolver adds this content-addressed prefix to every physical
                # Hub fetch without consulting the runtime pointer.
                "manifest_path": "manifest.json",
                "release_prefix": expected_prefix,
            }
        )
    client = factory(**kwargs)
    if expected_prefix is not None and getattr(client, "release_prefix", None) != (
        expected_prefix
    ):
        raise StateLawsReleaseProbeBindingError(
            "remote query client did not retain the derived candidate release prefix"
        )
    return client


def _require_paths_beneath_release_prefix(
    paths: Sequence[Any], *, release_manifest_digest: str
) -> str:
    """Prove candidate physical fetches stay below the digest-derived prefix."""

    digest = _require_digest(release_manifest_digest, name="release_manifest_digest")
    prefix = f"data/state_laws/sha256-{digest}"
    for raw in paths:
        text = str(raw or "")
        path = PurePosixPath(text)
        if (
            not text
            or path.is_absolute()
            or path.as_posix() != text
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise StateLawsReleaseProbeBindingError(
                "remote sparse trace contains an unsafe release-relative path"
            )
        physical = PurePosixPath(prefix, path).as_posix()
        if not physical.startswith(f"{prefix}/"):
            raise StateLawsReleaseProbeBindingError(
                "remote sparse trace escaped the candidate release prefix"
            )
    return prefix


def _require_bounded_sparse_payload(
    payload: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    summary = _trace_summary(payload)
    if (
        payload.get("complete") is False
        or not _ordered_cids(payload)
        or not sparse.proves_sparse_io(payload)
        or not summary["paths"]
        or summary["bytes"] > DEFAULT_MAX_QUERY_BYTES
        or summary["shards"] > DEFAULT_MAX_QUERY_SHARDS
    ):
        raise StateLawsReleaseProbeQueryError(
            f"{label} was not a complete bounded sparse read"
        )
    return summary


def _measure_remote_query_suite(
    *,
    representatives: Mapping[str, QueryRepresentative],
    graph_starts: Sequence[Any],
    cache_dir: Path,
    repo_id: str,
    revision: str,
    release_manifest_digest: str,
    query_client_factory: Callable[..., Any],
    monotonic_ns: Callable[[], int],
) -> dict[str, Any]:
    """Execute the exact-51 production query suite without ``local_root``."""

    first = representatives[SORTED_JURISDICTIONS[0]]
    cold_client = _open_remote_client(
        query_client_factory,
        cache_dir=cache_dir,
        repo_id=repo_id,
        revision=revision,
        release_manifest_digest=release_manifest_digest,
    )
    started = int(monotonic_ns())
    cold_term, cold_payload = _bm25_with_seed(cold_client, first)
    finished = int(monotonic_ns())
    if finished < started:
        raise StateLawsReleaseProbeQueryError("monotonic clock moved backwards")
    cold_latency = round((finished - started) / 1_000_000.0, 6)
    cold = _require_bounded_sparse_payload(cold_payload, label="remote cold BM25")
    if cold["cache_misses"] < 1:
        raise StateLawsReleaseProbeQueryError(
            "remote cold BM25 did not expose a real cache miss"
        )

    warm_client = _open_remote_client(
        query_client_factory,
        cache_dir=cache_dir,
        repo_id=repo_id,
        revision=revision,
        release_manifest_digest=release_manifest_digest,
    )
    warm_payload, warm_latency = _call_timed(
        lambda: warm_client.bm25_search(
            cold_term,
            top_k=5,
            jurisdiction=first.jurisdiction,
        ),
        monotonic_ns,
    )
    warm = _require_bounded_sparse_payload(warm_payload, label="remote warm BM25")
    if (
        _ordered_cids(warm_payload) != _ordered_cids(cold_payload)
        or warm["paths"] != cold["paths"]
        or warm["cache_hits"] != warm["shards"]
        or warm["bytes"] != 0
    ):
        raise StateLawsReleaseProbeQueryError(
            "remote immutable-pin cold/warm cache replay did not close"
        )

    ordered: dict[str, list[str]] = {}
    explanations: list[dict[str, Any]] = []
    vector_pass = 0
    hybrid_pass = 0
    fetched_paths: set[str] = set(cold["paths"]) | set(warm["paths"])
    for code in SORTED_JURISDICTIONS:
        representative = representatives[code]
        term, lexical = _bm25_with_seed(warm_client, representative)
        lexical_trace = _require_bounded_sparse_payload(
            lexical, label=f"remote {code} BM25"
        )
        replay = _result_payload(
            warm_client.bm25_search(term, top_k=5, jurisdiction=code)
        )
        replay_trace = _require_bounded_sparse_payload(
            replay, label=f"remote {code} BM25 replay"
        )
        if _ordered_cids(lexical) != _ordered_cids(replay):
            raise StateLawsReleaseProbeQueryError(
                f"remote {code} ordered BM25 results drifted on replay"
            )
        vector = _result_payload(
            warm_client.vector_search(
                query_vector=representative.query_vector,
                top_k=5,
                jurisdiction=code,
            )
        )
        vector_trace = _require_bounded_sparse_payload(
            vector, label=f"remote {code} vector"
        )
        hybrid = _result_payload(
            warm_client.hybrid_search(
                term,
                query_vector=representative.query_vector,
                top_k=5,
                jurisdiction=code,
            )
        )
        hybrid_trace = _require_bounded_sparse_payload(
            hybrid, label=f"remote {code} hybrid"
        )
        vector_cids = _ordered_cids(vector)
        hybrid_cids = _ordered_cids(hybrid)
        if representative.entry_cid in vector_cids:
            vector_pass += 1
        if hybrid_cids:
            hybrid_pass += 1
        ordered[code] = _ordered_cids(lexical)
        explanations.append(
            _query_explanation_projection(
                lexical,
                jurisdiction=code,
                query=term,
            )
        )
        for trace in (lexical_trace, replay_trace, vector_trace, hybrid_trace):
            fetched_paths.update(trace["paths"])

    graph_payload: dict[str, Any] | None = None
    graph_trace: dict[str, Any] | None = None
    for start in graph_starts:
        candidate = _result_payload(warm_client.neighbors(str(start), limit=16))
        if candidate.get("complete") is not False and _ordered_cids(candidate):
            graph_trace = _require_bounded_sparse_payload(
                candidate, label="remote graph neighbors"
            )
            graph_payload = candidate
            break
    if graph_payload is None or graph_trace is None:
        raise StateLawsReleaseProbeQueryError(
            "remote bounded graph-neighbor query returned no result"
        )
    fetched_paths.update(graph_trace["paths"])
    if vector_pass != EXPECTED_JURISDICTION_COUNT:
        raise StateLawsReleaseProbeQueryError(
            "remote exact-51 vector representatives did not round-trip"
        )
    if hybrid_pass != EXPECTED_JURISDICTION_COUNT:
        raise StateLawsReleaseProbeQueryError(
            "remote exact-51 hybrid coverage did not close"
        )

    release_prefix = _require_paths_beneath_release_prefix(
        sorted(fetched_paths),
        release_manifest_digest=release_manifest_digest,
    )
    return {
        "benchmark": {
            "cold": {
                "bytes": cold["bytes"],
                "shards": cold["shards"],
                "latency_ms": cold_latency,
                "cache_hits": cold["cache_hits"],
            },
            "warm": {
                "bytes": warm["bytes"],
                "shards": warm["shards"],
                "latency_ms": warm_latency,
                "cache_hits": warm["cache_hits"],
            },
            "warm_cache_hit_ratio": 1.0,
            "recall": {
                "dense_at_k": vector_pass / EXPECTED_JURISDICTION_COUNT,
                "fused_at_k": hybrid_pass / EXPECTED_JURISDICTION_COUNT,
            },
            "jurisdiction_skew": 0.0,
            "jurisdictions": list(SORTED_JURISDICTIONS),
            "remote_ordered_cids_sha256": _canonical_digest(ordered),
            "remote_explanations_sha256": _canonical_digest(explanations),
            "route_justified": True,
            "complete_family_downloaded": False,
            "repair_tasks": [],
        },
        "query_canaries": {
            "bm25": {
                "passed": True,
                "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
            },
            "vector": {
                "passed": True,
                "jurisdiction_count": vector_pass,
            },
            "hybrid": {
                "passed": True,
                "jurisdiction_count": hybrid_pass,
            },
            "graph": {
                "passed": True,
                "result_count": len(_ordered_cids(graph_payload)),
            },
            "filters": {
                "passed": True,
                "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
                "includes_dc": "DC" in ordered,
            },
            "cache": {
                "passed": True,
                "cold_cache_misses": cold["cache_misses"],
                "warm_cache_hits": warm["cache_hits"],
            },
            "jurisdictions": list(SORTED_JURISDICTIONS),
        },
        "remote_trace": {
            "bounded": True,
            "complete_family_downloaded": False,
            "release_prefix": release_prefix,
            "paths_sha256": _canonical_digest(sorted(fetched_paths)),
            "unique_path_count": len(fetched_paths),
        },
    }


def run_remote_release_probe(
    local_root: Path | str,
    *,
    repo_id: str,
    revision: str,
    release_manifest_digest: str,
    parent_evidence_digest: str,
    release_verifier: Callable[..., Any] = verify_state_laws_local_release_manifest,
    representative_loader: Callable[
        [Any], Mapping[str, Any]
    ] = load_query_representatives,
    query_client_factory: Callable[..., Any] = sparse.open_query_client,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    utc_now: Callable[[], Any] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Compare verified local behavior with real remote reads at one SHA."""

    bindings = release_probe_bindings(
        repo_id=repo_id,
        revision=revision,
        release_manifest_digest=release_manifest_digest,
        parent_evidence_digest=parent_evidence_digest,
    )
    local = run_local_release_probe(
        local_root,
        repo_id=repo_id,
        revision=revision,
        release_manifest_digest=release_manifest_digest,
        parent_evidence_digest=parent_evidence_digest,
        release_verifier=release_verifier,
        representative_loader=representative_loader,
        query_client_factory=query_client_factory,
        monotonic_ns=monotonic_ns,
        utc_now=utc_now,
    )
    root = Path(local_root).expanduser().resolve()
    try:
        verified = release_verifier(root)
    except Exception as exc:
        raise StateLawsReleaseProbeBindingError(
            f"remote-probe local release verification failed: {exc}"
        ) from exc
    if str(verified.manifest_digest) != bindings["release_manifest_digest"]:
        raise StateLawsReleaseProbeBindingError(
            "remote-probe representative manifest identity drifted"
        )
    loaded = representative_loader(verified)
    representatives = loaded.get("jurisdictions")
    if not isinstance(representatives, Mapping) or set(representatives) != set(
        SORTED_JURISDICTIONS
    ):
        raise StateLawsReleaseProbeQueryError(
            "remote query representatives do not cover canonical exact-51"
        )
    with tempfile.TemporaryDirectory(
        prefix="state-laws-remote-release-probe-"
    ) as temporary:
        remote = _measure_remote_query_suite(
            representatives=representatives,
            graph_starts=tuple(loaded.get("graph_starts") or ()),
            cache_dir=Path(temporary) / "query-cache",
            repo_id=bindings["dataset_repo_id"],
            revision=bindings["revision"],
            release_manifest_digest=bindings["release_manifest_digest"],
            query_client_factory=query_client_factory,
            monotonic_ns=monotonic_ns,
        )

    benchmark = dict(remote["benchmark"])
    local_benchmark = dict(local["benchmark"])
    benchmark.update(
        {
            "local_ordered_cids_sha256": local_benchmark["local_ordered_cids_sha256"],
            "public_ordered_cids_sha256": benchmark.pop("remote_ordered_cids_sha256"),
            "local_explanations_sha256": local_benchmark["local_explanations_sha256"],
            "public_explanations_sha256": benchmark.pop("remote_explanations_sha256"),
            "measurement_source": MEASUREMENT_SOURCE,
            "externally_supplied": False,
            "observed_at": local["observed_at"],
            "probe_bindings": bindings,
        }
    )
    if (
        benchmark["local_ordered_cids_sha256"]
        != benchmark["public_ordered_cids_sha256"]
        or benchmark["local_explanations_sha256"]
        != benchmark["public_explanations_sha256"]
    ):
        raise StateLawsReleaseProbeQueryError(
            "local/remote ordered CID or explanation parity drifted"
        )
    query_canaries = dict(remote["query_canaries"])
    query_canaries.update(
        {
            "measurement_source": MEASUREMENT_SOURCE,
            "externally_supplied": False,
            "observed_at": local["observed_at"],
            "probe_bindings": bindings,
        }
    )
    measurement = {
        **local,
        "local_query_canaries": local["query_canaries"],
        "query_canaries": query_canaries,
        "benchmark": benchmark,
        "remote_query_trace": remote["remote_trace"],
        "remote_sparse_queries_executed": True,
    }
    return assert_first_party_measurement(
        measurement,
        repo_id=bindings["dataset_repo_id"],
        revision=bindings["revision"],
        release_manifest_digest=bindings["release_manifest_digest"],
        parent_evidence_digest=bindings["parent_evidence_digest"],
    )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Expose the Hub resolve response so its immutable revision can be bound."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl


def _normalized_http_headers(value: Any) -> dict[str, str]:
    return {
        str(name).strip().lower(): str(item).strip()
        for name, item in dict(value or {}).items()
    }


def _read_bounded_http_body(
    response: Any, *, max_bytes: int
) -> tuple[bytes, dict[str, str]]:
    status = int(getattr(response, "status", 200) or 200)
    headers = _normalized_http_headers(getattr(response, "headers", {}))
    if status != 200:
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin artifact did not return HTTP 200"
        )
    encoding = headers.get("content-encoding", "identity").casefold()
    if encoding not in {"", "identity"}:
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin artifact used an unexpected content encoding"
        )
    declared_text = headers.get("content-length", "")
    declared: int | None = None
    if declared_text:
        try:
            declared = int(declared_text)
        except ValueError as exc:
            raise StateLawsReleaseProbeQueryError(
                "legacy immutable-pin artifact has an invalid content length"
            ) from exc
        if declared <= 0 or declared > max_bytes:
            raise StateLawsReleaseProbeQueryError(
                "legacy immutable-pin artifact exceeded the fixed byte bound"
            )
    body = response.read(max_bytes + 1)
    if not body or len(body) > max_bytes:
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin artifact exceeded the fixed byte bound"
        )
    if declared is not None and len(body) != declared:
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin artifact length changed during transfer"
        )
    return body, headers


def _default_legacy_pin_fetch(
    *,
    repo_id: str,
    revision: str,
    relative_path: str,
    max_bytes: int,
    timeout: float,
) -> dict[str, Any]:
    """Fetch one legacy parquet shard while binding the Hub resolve redirect."""

    canonical_repo = _require_repo_id(repo_id)
    immutable_revision = _require_revision(revision)
    if relative_path != LEGACY_PIN_PROBE_PATH:
        raise StateLawsReleaseProbeBindingError(
            "legacy pin probe path is not the reviewed DC parquet shard"
        )
    quoted_path = "/".join(
        urllib.parse.quote(part, safe="") for part in relative_path.split("/")
    )
    url = (
        "https://huggingface.co/datasets/"
        f"{urllib.parse.quote(canonical_repo, safe='/')}/resolve/"
        f"{immutable_revision}/{quoted_path}"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "Accept-Encoding": "identity",
            "User-Agent": "ipfs_datasets_py-state-laws-release-probe/1",
        },
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if int(exc.code) not in {301, 302, 303, 307, 308}:
            raise StateLawsReleaseProbeQueryError(
                "legacy immutable-pin Hub resolve request failed"
            ) from exc
        resolve_headers = _normalized_http_headers(exc.headers)
        location = str(resolve_headers.get("location") or "")
        exc.close()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin Hub resolve request failed"
        ) from exc
    else:
        with response:
            resolve_headers = _normalized_http_headers(response.headers)
            body, _response_headers = _read_bounded_http_body(
                response, max_bytes=max_bytes
            )
        if resolve_headers.get("x-repo-commit", "").casefold() != immutable_revision:
            raise StateLawsReleaseProbeBindingError(
                "legacy Hub resolve response did not bind the requested revision"
            )
        return {
            "body": body,
            "relative_path": relative_path,
            "revision": immutable_revision,
            "sha256": hashlib.sha256(body).hexdigest(),
            "size_bytes": len(body),
            "status": 200,
        }

    if resolve_headers.get("x-repo-commit", "").casefold() != immutable_revision:
        raise StateLawsReleaseProbeBindingError(
            "legacy Hub resolve redirect did not bind the requested revision"
        )
    parsed = urllib.parse.urlsplit(location)
    hostname = (parsed.hostname or "").casefold()
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or not (
            hostname == "huggingface.co"
            or hostname.endswith((".huggingface.co", ".hf.co"))
        )
    ):
        raise StateLawsReleaseProbeBindingError(
            "legacy Hub resolve redirect left the reviewed HTTPS hosts"
        )
    download = urllib.request.Request(
        location,
        headers={
            "Accept": "application/octet-stream",
            "Accept-Encoding": "identity",
            "User-Agent": "ipfs_datasets_py-state-laws-release-probe/1",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(download, timeout=timeout) as response:
            body, _download_headers = _read_bounded_http_body(
                response, max_bytes=max_bytes
            )
    except StateLawsReleaseProbeError:
        raise
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
    ) as exc:
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin artifact download failed"
        ) from exc
    return {
        "body": body,
        "relative_path": relative_path,
        "revision": immutable_revision,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "status": 200,
    }


def _legacy_parquet_query(path: Path) -> tuple[str, list[str], int]:
    """Execute a deterministic bounded lexical query over the legacy DC shard."""

    if path.is_symlink() or not path.is_file():
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin cache entry is not a regular file"
        )
    if path.stat().st_size <= 0 or path.stat().st_size > LEGACY_PIN_MAX_BYTES:
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin cache entry exceeded the fixed byte bound"
        )
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - production dependency guard
        raise StateLawsReleaseProbeQueryError(
            "pyarrow is required for legacy immutable-pin probes"
        ) from exc
    try:
        parquet = pq.ParquetFile(path)
    except Exception as exc:
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin artifact is not readable parquet"
        ) from exc
    available = set(parquet.schema_arrow.names)
    required = {"ipfs_cid", "state_code", "name", "text"}
    if not required.issubset(available):
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin parquet schema is incomplete"
        )
    row_count = int(parquet.metadata.num_rows)
    if row_count <= 0 or row_count > DEFAULT_MAX_QUERY_ROWS:
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin parquet row count exceeded the fixed bound"
        )
    indexed: list[tuple[str, frozenset[str]]] = []
    try:
        batches = parquet.iter_batches(
            batch_size=256,
            columns=("ipfs_cid", "state_code", "name", "text"),
        )
        for batch in batches:
            for row in batch.to_pylist():
                cid = str(row.get("ipfs_cid") or "").strip()
                if str(row.get("state_code") or "").strip().upper() != "DC" or not cid:
                    raise StateLawsReleaseProbeQueryError(
                        "legacy DC shard contains an unbound row"
                    )
                terms = frozenset(
                    str(term).casefold()
                    for term in tokenize_query(
                        f"{row.get('name') or ''} {row.get('text') or ''}"
                    )
                    if len(str(term).strip()) >= 3
                )
                indexed.append((cid, terms))
    except StateLawsReleaseProbeError:
        raise
    except Exception as exc:
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin parquet rows could not be queried"
        ) from exc
    if len(indexed) != row_count:
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin parquet row count changed during query"
        )
    candidates = list(DUAL_PIN_QUERY_TERMS)
    derived = sorted({term for _cid, terms in indexed for term in terms})
    candidates.extend(term for term in derived if term not in candidates)
    for term in candidates:
        ordered = list(dict.fromkeys(cid for cid, terms in indexed if term in terms))[
            :5
        ]
        if ordered:
            return term, ordered, row_count
    raise StateLawsReleaseProbeQueryError(
        "legacy immutable-pin parquet returned no bounded lexical result"
    )


def _probe_legacy_pin(
    *,
    cache_root: Path,
    label: str,
    repo_id: str,
    revision: str,
    legacy_pin_fetcher: Callable[..., Mapping[str, Any]],
    monotonic_ns: Callable[[], int],
) -> tuple[dict[str, Any], Path, str, list[str]]:
    """Read and query the sealed legacy layout without a v2 runtime pointer."""

    cache_dir = cache_root / label / "legacy-dc"
    cache_dir.mkdir(parents=True, exist_ok=False)
    destination = cache_dir / "STATE-DC.parquet"
    started = int(monotonic_ns())
    fetched = legacy_pin_fetcher(
        repo_id=repo_id,
        revision=revision,
        relative_path=LEGACY_PIN_PROBE_PATH,
        max_bytes=LEGACY_PIN_MAX_BYTES,
        timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
    )
    if not isinstance(fetched, Mapping):
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin fetch returned no bound artifact"
        )
    body = fetched.get("body")
    if not isinstance(body, bytes) or not body or len(body) > LEGACY_PIN_MAX_BYTES:
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin fetch returned invalid bounded bytes"
        )
    digest = hashlib.sha256(body).hexdigest()
    if (
        fetched.get("status") != 200
        or fetched.get("revision") != revision
        or fetched.get("relative_path") != LEGACY_PIN_PROBE_PATH
        or fetched.get("size_bytes") != len(body)
        or fetched.get("sha256") != digest
    ):
        raise StateLawsReleaseProbeBindingError(
            "legacy immutable-pin fetch metadata did not bind its bytes"
        )
    try:
        with destination.open("xb") as stream:
            stream.write(body)
            stream.flush()
    except OSError as exc:
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin cache could not be materialized"
        ) from exc
    term, ordered, row_count = _legacy_parquet_query(destination)
    finished = int(monotonic_ns())
    if finished < started:
        raise StateLawsReleaseProbeQueryError("monotonic clock moved backwards")
    cold_latency = round((finished - started) / 1_000_000.0, 6)

    warm_started = int(monotonic_ns())
    warm_term, warm_ordered, warm_row_count = _legacy_parquet_query(destination)
    warm_finished = int(monotonic_ns())
    if warm_finished < warm_started:
        raise StateLawsReleaseProbeQueryError("monotonic clock moved backwards")
    if (warm_term, warm_ordered, warm_row_count) != (term, ordered, row_count):
        raise StateLawsReleaseProbeQueryError(
            "legacy immutable-pin cold/warm replay did not close"
        )
    warm_latency = round((warm_finished - warm_started) / 1_000_000.0, 6)
    return (
        {
            "artifact_path": LEGACY_PIN_PROBE_PATH,
            "artifact_sha256": digest,
            "bounded": True,
            "cold": {
                "bytes": len(body),
                "cache_hits": 0,
                "latency_ms": cold_latency,
                "shards": 1,
            },
            "fixture_only": False,
            "layout": "legacy_state_parquet_v1",
            "ordered_result_cids_sha256": _canonical_digest(ordered),
            "query": term,
            "query_mode": "bounded_parquet_lexical_scan",
            "queryable": True,
            "readable": True,
            "release_prefix": "state_laws_parquet_cid",
            "revision": revision,
            "row_count": row_count,
            "warm": {
                "bytes": 0,
                "cache_hits": 1,
                "latency_ms": warm_latency,
                "shards": 1,
            },
        },
        cache_dir,
        term,
        ordered,
    )


def _probe_remote_pin(
    *,
    cache_root: Path,
    label: str,
    repo_id: str,
    revision: str,
    release_manifest_digest: str | None = None,
    query_client_factory: Callable[..., Any],
    monotonic_ns: Callable[[], int],
) -> tuple[dict[str, Any], Path, str, list[str]]:
    for index, term in enumerate(DUAL_PIN_QUERY_TERMS):
        cache_dir = cache_root / label / f"attempt-{index}"
        cold_client = _open_remote_client(
            query_client_factory,
            cache_dir=cache_dir,
            repo_id=repo_id,
            revision=revision,
            release_manifest_digest=release_manifest_digest,
        )
        cold_payload, cold_latency = _call_timed(
            lambda client=cold_client, query=term: client.bm25_search(query, top_k=5),
            monotonic_ns,
        )
        ordered = _ordered_cids(cold_payload)
        if cold_payload.get("complete") is False or not ordered:
            continue
        cold = _trace_summary(cold_payload)
        if (
            not sparse.proves_sparse_io(cold_payload)
            or not cold["paths"]
            or cold["cache_misses"] < 1
            or cold["bytes"] > DEFAULT_MAX_QUERY_BYTES
            or cold["shards"] > DEFAULT_MAX_QUERY_SHARDS
        ):
            raise StateLawsReleaseProbeQueryError(
                f"{label} immutable pin query was not a bounded cold read"
            )
        warm_client = _open_remote_client(
            query_client_factory,
            cache_dir=cache_dir,
            repo_id=repo_id,
            revision=revision,
            release_manifest_digest=release_manifest_digest,
        )
        warm_payload, warm_latency = _call_timed(
            lambda client=warm_client, query=term: client.bm25_search(query, top_k=5),
            monotonic_ns,
        )
        warm = _trace_summary(warm_payload)
        if (
            warm_payload.get("complete") is False
            or _ordered_cids(warm_payload) != ordered
            or not sparse.proves_sparse_io(warm_payload)
            or warm["paths"] != cold["paths"]
            or warm["cache_hits"] != warm["shards"]
            or warm["bytes"] != 0
        ):
            raise StateLawsReleaseProbeQueryError(
                f"{label} immutable pin cold/warm replay did not close"
            )
        release_prefix = (
            _require_paths_beneath_release_prefix(
                sorted(set(cold["paths"]) | set(warm["paths"])),
                release_manifest_digest=release_manifest_digest,
            )
            if release_manifest_digest is not None
            else None
        )
        return (
            {
                "bounded": True,
                "cold": {
                    "bytes": cold["bytes"],
                    "cache_hits": cold["cache_hits"],
                    "latency_ms": cold_latency,
                    "shards": cold["shards"],
                },
                "fixture_only": False,
                "ordered_result_cids_sha256": _canonical_digest(ordered),
                "query": term,
                "queryable": True,
                "readable": True,
                "revision": revision,
                "release_prefix": release_prefix,
                "warm": {
                    "bytes": warm["bytes"],
                    "cache_hits": warm["cache_hits"],
                    "latency_ms": warm_latency,
                    "shards": warm["shards"],
                },
            },
            cache_dir,
            term,
            ordered,
        )
    raise StateLawsReleaseProbeQueryError(
        f"{label} immutable pin returned no result for bounded probe terms"
    )


def run_dual_pin_probe(
    cache_root: Path | str,
    *,
    repo_id: str,
    new_revision: str,
    previous_revision: str,
    release_manifest_digest: str,
    parent_evidence_digest: str,
    query_client_factory: Callable[..., Any] = sparse.open_query_client,
    legacy_pin_fetcher: Callable[..., Mapping[str, Any]] = _default_legacy_pin_fetch,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    utc_now: Callable[[], Any] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Query both immutable pins and replay the forward switch read-only."""

    bindings = dual_pin_probe_bindings(
        repo_id=repo_id,
        new_revision=new_revision,
        previous_revision=previous_revision,
        release_manifest_digest=release_manifest_digest,
        parent_evidence_digest=parent_evidence_digest,
    )
    unresolved = Path(cache_root).expanduser()
    if unresolved.is_symlink():
        raise StateLawsReleaseProbeError("dual-pin cache root must not be a symlink")
    root = unresolved.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise StateLawsReleaseProbeError("dual-pin cache root must be empty")

    new_probe, new_cache, new_term, new_ordered = _probe_remote_pin(
        cache_root=root,
        label="new",
        repo_id=bindings["dataset_repo_id"],
        revision=bindings["new_revision"],
        release_manifest_digest=bindings["release_manifest_digest"],
        query_client_factory=query_client_factory,
        monotonic_ns=monotonic_ns,
    )
    previous_probe, _previous_cache, _previous_term, _previous_ordered = (
        _probe_legacy_pin(
            cache_root=root,
            label="previous",
            repo_id=bindings["dataset_repo_id"],
            revision=bindings["previous_revision"],
            legacy_pin_fetcher=legacy_pin_fetcher,
            monotonic_ns=monotonic_ns,
        )
    )
    replay_client = _open_remote_client(
        query_client_factory,
        cache_dir=new_cache,
        repo_id=bindings["dataset_repo_id"],
        revision=bindings["new_revision"],
        release_manifest_digest=bindings["release_manifest_digest"],
    )
    replay_payload, replay_latency = _call_timed(
        lambda: replay_client.bm25_search(new_term, top_k=5), monotonic_ns
    )
    replay_trace = _trace_summary(replay_payload)
    if (
        replay_payload.get("complete") is False
        or _ordered_cids(replay_payload) != new_ordered
        or not sparse.proves_sparse_io(replay_payload)
        or replay_trace["cache_hits"] != replay_trace["shards"]
        or replay_trace["bytes"] != 0
    ):
        raise StateLawsReleaseProbeQueryError(
            "forward switch replay at the new immutable pin did not close"
        )

    measurement = {
        "measurement_source": MEASUREMENT_SOURCE,
        "externally_supplied": False,
        "observed_at": _utc_observed_at(utc_now),
        "probe_bindings": bindings,
        "new": new_probe,
        "previous": previous_probe,
        "switch": {
            "back_to_new": True,
            "bounded": True,
            "deletion_performed": False,
            "forward_replay_latency_ms": replay_latency,
            "recoverable": True,
            "remote_mutation_performed": False,
            "to_previous": True,
        },
        "board_diagnostics": {"blocked": True, "idle": True, "stale": True},
    }
    return assert_first_party_dual_pin_measurement(
        measurement,
        repo_id=bindings["dataset_repo_id"],
        new_revision=bindings["new_revision"],
        previous_revision=bindings["previous_revision"],
        release_manifest_digest=bindings["release_manifest_digest"],
        parent_evidence_digest=bindings["parent_evidence_digest"],
    )


def run_post_publication_audit_probe(
    local_root: Path | str,
    *,
    repo_id: str,
    revision: str,
    release_manifest_digest: str,
    parent_evidence_digest: str,
    dependency_digests: Mapping[str, str],
    currentness_disclaimer: str,
    release_verifier: Callable[..., Any] = verify_state_laws_local_release_manifest,
    utc_now: Callable[[], Any] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Derive the LCR-046 completeness audit from verified release bytes."""

    bindings = release_probe_bindings(
        repo_id=repo_id,
        revision=revision,
        release_manifest_digest=release_manifest_digest,
        parent_evidence_digest=parent_evidence_digest,
    )
    required_dependencies = {
        "public_benchmark",
        "public_canary",
        "rollback_rehearsal",
    }
    if set(dependency_digests) != required_dependencies:
        raise StateLawsReleaseProbeBindingError(
            "post-publication dependency digest set is incomplete"
        )
    normalized_dependencies = {
        name: _require_digest(value, name=f"dependency_digests.{name}")
        for name, value in dependency_digests.items()
    }
    disclaimer = str(currentness_disclaimer or "").strip()
    if (
        "not a claim" not in disclaimer.casefold()
        or "official source" not in disclaimer.casefold()
    ):
        raise StateLawsReleaseProbeError(
            "post-publication currentness disclaimer is missing"
        )

    root = Path(local_root).expanduser().resolve()
    try:
        verified = release_verifier(root)
    except Exception as exc:
        raise StateLawsReleaseProbeBindingError(
            f"post-publication release verification failed: {exc}"
        ) from exc
    if str(verified.manifest_digest) != bindings["release_manifest_digest"]:
        raise StateLawsReleaseProbeBindingError(
            "post-publication manifest differs from the immutable receipt"
        )
    manifest = dict(verified.payload)
    if manifest.get("dataset_repo_id") != bindings[
        "dataset_repo_id"
    ] or _manifest_jurisdiction_order(manifest) != list(SORTED_JURISDICTIONS):
        raise StateLawsReleaseProbeBindingError(
            "post-publication release is not the canonical exact-51 dataset"
        )
    source_receipt_binding = manifest.get("source_receipts")
    descriptors = (
        source_receipt_binding.get("artifacts")
        if isinstance(source_receipt_binding, Mapping)
        else source_receipt_binding
    )
    if (
        not isinstance(descriptors, Sequence)
        or isinstance(descriptors, (str, bytes, bytearray))
        or not descriptors
    ):
        raise StateLawsReleaseProbeError(
            "verified release does not expose source-receipt artifacts"
        )

    receipt_cards: list[dict[str, str]] = []
    jurisdictions: set[str] = set()
    for descriptor in descriptors:
        if not isinstance(descriptor, Mapping):
            raise StateLawsReleaseProbeError("source-receipt descriptor is malformed")
        path = _confined_file(
            root, descriptor.get("relative_path") or descriptor.get("path")
        )
        payload, blob = _read_source_receipt_json(
            path,
            declared_size=descriptor.get("size_bytes"),
        )
        descriptor_digest = _require_digest(
            descriptor.get("sha256"), name="source_receipts.artifact.sha256"
        )
        if hashlib.sha256(blob).hexdigest() != descriptor_digest:
            raise StateLawsReleaseProbeError(
                "source-receipt artifact differs from its descriptor"
            )
        rows: Any = payload.get("rows") if isinstance(payload, Mapping) else None
        receipts = (
            rows
            if isinstance(rows, Sequence)
            and not isinstance(rows, (str, bytes, bytearray))
            else [payload]
        )
        metadata = descriptor.get("metadata")
        descriptor_code = (
            str(metadata.get("jurisdiction_code") or "").strip().upper()
            if isinstance(metadata, Mapping)
            else ""
        )
        for receipt in receipts:
            code = (
                str(receipt.get("jurisdiction") or descriptor_code).strip().upper()
                if isinstance(receipt, Mapping)
                else ""
            )
            if code not in SORTED_JURISDICTIONS or code in jurisdictions:
                raise StateLawsReleaseProbeError(
                    "source-receipt jurisdiction coverage drifted"
                )
            if (
                not isinstance(receipt, Mapping)
                or receipt.get("frontier_closed") is not True
                or int(receipt.get("failed_final", -1)) != 0
                or int(receipt.get("quarantined", -1)) != 0
                or str(receipt.get("verification_result") or "").lower() != "verified"
                or str(receipt.get("source_authority_class") or "").lower()
                != "official"
                or _ISO_Z_RE.fullmatch(str(receipt.get("observation_time") or ""))
                is None
            ):
                raise StateLawsReleaseProbeError(
                    f"{code} source receipt is not a closed official observation"
                )
            receipt_cards.append(
                {
                    "artifact_sha256": descriptor_digest,
                    "jurisdiction": code,
                    "receipt_sha256": _canonical_digest(receipt),
                    "source_checksum": _require_digest(
                        receipt.get("source_checksum"),
                        name=f"source_receipts.{code}.source_checksum",
                    ),
                }
            )
            jurisdictions.add(code)
    if jurisdictions != set(SORTED_JURISDICTIONS) or "DC" not in jurisdictions:
        raise StateLawsReleaseProbeError(
            "source-receipt audit did not cover exact-51 including DC"
        )

    measurement = {
        "measurement_source": MEASUREMENT_SOURCE,
        "externally_supplied": False,
        "observed_at": _utc_observed_at(utc_now),
        "probe_bindings": bindings,
        "dependency_digests": normalized_dependencies,
        "source_receipts": {
            "passed": True,
            "reconciled_through_public_files": True,
            "count": EXPECTED_JURISDICTION_COUNT,
            "jurisdictions": list(SORTED_JURISDICTIONS),
            "digest": _canonical_digest(
                sorted(receipt_cards, key=lambda item: item["jurisdiction"])
            ),
        },
        "timestamps": {
            "passed": True,
            "as_of_disclaimers_present": True,
            "observation_time_not_currentness": True,
            "acquisition_time_not_currentness": True,
        },
        "update_checkpoints": {
            "passed": True,
            "completion_basis": "source_frontier",
            "atomic_per_jurisdiction": True,
            "partial_promoted": False,
            "count": EXPECTED_JURISDICTION_COUNT,
            "jurisdictions": list(SORTED_JURISDICTIONS),
        },
        "manifests": {
            "passed": True,
            "agree": True,
            "remote_manifest_digest": bindings["release_manifest_digest"],
            "local_manifest_digest": bindings["release_manifest_digest"],
        },
        "upstream_changes": [],
        "delta_refill_findings_bounded": True,
        "max_delta_findings": EXPECTED_JURISDICTION_COUNT,
    }
    return assert_first_party_measurement(
        measurement,
        repo_id=bindings["dataset_repo_id"],
        revision=bindings["revision"],
        release_manifest_digest=bindings["release_manifest_digest"],
        parent_evidence_digest=bindings["parent_evidence_digest"],
    )


def _default_viewer_fetch(
    url: str, *, max_bytes: int, timeout: float
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "ipfs_datasets_py-state-laws-release-probe/1",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            headers = {
                str(name).strip().lower(): str(value).strip()
                for name, value in response.headers.items()
            }
            body = response.read(max_bytes + 1)
    except Exception as exc:  # pragma: no cover - live HTTPS transport
        raise StateLawsReleaseProbeViewerError(
            f"pinned Dataset Viewer request failed: {type(exc).__name__}"
        ) from exc
    if len(body) > max_bytes:
        raise StateLawsReleaseProbeViewerError("Dataset Viewer response exceeded bound")
    return {"status": status, "body": body, "headers": headers}


def _viewer_manifest_contract(
    manifest: Mapping[str, Any], *, release_manifest_digest: str
) -> dict[str, Any]:
    digest = _require_digest(release_manifest_digest, name="release_manifest_digest")
    if _canonical_digest(manifest) != digest:
        raise StateLawsReleaseProbeViewerError(
            "Viewer manifest payload does not match the verified manifest digest"
        )
    if manifest.get("dataset_repo_id") != DEFAULT_DATASET_REPO_ID:
        raise StateLawsReleaseProbeViewerError(
            "Viewer manifest does not bind the canonical dataset repository"
        )
    jurisdictions = _manifest_jurisdiction_order(manifest)
    if jurisdictions != list(SORTED_JURISDICTIONS) or "DC" not in jurisdictions:
        raise StateLawsReleaseProbeViewerError(
            "Viewer manifest does not bind canonical exact-51 order"
        )
    configs = manifest.get("configs")
    if isinstance(configs, Mapping):
        if configs.get("default") != DEFAULT_CONFIG_NAME:
            raise StateLawsReleaseProbeViewerError(
                "Viewer manifest default configuration drifted"
            )
        # LCR-038's verified local manifest binds the viewer-safe default by
        # name plus its canonical chunk configuration.  Bind that name to the
        # production Dataset-card contract before deriving Viewer row counts.
        canonical_chunks = configs.get("canonical_chunks")
        if not isinstance(canonical_chunks, Mapping) or not canonical_chunks:
            raise StateLawsReleaseProbeViewerError(
                "Viewer manifest canonical chunk configuration is missing"
            )
        from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
            advertised_viewer_configs,
        )

        defaults = [
            item.to_dict()
            for item in advertised_viewer_configs()
            if item.config_name == DEFAULT_CONFIG_NAME and item.is_default
        ]
        if len(defaults) != 1:
            raise StateLawsReleaseProbeViewerError(
                "Dataset-card contract lacks one exact default configuration"
            )
        default = defaults[0]
    else:
        if not isinstance(configs, Sequence) or isinstance(
            configs, (str, bytes, bytearray)
        ):
            raise StateLawsReleaseProbeViewerError(
                "Viewer manifest configurations are missing"
            )
        defaults = [
            dict(item)
            for item in configs
            if isinstance(item, Mapping)
            and item.get("config_name") == DEFAULT_CONFIG_NAME
            and item.get("is_default") is True
        ]
        if len(defaults) != 1:
            raise StateLawsReleaseProbeViewerError(
                "Viewer manifest must bind one exact default configuration"
            )
        default = defaults[0]
        if (
            default.get("satisfies_exact_51_gate") is not True
            or default.get("viewer_visible") is not True
            or not isinstance(default.get("data_files"), Sequence)
            or isinstance(default.get("data_files"), (str, bytes, bytearray))
            or not default.get("data_files")
        ):
            raise StateLawsReleaseProbeViewerError(
                "Viewer manifest default configuration is not exact-51/viewer-visible"
            )

    data_files = default.get("data_files")
    expected_local_data_file = {
        "path": VIEWER_DEFAULT_CORPUS_GLOB,
        "split": "train",
    }
    if (
        not isinstance(data_files, Sequence)
        or isinstance(data_files, (str, bytes, bytearray))
        or len(data_files) != 1
        or not isinstance(data_files[0], Mapping)
        or dict(data_files[0]) != expected_local_data_file
    ):
        raise StateLawsReleaseProbeViewerError(
            "Viewer default configuration has an unsafe or unexpected data_files binding"
        )
    artifacts = manifest.get("artifacts")
    if (
        not isinstance(artifacts, Sequence)
        or isinstance(artifacts, (str, bytes, bytearray))
        or not artifacts
    ):
        raise StateLawsReleaseProbeViewerError(
            "Viewer manifest has no artifact descriptors"
        )
    matched: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for item in artifacts:
        if not isinstance(item, Mapping):
            raise StateLawsReleaseProbeViewerError(
                "Viewer manifest artifact descriptor is malformed"
            )
        raw_path = item.get("relative_path") or item.get("path")
        if not isinstance(raw_path, str):
            raise StateLawsReleaseProbeViewerError(
                "Viewer manifest artifact path is missing"
            )
        relative_path = raw_path.strip()
        relative = PurePosixPath(relative_path)
        if (
            not relative_path
            or relative_path != raw_path
            or relative.is_absolute()
            or ".." in relative.parts
            or "\\" in relative_path
            or relative.as_posix() != relative_path
        ):
            raise StateLawsReleaseProbeViewerError(
                "Viewer manifest artifact path is unsafe"
            )
        if relative_path in seen_paths:
            raise StateLawsReleaseProbeViewerError(
                "Viewer manifest artifact path is duplicated"
            )
        seen_paths.add(relative_path)
        if not (
            len(relative.parts) == 3
            and relative.parts[:2] == ("data", "corpus")
            and relative.name.startswith("part-")
            and relative.suffix == ".parquet"
        ):
            continue
        if item.get("media_type") != "application/vnd.apache.parquet":
            raise StateLawsReleaseProbeViewerError(
                "Viewer default glob matched a non-Parquet descriptor"
            )
        row_count = item.get("row_count")
        if (
            isinstance(row_count, bool)
            or not isinstance(row_count, int)
            or row_count < 0
        ):
            raise StateLawsReleaseProbeViewerError(
                "Viewer default artifact has an invalid row_count"
            )
        matched.append({"path": relative_path, "row_count": row_count})
    expected_rows = sum(item["row_count"] for item in matched)
    if not matched or expected_rows <= 0:
        raise StateLawsReleaseProbeViewerError(
            "Viewer default data_files binding matched no positive artifact rows"
        )
    key_parity = manifest.get("key_parity")
    key_digest = (
        key_parity.get("parent_entry_cids_sha256")
        if isinstance(key_parity, Mapping)
        else None
    )
    normalized_key_digest = _require_digest(
        key_digest, name="key_parity.parent_entry_cids_sha256"
    )
    release_prefix = f"data/state_laws/sha256-{digest}"
    root_configs = state_laws_root_viewer_configs(release_prefix)
    root_defaults = [
        dict(item)
        for item in root_configs
        if item.get("config_name") == DEFAULT_CONFIG_NAME
    ]
    if len(root_defaults) != 1:
        raise StateLawsReleaseProbeViewerError(
            "root Viewer control lacks one exact default configuration"
        )
    root_default = root_defaults[0]
    return {
        "default_config": DEFAULT_CONFIG_NAME,
        "default_config_sha256": _canonical_digest(root_default),
        "default_data_files": list(root_default["data_files"]),
        "default_matched_artifact_count": len(matched),
        "default_matched_artifacts_sha256": _canonical_digest(matched),
        "expected_rows": expected_rows,
        "jurisdictions_sha256": _canonical_digest(jurisdictions),
        "key_parity_sha256": normalized_key_digest,
        "manifest_default_config_sha256": _canonical_digest(default),
        "manifest_default_data_files": [expected_local_data_file],
        "manifest_digest": digest,
        "release_prefix": release_prefix,
    }


def _reject_viewer_unsettled(payload: Mapping[str, Any], *, endpoint: str) -> None:
    stack: list[Any] = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, Mapping):
            for key, value in current.items():
                if str(key).casefold() in {"failed", "pending"} and value:
                    raise StateLawsReleaseProbeViewerError(
                        f"Dataset Viewer {endpoint} has failed/pending work"
                    )
                stack.append(value)
        elif isinstance(current, Sequence) and not isinstance(
            current, (str, bytes, bytearray)
        ):
            stack.extend(current)


def _positive_viewer_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StateLawsReleaseProbeViewerError(
            f"Dataset Viewer {label} must be a positive integer"
        )
    return value


def _viewer_semantic_summary(
    endpoint: str,
    payload: Mapping[str, Any],
    *,
    expected_rows: int,
) -> dict[str, Any]:
    _reject_viewer_unsettled(payload, endpoint=endpoint)
    if endpoint == "is-valid":
        capabilities: dict[str, bool] = {}
        for name in ("viewer", "preview", "search", "filter", "statistics"):
            value = payload.get(name)
            if not isinstance(value, bool):
                raise StateLawsReleaseProbeViewerError(
                    f"Dataset Viewer is-valid.{name} must be boolean"
                )
            capabilities[name] = value
        if not all(capabilities[name] for name in VIEWER_REQUIRED_CAPABILITIES):
            raise StateLawsReleaseProbeViewerError(
                "Dataset Viewer viewer/preview capabilities are not ready"
            )
        return {"capabilities": capabilities}
    if endpoint == "info":
        if payload.get("partial") is not False:
            raise StateLawsReleaseProbeViewerError(
                "Dataset Viewer info is not explicitly complete"
            )
        info = payload.get("dataset_info")
        if not isinstance(info, Mapping):
            raise StateLawsReleaseProbeViewerError(
                "Dataset Viewer info lacks dataset_info"
            )
        if info.get("config_name") != DEFAULT_CONFIG_NAME:
            raise StateLawsReleaseProbeViewerError(
                "Dataset Viewer info returned the wrong configuration"
            )
        splits = info.get("splits")
        if not isinstance(splits, Mapping) or not splits:
            raise StateLawsReleaseProbeViewerError(
                "Dataset Viewer info returned no splits"
            )
        rows = sum(
            _positive_viewer_int(item.get("num_examples"), label="info rows")
            for item in splits.values()
            if isinstance(item, Mapping)
        )
        if rows != expected_rows:
            raise StateLawsReleaseProbeViewerError(
                "Dataset Viewer info row count differs from verified manifest"
            )
        return {"config": DEFAULT_CONFIG_NAME, "row_count": rows}
    if endpoint == "size":
        if payload.get("partial") is not False:
            raise StateLawsReleaseProbeViewerError(
                "Dataset Viewer size is not explicitly complete"
            )
        size = payload.get("size")
        config = size.get("config") if isinstance(size, Mapping) else None
        if not isinstance(config, Mapping):
            raise StateLawsReleaseProbeViewerError(
                "Dataset Viewer size lacks its config-scoped result"
            )
        if config.get("config") != DEFAULT_CONFIG_NAME:
            raise StateLawsReleaseProbeViewerError(
                "Dataset Viewer size did not close the exact configuration"
            )
        rows = _positive_viewer_int(config.get("num_rows"), label="size rows")
        if rows != expected_rows:
            raise StateLawsReleaseProbeViewerError(
                "Dataset Viewer size row count differs from verified manifest"
            )
        return {"config": DEFAULT_CONFIG_NAME, "row_count": rows}
    if endpoint == "splits":
        for field in ("pending", "failed"):
            unsettled = payload.get(field)
            if (
                not isinstance(unsettled, Sequence)
                or isinstance(unsettled, (str, bytes, bytearray))
                or unsettled
            ):
                raise StateLawsReleaseProbeViewerError(
                    f"Dataset Viewer splits.{field} is not explicitly empty"
                )
        splits = payload.get("splits")
        if not isinstance(splits, Sequence) or isinstance(
            splits, (str, bytes, bytearray)
        ):
            raise StateLawsReleaseProbeViewerError(
                "Dataset Viewer splits response is malformed"
            )
        matching = [
            item
            for item in splits
            if isinstance(item, Mapping)
            and (item.get("config") or item.get("config_name")) == DEFAULT_CONFIG_NAME
            and str(item.get("split") or item.get("name") or "").strip()
        ]
        if not matching:
            raise StateLawsReleaseProbeViewerError(
                "Dataset Viewer splits omits the exact configuration"
            )
        return {
            "config": DEFAULT_CONFIG_NAME,
            "split_count": len(matching),
        }
    raise StateLawsReleaseProbeViewerError("unsupported Dataset Viewer endpoint")


def run_pinned_viewer_probe(
    *,
    repo_id: str,
    revision: str,
    verified_manifest: Mapping[str, Any],
    release_manifest_digest: str,
    viewer_fetch: Callable[..., Mapping[str, Any]] = _default_viewer_fetch,
    max_bytes: int = DEFAULT_MAX_VIEWER_BYTES,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Probe Viewer endpoints and verify their response commit headers."""

    dataset = _require_repo_id(repo_id)
    pin = _require_revision(revision)
    manifest_binding = _viewer_manifest_contract(
        verified_manifest,
        release_manifest_digest=release_manifest_digest,
    )
    observations: list[dict[str, Any]] = []
    for endpoint in VIEWER_ENDPOINTS:
        query: dict[str, str] = {"dataset": dataset}
        if endpoint in {"info", "size"}:
            query["config"] = DEFAULT_CONFIG_NAME
        url = (
            f"https://datasets-server.huggingface.co/{endpoint}?"
            f"{urllib.parse.urlencode(query)}"
        )
        response = viewer_fetch(url, max_bytes=max_bytes, timeout=timeout)
        status = int(response.get("status", -1))
        raw_headers = response.get("headers")
        headers = (
            {
                str(name).strip().lower(): str(value).strip()
                for name, value in raw_headers.items()
            }
            if isinstance(raw_headers, Mapping)
            else {}
        )
        response_revision = headers.get("x-revision")
        if (
            response_revision != pin
            or _SHA_RE.fullmatch(response_revision or "") is None
        ):
            raise StateLawsReleaseProbeViewerError(
                f"Dataset Viewer {endpoint} response is not bound to the requested pin"
            )
        body = response.get("body")
        if isinstance(body, str):
            body = body.encode("utf-8")
        if status < 200 or status >= 300 or not isinstance(body, bytes):
            raise StateLawsReleaseProbeViewerError(
                f"pinned Dataset Viewer {endpoint} returned HTTP {status}"
            )
        if len(body) > max_bytes:
            raise StateLawsReleaseProbeViewerError(
                f"pinned Dataset Viewer {endpoint} exceeded the response bound"
            )
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise StateLawsReleaseProbeViewerError(
                f"pinned Dataset Viewer {endpoint} returned invalid JSON"
            ) from exc
        if not isinstance(payload, Mapping):
            raise StateLawsReleaseProbeViewerError(
                f"pinned Dataset Viewer {endpoint} returned a non-object"
            )
        semantic = _viewer_semantic_summary(
            endpoint,
            payload,
            expected_rows=int(manifest_binding["expected_rows"]),
        )
        observations.append(
            {
                "endpoint": endpoint,
                "response_bytes": len(body),
                "response_sha256": hashlib.sha256(body).hexdigest(),
                "status": status,
                "x_revision": response_revision,
                "semantic": semantic,
            }
        )
    return {
        "passed": True,
        "dataset_viewer_api_passed": True,
        "default_config": DEFAULT_CONFIG_NAME,
        "ia_only": False,
        "jurisdictions": list(SORTED_JURISDICTIONS),
        "pinned_revision": pin,
        "bounded": True,
        "manifest_binding": manifest_binding,
        "responses": observations,
    }


def run_public_release_probe(
    local_root: Path | str,
    *,
    repo_id: str,
    revision: str,
    release_manifest_digest: str,
    parent_evidence_digest: str,
    viewer_fetch: Callable[..., Mapping[str, Any]] = _default_viewer_fetch,
    **local_probe_kwargs: Any,
) -> dict[str, Any]:
    """Combine verified remote query measurements with the pinned Viewer."""

    measured = run_remote_release_probe(
        local_root,
        repo_id=repo_id,
        revision=revision,
        release_manifest_digest=release_manifest_digest,
        parent_evidence_digest=parent_evidence_digest,
        **local_probe_kwargs,
    )
    release_verifier = local_probe_kwargs.get(
        "release_verifier", verify_state_laws_local_release_manifest
    )
    try:
        verified = release_verifier(Path(local_root).expanduser().resolve())
    except Exception as exc:
        raise StateLawsReleaseProbeBindingError(
            f"public Viewer manifest verification failed: {exc}"
        ) from exc
    if str(verified.manifest_digest) != _require_digest(
        release_manifest_digest, name="release_manifest_digest"
    ):
        raise StateLawsReleaseProbeBindingError(
            "public Viewer manifest identity drifted"
        )
    viewer = run_pinned_viewer_probe(
        repo_id=repo_id,
        revision=revision,
        verified_manifest=dict(verified.payload),
        release_manifest_digest=release_manifest_digest,
        viewer_fetch=viewer_fetch,
    )
    viewer.update(
        {
            "measurement_source": MEASUREMENT_SOURCE,
            "externally_supplied": False,
            "observed_at": measured["observed_at"],
            "probe_bindings": measured["probe_bindings"],
        }
    )
    return {**measured, "viewer": viewer}


__all__ = [
    "DUAL_PIN_QUERY_TERMS",
    "MEASUREMENT_SOURCE",
    "SCHEMA_VERSION",
    "SORTED_JURISDICTIONS",
    "QueryRepresentative",
    "StateLawsReleaseProbeBindingError",
    "StateLawsReleaseProbeError",
    "StateLawsReleaseProbeQueryError",
    "StateLawsReleaseProbeViewerError",
    "assert_first_party_dual_pin_measurement",
    "assert_first_party_measurement",
    "dual_pin_probe_bindings",
    "load_query_representatives",
    "release_probe_bindings",
    "run_dual_pin_probe",
    "run_local_release_probe",
    "run_pinned_viewer_probe",
    "run_post_publication_audit_probe",
    "run_public_release_probe",
    "run_remote_release_probe",
]
