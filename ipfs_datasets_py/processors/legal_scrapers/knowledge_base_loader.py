"""Knowledge Base Loader for Legal Search.

This module loads and indexes legal entity data from JSONL files:
- federal_all_branches.jsonl: Federal government entities (legislative, executive, judicial)
- state_agencies_all.jsonl: State-level agencies and departments
- us_towns_and_counties_urls.jsonl: Municipal and county government entities

The data is indexed for efficient lookup by:
- Entity name and aliases
- Jurisdiction (federal/state/local)
- Branch (legislative/executive/judicial)
- Agency type
- Website domains and URLs
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class FederalEntity:
    """Federal government entity (agency, department, service)."""
    id: str
    name: str
    branch: str  # legislative, executive, judicial
    website: Optional[str] = None
    host: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    description: str = ""
    seed_urls: List[str] = field(default_factory=list)
    
    def to_search_terms(self) -> List[str]:
        """Generate search terms for this entity."""
        terms = [self.name]
        terms.extend(self.aliases)
        if self.description:
            terms.append(self.description)
        return [t for t in terms if t]


@dataclass
class StateEntity:
    """State-level government entity."""
    jurisdiction: str  # State code (e.g., "CA", "NY")
    state_name: str
    branch: str
    agency_name: str
    agency_url: Optional[str] = None
    host: Optional[str] = None
    domain: Optional[str] = None
    
    def to_search_terms(self) -> List[str]:
        """Generate search terms for this entity."""
        terms = [
            f"{self.agency_name} {self.state_name}",
            self.agency_name,
            f"{self.jurisdiction} {self.agency_name}"
        ]
        return [t for t in terms if t]


@dataclass
class MunicipalEntity:
    """Municipal or county government entity."""
    gnis: int  # Geographic Names Information System ID
    place_name: str
    state_code: str
    source_urls: List[str] = field(default_factory=list)
    status: str = "not_scraped"
    
    def to_search_terms(self) -> List[str]:
        """Generate search terms for this entity."""
        terms = [
            self.place_name,
            f"{self.place_name} {self.state_code}",
            f"{self.place_name} government"
        ]
        return [t for t in terms if t]


class LegalKnowledgeBase:
    """Indexed knowledge base of legal entities for search term generation.
    
    This class loads and indexes legal entity data from JSONL files, providing
    efficient lookup and search term generation capabilities.
    
    Example:
        >>> kb = LegalKnowledgeBase()
        >>> kb.load_from_directory("/path/to/legal_scrapers")
        >>> entities = kb.search_entities("EPA environmental")
        >>> terms = kb.generate_search_terms("EPA", entity_type="federal")
    """
    
    def __init__(self):
        """Initialize empty knowledge base."""
        self.federal_entities: List[FederalEntity] = []
        self.state_entities: List[StateEntity] = []
        self.municipal_entities: List[MunicipalEntity] = []
        
        # Indexes for efficient lookup
        self.federal_by_name: Dict[str, List[FederalEntity]] = defaultdict(list)
        self.federal_by_branch: Dict[str, List[FederalEntity]] = defaultdict(list)
        self.federal_by_domain: Dict[str, List[FederalEntity]] = defaultdict(list)
        
        self.state_by_jurisdiction: Dict[str, List[StateEntity]] = defaultdict(list)
        self.state_by_agency: Dict[str, List[StateEntity]] = defaultdict(list)
        self.state_by_branch: Dict[str, List[StateEntity]] = defaultdict(list)
        
        self.municipal_by_state: Dict[str, List[MunicipalEntity]] = defaultdict(list)
        self.municipal_by_name: Dict[str, List[MunicipalEntity]] = defaultdict(list)
        
        self.loaded = False
    
    def load_from_directory(self, directory: str) -> None:
        """Load knowledge base from directory containing JSONL files.
        
        Args:
            directory: Path to directory containing the JSONL files
        """
        dir_path = Path(directory)
        
        # Load federal entities
        federal_path = dir_path / "federal_all_branches.jsonl"
        if federal_path.exists():
            self._load_federal_entities(federal_path)
            logger.info(f"Loaded {len(self.federal_entities)} federal entities")
        else:
            logger.warning(f"Federal entities file not found: {federal_path}")
        
        # Load state entities
        state_path = dir_path / "state_agencies_all.jsonl"
        if state_path.exists():
            self._load_state_entities(state_path)
            logger.info(f"Loaded {len(self.state_entities)} state entities")
        else:
            logger.warning(f"State entities file not found: {state_path}")
        
        # Load municipal entities
        municipal_path = dir_path / "us_towns_and_counties_urls.jsonl"
        if municipal_path.exists():
            self._load_municipal_entities(municipal_path)
            logger.info(f"Loaded {len(self.municipal_entities)} municipal entities")
        else:
            logger.warning(f"Municipal entities file not found: {municipal_path}")
        
        self.loaded = True
    
    def _load_federal_entities(self, path: Path) -> None:
        """Load federal entities from JSONL file."""
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    entity = FederalEntity(
                        id=data.get('id', ''),
                        name=data.get('name', ''),
                        branch=data.get('branch', 'unknown'),
                        website=data.get('website'),
                        host=data.get('host'),
                        aliases=data.get('aliases', []),
                        description=data.get('description', ''),
                        seed_urls=data.get('seed_urls', [])
                    )
                    
                    # Skip entities with empty names
                    if not entity.name:
                        continue
                    
                    self.federal_entities.append(entity)
                    
                    # Build indexes
                    name_lower = entity.name.lower()
                    self.federal_by_name[name_lower].append(entity)
                    for alias in entity.aliases:
                        if alias:  # Skip empty aliases
                            self.federal_by_name[alias.lower()].append(entity)
                    
                    self.federal_by_branch[entity.branch].append(entity)
                    
                    if entity.host:
                        self.federal_by_domain[entity.host].append(entity)
                    
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Error parsing federal entity: {e}")
    
    def _load_state_entities(self, path: Path) -> None:
        """Load state entities from JSONL file."""
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    entity = StateEntity(
                        jurisdiction=data.get('jurisdiction', ''),
                        state_name=data.get('name', ''),
                        branch=data.get('branch', 'unknown'),
                        agency_name=data.get('agency_name', ''),
                        agency_url=data.get('agency_url'),
                        host=data.get('host'),
                        domain=data.get('domain')
                    )
                    
                    # Skip entities with empty names
                    if not entity.agency_name:
                        continue
                    
                    self.state_entities.append(entity)
                    
                    # Build indexes
                    self.state_by_jurisdiction[entity.jurisdiction].append(entity)
                    agency_lower = entity.agency_name.lower()
                    self.state_by_agency[agency_lower].append(entity)
                    self.state_by_branch[entity.branch].append(entity)
                    
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Error parsing state entity: {e}")
    
    def _load_municipal_entities(self, path: Path) -> None:
        """Load municipal entities from JSONL file."""
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    # Handle both single source_url and source_urls list
                    source_urls = data.get('source_urls', [])
                    if not source_urls and 'source_url' in data:
                        source_url = data['source_url']
                        if isinstance(source_url, str):
                            source_urls = [url.strip() for url in source_url.split(',')]
                        else:
                            source_urls = [source_url]
                    
                    entity = MunicipalEntity(
                        gnis=data.get('gnis', 0),
                        place_name=data.get('place_name', ''),
                        state_code=data.get('state_code', ''),
                        source_urls=source_urls,
                        status=data.get('status', 'not_scraped')
                    )
                    
                    # Skip entities with empty names
                    if not entity.place_name:
                        continue
                    
                    self.municipal_entities.append(entity)
                    
                    # Build indexes
                    self.municipal_by_state[entity.state_code].append(entity)
                    name_lower = entity.place_name.lower()
                    self.municipal_by_name[name_lower].append(entity)
                    
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Error parsing municipal entity: {e}")
    
    def search_federal(self, query: str) -> List[FederalEntity]:
        """Search for federal entities by name or branch.
        
        Args:
            query: Search query (name, alias, or branch)
            
        Returns:
            List of matching federal entities
        """
        query_lower = query.lower()
        results = []
        
        # Search by name/alias
        results.extend(self.federal_by_name.get(query_lower, []))
        
        # Search by branch
        results.extend(self.federal_by_branch.get(query_lower, []))
        
        # Partial name matching
        for entity in self.federal_entities:
            if query_lower in entity.name.lower() or any(query_lower in alias.lower() for alias in entity.aliases):
                if entity not in results:
                    results.append(entity)
        
        return results
    
    def search_state(self, query: str, jurisdiction: Optional[str] = None) -> List[StateEntity]:
        """Search for state entities by name or jurisdiction.
        
        Args:
            query: Search query (agency name)
            jurisdiction: Optional state code to filter by (e.g., "CA", "NY")
            
        Returns:
            List of matching state entities
        """
        query_lower = query.lower()
        results = []
        
        # Filter by jurisdiction if provided
        if jurisdiction:
            candidates = self.state_by_jurisdiction.get(jurisdiction.upper(), [])
        else:
            candidates = self.state_entities
        
        # Search by agency name
        for entity in candidates:
            if query_lower in entity.agency_name.lower():
                results.append(entity)
        
        return results
    
    def search_municipal(self, query: str, state_code: Optional[str] = None) -> List[MunicipalEntity]:
        """Search for municipal entities by name or state.
        
        Args:
            query: Search query (place name)
            state_code: Optional state code to filter by (e.g., "CA", "NY")
            
        Returns:
            List of matching municipal entities
        """
        query_lower = query.lower()
        results = []
        
        # Filter by state if provided
        if state_code:
            candidates = self.municipal_by_state.get(state_code.upper(), [])
        else:
            candidates = self.municipal_entities
        
        # Search by place name
        for entity in candidates:
            if query_lower in entity.place_name.lower():
                results.append(entity)
        
        return results
    
    def search_all(self, query: str) -> Dict[str, List[Any]]:
        """Search across all entity types.
        
        Args:
            query: Search query
            
        Returns:
            Dict with keys 'federal', 'state', 'municipal' containing matching entities
        """
        return {
            'federal': self.search_federal(query),
            'state': self.search_state(query),
            'municipal': self.search_municipal(query)
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the knowledge base.
        
        Returns:
            Dict containing entity counts and other statistics
        """
        return {
            'loaded': self.loaded,
            'total_entities': len(self.federal_entities) + len(self.state_entities) + len(self.municipal_entities),
            'federal': {
                'total': len(self.federal_entities),
                'by_branch': {branch: len(entities) for branch, entities in self.federal_by_branch.items()}
            },
            'state': {
                'total': len(self.state_entities),
                'by_jurisdiction': {j: len(entities) for j, entities in self.state_by_jurisdiction.items()},
                'by_branch': {branch: len(entities) for branch, entities in self.state_by_branch.items()}
            },
            'municipal': {
                'total': len(self.municipal_entities),
                'by_state': {state: len(entities) for state, entities in self.municipal_by_state.items()}
            }
        }


# Global instance for easy access
_global_kb: Optional[LegalKnowledgeBase] = None


def get_global_knowledge_base() -> LegalKnowledgeBase:
    """Get or create the global knowledge base instance.
    
    Returns:
        Global LegalKnowledgeBase instance
    """
    global _global_kb
    if _global_kb is None:
        _global_kb = LegalKnowledgeBase()
    return _global_kb


def load_knowledge_base(directory: Optional[str] = None) -> LegalKnowledgeBase:
    """Load or reload the global knowledge base.
    
    Args:
        directory: Path to directory containing JSONL files. If None, uses default location.
        
    Returns:
        Loaded LegalKnowledgeBase instance
    """
    kb = get_global_knowledge_base()
    
    if directory is None:
        # Default to same directory as this file
        directory = str(Path(__file__).parent)
    
    kb.load_from_directory(directory)
    return kb
