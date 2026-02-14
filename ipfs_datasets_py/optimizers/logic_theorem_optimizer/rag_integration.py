"""RAG Integration for Logic Theorem Optimizer.

This module provides integration with the Retrieval-Augmented Generation (RAG)
system to enhance logic extraction with contextual information and few-shot examples.
"""

from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
import logging
import hashlib
import json

logger = logging.getLogger(__name__)


@dataclass
class RAGContext:
    """Context retrieved from RAG system.
    
    Attributes:
        query: Original query text
        relevant_documents: Retrieved relevant documents
        few_shot_examples: Few-shot examples for the task
        ontology_context: Ontology constraints and rules
        similar_theorems: Previously extracted similar theorems
        confidence: Confidence in retrieved context
    """
    
    query: str
    relevant_documents: List[Dict[str, Any]] = field(default_factory=list)
    few_shot_examples: List[Dict[str, str]] = field(default_factory=list)
    ontology_context: Dict[str, Any] = field(default_factory=dict)
    similar_theorems: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class RAGStatistics:
    """Statistics for RAG operations.
    
    Attributes:
        queries: Total number of queries
        cache_hits: Number of cache hits
        cache_misses: Number of cache misses
        avg_documents_retrieved: Average documents per query
        avg_examples_retrieved: Average examples per query
    """
    
    queries: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    avg_documents_retrieved: float = 0.0
    avg_examples_retrieved: float = 0.0
    
    def cache_hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0


