"""Natural Language Query Processor for Legal Search.

This module processes natural language queries about legal rules and regulations,
extracting key information needed to generate effective search terms:
- Legal topics and concepts
- Jurisdictions (federal, state, local)
- Entity mentions (agencies, departments)
- Legal domains (housing, employment, civil rights, etc.)

It leverages the complaint_analysis module for keyword extraction and categorization.

SHARED COMPONENTS:
This module uses shared components from complaint_analysis:
- get_keywords() - Legal domain keyword registry (see ../SHARED_COMPONENTS.md)
- LegalPatternExtractor - Legal concept and pattern extraction
These components are shared across multiple systems in legal_scrapers.
"""

import logging
import re
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Import complaint analysis components for reuse
# NOTE: These are SHARED components used by multiple systems in legal_scrapers.
# See ../SHARED_COMPONENTS.md for documentation on shared component usage.
try:
    from .complaint_analysis import (
        get_keywords,           # Shared: Legal domain keyword registry
        get_registered_types,   # Shared: List of all registered complaint types
        LegalPatternExtractor   # Shared: Legal pattern and concept extraction
    )
    HAVE_COMPLAINT_ANALYSIS = True
except ImportError:
    HAVE_COMPLAINT_ANALYSIS = False
    logger.warning("complaint_analysis module not available for query processing")


# US state codes and names
US_STATES = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
    'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
    'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho',
    'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
    'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
    'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
    'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
    'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
    'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
    'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
    'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'District of Columbia'
}

# Federal agencies and departments (common mentions)
FEDERAL_ENTITIES = {
    'epa': 'Environmental Protection Agency',
    'fda': 'Food and Drug Administration',
    'ftc': 'Federal Trade Commission',
    'fcc': 'Federal Communications Commission',
    'sec': 'Securities and Exchange Commission',
    'doj': 'Department of Justice',
    'dhs': 'Department of Homeland Security',
    'irs': 'Internal Revenue Service',
    'eeoc': 'Equal Employment Opportunity Commission',
    'nlrb': 'National Labor Relations Board',
    'osha': 'Occupational Safety and Health Administration',
    'hud': 'Department of Housing and Urban Development',
    'doe': 'Department of Energy',
    'usda': 'Department of Agriculture',
    'dot': 'Department of Transportation',
    'congress': 'United States Congress',
    'senate': 'United States Senate',
    'house': 'House of Representatives'
}

# Government branches
BRANCHES = ['legislative', 'executive', 'judicial']


@dataclass
class QueryIntent:
    """Parsed query intent and extracted entities."""
    
    # Original query
    original_query: str
    
    # Extracted entities
    topics: List[str] = field(default_factory=list)
    legal_concepts: List[str] = field(default_factory=list)
    jurisdictions: List[str] = field(default_factory=list)  # State codes or "federal"
    municipalities: List[str] = field(default_factory=list)
    agencies: List[str] = field(default_factory=list)
    branches: List[str] = field(default_factory=list)
    
    # Categorization
    legal_domains: List[str] = field(default_factory=list)  # housing, employment, etc.
    scope: str = "federal"  # federal, state, local, or mixed
    
    # Confidence scores
    confidence: float = 0.0
    
    def __repr__(self) -> str:
        parts = [f"Query: '{self.original_query}'"]
        if self.topics:
            parts.append(f"Topics: {', '.join(self.topics)}")
        if self.jurisdictions:
            parts.append(f"Jurisdictions: {', '.join(self.jurisdictions)}")
        if self.agencies:
            parts.append(f"Agencies: {', '.join(self.agencies)}")
        if self.legal_domains:
            parts.append(f"Domains: {', '.join(self.legal_domains)}")
        parts.append(f"Scope: {self.scope}")
        return " | ".join(parts)


