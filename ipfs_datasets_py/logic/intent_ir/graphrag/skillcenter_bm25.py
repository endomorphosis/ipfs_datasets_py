"""Policy-gated, persisted BM25 bag-of-words indexes for SkillCenter.

The index is an explainable lexical sidecar for Intent IR GraphRAG.  It stores
document metadata, vocabulary statistics, and term-frequency postings in
Parquet.  Raw ``skill_md`` and other source bodies are never copied into the
index and must remain separately content addressed.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Any, Final, Iterator

from ipfs_datasets_py.processors.retrieval import tokenize_lexical_text

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import cid_v1
from ..source_adapters.policy import (
    AllowedUseDecision,
    SKILL_SOURCE_POLICY_VERSION,
    SkillSourcePolicy,
)
from ..source_adapters.skillcenter import (
    SkillCenterBundleReader,
    SkillCenterSkillRecord,
)


SKILLCENTER_BM25_INDEX_SCHEMA_VERSION: Final = "skillcenter-bm25-index/v1"
SKILLCENTER_BM25_DOCUMENT_SCHEMA_VERSION: Final = (
    "skillcenter-bm25-document/v1"
)
SKILLCENTER_BM25_TERM_SCHEMA_VERSION: Final = "skillcenter-bm25-term/v1"
SKILLCENTER_BM25_POSTING_SCHEMA_VERSION: Final = (
    "skillcenter-bm25-posting/v1"
)
SKILLCENTER_BM25_POLICY_SCHEMA_VERSION: Final = (
    "skillcenter-bm25-policy-ledger/v1"
)
SKILLCENTER_BM25_TOKENIZER_VERSION: Final = (
    "ascii-alphanumeric-underscore-lowercase/v1"
)
DEFAULT_BM25_K1: Final = 1.5
DEFAULT_BM25_B: Final = 0.75
DEFAULT_TITLE_BOOST: Final = 2
DEFAULT_MAX_TOKEN_CHARS: Final = 128

_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_CONTENT_ALLOWED_USES = frozenset(
    {
        AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH,
        AllowedUseDecision.ALLOW_INTERNAL_EVALUATION,
    }
)
_FILTER_FIELDS = frozenset(
    {
        "allowed_use",
        "domain",
        "language",
        "profile",
        "repository_file",
        "skill_id",
        "source_type",
    }
)
_FORBIDDEN_COLUMNS = frozenset(
    {
        "body",
        "content",
        "library_md",
        "metadata_yaml",
        "skill_md",
        "source_body",
        "source_text",
        "text",
    }
)


class SkillCenterBM25Error(ValueError):
    """Raised when a BM25 build or persisted artifact is invalid."""


@dataclass(frozen=True, slots=True)
class SkillCenterBM25Config:
    """Stable tokenizer, weighting, and policy configuration."""

    k1: float = DEFAULT_BM25_K1
    b: float = DEFAULT_BM25_B
    title_boost: int = DEFAULT_TITLE_BOOST
    max_token_chars: int = DEFAULT_MAX_TOKEN_CHARS
    included_allowed_uses: tuple[AllowedUseDecision, ...] = (
        AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH,
        AllowedUseDecision.ALLOW_INTERNAL_EVALUATION,
    )
    tokenizer_version: str = SKILLCENTER_BM25_TOKENIZER_VERSION
    policy_version: str = SKILL_SOURCE_POLICY_VERSION

    def __post_init__(self) -> None:
        for field_name in ("k1", "b"):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise SkillCenterBM25Error(
                    f"{field_name} must be finite"
                )
            object.__setattr__(self, field_name, float(value))
        if self.k1 <= 0.0:
            raise SkillCenterBM25Error("k1 must be positive")
        if not 0.0 <= self.b <= 1.0:
            raise SkillCenterBM25Error("b must be between 0 and 1")
        if (
            isinstance(self.title_boost, bool)
            or not isinstance(self.title_boost, int)
            or not 1 <= self.title_boost <= 16
        ):
            raise SkillCenterBM25Error(
                "title_boost must be between 1 and 16"
            )
        if (
            isinstance(self.max_token_chars, bool)
            or not isinstance(self.max_token_chars, int)
            or not 8 <= self.max_token_chars <= 1024
        ):
            raise SkillCenterBM25Error(
                "max_token_chars must be between 8 and 1024"
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
            raise SkillCenterBM25Error(
                "included_allowed_uses contains an unsupported decision"
            ) from exc
        if not allowed_uses or not set(allowed_uses) <= _CONTENT_ALLOWED_USES:
            raise SkillCenterBM25Error(
                "BM25 content must be train/publish or internal-evaluation allowed"
            )
        if self.tokenizer_version != SKILLCENTER_BM25_TOKENIZER_VERSION:
            raise SkillCenterBM25Error("unsupported tokenizer_version")
        if self.policy_version != SKILL_SOURCE_POLICY_VERSION:
            raise SkillCenterBM25Error("unsupported policy_version")
        object.__setattr__(self, "included_allowed_uses", allowed_uses)

    def to_dict(self) -> dict[str, Any]:
        return {
            "b": self.b,
            "included_allowed_uses": [
                item.value for item in self.included_allowed_uses
            ],
            "k1": self.k1,
            "max_token_chars": self.max_token_chars,
            "policy_version": self.policy_version,
            "title_boost": self.title_boost,
            "tokenizer_version": self.tokenizer_version,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.to_dict())).hexdigest()


@dataclass(frozen=True, slots=True)
class SkillCenterBM25BuildSummary:
    """Compact result for a built or verified existing lexical index."""

    output_dir: str
    dataset_revision: str
    source_records: int
    indexed_skills: int
    vocabulary_size: int
    posting_count: int
    average_document_length: float
    manifest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "average_document_length": self.average_document_length,
            "dataset_revision": self.dataset_revision,
            "indexed_skills": self.indexed_skills,
            "manifest_sha256": self.manifest_sha256,
            "output_dir": self.output_dir,
            "posting_count": self.posting_count,
            "source_records": self.source_records,
            "vocabulary_size": self.vocabulary_size,
        }


@dataclass(frozen=True, slots=True)
class SkillCenterBM25SearchHit:
    """One explainable lexical result without inline source content."""

    document_index: int
    skill_id: str
    score: float
    matched_terms: tuple[str, ...]
    metadata: Mapping[str, Any]
    authority: str = "context_only"
    proof_authority: bool = False

    def __post_init__(self) -> None:
        if (
            isinstance(self.document_index, bool)
            or not isinstance(self.document_index, int)
            or self.document_index < 0
        ):
            raise SkillCenterBM25Error(
                "document_index must be non-negative"
            )
        if not self.skill_id or not math.isfinite(float(self.score)):
            raise SkillCenterBM25Error("BM25 hit is malformed")
        if self.authority != "context_only" or self.proof_authority is not False:
            raise SkillCenterBM25Error("BM25 hits are context-only")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "document_index": self.document_index,
            "matched_terms": list(self.matched_terms),
            "metadata": dict(self.metadata),
            "proof_authority": self.proof_authority,
            "score": self.score,
            "skill_id": self.skill_id,
        }


class SkillCenterBM25Index:
    """Verified in-memory search facade over persisted Parquet postings."""

    def __init__(
        self,
        *,
        root: Path,
        manifest: Mapping[str, Any],
        config: SkillCenterBM25Config,
        documents: Sequence[Mapping[str, Any]],
        terms: Sequence[Mapping[str, Any]],
        postings: Sequence[Mapping[str, Any]],
        policy_rows: Sequence[Mapping[str, Any]],
    ) -> None:
        self.root = root
        self.manifest = dict(manifest)
        self.config = config
        self.documents = tuple(dict(row) for row in documents)
        self.terms = tuple(dict(row) for row in terms)
        self.postings = tuple(dict(row) for row in postings)
        self.policy_rows = tuple(dict(row) for row in policy_rows)
        self._term_id_by_value = {
            str(row["term"]): int(row["term_id"]) for row in self.terms
        }
        self._term_by_id = tuple(str(row["term"]) for row in self.terms)
        postings_by_term: dict[int, list[tuple[int, int, float]]] = defaultdict(
            list
        )
        document_terms: dict[int, list[int]] = defaultdict(list)
        for row in self.postings:
            term_id = int(row["term_id"])
            document_index = int(row["document_index"])
            postings_by_term[term_id].append(
                (
                    document_index,
                    int(row["term_frequency"]),
                    float(row["bm25_term_score"]),
                )
            )
            document_terms[document_index].append(term_id)
        self._postings_by_term = {
            key: tuple(value) for key, value in postings_by_term.items()
        }
        self._document_terms = {
            key: tuple(value) for key, value in document_terms.items()
        }
        self._document_by_skill = {
            str(row["skill_id"]): int(row["document_index"])
            for row in self.documents
        }

    @classmethod
    def load(cls, root: str | Path) -> "SkillCenterBM25Index":
        """Load an index only after replaying its full integrity contract."""

        index_root = Path(root).expanduser().resolve()
        manifest_path = index_root / "manifest.json"
        if (
            index_root.is_symlink()
            or not index_root.is_dir()
            or manifest_path.is_symlink()
            or not manifest_path.is_file()
            or manifest_path.stat().st_size > _MAX_MANIFEST_BYTES
        ):
            raise SkillCenterBM25Error(
                "BM25 index must contain a bounded regular manifest.json"
            )
        manifest_bytes = manifest_path.read_bytes()
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SkillCenterBM25Error("BM25 manifest is malformed") from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version")
            != SKILLCENTER_BM25_INDEX_SCHEMA_VERSION
        ):
            raise SkillCenterBM25Error("unsupported BM25 manifest")
        config_payload = manifest.get("config")
        if not isinstance(config_payload, Mapping):
            raise SkillCenterBM25Error("BM25 manifest config is missing")
        try:
            config = SkillCenterBM25Config(**dict(config_payload))
        except (TypeError, ValueError) as exc:
            raise SkillCenterBM25Error("BM25 manifest config is invalid") from exc
        if manifest.get("config_sha256") != config.digest:
            raise SkillCenterBM25Error(
                "BM25 config_sha256 does not match config"
            )
        files = manifest.get("files")
        required = {"documents", "policy", "postings", "terms"}
        if not isinstance(files, Mapping) or set(files) != required:
            raise SkillCenterBM25Error(
                "BM25 manifest has an unexpected file set"
            )
        paths = {
            key: _verify_file_descriptor(index_root, files[key])
            for key in sorted(required)
        }
        _, parquet = _pyarrow()
        documents = parquet.read_table(paths["documents"]).to_pylist()
        terms = parquet.read_table(paths["terms"]).to_pylist()
        postings = parquet.read_table(paths["postings"]).to_pylist()
        policy_rows = parquet.read_table(paths["policy"]).to_pylist()
        _validate_loaded_index(
            manifest,
            config,
            documents,
            terms,
            postings,
            policy_rows,
        )
        return cls(
            root=index_root,
            manifest=manifest,
            config=config,
            documents=documents,
            terms=terms,
            postings=postings,
            policy_rows=policy_rows,
        )

    @property
    def summary(self) -> SkillCenterBM25BuildSummary:
        return _summary_from_manifest(self.root, self.manifest)

    @property
    def indexed_skill_ids(self) -> frozenset[str]:
        return frozenset(self._document_by_skill)

    def search(
        self,
        query: str,
        *,
        k: int = 10,
        filters: Mapping[str, str | Sequence[str]] | None = None,
        exclude_skill_id: str = "",
        max_matched_terms: int = 32,
    ) -> tuple[SkillCenterBM25SearchHit, ...]:
        """Search an arbitrary query using exact persisted BM25 contributions."""

        query_text = str(query or "").strip()
        if not query_text:
            raise SkillCenterBM25Error("query must not be empty")
        term_ids = tuple(
            sorted(
                {
                    self._term_id_by_value[token]
                    for token in _tokenize(query_text, self.config)
                    if token in self._term_id_by_value
                }
            )
        )
        return self._search_term_ids(
            term_ids,
            k=k,
            filters=_prepare_filters(filters),
            exclude_skill_id=str(exclude_skill_id or ""),
            max_matched_terms=max_matched_terms,
        )

    def skill_neighbors(
        self,
        skill_id: str,
        *,
        k: int = 8,
        max_matched_terms: int = 32,
    ) -> tuple[SkillCenterBM25SearchHit, ...]:
        """Treat one indexed skill's bag of words as a lexical query."""

        normalized = str(skill_id or "").strip()
        try:
            document_index = self._document_by_skill[normalized]
        except KeyError as exc:
            raise SkillCenterBM25Error(
                f"skill is not indexed: {normalized!r}"
            ) from exc
        return self._search_term_ids(
            self._document_terms.get(document_index, ()),
            k=k,
            filters={},
            exclude_skill_id=normalized,
            max_matched_terms=max_matched_terms,
        )

    def all_skill_neighbors(
        self,
        *,
        k: int = 8,
        max_matched_terms: int = 32,
    ) -> dict[str, tuple[SkillCenterBM25SearchHit, ...]]:
        """Return deterministic top-k lexical neighborhoods for every skill."""

        return {
            skill_id: self.skill_neighbors(
                skill_id,
                k=k,
                max_matched_terms=max_matched_terms,
            )
            for skill_id in sorted(self._document_by_skill)
        }

    def _search_term_ids(
        self,
        term_ids: Sequence[int],
        *,
        k: int,
        filters: Mapping[str, frozenset[str]],
        exclude_skill_id: str,
        max_matched_terms: int,
    ) -> tuple[SkillCenterBM25SearchHit, ...]:
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 256:
            raise SkillCenterBM25Error("k must be between 1 and 256")
        if (
            isinstance(max_matched_terms, bool)
            or not isinstance(max_matched_terms, int)
            or not 1 <= max_matched_terms <= 256
        ):
            raise SkillCenterBM25Error(
                "max_matched_terms must be between 1 and 256"
            )
        scores: Counter[int] = Counter()
        contributions: dict[int, dict[int, float]] = defaultdict(dict)
        for term_id in sorted(set(int(item) for item in term_ids)):
            for document_index, _frequency, term_score in self._postings_by_term.get(
                term_id, ()
            ):
                scores[document_index] += term_score
                contributions[document_index][term_id] = term_score
        ranked = sorted(
            scores,
            key=lambda document_index: (
                -float(scores[document_index]),
                str(self.documents[document_index]["skill_id"]),
            ),
        )
        hits = []
        for document_index in ranked:
            document = self.documents[document_index]
            skill_id = str(document["skill_id"])
            if skill_id == exclude_skill_id or not _matches_filters(
                document, filters
            ):
                continue
            matched = tuple(
                self._term_by_id[term_id]
                for term_id, _score in sorted(
                    contributions[document_index].items(),
                    key=lambda item: (
                        -float(item[1]),
                        self._term_by_id[item[0]],
                    ),
                )[:max_matched_terms]
            )
            hits.append(
                SkillCenterBM25SearchHit(
                    document_index=document_index,
                    skill_id=skill_id,
                    score=float(scores[document_index]),
                    matched_terms=matched,
                    metadata=document,
                )
            )
            if len(hits) == k:
                break
        return tuple(hits)


