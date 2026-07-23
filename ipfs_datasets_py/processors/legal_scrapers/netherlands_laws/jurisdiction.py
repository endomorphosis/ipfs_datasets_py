"""Netherlands implementation of the reusable legal corpus interfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.legal_scrapers.legal_corpus import (
    DiscoveryRecord,
    FetchedDocument,
    HierarchyNode,
    JurisdictionSpec,
    ParsedArticleRecord,
    ParsedLawRecord,
    StatusMetadata,
    register_jurisdiction,
)
from ipfs_datasets_py.processors.legal_scrapers.legal_corpus.interfaces import STATUS_FIELD_NAMES
from ipfs_datasets_py.utils.cid_utils import cid_for_obj

from .paths import (
    DEFAULT_BWBR_CATALOG_PATH,
    DEFAULT_HF_NAMESPACE,
    DEFAULT_HF_REPO_IDS,
    PACKAGE_RAW_OUTPUT_DIR,
)


def _status_metadata_from_row(row: Mapping[str, Any]) -> StatusMetadata:
    status = str(row.get("law_status") or "unknown").lower()
    if status not in {"current", "historical", "repealed", "superseded", "unknown"}:
        status = "unknown"
    confidence = str(row.get("status_confidence") or "unknown").lower()
    if confidence not in {"high", "medium", "low", "unknown"}:
        confidence = "unknown"
    return StatusMetadata(
        law_status=status,  # type: ignore[arg-type]
        is_current=row.get("is_current") if row.get("is_current") in (True, False, None) else None,
        valid_from=str(row.get("valid_from") or ""),
        valid_to=str(row.get("valid_to") or ""),
        effective_date=str(row.get("effective_date") or ""),
        retrieved_at=str(row.get("retrieved_at") or ""),
        status_source=str(row.get("status_source") or ""),
        status_confidence=confidence,  # type: ignore[arg-type]
        status_note=str(row.get("status_note") or ""),
        version_start_date=str(row.get("version_start_date") or ""),
        version_end_date=str(row.get("version_end_date") or ""),
    )


class NetherlandsDiscoveryProvider:
    """Official BWBR discovery catalog adapter."""

    def discover(self, **kwargs: Any) -> Mapping[str, Any]:
        return {
            "status": "success",
            "jurisdiction": "NL",
            "official_sources": (
                "Official BWB SRU service at zoekservice.overheid.nl",
                "wetten.overheid.nl law document pages",
                "wetten.overheid.nl /informatie metadata pages",
            ),
            "note": "Use import_catalog for persisted official SRU discovery output.",
        }

    def import_catalog(self, **kwargs: Any) -> Mapping[str, Any]:
        from . import operations

        discovery_jsonl_path = kwargs.pop("discovery_jsonl_path", kwargs.pop("discovery_jsonl", None))
        if discovery_jsonl_path is None:
            raise ValueError("Netherlands discovery import requires discovery_jsonl_path.")
        return operations.import_discovery_catalog(discovery_jsonl_path=Path(discovery_jsonl_path), **kwargs)

    def queue(self, **kwargs: Any) -> Mapping[str, Any]:
        from . import operations

        return operations.queue_identifiers(**kwargs)

    def coverage_report(self, **kwargs: Any) -> Mapping[str, Any]:
        from . import operations

        return operations.coverage_report(**kwargs)


class NetherlandsFetchProvider:
    """Official wetten.overheid.nl fetching adapter."""

    async def fetch(self, record: DiscoveryRecord | Mapping[str, Any], **kwargs: Any) -> Mapping[str, Any]:
        from .api import scrape

        document_url = record.document_url if isinstance(record, DiscoveryRecord) else str(record.get("document_url") or record.get("source_url") or "")
        if not document_url:
            raise ValueError("Netherlands fetch requires a document_url or source_url.")
        output_dir = Path(kwargs.pop("output_dir", PACKAGE_RAW_OUTPUT_DIR))
        return await scrape(
            output_dir=output_dir,
            document_urls=[document_url],
            seed_urls=[],
            use_default_seeds=False,
            max_documents=None,
            max_seed_pages=0,
            crawl_depth=0,
            resume=bool(kwargs.pop("resume", True)),
            skip_existing=bool(kwargs.pop("skip_existing", True)),
            **kwargs,
        )

    async def scrape_batch(self, **kwargs: Any) -> Mapping[str, Any]:
        from . import operations

        return await operations.scrape_queued_batch(**kwargs)

    async def resume(self, **kwargs: Any) -> Mapping[str, Any]:
        from . import operations

        reset = operations.reset_interrupted_downloads(
            catalog_path=kwargs.get("catalog_path"),
            stale_after_minutes=kwargs.get("stale_after_minutes", 120),
        )
        scrape_result = await operations.scrape_queued_batch(**kwargs)
        return {"reset": reset, "scrape": scrape_result}


class NetherlandsParser:
    """Parser adapter for Netherlands law documents."""

    def parse_document(self, document: FetchedDocument | Mapping[str, Any] | str, **kwargs: Any) -> ParsedLawRecord:
        from ipfs_datasets_py.processors.legal_scrapers import netherlands_laws_scraper as scraper

        if isinstance(document, FetchedDocument):
            html = document.body.decode("utf-8", errors="replace") if isinstance(document.body, bytes) else str(document.body)
        elif isinstance(document, Mapping):
            body = document.get("body") or document.get("html") or document.get("text") or ""
            html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
        else:
            html = str(document)
        parsed = scraper._extract_title_and_text(html)
        fields = {
            "title": parsed.get("title"),
            "text": parsed.get("text"),
            "articles": parsed.get("structure", {}).get("articles", []),
            "chapters": parsed.get("structure", {}).get("chapters", []),
            "parts": parsed.get("structure", {}).get("parts", []),
        }
        hierarchy = NetherlandsHierarchyExtractor().extract_hierarchy(fields)
        articles = tuple(ParsedArticleRecord(fields=article) for article in fields["articles"])
        return ParsedLawRecord(fields=fields, articles=articles, hierarchy=tuple(hierarchy))

    def sync_parsed_rows(self, **kwargs: Any) -> Mapping[str, Any]:
        from . import operations

        return operations.sync_catalog_from_raw(**kwargs)


class NetherlandsHierarchyExtractor:
    """Hierarchy adapter for BWBR law rows."""

    def extract_hierarchy(self, parsed_law: ParsedLawRecord | Mapping[str, Any], **kwargs: Any) -> Sequence[HierarchyNode]:
        fields = parsed_law.fields if isinstance(parsed_law, ParsedLawRecord) else parsed_law
        nodes: list[HierarchyNode] = []
        for part in fields.get("parts") or fields.get("chapters") or []:
            if not isinstance(part, Mapping):
                continue
            path = tuple(
                str(item.get("label") or "")
                for item in part.get("hierarchy_path", [])
                if isinstance(item, Mapping) and item.get("label")
            )
            nodes.append(
                HierarchyNode(
                    kind=str(part.get("kind") or ""),
                    label=str(part.get("label") or ""),
                    number=str(part.get("number") or ""),
                    parent_path=path,
                    source_identifier=str(fields.get("law_identifier") or fields.get("identifier") or ""),
                    metadata=dict(part),
                )
            )
        return nodes

    def validate_hierarchy(self, rows: Iterable[Mapping[str, Any]], **kwargs: Any) -> Mapping[str, Any]:
        checked = 0
        missing_article_paths: list[str] = []
        for row in rows:
            checked += 1
            if str(row.get("record_type") or "") == "article" and not row.get("hierarchy_path"):
                missing_article_paths.append(str(row.get("article_identifier") or row.get("citation") or ""))
        return {"ok": not missing_article_paths, "checked": checked, "missing_article_paths": missing_article_paths}


class NetherlandsStatusClassifier:
    """Official metadata status classifier adapter."""

    def classify_law(self, law: Mapping[str, Any] | str, **kwargs: Any) -> StatusMetadata:
        from ipfs_datasets_py.processors.legal_scrapers import netherlands_laws_scraper as scraper

        if isinstance(law, str):
            return _status_metadata_from_row(scraper._extract_status_metadata(law, source_url=str(kwargs.get("source_url") or "")))
        return _status_metadata_from_row(scraper._ensure_status_fields(dict(law)))

    def inherit_article_status(self, law: Mapping[str, Any], article: Mapping[str, Any]) -> dict[str, Any]:
        inherited = dict(article)
        for field in STATUS_FIELD_NAMES:
            if field in law:
                inherited[field] = law.get(field)
        return inherited


class NetherlandsCIDGenerator:
    """CID generation adapter for Netherlands package rows."""

    def assign_record_cids(self, rows: Iterable[Mapping[str, Any]], **kwargs: Any) -> Iterable[dict[str, Any]]:
        for row in rows:
            payload = dict(row)
            cid = cid_for_obj(payload)
            payload["cid"] = cid
            payload["content_address"] = f"ipfs://{cid}"
            yield payload

    def build_cid_package(self, **kwargs: Any) -> Path:
        from .builders.ipfs_package import build_ipfs_cid_package

        return build_ipfs_cid_package(**kwargs)


class NetherlandsPackageBuilder:
    """Normalized and CID package builder adapter."""

    def build_normalized(self, **kwargs: Any) -> Path:
        from .builders.normalized_package import build_normalized_package

        return build_normalized_package(**kwargs)

    def build_cid_package(self, **kwargs: Any) -> Path:
        from .builders.ipfs_package import build_ipfs_cid_package

        return build_ipfs_cid_package(**kwargs)

    def build_all(self, **kwargs: Any) -> Mapping[str, Path]:
        from .api import build_package_set

        raw_dir = kwargs.pop("raw_dir", None)
        return build_package_set(raw_dir=raw_dir)


class NetherlandsVectorIndexBuilder:
    def build(self, **kwargs: Any) -> Path:
        from .builders.ipfs_indexes import build_vector_index

        return build_vector_index(**kwargs)


class NetherlandsBM25IndexBuilder:
    def build(self, **kwargs: Any) -> Path:
        from .builders.ipfs_indexes import build_bm25_index

        return build_bm25_index(**kwargs)


class NetherlandsJsonLdGraphBuilder:
    def build(self, **kwargs: Any) -> Path:
        from .builders.ipfs_indexes import build_knowledge_graph

        return build_knowledge_graph(**kwargs)


class NetherlandsHuggingFacePublisher:
    def upload(self, targets: Iterable[str] | None = None, **kwargs: Any) -> Sequence[Mapping[str, Any]]:
        from .upload import upload_datasets

        return upload_datasets(targets, **kwargs)

    def verify(self, targets: Iterable[str] | None = None, **kwargs: Any) -> Sequence[Mapping[str, Any]]:
        from .upload import verify_remote_datasets

        return verify_remote_datasets(targets, **kwargs)


class NetherlandsIntegrityValidator:
    def validate(self, **kwargs: Any) -> Mapping[str, Any]:
        from . import operations

        return operations.validate_integrity(**kwargs)


class NetherlandsLegalCorpusJurisdiction:
    """Aggregate Netherlands jurisdiction implementation."""

    def __init__(self) -> None:
        self.spec = JurisdictionSpec(
            jurisdiction_id="NL",
            slug="netherlands",
            display_name="Netherlands",
            country_code="NL",
            language_codes=("nl",),
            official_sources=(
                "Official BWB SRU service at zoekservice.overheid.nl",
                "wetten.overheid.nl law document pages",
                "wetten.overheid.nl /informatie metadata pages",
            ),
            default_raw_dir=PACKAGE_RAW_OUTPUT_DIR,
            default_catalog_path=DEFAULT_BWBR_CATALOG_PATH,
            default_hf_namespace=DEFAULT_HF_NAMESPACE,
            hf_repo_ids=DEFAULT_HF_REPO_IDS,
            aliases=("netherlands_laws", "dutch_laws", "bwbr"),
        )
        self.discovery = NetherlandsDiscoveryProvider()
        self.fetcher = NetherlandsFetchProvider()
        self.parser = NetherlandsParser()
        self.hierarchy = NetherlandsHierarchyExtractor()
        self.status = NetherlandsStatusClassifier()
        self.cid = NetherlandsCIDGenerator()
        self.packaging = NetherlandsPackageBuilder()
        self.vector = NetherlandsVectorIndexBuilder()
        self.bm25 = NetherlandsBM25IndexBuilder()
        self.jsonld = NetherlandsJsonLdGraphBuilder()
        self.publisher = NetherlandsHuggingFacePublisher()
        self.integrity = NetherlandsIntegrityValidator()

    def command_groups(self) -> Mapping[str, Any]:
        return {
            "entrypoints": ("netherlands-laws", "ipfs-netherlands-laws"),
            "commands": (
                "discover",
                "queue",
                "scrape",
                "retry-failures",
                "resume",
                "sync-raw",
                "build-normalized",
                "build-ipfs-package",
                "build-vector-index",
                "build-bm25-index",
                "build-knowledge-graph",
                "build-indexes",
                "rebuild-indexes",
                "rebuild-huggingface",
                "build-unified",
                "validate-unified",
                "upload",
                "verify-remote",
                "verify",
                "coverage-report",
                "quality-audit",
            ),
        }

    def run_cli(self, argv: list[str] | None = None) -> int:
        from .cli import main

        return main(argv)


_NETHERLANDS_JURISDICTION = NetherlandsLegalCorpusJurisdiction()


def get_jurisdiction() -> NetherlandsLegalCorpusJurisdiction:
    return _NETHERLANDS_JURISDICTION


def register_netherlands_jurisdiction() -> NetherlandsLegalCorpusJurisdiction:
    return register_jurisdiction(_NETHERLANDS_JURISDICTION)


register_netherlands_jurisdiction()


__all__ = [
    "NetherlandsBM25IndexBuilder",
    "NetherlandsCIDGenerator",
    "NetherlandsDiscoveryProvider",
    "NetherlandsFetchProvider",
    "NetherlandsHierarchyExtractor",
    "NetherlandsHuggingFacePublisher",
    "NetherlandsIntegrityValidator",
    "NetherlandsJsonLdGraphBuilder",
    "NetherlandsLegalCorpusJurisdiction",
    "NetherlandsPackageBuilder",
    "NetherlandsParser",
    "NetherlandsStatusClassifier",
    "NetherlandsVectorIndexBuilder",
    "get_jurisdiction",
    "register_netherlands_jurisdiction",
]