class QueryProcessor:
    """Process natural language queries for legal search.
    
    This processor extracts structured information from natural language queries
    to enable effective search term generation.
    
    Example:
        >>> processor = QueryProcessor()
        >>> intent = processor.process("EPA regulations on water pollution in California")
        >>> print(intent.agencies)  # ['EPA']
        >>> print(intent.jurisdictions)  # ['federal', 'CA']
        >>> print(intent.topics)  # ['water pollution', 'regulations']
    """
    
    def __init__(self):
        """Initialize the query processor."""
        self.legal_extractor = None
        if HAVE_COMPLAINT_ANALYSIS:
            try:
                self.legal_extractor = LegalPatternExtractor()
            except Exception as e:
                logger.warning(f"Could not initialize LegalPatternExtractor: {e}")
    
    def process(self, query: str) -> QueryIntent:
        """Process a natural language query and extract intent.
        
        Args:
            query: Natural language query about legal rules/regulations
            
        Returns:
            QueryIntent with extracted entities and categorization
        """
        intent = QueryIntent(original_query=query)
        
        # Extract different components
        intent.topics = self._extract_topics(query)
        intent.legal_concepts = self._extract_legal_concepts(query)
        intent.jurisdictions = self._extract_jurisdictions(query)
        intent.municipalities = self._extract_municipalities(query)
        intent.agencies = self._extract_agencies(query)
        intent.branches = self._extract_branches(query)
        intent.legal_domains = self._categorize_legal_domain(query)
        intent.scope = self._determine_scope(intent)
        intent.confidence = self._calculate_confidence(intent)
        
        return intent
    
    def _extract_topics(self, query: str) -> List[str]:
        """Extract main topics from query.
        
        Args:
            query: Query text
            
        Returns:
            List of identified topics
        """
        topics = []
        query_lower = query.lower()
        
        # Topic keywords
        topic_patterns = [
            (r'\b(regulation|rule|law|statute|ordinance|code|policy)s?\b', 'regulations'),
            (r'\b(enforcement|compliance|violation|penalty|fine)s?\b', 'enforcement'),
            (r'\b(permit|license|certification|approval)s?\b', 'permits'),
            (r'\b(report|filing|disclosure|notification)s?\b', 'reporting'),
            (r'\b(safety|health|environmental|pollution)s?\b', 'safety and health'),
            (r'\b(employment|workplace|labor|worker)s?\b', 'employment'),
            (r'\b(housing|tenant|landlord|rent)s?\b', 'housing'),
            (r'\b(consumer|product|service|purchase)s?\b', 'consumer protection'),
        ]
        
        for pattern, topic in topic_patterns:
            if re.search(pattern, query_lower):
                topics.append(topic)
        
        return list(set(topics))
    
    def _extract_legal_concepts(self, query: str) -> List[str]:
        """Extract legal concepts and terms from query.
        
        Args:
            query: Query text
            
        Returns:
            List of legal concepts
        """
        concepts = []
        
        # Use legal pattern extractor if available
        if self.legal_extractor:
            try:
                provisions = self.legal_extractor.extract_provisions(query)
                concepts.extend(provisions.get('provisions', []))
                
                citations = self.legal_extractor.extract_citations(query)
                concepts.extend([c['full_citation'] for c in citations.get('citations', [])])
            except Exception as e:
                logger.debug(f"Error extracting legal concepts: {e}")
        
        # Extract common legal terms
        legal_terms = [
            'discrimination', 'harassment', 'civil rights', 'due process',
            'equal protection', 'first amendment', 'fourth amendment',
            'reasonable accommodation', 'ada', 'title vii', 'fair housing',
            'environmental', 'pollution', 'hazardous', 'toxic',
            'malpractice', 'negligence', 'liability', 'damages'
        ]
        
        query_lower = query.lower()
        for term in legal_terms:
            if term in query_lower:
                concepts.append(term)
        
        return list(set(concepts))
    
    def _extract_jurisdictions(self, query: str) -> List[str]:
        """Extract jurisdictions (federal, state codes) from query.
        
        Args:
            query: Query text
            
        Returns:
            List of jurisdiction identifiers
        """
        jurisdictions = []
        query_lower = query.lower()
        
        # Check for federal
        if re.search(r'\b(federal|nationwide|national|us|united states)\b', query_lower):
            jurisdictions.append('federal')
        
        # Check for state mentions
        for code, name in US_STATES.items():
            if name.lower() in query_lower or f" {code.lower()} " in f" {query_lower} ":
                jurisdictions.append(code)
        
        return list(set(jurisdictions))
    
    def _extract_municipalities(self, query: str) -> List[str]:
        """Extract municipality names from query.
        
        Args:
            query: Query text
            
        Returns:
            List of municipality names
        """
        municipalities = []
        query_lower = query.lower()
        
        # Look for city/county/town mentions
        city_pattern = r'\b(city|county|town|municipality) of ([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b'
        matches = re.finditer(city_pattern, query, re.IGNORECASE)
        for match in matches:
            municipalities.append(match.group(2))
        
        # Look for well-known cities
        major_cities = [
            'New York', 'Los Angeles', 'Chicago', 'Houston', 'Phoenix',
            'Philadelphia', 'San Antonio', 'San Diego', 'Dallas', 'San Jose',
            'Austin', 'Jacksonville', 'Fort Worth', 'Columbus', 'Charlotte',
            'San Francisco', 'Indianapolis', 'Seattle', 'Denver', 'Boston'
        ]
        
        for city in major_cities:
            if city.lower() in query_lower:
                municipalities.append(city)
        
        return list(set(municipalities))
    
    def _extract_agencies(self, query: str) -> List[str]:
        """Extract federal agency mentions from query.
        
        Args:
            query: Query text
            
        Returns:
            List of agency names/acronyms
        """
        agencies = []
        query_lower = query.lower()
        
        # Check for known federal entities
        for acronym, full_name in FEDERAL_ENTITIES.items():
            if acronym in query_lower or full_name.lower() in query_lower:
                agencies.append(full_name)
        
        # Look for "department of X" pattern
        dept_pattern = r'\bdepartment of ([a-z\s]+)\b'
        matches = re.finditer(dept_pattern, query_lower)
        for match in matches:
            agencies.append(f"Department of {match.group(1).title()}")
        
        return list(set(agencies))
    
    def _extract_branches(self, query: str) -> List[str]:
        """Extract government branch mentions from query.
        
        Args:
            query: Query text
            
        Returns:
            List of branches (legislative, executive, judicial)
        """
        branches = []
        query_lower = query.lower()
        
        if re.search(r'\b(congress|senate|house|legislative|legislation)\b', query_lower):
            branches.append('legislative')
        
        if re.search(r'\b(executive|agency|department|administration|president)\b', query_lower):
            branches.append('executive')
        
        if re.search(r'\b(court|judicial|judge|justice|ruling)\b', query_lower):
            branches.append('judicial')
        
        return list(set(branches))
    
    def _categorize_legal_domain(self, query: str) -> List[str]:
        """Categorize query into legal domains (housing, employment, etc.).
        
        Uses all 14 registered complaint types from complaint_analysis for
        comprehensive categorization.
        
        Args:
            query: Query text
            
        Returns:
            List of applicable legal domains
        """
        domains = []
        
        # Use complaint analysis if available
        if self.legal_extractor and HAVE_COMPLAINT_ANALYSIS:
            try:
                categories = self.legal_extractor.categorize_complaint_type(query)
                domains.extend(categories.get('categories', []))
            except Exception as e:
                logger.debug(f"Error categorizing legal domain: {e}")
        
        # Enhanced: Use all 14 registered complaint types for better matching
        if HAVE_COMPLAINT_ANALYSIS:
            try:
                from .complaint_analysis import get_registered_types, get_keywords
                
                # Get all registered types and their keywords
                all_types = get_registered_types()
                matches = self._match_to_complaint_types(query, all_types)
                domains.extend(matches)
                
            except Exception as e:
                logger.debug(f"Error using complaint types registry: {e}")
        
        # Fallback: keyword-based categorization
        if not domains:
            query_lower = query.lower()
            
            domain_keywords = {
                'housing': ['housing', 'tenant', 'landlord', 'rent', 'eviction', 'fair housing'],
                'employment': ['employment', 'workplace', 'discrimination', 'wrongful termination', 'eeoc'],
                'civil_rights': ['civil rights', 'discrimination', 'equal protection', 'voting rights'],
                'consumer': ['consumer', 'fraud', 'deceptive', 'false advertising', 'ftc'],
                'environmental': ['environmental', 'pollution', 'epa', 'clean air', 'clean water'],
                'healthcare': ['healthcare', 'medical', 'hipaa', 'patient rights', 'malpractice'],
                'immigration': ['immigration', 'visa', 'asylum', 'deportation', 'uscis'],
                'tax': ['tax', 'irs', 'tax court', 'tax penalty'],
            }
            
            for domain, keywords in domain_keywords.items():
                if any(keyword in query_lower for keyword in keywords):
                    domains.append(domain)
        
        return list(set(domains))
    
    def _match_to_complaint_types(self, query: str, complaint_types: List[str]) -> List[str]:
        """Match query to complaint types using type-specific keywords.
        
        This method uses the complaint_analysis keyword registry to check
        each complaint type's keywords against the query, providing more
        accurate categorization than simple keyword matching.
        
        Args:
            query: Query text
            complaint_types: List of complaint type names to check
            
        Returns:
            List of matching complaint types
        """
        if not HAVE_COMPLAINT_ANALYSIS:
            return []
        
        try:
            from .complaint_analysis import get_keywords
            
            matches = []
            query_lower = query.lower()
            
            # Minimum keyword matches required (threshold)
            MATCH_THRESHOLD = 2
            
            for complaint_type in complaint_types:
                # Get type-specific keywords for more precise matching
                keywords = get_keywords('complaint', complaint_type=complaint_type)
                
                if not keywords:
                    continue
                
                # Count matches
                match_count = sum(1 for kw in keywords if kw.lower() in query_lower)
                
                # Add to results if meets threshold
                if match_count >= MATCH_THRESHOLD:
                    matches.append(complaint_type)
                elif match_count == 1 and len(keywords) < 10:
                    # Lower threshold for types with fewer keywords
                    matches.append(complaint_type)
            
            return matches
            
        except Exception as e:
            logger.debug(f"Error matching complaint types: {e}")
            return []
    
    def _determine_scope(self, intent: QueryIntent) -> str:
        """Determine the scope of the query (federal, state, local, mixed).
        
        Args:
            intent: Partially populated QueryIntent
            
        Returns:
            Scope string
        """
        has_federal = 'federal' in intent.jurisdictions or bool(intent.agencies)
        has_state = any(j != 'federal' for j in intent.jurisdictions)
        has_local = bool(intent.municipalities)
        
        if has_federal and (has_state or has_local):
            return 'mixed'
        elif has_local:
            return 'local'
        elif has_state:
            return 'state'
        else:
            return 'federal'
    
    def _calculate_confidence(self, intent: QueryIntent) -> float:
        """Calculate confidence score for the parsed intent.
        
        Args:
            intent: Populated QueryIntent
            
        Returns:
            Confidence score (0.0 to 1.0)
        """
        # Base confidence
        confidence = 0.5
        
        # Increase confidence for each extracted component
        if intent.jurisdictions:
            confidence += 0.1
        if intent.agencies:
            confidence += 0.1
        if intent.legal_domains:
            confidence += 0.1
        if intent.topics:
            confidence += 0.1
        if intent.legal_concepts:
            confidence += 0.1
        
        return min(1.0, confidence)
    
    def batch_process(self, queries: List[str]) -> List[QueryIntent]:
        """Process multiple queries.
        
        Args:
            queries: List of natural language queries
            
        Returns:
            List of QueryIntent objects
        """
        return [self.process(query) for query in queries]