def build_skillcenter_bm25_index(
    readers: Sequence[SkillCenterBundleReader],
    *,
    output_dir: str | Path,
    config: SkillCenterBM25Config | None = None,
    policy: SkillSourcePolicy | None = None,
) -> SkillCenterBM25BuildSummary:
    """Build an atomic policy-gated BM25 inverted index."""

    active_config = config or SkillCenterBM25Config()
    if not isinstance(active_config, SkillCenterBM25Config):
        raise TypeError("config must be a SkillCenterBM25Config")
    active_policy = policy or SkillSourcePolicy()
    prepared_readers = tuple(readers)
    if not prepared_readers or any(
        not isinstance(reader, SkillCenterBundleReader)
        for reader in prepared_readers
    ):
        raise TypeError(
            "readers must contain at least one SkillCenterBundleReader"
        )
    manifests = tuple(
        sorted(
            (reader.inspect() for reader in prepared_readers),
            key=lambda item: item.repository_file,
        )
    )
    if len({item.repository_file for item in manifests}) != len(manifests):
        raise SkillCenterBM25Error("reader repository files must be unique")
    if (
        len({item.dataset_id for item in manifests}) != 1
        or len({item.dataset_revision for item in manifests}) != 1
    ):
        raise SkillCenterBM25Error(
            "all BM25 source bundles must share one dataset revision"
        )
    inputs = [
        {
            "bundle_sha256": item.local_sha256,
            "profile": _profile_for_reader(
                next(
                    reader
                    for reader in prepared_readers
                    if reader.inspect().repository_file == item.repository_file
                )
            ),
            "repository_file": item.repository_file,
            "source_records": item.total_skills,
        }
        for item in manifests
    ]
    identity_payload = {
        "config": active_config.to_dict(),
        "inputs": inputs,
        "schema_version": SKILLCENTER_BM25_INDEX_SCHEMA_VERSION,
    }
    build_identity_sha256 = hashlib.sha256(
        canonical_json_bytes(identity_payload)
    ).hexdigest()
    output = Path(output_dir).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise SkillCenterBM25Error("output_dir must not be a symlink")
    with _build_lock(output):
        if output.exists():
            existing = SkillCenterBM25Index.load(output)
            if (
                existing.manifest.get("build_identity_sha256")
                != build_identity_sha256
            ):
                raise SkillCenterBM25Error(
                    "existing BM25 index was built from different inputs or config"
                )
            return existing.summary
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output.name}.",
                suffix=".partial",
                dir=output.parent,
            )
        )
        try:
            manifest = _build_into_directory(
                staging,
                readers=prepared_readers,
                source_manifests=manifests,
                inputs=inputs,
                build_identity_sha256=build_identity_sha256,
                config=active_config,
                policy=active_policy,
            )
            os.replace(staging, output)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
    loaded = SkillCenterBM25Index.load(output)
    if loaded.manifest != manifest:
        raise SkillCenterBM25Error(
            "published BM25 manifest changed during atomic promotion"
        )
    return loaded.summary


