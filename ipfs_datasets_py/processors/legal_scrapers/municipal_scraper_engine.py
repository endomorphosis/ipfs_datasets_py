"""
Municipal Scraper Fallback Engine — canonical business logic.

Extracted from mcp_server/tools/legal_dataset_tools/municipal_scraper_fallbacks.py
and mcp_server/tools/legacy_mcp_tools/municipal_scraper_fallbacks.py.

Reusable by:
- MCP server tools (mcp_server/tools/legal_dataset_tools/)
- CLI commands
- Direct Python imports:
    from ipfs_datasets_py.processors.legal_scrapers.municipal_scraper_engine import (
        MunicipalScraperFallbacks,
        scrape_with_fallbacks,
    )
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


_STATE_RE = re.compile(r"\b([A-Z]{2})\b")


def _parse_jurisdiction_hint(jurisdiction: str) -> Tuple[Optional[str], Optional[str]]:
    """Best-effort extraction of place/state from labels like "Portland, OR"."""
    text = str(jurisdiction or "").strip()
    if not text:
        return None, None

    state_code = None
    match = _STATE_RE.search(text)
    if match:
        state_code = match.group(1).upper()

    place = text
    if "," in place:
        place = place.split(",", 1)[0]
    place = re.sub(r"\b(city|town|village|county)\s+of\b", "", place, flags=re.IGNORECASE)
    place = re.sub(r"\b[A-Z]{2}\b", "", place).strip(" ,")
    return place or None, state_code

class MunicipalScraperFallbacks:
    """
    Manages fallback scraping strategies for municipal code websites.
    
    This class coordinates multiple scraping methods to ensure reliable
    data collection even when primary sources fail or are unavailable.
    """
    
    def __init__(self):
        """Initialize fallback scraper with default configuration."""
        self.supported_methods = [
            "common_crawl",
            "wayback_machine",
            "archive_is",
            "autoscraper",
            "ipwb",
            "playwright"
        ]
        
        self.method_descriptions = {
            "common_crawl": "Query Common Crawl archives for historical municipal website data",
            "wayback_machine": "Retrieve archived snapshots from Internet Archive's Wayback Machine",
            "archive_is": "Access webpage archives from Archive.is service",
            "autoscraper": "Use AutoScraper for pattern-based data extraction",
            "ipwb": "Query InterPlanetary Wayback for decentralized web archives",
            "playwright": "Direct browser automation as final fallback"
        }
    
    async def scrape_with_fallbacks(
        self,
        url: str,
        jurisdiction: str,
        fallback_methods: List[str],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Attempt to scrape municipal codes using fallback methods.
        
        Args:
            url: Target URL to scrape
            jurisdiction: Jurisdiction name (e.g., "Seattle, WA")
            fallback_methods: List of methods to try in order
            **kwargs: Additional parameters for specific scrapers
            
        Returns:
            Dictionary with scraping results and metadata
        """
        results = {
            "jurisdiction": jurisdiction,
            "url": url,
            "attempts": [],
            "success": False,
            "data": None,
            "metadata": {}
        }
        
        for method in fallback_methods:
            if method not in self.supported_methods:
                logger.warning(f"Unknown fallback method: {method}")
                continue
            
            try:
                logger.info(f"Attempting {method} for {jurisdiction}")
                
                if method == "common_crawl":
                    result = await self._scrape_common_crawl(url, jurisdiction, **kwargs)
                elif method == "wayback_machine":
                    result = await self._scrape_wayback_machine(url, jurisdiction, **kwargs)
                elif method == "archive_is":
                    result = await self._scrape_archive_is(url, jurisdiction, **kwargs)
                elif method == "autoscraper":
                    result = await self._scrape_autoscraper(url, jurisdiction, **kwargs)
                elif method == "ipwb":
                    result = await self._scrape_ipwb(url, jurisdiction, **kwargs)
                elif method == "playwright":
                    result = await self._scrape_playwright(url, jurisdiction, **kwargs)
                
                results["attempts"].append({
                    "method": method,
                    "success": result.get("success", False),
                    "timestamp": datetime.now().isoformat(),
                    "message": result.get("message", "")
                })
                
                if result.get("success"):
                    results["success"] = True
                    results["data"] = result.get("data")
                    results["metadata"] = result.get("metadata", {})
                    results["metadata"]["successful_method"] = method
                    logger.info(f"Successfully scraped {jurisdiction} using {method}")
                    break
                    
            except Exception as e:
                logger.error(f"Error with {method} for {jurisdiction}: {e}")
                results["attempts"].append({
                    "method": method,
                    "success": False,
                    "timestamp": datetime.now().isoformat(),
                    "error": str(e)
                })
        
        return results
    
    async def _scrape_common_crawl(
        self,
        url: str,
        jurisdiction: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Scrape municipal codes from Common Crawl archives.
        
        Common Crawl provides petabyte-scale web crawl data. This method
        queries the Common Crawl Index to find archived versions of municipal
        code websites and extracts the legal text.
        
        Args:
            url: Target URL
            jurisdiction: Jurisdiction name
            **kwargs: Additional parameters
            
        Returns:
            Scraping result dictionary
        """
        logger.info(f"Querying Common Crawl for {url}")

        place_name, state_code = _parse_jurisdiction_hint(jurisdiction)
        place_name = kwargs.get("place_name") or place_name
        state_code = (kwargs.get("state_code") or state_code or "").upper() or None
        gnis = kwargs.get("gnis")
        max_results = int(kwargs.get("max_results") or kwargs.get("common_crawl_max_results") or 25)
        max_pages = int(kwargs.get("max_pages") or kwargs.get("common_crawl_max_pages") or min(max_results, 10))
        url_terms = kwargs.get("url_terms")
        if url_terms is None:
            url_terms = ["code", "ordinance", "charter", "municipal"]
        mime_terms = kwargs.get("mime_terms")

        try:
            index_loader = kwargs.get("index_loader")
            if index_loader is None:
                from .common_crawl_index_loader import CommonCrawlIndexLoader

                index_loader = CommonCrawlIndexLoader(
                    local_base_dir=kwargs.get("common_crawl_index_dir"),
                    use_hf_fallback=kwargs.get("use_hf_fallback", True),
                )

            records = index_loader.query_municipal_index(
                place_name=place_name,
                state_code=state_code,
                gnis=gnis,
                url_terms=url_terms,
                mime_terms=mime_terms,
                max_results=max_results,
            )
            if kwargs.get("dedupe_urls"):
                deduped: Dict[str, Dict[str, Any]] = {}
                for record in records:
                    record_url = str(record.get("url") or "").strip()
                    if not record_url:
                        continue
                    current = deduped.get(record_url)
                    if current is None or str(record.get("timestamp") or "") > str(current.get("timestamp") or ""):
                        deduped[record_url] = record
                records = sorted(
                    deduped.values(),
                    key=lambda item: (
                        0 if int(item.get("status") or 0) == 200 else 1,
                        str(item.get("timestamp") or ""),
                    ),
                    reverse=True,
                )
        except Exception as exc:
            return {
                "success": False,
                "message": f"Common Crawl municipal index query failed: {type(exc).__name__}: {exc}",
                "data": None,
                "metadata": {
                    "method": "common_crawl",
                    "url": url,
                    "jurisdiction": jurisdiction,
                    "place_name": place_name,
                    "state_code": state_code,
                },
            }

        if not records:
            last_error = str(getattr(index_loader, "last_query_error", "") or "")
            return {
                "success": False,
                "message": last_error or "No Common Crawl municipal index records found",
                "data": None,
                "metadata": {
                    "method": "common_crawl",
                    "url": url,
                    "jurisdiction": jurisdiction,
                    "place_name": place_name,
                    "state_code": state_code,
                    "gnis": gnis,
                    "url_terms": list(url_terms or []),
                },
            }

        ccapi = kwargs.get("ccapi")
        if ccapi is None:
            try:
                try:
                    from ..web_archiving.common_crawl_integration import _ensure_common_crawl_import_path

                    _ensure_common_crawl_import_path()
                except Exception:
                    pass
                from common_crawl_search_engine.ccindex import api as ccapi
            except Exception as exc:
                return {
                    "success": False,
                    "message": f"common_crawl_search_engine unavailable: {type(exc).__name__}: {exc}",
                    "data": None,
                    "metadata": {
                        "method": "common_crawl",
                        "url": url,
                        "jurisdiction": jurisdiction,
                        "candidate_records": records[: min(len(records), 25)],
                    },
                }

        pages: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        prefix = str(kwargs.get("common_crawl_prefix") or "https://data.commoncrawl.org/")
        timeout_s = float(kwargs.get("timeout") or kwargs.get("common_crawl_timeout") or 30)
        max_bytes = int(kwargs.get("common_crawl_fetch_max_bytes") or 2_000_000)
        cache_mode = str(kwargs.get("common_crawl_cache_mode") or "range")

        for record in records[:max_pages]:
            page_url = str(record.get("url") or url)
            wf = record.get("warc_filename")
            off = record.get("warc_offset")
            ln = record.get("warc_length")
            if not wf or off is None or ln is None:
                errors.append({"url": page_url, "error": "Common Crawl pointer missing warc_filename/offset/length"})
                continue

            try:
                fetch, source, local_path = ccapi.fetch_warc_record(
                    warc_filename=str(wf),
                    warc_offset=int(off),
                    warc_length=int(ln),
                    prefix=prefix,
                    timeout_s=timeout_s,
                    max_bytes=max_bytes,
                    decode_gzip_text=False,
                    cache_mode=cache_mode,
                )
                if not getattr(fetch, "ok", False) or not getattr(fetch, "raw_base64", None):
                    errors.append({"url": page_url, "error": str(getattr(fetch, "error", None) or "fetch_warc_record failed")})
                    continue

                import base64

                gz_bytes = base64.b64decode(fetch.raw_base64)
                http = ccapi.extract_http_from_warc_gzip_member(
                    gz_bytes,
                    max_body_bytes=max_bytes,
                    max_preview_chars=200_000,
                    include_body_base64=True,
                )
                body_mime = str(getattr(http, "body_mime", "") or "")
                is_html = bool(getattr(http, "body_is_html", False)) or body_mime.lower().startswith("text/html")
                html = str(getattr(http, "body_text_preview", "") or "") if is_html else ""
                text = ""
                title = ""
                links: List[Dict[str, str]] = []
                body_base64 = getattr(http, "body_base64", None)
                body_text = ""
                if html:
                    try:
                        from bs4 import BeautifulSoup

                        soup = BeautifulSoup(html, "html.parser")
                        title_tag = soup.find("title")
                        title = title_tag.get_text(strip=True) if title_tag else ""
                        for script in soup(["script", "style"]):
                            script.decompose()
                        text = soup.get_text(separator="\n", strip=True)
                        for link in soup.find_all("a", href=True):
                            href = str(link.get("href") or "")
                            if href.startswith("/"):
                                href = urljoin(page_url, href)
                            links.append({"url": href, "text": link.get_text(strip=True)})
                    except Exception:
                        text = html
                elif body_base64 and "pdf" in body_mime.lower():
                    pdf_bytes = b""
                    try:
                        import base64
                        from io import BytesIO

                        pdf_bytes = base64.b64decode(body_base64)
                        try:
                            from pypdf import PdfReader
                        except Exception:
                            from PyPDF2 import PdfReader  # type: ignore

                        reader = PdfReader(BytesIO(pdf_bytes))
                        body_text = "\n".join((page.extract_text() or "") for page in reader.pages)
                    except Exception as exc:
                        errors.append({"url": page_url, "error": f"PDF text extraction failed: {type(exc).__name__}: {exc}"})
                    if not body_text.strip() and pdf_bytes:
                        try:
                            import subprocess
                            from tempfile import NamedTemporaryFile

                            with NamedTemporaryFile(suffix=".pdf") as handle:
                                handle.write(pdf_bytes)
                                handle.flush()
                                completed = subprocess.run(
                                    ["pdftotext", handle.name, "-"],
                                    capture_output=True,
                                    timeout=30,
                                    check=False,
                                )
                            fallback_text = completed.stdout.decode("utf-8", errors="ignore").strip()
                            if fallback_text:
                                body_text = fallback_text
                        except Exception as exc:
                            errors.append({"url": page_url, "error": f"pdftotext fallback failed: {type(exc).__name__}: {exc}"})

                if html or text or body_base64:
                    pages.append(
                        {
                            "url": page_url,
                            "title": title,
                            "text": text or body_text,
                            "html": html,
                            "body_base64": body_base64,
                            "body_mime": body_mime,
                            "links": links,
                            "metadata": {
                                "cc_record": record,
                                "cc_source": source,
                                "cc_local_warc_path": local_path,
                                "http_status": getattr(http, "http_status", None),
                                "http_mime": getattr(http, "body_mime", None),
                                "http_charset": getattr(http, "body_charset", None),
                                "ok": getattr(http, "ok", None),
                                "error": getattr(http, "error", None),
                            },
                        }
                    )
                else:
                    errors.append({"url": page_url, "error": str(getattr(http, "error", None) or "empty extracted body")})
            except Exception as exc:
                errors.append({"url": page_url, "error": f"{type(exc).__name__}: {exc}"})

        if pages:
            return {
                "success": True,
                "message": f"Extracted {len(pages)} Common Crawl municipal page(s)",
                "data": {
                    "pages": pages,
                    "records_considered": len(records),
                },
                "metadata": {
                    "method": "common_crawl",
                    "url": url,
                    "jurisdiction": jurisdiction,
                    "place_name": place_name,
                    "state_code": state_code,
                    "gnis": gnis,
                    "errors": errors,
                },
            }

        return {
            "success": False,
            "message": "Common Crawl records were found, but no pages could be extracted",
            "data": None,
            "metadata": {
                "method": "common_crawl",
                "url": url,
                "jurisdiction": jurisdiction,
                "place_name": place_name,
                "state_code": state_code,
                "candidate_records": records[: min(len(records), 25)],
                "errors": errors,
            }
        }
    
    async def _scrape_wayback_machine(
        self,
        url: str,
        jurisdiction: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Scrape municipal codes from Internet Archive's Wayback Machine.
        
        The Wayback Machine archives billions of web pages. This method
        queries the Wayback Machine API to find archived snapshots of
        municipal code websites.
        
        Args:
            url: Target URL
            jurisdiction: Jurisdiction name
            **kwargs: Additional parameters
            
        Returns:
            Scraping result dictionary
        """
        logger.info(f"Querying Wayback Machine for {url}")
        
        # Placeholder implementation
        # TODO: Implement Wayback Machine API integration
        # - Use Wayback Machine Availability API
        # - Find latest/best snapshot of the municipal code page
        # - Retrieve archived HTML content
        # - Extract legal text and metadata
        
        return {
            "success": False,
            "message": "Wayback Machine integration not yet implemented",
            "data": None,
            "metadata": {
                "method": "wayback_machine",
                "url": url,
                "note": "Will use Wayback Machine API (https://archive.org/wayback/available)"
            }
        }
    
    async def _scrape_archive_is(
        self,
        url: str,
        jurisdiction: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Scrape municipal codes from Archive.is.
        
        Archive.is provides on-demand webpage archiving. This method
        checks for existing archives or creates new ones of municipal
        code websites.
        
        Args:
            url: Target URL
            jurisdiction: Jurisdiction name
            **kwargs: Additional parameters
            
        Returns:
            Scraping result dictionary
        """
        logger.info(f"Querying Archive.is for {url}")
        
        # Placeholder implementation
        # TODO: Implement Archive.is integration
        # - Check for existing archives via Archive.is search
        # - If not found, submit URL for archiving
        # - Retrieve archived content
        # - Extract legal text
        
        return {
            "success": False,
            "message": "Archive.is integration not yet implemented",
            "data": None,
            "metadata": {
                "method": "archive_is",
                "url": url,
                "note": "Will check Archive.is archives and create new ones if needed"
            }
        }
    
    async def _scrape_autoscraper(
        self,
        url: str,
        jurisdiction: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Scrape municipal codes using AutoScraper.
        
        AutoScraper uses machine learning to automatically identify and
        extract structured data from web pages based on example patterns.
        
        Args:
            url: Target URL
            jurisdiction: Jurisdiction name
            **kwargs: Additional parameters
            
        Returns:
            Scraping result dictionary
        """
        logger.info(f"Using AutoScraper for {url}")
        
        # Placeholder implementation
        # TODO: Implement AutoScraper integration
        # - Initialize AutoScraper with example patterns
        # - Train on sample municipal code pages
        # - Apply learned patterns to extract legal text
        # - Structure extracted data
        
        return {
            "success": False,
            "message": "AutoScraper integration not yet implemented",
            "data": None,
            "metadata": {
                "method": "autoscraper",
                "url": url,
                "note": "Will use AutoScraper for pattern-based extraction"
            }
        }
    
    async def _scrape_ipwb(
        self,
        url: str,
        jurisdiction: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Scrape municipal codes from InterPlanetary Wayback (IPWB).
        
        IPWB is a decentralized web archive system built on IPFS. This method
        queries IPWB for archived versions of municipal code websites.
        
        Args:
            url: Target URL
            jurisdiction: Jurisdiction name
            **kwargs: Additional parameters
            
        Returns:
            Scraping result dictionary
        """
        logger.info(f"Querying IPWB for {url}")
        
        # Placeholder implementation
        # TODO: Implement IPWB integration
        # - Connect to IPWB service
        # - Query for archived versions of the URL
        # - Retrieve content from IPFS
        # - Extract legal text
        
        return {
            "success": False,
            "message": "IPWB integration not yet implemented",
            "data": None,
            "metadata": {
                "method": "ipwb",
                "url": url,
                "note": "Will query InterPlanetary Wayback for decentralized archives"
            }
        }
    
    async def _scrape_playwright(
        self,
        url: str,
        jurisdiction: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Scrape municipal codes using Playwright browser automation.
        
        Playwright provides reliable cross-browser automation. This is
        used as a final fallback when archive-based methods fail.
        
        Args:
            url: Target URL
            jurisdiction: Jurisdiction name
            **kwargs: Additional parameters
            
        Returns:
            Scraping result dictionary
        """
        logger.info(f"Using Playwright for {url}")
        
        # Placeholder implementation
        # TODO: Implement Playwright fallback
        # - Launch headless browser
        # - Navigate to municipal code URL
        # - Wait for dynamic content to load
        # - Extract legal text from rendered HTML
        # - Handle JavaScript-heavy sites
        
        return {
            "success": False,
            "message": "Playwright fallback not yet implemented",
            "data": None,
            "metadata": {
                "method": "playwright",
                "url": url,
                "note": "Will use Playwright for direct browser automation"
            }
        }
    
    def get_method_info(self, method: str) -> Dict[str, Any]:
        """
        Get information about a specific fallback method.
        
        Args:
            method: Method name
            
        Returns:
            Dictionary with method information
        """
        if method not in self.supported_methods:
            return {"error": f"Unknown method: {method}"}
        
        return {
            "method": method,
            "description": self.method_descriptions.get(method, ""),
            "supported": True,
            "implementation_status": "planned"
        }
    
    def list_methods(self) -> List[Dict[str, Any]]:
        """
        List all supported fallback methods.
        
        Returns:
            List of method information dictionaries
        """
        return [self.get_method_info(method) for method in self.supported_methods]


# Global convenience instance (also exposed as fallback_scraper for backward compat)
_fallback_scraper = MunicipalScraperFallbacks()
fallback_scraper = _fallback_scraper  # backward-compatible alias


async def scrape_with_fallbacks(
    url: str,
    jurisdiction: str,
    fallback_methods: Optional[List[str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Convenience function to scrape municipal codes using fallback methods.

    Args:
        url: Target URL to scrape.
        jurisdiction: Jurisdiction name (e.g., "Seattle, WA").
        fallback_methods: Ordered list of fallback method names to try.
            Defaults to all supported methods.
        **kwargs: Additional parameters forwarded to the underlying scraper.

    Returns:
        Dictionary with scraping results and metadata.
    """
    if fallback_methods is None:
        fallback_methods = [
            "wayback_machine",
            "archive_is",
            "common_crawl",
            "ipwb",
            "autoscraper",
            "playwright",
        ]
    return await _fallback_scraper.scrape_with_fallbacks(
        url, jurisdiction, fallback_methods, **kwargs
    )
