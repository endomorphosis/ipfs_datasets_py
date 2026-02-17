"""
Enhanced Citation Extraction for Search Results.

This module extends the base CitationExtractor to work with search results,
providing citation-based ranking, network building, and export capabilities.

Features:
- Citation detection in search result titles and snippets
- Citation-based result ranking and scoring
- Citation network builder for finding related documents
- Citation validation against knowledge base
- "Find similar by citations" feature
- Export formats (BibTeX, RIS, JSON)
- Integration with ResultFilter

Usage:
    from ipfs_datasets_py.processors.legal_scrapers import SearchResultCitationExtractor
    
    extractor = SearchResultCitationExtractor()
    results_with_citations = extractor.extract_from_results(search_results)
    ranked = extractor.rank_by_citations(results_with_citations)
    network = extractor.build_citation_network(results_with_citations)
"""

import json
import logging
from typing import List, Dict, Optional, Set, Any, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict, Counter

from .citation_extraction import CitationExtractor, Citation

logger = logging.getLogger(__name__)


@dataclass
class SearchResultWithCitations:
    """Search result with extracted citations."""
    title: str
    url: str
    snippet: str
    domain: Optional[str] = None
    citations: List[Citation] = field(default_factory=list)
    citation_count: int = 0
    citation_score: float = 0.0
    cited_by_count: int = 0  # How many other results cite this
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CitationNetwork:
    """Network of citation relationships between search results."""
    nodes: List[Dict[str, Any]] = field(default_factory=list)  # Results as nodes
    edges: List[Dict[str, Any]] = field(default_factory=list)  # Citations as edges
    citation_graph: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    reverse_citation_graph: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    
    def get_connected_results(self, url: str, max_depth: int = 2) -> List[str]:
        """Get all results connected to a given result within max_depth."""
        if url not in self.citation_graph:
            return []
        
        connected = set()
        current_level = {url}
        visited = set()
        
        for _ in range(max_depth):
            next_level = set()
            for node in current_level:
                if node in visited:
                    continue
                visited.add(node)
                
                # Add direct citations
                if node in self.citation_graph:
                    next_level.update(self.citation_graph[node])
                
                # Add reverse citations (cited by)
                if node in self.reverse_citation_graph:
                    next_level.update(self.reverse_citation_graph[node])
            
            connected.update(next_level)
            current_level = next_level
        
        return list(connected - {url})