def _build_into_directory(
    root: Path,
    *,
    readers: Sequence[SkillCenterBundleReader],
    source_manifests: Sequence[Any],
    inputs: Sequence[Mapping[str, Any]],
    build_identity_sha256: str,
    config: SkillCenterBM25Config,
    policy: SkillSourcePolicy,
) -> dict[str, Any]:
    records = []
    for reader in sorted(
        readers,
        key=lambda item: item.inspect().repository_file,
    ):
        records.extend(reader.iter_records())
    records.sort(key=lambda item: (item.repository_file, item.skill_id))
    if len({record.skill_id for record in records}) != len(records):
        raise SkillCenterBM25Error(
            "skill_id values must be globally unique across bundles"
        )

    policy_rows = []
    prepared_documents = []
    decision_counts: Counter[str] = Counter()
    document_frequency: Counter[str] = Counter()
    corpus_frequency: Counter[str] = Counter()
    for record in records:
        decision = policy.evaluate(record)
        decision_counts[decision.allowed_use.value] += 1
        source_ref = record.to_source_ref(review_status=decision.review_status)
        policy_rows.append(
            {
                "allowed_use": decision.allowed_use.value,
                "bundle_sha256": record.bundle_sha256,
                "content_sha256": record.content_sha256,
                "dataset_id": record.dataset_id,
                "dataset_revision": record.dataset_revision,
                "embedded_or_indexed": (
                    decision.allowed_use in config.included_allowed_uses
                ),
                "finding_codes": sorted(
                    {finding.code for finding in decision.findings}
                ),
                "license_expression": decision.license_decision.expression,
                "profile": record.profile,
                "repository_file": record.repository_file,
                "schema_version": SKILLCENTER_BM25_POLICY_SCHEMA_VERSION,
                "skill_id": record.skill_id,
                "source_ref_id": source_ref.ref_id,
                "trust_decision": decision.trust_decision.value,
            }
        )
        if decision.allowed_use not in config.included_allowed_uses:
            continue
        tokens = _record_tokens(record, config)
        if not tokens:
            continue
        counts = Counter(tokens)
        document_frequency.update(counts.keys())
        corpus_frequency.update(counts)
        prepared_documents.append((record, decision, source_ref, counts))

    document_count = len(prepared_documents)
    if document_count < 1:
        raise SkillCenterBM25Error(
            "BM25 index requires at least one policy-eligible document"
        )
    total_tokens = sum(
        sum(counts.values())
        for _record, _decision, _source_ref, counts in prepared_documents
    )
    average_document_length = total_tokens / document_count
    vocabulary = sorted(document_frequency)
    term_id_by_value = {
        term: term_id for term_id, term in enumerate(vocabulary)
    }
    terms = []
    for term_id, term in enumerate(vocabulary):
        df = int(document_frequency[term])
        terms.append(
            {
                "corpus_frequency": int(corpus_frequency[term]),
                "document_frequency": df,
                "idf": _idf(document_count, df),
                "schema_version": SKILLCENTER_BM25_TERM_SCHEMA_VERSION,
                "term": term,
                "term_id": term_id,
            }
        )

    documents = []
    postings = []
    for document_index, (
        record,
        decision,
        source_ref,
        counts,
    ) in enumerate(prepared_documents):
        document_length = sum(counts.values())
        documents.append(
            {
                "allowed_use": decision.allowed_use.value,
                "bundle_sha256": record.bundle_sha256,
                "content_sha256": record.content_sha256,
                "dataset_id": record.dataset_id,
                "dataset_revision": record.dataset_revision,
                "document_index": document_index,
                "document_length": document_length,
                "domain": record.domain,
                "language": record.language,
                "license_expression": decision.license_decision.expression,
                "profile": record.profile,
                "repository_file": record.repository_file,
                "schema_version": SKILLCENTER_BM25_DOCUMENT_SCHEMA_VERSION,
                "skill_id": record.skill_id,
                "skill_kind": record.skill_kind,
                "source_ref_id": source_ref.ref_id,
                "source_type": record.source_type,
                "title": record.title,
                "unique_term_count": len(counts),
            }
        )
        for term, term_frequency in sorted(counts.items()):
            term_id = term_id_by_value[term]
            postings.append(
                {
                    "bm25_term_score": _term_score(
                        term_frequency,
                        document_length,
                        idf=float(terms[term_id]["idf"]),
                        average_document_length=average_document_length,
                        config=config,
                    ),
                    "document_index": document_index,
                    "document_length": document_length,
                    "schema_version": SKILLCENTER_BM25_POSTING_SCHEMA_VERSION,
                    "term_frequency": int(term_frequency),
                    "term_id": term_id,
                }
            )

    postings.sort(
        key=lambda row: (
            int(row["term_id"]),
            int(row["document_index"]),
        )
    )
    _write_documents(root / "documents.parquet", documents)
    _write_terms(root / "terms.parquet", terms)
    _write_postings(root / "postings.parquet", postings)
    _write_policy(root / "policy.parquet", policy_rows)
    files = {
        "documents": _file_descriptor(
            root / "documents.parquet",
            root=root,
        ),
        "policy": _file_descriptor(root / "policy.parquet", root=root),
        "postings": _file_descriptor(root / "postings.parquet", root=root),
        "terms": _file_descriptor(root / "terms.parquet", root=root),
    }
    manifest = {
        "average_document_length": average_document_length,
        "build_identity_sha256": build_identity_sha256,
        "config": config.to_dict(),
        "config_sha256": config.digest,
        "dataset_id": source_manifests[0].dataset_id,
        "dataset_revision": source_manifests[0].dataset_revision,
        "decision_counts": dict(sorted(decision_counts.items())),
        "files": files,
        "indexed_skills": document_count,
        "inputs": list(inputs),
        "posting_count": len(postings),
        "schema_version": SKILLCENTER_BM25_INDEX_SCHEMA_VERSION,
        "source_records": len(records),
        "total_tokens": total_tokens,
        "vocabulary_size": len(terms),
    }
    _write_bytes(root / "manifest.json", canonical_json_bytes(manifest))
    return manifest


