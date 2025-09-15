"""
Caselaw GraphRAG Processor

This module extends the existing GraphRAG capabilities to process legal documents
from the Caselaw Access Project, focusing on legal entity extraction, citation
relationships, legal concept mapping, and IPLD knowledge graph construction.

Enhanced to work with comprehensive embeddings and create IPLD-compatible 
knowledge graphs for decentralized legal document analysis.
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional, Tuple, Set
from collections import defaultdict, Counter
import re
import math
from datetime import datetime

try:
    import networkx as nx
    NETWORKX_AVAILABLE = True
except ImportError:
    NETWORKX_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

from .caselaw_dataset import CaselawDatasetLoader

logger = logging.getLogger(__name__)


class EnhancedLegalEntityExtractor:
    """Enhanced legal entity extractor with improved pattern matching"""
    
    def __init__(self):
        # Enhanced legal entity patterns
        self.patterns = {
            'case_citation': [
                r'\d+\s+U\.S\.\s+\d+',                    # Supreme Court (e.g., "347 U.S. 483")
                r'\d+\s+S\.?\s?Ct\.?\s+\d+',              # Supreme Court Reporter
                r'\d+\s+F\.\s?(?:2d|3d)?\s+\d+',         # Federal Reporter
                r'\d+\s+F\.\s?Supp\.?\s?(?:2d|3d)?\s+\d+', # Federal Supplement
                r'\d+\s+[A-Z][a-z]+\.?\s+(?:2d|3d)?\s+\d+', # State reporters
            ],
            'court_names': [
                r'Supreme Court of the United States',
                r'U\.?S\.? Supreme Court',
                r'United States Court of Appeals',
                r'U\.?S\.? Court of Appeals for the [A-Z][a-z]+ Circuit',
                r'United States District Court',
                r'U\.?S\.? District Court',
                r'State Supreme Court',
                r'Court of Appeals',
                r'Circuit Court',
                r'District Court',
                r'Family Court',
                r'Criminal Court',
                r'Civil Court'
            ],
            'legal_concepts': [
                r'due process(?:\s+clause)?',
                r'equal protection(?:\s+clause)?',
                r'first amendment(?:\s+rights?)?',
                r'fourth amendment(?:\s+rights?)?',
                r'fifth amendment(?:\s+rights?)?',
                r'sixth amendment(?:\s+rights?)?',
                r'fourteenth amendment(?:\s+rights?)?',
                r'miranda(?:\s+rights?|\s+warnings?)?',
                r'probable cause',
                r'search and seizure',
                r'freedom of speech',
                r'freedom of religion',
                r'freedom of the press',
                r'civil rights?',
                r'constitutional law',
                r'criminal procedure',
                r'habeas corpus',
                r'double jeopardy',
                r'cruel and unusual punishment',
                r'right to counsel',
                r'interstate commerce',
                r'commerce clause',
                r'supremacy clause',
                r'separation of powers',
                r'checks and balances'
            ],
            'case_names': [
                r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+v\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*',
                r'[A-Z][a-z]+(?:\s+&\s+[A-Z][a-z]+)*\s+v\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*',
                r'In\s+re\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*',
                r'Ex\s+parte\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*'
            ],
            'judges': [
                r'Justice\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*',
                r'Chief Justice\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*',
                r'Judge\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*',
                r'Circuit Judge\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*',
                r'District Judge\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*'
            ],
            'statutes': [
                r'(?:USC|U\.S\.C\.)\s+§?\s*\d+(?:-\d+)?(?:\([a-z]\))?',
                r'\d+\s+U\.S\.C\.\s+§?\s*\d+(?:-\d+)?(?:\([a-z]\))?',
                r'Title\s+\d+\s+U\.S\.C\.\s+§?\s*\d+',
                r'\d+\s+C\.F\.R\.\s+§?\s*\d+(?:\.\d+)?',
                r'Federal Rules?\s+of\s+(?:Civil|Criminal)\s+Procedure\s+(?:Rule\s+)?\d+',
                r'Fed\.?\s?R\.?\s?(?:Civ|Crim)\.?\s?P\.?\s+\d+'
            ],
            'amendments': [
                r'(?:First|1st)\s+Amendment',
                r'(?:Second|2nd)\s+Amendment',
                r'(?:Third|3rd)\s+Amendment',
                r'(?:Fourth|4th)\s+Amendment',
                r'(?:Fifth|5th)\s+Amendment',
                r'(?:Sixth|6th)\s+Amendment',
                r'(?:Seventh|7th)\s+Amendment',
                r'(?:Eighth|8th)\s+Amendment',
                r'(?:Ninth|9th)\s+Amendment',
                r'(?:Tenth|10th)\s+Amendment',
                r'(?:Eleventh|11th)\s+Amendment',
                r'(?:Twelfth|12th)\s+Amendment',
                r'(?:Thirteenth|13th)\s+Amendment',
                r'(?:Fourteenth|14th)\s+Amendment',
                r'(?:Fifteenth|15th)\s+Amendment'
            ]
        }
        
        # Compile patterns for efficiency
        self.compiled_patterns = {}
        for entity_type, pattern_list in self.patterns.items():
            combined_pattern = '|'.join(f'({pattern})' for pattern in pattern_list)
            self.compiled_patterns[entity_type] = re.compile(combined_pattern, re.IGNORECASE)
    
    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """Extract legal entities from text with enhanced patterns"""
        entities = defaultdict(set)
        
        for entity_type, pattern in self.compiled_patterns.items():
            matches = pattern.finditer(text)
            for match in matches:
                # Get the actual matched text (not the group)
                matched_text = match.group(0).strip()
                if matched_text and len(matched_text) > 2:  # Filter out very short matches
                    entities[entity_type].add(matched_text)
        
        # Convert sets to lists for JSON serialization
        return {k: list(v) for k, v in entities.items()}


class EnhancedLegalRelationshipMapper:
    """Enhanced relationship mapper with embedding-based similarity"""
    
    def __init__(self):
        self.relationship_types = [
            'cites', 'overrules', 'distinguishes', 'follows', 'applies',
            'interprets', 'construes', 'relies_on', 'references', 'extends',
            'contradicts', 'supports', 'analogizes', 'reverses'
        ]
    
    def extract_relationships(self, case_data: Dict[str, Any], 
                            all_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract relationships with embedding-based similarity"""
        relationships = []
        
        # Extract citation relationships
        citations = self._extract_citations(case_data['text'])
        for citation in citations:
            relationships.append({
                'source': case_data['id'],
                'target': citation,
                'type': 'cites',
                'confidence': 0.9,
                'metadata': {'citation_type': 'direct'}
            })
        
        # Extract conceptual relationships
        concepts = case_data.get('legal_concepts', [])
        for concept in concepts:
            relationships.append({
                'source': case_data['id'],
                'target': f"concept_{concept.replace(' ', '_')}",
                'type': 'involves_concept',
                'confidence': 0.8,
                'metadata': {'concept_category': self._categorize_concept(concept)}
            })
        
        # Find similar cases using embeddings if available
        if case_data.get('embedding') and NUMPY_AVAILABLE:
            similar_cases = self._find_similar_cases_by_embedding(case_data, all_cases)
        else:
            similar_cases = self._find_similar_cases_by_content(case_data, all_cases)
        
        for similar_case in similar_cases:
            relationships.append({
                'source': case_data['id'],
                'target': similar_case['id'],
                'type': 'related_to',
                'confidence': similar_case['similarity'],
                'metadata': {
                    'similarity_type': 'embedding' if case_data.get('embedding') else 'content',
                    'similarity_score': similar_case['similarity']
                }
            })
        
        # Extract temporal relationships (cases from same era)
        temporal_cases = self._find_temporal_relationships(case_data, all_cases)
        for temporal_case in temporal_cases:
            relationships.append({
                'source': case_data['id'],
                'target': temporal_case['id'],
                'type': 'temporal_context',
                'confidence': 0.6,
                'metadata': {
                    'year_difference': abs(case_data.get('year', 0) - temporal_case.get('year', 0)),
                    'same_court': case_data.get('court') == temporal_case.get('court')
                }
            })
        
        return relationships
    
    def _find_similar_cases_by_embedding(self, case: Dict[str, Any], 
                                       all_cases: List[Dict[str, Any]], 
                                       threshold: float = 0.7) -> List[Dict[str, Any]]:
        """Find similar cases using embedding cosine similarity"""
        if not NUMPY_AVAILABLE:
            return self._find_similar_cases_by_content(case, all_cases, threshold)
        
        case_embedding = np.array(case['embedding'])
        similar_cases = []
        
        for other_case in all_cases:
            if other_case['id'] == case['id'] or not other_case.get('embedding'):
                continue
                
            other_embedding = np.array(other_case['embedding'])
            
            # Calculate cosine similarity
            dot_product = np.dot(case_embedding, other_embedding)
            norm_a = np.linalg.norm(case_embedding)
            norm_b = np.linalg.norm(other_embedding)
            
            if norm_a > 0 and norm_b > 0:
                similarity = dot_product / (norm_a * norm_b)
                
                # Convert from [-1, 1] to [0, 1] range
                similarity = (similarity + 1) / 2
                
                if similarity >= threshold:
                    similar_cases.append({
                        'id': other_case['id'],
                        'similarity': float(similarity),
                        'title': other_case.get('title', ''),
                        'year': other_case.get('year', 0),
                        'court': other_case.get('court', '')
                    })
        
        # Sort by similarity and return top matches
        similar_cases.sort(key=lambda x: x['similarity'], reverse=True)
        return similar_cases[:10]  # Top 10 most similar
    
    def _find_similar_cases_by_content(self, case: Dict[str, Any], 
                                     all_cases: List[Dict[str, Any]], 
                                     threshold: float = 0.7) -> List[Dict[str, Any]]:
        """Fallback content-based similarity when embeddings not available"""
        similar_cases = []
        case_concepts = set(case.get('legal_concepts', []))
        case_topic = case.get('topic', '')
        
        for other_case in all_cases:
            if other_case['id'] == case['id']:
                continue
                
            # Calculate similarity based on concepts and topics
            other_concepts = set(other_case.get('legal_concepts', []))
            other_topic = other_case.get('topic', '')
            
            concept_overlap = len(case_concepts.intersection(other_concepts))
            concept_union = len(case_concepts.union(other_concepts))
            
            if concept_union > 0:
                concept_similarity = concept_overlap / concept_union
            else:
                concept_similarity = 0
            
            topic_similarity = 1.0 if case_topic == other_topic else 0.0
            
            # Combined similarity score
            similarity = (concept_similarity * 0.7) + (topic_similarity * 0.3)
            
            if similarity >= threshold:
                similar_cases.append({
                    'id': other_case['id'],
                    'similarity': similarity,
                    'title': other_case.get('title', ''),
                    'year': other_case.get('year', 0),
                    'court': other_case.get('court', '')
                })
        
        return similar_cases[:5]  # Limit to top 5 for content-based
    
    def _find_temporal_relationships(self, case: Dict[str, Any], 
                                   all_cases: List[Dict[str, Any]], 
                                   year_threshold: int = 5) -> List[Dict[str, Any]]:
        """Find cases from similar time periods"""
        case_year = case.get('year', 0)
        temporal_cases = []
        
        for other_case in all_cases:
            if other_case['id'] == case['id']:
                continue
                
            other_year = other_case.get('year', 0)
            year_diff = abs(case_year - other_year)
            
            if year_diff <= year_threshold and year_diff > 0:
                temporal_cases.append({
                    'id': other_case['id'],
                    'year': other_year,
                    'year_diff': year_diff,
                    'court': other_case.get('court', '')
                })
        
        return temporal_cases[:3]  # Limit to 3 temporal relationships
    
    def _extract_citations(self, text: str) -> List[str]:
        """Enhanced citation extraction"""
        citation_patterns = [
            r'\d+\s+U\.S\.\s+\d+',
            r'\d+\s+S\.?\s?Ct\.?\s+\d+',
            r'\d+\s+F\.\s?(?:2d|3d)?\s+\d+',
            r'\d+\s+F\.\s?Supp\.?\s?(?:2d|3d)?\s+\d+'
        ]
        
        citations = []
        for pattern in citation_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            citations.extend([cite.strip() for cite in matches])
        
        return list(set(citations))  # Remove duplicates
    
    def _categorize_concept(self, concept: str) -> str:
        """Categorize legal concepts"""
        concept_lower = concept.lower()
        
        if any(word in concept_lower for word in ['amendment', 'constitutional', 'constitution']):
            return 'constitutional_law'
        elif any(word in concept_lower for word in ['criminal', 'procedure', 'miranda', 'search', 'seizure']):
            return 'criminal_law'
        elif any(word in concept_lower for word in ['civil', 'rights', 'discrimination', 'equal']):
            return 'civil_rights'
        elif any(word in concept_lower for word in ['commerce', 'regulation', 'interstate']):
            return 'commercial_law'
        else:
            return 'general_law'


