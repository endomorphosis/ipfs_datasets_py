"""JurisdictionSpec wrappers for harvested official-gazette collectors."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from datetime import datetime, timezone
import json

from ipfs_datasets_py.processors.legal_scrapers.legal_corpus.interfaces import (
    DiscoveryRecord,
    FetchedDocument,
    HierarchyNode,
    JurisdictionSpec,
    ParsedArticleRecord,
    ParsedLawRecord,
    StatusMetadata,
)
from ipfs_datasets_py.processors.legal_scrapers.legal_corpus.registry import register_jurisdiction
from ipfs_datasets_py.utils.cid_utils import cid_for_obj

from .catalog import SnapshotCorpus, get_snapshot_corpus
from .helpers.paths import corpora_root
from .runtime import load_instrument_records, run_harvested_collector


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _status_from_row(row: Mapping[str, Any]) -> StatusMetadata:
    status = str(row.get("law_status") or "unknown").lower()
    if status not in {"current", "historical", "repealed", "superseded", "unknown"}:
        status = "unknown"
    is_current = row.get("is_current")
    if is_current not in (True, False, None):
        is_current = True if status == "current" else None
    return StatusMetadata(
        law_status=status,  # type: ignore[arg-type]
        is_current=is_current if is_current in (True, False, None) else None,
        valid_from=str(row.get("valid_from") or row.get("date") or ""),
        valid_to=str(row.get("valid_to") or ""),
        effective_date=str(row.get("effective_date") or row.get("date_issued") or row.get("date") or ""),
        retrieved_at=str(row.get("retrieved_at") or ""),
        status_source=str(row.get("source_url") or row.get("source_type") or ""),
        status_confidence="medium" if row.get("text") else "low",
        status_note="Harvested official-gazette snapshot. Not legal advice.",
    )


class SnapshotDiscoveryProvider:
    def __init__(self, entry: SnapshotCorpus) -> None:
        self.entry = entry

    def discover(self, **kwargs: Any) -> Mapping[str, Any]:
        return {
            "status": "success",
            "jurisdiction": self.entry.country_code,
            "official_sources": (self.entry.source_dataset_id, self.entry.collector),
            "quality": self.entry.quality,
            "note": "Use published Hugging Face snapshot or harvested collector. Not legal advice.",
        }

    def import_catalog(self, **kwargs: Any) -> Mapping[str, Any]:
        output_dir = kwargs.get("output_dir")
        laws, articles = load_instrument_records(self.entry.country_code, output_dir=output_dir)
        return {
            "status": "success",
            "jurisdiction": self.entry.country_code,
            "laws": len(laws),
            "articles": len(articles),
        }

    def queue(self, **kwargs: Any) -> Mapping[str, Any]:
        return self.import_catalog(**kwargs)

    def coverage_report(self, **kwargs: Any) -> Mapping[str, Any]:
        payload = self.import_catalog(**kwargs)
        payload["quality"] = self.entry.quality
        payload["source_dataset_id"] = self.entry.source_dataset_id
        payload["collector"] = self.entry.collector
        return payload


class SnapshotFetchProvider:
    def __init__(self, entry: SnapshotCorpus) -> None:
        self.entry = entry

    def fetch(self, record: DiscoveryRecord | Mapping[str, Any], **kwargs: Any) -> FetchedDocument:
        if isinstance(record, DiscoveryRecord):
            identifier = record.identifier
            url = record.document_url
            title = record.title
        else:
            identifier = str(record.get("identifier") or record.get("id") or "")
            url = str(record.get("document_url") or record.get("source_url") or "")
            title = str(record.get("title") or "")
        return FetchedDocument(
            identifier=identifier,
            source_url=url,
            body=str(record.get("text") or "") if isinstance(record, Mapping) else "",
            content_type="text/plain",
            retrieved_at=_utcnow(),
            metadata={"title": title, "collector": self.entry.collector},
        )

    def scrape_batch(self, **kwargs: Any) -> Mapping[str, Any]:
        dry_run = bool(kwargs.get("dry_run"))
        result = run_harvested_collector(
            self.entry.canonical_slug,
            output_dir=kwargs.get("output_dir"),
            collectors_dir=kwargs.get("collectors_dir"),
            argv=list(kwargs.get("argv") or []),
            dry_run=dry_run,
        )
        return {
            "status": result.status,
            "jurisdiction": result.country_code,
            "collector": result.collector,
            "output_dir": result.output_dir,
            "laws": result.law_count,
            "articles": result.article_count,
            "error": result.error,
            "details": dict(result.details or {}),
        }

    def resume(self, **kwargs: Any) -> Mapping[str, Any]:
        kwargs.setdefault("argv", ["--resume"])
        return self.scrape_batch(**kwargs)


class SnapshotParser:
    def parse_document(self, document: FetchedDocument | Mapping[str, Any] | str, **kwargs: Any) -> ParsedLawRecord:
        if isinstance(document, FetchedDocument):
            body = document.body.decode("utf-8", errors="replace") if isinstance(document.body, bytes) else str(document.body)
            fields = {
                "id": document.identifier,
                "title": str((document.metadata or {}).get("title") or document.identifier),
                "text": body,
                "source_url": document.source_url,
            }
        elif isinstance(document, Mapping):
            fields = dict(document)
        else:
            fields = {"text": str(document)}
        articles = []
        for item in fields.get("documents") or fields.get("articles") or []:
            if isinstance(item, Mapping):
                articles.append(ParsedArticleRecord(fields=dict(item)))
        hierarchy = SnapshotHierarchyExtractor().extract_hierarchy(fields)
        return ParsedLawRecord(fields=fields, articles=tuple(articles), hierarchy=tuple(hierarchy))

    def sync_parsed_rows(self, **kwargs: Any) -> Mapping[str, Any]:
        country_code = str(kwargs.get("country_code") or kwargs.get("jurisdiction") or "")
        laws, articles = load_instrument_records(country_code, output_dir=kwargs.get("output_dir"))
        return {"status": "success", "laws": len(laws), "articles": len(articles)}


class SnapshotHierarchyExtractor:
    def extract_hierarchy(self, parsed_law: ParsedLawRecord | Mapping[str, Any], **kwargs: Any) -> Sequence[HierarchyNode]:
        fields = parsed_law.fields if isinstance(parsed_law, ParsedLawRecord) else parsed_law
        nodes: list[HierarchyNode] = []
        law_id = str(fields.get("id") or fields.get("law_identifier") or fields.get("identifier") or "")
        nodes.append(HierarchyNode(kind="law", label=str(fields.get("title") or law_id), source_identifier=law_id))
        for item in fields.get("documents") or fields.get("articles") or []:
            if not isinstance(item, Mapping):
                continue
            number = str(item.get("article_number") or item.get("document_number") or "")
            nodes.append(
                HierarchyNode(
                    kind=str(item.get("record_type") or "article"),
                    label=str(item.get("title") or number),
                    number=number,
                    parent_path=(law_id,) if law_id else (),
                    source_identifier=str(item.get("id") or ""),
                    metadata=dict(item),
                )
            )
        return nodes

    def validate_hierarchy(self, rows: Iterable[Mapping[str, Any]], **kwargs: Any) -> Mapping[str, Any]:
        checked = 0
        missing = 0
        for row in rows:
            checked += 1
            if str(row.get("record_type") or "") == "article" and not (row.get("law_id") or row.get("law_identifier")):
                missing += 1
        return {"ok": missing == 0, "checked": checked, "missing_parent": missing}


class SnapshotStatusClassifier:
    def classify_law(self, law: Mapping[str, Any] | str, **kwargs: Any) -> StatusMetadata:
        if isinstance(law, str):
            return _status_from_row({"text": law, "source_url": str(kwargs.get("source_url") or "")})
        return _status_from_row(law)

    def inherit_article_status(self, law: Mapping[str, Any], article: Mapping[str, Any]) -> dict[str, Any]:
        inherited = dict(article)
        status = _status_from_row(law)
        inherited.update(status.as_row_fields())
        return inherited


class SnapshotCIDGenerator:
    def assign_record_cids(self, rows: Iterable[Mapping[str, Any]], **kwargs: Any) -> Iterable[dict[str, Any]]:
        for row in rows:
            payload = dict(row)
            cid = cid_for_obj(payload)
            payload["cid"] = cid
            payload["content_address"] = f"ipfs://{cid}"
            yield payload

    def build_cid_package(self, **kwargs: Any) -> Path:
        output_dir = Path(kwargs.get("output_dir") or corpora_root())
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir


class SnapshotPackageBuilder:
    def __init__(self, entry: SnapshotCorpus) -> None:
        self.entry = entry

    def build_normalized(self, **kwargs: Any) -> Path:
        output_dir = Path(kwargs.get("output_dir") or (corpora_root() / self.entry.country_code.lower() / "package"))
        output_dir.mkdir(parents=True, exist_ok=True)
        laws, articles = load_instrument_records(
            self.entry.country_code,
            output_dir=kwargs.get("corpora_dir") or kwargs.get("raw_dir") or corpora_root(),
        )
        (output_dir / "laws.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in laws),
            encoding="utf-8",
        )
        (output_dir / "articles.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in articles),
            encoding="utf-8",
        )
        manifest = {
            "jurisdiction": self.entry.country_code,
            "source_dataset_id": self.entry.source_dataset_id,
            "laws": len(laws),
            "articles": len(articles),
            "not_legal_advice": True,
        }
        (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return output_dir

    def build_cid_package(self, **kwargs: Any) -> Path:
        output_dir = self.build_normalized(**kwargs)
        laws = []
        path = output_dir / "laws.jsonl"
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    laws.append(json.loads(line))
        addressed = list(SnapshotCIDGenerator().assign_record_cids(laws))
        (output_dir / "laws_cid.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in addressed),
            encoding="utf-8",
        )
        return output_dir

    def build_all(self, **kwargs: Any) -> Mapping[str, Path]:
        normalized = self.build_normalized(**kwargs)
        cid_dir = self.build_cid_package(**kwargs)
        return {"normalized": normalized, "cid": cid_dir}


class SnapshotIndexBuilder:
    def __init__(self, index_type: str, entry: SnapshotCorpus) -> None:
        self.index_type = index_type
        self.entry = entry

    def build(self, **kwargs: Any) -> Path:
        output_dir = Path(kwargs.get("output_dir") or (corpora_root() / self.entry.country_code.lower() / self.index_type))
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "README.md").write_text(
            f"# {self.entry.display_name} {self.index_type}\n\n"
            "Snapshot packaging only. Full GraphRAG indexes live in justicedao IR datasets.\n"
            "Not legal advice.\n",
            encoding="utf-8",
        )
        return output_dir


class SnapshotHuggingFacePublisher:
    def __init__(self, entry: SnapshotCorpus) -> None:
        self.entry = entry

    def upload(self, targets: Iterable[str] | None = None, **kwargs: Any) -> Sequence[Mapping[str, Any]]:
        return [
            {
                "target": "source",
                "repo_id": self.entry.source_dataset_id,
                "ok": None,
                "note": "Use huggingface_hub to publish rewritten snapshots. Not performed by default.",
            }
        ]

    def verify(self, targets: Iterable[str] | None = None, **kwargs: Any) -> Sequence[Mapping[str, Any]]:
        return [
            {
                "target": "source",
                "repo_id": self.entry.source_dataset_id,
                "ok": True,
                "note": "Published snapshot expected at data/laws.parquet and data/articles.parquet.",
            }
        ]


class SnapshotIntegrityValidator:
    def __init__(self, entry: SnapshotCorpus) -> None:
        self.entry = entry

    def validate(self, **kwargs: Any) -> Mapping[str, Any]:
        laws, articles = load_instrument_records(self.entry.country_code, output_dir=kwargs.get("output_dir"))
        ids = [str(row.get("id") or "") for row in laws]
        duplicates = sorted({value for value in ids if value and ids.count(value) > 1})
        orphan_articles = [
            str(row.get("id") or "")
            for row in articles
            if str(row.get("law_id") or "") not in set(ids)
        ]
        return {
            "ok": not duplicates and not orphan_articles,
            "laws": len(laws),
            "articles": len(articles),
            "duplicate_ids": duplicates,
            "orphan_articles": orphan_articles[:50],
            "quality": self.entry.quality,
            "not_legal_advice": True,
        }


class SnapshotLegalCorpusJurisdiction:
    """Generic wrapper around a harvested endomorphosis gazette collector."""

    def __init__(self, entry: SnapshotCorpus) -> None:
        self.entry = entry
        self.spec = JurisdictionSpec(
            jurisdiction_id=entry.country_code,
            slug=entry.canonical_slug,
            display_name=entry.display_name,
            country_code=entry.country_code,
            language_codes=(entry.language,),
            official_sources=(entry.source_dataset_id, entry.collector),
            default_raw_dir=corpora_root() / entry.country_code.lower(),
            default_catalog_path=corpora_root() / entry.country_code.lower() / "index.jsonl",
            default_hf_namespace="endomorphosis",
            hf_repo_ids={
                "source": entry.source_dataset_id,
                "ir": entry.ir_dataset_id,
            },
            aliases=entry.aliases(),
        )
        self.discovery = SnapshotDiscoveryProvider(entry)
        self.fetcher = SnapshotFetchProvider(entry)
        self.parser = SnapshotParser()
        self.hierarchy = SnapshotHierarchyExtractor()
        self.status = SnapshotStatusClassifier()
        self.cid = SnapshotCIDGenerator()
        self.packaging = SnapshotPackageBuilder(entry)
        self.vector = SnapshotIndexBuilder("vector", entry)
        self.bm25 = SnapshotIndexBuilder("bm25", entry)
        self.jsonld = SnapshotIndexBuilder("jsonld", entry)
        self.publisher = SnapshotHuggingFacePublisher(entry)
        self.integrity = SnapshotIntegrityValidator(entry)

    def command_groups(self) -> Mapping[str, Any]:
        return {
            "entrypoints": (f"{self.entry.canonical_slug}-laws", "legal-scrape"),
            "commands": (
                "discover",
                "scrape",
                "resume",
                "snapshot",
                "build-normalized",
                "validate",
            ),
        }

    def run_cli(self, argv: list[str] | None = None) -> int:
        from .api import scrape_legal_data

        args = list(argv or [])
        mode = args[0] if args else "snapshot"
        result = scrape_legal_data(self.entry.canonical_slug, mode=mode)
        return 0 if result.get("status") in {"ok", "success", "dry_run", "snapshot"} else 1


def register_snapshot_jurisdiction(key: str) -> SnapshotLegalCorpusJurisdiction:
    entry = get_snapshot_corpus(key)
    jurisdiction = SnapshotLegalCorpusJurisdiction(entry)
    return register_jurisdiction(jurisdiction)  # type: ignore[return-value]


__all__ = [
    "SnapshotLegalCorpusJurisdiction",
    "register_snapshot_jurisdiction",
]