def _profile_for_reader(reader: SkillCenterBundleReader) -> str:
    record = next(reader.iter_records(limit=1), None)
    return record.profile if record is not None else "unknown"


def _record_tokens(
    record: SkillCenterSkillRecord,
    config: SkillCenterBM25Config,
) -> list[str]:
    fields = [
        *(record.title for _ in range(config.title_boost)),
        record.domain,
        record.profile,
        record.skill_kind,
        record.skill_md,
    ]
    tokens = []
    for value in fields:
        tokens.extend(_tokenize(value, config))
    return tokens


def _tokenize(value: str, config: SkillCenterBM25Config) -> list[str]:
    return [
        token
        for token in tokenize_lexical_text(value)
        if len(token) <= config.max_token_chars
    ]


def _idf(document_count: int, document_frequency: int) -> float:
    return math.log(
        1.0
        + (
            (document_count - document_frequency + 0.5)
            / (document_frequency + 0.5)
        )
    )


def _term_score(
    term_frequency: int,
    document_length: int,
    *,
    idf: float,
    average_document_length: float,
    config: SkillCenterBM25Config,
) -> float:
    denominator = term_frequency + config.k1 * (
        1.0
        - config.b
        + config.b * (document_length / max(1.0, average_document_length))
    )
    return idf * (
        (term_frequency * (config.k1 + 1.0))
        / max(1e-12, denominator)
    )