class IPLDCaselawKnowledgeGraph:
    """Enhanced IPLD-compatible knowledge graph for legal cases"""
    
    def __init__(self):
        self.graph = None
        self.entity_extractor = EnhancedLegalEntityExtractor()
        self.relationship_mapper = EnhancedLegalRelationshipMapper()
        self.ipld_nodes = {}
        self.ipld_links = []
        
        if NETWORKX_AVAILABLE:
            self.graph = nx.DiGraph()
    
    def build_ipld_knowledge_graph(self, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build IPLD-compatible knowledge graph from case data"""
        logger.info(f"Building IPLD knowledge graph from {len(cases)} cases...")
        
        graph_data = {
            'nodes': [],
            'edges': [],
            'ipld_structure': {
                'dag_nodes': {},
                'content_links': [],
                'schema_version': '1.0'
            },
            'statistics': {},
            'metadata': {
                'created_at': datetime.now().isoformat(),
                'total_cases': len(cases),
                'processing_pipeline': 'ipfs_datasets_py.caselaw_graphrag'
            }
        }
        
        all_entities = defaultdict(list)
        all_relationships = []
        
        # Process each case and create IPLD nodes
        for i, case in enumerate(cases):
            # Create IPLD-compatible case node
            case_ipld_node = self._create_ipld_case_node(case, i)
            graph_data['ipld_structure']['dag_nodes'][case['id']] = case_ipld_node
            
            # Add case as graph node
            case_node = {
                'id': case['id'],
                'type': 'case',
                'title': case['title'],
                'court': case['court'],
                'year': case['year'],
                'topic': case['topic'],
                'precedent_value': case.get('precedent_value', 'medium'),
                'ipld_cid': case_ipld_node['cid'],
                'embedding_available': 'embedding' in case and case['embedding'] is not None
            }
            graph_data['nodes'].append(case_node)
            
            # Extract and process entities
            entities = self.entity_extractor.extract_entities(case.get('text', ''))
            for entity_type, entity_list in entities.items():
                for entity in entity_list:
                    entity_id = f"{entity_type}_{hash(entity) % 10000}"
                    
                    # Create IPLD node for entity
                    entity_ipld_node = self._create_ipld_entity_node(entity, entity_type, entity_id)
                    graph_data['ipld_structure']['dag_nodes'][entity_id] = entity_ipld_node
                    
                    # Add entity as graph node
                    entity_node = {
                        'id': entity_id,
                        'type': entity_type,
                        'name': entity,
                        'ipld_cid': entity_ipld_node['cid'],
                        'category': self._categorize_entity(entity_type)
                    }
                    
                    # Check if entity already exists
                    existing_entity = next((n for n in graph_data['nodes'] if n['id'] == entity_id), None)
                    if not existing_entity:
                        graph_data['nodes'].append(entity_node)
                    
                    all_entities[entity_type].extend(entity_list)
                    
                    # Add edge from case to entity with IPLD link
                    ipld_link = self._create_ipld_link(case['id'], entity_id, 'mentions')
                    graph_data['ipld_structure']['content_links'].append(ipld_link)
                    
                    graph_data['edges'].append({
                        'source': case['id'],
                        'target': entity_id,
                        'type': 'mentions',
                        'confidence': 0.8,
                        'ipld_link': ipld_link['link_id']
                    })
            
            # Extract relationships with enhanced mapping
            relationships = self.relationship_mapper.extract_relationships(case, cases)
            all_relationships.extend(relationships)
        
        # Process relationships and create IPLD links
        for rel in all_relationships:
            ipld_link = self._create_ipld_link(
                rel['source'], 
                rel['target'], 
                rel['type'],
                metadata=rel.get('metadata', {})
            )
            graph_data['ipld_structure']['content_links'].append(ipld_link)
            
            graph_data['edges'].append({
                'source': rel['source'],
                'target': rel['target'], 
                'type': rel['type'],
                'confidence': rel['confidence'],
                'ipld_link': ipld_link['link_id'],
                'metadata': rel.get('metadata', {})
            })
        
        # Add to NetworkX graph if available
        if self.graph is not None:
            for node in graph_data['nodes']:
                self.graph.add_node(node['id'], **node)
            
            for edge in graph_data['edges']:
                self.graph.add_edge(edge['source'], edge['target'], **{
                    'type': edge['type'],
                    'confidence': edge['confidence'],
                    'ipld_link': edge.get('ipld_link')
                })
        
        # Calculate enhanced statistics with IPLD metrics
        graph_data['statistics'] = self._calculate_enhanced_statistics(cases, graph_data)
        
        return graph_data
    
    def _create_ipld_case_node(self, case: Dict[str, Any], index: int) -> Dict[str, Any]:
        """Create IPLD-compatible node for a legal case"""
        case_cid = f"baf{'c' * 56}{'0' * 8}{index:08d}"
        
        ipld_node = {
            'cid': case_cid,
            'type': 'legal_case',
            'data': {
                'title': case['title'],
                'court': case['court'],
                'year': case['year'],
                'citation': case.get('citation', ''),
                'jurisdiction': case.get('jurisdiction', 'unknown'),
                'topic': case.get('topic', 'general'),
                'summary': case.get('summary', ''),
                'legal_concepts': case.get('legal_concepts', []),
                'precedent_value': case.get('precedent_value', 'medium')
            },
            'links': [
                {
                    'name': 'text_content',
                    'cid': f"baf{'t' * 56}{'0' * 8}{index:08d}",
                    'size': len(case.get('text', ''))
                },
                {
                    'name': 'embeddings',
                    'cid': f"baf{'e' * 56}{'0' * 8}{index:08d}",
                    'size': len(case.get('embedding', [])) * 4 if case.get('embedding') else 0
                }
            ],
            'metadata': case.get('ipld_metadata', {}),
            'created_at': datetime.now().isoformat()
        }
        
        return ipld_node
    
    def _create_ipld_entity_node(self, entity_name: str, entity_type: str, entity_id: str) -> Dict[str, Any]:
        """Create IPLD-compatible node for a legal entity"""
        entity_cid = f"baf{'n' * 56}{hash(entity_id) % 100000000:08d}"
        
        ipld_node = {
            'cid': entity_cid,
            'type': f'legal_entity_{entity_type}',
            'data': {
                'name': entity_name,
                'entity_type': entity_type,
                'category': self._categorize_entity(entity_type),
                'normalized_name': self._normalize_entity_name(entity_name)
            },
            'links': [],
            'metadata': {
                'extraction_confidence': 0.8,
                'processing_timestamp': datetime.now().isoformat()
            }
        }
        
        return ipld_node
    
    def _create_ipld_link(self, source_id: str, target_id: str, 
                         relationship_type: str, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create IPLD-compatible link between nodes"""
        link_id = f"link_{hash(f'{source_id}_{target_id}_{relationship_type}') % 1000000:06d}"
        
        ipld_link = {
            'link_id': link_id,
            'source': source_id,
            'target': target_id,
            'relationship_type': relationship_type,
            'metadata': metadata or {},
            'created_at': datetime.now().isoformat(),
            'link_cid': f"baf{'l' * 56}{hash(link_id) % 100000000:08d}"
        }
        
        return ipld_link
    
    def _categorize_entity(self, entity_type: str) -> str:
        """Categorize entity types for better organization"""
        categories = {
            'case_citation': 'reference',
            'court_names': 'institution',
            'legal_concepts': 'concept',
            'case_names': 'precedent',
            'judges': 'person',
            'statutes': 'law',
            'amendments': 'constitutional'
        }
        return categories.get(entity_type, 'general')
    
    def _normalize_entity_name(self, name: str) -> str:
        """Normalize entity names for consistent identification"""
        # Remove extra whitespace and standardize format
        normalized = re.sub(r'\s+', ' ', name.strip())
        
        # Standardize court names
        court_mappings = {
            'Supreme Court of the United States': 'SCOTUS',
            'U.S. Supreme Court': 'SCOTUS',
            'United States Court of Appeals': 'USCA',
            'United States District Court': 'USDC'
        }
        
        for full_name, short_name in court_mappings.items():
            if full_name in normalized:
                normalized = normalized.replace(full_name, short_name)
        
        return normalized
    
    def _calculate_enhanced_statistics(self, cases: List[Dict[str, Any]], 
                                     graph_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate comprehensive statistics including IPLD metrics"""
        stats = {
            # Basic graph metrics
            'total_nodes': len(graph_data['nodes']),
            'total_edges': len(graph_data['edges']),
            'case_nodes': len([n for n in graph_data['nodes'] if n['type'] == 'case']),
            'entity_types': len(set(n['type'] for n in graph_data['nodes'])),
            'relationship_types': len(set(e['type'] for e in graph_data['edges'])),
            
            # IPLD-specific metrics
            'ipld_nodes': len(graph_data['ipld_structure']['dag_nodes']),
            'ipld_links': len(graph_data['ipld_structure']['content_links']),
            'total_ipld_size': sum(
                sum(link.get('size', 0) for link in node.get('links', []))
                for node in graph_data['ipld_structure']['dag_nodes'].values()
            ),
            
            # Legal-specific metrics
            'most_common_topics': self._get_topic_distribution(cases),
            'court_distribution': self._get_court_distribution(cases),
            'year_range': self._get_year_range(cases),
            'legal_concept_frequency': self._get_concept_frequency(cases),
            'embedding_coverage': sum(1 for case in cases if case.get('embedding')) / len(cases) if cases else 0,
            
            # Network analysis metrics (if NetworkX available)
            'network_metrics': self._calculate_network_metrics() if self.graph and NETWORKX_AVAILABLE else {}
        }
        
        return stats
    
    def _calculate_network_metrics(self) -> Dict[str, Any]:
        """Calculate network analysis metrics using NetworkX"""
        if not self.graph or not NETWORKX_AVAILABLE:
            return {}
        
        metrics = {}
        
        try:
            # Basic connectivity metrics
            metrics['number_of_nodes'] = self.graph.number_of_nodes()
            metrics['number_of_edges'] = self.graph.number_of_edges()
            metrics['density'] = nx.density(self.graph)
            
            # Centrality measures (for smaller graphs)
            if self.graph.number_of_nodes() < 1000:
                degree_centrality = nx.degree_centrality(self.graph)
                metrics['avg_degree_centrality'] = sum(degree_centrality.values()) / len(degree_centrality)
                metrics['max_degree_centrality'] = max(degree_centrality.values()) if degree_centrality else 0
                
                # Most central nodes
                top_central_nodes = sorted(degree_centrality.items(), key=lambda x: x[1], reverse=True)[:5]
                metrics['most_central_nodes'] = [{'node': node, 'centrality': cent} for node, cent in top_central_nodes]
            
            # Component analysis
            if not nx.is_directed_acyclic_graph(self.graph):
                undirected = self.graph.to_undirected()
                metrics['number_of_components'] = nx.number_connected_components(undirected)
                metrics['largest_component_size'] = len(max(nx.connected_components(undirected), key=len))
            
        except Exception as e:
            logger.warning(f"Error calculating network metrics: {e}")
            metrics['error'] = str(e)
        
        return metrics
    
    def _get_topic_distribution(self, cases: List[Dict[str, Any]]) -> Dict[str, int]:
        """Get distribution of legal topics"""
        topics = [case.get('topic', 'unknown') for case in cases]
        return dict(Counter(topics).most_common(10))
    
    def _get_court_distribution(self, cases: List[Dict[str, Any]]) -> Dict[str, int]:
        """Get distribution of courts"""
        courts = [case.get('court', 'unknown') for case in cases]
        return dict(Counter(courts).most_common(10))
    
    def _get_year_range(self, cases: List[Dict[str, Any]]) -> Dict[str, int]:
        """Get year range of cases"""
        years = [case.get('year', 0) for case in cases if case.get('year')]
        if years:
            return {
                'min_year': min(years),
                'max_year': max(years),
                'span': max(years) - min(years)
            }
        return {'min_year': 0, 'max_year': 0, 'span': 0}
    
    def _get_concept_frequency(self, cases: List[Dict[str, Any]]) -> Dict[str, int]:
        """Get frequency of legal concepts across all cases"""
        concept_counter = Counter()
        for case in cases:
            concepts = case.get('legal_concepts', [])
            concept_counter.update(concepts)
        return dict(concept_counter.most_common(20))


class EnhancedCaselawGraphRAGProcessor:
    """Enhanced main processor for Caselaw GraphRAG pipeline with IPLD support"""
    
    def __init__(self, cache_dir: Optional[str] = None, embedding_dim: int = 768):
        self.dataset_loader = CaselawDatasetLoader(cache_dir=cache_dir, embedding_dim=embedding_dim)
        self.knowledge_graph = IPLDCaselawKnowledgeGraph()
        self.processed_data = None
        self.embedding_dim = embedding_dim
        
    def process_dataset(self, split: str = "train", max_samples: Optional[int] = None) -> Dict[str, Any]:
        """Process the complete caselaw dataset through enhanced GraphRAG pipeline"""
        logger.info(f"Starting enhanced GraphRAG processing for caselaw dataset...")
        
        # Load enhanced dataset with embeddings
        dataset_result = self.dataset_loader.load_dataset(split=split, max_samples=max_samples)
        if dataset_result['status'] != 'success':
            return {'status': 'error', 'message': 'Failed to load dataset'}
        
        cases = dataset_result['dataset']
        logger.info(f"Processing {len(cases)} cases with embedding dimension {dataset_result.get('embedding_dim', 'unknown')}...")
        
        # Build enhanced IPLD knowledge graph
        graph_data = self.knowledge_graph.build_ipld_knowledge_graph(cases)
        
        # Store processed data for querying
        self.processed_data = {
            'cases': cases,
            'knowledge_graph': graph_data,
            'dataset_info': dataset_result
        }
        
        # Prepare final result with comprehensive information
        result = {
            'status': 'success',
            'dataset_info': {
                'source': dataset_result['source'],
                'count': dataset_result['count'],
                'split': split,
                'embedding_dimension': dataset_result.get('embedding_dim', self.embedding_dim),
                'has_embeddings': any(case.get('embedding') for case in cases)
            },
            'knowledge_graph': graph_data,
            'processing_summary': {
                'total_entities_extracted': sum(
                    len(entities) for entities in [
                        self.knowledge_graph.entity_extractor.extract_entities(case.get('text', ''))
                        for case in cases
                    ]
                ),
                'embedding_coverage': graph_data['statistics'].get('embedding_coverage', 0),
                'ipld_nodes_created': graph_data['statistics'].get('ipld_nodes', 0),
                'ipld_links_created': graph_data['statistics'].get('ipld_links', 0),
                'processing_time': datetime.now().isoformat()
            }
        }
        
        logger.info(f"Enhanced GraphRAG processing completed successfully:")
        logger.info(f"  - {result['knowledge_graph']['statistics']['total_nodes']} total nodes")
        logger.info(f"  - {result['knowledge_graph']['statistics']['total_edges']} total edges")
        logger.info(f"  - {result['knowledge_graph']['statistics']['ipld_nodes']} IPLD nodes")
        logger.info(f"  - {result['processing_summary']['embedding_coverage']:.2%} embedding coverage")
        
        return result
    
    def query_knowledge_graph(self, query: str, max_results: int = 10, 
                            use_embeddings: bool = True) -> List[Dict[str, Any]]:
        """Enhanced query function with embedding-based semantic search"""
        if not self.processed_data:
            return []
        
        cases = self.processed_data['cases']
        query_lower = query.lower()
        results = []
        
        # If embeddings are available and requested, use semantic search
        if use_embeddings and NUMPY_AVAILABLE:
            # Generate query embedding (simplified approach - in production would use same model as cases)
            query_embedding = self._generate_query_embedding(query)
            if query_embedding is not None:
                results = self._semantic_search(query_embedding, cases, max_results)
                if results:
                    return results
        
        # Fallback to text-based search
        for case in cases:
            relevance_score = 0
            
            # Check title match
            if query_lower in case.get('title', '').lower():
                relevance_score += 2.0
            
            # Check text content match
            if query_lower in case.get('text', '').lower():
                relevance_score += 1.5
            
            # Check summary match
            if query_lower in case.get('summary', '').lower():
                relevance_score += 1.2
            
            # Check legal concepts match
            for concept in case.get('legal_concepts', []):
                if query_lower in concept.lower():
                    relevance_score += 1.0
            
            # Check topic match
            if query_lower in case.get('topic', '').lower():
                relevance_score += 0.8
            
            # Check court match
            if query_lower in case.get('court', '').lower():
                relevance_score += 0.5
            
            if relevance_score > 0:
                results.append({
                    'case': case,
                    'relevance_score': relevance_score,
                    'search_type': 'text_based'
                })
        
        # Sort by relevance and return top results
        results.sort(key=lambda x: x['relevance_score'], reverse=True)
        return results[:max_results]
    
    def _generate_query_embedding(self, query: str) -> Optional[List[float]]:
        """Generate embedding for search query (simplified implementation)"""
        if not NUMPY_AVAILABLE:
            return None
        
        # Simplified query embedding generation
        # In production, this should use the same model as the case embeddings
        import hashlib
        
        # Use hash-based approach for consistent query embeddings
        query_hash = hashlib.sha256(query.encode()).hexdigest()
        embedding = []
        
        for i in range(self.embedding_dim):
            sub_hash = hashlib.sha256(f"{query_hash}_{i}".encode()).hexdigest()
            hex_val = int(sub_hash[:8], 16)
            normalized_val = (hex_val / (16**8 - 1)) * 2 - 1
            embedding.append(normalized_val)
        
        # Normalize to unit vector
        embedding = np.array(embedding)
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        
        return embedding.tolist()
    
    def _semantic_search(self, query_embedding: List[float], cases: List[Dict[str, Any]], 
                        max_results: int) -> List[Dict[str, Any]]:
        """Perform semantic search using embeddings"""
        if not NUMPY_AVAILABLE:
            return []
        
        query_vec = np.array(query_embedding)
        results = []
        
        for case in cases:
            if not case.get('embedding'):
                continue
                
            case_embedding = np.array(case['embedding'])
            
            # Calculate cosine similarity
            dot_product = np.dot(query_vec, case_embedding)
            norm_query = np.linalg.norm(query_vec)
            norm_case = np.linalg.norm(case_embedding)
            
            if norm_query > 0 and norm_case > 0:
                similarity = dot_product / (norm_query * norm_case)
                # Convert from [-1, 1] to [0, 1] range
                similarity = (similarity + 1) / 2
                
                if similarity > 0.1:  # Minimum similarity threshold
                    results.append({
                        'case': case,
                        'relevance_score': float(similarity),
                        'search_type': 'semantic_embedding'
                    })
        
        # Sort by similarity
        results.sort(key=lambda x: x['relevance_score'], reverse=True)
        return results[:max_results]
    
    def get_ipld_structure(self) -> Optional[Dict[str, Any]]:
        """Get the IPLD structure for integration with IPFS"""
        if not self.processed_data:
            return None
        
        return self.processed_data['knowledge_graph']['ipld_structure']
    
    def export_for_ipfs(self, output_dir: str) -> Dict[str, Any]:
        """Export knowledge graph in IPFS-ready format"""
        if not self.processed_data:
            return {'status': 'error', 'message': 'No processed data available'}
        
        os.makedirs(output_dir, exist_ok=True)
        
        # Export IPLD structure
        ipld_structure = self.get_ipld_structure()
        with open(os.path.join(output_dir, 'ipld_structure.json'), 'w') as f:
            json.dump(ipld_structure, f, indent=2)
        
        # Export individual case files
        cases_dir = os.path.join(output_dir, 'cases')
        os.makedirs(cases_dir, exist_ok=True)
        
        for case in self.processed_data['cases']:
            case_file = os.path.join(cases_dir, f"{case['id']}.json")
            with open(case_file, 'w') as f:
                json.dump(case, f, indent=2)
        
        # Export knowledge graph
        kg_file = os.path.join(output_dir, 'knowledge_graph.json')
        with open(kg_file, 'w') as f:
            json.dump(self.processed_data['knowledge_graph'], f, indent=2)
        
        return {
            'status': 'success',
            'output_directory': output_dir,
            'files_created': {
                'ipld_structure': 'ipld_structure.json',
                'knowledge_graph': 'knowledge_graph.json',
                'cases_directory': 'cases/',
                'total_case_files': len(self.processed_data['cases'])
            }
        }


# Backward compatibility aliases
CaselawKnowledgeGraph = IPLDCaselawKnowledgeGraph
CaselawGraphRAGProcessor = EnhancedCaselawGraphRAGProcessor




if __name__ == "__main__":
    # Test the enhanced GraphRAG processor
    print("🔬 Testing Enhanced Caselaw GraphRAG Processor...")
    
    processor = create_caselaw_graphrag_processor()
    
    # Process sample data with enhanced features
    result = processor.process_dataset(max_samples=50)
    
    if result['status'] == 'success':
        print(f"✅ Successfully processed {result['dataset_info']['count']} cases")
        print(f"📊 Knowledge graph: {result['knowledge_graph']['statistics']['total_nodes']} nodes, {result['knowledge_graph']['statistics']['total_edges']} edges")
        print(f"🔗 IPLD nodes: {result['knowledge_graph']['statistics']['ipld_nodes']}")
        print(f"📎 IPLD links: {result['knowledge_graph']['statistics']['ipld_links']}")
        print(f"🧠 Embedding coverage: {result['knowledge_graph']['statistics']['embedding_coverage']:.2%}")
        
        # Test enhanced querying
        query_results = processor.query_knowledge_graph("civil rights", use_embeddings=True)
        print(f"🔍 Enhanced query 'civil rights' found {len(query_results)} relevant cases")
        
        if query_results:
            top_result = query_results[0]
            print(f"📄 Top result: {top_result['case']['title']} (score: {top_result['relevance_score']:.3f}, type: {top_result['search_type']})")
        
        # Test IPLD export
        ipld_structure = processor.get_ipld_structure()
        if ipld_structure:
            print(f"📦 IPLD structure ready with {len(ipld_structure['dag_nodes'])} DAG nodes")
    else:
        print("❌ Processing failed")