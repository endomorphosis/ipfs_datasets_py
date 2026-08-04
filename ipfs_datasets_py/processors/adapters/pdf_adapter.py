"""
PDFProcessorAdapter - Adapter for PDF processing.

Wraps the consolidated PDF processor (processors.specialized.pdf)
to implement ProcessorProtocol. Delegates to the real multi-stage
PDF pipeline (decompose → OCR → text-layer merge with provenance)
and converts results into the canonical ProcessingResult contract.

Updated: 2026-08-03 - PATLAW-007: real pipeline, no placeholder output
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional, Union

from ..protocol import (
    Entity,
    InputType,
    KnowledgeGraph,
    ProcessingMetadata,
    ProcessingResult,
    ProcessingStatus,
    Relationship,
    VectorStore,
)

logger = logging.getLogger(__name__)

# Forbidden synthetic placeholders that must never appear as extracted text.
_PLACEHOLDER_PREFIXES = (
    "PDF content from ",
    "placeholder",
    "TODO: extract",
    "NotImplemented",
)

# OCR / merge statuses that mean extraction completed with gaps (PARTIAL).
_PARTIAL_OCR_STATUSES = frozenset(
    {
        "ocr_unavailable",
        "low_confidence",
        "ocr_failed",
        "empty",
        "partial",
    }
)


class PDFProcessorAdapter:
    """
    Adapter for PDF processors that implements ProcessorProtocol.

    Delegates to ``PDFProcessor.process_pdf`` (specialized pipeline) and
    maps page text, span provenance, coverage receipts, warnings, and
    error/partial status into the canonical runtime contract.

    Privacy: ordinary logs and error paths carry path/type identifiers only —
    never document body, OCR text, or full content dumps.

    Example:
        >>> adapter = PDFProcessorAdapter()
        >>> can_process = await adapter.can_process("document.pdf")
        >>> result = await adapter.process("document.pdf")
    """

    def __init__(
        self,
        processor: Any = None,
        *,
        enable_monitoring: bool = False,
        enable_audit: bool = False,
        processor_kwargs: Optional[dict[str, Any]] = None,
    ):
        """
        Initialize adapter.

        Args:
            processor: Optional pre-built PDFProcessor (or compatible) for
                dependency injection in tests. When None, lazy-loads the
                specialized PDFProcessor on first use.
            enable_monitoring: Forwarded when constructing the default processor.
            enable_audit: Forwarded when constructing the default processor.
                Default False so confidential body text is not pushed into
                audit sinks that may log resource details aggressively.
            processor_kwargs: Extra kwargs for PDFProcessor construction.
        """
        self._processor = processor
        self._enable_monitoring = enable_monitoring
        self._enable_audit = enable_audit
        self._processor_kwargs = dict(processor_kwargs or {})

    def _get_processor(self):
        """Lazy-load PDF processor on first use."""
        if self._processor is None:
            try:
                from ..specialized.pdf import PDFProcessor

                if PDFProcessor is None:
                    raise ImportError("PDFProcessor is unavailable")
                kwargs = {
                    "enable_monitoring": self._enable_monitoring,
                    "enable_audit": self._enable_audit,
                    **self._processor_kwargs,
                }
                self._processor = PDFProcessor(**kwargs)
                logger.info(
                    "PDFProcessor loaded from specialized.pdf (pipeline v%s)",
                    getattr(self._processor, "pipeline_version", "unknown"),
                )
            except ImportError as e:
                logger.warning(
                    "Could not load PDFProcessor from specialized.pdf: %s",
                    type(e).__name__,
                )
                try:
                    from ..pdf_processor import PDFProcessor as LegacyPDFProcessor

                    self._processor = LegacyPDFProcessor()
                    logger.warning(
                        "Loaded PDFProcessor from deprecated location"
                    )
                except ImportError as e2:
                    logger.error(
                        "No PDF processor available: %s",
                        type(e2).__name__,
                    )
                    raise RuntimeError("No PDF processor available") from e2
        return self._processor

    async def can_process(self, input_source: Union[str, Path]) -> bool:
        """
        Check if this adapter can handle PDF inputs.

        Args:
            input_source: Input to check

        Returns:
            True if input is a PDF file or URL pointing to PDF
        """
        input_str = str(input_source).lower()

        if input_str.endswith(".pdf"):
            return True

        if input_str.startswith(("http://", "https://")) and ".pdf" in input_str:
            return True

        path = Path(input_source)
        if path.exists() and path.is_file() and path.suffix.lower() == ".pdf":
            return True

        return False

    async def process(
        self,
        input_source: Union[str, Path],
        **options,
    ) -> ProcessingResult:
        """
        Process PDF via the real specialized pipeline and return a
        standardized ProcessingResult.

        Args:
            input_source: PDF file path or URL
            **options: Processing options. Recognized keys:
                - metadata: dict merged into pipeline processing metadata
                - Any other keys are forwarded as pipeline metadata if no
                  explicit ``metadata`` is provided (string keys only)

        Returns:
            ProcessingResult with extracted text, page provenance, KG, and
            status reflecting success / partial / failed outcomes.
        """
        start_time = time.time()
        source_str = str(input_source)

        metadata = ProcessingMetadata(
            processor_name="PDFProcessor",
            processor_version="2.0",
            input_type=InputType.FILE,
        )

        try:
            processor = self._get_processor()
            pipeline_metadata = self._extract_pipeline_metadata(options)

            raw = await self._invoke_pipeline(
                processor, input_source, pipeline_metadata
            )
            return self._convert_pipeline_result(
                raw,
                source=source_str,
                start_time=start_time,
                metadata=metadata,
            )

        except Exception as e:
            elapsed = time.time() - start_time
            metadata.processing_time_seconds = elapsed
            metadata.status = ProcessingStatus.FAILED
            # Safe error surface: type + short message; never log body text
            err_type = type(e).__name__
            err_msg = f"{err_type}: {e}"
            metadata.errors.append(err_msg)

            logger.error(
                "PDF processing failed for %s: %s",
                source_str,
                err_type,
            )

            return ProcessingResult(
                knowledge_graph=KnowledgeGraph(source=source_str),
                vectors=VectorStore(),
                content={
                    "error": err_msg,
                    "text": "",
                    "pages": [],
                    "page_coverage": [],
                    "provenance": {},
                },
                metadata=metadata,
                extra={
                    "processor_type": "pdf",
                    "pipeline_status": "error",
                    "error_type": err_type,
                },
            )

    async def _invoke_pipeline(
        self,
        processor: Any,
        input_source: Union[str, Path],
        pipeline_metadata: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        """Call the real PDF pipeline entry point."""
        if hasattr(processor, "process_pdf"):
            result = await processor.process_pdf(
                input_source, metadata=pipeline_metadata
            )
        elif hasattr(processor, "process") and callable(processor.process):
            # Compatible alternate surface (tests / shims)
            maybe = processor.process(input_source, metadata=pipeline_metadata)
            if hasattr(maybe, "__await__"):
                result = await maybe
            else:
                result = maybe
        else:
            raise RuntimeError(
                "PDF processor has no process_pdf or process method"
            )

        if not isinstance(result, dict):
            raise TypeError(
                f"PDF pipeline must return dict, got {type(result).__name__}"
            )
        return result

    @staticmethod
    def _extract_pipeline_metadata(
        options: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Build metadata dict for process_pdf from adapter options."""
        if "metadata" in options and options["metadata"] is not None:
            meta = options["metadata"]
            if not isinstance(meta, dict):
                raise TypeError("options['metadata'] must be a dict or None")
            return meta
        # Forward remaining options as metadata when they look like tags
        reserved = {"metadata"}
        extra = {
            k: v
            for k, v in options.items()
            if k not in reserved and isinstance(k, str)
        }
        return extra or None

    def _convert_pipeline_result(
        self,
        raw: dict[str, Any],
        *,
        source: str,
        start_time: float,
        metadata: ProcessingMetadata,
    ) -> ProcessingResult:
        """
        Map specialized pipeline dict → canonical ProcessingResult.

        Preserves page/span provenance, coverage receipts, warnings, and
        partial/error status. Rejects known placeholder strings.
        """
        elapsed = time.time() - start_time
        metadata.processing_time_seconds = elapsed

        pipeline_status = str(raw.get("status") or "error").lower()
        stages_completed = list(raw.get("stages_completed") or [])

        # Prefer processor-reported version when present
        proc_meta = raw.get("processing_metadata") or {}
        if isinstance(proc_meta, dict):
            pv = proc_meta.get("pipeline_version")
            if pv:
                metadata.processor_version = str(pv)

        text_merge = raw.get("text_merge")
        if not isinstance(text_merge, dict):
            text_merge = {}

        full_text = self._resolve_full_text(raw, text_merge)
        self._assert_not_placeholder(full_text, source)

        pages = self._build_pages(text_merge, raw)
        page_coverage = self._build_page_coverage(text_merge, raw)
        provenance = self._build_provenance(text_merge, raw, pages)
        warnings = self._collect_warnings(raw, text_merge, page_coverage)

        for warning in warnings:
            metadata.add_warning(warning)

        quality_scores = None
        if isinstance(proc_meta, dict):
            quality_scores = proc_meta.get("quality_scores")

        pdf_info = raw.get("pdf_info") if isinstance(raw.get("pdf_info"), dict) else {}
        page_count = (
            pdf_info.get("page_count")
            or provenance.get("page_count")
            or len(pages)
            or 0
        )

        pdf_metadata = {
            "source": source,
            "format": "pdf",
            "pages": page_count,
            "document_id": raw.get("document_id"),
            "ipld_cid": raw.get("ipld_cid"),
        }
        if pdf_info:
            for key, value in pdf_info.items():
                pdf_metadata.setdefault(key, value)

        # --- Status: FAILED / PARTIAL / SUCCESS ---
        if pipeline_status in ("error", "failed", "failure"):
            metadata.status = ProcessingStatus.FAILED
            err = raw.get("error") or raw.get("message") or "PDF pipeline error"
            # Keep error string; do not re-log body
            if not metadata.errors:
                metadata.errors.append(str(err))
        else:
            partial_reason = self._partial_reason(
                text_merge=text_merge,
                full_text=full_text,
                warnings=warnings,
                quality_scores=quality_scores,
                page_coverage=page_coverage,
                pipeline_status=pipeline_status,
            )
            if partial_reason:
                metadata.status = ProcessingStatus.PARTIAL
                if partial_reason not in metadata.warnings:
                    metadata.add_warning(partial_reason)
            else:
                metadata.status = ProcessingStatus.SUCCESS

        kg = self._build_knowledge_graph(
            full_text,
            source,
            pdf_metadata,
            entities=raw.get("extracted_entities"),
            relationships=raw.get("extracted_relationships"),
        )

        vectors = VectorStore(
            metadata={
                "model": "pdf_processor",
                "source": source,
                "document_id": raw.get("document_id"),
            }
        )

        content: dict[str, Any] = {
            "text": full_text,
            "pages": pages,
            "page_coverage": page_coverage,
            "provenance": provenance,
            "metadata": pdf_metadata,
            "stages_completed": stages_completed,
            "quality_scores": quality_scores,
            "ocr_status": text_merge.get("ocr_status")
            or (quality_scores or {}).get("ocr_status"),
            "overall_coverage": text_merge.get("overall_coverage"),
            "overall_ocr_confidence": text_merge.get("overall_ocr_confidence"),
        }
        if pipeline_status in ("error", "failed", "failure"):
            content["error"] = raw.get("error") or raw.get("message")

        return ProcessingResult(
            knowledge_graph=kg,
            vectors=vectors,
            content=content,
            metadata=metadata,
            extra={
                "processor_type": "pdf",
                "pipeline_status": pipeline_status,
                "pages": page_count,
                "document_id": raw.get("document_id"),
                "ipld_cid": raw.get("ipld_cid"),
                "entities_count": raw.get("entities_count"),
                "relationships_count": raw.get("relationships_count"),
                "stages_completed": stages_completed,
            },
        )

    @staticmethod
    def _resolve_full_text(raw: dict[str, Any], text_merge: dict[str, Any]) -> str:
        """Prefer merged full_text; fall back to page joins; never invent text."""
        full = text_merge.get("full_text")
        if isinstance(full, str) and full.strip():
            return full

        pages = text_merge.get("pages")
        if isinstance(pages, list):
            parts = []
            for p in pages:
                if isinstance(p, dict) and isinstance(p.get("text"), str):
                    if p["text"].strip():
                        parts.append(p["text"])
            if parts:
                return "\n\n".join(parts)

        # Optional legacy fields — still real pipeline data, not placeholders
        for key in ("text", "extracted_text", "content_text"):
            val = raw.get(key)
            if isinstance(val, str) and val.strip():
                return val

        return full if isinstance(full, str) else ""

    @staticmethod
    def _assert_not_placeholder(text: str, source: str) -> None:
        """Hard-fail if the adapter would emit a known placeholder string."""
        if not text:
            return
        stripped = text.strip()
        for prefix in _PLACEHOLDER_PREFIXES:
            if stripped.startswith(prefix) or stripped.lower().startswith(
                prefix.lower()
            ):
                raise RuntimeError(
                    "Refusing placeholder PDF text output; "
                    "real pipeline extraction required"
                )
        # Historical bug: f"PDF content from {input_source}"
        if stripped == f"PDF content from {source}":
            raise RuntimeError(
                "Refusing placeholder PDF text output; "
                "real pipeline extraction required"
            )

    def _build_pages(
        self,
        text_merge: dict[str, Any],
        raw: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Normalize per-page text + span provenance for the content contract."""
        pages_out: list[dict[str, Any]] = []
        merge_pages = text_merge.get("pages")
        if isinstance(merge_pages, list) and merge_pages:
            for p in merge_pages:
                if not isinstance(p, dict):
                    continue
                pages_out.append(
                    {
                        "page": p.get("page"),
                        "text": p.get("text") or "",
                        "spans": list(p.get("spans") or []),
                        "coverage": p.get("coverage") or {},
                        "selected_origins": list(p.get("selected_origins") or []),
                    }
                )
            return pages_out

        # Fall back to page_coverage only (no text) — still provenance
        coverage = raw.get("page_coverage") or text_merge.get("page_coverage")
        if isinstance(coverage, list):
            for c in coverage:
                if not isinstance(c, dict):
                    continue
                pages_out.append(
                    {
                        "page": c.get("page"),
                        "text": "",
                        "spans": [],
                        "coverage": c,
                        "selected_origins": list(c.get("origins_present") or []),
                    }
                )
        return pages_out

    @staticmethod
    def _build_page_coverage(
        text_merge: dict[str, Any],
        raw: dict[str, Any],
    ) -> list[dict[str, Any]]:
        coverage = text_merge.get("page_coverage")
        if isinstance(coverage, list) and coverage:
            return [c if isinstance(c, dict) else {} for c in coverage]
        raw_cov = raw.get("page_coverage")
        if isinstance(raw_cov, list):
            return [c if isinstance(c, dict) else {} for c in raw_cov]
        # Derive from pages
        pages = text_merge.get("pages")
        if isinstance(pages, list):
            out = []
            for p in pages:
                if isinstance(p, dict) and isinstance(p.get("coverage"), dict):
                    out.append(p["coverage"])
            return out
        return []

    @staticmethod
    def _build_provenance(
        text_merge: dict[str, Any],
        raw: dict[str, Any],
        pages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prov = dict(text_merge.get("provenance") or {})
        if not prov:
            prov = {
                "page_count": len(pages),
                "pages_with_text": sum(
                    1 for p in pages if (p.get("text") or "").strip()
                ),
            }
        # Attach span-origin summary for quick consumers
        origins: set[str] = set()
        for p in pages:
            for origin in p.get("selected_origins") or []:
                origins.add(str(origin))
            for span in p.get("spans") or []:
                if isinstance(span, dict) and span.get("origin"):
                    origins.add(str(span["origin"]))
        if origins:
            prov.setdefault("origins_present", sorted(origins))
        ocr_meta = (raw.get("ocr_results") or {}).get("_meta")
        if isinstance(ocr_meta, dict):
            prov.setdefault("ocr_meta", {
                k: ocr_meta[k]
                for k in (
                    "available_engines",
                    "pages_with_rendered_ocr",
                    "pages_ocr_unavailable",
                    "ocr_available",
                )
                if k in ocr_meta
            })
        return prov

    @staticmethod
    def _collect_warnings(
        raw: dict[str, Any],
        text_merge: dict[str, Any],
        page_coverage: list[dict[str, Any]],
    ) -> list[str]:
        warnings: list[str] = []
        for w in text_merge.get("warnings") or []:
            if w and str(w) not in warnings:
                warnings.append(str(w))
        for cov in page_coverage:
            if not isinstance(cov, dict):
                continue
            for w in cov.get("warnings") or []:
                if w and str(w) not in warnings:
                    warnings.append(str(w))
            ocr_status = cov.get("ocr_status")
            if ocr_status in _PARTIAL_OCR_STATUSES:
                msg = f"page {cov.get('page')}: ocr_status={ocr_status}"
                if msg not in warnings:
                    warnings.append(msg)
        # Pipeline-level quality ocr_status
        proc_meta = raw.get("processing_metadata") or {}
        qs = proc_meta.get("quality_scores") if isinstance(proc_meta, dict) else None
        if isinstance(qs, dict):
            ocr_st = qs.get("ocr_status")
            if ocr_st in _PARTIAL_OCR_STATUSES:
                msg = f"document ocr_status={ocr_st}"
                if msg not in warnings:
                    warnings.append(msg)
        return warnings

    @staticmethod
    def _partial_reason(
        *,
        text_merge: dict[str, Any],
        full_text: str,
        warnings: list[str],
        quality_scores: Any,
        page_coverage: list[dict[str, Any]],
        pipeline_status: str,
    ) -> Optional[str]:
        """Return a reason string if result should be PARTIAL, else None."""
        if pipeline_status in ("partial", "warning"):
            return f"pipeline_status={pipeline_status}"

        ocr_status = text_merge.get("ocr_status")
        if isinstance(quality_scores, dict) and not ocr_status:
            ocr_status = quality_scores.get("ocr_status")
        if ocr_status in _PARTIAL_OCR_STATUSES:
            return f"ocr_status={ocr_status}"

        for cov in page_coverage:
            if not isinstance(cov, dict):
                continue
            if cov.get("ocr_status") in _PARTIAL_OCR_STATUSES:
                return f"page_ocr_status={cov.get('ocr_status')}"
            if cov.get("status") in ("empty", "partial", "failed"):
                # empty page with no OCR is a coverage gap when no text overall
                if not full_text.strip():
                    return f"page_status={cov.get('status')}"

        if warnings:
            # Warnings alone (e.g. disagreement) still surface as partial when
            # they indicate extraction incompleteness; keep success only when
            # warnings list is empty.
            significant = [
                w
                for w in warnings
                if any(
                    token in w.lower()
                    for token in (
                        "ocr",
                        "unavailable",
                        "low_confidence",
                        "failed",
                        "empty",
                        "coverage",
                        "missing",
                    )
                )
            ]
            if significant:
                return significant[0]

        if not (full_text or "").strip():
            return "no_extractable_text"

        if isinstance(quality_scores, dict):
            overall = quality_scores.get("overall_quality")
            try:
                if overall is not None and float(overall) < 0.5:
                    return f"low_overall_quality={overall}"
            except (TypeError, ValueError):
                pass

        return None

    def _build_knowledge_graph(
        self,
        text: str,
        source: str,
        pdf_metadata: dict,
        entities: Any = None,
        relationships: Any = None,
    ) -> KnowledgeGraph:
        """Build knowledge graph from pipeline entities or a document node."""
        kg = KnowledgeGraph(source=source)

        # Prefer real extracted entities from the pipeline
        if isinstance(entities, list) and entities:
            for idx, ent in enumerate(entities):
                if not isinstance(ent, dict):
                    continue
                eid = str(
                    ent.get("id")
                    or ent.get("entity_id")
                    or f"entity_{idx}"
                )
                etype = str(ent.get("type") or ent.get("entity_type") or "Entity")
                label = str(
                    ent.get("label")
                    or ent.get("name")
                    or ent.get("text")
                    or eid
                )
                conf = ent.get("confidence", 1.0)
                try:
                    conf_f = float(conf) if conf is not None else 1.0
                except (TypeError, ValueError):
                    conf_f = 1.0
                conf_f = max(0.0, min(1.0, conf_f))
                props = {
                    k: v
                    for k, v in ent.items()
                    if k
                    not in (
                        "id",
                        "entity_id",
                        "type",
                        "entity_type",
                        "label",
                        "name",
                        "text",
                        "confidence",
                    )
                }
                kg.add_entity(
                    Entity(
                        id=eid,
                        type=etype,
                        label=label,
                        properties=props,
                        confidence=conf_f,
                    )
                )

        if isinstance(relationships, list) and relationships:
            for idx, rel in enumerate(relationships):
                if not isinstance(rel, dict):
                    continue
                src = rel.get("source") or rel.get("source_id")
                tgt = rel.get("target") or rel.get("target_id")
                if not src or not tgt:
                    continue
                conf = rel.get("confidence", 1.0)
                try:
                    conf_f = float(conf) if conf is not None else 1.0
                except (TypeError, ValueError):
                    conf_f = 1.0
                conf_f = max(0.0, min(1.0, conf_f))
                kg.add_relationship(
                    Relationship(
                        id=str(rel.get("id") or f"rel_{idx}"),
                        source=str(src),
                        target=str(tgt),
                        type=str(rel.get("type") or rel.get("relationship_type") or "RELATED"),
                        properties={
                            k: v
                            for k, v in rel.items()
                            if k
                            not in (
                                "id",
                                "source",
                                "source_id",
                                "target",
                                "target_id",
                                "type",
                                "relationship_type",
                                "confidence",
                            )
                        },
                        confidence=conf_f,
                    )
                )

        # Always include a document-level node for provenance anchoring
        doc_entity = Entity(
            id=f"pdf_{abs(hash(source))}",
            type="PDFDocument",
            label=Path(source).name,
            properties={
                "source": source,
                "pages": pdf_metadata.get("pages", 0),
                "word_count": len(text.split()) if text else 0,
                "document_id": pdf_metadata.get("document_id"),
                "ipld_cid": pdf_metadata.get("ipld_cid"),
            },
        )
        kg.add_entity(doc_entity)
        return kg

    def get_supported_types(self) -> list[str]:
        """Return supported input types."""
        return ["pdf", "file"]

    def get_priority(self) -> int:
        """Return processor priority (higher for specialized processors)."""
        return 10

    def get_name(self) -> str:
        """Return processor name."""
        return "PDFProcessor"
