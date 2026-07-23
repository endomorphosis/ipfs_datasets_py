"""Enhanced State Admin Rules Orchestrator with Parallel Agentic Discovery.

This module provides true parallel agentic discovery for state administrative rules,
addressing the timeout issues in the sequential scraper by leveraging:
- ParallelWebArchiver for 10-25x faster batch retrieval
- Concurrent agentic domain discovery per state
- Integrated corpus gap analysis
- PDF processing for rule documents
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

try:
    import anyio
except ImportError:
    anyio = None

logger = logging.getLogger(__name__)

from .url_archive_cache import URLArchiveCache


@dataclass
class ParallelStateDiscoveryConfig:
    """Configuration for parallel agentic state discovery."""
    
    # Concurrency limits
    max_state_workers: int = 6  # Parallel states being discovered
    max_domain_workers_per_state: int = 4  # URLs being fetched per state
    max_urls_per_domain: int = 20  # Depth limit per domain
    
    # Batch size and fetch budget
    max_fetch_per_state: int = 12  # Total rules to fetch per state
    max_candidates_per_state: int = 40  # Candidates to evaluate
    
    # Timeouts (seconds)
    url_fetch_timeout: float = 25.0  # Per-URL fetch timeout
    state_timeout: float = 180.0  # Per-state total timeout
    domain_timeout: float = 45.0  # Per-domain timeout
    
    # Quality filters
    min_rule_text_chars: int = 220
    require_substantive_text: bool = True
    
    # PDF processing
    enable_pdf_processing: bool = True
    pdf_extract_timeout: float = 15.0
    
    # Gap analysis
    enable_gap_analysis: bool = True
    gap_analysis_sample_size: int = 10
    cache_dir: Optional[str] = None
    cache_read_enabled: bool = True
    cache_write_enabled: bool = True
    cache_to_ipfs: bool = True


@dataclass
class StateDiscoveryResult:
    """Result of discovering rules for a single state."""
    
    state_code: str
    state_name: str
    status: str  # "success", "partial", "timeout", "error"
    
    rules: List[Dict[str, Any]] = field(default_factory=list)
    urls_discovered: int = 0
    urls_fetched: int = 0
    fetch_errors: int = 0
    
    domains_visited: Set[str] = field(default_factory=set)
    methods_used: Dict[str, int] = field(default_factory=dict)  # method -> count
    
    start_time: float = field(default_factory=time.monotonic)
    end_time: Optional[float] = None
    duration_seconds: float = 0.0
    
    gap_analysis: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    
    def elapsed(self) -> float:
        """Get elapsed time in seconds."""
        return (self.end_time or time.monotonic()) - self.start_time
    
    def success_rate(self) -> float:
        """Get success rate of fetches."""
        if self.urls_fetched == 0:
            return 0.0
        return (self.urls_fetched - self.fetch_errors) / self.urls_fetched


class ParallelStateAdminOrchestrator:
    """Orchestrates parallel agentic discovery for state admin rules."""
    
    def __init__(
        self,
        config: Optional[ParallelStateDiscoveryConfig] = None,
        parallel_archiver=None,
        pdf_processor=None,
        scrape_optimizer=None,
    ):
        """Initialize orchestrator.
        
        Args:
            config: Discovery configuration
            parallel_archiver: ParallelWebArchiver instance (auto-created if None)
            pdf_processor: PDF processor instance (auto-created if None)
        """
        self.config = config or ParallelStateDiscoveryConfig()
        self.parallel_archiver = parallel_archiver
        self.pdf_processor = pdf_processor
        self.scrape_optimizer = scrape_optimizer
        default_cache_dir = Path.home() / ".cache" / "ipfs_datasets_py" / "state_admin_rules_parallel_cache"
        self.url_cache = URLArchiveCache(
            metadata_dir=self.config.cache_dir or str(default_cache_dir),
            persist_to_ipfs=bool(self.config.cache_to_ipfs),
        )
        
        # Lazy-initialize if not provided
        self._archiver_initialized = False
        self._pdf_initialized = False
        self._optimizer_initialized = False
    
    async def discover_state_rules_parallel(
        self,
        states: List[str],
        seed_urls_by_state: Dict[str, List[str]],
        candidate_domains: Optional[Dict[str, List[str]]] = None,
    ) -> Dict[str, StateDiscoveryResult]:
        """Discover rules for multiple states in parallel.
        
        Args:
            states: List of state codes (e.g., ["UT", "AZ", "RI"])
            seed_urls_by_state: Dict mapping state code to initial seed URLs
            candidate_domains: Dict mapping state code to candidate domain URLs
        
        Returns:
            Dict mapping state code to StateDiscoveryResult
        """
        await self._ensure_archiver_initialized()
        
        results: Dict[str, StateDiscoveryResult] = {}
        
        # Launch parallel state discovery with semaphore for concurrency control
        semaphore = asyncio.Semaphore(self.config.max_state_workers)
        
        tasks = []
        for state_code in states:
            task = self._discover_state_with_semaphore(
                semaphore=semaphore,
                state_code=state_code,
                seed_urls=seed_urls_by_state.get(state_code, []),
                candidate_urls=candidate_domains.get(state_code, []) if candidate_domains else None,
            )
            tasks.append((state_code, task))
        
        # Gather results
        for state_code, task in tasks:
            try:
                result = await task
                results[state_code] = result
            except Exception as exc:
                logger.error(f"Failed to discover rules for {state_code}: {exc}")
                result = StateDiscoveryResult(
                    state_code=state_code,
                    state_name=state_code,
                    status="error",
                    error_message=str(exc),
                )
                results[state_code] = result
        
        return results
    
    async def _discover_state_with_semaphore(
        self,
        semaphore: asyncio.Semaphore,
        state_code: str,
        seed_urls: List[str],
        candidate_urls: Optional[List[str]] = None,
    ) -> StateDiscoveryResult:
        """Discover rules for a state with semaphore-controlled concurrency."""
        async with semaphore:
            return await self._discover_state(
                state_code=state_code,
                seed_urls=seed_urls,
                candidate_urls=candidate_urls,
            )
    
    async def _discover_state(
        self,
        state_code: str,
        seed_urls: List[str],
        candidate_urls: Optional[List[str]] = None,
    ) -> StateDiscoveryResult:
        """Discover rules for a single state with parallel fetching."""
        result = StateDiscoveryResult(state_code=state_code, state_name=state_code, status="partial")
        state_deadline = time.monotonic() + self.config.state_timeout
        
        try:
            # Phase 1: Fetch seed URLs (official entrypoints)
            logger.info(f"[{state_code}] Phase 1: Fetching {len(seed_urls)} seed URLs")
            seed_results = await self._parallel_fetch_urls(
                urls=seed_urls[:6],
                state_code=state_code,
                deadline=state_deadline,
                phase="seeds",
            )
            
            for url, content, method in seed_results:
                if content:
                    result.urls_fetched += 1
                    result.domains_visited.add(urlparse(url).netloc)
                    self._increment_method_count(result, method)
                    
                    # Try to extract rules from content
                    rules = await self._extract_rules_from_content(
                        url=url,
                        content=content,
                        state_code=state_code,
                    )
                    result.rules.extend(rules)
                    
                    if len(result.rules) >= self.config.max_fetch_per_state:
                        break
            
            # Phase 2: Candidate URLs discovery (if seeds insufficient)
            if len(result.rules) < self.config.max_fetch_per_state:
                all_candidates = candidate_urls or []
                if not all_candidates:
                    # Generate candidates from seed URLs via link extraction
                    all_candidates = await self._extract_candidate_urls(
                        seed_urls=seed_urls[:3],
                        state_code=state_code,
                        deadline=state_deadline,
                    )
                
                logger.info(
                    f"[{state_code}] Phase 2: Discovered {len(all_candidates)} "
                    f"candidates from {len(seed_urls)} seeds"
                )
                
                # Parallel fetch candidates
                remaining_budget = self.config.max_fetch_per_state - len(result.rules)
                candidate_results = await self._parallel_fetch_urls(
                    urls=all_candidates[: min(remaining_budget * 3, self.config.max_candidates_per_state)],
                    state_code=state_code,
                    deadline=state_deadline,
                    phase="candidates",
                )
                
                for url, content, method in candidate_results:
                    if len(result.rules) >= self.config.max_fetch_per_state:
                        break
                    
                    if content:
                        result.urls_fetched += 1
                        result.domains_visited.add(urlparse(url).netloc)
                        self._increment_method_count(result, method)
                        
                        rules = await self._extract_rules_from_content(
                            url=url,
                            content=content,
                            state_code=state_code,
                        )
                        result.rules.extend(rules)
            
            # Phase 3: PDF processing (if enabled)
            if self.config.enable_pdf_processing and len(result.rules) < self.config.max_fetch_per_state:
                await self._process_pdfs_if_available(
                    state_code=state_code,
                    candidate_urls=list(dict.fromkeys((seed_urls or []) + list(all_candidates or []))),
                    existing_rules=result.rules,
                    deadline=state_deadline,
                )
            
            # Phase 4: Gap analysis (if enabled)
            if self.config.enable_gap_analysis:
                gap_results = await self._analyze_corpus_gaps(
                    state_code=state_code,
                    discovered_rules=result.rules,
                    candidate_urls=list(dict.fromkeys((seed_urls or []) + list(all_candidates or []))),
                )
                result.gap_analysis = gap_results
            
            result.status = "success" if result.rules else "partial"
            result.urls_discovered = len(all_candidates) if "all_candidates" in locals() else len(seed_urls)
        
        except asyncio.TimeoutError:
            result.status = "timeout"
            result.error_message = f"Discovery timeout after {self.config.state_timeout}s"
        except Exception as exc:
            result.status = "error"
            result.error_message = str(exc)
            logger.exception(f"Error discovering rules for {state_code}")
        
        finally:
            result.end_time = time.monotonic()
            result.duration_seconds = result.elapsed()
        
        return result
    
    async def _parallel_fetch_urls(
        self,
        urls: List[str],
        state_code: str,
        deadline: float,
        phase: str = "default",
    ) -> List[Tuple[str, Optional[str], str]]:
        """Fetch multiple URLs in parallel.
        
        Returns:
            List of (url, content, method) tuples
        """
        if not urls:
            return []

        ordered_urls = [str(url).strip() for url in list(urls or []) if str(url).strip()]
        cached_results: List[Tuple[str, Optional[str], str]] = []
        uncached_urls: List[str] = []
        seen_urls: Set[str] = set()

        for url in ordered_urls:
            normalized = self.url_cache.normalize_url(url)
            if not normalized or normalized in seen_urls:
                continue
            seen_urls.add(normalized)
            if self.config.cache_read_enabled:
                cached = self.url_cache.get(normalized)
                if cached and cached.content:
                    cached_results.append((cached.url, cached.content, f"{cached.source}:cache"))
                    continue
            uncached_urls.append(url)

        if not uncached_urls:
            return cached_results
        
        # Use ParallelWebArchiver if available, otherwise fall back to sequential
        if self.parallel_archiver:
            try:
                archive_kwargs: Dict[str, Any] = {
                    "urls": uncached_urls,
                    "max_concurrent": self.config.max_domain_workers_per_state,
                    "jurisdiction": "state",
                    "state_code": state_code,
                }
                try:
                    results = await self.parallel_archiver.archive_urls_parallel(**archive_kwargs)
                except TypeError as exc:
                    # Preserve compatibility with older/simple archiver shims that
                    # only accept urls/progress/max_concurrent.
                    if "unexpected keyword argument" not in str(exc):
                        raise
                    results = await self.parallel_archiver.archive_urls_parallel(
                        urls=uncached_urls,
                        max_concurrent=self.config.max_domain_workers_per_state,
                    )
                fetched_results: List[Tuple[str, Optional[str], str]] = []
                for result in results:
                    if not result.success or not result.content:
                        continue
                    fetched_results.append((result.url, result.content, result.source))
                    if self.config.cache_write_enabled:
                        await self.url_cache.put(
                            url=result.url,
                            content=result.content,
                            source=str(result.source or "parallel_web_archiver"),
                            metadata={"state_code": state_code, "phase": phase},
                        )
                return cached_results + fetched_results
            except Exception as exc:
                logger.warning(f"ParallelArchiver failed for {state_code}: {exc}")
                # Fall through to sequential fetch
        
        # Sequential fallback with timeout control
        tasks = []
        for url in uncached_urls:
            if time.monotonic() > deadline:
                break
            
            timeout = min(self.config.url_fetch_timeout, deadline - time.monotonic())
            task = self._fetch_single_url(url=url, timeout=timeout)
            tasks.append((url, task))
        
        results = []
        for url, task in tasks:
            try:
                content, method = await task
                if content:
                    results.append((url, content, method))
                    if self.config.cache_write_enabled:
                        await self.url_cache.put(
                            url=url,
                            content=content,
                            source=str(method or "unified_api"),
                            metadata={"state_code": state_code, "phase": phase},
                        )
            except asyncio.TimeoutError:
                logger.debug(f"Timeout fetching {url}")
            except Exception as exc:
                logger.debug(f"Error fetching {url}: {exc}")
        
        return cached_results + results
    
    async def _fetch_single_url(
        self, url: str, timeout: float = 25.0
    ) -> Tuple[Optional[str], str]:
        """Fetch a single URL with unified archiving API.
        
        Returns:
            (content, method_used) tuple
        """
        try:
            from ipfs_datasets_py.processors.web_archiving.contracts import (
                OperationMode,
                UnifiedFetchRequest,
            )
            from ipfs_datasets_py.processors.web_archiving.unified_api import (
                UnifiedWebArchivingAPI,
            )
        except ImportError:
            try:
                from ..web_archiving.contracts import (
                    OperationMode,
                    UnifiedFetchRequest,
                )
                from ..web_archiving.unified_api import UnifiedWebArchivingAPI
            except ImportError:
                return None, "fallback"
        
        try:
            api = UnifiedWebArchivingAPI()
            request = UnifiedFetchRequest(
                url=url,
                mode=OperationMode.BALANCED,
                timeout_seconds=max(1, int(timeout)),
                domain="legal",
            )
            
            response = await asyncio.wait_for(
                asyncio.to_thread(api.fetch, request),
                timeout=timeout,
            )
            
            doc = getattr(response, "document", None)
            if doc:
                content = str(getattr(doc, "text", "") or "").strip()
                method = (getattr(doc, "extraction_provenance", {}) or {}).get("method", "unknown")
                return content if content else None, method
        
        except Exception as exc:
            logger.debug(f"Unified API fetch failed for {url}: {exc}")
        
        return None, "failed"
    
    async def _extract_rules_from_content(
        self, url: str, content: str, state_code: str
    ) -> List[Dict[str, Any]]:
        """Extract rule records from gathered content."""
        url_value = str(url or "").strip()
        if not url_value:
            return []

        lowered_url = url_value.lower()
        if lowered_url.endswith(".pdf") or ".pdf?" in lowered_url:
            scraped = await self._scrape_document_url(url_value, file_type="pdf")
            return self._normalize_scraped_rule_rows(scraped=scraped, state_code=state_code, url=url_value)
        if lowered_url.endswith(".rtf") or ".rtf?" in lowered_url:
            scraped = await self._scrape_document_url(url_value, file_type="rtf")
            return self._normalize_scraped_rule_rows(scraped=scraped, state_code=state_code, url=url_value)

        if not content:
            return []

        await self._ensure_optimizer_initialized()
        cleaned_text = str(content or "").strip()
        structured_fields: Dict[str, Any] = {}
        entities: List[Dict[str, Any]] = []
        if self.scrape_optimizer is not None:
            try:
                parsed = self.scrape_optimizer.transform(
                    url=url_value,
                    title="",
                    text=cleaned_text,
                    metadata={"state_code": state_code},
                    domain="legal",
                )
                cleaned_text = str(getattr(parsed, "cleaned_text", "") or cleaned_text).strip()
                structured_fields = dict(getattr(parsed, "structured_fields", {}) or {})
                entities = list(getattr(parsed, "entities", []) or [])
            except Exception as exc:
                logger.debug("Optimizer transform failed for %s: %s", url_value, exc)

        if len(cleaned_text) < self.config.min_rule_text_chars:
            return []

        is_admin_rule = self._looks_like_admin_rule(cleaned_text)
        if not is_admin_rule and self.config.require_substantive_text:
            return []

        return [
            {
                "state_code": state_code,
                "url": url_value,
                "source_url": url_value,
                "title": cleaned_text[:100] if cleaned_text else "",
                "text": cleaned_text,
                "full_text": cleaned_text,
                "length": len(cleaned_text),
                "domain": urlparse(url_value).netloc,
                "fetched_at": datetime.now().isoformat(),
                "structured_data": {
                    "optimizer": {
                        "structured_fields": structured_fields,
                        "entities": entities[:24],
                    }
                },
            }
        ]
    
    async def _extract_candidate_urls(
        self, seed_urls: List[str], state_code: str, deadline: float
    ) -> List[str]:
        """Extract candidate rule URLs from seed pages via link extraction."""
        candidates = set()
        
        # Fetch seeds and extract links
        for seed_url in seed_urls:
            if time.monotonic() > deadline:
                break
            
            try:
                timeout = deadline - time.monotonic()
                if timeout <= 0:
                    break
                
                content, _ = await self._fetch_single_url(seed_url, timeout=timeout)
                if content:
                    # Extract links (simple regex-based)
                    links = self._extract_urls_from_html(content, seed_url)
                    ranked_links = await self._rank_candidate_urls(links, state_code=state_code)
                    for link in ranked_links[: self.config.max_urls_per_domain]:
                        candidates.add(link)
            
            except Exception as exc:
                logger.debug(f"Error extracting candidates from {seed_url}: {exc}")
        
        return list(candidates)
    
    def _extract_urls_from_html(self, html: str, base_url: str) -> List[str]:
        """Extract URLs from HTML content."""
        import re
        urls = []
        
        # Simple regex-based URL extraction
        url_pattern = re.compile(
            r'(?:href|src)=["\']([^"\']+)["\']', re.IGNORECASE
        )
        for match in url_pattern.finditer(html):
            url = match.group(1)
            # Resolve relative URLs
            if url.startswith("http"):
                urls.append(url)
            elif url.startswith("/"):
                urls.append(urljoin(base_url, url))
            elif url and not url.startswith(("#", "javascript:", "mailto:")):
                urls.append(urljoin(base_url, url))
        
        return list(dict.fromkeys(urls))
    
    async def _process_pdfs_if_available(
        self,
        state_code: str,
        candidate_urls: List[str],
        existing_rules: List[Dict[str, Any]],
        deadline: float,
    ) -> None:
        """Process PDF documents if available and enable_pdf_processing=True."""
        if not self.config.enable_pdf_processing:
            return

        seen_urls = {
            str(rule.get("url") or rule.get("source_url") or "").strip().lower()
            for rule in existing_rules
            if isinstance(rule, dict)
        }
        document_urls = []
        for candidate in list(candidate_urls or []):
            lowered = str(candidate or "").strip().lower()
            if not lowered:
                continue
            if lowered in seen_urls:
                continue
            if lowered.endswith(".pdf") or ".pdf?" in lowered or lowered.endswith(".rtf") or ".rtf?" in lowered:
                document_urls.append(str(candidate).strip())

        for document_url in document_urls:
            if len(existing_rules) >= self.config.max_fetch_per_state or time.monotonic() > deadline:
                break
            file_type = "pdf" if ".pdf" in document_url.lower() else "rtf"
            try:
                scraped = await asyncio.wait_for(
                    self._scrape_document_url(document_url, file_type=file_type),
                    timeout=max(1.0, min(self.config.pdf_extract_timeout, deadline - time.monotonic())),
                )
            except Exception as exc:
                logger.debug("Document processing failed for %s: %s", document_url, exc)
                continue
            rows = self._normalize_scraped_rule_rows(scraped=scraped, state_code=state_code, url=document_url)
            for row in rows:
                row_url = str(row.get("url") or row.get("source_url") or "").strip().lower()
                if not row_url or row_url in seen_urls:
                    continue
                existing_rules.append(row)
                seen_urls.add(row_url)
    
    async def _analyze_corpus_gaps(
        self,
        state_code: str,
        discovered_rules: List[Dict[str, Any]],
        candidate_urls: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Analyze gaps in corpus for the state."""
        candidate_urls = [str(item).strip() for item in list(candidate_urls or []) if str(item).strip()]
        document_candidates = [
            url for url in candidate_urls if url.lower().endswith(".pdf") or ".pdf?" in url.lower() or url.lower().endswith(".rtf") or ".rtf?" in url.lower()
        ]
        processed_document_rules = sum(
            1
            for rule in discovered_rules
            if self._document_format_from_url(rule.get("url") or rule.get("source_url")) in {"pdf", "rtf"}
        )
        visited_hosts = sorted(
            {
                str(urlparse(str(rule.get("url") or rule.get("source_url") or "")).netloc or "").strip().lower()
                for rule in discovered_rules
                if isinstance(rule, dict)
            }
        )
        candidate_hosts = sorted({str(urlparse(url).netloc or "").strip().lower() for url in candidate_urls if url})
        missing_hosts = [host for host in candidate_hosts if host and host not in visited_hosts]
        return {
            "gap_analysis_status": "completed",
            "discovered_count": len(discovered_rules),
            "candidate_count": len(candidate_urls),
            "document_candidate_count": len(document_candidates),
            "processed_document_rules": processed_document_rules,
            "missing_candidate_hosts": missing_hosts,
            "weak_coverage": len(discovered_rules) < max(2, min(4, self.config.max_fetch_per_state // 2)),
        }
    
    def _looks_like_admin_rule(self, text: str) -> bool:
        """Check if text looks like an administrative rule."""
        import re
        
        pattern = re.compile(
            r"administrative|admin\.?\s+code|regulation|agency\s+rule|oar\b|aac\b",
            re.IGNORECASE,
        )
        return bool(pattern.search(text))
    
    def _increment_method_count(self, result: StateDiscoveryResult, method: str) -> None:
        """Track method usage in discovery."""
        result.methods_used[method] = result.methods_used.get(method, 0) + 1
    
    async def _ensure_archiver_initialized(self) -> None:
        """Lazy-initialize ParallelWebArchiver if needed."""
        if self._archiver_initialized or self.parallel_archiver:
            return
        
        try:
            from ipfs_datasets_py.processors.legal_scrapers.parallel_web_archiver import (
                ParallelWebArchiver,
            )
            self.parallel_archiver = ParallelWebArchiver(max_concurrent=self.config.max_domain_workers_per_state)
            self._archiver_initialized = True
            logger.info("ParallelWebArchiver initialized")
        except ImportError:
            logger.warning("ParallelWebArchiver not available - using fallback")
            self._archiver_initialized = True

    async def _ensure_optimizer_initialized(self) -> None:
        if self._optimizer_initialized or self.scrape_optimizer is not None:
            return
        try:
            from ipfs_datasets_py.processors.web_archiving.agentic_scrape_optimizer import AgenticScrapeOptimizer

            self.scrape_optimizer = AgenticScrapeOptimizer()
        except Exception as exc:
            logger.debug("AgenticScrapeOptimizer unavailable: %s", exc)
            self.scrape_optimizer = None
        self._optimizer_initialized = True

    async def _rank_candidate_urls(self, urls: List[str], *, state_code: str) -> List[str]:
        deduped = list(dict.fromkeys([str(item).strip() for item in list(urls or []) if str(item).strip()]))
        if not deduped:
            return []
        await self._ensure_optimizer_initialized()
        if self.scrape_optimizer is None:
            return deduped
        try:
            ranked = self.scrape_optimizer.rank_links(
                [{"url": url, "text": urlparse(url).path} for url in deduped],
                [state_code, "administrative", "rules", "rule", "code", "pdf", "rtf"],
            )
            return [str(item.get("url") or "").strip() for item in ranked if str(item.get("url") or "").strip()]
        except Exception as exc:
            logger.debug("Candidate ranking failed for %s: %s", state_code, exc)
            return deduped

    async def _scrape_document_url(self, url: str, *, file_type: str) -> Optional[Any]:
        try:
            from ipfs_datasets_py.processors.legal_scrapers import state_admin_rules_scraper as _scraper_module
        except ImportError:
            try:
                from . import state_admin_rules_scraper as _scraper_module
            except Exception:
                return None

        if file_type == "pdf":
            return await _scraper_module._scrape_pdf_candidate_url_with_processor(url)
        return await _scraper_module._scrape_rtf_candidate_url_with_processor(url)

    def _normalize_scraped_rule_rows(self, *, scraped: Optional[Any], state_code: str, url: str) -> List[Dict[str, Any]]:
        if scraped is None:
            return []
        text = str(getattr(scraped, "text", "") or "").strip()
        if len(text) < self.config.min_rule_text_chars:
            return []
        title = str(getattr(scraped, "title", "") or text[:100]).strip()
        source_url = str(getattr(scraped, "source_url", "") or url).strip()
        method_used = str(getattr(scraped, "method_used", "") or "").strip()
        return [
            {
                "state_code": state_code,
                "url": source_url,
                "source_url": source_url,
                "title": title,
                "text": text,
                "full_text": text,
                "length": len(text),
                "domain": urlparse(source_url).netloc,
                "fetched_at": datetime.now().isoformat(),
                "method_used": method_used,
                "structured_data": {"method_used": method_used},
            }
        ]

    @staticmethod
    def _document_format_from_url(value: Any) -> str:
        lowered = str(value or "").strip().lower()
        if lowered.endswith(".pdf") or ".pdf?" in lowered:
            return "pdf"
        if lowered.endswith(".rtf") or ".rtf?" in lowered:
            return "rtf"
        return "html"


async def discover_multi_state_rules_parallel(
    states: List[str],
    seed_urls_by_state: Dict[str, List[str]],
    config: Optional[ParallelStateDiscoveryConfig] = None,
) -> Dict[str, StateDiscoveryResult]:
    """Convenience function for discovering rules across multiple states in parallel."""
    orchestrator = ParallelStateAdminOrchestrator(config=config)
    return await orchestrator.discover_state_rules_parallel(
        states=states,
        seed_urls_by_state=seed_urls_by_state,
    )
