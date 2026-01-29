"""Citation extraction and linking for legal documents.

This module provides comprehensive citation extraction capabilities for legal texts,
including case law, statutes, regulations, and cross-references.
"""
import re
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Citation:
    """Represents a legal citation."""
    type: str  # "case", "statute", "regulation", "cfr", "usc", "federal_register"
    text: str  # Full citation text as it appears
    reporter: Optional[str] = None  # e.g., "F.3d", "U.S."
    volume: Optional[str] = None
    page: Optional[str] = None
    year: Optional[str] = None
    title: Optional[str] = None  # For statutes/regulations
    section: Optional[str] = None
    court: Optional[str] = None
    url: Optional[str] = None  # Link to source if available
    start_pos: int = 0  # Character position in source text
    end_pos: int = 0


# Citation patterns
CASE_CITATION_PATTERNS = [
    # Federal reporters: e.g., "123 F.3d 456"
    r'(\d+)\s+(F\.\s?(?:2d|3d|4th|App\'?x?))\s+(\d+)',
    # U.S. Reports: e.g., "123 U.S. 456"
    r'(\d+)\s+(U\.S\.)\s+(\d+)',
    # Supreme Court: e.g., "123 S.Ct. 456"
    r'(\d+)\s+(S\.?\s?Ct\.)\s+(\d+)',
    # Federal Supplement: e.g., "123 F.Supp.2d 456"
    r'(\d+)\s+(F\.?\s?Supp\.?\s?(?:2d|3d)?)\s+(\d+)',
]

USC_CITATION_PATTERNS = [
    # U.S. Code: e.g., "42 U.S.C. § 1983", "18 USC 2251"
    r'(\d+)\s+U\.?S\.?C\.?(?:A\.?)?\s+§?\s*(\d+[\w\-]*(?:\([a-z0-9]+\))?)',
]

CFR_CITATION_PATTERNS = [
    # Code of Federal Regulations: e.g., "40 C.F.R. § 1.1", "21 CFR 314.80"
    r'(\d+)\s+C\.?F\.?R\.?\s+§?\s*(\d+(?:\.\d+)?(?:\([a-z0-9]+\))?)',
]

FEDERAL_REGISTER_PATTERNS = [
    # Federal Register: e.g., "85 FR 12345", "90 Fed. Reg. 54321"
    r'(\d+)\s+(?:FR|Fed\.?\s+Reg\.?)\s+(\d+)',
]

PUBLIC_LAW_PATTERNS = [
    # Public Law: e.g., "Pub. L. 111-148", "P.L. 117-2"
    r'(?:Pub\.?\s+L\.?|P\.L\.)\s+(\d+)-(\d+)',
]


