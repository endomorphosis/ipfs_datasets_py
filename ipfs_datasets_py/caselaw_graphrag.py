"""
Caselaw GraphRAG Processor

This module extends the existing GraphRAG capabilities to process legal documents
from the Caselaw Access Project, focusing on legal entity extraction, citation
relationships, and legal concept mapping.
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional, Tuple, Set
from collections import defaultdict, Counter
import re
from datetime import datetime

try:
    import networkx as nx
    NETWORKX_AVAILABLE = True
except ImportError:
    NETWORKX_AVAILABLE = False

from .caselaw_dataset import CaselawDatasetLoader

logger = logging.getLogger(__name__)


class LegalEntityExtractor:
    """Extract legal entities from case text"""
    
    def __init__(self):
        # Legal entity patterns
        self.patterns = {
            'case_citation': r'\d+\s+U\.S\.\s+\d+|\d+\s+F\.\s?\d+d?\s+\d+|\d+\s+S\.Ct\.\s+\d+',
            'court_names': r'Supreme Court|Circuit Court|District Court|Court of Appeals|State Supreme Court',
            'legal_concepts': r'due process|equal protection|first amendment|fourth amendment|miranda rights|probable cause|search and seizure',
            'case_names': r'[A-Z][a-z]+\s+v\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*',
            'judges': r'Justice\s+[A-Z][a-z]+|Judge\s+[A-Z][a-z]+|Chief Justice\s+[A-Z][a-z]+',
            'statutes': r'(?:USC|U\.S\.C\.)\s+§?\s*\d+(?:-\d+)?|\d+\s+U\.S\.C\.\s+§?\s*\d+',
            'amendments': r'(?:First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth|Eleventh|Twelfth|Thirteenth|Fourteenth|Fifteenth)\s+Amendment'
        }
        
        # Compile patterns for efficiency
        self.compiled_patterns = {
            name: re.compile(pattern, re.IGNORECASE) 
            for name, pattern in self.patterns.items()
        }
    
    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """Extract legal entities from text"""
        entities = defaultdict(list)
        
        for entity_type, pattern in self.compiled_patterns.items():
            matches = pattern.findall(text)
            if matches:
                # Clean and deduplicate matches
                cleaned_matches = list(set([match.strip() for match in matches if match.strip()]))
                entities[entity_type].extend(cleaned_matches)
        
        return dict(entities)


class LegalRelationshipMapper:
    """Map relationships between legal entities and concepts"""
    
    def __init__(self):
        self.relationship_types = [
            'cites', 'overrules', 'distinguishes', 'follows', 'applies',
            'interprets', 'construes', 'relies_on', 'references', 'extends'
        ]
    
    def extract_relationships(self, case_data: Dict[str, Any], 
                            all_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract relationships between cases and legal concepts"""
        relationships = []
        
        # Extract citation relationships
        citations = self._extract_citations(case_data['text'])
        for citation in citations:
            relationships.append({
                'source': case_data['id'],
                'target': citation,
                'type': 'cites',
                'confidence': 0.9
            })
        
        # Extract conceptual relationships
        concepts = case_data.get('legal_concepts', [])
        for concept in concepts:
            relationships.append({
                'source': case_data['id'],
                'target': concept,
                'type': 'involves_concept',
                'confidence': 0.8
            })
        
        # Find similar cases by topic
        similar_cases = self._find_similar_cases(case_data, all_cases)
        for similar_case in similar_cases:
            relationships.append({
                'source': case_data['id'],
                'target': similar_case['id'],
                'type': 'related_to',
                'confidence': similar_case['similarity']
            })
        
        return relationships
    
    def _extract_citations(self, text: str) -> List[str]:
        """Extract legal citations from text"""
        citation_pattern = r'\d+\s+U\.S\.\s+\d+|\d+\s+F\.\s?\d+d?\s+\d+|\d+\s+S\.Ct\.\s+\d+'
        citations = re.findall(citation_pattern, text, re.IGNORECASE)
        return list(set([cite.strip() for cite in citations]))
    
    def _find_similar_cases(self, case: Dict[str, Any], 
                          all_cases: List[Dict[str, Any]], 
                          threshold: float = 0.7) -> List[Dict[str, Any]]:
        """Find cases with similar topics or concepts"""
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
                    'similarity': similarity
                })
        
        return similar_cases


