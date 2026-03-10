"""Integrated PDF Processing for State Administrative Rules.

This module handles PDF extraction, processing, and indexing for
state administrative rules, leveraging the specialized PDF processors
in ipfs_datasets_py/processors/specialized/pdf/.

Features:
- PDF discovery from state agency domains
- Text extraction with OCR fallback
- Rule classification and segmentation
- Metadata enrichment
- Parallel batch processing
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PDFProcessingResult:
    """Result of processing a single PDF."""
    
    pdf_url: str
    state_code: str
    
    status: str  # "success", "partial", "error", "timeout"
    error_message: Optional[str] = None
    
    extracted_text: Optional[str] = None
    extracted_rules: List[Dict[str, Any]] = None
    
    page_count: int = 0
    text_length: int = 0
    
    method_used: str = "unknown"  # "pdfplumber", "ocr", "fallback"
    processing_time_seconds: float = 0.0


class IntegratedPDFProcessor:
    """Processes PDFs for state administrative rules."""
    
    def __init__(self, enable_ocr: bool = True):
        """Initialize PDF processor.
        
        Args:
            enable_ocr: Whether to use OCR fallback for images/scanned PDFs
        """
        self.enable_ocr = enable_ocr
        self._pdf_extractor = None
        self._ocr_engine = None
        self._initialized = False
    
    async def process_pdf_batch(
        self,
        pdf_urls: List[str],
        state_code: str,
        max_concurrent: int = 4,
        timeout_per_pdf: float = 30.0,
    ) -> List[PDFProcessingResult]:
        """Process multiple PDFs in parallel.
        
        Args:
            pdf_urls: List of PDF URLs to process
            state_code: State code for context
            max_concurrent: Max concurrent PDF processing tasks
            timeout_per_pdf: Timeout per PDF in seconds
        
        Returns:
            List of PDFProcessingResult objects
        """
        await self._ensure_initialized()
        
        results = []
        semaphore = asyncio.Semaphore(max_concurrent)
        
        tasks = []
        for url in pdf_urls:
            task = self._process_pdf_with_semaphore(
                semaphore=semaphore,
                pdf_url=url,
                state_code=state_code,
                timeout=timeout_per_pdf,
            )
            tasks.append((url, task))
        
        for url, task in tasks:
            try:
                result = await task
                results.append(result)
            except Exception as exc:
                logger.error(f"Failed to process PDF {url}: {exc}")
                results.append(
                    PDFProcessingResult(
                        pdf_url=url,
                        state_code=state_code,
                        status="error",
                        error_message=str(exc),
                    )
                )
        
        return results
    
    async def _process_pdf_with_semaphore(
        self,
        semaphore: asyncio.Semaphore,
        pdf_url: str,
        state_code: str,
        timeout: float,
    ) -> PDFProcessingResult:
        """Process a single PDF with semaphore-controlled concurrency."""
        async with semaphore:
            return await self._process_single_pdf(
                pdf_url=pdf_url,
                state_code=state_code,
                timeout=timeout,
            )
    
    async def _process_single_pdf(
        self,
        pdf_url: str,
        state_code: str,
        timeout: float,
    ) -> PDFProcessingResult:
        """Process a single PDF document."""
        import time
        start_time = time.monotonic()
        result = PDFProcessingResult(pdf_url=pdf_url, state_code=state_code)
        
        try:
            # Phase 1: Download PDF
            logger.debug(f"Downloading PDF: {pdf_url}")
            pdf_bytes = await self._download_pdf(pdf_url, timeout=timeout * 0.3)
            if not pdf_bytes:
                result.status = "error"
                result.error_message = "Failed to download PDF"
                return result
            
            # Phase 2: Extract text
            logger.debug(f"Extracting text from PDF: {pdf_url}")
            extracted_text, page_count, method = await self._extract_text_from_pdf(
                pdf_bytes=pdf_bytes,
                pdf_url=pdf_url,
                timeout=timeout * 0.4,
            )
            
            if not extracted_text:
                result.status = "error"
                result.error_message = "Failed to extract text"
                return result
            
            result.extracted_text = extracted_text
            result.page_count = page_count
            result.text_length = len(extracted_text)
            result.method_used = method
            
            # Phase 3: Extract rules from text
            logger.debug(f"Extracting rules from PDF text: {pdf_url}")
            rules = await self._extract_rules_from_pdf_text(
                text=extracted_text,
                pdf_url=pdf_url,
                state_code=state_code,
            )
            
            result.extracted_rules = rules
            result.status = "success" if rules else "partial"
        
        except asyncio.TimeoutError:
            result.status = "timeout"
            result.error_message = f"Processing timeout ({timeout}s)"
        except Exception as exc:
            result.status = "error"
            result.error_message = str(exc)
            logger.exception(f"Error processing PDF {pdf_url}")
        
        finally:
            result.processing_time_seconds = time.monotonic() - start_time
        
        return result
    
    async def _download_pdf(
        self, pdf_url: str, timeout: float = 10.0
    ) -> Optional[bytes]:
        """Download PDF from URL."""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    pdf_url,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    headers={"User-Agent": "Mozilla/5.0"},
                ) as response:
                    if response.status == 200:
                        return await response.read()
        
        except ImportError:
            # Fallback to requests if aiohttp not available
            try:
                import requests
                result = await asyncio.to_thread(
                    requests.get,
                    pdf_url,
                    timeout=timeout,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if result.status_code == 200:
                    return result.content
            except Exception as exc:
                logger.debug(f"Failed to download PDF: {exc}")
        
        except Exception as exc:
            logger.debug(f"Error downloading PDF {pdf_url}: {exc}")
        
        return None
    
    async def _extract_text_from_pdf(
        self, pdf_bytes: bytes, pdf_url: str, timeout: float = 15.0
    ) -> Tuple[Optional[str], int, str]:
        """Extract text from PDF using specialized processors.
        
        Returns:
            (extracted_text, page_count, method_used) tuple
        """
        # Try pdfplumber first (fast, accurate)
        try:
            import pdfplumber
            
            with pdfplumber.open(pdf_bytes) as pdf:
                page_count = len(pdf.pages)
                text_parts = []
                
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                
                if text_parts:
                    extracted_text = "\n".join(text_parts)
                    return extracted_text, page_count, "pdfplumber"
        
        except ImportError:
            logger.debug("pdfplumber not available, trying fallback")
        except Exception as exc:
            logger.debug(f"pdfplumber extraction failed: {exc}")
        
        # Try PyPDF2 as fallback
        try:
            import PyPDF2
            from io import BytesIO
            
            pdf_file = BytesIO(pdf_bytes)
            reader = PyPDF2.PdfReader(pdf_file)
            page_count = len(reader.pages)
            text_parts = []
            
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            
            if text_parts:
                extracted_text = "\n".join(text_parts)
                return extracted_text, page_count, "PyPDF2"
        
        except ImportError:
            pass
        except Exception as exc:
            logger.debug(f"PyPDF2 extraction failed: {exc}")
        
        # Try specialized PDF processor if enable_ocr
        if self.enable_ocr:
            try:
                from ipfs_datasets_py.processors.specialized.pdf.pdf_processor import PDFProcessor
                
                processor = PDFProcessor()
                result = await asyncio.to_thread(processor.process, pdf_bytes)
                if result and result.get("text"):
                    return result["text"], result.get("page_count", 0), "specialized_pdf"
            
            except ImportError:
                pass
            except Exception as exc:
                logger.debug(f"Specialized PDF processor failed: {exc}")
        
        return None, 0, "failed"
    
    async def _extract_rules_from_pdf_text(
        self,
        text: str,
        pdf_url: str,
        state_code: str,
    ) -> List[Dict[str, Any]]:
        """Extract rule records from PDF text."""
        if not text or len(text) < 220:
            return []
        
        # Check if text looks like administrative rules
        is_admin_rule = self._looks_like_admin_rule(text)
        if not is_admin_rule:
            return []
        
        # Segment PDF by potential rules (simple heuristic)
        rules = []
        
        # Look for chapter/rule patterns
        pattern = re.compile(
            r"(?:chapter|title|part|section|rule)\s+([A-Z0-9\-\.]+)",
            re.IGNORECASE,
        )
        
        for match in pattern.finditer(text):
            rule_id = match.group(1)
            start_pos = match.start()
            
            # Extract context around rule ID (up to 1000 chars of surrounding text)
            end_pos = min(len(text), start_pos + 2000)
            rule_text = text[start_pos:end_pos]
            
            rules.append({
                "state_code": state_code,
                "pdf_url": pdf_url,
                "rule_id": rule_id,
                "text": rule_text,
                "domain": urlparse(pdf_url).netloc,
                "source": "pdf_extraction",
            })
        
        # If no rules matched pattern, return the whole text as one rule
        if not rules:
            domain = urlparse(pdf_url).netloc
            title = self._extract_title_from_pdf(text, domain)
            
            rules.append({
                "state_code": state_code,
                "pdf_url": pdf_url,
                "title": title,
                "text": text[:5000],  # Limit to first 5k chars
                "domain": domain,
                "source": "pdf_extraction",
            })
        
        return rules
    
    def _looks_like_admin_rule(self, text: str) -> bool:
        """Check if text looks like administrative rules."""
        pattern = re.compile(
            r"administrative|admin\.?\s+code|regulation|agency\s+rule|oar\b|aac\b",
            re.IGNORECASE,
        )
        return bool(pattern.search(text))
    
    def _extract_title_from_pdf(self, text: str, domain: str) -> str:
        """Extract title from PDF text."""
        # Try first line as title
        lines = text.split("\n")
        for line in lines[:5]:
            line = line.strip()
            if len(line) > 10 and len(line) < 200:
                return line
        
        # Fallback to domain name
        return f"Rules from {domain}"
    
    async def _ensure_initialized(self) -> None:
        """Lazy-initialize PDF processors."""
        if self._initialized:
            return
        
        try:
            import pdfplumber
            logger.debug("pdfplumber available for PDF processing")
        except ImportError:
            logger.warning("pdfplumber not available - PDF processing will use fallback")
        
        self._initialized = True


async def discover_and_process_state_pdfs(
    state_code: str,
    known_domains: Optional[List[str]] = None,
    max_concurrent: int = 4,
) -> List[PDFProcessingResult]:
    """Discover and process PDFs for a state.
    
    Args:
        state_code: State code (e.g., "UT")
        known_domains: Domains to search for PDFs
        max_concurrent: Max concurrent PDF processing
    
    Returns:
        List of PDFProcessingResult objects
    """
    processor = IntegratedPDFProcessor(enable_ocr=True)
    
    # TODO: Implement PDF discovery from domains
    # This would need to:
    # 1. Query Common Crawl for .pdf files from domains
    # 2. Or crawl known rule repositories for PDF links
    # 3. Filter for state-relevant PDFs
    
    pdf_urls = []  # Placeholder
    
    if pdf_urls:
        return await processor.process_pdf_batch(
            pdf_urls=pdf_urls,
            state_code=state_code,
            max_concurrent=max_concurrent,
        )
    
    return []