class CitationExtractor:
    """Extract and analyze citations from legal documents."""
    
    def __init__(self):
        """Initialize citation extractor."""
        self.case_patterns = [re.compile(p, re.IGNORECASE) for p in CASE_CITATION_PATTERNS]
        self.usc_patterns = [re.compile(p, re.IGNORECASE) for p in USC_CITATION_PATTERNS]
        self.cfr_patterns = [re.compile(p, re.IGNORECASE) for p in CFR_CITATION_PATTERNS]
        self.fr_patterns = [re.compile(p, re.IGNORECASE) for p in FEDERAL_REGISTER_PATTERNS]
        self.pl_patterns = [re.compile(p, re.IGNORECASE) for p in PUBLIC_LAW_PATTERNS]
    
    def extract_citations(self, text: str) -> List[Citation]:
        """Extract all citations from a text.
        
        Args:
            text: Text to extract citations from
            
        Returns:
            List of Citation objects
        """
        citations = []
        
        # Extract case citations
        citations.extend(self._extract_case_citations(text))
        
        # Extract USC citations
        citations.extend(self._extract_usc_citations(text))
        
        # Extract CFR citations
        citations.extend(self._extract_cfr_citations(text))
        
        # Extract Federal Register citations
        citations.extend(self._extract_fr_citations(text))
        
        # Extract Public Law citations
        citations.extend(self._extract_pl_citations(text))
        
        # Sort by position in text
        citations.sort(key=lambda c: c.start_pos)
        
        return citations
    
    def _extract_case_citations(self, text: str) -> List[Citation]:
        """Extract case law citations."""
        citations = []
        
        for pattern in self.case_patterns:
            for match in pattern.finditer(text):
                volume = match.group(1)
                reporter = match.group(2)
                page = match.group(3)
                
                # Extract year if present nearby
                year_match = re.search(r'\((\d{4})\)', text[match.end():match.end()+20])
                year = year_match.group(1) if year_match else None
                
                citation = Citation(
                    type="case",
                    text=match.group(0),
                    reporter=reporter,
                    volume=volume,
                    page=page,
                    year=year,
                    start_pos=match.start(),
                    end_pos=match.end()
                )
                
                # Try to determine court from reporter
                citation.court = self._determine_court(reporter)
                
                # Try to generate URL
                citation.url = self._generate_case_url(citation)
                
                citations.append(citation)
        
        return citations
    
    def _extract_usc_citations(self, text: str) -> List[Citation]:
        """Extract U.S. Code citations."""
        citations = []
        
        for pattern in self.usc_patterns:
            for match in pattern.finditer(text):
                title = match.group(1)
                section = match.group(2)
                
                citation = Citation(
                    type="usc",
                    text=match.group(0),
                    title=title,
                    section=section,
                    start_pos=match.start(),
                    end_pos=match.end()
                )
                
                # Generate URL
                citation.url = f"https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title{title}-section{section}"
                
                citations.append(citation)
        
        return citations
    
    def _extract_cfr_citations(self, text: str) -> List[Citation]:
        """Extract Code of Federal Regulations citations."""
        citations = []
        
        for pattern in self.cfr_patterns:
            for match in pattern.finditer(text):
                title = match.group(1)
                section = match.group(2)
                
                citation = Citation(
                    type="cfr",
                    text=match.group(0),
                    title=title,
                    section=section,
                    start_pos=match.start(),
                    end_pos=match.end()
                )
                
                # Generate URL (eCFR)
                citation.url = f"https://www.ecfr.gov/current/title-{title}/section-{section}"
                
                citations.append(citation)
        
        return citations
    
    def _extract_fr_citations(self, text: str) -> List[Citation]:
        """Extract Federal Register citations."""
        citations = []
        
        for pattern in self.fr_patterns:
            for match in pattern.finditer(text):
                volume = match.group(1)
                page = match.group(2)
                
                citation = Citation(
                    type="federal_register",
                    text=match.group(0),
                    volume=volume,
                    page=page,
                    start_pos=match.start(),
                    end_pos=match.end()
                )
                
                # Generate URL
                citation.url = f"https://www.federalregister.gov/citation/{volume}-FR-{page}"
                
                citations.append(citation)
        
        return citations
    
    def _extract_pl_citations(self, text: str) -> List[Citation]:
        """Extract Public Law citations."""
        citations = []
        
        for pattern in self.pl_patterns:
            for match in pattern.finditer(text):
                congress = match.group(1)
                law = match.group(2)
                
                citation = Citation(
                    type="public_law",
                    text=match.group(0),
                    volume=congress,  # Store congress number as volume
                    page=law,  # Store law number as page
                    start_pos=match.start(),
                    end_pos=match.end()
                )
                
                # Generate URL (Congress.gov)
                citation.url = f"https://www.congress.gov/bill/{congress}th-congress/house-bill"
                
                citations.append(citation)
        
        return citations
    
    def _determine_court(self, reporter: str) -> Optional[str]:
        """Determine court from reporter abbreviation."""
        reporter_lower = reporter.lower().replace(' ', '').replace('.', '')
        
        court_mapping = {
            'us': 'U.S. Supreme Court',
            'sct': 'U.S. Supreme Court',
            'f3d': 'U.S. Court of Appeals',
            'f2d': 'U.S. Court of Appeals',
            'f4th': 'U.S. Court of Appeals',
            'fappx': 'U.S. Court of Appeals (Unpublished)',
            'fsupp': 'U.S. District Court',
            'fsupp2d': 'U.S. District Court',
            'fsupp3d': 'U.S. District Court',
        }
        
        return court_mapping.get(reporter_lower)
    
    def _generate_case_url(self, citation: Citation) -> Optional[str]:
        """Generate URL for case citation (CourtListener)."""
        if not (citation.volume and citation.reporter and citation.page):
            return None
        
        # Use CourtListener citation lookup
        reporter_clean = citation.reporter.replace('.', '').replace(' ', '-').lower()
        return f"https://www.courtlistener.com/opinion/{citation.volume}/{reporter_clean}/{citation.page}/"
    
    def analyze_citations(self, citations: List[Citation]) -> Dict[str, Any]:
        """Analyze extracted citations and generate statistics.
        
        Args:
            citations: List of Citation objects
            
        Returns:
            Dict with citation statistics and analysis
        """
        if not citations:
            return {
                "total_citations": 0,
                "by_type": {},
                "unique_citations": 0,
                "citation_density": 0
            }
        
        # Count by type
        by_type = {}
        for citation in citations:
            by_type[citation.type] = by_type.get(citation.type, 0) + 1
        
        # Find unique citations
        unique_texts = set(c.text for c in citations)
        
        return {
            "total_citations": len(citations),
            "by_type": by_type,
            "unique_citations": len(unique_texts),
            "most_cited": self._find_most_cited(citations),
            "citation_types": list(by_type.keys())
        }
    
    def _find_most_cited(self, citations: List[Citation], top_n: int = 5) -> List[Dict[str, Any]]:
        """Find most frequently cited sources."""
        citation_counts = {}
        
        for citation in citations:
            key = citation.text
            if key not in citation_counts:
                citation_counts[key] = {
                    "text": citation.text,
                    "type": citation.type,
                    "count": 0,
                    "url": citation.url
                }
            citation_counts[key]["count"] += 1
        
        # Sort by count
        sorted_citations = sorted(citation_counts.values(), key=lambda x: x["count"], reverse=True)
        return sorted_citations[:top_n]
    
    def create_citation_graph(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create a citation graph showing relationships between documents.
        
        Args:
            documents: List of documents with 'id', 'text', and optional 'citations' fields
            
        Returns:
            Dict with graph structure
        """
        graph = {
            "nodes": [],
            "edges": [],
            "statistics": {}
        }
        
        # Create nodes for each document
        for doc in documents:
            graph["nodes"].append({
                "id": doc.get("id"),
                "title": doc.get("title", "Unknown"),
                "type": doc.get("type", "document")
            })
        
        # Extract citations and create edges
        for doc in documents:
            doc_id = doc.get("id")
            text = doc.get("text", "")
            
            citations = self.extract_citations(text)
            
            for citation in citations:
                # Find matching documents
                for target_doc in documents:
                    if self._citation_matches_document(citation, target_doc):
                        graph["edges"].append({
                            "source": doc_id,
                            "target": target_doc.get("id"),
                            "citation_text": citation.text,
                            "citation_type": citation.type
                        })
        
        # Calculate statistics
        graph["statistics"] = {
            "total_documents": len(documents),
            "total_edges": len(graph["edges"]),
            "avg_citations_per_document": len(graph["edges"]) / len(documents) if documents else 0
        }
        
        return graph
    
    def _citation_matches_document(self, citation: Citation, document: Dict[str, Any]) -> bool:
        """Check if a citation matches a document."""
        # Simple matching logic - can be enhanced
        doc_title = document.get("title", "").lower()
        citation_text = citation.text.lower()
        
        # Check if citation text appears in document title
        if citation_text in doc_title:
            return True
        
        # Check type-specific matches
        if citation.type == "usc" and "us code" in doc_title:
            if citation.title in doc_title:
                return True
        
        return False


# Convenience functions
def extract_citations_from_text(text: str) -> List[Citation]:
    """Extract all citations from text (convenience function).
    
    Args:
        text: Text to analyze
        
    Returns:
        List of Citation objects
    """
    extractor = CitationExtractor()
    return extractor.extract_citations(text)


def analyze_document_citations(text: str) -> Dict[str, Any]:
    """Extract and analyze citations from a document.
    
    Args:
        text: Document text
        
    Returns:
        Dict with citations and analysis
    """
    extractor = CitationExtractor()
    citations = extractor.extract_citations(text)
    analysis = extractor.analyze_citations(citations)
    
    return {
        "citations": [
            {
                "type": c.type,
                "text": c.text,
                "url": c.url,
                "position": {"start": c.start_pos, "end": c.end_pos}
            }
            for c in citations
        ],
        "analysis": analysis
    }


def create_citation_network(documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create a citation network from multiple documents.
    
    Args:
        documents: List of documents with 'id' and 'text' fields
        
    Returns:
        Dict with network graph structure
    """
    extractor = CitationExtractor()
    return extractor.create_citation_graph(documents)


__all__ = [
    "Citation",
    "CitationExtractor",
    "extract_citations_from_text",
    "analyze_document_citations",
    "create_citation_network",
]