def _validate_loaded_index(
    manifest: Mapping[str, Any],
    config: SkillCenterBM25Config,
    documents: Sequence[Mapping[str, Any]],
    terms: Sequence[Mapping[str, Any]],
    postings: Sequence[Mapping[str, Any]],
    policy_rows: Sequence[Mapping[str, Any]],
) -> None:
    expected_counts = {
        "indexed_skills": len(documents),
        "posting_count": len(postings),
        "source_records": len(policy_rows),
        "vocabulary_size": len(terms),
    }
    if any(int(manifest.get(key, -1)) != value for key, value in expected_counts.items()):
        raise SkillCenterBM25Error(
            "BM25 parquet row counts do not match the manifest"
        )
    for rows in (documents, terms, postings, policy_rows):
        if rows and _FORBIDDEN_COLUMNS & set(rows[0]):
            raise SkillCenterBM25Error(
                "BM25 artifact contains a prohibited source-body column"
            )
    if [int(row.get("document_index", -1)) for row in documents] != list(
        range(len(documents))
    ):
        raise SkillCenterBM25Error(
            "BM25 document indexes are not contiguous"
        )
    skill_ids = [str(row.get("skill_id", "")) for row in documents]
    if any(not value for value in skill_ids) or len(set(skill_ids)) != len(skill_ids):
        raise SkillCenterBM25Error(
            "BM25 document skill IDs must be non-empty and unique"
        )
    if [int(row.get("term_id", -1)) for row in terms] != list(range(len(terms))):
        raise SkillCenterBM25Error("BM25 term IDs are not contiguous")
    term_values = [str(row.get("term", "")) for row in terms]
    if term_values != sorted(set(term_values)):
        raise SkillCenterBM25Error(
            "BM25 terms must be unique and canonically sorted"
        )
    posting_keys = [
        (int(row.get("term_id", -1)), int(row.get("document_index", -1)))
        for row in postings
    ]
    if posting_keys != sorted(set(posting_keys)):
        raise SkillCenterBM25Error(
            "BM25 postings must be unique and canonically sorted"
        )
    doc_lengths: Counter[int] = Counter()
    doc_unique: Counter[int] = Counter()
    term_df: Counter[int] = Counter()
    term_cf: Counter[int] = Counter()
    for row in postings:
        term_id = int(row.get("term_id", -1))
        document_index = int(row.get("document_index", -1))
        frequency = int(row.get("term_frequency", 0))
        if (
            not 0 <= term_id < len(terms)
            or not 0 <= document_index < len(documents)
            or frequency < 1
            or row.get("schema_version")
            != SKILLCENTER_BM25_POSTING_SCHEMA_VERSION
        ):
            raise SkillCenterBM25Error("BM25 posting is malformed")
        doc_lengths[document_index] += frequency
        doc_unique[document_index] += 1
        term_df[term_id] += 1
        term_cf[term_id] += frequency
    average_document_length = (
        sum(doc_lengths.values()) / max(1, len(documents))
    )
    if not math.isclose(
        average_document_length,
        float(manifest.get("average_document_length", -1.0)),
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise SkillCenterBM25Error(
            "BM25 average document length does not match postings"
        )
    for document_index, row in enumerate(documents):
        if (
            int(row.get("document_length", -1)) != doc_lengths[document_index]
            or int(row.get("unique_term_count", -1))
            != doc_unique[document_index]
            or row.get("schema_version")
            != SKILLCENTER_BM25_DOCUMENT_SCHEMA_VERSION
        ):
            raise SkillCenterBM25Error(
                "BM25 document statistics do not match postings"
            )
    for term_id, row in enumerate(terms):
        expected_idf = _idf(len(documents), term_df[term_id])
        if (
            int(row.get("document_frequency", -1)) != term_df[term_id]
            or int(row.get("corpus_frequency", -1)) != term_cf[term_id]
            or not math.isclose(
                float(row.get("idf", math.nan)),
                expected_idf,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            or row.get("schema_version")
            != SKILLCENTER_BM25_TERM_SCHEMA_VERSION
        ):
            raise SkillCenterBM25Error(
                "BM25 term statistics do not match postings"
            )
    for row in postings:
        term = terms[int(row["term_id"])]
        expected_score = _term_score(
            int(row["term_frequency"]),
            int(row["document_length"]),
            idf=float(term["idf"]),
            average_document_length=average_document_length,
            config=config,
        )
        if (
            int(row["document_length"])
            != doc_lengths[int(row["document_index"])]
            or not math.isclose(
                float(row["bm25_term_score"]),
                expected_score,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ):
            raise SkillCenterBM25Error(
                "BM25 posting score or document length is invalid"
            )
    eligible_policy_ids = {
        str(row["skill_id"])
        for row in policy_rows
        if AllowedUseDecision(str(row["allowed_use"]))
        in config.included_allowed_uses
    }
    if eligible_policy_ids != set(skill_ids):
        raise SkillCenterBM25Error(
            "BM25 documents do not match policy-eligible skills"
        )
    if any(
        row.get("schema_version") != SKILLCENTER_BM25_POLICY_SCHEMA_VERSION
        for row in policy_rows
    ):
        raise SkillCenterBM25Error("BM25 policy ledger schema is invalid")


def _prepare_filters(
    filters: Mapping[str, str | Sequence[str]] | None,
) -> dict[str, frozenset[str]]:
    if filters is None:
        return {}
    if not isinstance(filters, Mapping):
        raise TypeError("filters must be a mapping")
    unknown = set(filters) - _FILTER_FIELDS
    if unknown:
        raise SkillCenterBM25Error(
            f"unsupported BM25 filter(s): {', '.join(sorted(unknown))}"
        )
    prepared = {}
    for key, value in filters.items():
        raw_values = (value,) if isinstance(value, str) else tuple(value)
        values = frozenset(str(item) for item in raw_values if str(item))
        if not values:
            raise SkillCenterBM25Error(
                f"BM25 filter {key!r} must not be empty"
            )
        prepared[key] = values
    return prepared


def _matches_filters(
    row: Mapping[str, Any],
    filters: Mapping[str, frozenset[str]],
) -> bool:
    return all(str(row.get(key, "")) in values for key, values in filters.items())


def _write_documents(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    pa, parquet = _pyarrow()
    schema = pa.schema(
        [
            ("allowed_use", pa.string()),
            ("bundle_sha256", pa.string()),
            ("content_sha256", pa.string()),
            ("dataset_id", pa.string()),
            ("dataset_revision", pa.string()),
            ("document_index", pa.int32()),
            ("document_length", pa.int32()),
            ("domain", pa.string()),
            ("language", pa.string()),
            ("license_expression", pa.string()),
            ("profile", pa.string()),
            ("repository_file", pa.string()),
            ("schema_version", pa.string()),
            ("skill_id", pa.string()),
            ("skill_kind", pa.string()),
            ("source_ref_id", pa.string()),
            ("source_type", pa.string()),
            ("title", pa.string()),
            ("unique_term_count", pa.int32()),
        ]
    )
    parquet.write_table(
        pa.Table.from_pylist(list(rows), schema=schema),
        path,
        compression="zstd",
    )


def _write_terms(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    pa, parquet = _pyarrow()
    schema = pa.schema(
        [
            ("corpus_frequency", pa.int64()),
            ("document_frequency", pa.int32()),
            ("idf", pa.float64()),
            ("schema_version", pa.string()),
            ("term", pa.string()),
            ("term_id", pa.int32()),
        ]
    )
    parquet.write_table(
        pa.Table.from_pylist(list(rows), schema=schema),
        path,
        compression="zstd",
    )


def _write_postings(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    pa, parquet = _pyarrow()
    schema = pa.schema(
        [
            ("bm25_term_score", pa.float64()),
            ("document_index", pa.int32()),
            ("document_length", pa.int32()),
            ("schema_version", pa.string()),
            ("term_frequency", pa.int32()),
            ("term_id", pa.int32()),
        ]
    )
    parquet.write_table(
        pa.Table.from_pylist(list(rows), schema=schema),
        path,
        compression="zstd",
    )


def _write_policy(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    pa, parquet = _pyarrow()
    schema = pa.schema(
        [
            ("allowed_use", pa.string()),
            ("bundle_sha256", pa.string()),
            ("content_sha256", pa.string()),
            ("dataset_id", pa.string()),
            ("dataset_revision", pa.string()),
            ("embedded_or_indexed", pa.bool_()),
            ("finding_codes", pa.list_(pa.string())),
            ("license_expression", pa.string()),
            ("profile", pa.string()),
            ("repository_file", pa.string()),
            ("schema_version", pa.string()),
            ("skill_id", pa.string()),
            ("source_ref_id", pa.string()),
            ("trust_decision", pa.string()),
        ]
    )
    parquet.write_table(
        pa.Table.from_pylist(list(rows), schema=schema),
        path,
        compression="zstd",
    )


def _file_descriptor(path: Path, *, root: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "cid": cid_v1(payload),
        "media_type": "application/vnd.apache.parquet",
        "relative_path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }


def _verify_file_descriptor(root: Path, value: object) -> Path:
    if not isinstance(value, Mapping):
        raise SkillCenterBM25Error("BM25 file descriptor must be an object")
    path = _safe_relative_file(root, str(value.get("relative_path", "")))
    payload = path.read_bytes()
    if (
        len(payload) != int(value.get("size_bytes", -1))
        or hashlib.sha256(payload).hexdigest()
        != str(value.get("sha256", ""))
        or cid_v1(payload) != str(value.get("cid", ""))
        or value.get("media_type") != "application/vnd.apache.parquet"
    ):
        raise SkillCenterBM25Error(
            "BM25 file descriptor failed verification"
        )
    return path


def _safe_relative_file(root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if (
        not relative_path
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != relative_path
    ):
        raise SkillCenterBM25Error(
            "BM25 artifact path must be normalized and relative"
        )
    path = root.joinpath(*relative.parts)
    if (
        path.is_symlink()
        or not path.is_file()
        or not path.resolve().is_relative_to(root)
    ):
        raise SkillCenterBM25Error(
            "BM25 artifact path is unsafe or missing"
        )
    return path


def _summary_from_manifest(
    root: Path,
    manifest: Mapping[str, Any],
) -> SkillCenterBM25BuildSummary:
    return SkillCenterBM25BuildSummary(
        output_dir=str(root),
        dataset_revision=str(manifest["dataset_revision"]),
        source_records=int(manifest["source_records"]),
        indexed_skills=int(manifest["indexed_skills"]),
        vocabulary_size=int(manifest["vocabulary_size"]),
        posting_count=int(manifest["posting_count"]),
        average_document_length=float(
            manifest["average_document_length"]
        ),
        manifest_sha256=_file_sha256(root / "manifest.json"),
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_bytes(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".partial",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise SkillCenterBM25Error(
            "pyarrow is required for the SkillCenter BM25 index"
        ) from exc
    return pa, parquet


@contextmanager
def _build_lock(output: Path) -> Iterator[None]:
    lock_path = output.parent / f".{output.name}.bm25.lock"
    if lock_path.is_symlink() or (
        lock_path.exists() and not lock_path.is_file()
    ):
        raise SkillCenterBM25Error("BM25 build lock is invalid")
    with lock_path.open("a+b") as handle:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SkillCenterBM25Error(
                "another BM25 build owns this output directory"
            ) from exc
        try:
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


__all__ = [
    "DEFAULT_BM25_B",
    "DEFAULT_BM25_K1",
    "DEFAULT_MAX_TOKEN_CHARS",
    "DEFAULT_TITLE_BOOST",
    "SKILLCENTER_BM25_DOCUMENT_SCHEMA_VERSION",
    "SKILLCENTER_BM25_INDEX_SCHEMA_VERSION",
    "SKILLCENTER_BM25_POLICY_SCHEMA_VERSION",
    "SKILLCENTER_BM25_POSTING_SCHEMA_VERSION",
    "SKILLCENTER_BM25_TERM_SCHEMA_VERSION",
    "SKILLCENTER_BM25_TOKENIZER_VERSION",
    "SkillCenterBM25BuildSummary",
    "SkillCenterBM25Config",
    "SkillCenterBM25Error",
    "SkillCenterBM25Index",
    "SkillCenterBM25SearchHit",
    "build_skillcenter_bm25_index",
]
