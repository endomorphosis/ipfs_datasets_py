"""Agentic scrape optimization utilities for web archiving.

This module bridges web scraping output with extraction methods used in the
`ipfs_datasets_py.optimizers` library to produce cleaner, structured results.

Key capabilities:
- Boilerplate/metadata cleanup from scraped content
- Domain-aware entity extraction using optimizer regex compiler
- Streaming extraction for very large documents
- PDF text extraction fallback for document-style targets
- Candidate link ranking for agentic discovery loops
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence


@dataclass
class AgenticExtractionConfig:
    """Configuration for optimizer-backed scrape transformation."""

    domain: str = "general"
    confidence_threshold: float = 0.5
    min_entity_length: int = 2
    max_confidence: float = 1.0
    custom_rules: List[tuple[str, str]] = field(default_factory=list)
    stopwords: List[str] = field(default_factory=lambda: [
        "cookie",
        "privacy",
        "terms",
        "menu",
        "navigation",
    ])
    allowed_entity_types: List[str] = field(default_factory=list)
    streaming_threshold_chars: int = 12000
    streaming_chunk_size: int = 1500
    streaming_overlap: int = 250


@dataclass
class ParsedScrapeResult:
    """Structured parsed output generated from a raw scrape payload."""

    url: str
    title: str
    cleaned_text: str
    entities: List[Dict[str, Any]] = field(default_factory=list)
    structured_fields: Dict[str, Any] = field(default_factory=dict)
    source_type: str = "html"
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgenticScrapeOptimizer:
    """Optimizer-backed transformation pipeline for scraped web content."""

    _BOILERPLATE_PATTERNS = [
        re.compile(r"\b(cookie|privacy policy|terms of use|all rights reserved)\b", re.IGNORECASE),
        re.compile(r"\b(sign in|sign up|subscribe|newsletter)\b", re.IGNORECASE),
        re.compile(r"\b(skip to content|back to top|menu|navigation)\b", re.IGNORECASE),
    ]
    _DATE_PATTERNS = [
        re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),
        re.compile(
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b",
            re.IGNORECASE,
        ),
    ]
    _LEGAL_CITATION_PATTERNS = [
        re.compile(r"\b\d+\s+U\.S\.C\.\s+§?\s*\d+[\w\-\.]*\b", re.IGNORECASE),
        re.compile(r"\b(?:Section|Sec\.)\s+\d+[\w\-\.]*\b", re.IGNORECASE),
        re.compile(r"\b(?:Article|Title)\s+\d+[\w\-\.]*\b", re.IGNORECASE),
    ]
    _STATUTE_ID_PATTERNS = [
        re.compile(r"\b\d{1,3}-\d{1,3}-\d{1,4}\b"),
        re.compile(r"\b\d+\.\d+[\w\-]*\b"),
    ]
    _MONEY_PATTERNS = [
        re.compile(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b"),
        re.compile(r"\b(?:USD|EUR|GBP)\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b", re.IGNORECASE),
    ]

    def __init__(self, config: Optional[AgenticExtractionConfig] = None):
        self.config = config or AgenticExtractionConfig()

    def transform(
        self,
        *,
        url: str,
        title: str = "",
        text: str = "",
        html: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ParsedScrapeResult:
        """Transform raw scrape payload into cleaned + parsed content."""
        meta = dict(metadata or {})
        source_type = self._detect_source_type(url=url, metadata=meta)

        if source_type == "pdf":
            pdf_bytes = meta.get("raw_bytes")
            if isinstance(pdf_bytes, (bytes, bytearray)):
                text = self.extract_pdf_text(bytes(pdf_bytes)) or text

        candidate_text = text or self._strip_html_to_text(html)
        cleaned_text = self.clean_text(candidate_text)
        entities = self.extract_entities(cleaned_text)
        structured_fields = self.parse_structured_fields(cleaned_text, source_type=source_type)

        return ParsedScrapeResult(
            url=url,
            title=title,
            cleaned_text=cleaned_text,
            entities=entities,
            structured_fields=structured_fields,
            source_type=source_type,
            metadata={
                **meta,
                "entity_count": len(entities),
                "cleaned_chars": len(cleaned_text),
            },
        )

    def clean_text(self, text: str) -> str:
        """Clean formatting noise and boilerplate from scraped text."""
        if not text:
            return ""

        cleaned = text.replace("\r", "\n")
        cleaned = re.sub(r"\u00a0", " ", cleaned)
        cleaned = re.sub(r"[\t\f\v]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r" {2,}", " ", cleaned)

        lines: List[str] = []
        for line in cleaned.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if any(pattern.search(stripped) for pattern in self._BOILERPLATE_PATTERNS):
                continue
            lines.append(stripped)

        return "\n".join(lines)

    def extract_entities(self, text: str) -> List[Dict[str, Any]]:
        """Extract domain-aware entities using optimizer extraction methods."""
        if not text:
            return []

        # Lazy imports keep module lightweight for environments not using this feature.
        from ipfs_datasets_py.optimizers.common.extraction_contexts import BaseExtractionConfig
        from ipfs_datasets_py.optimizers.graphrag.regex_pattern_compiler import RegexPatternCompiler
        from ipfs_datasets_py.optimizers.graphrag.streaming_extractor import (
            ChunkStrategy,
            StreamingEntityExtractor,
        )

        cfg = BaseExtractionConfig(
            confidence_threshold=self.config.confidence_threshold,
            domain=self.config.domain,
            custom_rules=list(self.config.custom_rules),
            min_entity_length=self.config.min_entity_length,
            stopwords=list(self.config.stopwords),
            allowed_entity_types=list(self.config.allowed_entity_types),
            max_confidence=self.config.max_confidence,
        )

        compiler = RegexPatternCompiler()
        patterns = compiler.build_precompiled_patterns(
            domain=cfg.domain,
            custom_rules=cfg.custom_rules,
        )

        allowed = set(cfg.allowed_entity_types)
        stopwords = set(cfg.stopwords)

        if len(text) >= self.config.streaming_threshold_chars:
            extractor = StreamingEntityExtractor(
                extractor_func=lambda chunk: compiler.extract_entities_with_precompiled(
                    chunk,
                    patterns,
                    allowed_types=allowed,
                    min_len=cfg.min_entity_length,
                    stopwords=stopwords,
                    max_confidence=cfg.max_confidence,
                ),
                chunk_size=self.config.streaming_chunk_size,
                overlap=self.config.streaming_overlap,
                chunk_strategy=ChunkStrategy.ADAPTIVE,
                batch_size=100,
            )
            entities: List[Dict[str, Any]] = []
            for batch in extractor.extract_stream(text):
                entities.extend(
                    {
                        "id": ent.entity_id,
                        "type": ent.entity_type,
                        "text": ent.text,
                        "confidence": ent.confidence,
                        "span": (ent.start_pos, ent.end_pos),
                        "metadata": ent.metadata,
                    }
                    for ent in batch.entities
                )
            return self._dedupe_entities(entities)

        entities = compiler.extract_entities_with_precompiled(
            text,
            patterns,
            allowed_types=allowed,
            min_len=cfg.min_entity_length,
            stopwords=stopwords,
            max_confidence=cfg.max_confidence,
        )
        return self._dedupe_entities(entities)

    def extract_pdf_text(self, pdf_bytes: bytes) -> str:
        """Extract text from PDF bytes.

        Uses `pypdf` when available and returns empty string on parse failure.
        """
        if not pdf_bytes:
            return ""

        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(BytesIO(pdf_bytes))
            pages = [page.extract_text() or "" for page in reader.pages]
            return self.clean_text("\n".join(pages))
        except Exception:
            return ""

    def rank_links(self, links: Iterable[Dict[str, Any]], target_terms: Sequence[str]) -> List[Dict[str, Any]]:
        """Rank candidate links for agentic follow-up based on target terms."""
        terms = [term.lower() for term in target_terms if term]
        scored: List[Dict[str, Any]] = []

        for link in links:
            url = str(link.get("url") or "")
            text = str(link.get("text") or "")
            haystack = f"{url} {text}".lower()
            score = sum(1 for term in terms if term in haystack)
            if ".pdf" in haystack:
                score += 1
            payload = dict(link)
            payload["score"] = score
            scored.append(payload)

        scored.sort(key=lambda item: float(item.get("score", 0)), reverse=True)
        return scored

    def parse_structured_fields(self, text: str, *, source_type: str = "html") -> Dict[str, Any]:
        """Extract higher-level structured fields from cleaned text."""
        if not text:
            return {
                "section_headers": [],
                "dates": [],
                "legal_citations": [],
                "statute_identifiers": [],
                "monetary_amounts": [],
                "is_pdf_content": source_type == "pdf",
            }

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        section_headers = []
        for line in lines:
            if len(line) > 120:
                continue
            if re.match(r"^(?:SECTION|ARTICLE|TITLE|CHAPTER)\b", line, re.IGNORECASE):
                section_headers.append(line)
                continue
            if re.match(r"^\d+(?:\.\d+)*\s+[A-Z]", line):
                section_headers.append(line)
                continue
            if line.isupper() and len(line.split()) <= 12:
                section_headers.append(line)

        dates = self._collect_pattern_matches(text, self._DATE_PATTERNS)
        legal_citations = self._collect_pattern_matches(text, self._LEGAL_CITATION_PATTERNS)
        statute_ids = self._collect_pattern_matches(text, self._STATUTE_ID_PATTERNS)
        monetary_amounts = self._collect_pattern_matches(text, self._MONEY_PATTERNS)

        return {
            "section_headers": section_headers[:50],
            "dates": dates[:100],
            "legal_citations": legal_citations[:200],
            "statute_identifiers": statute_ids[:200],
            "monetary_amounts": monetary_amounts[:100],
            "is_pdf_content": source_type == "pdf",
        }

    @staticmethod
    def _strip_html_to_text(html: str) -> str:
        if not html:
            return ""
        # Lightweight fallback that avoids mandatory parser dependencies.
        text = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _detect_source_type(url: str, metadata: Dict[str, Any]) -> str:
        content_type = str(metadata.get("content_type") or metadata.get("http_mime") or "").lower()
        if "pdf" in content_type or url.lower().endswith(".pdf"):
            return "pdf"
        return "html"

    @staticmethod
    def _dedupe_entities(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        out: List[Dict[str, Any]] = []
        for ent in entities:
            key = (str(ent.get("type") or ""), str(ent.get("text") or "").lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(ent)
        return out

    @staticmethod
    def _collect_pattern_matches(text: str, patterns: Sequence[re.Pattern[str]]) -> List[str]:
        seen = set()
        out: List[str] = []
        for pattern in patterns:
            for match in pattern.findall(text):
                value = str(match).strip()
                key = value.lower()
                if not value or key in seen:
                    continue
                seen.add(key)
                out.append(value)
        return out


__all__ = [
    "AgenticExtractionConfig",
    "ParsedScrapeResult",
    "AgenticScrapeOptimizer",
]