class CaselawKnowledgeGraph:
    """Build and manage knowledge graph for legal cases"""
    
    def __init__(self):
        self.graph = None
        self.entity_extractor = LegalEntityExtractor()
        self.relationship_mapper = LegalRelationshipMapper()
        
        if NETWORKX_AVAILABLE:
            self.graph = nx.DiGraph()
    
    def build_graph(self, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build knowledge graph from case data"""
        graph_data = {
            'nodes': [],
            'edges': [],
            'statistics': {}
        }
        
        all_entities = defaultdict(list)
        all_relationships = []
        
        # Process each case
        for case in cases:
            # Add case as node
            case_node = {
                'id': case['id'],
                'type': 'case',
                'title': case['title'],
                'court': case['court'],
                'year': case['year'],
                'topic': case['topic'],
                'precedent_value': case.get('precedent_value', 'medium')
            }
            graph_data['nodes'].append(case_node)
            
            # Extract entities from case
            entities = self.entity_extractor.extract_entities(case['text'])
            for entity_type, entity_list in entities.items():
                for entity in entity_list:
                    entity_node = {
                        'id': f"{entity_type}_{entity}",
                        'type': entity_type,
                        'name': entity
                    }
                    graph_data['nodes'].append(entity_node)
                    all_entities[entity_type].extend(entity_list)
                    
                    # Add edge from case to entity
                    graph_data['edges'].append({
                        'source': case['id'],
                        'target': f"{entity_type}_{entity}",
                        'type': 'mentions',
                        'confidence': 0.8
                    })
            
            # Extract relationships
            relationships = self.relationship_mapper.extract_relationships(case, cases)
            all_relationships.extend(relationships)
        
        # Add relationship edges
        graph_data['edges'].extend([
            {
                'source': rel['source'],
                'target': rel['target'], 
                'type': rel['type'],
                'confidence': rel['confidence']
            }
            for rel in all_relationships
        ])
        
        # Add to NetworkX graph if available
        if self.graph is not None:
            for node in graph_data['nodes']:
                self.graph.add_node(node['id'], **node)
            
            for edge in graph_data['edges']:
                self.graph.add_edge(edge['source'], edge['target'], **{
                    'type': edge['type'],
                    'confidence': edge['confidence']
                })
        
        # Calculate statistics
        graph_data['statistics'] = {
            'total_nodes': len(graph_data['nodes']),
            'total_edges': len(graph_data['edges']),
            'case_nodes': len([n for n in graph_data['nodes'] if n['type'] == 'case']),
            'entity_types': len(set(n['type'] for n in graph_data['nodes'])),
            'relationship_types': len(set(e['type'] for e in graph_data['edges'])),
            'most_common_topics': self._get_topic_distribution(cases),
            'court_distribution': self._get_court_distribution(cases),
            'year_range': self._get_year_range(cases)
        }
        
        return graph_data
    
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


class CaselawGraphRAGProcessor:
    """Main processor for Caselaw GraphRAG pipeline"""
    
    def __init__(self, cache_dir: Optional[str] = None):
        self.dataset_loader = CaselawDatasetLoader(cache_dir=cache_dir)
        self.knowledge_graph = CaselawKnowledgeGraph()
        self.processed_data = None
        
    def process_dataset(self, split: str = "train", max_samples: Optional[int] = None) -> Dict[str, Any]:
        """Process the complete caselaw dataset through GraphRAG pipeline"""
        logger.info(f"Starting GraphRAG processing for caselaw dataset...")
        
        # Load dataset
        dataset_result = self.dataset_loader.load_dataset(split=split, max_samples=max_samples)
        if dataset_result['status'] != 'success':
            return {'status': 'error', 'message': 'Failed to load dataset'}
        
        cases = dataset_result['dataset']
        logger.info(f"Processing {len(cases)} cases...")
        
        # Build knowledge graph
        graph_data = self.knowledge_graph.build_graph(cases)
        
        # Prepare final result
        result = {
            'status': 'success',
            'dataset_info': {
                'source': dataset_result['source'],
                'count': dataset_result['count'],
                'split': split
            },
            'knowledge_graph': graph_data,
            'processing_summary': {
                'entities_extracted': graph_data['statistics']['total_nodes'] - graph_data['statistics']['case_nodes'],
                'relationships_found': graph_data['statistics']['total_edges'],
                'legal_topics': list(graph_data['statistics']['most_common_topics'].keys()),
                'court_types': list(graph_data['statistics']['court_distribution'].keys()),
                'time_span': graph_data['statistics']['year_range']
            }
        }
        
        self.processed_data = result
        logger.info("✅ GraphRAG processing completed successfully")
        
        return result
    
    def query_knowledge_graph(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Query the knowledge graph for relevant cases"""
        if not self.processed_data:
            return []
        
        # Simple text-based search for now (can be enhanced with embeddings)
        query_lower = query.lower()
        results = []
        
        for node in self.processed_data['knowledge_graph']['nodes']:
            if node['type'] == 'case':
                # Check if query matches case information
                score = 0
                text_fields = [
                    node.get('title', '').lower(),
                    node.get('topic', '').lower(),
                    node.get('court', '').lower()
                ]
                
                for field in text_fields:
                    if query_lower in field:
                        score += 1
                
                if score > 0:
                    results.append({
                        'case': node,
                        'relevance_score': score,
                        'match_type': 'text_similarity'
                    })
        
        # Sort by relevance and return top results
        results.sort(key=lambda x: x['relevance_score'], reverse=True)
        return results[:max_results]
    
    def get_case_relationships(self, case_id: str) -> Dict[str, Any]:
        """Get all relationships for a specific case"""
        if not self.processed_data:
            return {}
        
        relationships = {
            'outgoing': [],
            'incoming': [],
            'entities': []
        }
        
        for edge in self.processed_data['knowledge_graph']['edges']:
            if edge['source'] == case_id:
                relationships['outgoing'].append(edge)
            elif edge['target'] == case_id:
                relationships['incoming'].append(edge)
        
        return relationships


def create_caselaw_graphrag_processor(cache_dir: Optional[str] = None) -> CaselawGraphRAGProcessor:
    """Factory function to create a Caselaw GraphRAG processor"""
    return CaselawGraphRAGProcessor(cache_dir=cache_dir)


if __name__ == "__main__":
    # Test the GraphRAG processor
    print("🔬 Testing Caselaw GraphRAG Processor...")
    
    processor = create_caselaw_graphrag_processor()
    
    # Process sample data
    result = processor.process_dataset(max_samples=10)
    
    if result['status'] == 'success':
        print(f"✅ Successfully processed {result['dataset_info']['count']} cases")
        print(f"📊 Knowledge graph: {result['knowledge_graph']['statistics']['total_nodes']} nodes, {result['knowledge_graph']['statistics']['total_edges']} edges")
        print(f"🏛️ Courts: {list(result['processing_summary']['court_types'])}")
        print(f"⚖️ Topics: {result['processing_summary']['legal_topics']}")
        
        # Test querying
        query_results = processor.query_knowledge_graph("civil rights")
        print(f"🔍 Query 'civil rights' found {len(query_results)} relevant cases")
        
        if query_results:
            top_result = query_results[0]
            print(f"📄 Top result: {top_result['case']['title']} (score: {top_result['relevance_score']})")
    else:
        print("❌ Processing failed")