"""Legal Web Archive Search - Unified Interface for Legal Content Discovery.

This module integrates Brave Legal Search with web archiving capabilities,
enabling comprehensive legal content discovery across:
- Current web content (via Brave Search API)
- Archived legal documents (via Common Crawl, Wayback Machine)
- Historical regulations and rules
- Preserved .gov websites

The unified interface provides:
- Natural language query processing
- Multi-source search (live + archived)
- Automatic archiving of important results
- Historical content comparison
- Jurisdiction and entity-aware archiving

Example:
    >>> from ipfs_datasets_py.processors.legal_scrapers import LegalWebArchiveSearch
    >>> 
    >>> # Search with archiving
    >>> searcher = LegalWebArchiveSearch()
    >>> results = searcher.search(
    ...     "EPA water pollution regulations California",
    ...     include_archives=True,
    ...     archive_results=True
    ... )
    >>> 
    >>> # Search historical content only
    >>> historical = searcher.search_archives(
    ...     "California housing laws",
    ...     from_date="2020-01-01",
    ...     to_date="2023-12-31"
    ... )
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Import Brave Legal Search components
try:
    from .brave_legal_search import BraveLegalSearch
    from .query_processor import QueryProcessor
    HAVE_LEGAL_SEARCH = True
except ImportError:
    HAVE_LEGAL_SEARCH = False
    logger.warning("Brave Legal Search not available")

# Import web archiving components
try:
    from ipfs_datasets_py.web_archiving.web_archive import WebArchive
    HAVE_WEB_ARCHIVE = True
except ImportError:
    HAVE_WEB_ARCHIVE = False
    logger.warning("Web archiving not available")

# Import Common Crawl search
try:
    from ipfs_datasets_py.mcp_server.tools.web_archive_tools.common_crawl_search import search_common_crawl
    HAVE_COMMON_CRAWL = True
except ImportError:
    HAVE_COMMON_CRAWL = False
    logger.warning("Common Crawl search not available")

# Import Common Crawl Index Loader (HuggingFace integration)
try:
    from .common_crawl_index_loader import CommonCrawlIndexLoader
    HAVE_INDEX_LOADER = True
except ImportError:
    HAVE_INDEX_LOADER = False
    logger.warning("Common Crawl Index Loader not available")


class LegalWebArchiveSearch:
    """Unified search interface combining legal search with web archiving.
    
    This class provides a comprehensive search solution that:
    1. Searches current legal content via Brave Search API
    2. Searches archived legal documents via Common Crawl
    3. Optionally archives important search results
    4. Provides historical content comparison
    
    Attributes:
        legal_searcher: BraveLegalSearch instance for current content
        web_archive: WebArchive instance for archiving results
        query_processor: QueryProcessor for understanding queries
        archive_enabled: Whether to archive results automatically
    
    Example:
        >>> searcher = LegalWebArchiveSearch(
        ...     archive_dir="/path/to/archives",
        ...     auto_archive=True
        ... )
        >>> results = searcher.unified_search("OSHA workplace safety")
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        knowledge_base_dir: Optional[str] = None,
        archive_dir: Optional[str] = None,
        auto_archive: bool = False,
        index_local_dir: Optional[str] = None,
        use_hf_indexes: bool = True
    ):
        """Initialize the unified legal web archive search.
        
        Args:
            api_key: Brave Search API key (or set BRAVE_API_KEY env var)
            knowledge_base_dir: Directory containing legal entity JSONL files
            archive_dir: Directory for storing archived results
            auto_archive: Whether to automatically archive search results
            index_local_dir: Local directory for Common Crawl indexes (checked first)
            use_hf_indexes: Whether to fall back to HuggingFace indexes if local not found
        """
        # Initialize Brave Legal Search
        if HAVE_LEGAL_SEARCH:
            self.legal_searcher = BraveLegalSearch(
                api_key=api_key,
                knowledge_base_dir=knowledge_base_dir
            )
            self.query_processor = QueryProcessor()
        else:
            self.legal_searcher = None
            self.query_processor = None
            logger.error("Brave Legal Search not available - unified search disabled")
        
        # Initialize web archiving
        if HAVE_WEB_ARCHIVE and archive_dir:
            self.web_archive = WebArchive(storage_path=archive_dir)
            self.archive_enabled = True
        else:
            self.web_archive = None
            self.archive_enabled = False
        
        # Initialize Common Crawl Index Loader (HuggingFace integration)
        if HAVE_INDEX_LOADER and use_hf_indexes:
            self.index_loader = CommonCrawlIndexLoader(
                local_base_dir=index_local_dir,
                use_hf_fallback=True
            )
            self.use_indexes = True
            logger.info("Common Crawl Index Loader initialized with HuggingFace fallback")
        else:
            self.index_loader = None
            self.use_indexes = False
            if use_hf_indexes:
                logger.warning("Common Crawl indexes not available")
        
        self.auto_archive = auto_archive
        self.archive_dir = archive_dir
    
    def unified_search(
        self,
        query: str,
        max_results: int = 20,
        include_archives: bool = False,
        archive_results: bool = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Perform unified search across current and archived legal content.
        
        This method combines live Brave Search results with archived content
        to provide comprehensive legal information discovery.
        
        Args:
            query: Natural language query about legal rules/regulations
            max_results: Maximum number of results to return
            include_archives: Whether to include archived content in results
            archive_results: Whether to archive the results (overrides auto_archive)
            **kwargs: Additional arguments passed to search methods
            
        Returns:
            Dict containing:
                - current_results: Results from Brave Search
                - archived_results: Results from web archives (if included)
                - combined_results: Merged and deduplicated results
                - query_intent: Parsed query information
                - archive_info: Information about archived items
        """
        if not self.legal_searcher:
            return {
                'status': 'error',
                'error': 'Legal search not available'
            }
        
        logger.info(f"Unified search for: {query}")
        
        # Parse query intent
        intent = self.query_processor.process(query) if self.query_processor else None
        
        # Search current content via Brave
        current_results = self.legal_searcher.search(
            query=query,
            max_results=max_results,
            **kwargs
        )
        
        archived_results = None
        if include_archives and HAVE_COMMON_CRAWL:
            # Extract domains for archive search
            domains = self._extract_domains_from_intent(intent) if intent else ['.gov']
            archived_results = self._search_archives_multi_domain(
                query=query,
                domains=domains,
                max_results_per_domain=max_results // len(domains) if domains else max_results
            )
        
        # Optionally archive results
        should_archive = archive_results if archive_results is not None else self.auto_archive
        archive_info = None
        if should_archive and self.archive_enabled and current_results.get('results'):
            archive_info = self._archive_search_results(
                query=query,
                results=current_results['results'],
                intent=intent
            )
        
        # Combine results
        combined_results = self._merge_results(
            current_results.get('results', []),
            archived_results.get('results', []) if archived_results else []
        )
        
        return {
            'status': 'success',
            'query': query,
            'query_intent': intent.__dict__ if intent else None,
            'current_results': current_results.get('results', []),
            'archived_results': archived_results.get('results', []) if archived_results else [],
            'combined_results': combined_results,
            'total_current': len(current_results.get('results', [])),
            'total_archived': len(archived_results.get('results', [])) if archived_results else 0,
            'total_combined': len(combined_results),
            'archive_info': archive_info,
            'metadata': {
                'timestamp': datetime.now().isoformat(),
                'search_sources': ['brave'] + (['common_crawl'] if include_archives else []),
                'auto_archived': should_archive and self.archive_enabled
            }
        }
    
    def search_archives(
        self,
        query: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        domains: Optional[List[str]] = None,
        max_results: int = 50
    ) -> Dict[str, Any]:
        """Search only archived legal content.
        
        This method searches Common Crawl and other web archives for
        historical legal documents and regulations.
        
        Args:
            query: Natural language query
            from_date: Start date (YYYY-MM-DD format)
            to_date: End date (YYYY-MM-DD format)
            domains: List of domains to search (defaults to .gov domains)
            max_results: Maximum results to return
            
        Returns:
            Dict with archived search results
        """
        if not HAVE_COMMON_CRAWL:
            return {
                'status': 'error',
                'error': 'Common Crawl search not available'
            }
        
        # Parse query to extract relevant domains if not provided
        if domains is None and self.query_processor:
            intent = self.query_processor.process(query)
            domains = self._extract_domains_from_intent(intent)
        
        if not domains:
            domains = ['.gov']  # Default to government domains
        
        # Convert dates to timestamp format if provided
        from_ts = None
        to_ts = None
        if from_date:
            from_ts = datetime.fromisoformat(from_date).strftime('%Y%m%d')
        if to_date:
            to_ts = datetime.fromisoformat(to_date).strftime('%Y%m%d')
        
        # Search archives
        results = self._search_archives_multi_domain(
            query=query,
            domains=domains,
            from_timestamp=from_ts,
            to_timestamp=to_ts,
            max_results_per_domain=max_results // len(domains)
        )
        
        return results
    
    def _extract_domains_from_intent(self, intent) -> List[str]:
        """Extract relevant .gov domains from query intent.
        
        Args:
            intent: QueryIntent object
            
        Returns:
            List of domain patterns to search
        """
        domains = []
        
        # Federal domains
        if 'federal' in intent.jurisdictions or intent.agencies:
            # Add federal agency domains based on agencies mentioned
            if intent.agencies:
                # Map agencies to their domains
                agency_domains = {
                    'Environmental Protection Agency': 'epa.gov',
                    'Food and Drug Administration': 'fda.gov',
                    'Federal Trade Commission': 'ftc.gov',
                    'Securities and Exchange Commission': 'sec.gov',
                    'Department of Justice': 'justice.gov',
                    'Department of Housing and Urban Development': 'hud.gov',
                }
                for agency in intent.agencies:
                    if agency in agency_domains:
                        domains.append(agency_domains[agency])
            
            # Add general federal domains
            if not domains:
                domains.extend(['epa.gov', 'regulations.gov', 'govinfo.gov'])
        
        # State domains
        state_jurisdictions = [j for j in intent.jurisdictions if j != 'federal' and len(j) == 2]
        for state_code in state_jurisdictions:
            # Most states use .state.<code>.us or .<code>.gov patterns
            domains.extend([
                f'.state.{state_code.lower()}.us',
                f'.{state_code.lower()}.gov'
            ])
        
        # Default to all .gov if no specific domains found
        if not domains:
            domains = ['.gov']
        
        return domains
    
    async def _search_archives_multi_domain(
        self,
        query: str,
        domains: List[str],
        from_timestamp: Optional[str] = None,
        to_timestamp: Optional[str] = None,
        max_results_per_domain: int = 20
    ) -> Dict[str, Any]:
        """Search multiple domains in Common Crawl archives.
        
        Args:
            query: Search query
            domains: List of domain patterns
            from_timestamp: Start timestamp (YYYYMMDD)
            to_timestamp: End timestamp (YYYYMMDD)
            max_results_per_domain: Max results per domain
            
        Returns:
            Dict with combined archive search results
        """
        all_results = []
        
        for domain in domains:
            try:
                result = await search_common_crawl(
                    domain=domain,
                    limit=max_results_per_domain,
                    from_timestamp=from_timestamp,
                    to_timestamp=to_timestamp
                )
                
                if result.get('status') == 'success':
                    # Add domain context to each result
                    for record in result.get('results', []):
                        record['search_domain'] = domain
                        record['source'] = 'common_crawl'
                    
                    all_results.extend(result.get('results', []))
                
            except Exception as e:
                logger.warning(f"Error searching domain {domain}: {e}")
        
        return {
            'status': 'success',
            'results': all_results,
            'count': len(all_results),
            'domains_searched': domains,
            'timestamp': datetime.now().isoformat()
        }
    
    def _merge_results(
        self,
        current_results: List[Dict],
        archived_results: List[Dict]
    ) -> List[Dict]:
        """Merge and deduplicate current and archived results.
        
        Args:
            current_results: Results from Brave Search
            archived_results: Results from archives
            
        Returns:
            Combined and deduplicated list of results
        """
        seen_urls = set()
        merged = []
        
        # Add current results first (higher priority)
        for result in current_results:
            url = result.get('url', '')
            if url and url not in seen_urls:
                result['source_type'] = 'current'
                merged.append(result)
                seen_urls.add(url)
        
        # Add archived results
        for result in archived_results:
            url = result.get('url', '')
            if url and url not in seen_urls:
                result['source_type'] = 'archived'
                merged.append(result)
                seen_urls.add(url)
        
        return merged
    
    def _archive_search_results(
        self,
        query: str,
        results: List[Dict],
        intent: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Archive important search results for future reference.
        
        Args:
            query: Original search query
            results: List of search results to archive
            intent: Parsed query intent
            
        Returns:
            Dict with archiving information
        """
        if not self.web_archive:
            return {'status': 'disabled', 'message': 'Web archiving not configured'}
        
        archived_items = []
        
        # Archive top results and .gov sites
        for result in results[:10]:  # Archive top 10
            url = result.get('url', '')
            if url and '.gov' in url:  # Prioritize .gov sites
                try:
                    archive_result = self.web_archive.archive_url(
                        url=url,
                        metadata={
                            'query': query,
                            'intent': intent.__dict__ if intent else None,
                            'title': result.get('title', ''),
                            'relevance_score': result.get('relevance_score', 0),
                            'archived_at': datetime.now().isoformat()
                        }
                    )
                    archived_items.append({
                        'url': url,
                        'archive_id': archive_result.get('archive_id'),
                        'status': archive_result.get('status')
                    })
                except Exception as e:
                    logger.warning(f"Failed to archive {url}: {e}")
        
        return {
            'status': 'success',
            'archived_count': len(archived_items),
            'archived_items': archived_items,
            'timestamp': datetime.now().isoformat()
        }
    
    def get_archive_stats(self) -> Dict[str, Any]:
        """Get statistics about archived content.
        
        Returns:
            Dict with archive statistics
        """
        if not self.web_archive:
            return {'status': 'disabled', 'message': 'Web archiving not configured'}
        
        return {
            'status': 'enabled',
            'archive_dir': self.archive_dir,
            'auto_archive': self.auto_archive,
            'archived_items_count': len(self.web_archive.archived_items),
            'storage_path': self.web_archive.storage_path
        }
    
    def search_with_indexes(
        self,
        query: str,
        jurisdiction_type: Optional[str] = None,
        state_code: Optional[str] = None,
        max_results: int = 50
    ) -> Dict[str, Any]:
        """Search using pre-loaded Common Crawl indexes for faster lookups.
        
        This method uses the HuggingFace-hosted Common Crawl indexes to perform
        faster searches without hitting the API. Indexes are checked locally first,
        then downloaded from HuggingFace if needed.
        
        Args:
            query: Natural language query
            jurisdiction_type: Type of jurisdiction ("federal", "state", "municipal")
            state_code: Optional 2-letter state code for state searches (e.g., "CA")
            max_results: Maximum results to return
            
        Returns:
            Dict with search results from indexes
            
        Example:
            >>> searcher = LegalWebArchiveSearch()
            >>> # Search federal indexes
            >>> results = searcher.search_with_indexes(
            ...     "EPA water regulations",
            ...     jurisdiction_type="federal"
            ... )
            >>> # Search California state indexes
            >>> ca_results = searcher.search_with_indexes(
            ...     "housing laws",
            ...     jurisdiction_type="state",
            ...     state_code="CA"
            ... )
        """
        if not self.use_indexes or not self.index_loader:
            return {
                'status': 'error',
                'error': 'Common Crawl indexes not available. Set use_hf_indexes=True'
            }
        
        # Parse query to understand intent
        intent = None
        if self.query_processor:
            intent = self.query_processor.process(query)
            
            # Auto-detect jurisdiction type if not specified
            if not jurisdiction_type and intent:
                if 'federal' in intent.jurisdictions or intent.agencies:
                    jurisdiction_type = 'federal'
                elif intent.jurisdictions:
                    jurisdiction_type = 'state'
                    # Try to extract state code
                    if not state_code:
                        for jurisdiction in intent.jurisdictions:
                            if len(jurisdiction) == 2:  # State code
                                state_code = jurisdiction
                                break
        
        # Default to federal if not specified
        if not jurisdiction_type:
            jurisdiction_type = 'federal'
        
        try:
            # Load appropriate index
            index_data = None
            if jurisdiction_type == 'federal':
                logger.info("Loading federal Common Crawl index (local first, HF fallback)...")
                index_data = self.index_loader.load_federal_index()
            elif jurisdiction_type == 'state':
                if state_code:
                    logger.info(f"Loading {state_code} state Common Crawl index (local first, HF fallback)...")
                else:
                    logger.info("Loading state Common Crawl index (local first, HF fallback)...")
                index_data = self.index_loader.load_state_index(state_code=state_code)
            elif jurisdiction_type == 'municipal':
                logger.info("Loading municipal Common Crawl index (local first, HF fallback)...")
                index_data = self.index_loader.load_municipal_index()
            
            if index_data is None:
                return {
                    'status': 'error',
                    'error': f'Failed to load {jurisdiction_type} index. May still be uploading to HuggingFace.'
                }
            
            # Search within the index
            results = self._search_within_index(
                index_data,
                query,
                intent,
                max_results
            )
            
            return {
                'status': 'success',
                'query': query,
                'query_intent': intent.__dict__ if intent else None,
                'jurisdiction_type': jurisdiction_type,
                'state_code': state_code,
                'results': results,
                'total_results': len(results),
                'source': 'common_crawl_indexes',
                'metadata': {
                    'timestamp': datetime.now().isoformat(),
                    'index_type': jurisdiction_type,
                    'used_local_index': self.index_loader._check_local_index(jurisdiction_type) is not None
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to search with indexes: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def _search_within_index(
        self,
        index_data: Any,
        query: str,
        intent: Optional[Any],
        max_results: int
    ) -> List[Dict[str, Any]]:
        """Search within a loaded index for relevant URLs.
        
        Args:
            index_data: Loaded index (DataFrame or HF Dataset)
            query: Search query
            intent: Parsed query intent
            max_results: Maximum results to return
            
        Returns:
            List of matching records from the index
        """
        try:
            import pandas as pd
            
            # Convert to DataFrame if needed
            if hasattr(index_data, 'to_pandas'):
                df = index_data.to_pandas()
            elif isinstance(index_data, pd.DataFrame):
                df = index_data
            else:
                logger.error(f"Unsupported index data type: {type(index_data)}")
                return []
            
            # Extract search terms from query
            search_terms = query.lower().split()
            if intent and intent.topics:
                search_terms.extend([t.lower() for t in intent.topics])
            
            # Search in URL and title fields
            if 'url' not in df.columns:
                logger.error("Index missing 'url' column")
                return []
            
            # Build search mask
            mask = pd.Series([False] * len(df))
            for term in search_terms:
                if 'url' in df.columns:
                    mask |= df['url'].str.contains(term, case=False, na=False)
                if 'title' in df.columns:
                    mask |= df['title'].str.contains(term, case=False, na=False)
                if 'content' in df.columns:
                    mask |= df['content'].str.contains(term, case=False, na=False)
            
            # Get matching records
            matches = df[mask].head(max_results)
            
            # Convert to list of dicts
            results = []
            for _, row in matches.iterrows():
                result = {
                    'url': row.get('url', ''),
                    'title': row.get('title', ''),
                    'timestamp': row.get('timestamp', ''),
                    'mime_type': row.get('mime_type', ''),
                }
                
                # Add optional fields if present
                if 'warc_filename' in row:
                    result['warc_filename'] = row['warc_filename']
                if 'warc_offset' in row:
                    result['warc_offset'] = row['warc_offset']
                if 'digest' in row:
                    result['digest'] = row['digest']
                    
                results.append(result)
            
            logger.info(f"Found {len(results)} matches in index")
            return results
            
        except Exception as e:
            logger.error(f"Error searching within index: {e}")
            return []
    
    def get_index_info(self) -> Dict[str, Any]:
        """Get information about available Common Crawl indexes.
        
        Returns:
            Dict with index availability and statistics
        """
        if not self.use_indexes or not self.index_loader:
            return {
                'status': 'disabled',
                'message': 'Common Crawl indexes not enabled'
            }
        
        return self.index_loader.get_index_info()
