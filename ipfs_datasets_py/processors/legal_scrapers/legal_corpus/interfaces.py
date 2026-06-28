"""Shared interfaces for jurisdiction-backed legal corpus pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Literal, Mapping, Protocol, Sequence, runtime_checkable


LawStatus = Literal["current", "historical", "repealed", "superseded", "unknown"]
StatusConfidence = Literal["high", "medium", "low", "unknown"]

STATUS_FIELD_NAMES: tuple[str, ...] = (
    "law_status",
    "is_current",
    "valid_from",
    "valid_to",
    "effective_date",
    "retrieved_at",
    "status_source",
    "status_confidence",
    "status_note",
    "version_start_date",
    "version_end_date",
)


@dataclass(frozen=True)
class JurisdictionSpec:
    """Stable metadata describing one legal corpus implementation."""

    jurisdiction_id: str
    slug: str
    display_name: str
    country_code: str
    language_codes: tuple[str, ...]
    official_sources: tuple[str, ...]
    default_raw_dir: Path | None = None
    default_catalog_path: Path | None = None
    default_hf_namespace: str | None = None
    hf_repo_ids: Mapping[str, str] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()
    status_values: tuple[str, ...] = ("current", "historical", "repealed", "superseded", "unknown")


@dataclass(frozen=True)
class StatusMetadata:
    """Normalized status/version fields shared by law and article rows."""

    law_status: LawStatus
    is_current: bool | None
    valid_from: str = ""
    valid_to: str = ""
    effective_date: str = ""
    retrieved_at: str = ""
    status_source: str = ""
    status_confidence: StatusConfidence = "unknown"
    status_note: str = ""
    version_start_date: str = ""
    version_end_date: str = ""

    def as_row_fields(self) -> dict[str, Any]:
        return {
            "law_status": self.law_status,
            "is_current": self.is_current,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "effective_date": self.effective_date,
            "retrieved_at": self.retrieved_at,
            "status_source": self.status_source,
            "status_confidence": self.status_confidence,
            "status_note": self.status_note,
            "version_start_date": self.version_start_date,
            "version_end_date": self.version_end_date,
        }


@dataclass(frozen=True)
class HierarchyNode:
    """One normalized legal hierarchy node."""

    kind: str
    label: str
    number: str = ""
    parent_path: tuple[str, ...] = ()
    source_identifier: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveryRecord:
    """One source document candidate discovered from official metadata."""

    identifier: str
    document_url: str
    source: str
    information_url: str = ""
    title: str = ""
    document_type: str = ""
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchedDocument:
    """Fetched source document payload plus retrieval metadata."""

    identifier: str
    source_url: str
    body: str | bytes
    content_type: str = ""
    status_code: int | None = None
    retrieved_at: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedArticleRecord:
    """Normalized article-level row before package-specific addressing."""

    fields: Mapping[str, Any]


@dataclass(frozen=True)
class ParsedLawRecord:
    """Normalized law-level row and its extracted article rows."""

    fields: Mapping[str, Any]
    articles: tuple[ParsedArticleRecord, ...] = ()
    hierarchy: tuple[HierarchyNode, ...] = ()


@dataclass(frozen=True)
class PackageBuildResult:
    """Result of building a package or CID-addressed package."""

    variant: str
    output_dir: Path
    manifest_path: Path | None = None
    records: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class IndexBuildResult:
    """Result of building a retrieval or graph index package."""

    index_type: str
    output_dir: Path
    manifest_path: Path | None = None
    records: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class PublicationResult:
    """Result of uploading or verifying a remote dataset package."""

    target: str
    repo_id: str
    ok: bool | None = None
    records: Mapping[str, int] = field(default_factory=dict)
    details: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class DiscoveryProvider(Protocol):
    """Official-source discovery and durable catalog import/queue operations."""

    def discover(self, **kwargs: Any) -> Mapping[str, Any] | Iterable[DiscoveryRecord]:
        ...

    def import_catalog(self, **kwargs: Any) -> Mapping[str, Any]:
        ...

    def queue(self, **kwargs: Any) -> Mapping[str, Any]:
        ...

    def coverage_report(self, **kwargs: Any) -> Mapping[str, Any]:
        ...


@runtime_checkable
class FetchProvider(Protocol):
    """Fetching and resumable scrape execution for official source records."""

    def fetch(self, record: DiscoveryRecord | Mapping[str, Any], **kwargs: Any) -> FetchedDocument | Awaitable[Any]:
        ...

    def scrape_batch(self, **kwargs: Any) -> Awaitable[Mapping[str, Any]] | Mapping[str, Any]:
        ...

    def resume(self, **kwargs: Any) -> Awaitable[Mapping[str, Any]] | Mapping[str, Any]:
        ...


@runtime_checkable
class Parser(Protocol):
    """Jurisdiction-specific source parsing into normalized law/article rows."""

    def parse_document(self, document: FetchedDocument | Mapping[str, Any] | str, **kwargs: Any) -> ParsedLawRecord | Mapping[str, Any]:
        ...

    def sync_parsed_rows(self, **kwargs: Any) -> Mapping[str, Any]:
        ...


@runtime_checkable
class HierarchyExtractor(Protocol):
    """Legal hierarchy extraction and validation."""

    def extract_hierarchy(self, parsed_law: ParsedLawRecord | Mapping[str, Any], **kwargs: Any) -> Sequence[HierarchyNode]:
        ...

    def validate_hierarchy(self, rows: Iterable[Mapping[str, Any]], **kwargs: Any) -> Mapping[str, Any]:
        ...


@runtime_checkable
class StatusClassifier(Protocol):
    """Official metadata based status/version classification."""

    def classify_law(self, law: Mapping[str, Any] | str, **kwargs: Any) -> StatusMetadata:
        ...

    def inherit_article_status(self, law: Mapping[str, Any], article: Mapping[str, Any]) -> dict[str, Any]:
        ...


@runtime_checkable
class CIDGenerator(Protocol):
    """Deterministic content-address generation for law/article records."""

    def assign_record_cids(self, rows: Iterable[Mapping[str, Any]], **kwargs: Any) -> Iterable[dict[str, Any]]:
        ...

    def build_cid_package(self, **kwargs: Any) -> Path:
        ...


@runtime_checkable
class PackageBuilder(Protocol):
    """Normalized and CID-addressed package building."""

    def build_normalized(self, **kwargs: Any) -> Path:
        ...

    def build_cid_package(self, **kwargs: Any) -> Path:
        ...

    def build_all(self, **kwargs: Any) -> Mapping[str, Path]:
        ...


@runtime_checkable
class VectorIndexBuilder(Protocol):
    """Dense vector retrieval index builder."""

    def build(self, **kwargs: Any) -> Path:
        ...


@runtime_checkable
class BM25IndexBuilder(Protocol):
    """Sparse BM25 retrieval index builder."""

    def build(self, **kwargs: Any) -> Path:
        ...


@runtime_checkable
class JsonLdGraphBuilder(Protocol):
    """JSON-LD knowledge graph builder."""

    def build(self, **kwargs: Any) -> Path:
        ...


@runtime_checkable
class HuggingFacePublisher(Protocol):
    """Hugging Face publication and remote verification."""

    def upload(self, targets: Iterable[str] | None = None, **kwargs: Any) -> Sequence[Mapping[str, Any]]:
        ...

    def verify(self, targets: Iterable[str] | None = None, **kwargs: Any) -> Sequence[Mapping[str, Any]]:
        ...


@runtime_checkable
class IntegrityValidator(Protocol):
    """Cross-artifact integrity validation."""

    def validate(self, **kwargs: Any) -> Mapping[str, Any]:
        ...


@runtime_checkable
class LegalCorpusJurisdiction(Protocol):
    """Aggregate interface implemented by each jurisdiction package."""

    spec: JurisdictionSpec
    discovery: DiscoveryProvider
    fetcher: FetchProvider
    parser: Parser
    hierarchy: HierarchyExtractor
    status: StatusClassifier
    cid: CIDGenerator
    packaging: PackageBuilder
    vector: VectorIndexBuilder
    bm25: BM25IndexBuilder
    jsonld: JsonLdGraphBuilder
    publisher: HuggingFacePublisher
    integrity: IntegrityValidator

    def command_groups(self) -> Mapping[str, Any]:
        ...

    def run_cli(self, argv: list[str] | None = None) -> int:
        ...


JurisdictionFactory = Callable[[], LegalCorpusJurisdiction]


__all__ = [
    "BM25IndexBuilder",
    "CIDGenerator",
    "DiscoveryProvider",
    "DiscoveryRecord",
    "FetchProvider",
    "FetchedDocument",
    "HierarchyExtractor",
    "HierarchyNode",
    "HuggingFacePublisher",
    "IndexBuildResult",
    "IntegrityValidator",
    "JsonLdGraphBuilder",
    "JurisdictionFactory",
    "JurisdictionSpec",
    "LawStatus",
    "LegalCorpusJurisdiction",
    "PackageBuildResult",
    "PackageBuilder",
    "ParsedArticleRecord",
    "ParsedLawRecord",
    "Parser",
    "PublicationResult",
    "STATUS_FIELD_NAMES",
    "StatusClassifier",
    "StatusConfidence",
    "StatusMetadata",
    "VectorIndexBuilder",
]