class SearchResultCitationExtractor(CitationExtractor):
    """
    Enhanced citation extractor for search results.
    
    Extends the base CitationExtractor to work with search results, providing:
    - Citation detection in titles and snippets
    - Citation-based ranking and scoring
    - Citation network building
    - Citation validation
    - Similar document finding by citations
    - Export to BibTeX, RIS, JSON formats
    
    Example:
        >>> extractor = SearchResultCitationExtractor()
        >>> results = extractor.extract_from_results(search_results)
        >>> ranked = extractor.rank_by_citations(results)
        >>> network = extractor.build_citation_network(results)
        >>> similar = extractor.find_similar_by_citations(results[0], results)
    """
    
    def __init__(self, knowledge_base: Optional[Any] = None):
        """Initialize search result citation extractor.
        
        Args:
            knowledge_base: Optional knowledge base for citation validation
        """
        super().__init__()
        self.knowledge_base = knowledge_base
        
        # Citation importance weights for ranking
        self.citation_weights = {
            "case": 1.0,  # Case law citations are most important
            "statute": 0.9,  # Statutes
            "regulation": 0.8,  # Regulations
            "cfr": 0.7,  # CFR
            "usc": 0.9,  # USC
            "federal_register": 0.6,  # Federal Register
        }
    
    def extract_from_results(
        self,
        results: List[Dict[str, Any]],
        extract_from_title: bool = True,
        extract_from_snippet: bool = True
    ) -> List[SearchResultWithCitations]:
        """
        Extract citations from search results.
        
        Args:
            results: List of search result dictionaries
            extract_from_title: Whether to extract from titles
            extract_from_snippet: Whether to extract from snippets
            
        Returns:
            List of SearchResultWithCitations with extracted citations
        """
        results_with_citations = []
        
        for result in results:
            title = result.get("title", "")
            snippet = result.get("snippet", result.get("description", ""))
            url = result.get("url", "")
            domain = result.get("domain")
            
            # Extract citations
            citations = []
            
            if extract_from_title and title:
                title_citations = self.extract_citations(title)
                for cit in title_citations:
                    cit.metadata = {"source": "title"}
                citations.extend(title_citations)
            
            if extract_from_snippet and snippet:
                snippet_citations = self.extract_citations(snippet)
                for cit in snippet_citations:
                    cit.metadata = {"source": "snippet"}
                citations.extend(snippet_citations)
            
            # Remove duplicate citations
            unique_citations = self._deduplicate_citations(citations)
            
            # Calculate citation score
            citation_score = self._calculate_citation_score(unique_citations)
            
            result_with_cit = SearchResultWithCitations(
                title=title,
                url=url,
                snippet=snippet,
                domain=domain,
                citations=unique_citations,
                citation_count=len(unique_citations),
                citation_score=citation_score,
                metadata=result.get("metadata", {})
            )
            
            results_with_citations.append(result_with_cit)
        
        # Calculate cited_by_count (how many other results cite each result)
        self._calculate_cited_by_counts(results_with_citations)
        
        logger.info(f"Extracted citations from {len(results_with_citations)} results")
        
        return results_with_citations
    
    def _deduplicate_citations(self, citations: List[Citation]) -> List[Citation]:
        """Remove duplicate citations based on text."""
        seen = set()
        unique = []
        
        for cit in citations:
            key = (cit.type, cit.text.lower().strip())
            if key not in seen:
                seen.add(key)
                unique.append(cit)
        
        return unique
    
    def _calculate_citation_score(self, citations: List[Citation]) -> float:
        """Calculate citation score based on citation types and importance."""
        if not citations:
            return 0.0
        
        total_weight = sum(
            self.citation_weights.get(cit.type, 0.5)
            for cit in citations
        )
        
        # Normalize by number of citations
        return min(total_weight / max(len(citations), 1), 1.0)
    
    def _calculate_cited_by_counts(self, results: List[SearchResultWithCitations]):
        """Calculate how many other results cite each result."""
        # Build URL to result mapping
        url_map = {r.url: r for r in results}
        
        # Count citations between results
        for result in results:
            for citation in result.citations:
                # Check if citation URL matches any result
                if citation.url and citation.url in url_map:
                    url_map[citation.url].cited_by_count += 1
    
    def rank_by_citations(
        self,
        results: List[SearchResultWithCitations],
        weight_citation_count: float = 0.4,
        weight_citation_score: float = 0.3,
        weight_cited_by: float = 0.3
    ) -> List[SearchResultWithCitations]:
        """
        Rank results by citation metrics.
        
        Args:
            results: Results to rank
            weight_citation_count: Weight for number of citations (outgoing)
            weight_citation_score: Weight for quality of citations
            weight_cited_by: Weight for being cited by others (incoming)
            
        Returns:
            Sorted list of results (highest rank first)
        """
        if not results:
            return []
        
        # Normalize metrics
        max_count = max((r.citation_count for r in results), default=1)
        max_cited_by = max((r.cited_by_count for r in results), default=1)
        
        # Calculate ranks
        for result in results:
            count_norm = result.citation_count / max_count if max_count > 0 else 0
            score_norm = result.citation_score
            cited_by_norm = result.cited_by_count / max_cited_by if max_cited_by > 0 else 0
            
            result.metadata["citation_rank"] = (
                count_norm * weight_citation_count +
                score_norm * weight_citation_score +
                cited_by_norm * weight_cited_by
            )
        
        # Sort by rank (descending)
        sorted_results = sorted(
            results,
            key=lambda r: r.metadata.get("citation_rank", 0),
            reverse=True
        )
        
        logger.info(f"Ranked {len(sorted_results)} results by citations")
        
        return sorted_results
    
    def build_citation_network(
        self,
        results: List[SearchResultWithCitations]
    ) -> CitationNetwork:
        """
        Build citation network from search results.
        
        Args:
            results: Results with citations
            
        Returns:
            CitationNetwork with nodes and edges
        """
        network = CitationNetwork()
        
        # Create nodes from results
        for i, result in enumerate(results):
            node = {
                "id": i,
                "url": result.url,
                "title": result.title,
                "citation_count": result.citation_count,
                "cited_by_count": result.cited_by_count,
                "citation_score": result.citation_score
            }
            network.nodes.append(node)
        
        # Build URL to index mapping
        url_to_idx = {r.url: i for i, r in enumerate(results)}
        
        # Create edges from citations
        for i, result in enumerate(results):
            for citation in result.citations:
                # If citation points to another result in our set
                if citation.url and citation.url in url_to_idx:
                    target_idx = url_to_idx[citation.url]
                    
                    edge = {
                        "source": i,
                        "target": target_idx,
                        "citation_type": citation.type,
                        "citation_text": citation.text
                    }
                    network.edges.append(edge)
                    
                    # Update graphs
                    network.citation_graph[result.url].add(citation.url)
                    network.reverse_citation_graph[citation.url].add(result.url)
        
        logger.info(f"Built citation network: {len(network.nodes)} nodes, {len(network.edges)} edges")
        
        return network
    
    def find_similar_by_citations(
        self,
        target_result: SearchResultWithCitations,
        all_results: List[SearchResultWithCitations],
        min_common_citations: int = 2
    ) -> List[Tuple[SearchResultWithCitations, int, float]]:
        """
        Find similar results based on shared citations.
        
        Args:
            target_result: Result to find similar results for
            all_results: All results to compare against
            min_common_citations: Minimum number of shared citations
            
        Returns:
            List of (result, common_count, similarity_score) tuples
        """
        target_citations = set(
            (c.type, c.text.lower().strip())
            for c in target_result.citations
        )
        
        if not target_citations:
            return []
        
        similar_results = []
        
        for result in all_results:
            if result.url == target_result.url:
                continue
            
            result_citations = set(
                (c.type, c.text.lower().strip())
                for c in result.citations
            )
            
            # Calculate shared citations
            common = target_citations & result_citations
            common_count = len(common)
            
            if common_count >= min_common_citations:
                # Calculate Jaccard similarity
                union = target_citations | result_citations
                similarity = common_count / len(union) if union else 0
                
                similar_results.append((result, common_count, similarity))
        
        # Sort by similarity (descending)
        similar_results.sort(key=lambda x: (x[2], x[1]), reverse=True)
        
        logger.info(f"Found {len(similar_results)} similar results")
        
        return similar_results
    
    def validate_citations(
        self,
        results: List[SearchResultWithCitations]
    ) -> Dict[str, Any]:
        """
        Validate citations against knowledge base.
        
        Args:
            results: Results with citations to validate
            
        Returns:
            Validation report with statistics
        """
        if not self.knowledge_base:
            logger.warning("No knowledge base provided for validation")
            return {"status": "skipped", "reason": "no_knowledge_base"}
        
        total_citations = 0
        validated = 0
        invalid = 0
        
        for result in results:
            for citation in result.citations:
                total_citations += 1
                
                # Validate citation (placeholder - depends on knowledge base structure)
                is_valid = self._validate_single_citation(citation)
                
                if is_valid:
                    validated += 1
                    citation.metadata = citation.metadata or {}
                    citation.metadata["validated"] = True
                else:
                    invalid += 1
        
        report = {
            "total_citations": total_citations,
            "validated": validated,
            "invalid": invalid,
            "validation_rate": validated / total_citations if total_citations > 0 else 0
        }
        
        logger.info(f"Citation validation: {validated}/{total_citations} validated")
        
        return report
    
    def _validate_single_citation(self, citation: Citation) -> bool:
        """Validate a single citation (placeholder implementation)."""
        # This would validate against the knowledge base
        # For now, just check if citation has required fields
        if citation.type == "case":
            return bool(citation.volume and citation.reporter and citation.page)
        elif citation.type in ("usc", "cfr"):
            return bool(citation.title and citation.section)
        else:
            return True
    
    def export_bibtex(
        self,
        results: List[SearchResultWithCitations],
        include_citations: bool = True
    ) -> str:
        """
        Export results to BibTeX format.
        
        Args:
            results: Results to export
            include_citations: Whether to include extracted citations
            
        Returns:
            BibTeX formatted string
        """
        bibtex_entries = []
        
        for i, result in enumerate(results):
            # Main result entry
            entry_id = f"result{i+1}"
            entry = f"@misc{{{entry_id},\n"
            entry += f"  title = {{{result.title}}},\n"
            entry += f"  url = {{{result.url}}},\n"
            if result.domain:
                entry += f"  howpublished = {{{result.domain}}},\n"
            entry += "}\n"
            
            bibtex_entries.append(entry)
            
            # Include citations if requested
            if include_citations:
                for j, cit in enumerate(result.citations):
                    cit_entry = self._citation_to_bibtex(cit, f"{entry_id}_cite{j+1}")
                    if cit_entry:
                        bibtex_entries.append(cit_entry)
        
        return "\n".join(bibtex_entries)
    
    def _citation_to_bibtex(self, citation: Citation, entry_id: str) -> str:
        """Convert citation to BibTeX entry."""
        if citation.type == "case":
            entry = f"@misc{{{entry_id},\n"
            entry += f"  title = {{{citation.text}}},\n"
            if citation.volume:
                entry += f"  volume = {{{citation.volume}}},\n"
            if citation.reporter:
                entry += f"  series = {{{citation.reporter}}},\n"
            if citation.page:
                entry += f"  pages = {{{citation.page}}},\n"
            if citation.year:
                entry += f"  year = {{{citation.year}}},\n"
            entry += "}\n"
            return entry
        
        # Add support for other types as needed
        return ""
    
    def export_ris(
        self,
        results: List[SearchResultWithCitations]
    ) -> str:
        """
        Export results to RIS format.
        
        Args:
            results: Results to export
            
        Returns:
            RIS formatted string
        """
        ris_entries = []
        
        for result in results:
            entry = "TY  - ELEC\n"  # Electronic source
            entry += f"TI  - {result.title}\n"
            entry += f"UR  - {result.url}\n"
            if result.snippet:
                entry += f"AB  - {result.snippet}\n"
            entry += "ER  - \n\n"
            
            ris_entries.append(entry)
        
        return "".join(ris_entries)
    
    def export_json(
        self,
        results: List[SearchResultWithCitations],
        include_citations: bool = True,
        pretty: bool = True
    ) -> str:
        """
        Export results to JSON format.
        
        Args:
            results: Results to export
            include_citations: Whether to include extracted citations
            pretty: Whether to pretty-print JSON
            
        Returns:
            JSON formatted string
        """
        data = []
        
        for result in results:
            result_dict = {
                "title": result.title,
                "url": result.url,
                "snippet": result.snippet,
                "domain": result.domain,
                "citation_count": result.citation_count,
                "citation_score": result.citation_score,
                "cited_by_count": result.cited_by_count
            }
            
            if include_citations:
                result_dict["citations"] = [
                    {
                        "type": c.type,
                        "text": c.text,
                        "volume": c.volume,
                        "reporter": c.reporter,
                        "page": c.page,
                        "year": c.year,
                        "title": c.title,
                        "section": c.section,
                        "url": c.url
                    }
                    for c in result.citations
                ]
            
            data.append(result_dict)
        
        if pretty:
            return json.dumps(data, indent=2)
        else:
            return json.dumps(data)