class RAGIntegration:
    """RAG Integration adapter for Logic Theorem Optimizer.
    
    This class provides integration with the LogicEnhancedRAG system to:
    - Retrieve relevant context for logic extraction
    - Provide few-shot examples from successful extractions
    - Load ontology context from the knowledge graph
    - Find similar previously extracted theorems
    - Build context-aware prompts
    
    Example:
        >>> rag = RAGIntegration()
        >>> context = rag.get_context("Extract logic from: All drivers must have licenses")
        >>> prompt = rag.build_prompt("All drivers must have licenses", context)
    """
    
    def __init__(self):
        """Initialize RAG integration adapter."""
        self.rag_system = None
        self.example_cache: Dict[str, List[Dict[str, str]]] = {}
        self.context_cache: Dict[str, RAGContext] = {}
        self.stats = RAGStatistics()
        
        # Try to initialize LogicEnhancedRAG
        self._init_rag_system()
    
    def _init_rag_system(self) -> None:
        """Initialize LogicEnhancedRAG system if available."""
        try:
            from ipfs_datasets_py.search.logic_integration import LogicEnhancedRAG
            self.rag_system = LogicEnhancedRAG(use_neural=True)
            logger.info("LogicEnhancedRAG system initialized")
        except (ImportError, Exception) as e:
            logger.warning(f"LogicEnhancedRAG not available: {e}")
            self.rag_system = None
    
    def is_available(self) -> bool:
        """Check if RAG system is available."""
        return self.rag_system is not None
    
    def get_context(
        self,
        query: str,
        num_documents: int = 5,
        num_examples: int = 3,
        use_cache: bool = True
    ) -> RAGContext:
        """Retrieve context from RAG system.
        
        Args:
            query: Query text to find context for
            num_documents: Number of relevant documents to retrieve
            num_examples: Number of few-shot examples to retrieve
            use_cache: Whether to use cached contexts
            
        Returns:
            RAGContext with retrieved information
        """
        self.stats.queries += 1
        
        # Check cache first
        if use_cache:
            cache_key = self._get_cache_key(query)
            if cache_key in self.context_cache:
                self.stats.cache_hits += 1
                logger.debug(f"Cache hit for query: {query[:50]}...")
                return self.context_cache[cache_key]
        
        self.stats.cache_misses += 1
        
        # If RAG system not available, return empty context
        if not self.is_available():
            logger.debug("RAG system not available, returning empty context")
            return RAGContext(query=query, confidence=0.0)
        
        # Retrieve context from RAG system
        context = self._retrieve_from_rag(query, num_documents, num_examples)
        
        # Cache the context
        if use_cache:
            cache_key = self._get_cache_key(query)
            self.context_cache[cache_key] = context
        
        # Update statistics
        self._update_stats(context)
        
        return context
    
    def _retrieve_from_rag(
        self,
        query: str,
        num_documents: int,
        num_examples: int
    ) -> RAGContext:
        """Retrieve context from RAG system.
        
        Args:
            query: Query text
            num_documents: Number of documents to retrieve
            num_examples: Number of examples to retrieve
            
        Returns:
            RAGContext with retrieved information
        """
        context = RAGContext(query=query)
        
        try:
            # Query the RAG system
            result = self.rag_system.query(query)
            
            # Extract relevant documents
            context.relevant_documents = self._extract_documents(result, num_documents)
            
            # Get few-shot examples
            context.few_shot_examples = self._get_few_shot_examples(query, num_examples)
            
            # Load ontology context
            context.ontology_context = self._get_ontology_context(result)
            
            # Find similar theorems
            context.similar_theorems = self._get_similar_theorems(result)
            
            # Calculate confidence
            context.confidence = result.confidence if hasattr(result, 'confidence') else 0.5
            
        except Exception as e:
            logger.error(f"Error retrieving from RAG: {e}")
            context.confidence = 0.0
        
        return context
    
    def _extract_documents(self, result: Any, num_documents: int) -> List[Dict[str, Any]]:
        """Extract relevant documents from RAG result.
        
        Args:
            result: RAG query result
            num_documents: Number of documents to extract
            
        Returns:
            List of relevant documents
        """
        documents = []
        
        if hasattr(result, 'relevant_nodes'):
            for node in result.relevant_nodes[:num_documents]:
                doc = {
                    'id': getattr(node, 'id', 'unknown'),
                    'text': getattr(node, 'text', ''),
                    'type': getattr(node, 'entity_type', 'unknown'),
                    'properties': getattr(node, 'properties', {})
                }
                documents.append(doc)
        
        return documents
    
    def _get_few_shot_examples(self, query: str, num_examples: int) -> List[Dict[str, str]]:
        """Get few-shot examples for the query.
        
        Args:
            query: Query text
            num_examples: Number of examples to retrieve
            
        Returns:
            List of few-shot examples
        """
        # Check if examples are cached
        cache_key = self._get_example_cache_key(query)
        if cache_key in self.example_cache:
            return self.example_cache[cache_key][:num_examples]
        
        # Generate default examples based on query type
        examples = self._generate_default_examples(query)
        
        # Cache the examples
        self.example_cache[cache_key] = examples
        
        return examples[:num_examples]
    
    def _generate_default_examples(self, query: str) -> List[Dict[str, str]]:
        """Generate default few-shot examples based on query.
        
        Args:
            query: Query text
            
        Returns:
            List of default examples
        """
        # Detect query type and provide appropriate examples
        examples = []
        
        # Obligation examples
        if any(word in query.lower() for word in ['must', 'shall', 'required', 'obligation']):
            examples.append({
                'input': 'All drivers must have a valid license.',
                'output': 'OBLIGATION(driver(X), have_license(X))',
                'formalism': 'TDFOL'
            })
            examples.append({
                'input': 'Tenants shall pay rent by the 1st of each month.',
                'output': 'OBLIGATION(tenant(X), pay_rent_by(X, first_of_month))',
                'formalism': 'TDFOL'
            })
        
        # Permission examples
        if any(word in query.lower() for word in ['may', 'can', 'allowed', 'permission']):
            examples.append({
                'input': 'Employees may work from home on Fridays.',
                'output': 'PERMISSION(employee(X), work_from_home(X, friday))',
                'formalism': 'TDFOL'
            })
        
        # Prohibition examples
        if any(word in query.lower() for word in ['must not', 'cannot', 'prohibited', 'forbidden']):
            examples.append({
                'input': 'Students must not cheat on exams.',
                'output': 'PROHIBITION(student(X), cheat_on_exam(X))',
                'formalism': 'TDFOL'
            })
        
        # General FOL examples
        if not examples:
            examples.append({
                'input': 'All humans are mortal.',
                'output': 'FORALL x: human(x) -> mortal(x)',
                'formalism': 'FOL'
            })
            examples.append({
                'input': 'If it rains, the ground gets wet.',
                'output': 'rains() -> wet(ground)',
                'formalism': 'FOL'
            })
        
        return examples
    
    def _get_ontology_context(self, result: Any) -> Dict[str, Any]:
        """Extract ontology context from RAG result.
        
        Args:
            result: RAG query result
            
        Returns:
            Ontology context dictionary
        """
        ontology = {
            'entities': [],
            'relationships': [],
            'constraints': []
        }
        
        if hasattr(result, 'logical_entities'):
            for entity in result.logical_entities:
                ontology['entities'].append({
                    'type': getattr(entity, 'entity_type', 'unknown'),
                    'text': getattr(entity, 'text', ''),
                    'properties': getattr(entity, 'properties', {})
                })
        
        return ontology
    
    def _get_similar_theorems(self, result: Any) -> List[Dict[str, Any]]:
        """Extract similar theorems from RAG result.
        
        Args:
            result: RAG query result
            
        Returns:
            List of similar theorems
        """
        theorems = []
        
        if hasattr(result, 'related_theorems'):
            for theorem_data in result.related_theorems:
                if isinstance(theorem_data, tuple) and len(theorem_data) >= 2:
                    theorems.append({
                        'statement': theorem_data[0],
                        'confidence': theorem_data[1],
                        'formalism': theorem_data[2] if len(theorem_data) > 2 else 'FOL'
                    })
        
        return theorems
    
    def build_prompt(
        self,
        text: str,
        context: RAGContext,
        formalism: str = "TDFOL"
    ) -> str:
        """Build context-aware prompt for logic extraction.
        
        Args:
            text: Text to extract logic from
            context: RAG context with relevant information
            formalism: Target logic formalism
            
        Returns:
            Complete prompt with context
        """
        prompt_parts = []
        
        # Add task description
        prompt_parts.append(f"Extract logical statements from the following text in {formalism} format.")
        
        # Add few-shot examples
        if context.few_shot_examples:
            prompt_parts.append("\nExamples:")
            for i, example in enumerate(context.few_shot_examples, 1):
                prompt_parts.append(f"\nExample {i}:")
                prompt_parts.append(f"Input: {example['input']}")
                prompt_parts.append(f"Output: {example['output']}")
        
        # Add ontology context
        if context.ontology_context.get('entities'):
            prompt_parts.append("\nRelevant entities:")
            for entity in context.ontology_context['entities'][:5]:
                prompt_parts.append(f"- {entity['type']}: {entity['text']}")
        
        # Add similar theorems
        if context.similar_theorems:
            prompt_parts.append("\nSimilar theorems:")
            for theorem in context.similar_theorems[:3]:
                prompt_parts.append(f"- {theorem['statement']} (confidence: {theorem['confidence']:.2f})")
        
        # Add the actual text to process
        prompt_parts.append(f"\nNow extract logic from:\n{text}")
        prompt_parts.append(f"\nOutput in {formalism} format:")
        
        return "\n".join(prompt_parts)
    
    def add_successful_extraction(
        self,
        input_text: str,
        output_formula: str,
        formalism: str,
        confidence: float
    ) -> None:
        """Store a successful extraction as a future example.
        
        Args:
            input_text: Input text that was processed
            output_formula: Extracted logical formula
            formalism: Logic formalism used
            confidence: Confidence in the extraction
        """
        # Only store high-confidence extractions
        if confidence < 0.7:
            return
        
        example = {
            'input': input_text,
            'output': output_formula,
            'formalism': formalism,
            'confidence': confidence
        }
        
        # Store in RAG system if available
        if self.is_available():
            try:
                # Add to knowledge graph as a successful pattern
                self.rag_system.ingest_document(
                    f"Example: {input_text} -> {output_formula}",
                    f"example_{hashlib.md5(input_text.encode()).hexdigest()}"
                )
            except Exception as e:
                logger.error(f"Error storing extraction in RAG: {e}")
        
        # Also store in local cache for quick access
        cache_key = self._get_example_cache_key(input_text)
        if cache_key not in self.example_cache:
            self.example_cache[cache_key] = []
        self.example_cache[cache_key].append(example)
    
    def _get_cache_key(self, query: str) -> str:
        """Generate cache key for query.
        
        Args:
            query: Query text
            
        Returns:
            Cache key string
        """
        return hashlib.md5(query.encode()).hexdigest()
    
    def _get_example_cache_key(self, query: str) -> str:
        """Generate cache key for examples based on query type.
        
        Args:
            query: Query text
            
        Returns:
            Example cache key
        """
        # Extract key terms to categorize examples
        key_terms = []
        for term in ['obligation', 'permission', 'prohibition', 'temporal', 'conditional']:
            if term in query.lower():
                key_terms.append(term)
        
        if not key_terms:
            key_terms.append('general')
        
        return '_'.join(sorted(key_terms))
    
    def _update_stats(self, context: RAGContext) -> None:
        """Update statistics based on retrieved context.
        
        Args:
            context: Retrieved context
        """
        # Update running averages
        n = self.stats.queries
        
        # Update average documents retrieved
        new_docs = len(context.relevant_documents)
        self.stats.avg_documents_retrieved = (
            (self.stats.avg_documents_retrieved * (n - 1) + new_docs) / n
        )
        
        # Update average examples retrieved
        new_examples = len(context.few_shot_examples)
        self.stats.avg_examples_retrieved = (
            (self.stats.avg_examples_retrieved * (n - 1) + new_examples) / n
        )
    
    def get_statistics(self) -> RAGStatistics:
        """Get RAG integration statistics.
        
        Returns:
            RAGStatistics object
        """
        return self.stats
    
    def clear_cache(self) -> None:
        """Clear all caches."""
        self.context_cache.clear()
        self.example_cache.clear()
        logger.info("RAG caches cleared")
