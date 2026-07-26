"""Resumable, policy-gated embeddings for pinned SkillCenter bundles.

Source bodies are read from immutable SQLite snapshots and passed only to the
injected embedding function.  Parquet artifacts retain vectors, bounded
retrieval metadata, source offsets, hashes, and policy decisions; they do not
copy ``skill_md``, ``library_md``, or arbitrary YAML bodies.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Final, Iterator

from ..source_adapters.policy import (
    AllowedUseDecision,
    SKILL_SOURCE_POLICY_VERSION,
    SkillSourcePolicy,
)
from ..source_adapters.skillcenter import (
    SkillCenterBundleReader,
    SkillCenterSkillRecord,
)


SKILLCENTER_EMBEDDING_CORPUS_SCHEMA_VERSION: Final = (
    "skillcenter-embedding-corpus/v1"
)
SKILLCENTER_EMBEDDING_BATCH_SCHEMA_VERSION: Final = (
    "skillcenter-embedding-batch/v1"
)
SKILLCENTER_EMBEDDING_TEXT_SCHEMA_VERSION: Final = (
    "skillcenter-title-domain-body-chunk/v1"
)
DEFAULT_EMBEDDING_MODEL: Final = "thenlper/gte-small"
DEFAULT_EMBEDDING_PROVIDER: Final = "huggingface"
DEFAULT_EMBEDDING_DEVICE: Final = "cpu"
DEFAULT_SOURCE_BATCH_SIZE: Final = 32
DEFAULT_CHUNK_CHARS: Final = 1_600
DEFAULT_CHUNK_OVERLAP_CHARS: Final = 160

_PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_BATCH_DIR_RE = re.compile(r"^batch-(?P<index>[0-9]{6})$")
_MAX_RECEIPT_BYTES = 1024 * 1024
_MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_CONTENT_ALLOWED_USES = frozenset(
    {
        AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH,
        AllowedUseDecision.ALLOW_INTERNAL_EVALUATION,
    }
)

EmbeddingFunction = Callable[[Sequence[str]], object]


class SkillCenterEmbeddingError(ValueError):
    """Raised when an embedding run or persisted checkpoint is invalid."""


@dataclass(frozen=True, slots=True)
class SkillCenterEmbeddingConfig:
    """Semantic and batching configuration bound into every checkpoint."""

    model_name: str = DEFAULT_EMBEDDING_MODEL
    provider: str = DEFAULT_EMBEDDING_PROVIDER
    device: str = DEFAULT_EMBEDDING_DEVICE
    source_batch_size: int = DEFAULT_SOURCE_BATCH_SIZE
    chunk_chars: int = DEFAULT_CHUNK_CHARS
    chunk_overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS
    internal_retrieval_all_records: bool = False
    max_chunks_per_record: int | None = None
    included_allowed_uses: tuple[AllowedUseDecision, ...] = (
        AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH,
        AllowedUseDecision.ALLOW_INTERNAL_EVALUATION,
    )
    text_schema_version: str = SKILLCENTER_EMBEDDING_TEXT_SCHEMA_VERSION
    policy_version: str = SKILL_SOURCE_POLICY_VERSION

    def __post_init__(self) -> None:
        for field_name in ("model_name", "provider", "device"):
            value = str(getattr(self, field_name) or "").strip()
            if not value or "\x00" in value:
                raise SkillCenterEmbeddingError(
                    f"{field_name} must be non-empty normalized text"
                )
            object.__setattr__(self, field_name, value)
        if (
            isinstance(self.source_batch_size, bool)
            or not isinstance(self.source_batch_size, int)
            or not 1 <= self.source_batch_size <= 1_000
        ):
            raise SkillCenterEmbeddingError(
                "source_batch_size must be between 1 and 1000"
            )
        if (
            isinstance(self.chunk_chars, bool)
            or not isinstance(self.chunk_chars, int)
            or self.chunk_chars < 64
        ):
            raise SkillCenterEmbeddingError("chunk_chars must be at least 64")
        if (
            isinstance(self.chunk_overlap_chars, bool)
            or not isinstance(self.chunk_overlap_chars, int)
            or not 0 <= self.chunk_overlap_chars < self.chunk_chars
        ):
            raise SkillCenterEmbeddingError(
                "chunk_overlap_chars must be non-negative and less than chunk_chars"
            )
        if not isinstance(self.internal_retrieval_all_records, bool):
            raise SkillCenterEmbeddingError(
                "internal_retrieval_all_records must be boolean"
            )
        if self.max_chunks_per_record is not None and (
            isinstance(self.max_chunks_per_record, bool)
            or not isinstance(self.max_chunks_per_record, int)
            or not 1 <= self.max_chunks_per_record <= 1024
        ):
            raise SkillCenterEmbeddingError(
                "max_chunks_per_record must be between 1 and 1024 or None"
            )
        try:
            allowed_uses = tuple(
                sorted(
                    {
                        AllowedUseDecision(value)
                        for value in self.included_allowed_uses
                    },
                    key=lambda item: item.value,
                )
            )
        except (TypeError, ValueError) as exc:
            raise SkillCenterEmbeddingError(
                "included_allowed_uses contains an unsupported decision"
            ) from exc
        if not allowed_uses or not set(allowed_uses) <= _CONTENT_ALLOWED_USES:
            raise SkillCenterEmbeddingError(
                "only train/publish and internal-evaluation records may be embedded"
            )
        if self.text_schema_version != SKILLCENTER_EMBEDDING_TEXT_SCHEMA_VERSION:
            raise SkillCenterEmbeddingError("unsupported text_schema_version")
        if self.policy_version != SKILL_SOURCE_POLICY_VERSION:
            raise SkillCenterEmbeddingError("unsupported policy_version")
        object.__setattr__(self, "included_allowed_uses", allowed_uses)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "chunk_chars": self.chunk_chars,
            "chunk_overlap_chars": self.chunk_overlap_chars,
            "device": self.device,
            "included_allowed_uses": [
                item.value for item in self.included_allowed_uses
            ],
            "model_name": self.model_name,
            "policy_version": self.policy_version,
            "provider": self.provider,
            "source_batch_size": self.source_batch_size,
            "text_schema_version": self.text_schema_version,
        }
        # Omit migration-only defaults so existing v1 checkpoint identities
        # remain verifiable byte-for-byte.
        if self.internal_retrieval_all_records:
            payload["internal_retrieval_all_records"] = True
        if self.max_chunks_per_record is not None:
            payload["max_chunks_per_record"] = self.max_chunks_per_record
        return payload

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(self.to_dict())).hexdigest()


@dataclass(frozen=True, slots=True)
class SkillCenterEmbeddingRunSummary:
    """Compact result returned after a new or resumed run."""

    output_dir: str
    status: str
    source_records_total: int
    source_records_processed: int
    embedded_records: int
    vector_count: int
    dimension: int
    batch_count: int
    last_skill_id: str
    manifest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_count": self.batch_count,
            "dimension": self.dimension,
            "embedded_records": self.embedded_records,
            "last_skill_id": self.last_skill_id,
            "manifest_sha256": self.manifest_sha256,
            "output_dir": self.output_dir,
            "source_records_processed": self.source_records_processed,
            "source_records_total": self.source_records_total,
            "status": self.status,
            "vector_count": self.vector_count,
        }


@dataclass(frozen=True, slots=True)
class _EmbeddingChunk:
    chunk_id: str
    chunk_index: int
    source_start_char: int
    source_end_char: int
    text: str
    text_sha256: str


def build_skillcenter_embedding_chunks(
    record: SkillCenterSkillRecord,
    *,
    config: SkillCenterEmbeddingConfig,
) -> tuple[_EmbeddingChunk, ...]:
    """Compose deterministic bounded embedding inputs for one skill."""

    if not isinstance(record, SkillCenterSkillRecord):
        raise TypeError("record must be a SkillCenterSkillRecord")
    if not isinstance(config, SkillCenterEmbeddingConfig):
        raise TypeError("config must be a SkillCenterEmbeddingConfig")

    body = record.skill_md.replace("\r\n", "\n").replace("\r", "\n")
    ranges: list[tuple[int, int]] = []
    if not body:
        ranges.append((0, 0))
    else:
        step = config.chunk_chars - config.chunk_overlap_chars
        start = 0
        while start < len(body):
            end = min(len(body), start + config.chunk_chars)
            ranges.append((start, end))
            if end >= len(body):
                break
            start += step

    chunks: list[_EmbeddingChunk] = []
    for index, (start, end) in enumerate(ranges):
        text = (
            f"Title: {record.title.strip()}\n"
            f"Domain: {record.domain.strip()}\n\n"
            f"{body[start:end]}"
        ).strip()
        text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        identity = {
            "bundle_sha256": record.bundle_sha256,
            "chunk_index": index,
            "dataset_id": record.dataset_id,
            "dataset_revision": record.dataset_revision,
            "repository_file": record.repository_file,
            "skill_id": record.skill_id,
            "source_end_char": end,
            "source_start_char": start,
            "text_schema_version": config.text_schema_version,
            "text_sha256": text_sha256,
        }
        digest = hashlib.sha256(_canonical_json_bytes(identity)).hexdigest()
        chunks.append(
            _EmbeddingChunk(
                chunk_id=f"skillcenter-chunk:sha256:{digest}",
                chunk_index=index,
                source_start_char=start,
                source_end_char=end,
                text=text,
                text_sha256=text_sha256,
            )
        )
    return tuple(chunks)


def run_skillcenter_embedding_job(
    reader: SkillCenterBundleReader,
    *,
    profile: str,
    output_dir: str | Path,
    config: SkillCenterEmbeddingConfig,
    embedder: EmbeddingFunction,
    policy: SkillSourcePolicy | None = None,
    max_records: int | None = None,
) -> SkillCenterEmbeddingRunSummary:
    """Create or resume atomic Parquet embedding checkpoints."""

    if not callable(embedder):
        raise TypeError("embedder must be callable")
    if not isinstance(config, SkillCenterEmbeddingConfig):
        raise TypeError("config must be a SkillCenterEmbeddingConfig")
    profile = str(profile or "").strip()
    if not _PROFILE_RE.fullmatch(profile):
        raise SkillCenterEmbeddingError("profile is not a normalized identifier")
    if max_records is not None and (
        isinstance(max_records, bool)
        or not isinstance(max_records, int)
        or max_records < 0
    ):
        raise SkillCenterEmbeddingError(
            "max_records must be a non-negative integer or None"
        )
    active_policy = policy or SkillSourcePolicy()
    manifest = reader.inspect()
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise SkillCenterEmbeddingError(
            "output_dir must be a real directory, not a symlink"
        )

    identity = {
        "bundle_sha256": manifest.local_sha256,
        "config_sha256": config.digest,
        "dataset_id": manifest.dataset_id,
        "dataset_revision": manifest.dataset_revision,
        "profile": profile,
        "repository_file": manifest.repository_file,
    }

    with _output_lock(root):
        receipts = _load_receipts(root, identity=identity)
        last_skill_id = (
            str(receipts[-1]["source_last_skill_id"]) if receipts else ""
        )
        processed_now = 0
        pending: list[SkillCenterSkillRecord] = []
        iterator = reader.iter_records(
            limit=max_records,
            batch_size=config.source_batch_size,
            start_after=last_skill_id,
        )
        for record in iterator:
            pending.append(record)
            if len(pending) >= config.source_batch_size:
                receipt = _write_record_batch(
                    root,
                    batch_index=len(receipts),
                    records=pending,
                    identity=identity,
                    config=config,
                    embedder=embedder,
                    policy=active_policy,
                )
                receipts.append(receipt)
                processed_now += len(pending)
                pending = []
                _write_manifest(
                    root,
                    bundle_manifest=manifest.to_dict(),
                    config=config,
                    identity=identity,
                    receipts=receipts,
                )
        if pending:
            receipt = _write_record_batch(
                root,
                batch_index=len(receipts),
                records=pending,
                identity=identity,
                config=config,
                embedder=embedder,
                policy=active_policy,
            )
            receipts.append(receipt)
            processed_now += len(pending)
        if processed_now or not (root / "manifest.json").exists():
            manifest_payload = _write_manifest(
                root,
                bundle_manifest=manifest.to_dict(),
                config=config,
                identity=identity,
                receipts=receipts,
            )
        else:
            manifest_payload = _manifest_payload(
                bundle_manifest=manifest.to_dict(),
                config=config,
                identity=identity,
                receipts=receipts,
            )
        if max_records is None and manifest_payload["status"] != "complete":
            raise SkillCenterEmbeddingError(
                "unbounded source iteration ended before the declared bundle count"
            )

    payload_bytes = _canonical_json_bytes(manifest_payload)
    return SkillCenterEmbeddingRunSummary(
        output_dir=str(root),
        status=str(manifest_payload["status"]),
        source_records_total=int(manifest_payload["source_records_total"]),
        source_records_processed=int(
            manifest_payload["source_records_processed"]
        ),
        embedded_records=int(manifest_payload["embedded_records"]),
        vector_count=int(manifest_payload["vector_count"]),
        dimension=int(manifest_payload["dimension"]),
        batch_count=int(manifest_payload["batch_count"]),
        last_skill_id=str(manifest_payload["last_skill_id"]),
        manifest_sha256=hashlib.sha256(payload_bytes).hexdigest(),
    )


def load_skillcenter_embedding_corpus(
    root: str | Path,
    *,
    require_complete: bool = True,
) -> dict[str, Any]:
    """Load and fully verify one persisted embedding corpus manifest.

    Verification replays every receipt and file descriptor rather than
    trusting the top-level counters.  The returned dictionary is the exact
    canonical manifest payload.
    """

    corpus_root = Path(root).expanduser().resolve()
    manifest_path = corpus_root / "manifest.json"
    if (
        corpus_root.is_symlink()
        or not corpus_root.is_dir()
        or manifest_path.is_symlink()
        or not manifest_path.is_file()
        or manifest_path.stat().st_size > _MAX_MANIFEST_BYTES
    ):
        raise SkillCenterEmbeddingError(
            "embedding corpus must contain a bounded regular manifest.json"
        )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SkillCenterEmbeddingError(
            "embedding corpus manifest is malformed"
        ) from exc
    if not isinstance(payload, dict):
        raise SkillCenterEmbeddingError(
            "embedding corpus manifest must be an object"
        )
    if payload.get("schema_version") != SKILLCENTER_EMBEDDING_CORPUS_SCHEMA_VERSION:
        raise SkillCenterEmbeddingError(
            "unsupported embedding corpus manifest schema"
        )
    config_payload = payload.get("config")
    bundle_manifest = payload.get("bundle_manifest")
    if not isinstance(config_payload, Mapping) or not isinstance(
        bundle_manifest, Mapping
    ):
        raise SkillCenterEmbeddingError(
            "embedding corpus manifest config and bundle_manifest are required"
        )
    try:
        config = SkillCenterEmbeddingConfig(**dict(config_payload))
    except (TypeError, ValueError) as exc:
        raise SkillCenterEmbeddingError(
            "embedding corpus manifest config is invalid"
        ) from exc
    identity = {
        key: str(payload.get(key) or "")
        for key in (
            "bundle_sha256",
            "config_sha256",
            "dataset_id",
            "dataset_revision",
            "profile",
            "repository_file",
        )
    }
    if any(not value for value in identity.values()):
        raise SkillCenterEmbeddingError(
            "embedding corpus manifest identity is incomplete"
        )
    if identity["config_sha256"] != config.digest:
        raise SkillCenterEmbeddingError(
            "embedding corpus config_sha256 does not match config"
        )
    receipts = _load_receipts(corpus_root, identity=identity)
    expected = _manifest_payload(
        bundle_manifest=bundle_manifest,
        config=config,
        identity=identity,
        receipts=receipts,
    )
    if payload != expected:
        raise SkillCenterEmbeddingError(
            "embedding corpus manifest does not match verified checkpoints"
        )
    if require_complete and payload["status"] != "complete":
        raise SkillCenterEmbeddingError(
            "embedding corpus is partial; a complete corpus is required"
        )
    return payload


def iter_skillcenter_embedding_rows(
    root: str | Path,
    *,
    columns: Sequence[str] | None = None,
    require_complete: bool = True,
) -> Iterator[dict[str, Any]]:
    """Yield verified embedding rows in stable batch and row order."""

    corpus_root = Path(root).expanduser().resolve()
    manifest = load_skillcenter_embedding_corpus(
        corpus_root,
        require_complete=require_complete,
    )
    identity = {
        key: str(manifest[key])
        for key in (
            "bundle_sha256",
            "config_sha256",
            "dataset_id",
            "dataset_revision",
            "profile",
            "repository_file",
        )
    }
    requested_columns = None
    if columns is not None:
        requested_columns = tuple(str(item) for item in columns)
        if not requested_columns or any(not item for item in requested_columns):
            raise SkillCenterEmbeddingError(
                "columns must contain non-empty column names"
            )
    _, parquet = _pyarrow()
    receipts = _load_receipts(corpus_root, identity=identity)
    for receipt in receipts:
        descriptor = receipt.get("embeddings_file")
        if descriptor is None:
            continue
        batch_dir = (
            corpus_root
            / "batches"
            / f"batch-{int(receipt['batch_index']):06d}"
        )
        embedding_path = _verify_file_descriptor(batch_dir, descriptor)
        try:
            batches = parquet.ParquetFile(embedding_path).iter_batches(
                columns=requested_columns,
            )
            for batch in batches:
                yield from batch.to_pylist()
        except (KeyError, ValueError) as exc:
            raise SkillCenterEmbeddingError(
                "requested embedding columns are not present"
            ) from exc


def _write_record_batch(
    root: Path,
    *,
    batch_index: int,
    records: Sequence[SkillCenterSkillRecord],
    identity: Mapping[str, str],
    config: SkillCenterEmbeddingConfig,
    embedder: EmbeddingFunction,
    policy: SkillSourcePolicy,
) -> dict[str, Any]:
    policy_rows: list[dict[str, Any]] = []
    embedding_metadata: list[dict[str, Any]] = []
    embedding_texts: list[str] = []
    decision_counts: Counter[str] = Counter()
    embedded_skill_ids: set[str] = set()

    for record in records:
        decision = policy.evaluate(record)
        allowed_use = decision.allowed_use
        should_embed = (
            allowed_use in config.included_allowed_uses
            or config.internal_retrieval_all_records
        )
        decision_counts[allowed_use.value] += 1
        source_ref = record.to_source_ref(review_status=decision.review_status)
        finding_codes = sorted({finding.code for finding in decision.findings})
        policy_rows.append(
            {
                "allowed_use": allowed_use.value,
                "bundle_sha256": record.bundle_sha256,
                "content_sha256": record.content_sha256,
                "content_cid": record.content_cid,
                "dataset_id": record.dataset_id,
                "dataset_revision": record.dataset_revision,
                "domain": record.domain,
                "embedded": should_embed,
                "entry_cid": record.entry_cid,
                "finding_codes": finding_codes,
                "finding_count": len(decision.findings),
                "language": record.language,
                "license_expression": decision.license_decision.expression,
                "license_reason_code": decision.license_decision.reason_code,
                "license_status": decision.license_decision.status.value,
                "policy_version": decision.policy_version,
                "profile": record.profile,
                "repository_file": record.repository_file,
                "skill_id": record.skill_id,
                "source_ref_id": source_ref.ref_id,
                "source_type": record.source_type,
                "trust_decision": decision.trust_decision.value,
            }
        )
        if not should_embed:
            continue
        chunks = build_skillcenter_embedding_chunks(record, config=config)
        if config.max_chunks_per_record is not None:
            chunks = chunks[: config.max_chunks_per_record]
        embedded_skill_ids.add(record.skill_id)
        for chunk in chunks:
            embedding_texts.append(chunk.text)
            embedding_metadata.append(
                {
                    "allowed_use": allowed_use.value,
                    "bundle_sha256": record.bundle_sha256,
                    "chunk_count": len(chunks),
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.chunk_index,
                    "content_sha256": record.content_sha256,
                    "content_cid": record.content_cid,
                    "dataset_id": record.dataset_id,
                    "dataset_revision": record.dataset_revision,
                    "domain": record.domain,
                    "entry_cid": record.entry_cid,
                    "language": record.language,
                    "license_expression": decision.license_decision.expression,
                    "overall_score": record.overall_score,
                    "profile": record.profile,
                    "repository_file": record.repository_file,
                    "skill_id": record.skill_id,
                    "skill_kind": record.skill_kind,
                    "source_end_char": chunk.source_end_char,
                    "source_ref_id": source_ref.ref_id,
                    "source_start_char": chunk.source_start_char,
                    "source_type": record.source_type,
                    "text_chars": len(chunk.text),
                    "text_schema_version": config.text_schema_version,
                    "text_sha256": chunk.text_sha256,
                    "title": record.title,
                }
            )

    vectors = (
        _normalize_vectors(embedder(embedding_texts), len(embedding_texts))
        if embedding_texts
        else []
    )
    dimension = len(vectors[0]) if vectors else 0
    embedding_rows = []
    for metadata, vector in zip(embedding_metadata, vectors):
        embedding_rows.append(
            {
                **metadata,
                "embedding": vector,
                "embedding_device": config.device,
                "embedding_dimension": dimension,
                "embedding_model": config.model_name,
                "embedding_norm": math.sqrt(
                    sum(item * item for item in vector)
                ),
                "embedding_provider": config.provider,
            }
        )

    batches_root = root / "batches"
    batches_root.mkdir(parents=True, exist_ok=True)
    final_dir = batches_root / f"batch-{batch_index:06d}"
    if final_dir.exists() or final_dir.is_symlink():
        raise SkillCenterEmbeddingError(
            f"batch checkpoint already exists: {final_dir.name}"
        )
    temporary_dir = Path(
        tempfile.mkdtemp(prefix=".batch-", suffix=".partial", dir=batches_root)
    )
    try:
        policy_path = temporary_dir / "policy.parquet"
        _write_policy_parquet(policy_path, policy_rows)
        embedding_path: Path | None = None
        if embedding_rows:
            embedding_path = temporary_dir / "embeddings.parquet"
            _write_embedding_parquet(
                embedding_path,
                embedding_rows,
                dimension=dimension,
            )
        receipt = {
            **identity,
            "batch_index": batch_index,
            "decision_counts": dict(sorted(decision_counts.items())),
            "dimension": dimension,
            "embedded_records": len(embedded_skill_ids),
            "embeddings_file": (
                _file_descriptor(embedding_path)
                if embedding_path is not None
                else None
            ),
            "policy_file": _file_descriptor(policy_path),
            "schema_version": SKILLCENTER_EMBEDDING_BATCH_SCHEMA_VERSION,
            "source_first_skill_id": records[0].skill_id,
            "source_last_skill_id": records[-1].skill_id,
            "source_record_count": len(records),
            "vector_count": len(embedding_rows),
        }
        (temporary_dir / "receipt.json").write_bytes(
            _canonical_json_bytes(receipt)
        )
        os.replace(temporary_dir, final_dir)
        return receipt
    except Exception:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise


def _write_policy_parquet(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    pa, parquet = _pyarrow()
    schema = pa.schema(
        [
            ("allowed_use", pa.string()),
            ("bundle_sha256", pa.string()),
            ("content_sha256", pa.string()),
            ("content_cid", pa.string()),
            ("dataset_id", pa.string()),
            ("dataset_revision", pa.string()),
            ("domain", pa.string()),
            ("embedded", pa.bool_()),
            ("entry_cid", pa.string()),
            ("finding_codes", pa.list_(pa.string())),
            ("finding_count", pa.int32()),
            ("language", pa.string()),
            ("license_expression", pa.string()),
            ("license_reason_code", pa.string()),
            ("license_status", pa.string()),
            ("policy_version", pa.string()),
            ("profile", pa.string()),
            ("repository_file", pa.string()),
            ("skill_id", pa.string()),
            ("source_ref_id", pa.string()),
            ("source_type", pa.string()),
            ("trust_decision", pa.string()),
        ]
    )
    table = pa.Table.from_pylist(list(rows), schema=schema)
    parquet.write_table(table, path, compression="zstd")


def _write_embedding_parquet(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    *,
    dimension: int,
) -> None:
    pa, parquet = _pyarrow()
    schema = pa.schema(
        [
            ("allowed_use", pa.string()),
            ("bundle_sha256", pa.string()),
            ("chunk_count", pa.int32()),
            ("chunk_id", pa.string()),
            ("chunk_index", pa.int32()),
            ("content_sha256", pa.string()),
            ("content_cid", pa.string()),
            ("dataset_id", pa.string()),
            ("dataset_revision", pa.string()),
            ("domain", pa.string()),
            ("entry_cid", pa.string()),
            ("embedding", pa.list_(pa.float32(), dimension)),
            ("embedding_device", pa.string()),
            ("embedding_dimension", pa.int32()),
            ("embedding_model", pa.string()),
            ("embedding_norm", pa.float32()),
            ("embedding_provider", pa.string()),
            ("language", pa.string()),
            ("license_expression", pa.string()),
            ("overall_score", pa.float64()),
            ("profile", pa.string()),
            ("repository_file", pa.string()),
            ("skill_id", pa.string()),
            ("skill_kind", pa.string()),
            ("source_end_char", pa.int64()),
            ("source_ref_id", pa.string()),
            ("source_start_char", pa.int64()),
            ("source_type", pa.string()),
            ("text_chars", pa.int32()),
            ("text_schema_version", pa.string()),
            ("text_sha256", pa.string()),
            ("title", pa.string()),
        ]
    )
    table = pa.Table.from_pylist(list(rows), schema=schema)
    parquet.write_table(table, path, compression="zstd")


def _load_receipts(
    root: Path,
    *,
    identity: Mapping[str, str],
) -> list[dict[str, Any]]:
    batches_root = root / "batches"
    if not batches_root.exists():
        return []
    if batches_root.is_symlink() or not batches_root.is_dir():
        raise SkillCenterEmbeddingError("batches path must be a real directory")

    batch_dirs = sorted(
        path
        for path in batches_root.iterdir()
        if _BATCH_DIR_RE.fullmatch(path.name)
    )
    receipts: list[dict[str, Any]] = []
    prior_last = ""
    dimension = 0
    for expected_index, batch_dir in enumerate(batch_dirs):
        match = _BATCH_DIR_RE.fullmatch(batch_dir.name)
        assert match is not None
        if int(match.group("index")) != expected_index:
            raise SkillCenterEmbeddingError("batch checkpoints are not contiguous")
        receipt_path = batch_dir / "receipt.json"
        if (
            batch_dir.is_symlink()
            or not batch_dir.is_dir()
            or receipt_path.is_symlink()
            or not receipt_path.is_file()
            or receipt_path.stat().st_size > _MAX_RECEIPT_BYTES
        ):
            raise SkillCenterEmbeddingError(
                f"invalid batch checkpoint: {batch_dir.name}"
            )
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SkillCenterEmbeddingError(
                f"malformed batch receipt: {batch_dir.name}"
            ) from exc
        if not isinstance(receipt, dict):
            raise SkillCenterEmbeddingError("batch receipt must be an object")
        if receipt.get("schema_version") != SKILLCENTER_EMBEDDING_BATCH_SCHEMA_VERSION:
            raise SkillCenterEmbeddingError("unsupported batch receipt schema")
        if int(receipt.get("batch_index", -1)) != expected_index:
            raise SkillCenterEmbeddingError("batch receipt index mismatch")
        for key, value in identity.items():
            if receipt.get(key) != value:
                raise SkillCenterEmbeddingError(
                    f"checkpoint identity mismatch for {key}"
                )
        first = str(receipt.get("source_first_skill_id") or "")
        last = str(receipt.get("source_last_skill_id") or "")
        if not first or not last or first > last or (prior_last and first <= prior_last):
            raise SkillCenterEmbeddingError(
                "batch source key ranges overlap or are unordered"
            )
        prior_last = last
        source_record_count = _receipt_int(
            receipt,
            "source_record_count",
            minimum=1,
        )
        vector_count = _receipt_int(receipt, "vector_count", minimum=0)
        embedded_records = _receipt_int(
            receipt,
            "embedded_records",
            minimum=0,
        )
        if embedded_records > source_record_count:
            raise SkillCenterEmbeddingError(
                "embedded_records exceeds the source batch size"
            )
        decisions = receipt.get("decision_counts")
        if not isinstance(decisions, Mapping) or any(
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for key, value in decisions.items()
        ):
            raise SkillCenterEmbeddingError("decision_counts is invalid")
        if sum(int(value) for value in decisions.values()) != source_record_count:
            raise SkillCenterEmbeddingError(
                "decision_counts does not match source_record_count"
            )
        receipt_dimension = _receipt_int(receipt, "dimension", minimum=0)
        if receipt_dimension:
            if dimension and receipt_dimension != dimension:
                raise SkillCenterEmbeddingError(
                    "embedding dimension changed between batches"
                )
            dimension = receipt_dimension
        policy_path = _verify_file_descriptor(
            batch_dir,
            receipt.get("policy_file"),
        )
        _, parquet = _pyarrow()
        policy_metadata = parquet.ParquetFile(policy_path).metadata
        if policy_metadata.num_rows != source_record_count:
            raise SkillCenterEmbeddingError(
                "policy parquet row count does not match its receipt"
            )
        embeddings_file = receipt.get("embeddings_file")
        if embeddings_file is not None:
            embedding_path = _verify_file_descriptor(
                batch_dir,
                embeddings_file,
            )
            embedding_file = parquet.ParquetFile(embedding_path)
            if embedding_file.metadata.num_rows != vector_count:
                raise SkillCenterEmbeddingError(
                    "embedding parquet row count does not match its receipt"
                )
            schema = embedding_file.schema_arrow
            field_index = schema.get_field_index("embedding")
            if (
                vector_count < 1
                or receipt_dimension < 1
                or field_index < 0
                or getattr(schema.field(field_index).type, "list_size", None)
                != receipt_dimension
            ):
                raise SkillCenterEmbeddingError(
                    "embedding parquet dimension does not match its receipt"
                )
        elif vector_count or receipt_dimension:
            raise SkillCenterEmbeddingError(
                "receipt declares vectors without an embeddings parquet"
            )
        receipts.append(receipt)
    return receipts


def _manifest_payload(
    *,
    bundle_manifest: Mapping[str, Any],
    config: SkillCenterEmbeddingConfig,
    identity: Mapping[str, str],
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    source_records_processed = sum(
        int(receipt["source_record_count"]) for receipt in receipts
    )
    source_records_total = int(bundle_manifest["total_skills"])
    dimensions = {
        int(receipt["dimension"])
        for receipt in receipts
        if int(receipt.get("dimension") or 0)
    }
    if len(dimensions) > 1:
        raise SkillCenterEmbeddingError("embedding dimensions are inconsistent")
    decision_counts: Counter[str] = Counter()
    for receipt in receipts:
        decision_counts.update(
            {
                str(key): int(value)
                for key, value in dict(receipt["decision_counts"]).items()
            }
        )
    return {
        **identity,
        "batch_count": len(receipts),
        "batches": [
            {
                "batch_index": int(receipt["batch_index"]),
                "receipt_sha256": hashlib.sha256(
                    _canonical_json_bytes(receipt)
                ).hexdigest(),
            }
            for receipt in receipts
        ],
        "bundle_manifest": dict(bundle_manifest),
        "config": config.to_dict(),
        "decision_counts": dict(sorted(decision_counts.items())),
        "dimension": next(iter(dimensions), 0),
        "embedded_records": sum(
            int(receipt["embedded_records"]) for receipt in receipts
        ),
        "last_skill_id": (
            str(receipts[-1]["source_last_skill_id"]) if receipts else ""
        ),
        "schema_version": SKILLCENTER_EMBEDDING_CORPUS_SCHEMA_VERSION,
        "source_records_processed": source_records_processed,
        "source_records_total": source_records_total,
        "status": (
            "complete"
            if source_records_processed == source_records_total
            else "partial"
        ),
        "vector_count": sum(
            int(receipt["vector_count"]) for receipt in receipts
        ),
    }


def _write_manifest(
    root: Path,
    *,
    bundle_manifest: Mapping[str, Any],
    config: SkillCenterEmbeddingConfig,
    identity: Mapping[str, str],
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    payload = _manifest_payload(
        bundle_manifest=bundle_manifest,
        config=config,
        identity=identity,
        receipts=receipts,
    )
    _write_bytes_atomic(root / "manifest.json", _canonical_json_bytes(payload))
    return payload


def _normalize_vectors(value: object, expected_count: int) -> list[list[float]]:
    if hasattr(value, "tolist") and callable(getattr(value, "tolist")):
        value = value.tolist()
    if not isinstance(value, (list, tuple)) or len(value) != expected_count:
        raise SkillCenterEmbeddingError(
            "embedder output count does not match embedding inputs"
        )
    vectors: list[list[float]] = []
    dimension = 0
    for row in value:
        if hasattr(row, "tolist") and callable(getattr(row, "tolist")):
            row = row.tolist()
        if not isinstance(row, (list, tuple)) or not row:
            raise SkillCenterEmbeddingError(
                "embedder returned an empty or malformed vector"
            )
        try:
            vector = [float(item) for item in row]
        except (TypeError, ValueError) as exc:
            raise SkillCenterEmbeddingError(
                "embedder returned a non-numeric vector"
            ) from exc
        if not all(math.isfinite(item) for item in vector):
            raise SkillCenterEmbeddingError(
                "embedder returned a non-finite vector"
            )
        if not dimension:
            dimension = len(vector)
        elif len(vector) != dimension:
            raise SkillCenterEmbeddingError(
                "embedder returned inconsistent dimensions"
            )
        vectors.append(vector)
    return vectors


def _pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise SkillCenterEmbeddingError(
            "pyarrow is required to persist embedding checkpoints"
        ) from exc
    return pa, parquet


def _file_descriptor(path: Path) -> dict[str, Any]:
    return {
        "name": path.name,
        "sha256": _file_sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _verify_file_descriptor(batch_dir: Path, value: object) -> Path:
    if not isinstance(value, Mapping):
        raise SkillCenterEmbeddingError("checkpoint file descriptor is invalid")
    name = str(value.get("name") or "")
    if Path(name).name != name:
        raise SkillCenterEmbeddingError("checkpoint filename is invalid")
    path = batch_dir / name
    if path.is_symlink() or not path.is_file():
        raise SkillCenterEmbeddingError(f"checkpoint file is missing: {name}")
    if path.stat().st_size != int(value.get("size_bytes") or -1):
        raise SkillCenterEmbeddingError(f"checkpoint size mismatch: {name}")
    if _file_sha256(path) != str(value.get("sha256") or ""):
        raise SkillCenterEmbeddingError(f"checkpoint hash mismatch: {name}")
    return path


def _receipt_int(
    receipt: Mapping[str, Any],
    key: str,
    *,
    minimum: int,
) -> int:
    value = receipt.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SkillCenterEmbeddingError(f"batch receipt {key} is invalid")
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".partial",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


@contextmanager
def _output_lock(root: Path) -> Iterator[None]:
    lock_path = root / ".embedding-job.lock"
    if lock_path.is_symlink() or (lock_path.exists() and not lock_path.is_file()):
        raise SkillCenterEmbeddingError("embedding job lock is invalid")
    with lock_path.open("a+b") as handle:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SkillCenterEmbeddingError(
                "another embedding job already owns this output directory"
            ) from exc
        try:
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


__all__ = [
    "DEFAULT_CHUNK_CHARS",
    "DEFAULT_CHUNK_OVERLAP_CHARS",
    "DEFAULT_EMBEDDING_DEVICE",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_EMBEDDING_PROVIDER",
    "DEFAULT_SOURCE_BATCH_SIZE",
    "SKILLCENTER_EMBEDDING_BATCH_SCHEMA_VERSION",
    "SKILLCENTER_EMBEDDING_CORPUS_SCHEMA_VERSION",
    "SKILLCENTER_EMBEDDING_TEXT_SCHEMA_VERSION",
    "SkillCenterEmbeddingConfig",
    "SkillCenterEmbeddingError",
    "SkillCenterEmbeddingRunSummary",
    "build_skillcenter_embedding_chunks",
    "iter_skillcenter_embedding_rows",
    "load_skillcenter_embedding_corpus",
    "run_skillcenter_embedding_job",
]
