"""
LLM Integration for GraphRAG with Query Optimization

This module provides integration between the LLM interface, RAG Query Optimizer,
and the GraphRAG system, specifically for enhancing cross-document reasoning
with LLM capabilities and optimized knowledge graph traversal.

Main components:
- GraphRAGLLMProcessor: Processes graph-based data using LLMs with query optimization
- ReasoningEnhancer: Enhances cross-document reasoning with optimized LLM capabilities
- DomainSpecificProcessor: Tailors reasoning for specific knowledge domains
- GraphRAGPerformanceMonitor: Tracks and optimizes LLM performance in GraphRAG tasks

This module integrates with the optimizers/graphrag/query_optimizer module to provide optimized
graph traversal strategies for different knowledge graph types (Wikipedia-derived
and IPLD-based), improving the quality and performance of cross-document reasoning.
"""

import json
import time
import logging
import traceback
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Callable, TYPE_CHECKING

import numpy as np

from ipfs_datasets_py.ml.llm.llm_interface import (
    LLMInterface, 
    LLMInterfaceFactory, 
    GraphRAGPromptTemplates,
    PromptLibrary, 
    AdaptivePrompting, 
)
from ipfs_datasets_py.ml.embeddings.ipfs_knn_index import IPFSKnnIndex # Added import
from ipfs_datasets_py.processors.storage.ipld.knowledge_graph import IPLDKnowledgeGraph # Added import

# Import UnifiedGraphRAGQueryOptimizer conditionally to avoid circular imports
if TYPE_CHECKING:
    from ipfs_datasets_py.optimizers.graphrag.query_optimizer import UnifiedGraphRAGQueryOptimizer


class GraphRAGPerformanceMonitor:
    """
    Tracks and optimizes LLM performance in GraphRAG tasks.

    This class monitors the performance of LLM interactions in GraphRAG tasks,
    collects metrics, and provides insights for optimization.
    """

    def __init__(self, max_history: int = 1000):
        """
        Initialize performance monitor.

        Args:
            max_history: Maximum number of interactions to track
        """
        self.max_history = max_history
        self._history: List[Dict[str, Any]] = []
        self._task_metrics: Dict[str, Dict[str, Any]] = {}
        self._model_metrics: Dict[str, Dict[str, Any]] = {}
        self._latency_tracker: Dict[str, List[float]] = {}
        self._error_tracker: Dict[str, int] = {}

    def record_interaction(
        self,
        task: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency: float,
        success: bool,
        error_msg: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record an LLM interaction.

        Args:
            task: Type of task performed
            model: Name of the model used
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            latency: Time taken for the interaction
            success: Whether the interaction was successful
            error_msg: Error message if unsuccessful
            metadata: Additional metadata
        """
        interaction = {
            "timestamp": datetime.now().isoformat(),
            "task": task,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "latency": latency,
            "success": success,
            "error_msg": error_msg,
            "metadata": metadata or {}
        }

        # Add to history
        self._history.append(interaction)
        if len(self._history) > self.max_history:
            self._history.pop(0)

        # Update task metrics
        if task not in self._task_metrics:
            self._task_metrics[task] = {
                "count": 0,
                "success_count": 0,
                "total_tokens": 0,
                "total_latency": 0,
                "error_count": 0
            }

        self._task_metrics[task]["count"] += 1
        if success:
            self._task_metrics[task]["success_count"] += 1
        else:
            self._task_metrics[task]["error_count"] += 1

        self._task_metrics[task]["total_tokens"] += input_tokens + output_tokens
        self._task_metrics[task]["total_latency"] += latency

        # Update model metrics
        if model not in self._model_metrics:
            self._model_metrics[model] = {
                "count": 0,
                "success_count": 0,
                "total_tokens": 0,
                "total_latency": 0,
                "error_count": 0
            }

        self._model_metrics[model]["count"] += 1
        if success:
            self._model_metrics[model]["success_count"] += 1
        else:
            self._model_metrics[model]["error_count"] += 1

        self._model_metrics[model]["total_tokens"] += input_tokens + output_tokens
        self._model_metrics[model]["total_latency"] += latency

        # Update latency tracker
        latency_key = f"{model}:{task}"
        if latency_key not in self._latency_tracker:
            self._latency_tracker[latency_key] = []

        self._latency_tracker[latency_key].append(latency)
        if len(self._latency_tracker[latency_key]) > 100:
            self._latency_tracker[latency_key].pop(0)

        # Update error tracker
        if not success and error_msg:
            if error_msg not in self._error_tracker:
                self._error_tracker[error_msg] = 0

            self._error_tracker[error_msg] += 1

    def get_task_metrics(self, task: Optional[str] = None) -> Dict[str, Any]:
        """
        Get metrics for a specific task or all tasks.

        Args:
            task: Specific task to get metrics for (all if None)

        Returns:
            Task metrics
        """
        if task:
            if task not in self._task_metrics:
                return {}

            metrics = self._task_metrics[task].copy()
            metrics["success_rate"] = (
                metrics["success_count"] / metrics["count"]
                if metrics["count"] > 0 else 0
            )
            metrics["avg_tokens"] = (
                metrics["total_tokens"] / metrics["count"]
                if metrics["count"] > 0 else 0
            )
            metrics["avg_latency"] = (
                metrics["total_latency"] / metrics["count"]
                if metrics["count"] > 0 else 0
            )

            return metrics
        else:
            # Return metrics for all tasks
            result = {}
            for task_name, metrics in self._task_metrics.items():
                task_result = metrics.copy()
                task_result["success_rate"] = (
                    task_result["success_count"] / task_result["count"]
                    if task_result["count"] > 0 else 0
                )
                task_result["avg_tokens"] = (
                    task_result["total_tokens"] / task_result["count"]
                    if task_result["count"] > 0 else 0
                )
                task_result["avg_latency"] = (
                    task_result["total_latency"] / task_result["count"]
                    if task_result["count"] > 0 else 0
                )

                result[task_name] = task_result

            return result

    def get_model_metrics(self, model: Optional[str] = None) -> Dict[str, Any]:
        """
        Get metrics for a specific model or all models.

        Args:
            model: Specific model to get metrics for (all if None)

        Returns:
            Model metrics
        """
        if model:
            if model not in self._model_metrics:
                return {}

            metrics = self._model_metrics[model].copy()
            metrics["success_rate"] = (
                metrics["success_count"] / metrics["count"]
                if metrics["count"] > 0 else 0
            )
            metrics["avg_tokens"] = (
                metrics["total_tokens"] / metrics["count"]
                if metrics["count"] > 0 else 0
            )
            metrics["avg_latency"] = (
                metrics["total_latency"] / metrics["count"]
                if metrics["count"] > 0 else 0
            )

            return metrics
        else:
            # Return metrics for all models
            result = {}
            for model_name, metrics in self._model_metrics.items():
                model_result = metrics.copy()
                model_result["success_rate"] = (
                    model_result["success_count"] / model_result["count"]
                    if model_result["count"] > 0 else 0
                )
                model_result["avg_tokens"] = (
                    model_result["total_tokens"] / model_result["count"]
                    if model_result["count"] > 0 else 0
                )
                model_result["avg_latency"] = (
                    model_result["total_latency"] / model_result["count"]
                    if model_result["count"] > 0 else 0
                )

                result[model_name] = model_result

            return result

    def get_recent_interactions(self, count: int = 10, task: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get recent interactions.

        Args:
            count: Number of interactions to retrieve
            task: Filter by task type

        Returns:
            List of recent interactions
        """
        if task:
            filtered = [i for i in self._history if i["task"] == task]
            return filtered[-count:]
        else:
            return self._history[-count:]

    def get_error_summary(self) -> Dict[str, int]:
        """
        Get summary of errors.

        Returns:
            Dictionary of error messages and their counts
        """
        return self._error_tracker.copy()

    def get_latency_percentiles(
        self,
        model: Optional[str] = None,
        task: Optional[str] = None
    ) -> Dict[str, float]:
        """
        Get latency percentiles.

        Args:
            model: Filter by model name
            task: Filter by task type

        Returns:
            Dictionary of percentiles and their values
        """
        latencies = []

        if model and task:
            key = f"{model}:{task}"
            latencies = self._latency_tracker.get(key, [])
        elif model:
            for key, values in self._latency_tracker.items():
                if key.startswith(f"{model}:"):
                    latencies.extend(values)
        elif task:
            for key, values in self._latency_tracker.items():
                if key.endswith(f":{task}"):
                    latencies.extend(values)
        else:
            for values in self._latency_tracker.values():
                latencies.extend(values)

        if not latencies:
            return {}

        latencies.sort()
        n = len(latencies)

        return {
            "p50": latencies[int(n * 0.5)] if n > 0 else 0,
            "p90": latencies[int(n * 0.9)] if n > 0 else 0,
            "p95": latencies[int(n * 0.95)] if n > 0 else 0,
            "p99": latencies[int(n * 0.99)] if n > 0 else 0,
            "min": latencies[0] if n > 0 else 0,
            "max": latencies[-1] if n > 0 else 0,
            "mean": sum(latencies) / n if n > 0 else 0
        }


class DomainSpecificProcessor:
    """
    Tailors reasoning for specific knowledge domains.

    This class provides domain-specific processing for GraphRAG tasks,
    adapting the reasoning approach and prompt templates to different
    knowledge domains and content types.
    """

    # Domain definitions with associated entity types and relationship patterns
    DOMAINS = {
        "academic": {
            "entity_types": ["paper", "author", "concept", "methodology", "finding"],
            "relationship_types": ["authored_by", "cites", "uses", "confirms", "contradicts"],
            "prompt_tags": ["academic", "research"]
        },
        "medical": {
            "entity_types": ["condition", "treatment", "medication", "procedure", "symptom"],
            "relationship_types": ["treats", "causes", "diagnoses", "prevents", "indicates"],
            "prompt_tags": ["medical", "healthcare"]
        },
        "legal": {
            "entity_types": ["case", "statute", "regulation", "court", "party"],
            "relationship_types": ["cites", "overturns", "interprets", "applies", "rules_on"],
            "prompt_tags": ["legal", "judicial"]
        },
        "financial": {
            "entity_types": ["company", "stock", "market", "report", "metric"],
            "relationship_types": ["reports", "competes_with", "acquired", "invests_in", "correlates_with"],
            "prompt_tags": ["financial", "business"]
        },
        "technical": {
            "entity_types": ["component", "system", "function", "module", "interface"],
            "relationship_types": ["depends_on", "implements", "extends", "calls", "configures"],
            "prompt_tags": ["technical", "software"]
        }
    }

    def __init__(
        self,
        adaptive_prompting: AdaptivePrompting,
        default_domain: str = "academic"
    ):
        """
        Initialize domain-specific processor.

        Args:
            adaptive_prompting: Adaptive prompting module
            default_domain: Default domain to use if detection fails
        """
        self.adaptive_prompting = adaptive_prompting
        self.default_domain = default_domain
        self._domain_detectors: Dict[str, Callable[[Dict[str, Any]], float]] = {}
        self._initialize_domain_rules()

    def _initialize_domain_rules(self) -> None:
        """Initialize domain detection rules."""
        # Add rules for domain detection to adaptive prompting
        for domain, info in self.DOMAINS.items():
            # Create domain detection function
            detector = self._create_domain_detector(domain, info)
            self._domain_detectors[domain] = detector

            # Create template selection function
            selector = self._create_template_selector(domain, info)

            # Add rule to adaptive prompting
            self.adaptive_prompting.add_rule(
                name=f"domain_{domain}",
                condition=lambda ctx, d=domain: self._is_domain_applicable(ctx, d),
                template_selector=selector,
                priority=10  # Domain rules have high priority
            )

    def _create_domain_detector(
        self,
        domain: str,
        info: Dict[str, Any]
    ) -> Callable[[Dict[str, Any]], float]:
        """
        Create domain detection function.

        Args:
            domain: Domain name
            info: Domain information

        Returns:
            Function that detects domain applicability
        """
        def detector(context: Dict[str, Any]) -> float:
            """Detect domain applicability."""
            if 'graph_info' not in context:
                return 0.0

            graph_info = context['graph_info']

            # Check entity types
            entity_score = 0.0
            if 'entity_types' in graph_info:
                domain_types = set(info['entity_types'])
                graph_types = set(graph_info['entity_types'])
                if domain_types & graph_types:  # Intersection
                    entity_score = len(domain_types & graph_types) / len(domain_types)

            # Check relationship types
            relation_score = 0.0
            if 'relationship_types' in graph_info:
                domain_relations = set(info['relationship_types'])
                graph_relations = set(graph_info['relationship_types'])
                if domain_relations & graph_relations:  # Intersection
                    relation_score = len(domain_relations & graph_relations) / len(domain_relations)

            # Check document metadata
            metadata_score = 0.0
            if 'document_metadata' in graph_info:
                metadata = graph_info['document_metadata']
                if domain.lower() in str(metadata).lower():
                    metadata_score = 0.5

            # Check query content
            query_score = 0.0
            if 'query' in context:
                query = context['query'].lower()
                if domain.lower() in query:
                    query_score = 0.5
                for entity_type in info['entity_types']:
                    if entity_type.lower() in query:
                        query_score += 0.1
                for relation_type in info['relationship_types']:
                    if relation_type.lower().replace('_', ' ') in query:
                        query_score += 0.1
                query_score = min(query_score, 1.0)

            # Combine scores
            combined_score = 0.4 * entity_score + 0.3 * relation_score + 0.2 * metadata_score + 0.1 * query_score
            return combined_score

        return detector

    def _create_template_selector(
        self,
        domain: str,
        info: Dict[str, Any]
    ) -> Callable[[Dict[str, Any]], Tuple[str, Optional[str]]]:
        """
        Create template selection function.

        Args:
            domain: Domain name
            info: Domain information

        Returns:
            Function that selects templates based on domain
        """
        def selector(context: Dict[str, Any]) -> Tuple[str, Optional[str]]:
            """Select template based on domain."""
            task = context.get('task', '')

            # Try to find template with domain-specific tag
            domain_tags = info.get('prompt_tags', [])

            if task == 'cross_document_reasoning':
                if 'academic' in domain_tags:
                    return ('cross_document_reasoning', '1.1.0')  # Academic version
                else:
                    return ('cross_document_reasoning', None)  # Latest version

            # For other tasks, return task name and latest version
            return (task, None)

        return selector

    def _is_domain_applicable(self, context: Dict[str, Any], domain: str) -> bool:
        """
        Check if domain is applicable to context.

        Args:
            context: Context dictionary
            domain: Domain to check

        Returns:
            True if domain is applicable
        """
        if domain not in self._domain_detectors:
            return False

        detector = self._domain_detectors[domain]
        score = detector(context)

        # Consider domain applicable if score is above threshold
        return score > 0.6

    def detect_domain(self, context: Dict[str, Any]) -> str:
        """
        Detect domain from context.

        Args:
            context: Context dictionary

        Returns:
            Detected domain or default domain
        """
        scores = {
            domain: detector(context)
            for domain, detector in self._domain_detectors.items()
        }

        if not scores:
            return self.default_domain

        # Get domain with highest score above threshold
        best_domain = max(scores.items(), key=lambda x: x[1])
        if best_domain[1] > 0.6:
            return best_domain[0]

        return self.default_domain

    def get_domain_info(self, domain: str) -> Dict[str, Any]:
        """
        Get information about a domain.

        Args:
            domain: Domain name

        Returns:
            Domain information
        """
        return self.DOMAINS.get(domain, self.DOMAINS[self.default_domain])

    def enhance_context_with_domain(
        self,
        context: Dict[str, Any],
        domain: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Enhance context with domain-specific information.

        Args:
            context: Context dictionary
            domain: Domain to use (detected if None)

        Returns:
            Enhanced context
        """
        if domain is None:
            domain = self.detect_domain(context)

        domain_info = self.get_domain_info(domain)

        # Create enhanced context
        enhanced = context.copy()
        enhanced['domain'] = domain
        enhanced['domain_info'] = domain_info

        return enhanced


class GraphRAGLLMProcessor:
    """
    Processor for enhancing GraphRAG operations with LLM capabilities.

    This class serves as the integration layer between the VectorAugmentedGraphDataset
    and the LLM interface, providing methods for using LLMs to enhance
    various GraphRAG operations.
    """

    def __init__(
        self,
        llm_interface: Optional[LLMInterface] = None,
        prompt_library: Optional[PromptLibrary] = None,
        performance_monitor: Optional[GraphRAGPerformanceMonitor] = None,
        query_optimizer: Optional['UnifiedGraphRAGQueryOptimizer'] = None
    ):
        """
        Initialize GraphRAG LLM processor.

        Args:
            llm_interface: LLM interface to use (creates default if None)
            prompt_library: Prompt library for managing templates
            performance_monitor: Monitor for tracking performance
            query_optimizer: Query optimizer for GraphRAG operations
        """
        self.llm = llm_interface or LLMInterfaceFactory.create()
        self.prompt_library = prompt_library or PromptLibrary()
        self.templates = GraphRAGPromptTemplates(self.prompt_library)
        self.performance_monitor = performance_monitor or GraphRAGPerformanceMonitor()

        # Create adaptive prompting module
        self.adaptive_prompting = AdaptivePrompting(self.prompt_library)

        # Create domain-specific processor
        self.domain_processor = DomainSpecificProcessor(self.adaptive_prompting)

        # Initialize query optimizer if provided
        self.query_optimizer = query_optimizer

        # Cache for LLM responses to reduce redundant calls
        self._response_cache = {}

        # Initialize vector and graph stores
        # TODO: Allow passing configured stores or config details
        try:
            # Use default dimension of 768 for embedding vectors
            self.vector_store = IPFSKnnIndex(dimension=768)
            logging.info("Initialized default IPFSKnnIndex as vector_store.")
        except Exception as e:
            logging.error(f"Failed to initialize IPFSKnnIndex: {e}")
            self.vector_store = None

        try:
            self.graph_store = IPLDKnowledgeGraph()
            logging.info("Initialized default IPLDKnowledgeGraph as graph_store.")
        except Exception as e:
            logging.error(f"Failed to initialize IPLDKnowledgeGraph: {e}")
            self.graph_store = None

    # --- Retrieval Methods (Implementations based on Optimizer requirements) ---

    def search_by_vector(self, vector: np.ndarray, top_k: int = 5, min_score: float = 0.5, **kwargs) -> List[Dict[str, Any]]:
        """Perform vector search using the initialized vector store."""
        if not self.vector_store:
            logging.error("Vector store not initialized in GraphRAGLLMProcessor.")
            return []
        try:
            # Assuming vector_store has a search method similar to IPFSKnnIndex
            # The actual result format might need adjustment based on the store's implementation
            search_results = self.vector_store.search(vector, top_k=top_k)

            # Filter by min_score and format
            formatted_results = []
            for result in search_results:
                 if result.score >= min_score:
                     formatted_results.append({
                         "id": result.id, # Assuming result has 'id'
                         "score": result.score, # Assuming result has 'score'
                         "metadata": result.metadata, # Assuming result has 'metadata'
                         "source": "vector" # Mark source for ranking
                     })
            return formatted_results
        except AttributeError:
             logging.error(f"Vector store ({type(self.vector_store)}) does not have a 'search' method.")
             return []
        except Exception as e:
            logging.error(f"Error during vector search: {e}")
            return []

    def expand_by_graph(self, entities: List[Dict[str, Any]], max_depth: int = 2, edge_types: Optional[List[str]] = None, **kwargs) -> List[Dict[str, Any]]:
        """Perform graph expansion using the initialized graph store."""
        if not self.graph_store:
            logging.error("Graph store not initialized in GraphRAGLLMProcessor.")
            return entities # Return original entities if no graph store

        if not entities:
            return []

        try:
            # Assuming graph_store has a method like traverse_from_entities
            # Need to adapt input/output based on actual graph store implementation
            seed_entities_info = [{"id": e["id"], "metadata": e.get("metadata", {})} for e in entities if "id" in e]

            # Call graph traversal (adjust parameters as needed for the actual method)
            traversed_entities = self.graph_store.traverse_from_entities(
                entities=seed_entities_info, # Pass necessary info
                relationship_types=edge_types,
                max_depth=max_depth
            )

            # Combine original entities with traversed ones, marking source
            # Need a strategy to handle duplicates and combine info/scores
            combined_results = entities[:] # Start with original vector results
            existing_ids = {e["id"] for e in entities}

            for trav_entity in traversed_entities:
                 # Assuming traversed_entity is a dict with 'id', 'properties', etc.
                 entity_id = trav_entity.get("id")
                 if entity_id and entity_id not in existing_ids:
                     combined_results.append({
                         "id": entity_id,
                         "score": 0.5, # Assign a default graph score or derive one
                         "metadata": trav_entity.get("properties", {}),
                         "source": "graph" # Mark source
                     })
                     existing_ids.add(entity_id)
                 # TODO: Add logic to potentially update existing entities if found via graph

            return combined_results
        except AttributeError:
             logging.error(f"Graph store ({type(self.graph_store)}) does not have a 'traverse_from_entities' method.")
             return entities # Return original entities
        except Exception as e:
            logging.error(f"Error during graph expansion: {e}")
            return entities # Return original entities on error

    def rank_results(self, results: List[Dict[str, Any]], vector_weight: float = 0.7, graph_weight: float = 0.3, **kwargs) -> List[Dict[str, Any]]:
        """Rank combined results from vector search and graph expansion."""
        """Rank combined results from vector search and graph expansion."""

        if not results:
            return []

        # Separate results by source
        vector_results = [r for r in results if r.get("source") == "vector"]
        graph_results = [r for r in results if r.get("source") == "graph"]
        other_results = [r for r in results if r.get("source") not in ["vector", "graph"]]

        # --- Score Normalization (Min-Max Scaling) ---
        # Normalize vector scores (assuming higher is better, scale 0-1)
        vector_scores = [r.get("score", 0.0) for r in vector_results]
        min_vec_score = min(vector_scores) if vector_scores else 0.0
        max_vec_score = max(vector_scores) if vector_scores else 1.0
        range_vec = max_vec_score - min_vec_score
        if range_vec == 0: range_vec = 1.0 # Avoid division by zero

        for r in vector_results:
            r["normalized_score"] = (r.get("score", 0.0) - min_vec_score) / range_vec

        # Normalize graph scores (assuming higher is better, scale 0-1)
        # Graph scores might represent distance or relevance, adjust logic as needed
        graph_scores = [r.get("score", 0.0) for r in graph_results]
        min_graph_score = min(graph_scores) if graph_scores else 0.0
        max_graph_score = max(graph_scores) if graph_scores else 1.0
        range_graph = max_graph_score - min_graph_score
        if range_graph == 0: range_graph = 1.0 # Avoid division by zero

        for r in graph_results:
             # Assuming higher score is better for graph results too
            r["normalized_score"] = (r.get("score", 0.0) - min_graph_score) / range_graph

        # Assign default normalized score for others
        for r in other_results:
            r["normalized_score"] = r.get("score", 0.0) # Or assign a fixed low score like 0.1

        # --- Weighted Combination ---
        combined_results = vector_results + graph_results + other_results
        final_ranked_results = []
        for result in combined_results:
            norm_score = result.get("normalized_score", 0.0)
            source = result.get("source", "unknown")

            if source == "vector":
                final_score = norm_score * vector_weight
            elif source == "graph":
                final_score = norm_score * graph_weight
            else:
                final_score = norm_score * 0.1 # Lower weight for unknown sources

            result["final_score"] = final_score
            final_ranked_results.append(result)

        # Sort by the final combined score
        return sorted(final_ranked_results, key=lambda x: x.get("final_score", 0.0), reverse=True)

    # --- Core LLM Processing Methods ---

    def analyze_evidence_chain(
        self,
        doc1: Dict[str, Any],
        doc2: Dict[str, Any],
        entity: Dict[str, Any],
        doc1_context: str,
        doc2_context: str,
        graph_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Analyze evidence chain between two documents connected by an entity.

        Args:
            doc1: First document metadata
            doc2: Second document metadata
            entity: Connecting entity metadata
            doc1_context: Relevant context from first document
            doc2_context: Relevant context from second document
            graph_info: Additional information about the graph

        Returns:
            Analysis of the evidence chain
        """
        # Create cache key
        key_str = f"{doc1['id']}:{doc2['id']}:{entity['id']}"
        cache_key = f"evidence_chain:{hash(key_str)}"

        # Check cache
        if cache_key in self._response_cache:
            return self._response_cache[cache_key]

        # Prepare context for adaptive prompting
        context = {
            "task": "evidence_chain_analysis",
            "doc1": doc1,
            "doc2": doc2,
            "entity": entity,
            "graph_info": graph_info or {}
        }

        # Create a query to help with domain detection
        entity_name = entity.get('name', entity['id'])
        entity_type = entity.get('type', 'Entity')
        doc1_title = doc1.get('title', f"Document {doc1['id']}")
        doc2_title = doc2.get('title', f"Document {doc2['id']}")
        context["query"] = f"Analyze the connection between {doc1_title} and {doc2_title} through the {entity_type} {entity_name}"

        # Detect domain and enhance context
        enhanced_context = self.domain_processor.enhance_context_with_domain(context)

        # Update adaptive prompting context
        self.adaptive_prompting.update_context(enhanced_context)

        # Get the appropriate template using adaptive prompting
        template = self.adaptive_prompting.select_prompt(
            task="evidence_chain_analysis",
            default_template="evidence_chain_analysis"
        )

        # Log parameters for performance monitoring
        start_time = time.time()

        try:
            # Format prompt
            prompt = template.format(
                doc1=doc1.get('title', f"Document {doc1['id']}"),
                doc2=doc2.get('title', f"Document {doc2['id']}"),
                entity=entity.get('name', entity['id']),
                entity_type=entity.get('type', 'Entity'),
                doc1_context=doc1_context,
                doc2_context=doc2_context
            )

            # Get schema based on domain
            domain = enhanced_context.get("domain", "academic")
            schema = self._get_evidence_chain_schema(domain)

            # Get structured output
            result = self.llm.generate_with_structured_output(prompt, schema)

            # Record successful interaction
            latency = time.time() - start_time
            self.performance_monitor.record_interaction(
                task="evidence_chain_analysis",
                model=self.llm.config.model_name,
                input_tokens=self.llm.count_tokens(prompt),
                output_tokens=self.llm.count_tokens(json.dumps(result)),
                latency=latency,
                success=True,
                metadata={
                    "domain": domain,
                    "doc1_id": doc1.get("id", "unknown"),
                    "doc2_id": doc2.get("id", "unknown"),
                    "entity_id": entity.get("id", "unknown")
                }
            )

            # Cache result
            self._response_cache[cache_key] = result

            return result

        except Exception as e:
            # Record failed interaction
            latency = time.time() - start_time
            error_msg = str(e)
            self.performance_monitor.record_interaction(
                task="evidence_chain_analysis",
                model=self.llm.config.model_name,
                input_tokens=self.llm.count_tokens(prompt) if "prompt" in locals() else 0,
                output_tokens=0,
                latency=latency,
                success=False,
                error_msg=error_msg,
                metadata={
                    "domain": enhanced_context.get("domain", "unknown"),
                    "doc1_id": doc1.get("id", "unknown"),
                    "doc2_id": doc2.get("id", "unknown"),
                    "entity_id": entity.get("id", "unknown")
                }
            )

            # Log error
            logging.error(f"Error in analyze_evidence_chain: {error_msg}")
            logging.debug(traceback.format_exc())

            # Return basic result on error
            return {
                "relationship_type": "unknown",
                "explanation": f"Error analyzing evidence chain: {error_msg}",
                "inference": "Unable to generate inference due to error",
                "confidence": 0.0
            }

    def _get_evidence_chain_schema(self, domain: str) -> Dict[str, Any]:
        """
        Get evidence chain schema for a specific domain.

        Args:
            domain: Domain name

        Returns:
            JSON schema for evidence chain analysis
        """
        # Base schema
        base_schema = {
            "type": "object",
            "properties": {
                "relationship_type": {
                    "type": "string",
                    "enum": ["complementary", "contradictory", "identical", "unrelated"]
                },
                "explanation": {"type": "string"},
                "inference": {"type": "string"},
                "confidence": {"type": "number"}
            },
            "required": ["relationship_type", "explanation", "inference", "confidence"]
        }

        # Domain-specific enhancements
        if domain == "academic":
            base_schema["properties"]["scholarly_impact"] = {"type": "string"}
            base_schema["properties"]["research_implications"] = {"type": "string"}
        elif domain == "medical":
            base_schema["properties"]["clinical_relevance"] = {"type": "string"}
            base_schema["properties"]["certainty_level"] = {"type": "string", "enum": ["high", "moderate", "low", "inconclusive"]}
        elif domain == "legal":
            base_schema["properties"]["precedent_relationship"] = {"type": "string", "enum": ["controlling", "persuasive", "distinguishable", "not_applicable"]}
            base_schema["properties"]["legal_significance"] = {"type": "string"}
        elif domain == "financial":
            base_schema["properties"]["market_implications"] = {"type": "string"}
            base_schema["properties"]["investment_relevance"] = {"type": "string"}
        elif domain == "technical":
            base_schema["properties"]["compatibility_impacts"] = {"type": "string"}
            base_schema["properties"]["implementation_considerations"] = {"type": "string"}

        return base_schema

    def identify_knowledge_gaps(
        self,
        entity: Dict[str, Any],
        doc1_info: str,
        doc2_info: str
    ) -> Dict[str, Any]:
        """
        Identify knowledge gaps between documents about an entity.

        Args:
            entity: Entity metadata
            doc1_info: Information from first document
            doc2_info: Information from second document

        Returns:
            Identified knowledge gaps
        """
        # Create cache key
        entity_info = f'{entity["id"]}:{doc1_info[:50]}:{doc2_info[:50]}'
        cache_key = f"knowledge_gaps:{hash(entity_info)}"

        # Check cache
        if cache_key in self._response_cache:
            return self._response_cache[cache_key]

        # Format prompt
        prompt = self.templates.KNOWLEDGE_GAP_IDENTIFICATION.format(
            entity=entity.get('name', entity['id']),
            doc1_info=doc1_info,
            doc2_info=doc2_info
        )

        # Get structured output
        schema = {
            "type": "object",
            "properties": {
                "gaps_doc1_to_doc2": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "gaps_doc2_to_doc1": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "summary": {"type": "string"}
            },
            "required": ["gaps_doc1_to_doc2", "gaps_doc2_to_doc1", "summary"]
        }

        result = self.llm.generate_with_structured_output(prompt, schema)

        # Cache result
        self._response_cache[cache_key] = result

        return result

    def generate_deep_inference(
        self,
        entity: Dict[str, Any],
        doc1: Dict[str, Any],
        doc2: Dict[str, Any],
        doc1_info: str,
        doc2_info: str,
        relation_type: str,
        knowledge_gaps: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate deep inferences from document relationships.

        Args:
            entity: Entity metadata
            doc1: First document metadata
            doc2: Second document metadata
            doc1_info: Information from first document
            doc2_info: Information from second document
            relation_type: Type of relationship between documents
            knowledge_gaps: Identified knowledge gaps

        Returns:
            Generated inferences
        """
        # Create cache key
        entity_info = f'{entity["id"]}:{doc1["id"]}:{doc2["id"]}:{relation_type}'
        cache_key = f"deep_inference:{hash(entity_info)}"

        # Check cache
        if cache_key in self._response_cache:
            return self._response_cache[cache_key]

        # Format prompt
        prompt = self.templates.DEEP_INFERENCE.format(
            entity_name=entity.get('name', entity['id']),
            entity_type=entity.get('type', 'Entity'),
            doc1_title=doc1.get('title', f"Document {doc1['id']}"),
            doc1_info=doc1_info,
            doc2_title=doc2.get('title', f"Document {doc2['id']}"),
            doc2_info=doc2_info,
            relation_type=relation_type,
            knowledge_gaps=knowledge_gaps.get('summary', 'Not available')
        )

        # Get structured output
        schema = {
            "type": "object",
            "properties": {
                "inferences": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "implications": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "confidence": {"type": "number"},
                "explanation": {"type": "string"}
            },
            "required": ["inferences", "confidence", "explanation"]
        }

        result = self.llm.generate_with_structured_output(prompt, schema)

        # Cache result
        self._response_cache[cache_key] = result

        return result

    def analyze_transitive_relationships(
        self,
        relationship_chain: str
    ) -> Dict[str, Any]:
        """
        Analyze transitive relationships in an entity chain.

        Args:
            relationship_chain: Description of entity relationship chain

        Returns:
            Analysis of transitive relationships
        """
        # Create cache key
        cache_key = f"transitive:{hash(relationship_chain)}"

        # Check cache
        if cache_key in self._response_cache:
            return self._response_cache[cache_key]

        # Format prompt
        prompt = self.templates.TRANSITIVE_ANALYSIS.format(
            relationship_chain=relationship_chain
        )

        # Get structured output
        schema = {
            "type": "object",
            "properties": {
                "transitive_relationships": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "implications": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "confidence": {"type": "number"},
                "explanation": {"type": "string"}
            },
            "required": ["transitive_relationships", "confidence", "explanation"]
        }

        result = self.llm.generate_with_structured_output(prompt, schema)

        # Cache result
        self._response_cache[cache_key] = result

        return result

    def synthesize_cross_document_reasoning(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        connections: str,
        reasoning_depth: str,
        graph_info: Optional[Dict[str, Any]] = None,
        query_vector: Optional[np.ndarray] = None,
        doc_trace_ids: Optional[List[str]] = None,
            root_cids: Optional[List[str]] = None,
            skip_cache: bool = False # Added skip_cache parameter
    ) -> Dict[str, Any]:
        """
        Synthesize information across documents to answer a query, potentially using query optimization.

        Args:
            query: User query
            documents: List of relevant documents
            connections: Description of document connections
            reasoning_depth: Reasoning depth level
            graph_info: Additional information about the graph
            query_vector: Query embedding vector for optimizer
            doc_trace_ids: Document trace IDs for Wikipedia knowledge graphs
            root_cids: Root CIDs for IPLD-based knowledge graphs

        Returns:
            Synthesized answer
        """
        # Create cache key
        cache_key = f"cross_doc:{hash(f'{query}:{reasoning_depth}')}"

        # Check cache
        if cache_key in self._response_cache:
            return self._response_cache[cache_key]

        # Extract entity types, relationship types, and document metadata for domain detection
        entity_types = set()
        relationship_types = set()
        document_metadata = {}

        # Extract entity and relationship information from documents and connections
        for doc in documents:
            if "type" in doc:
                entity_types.add(doc["type"])

            # Extract metadata
            metadata = {k: v for k, v in doc.items() if k not in ["id", "content", "title"]}
            doc_id = doc.get("id", "unknown")
            document_metadata[doc_id] = metadata

        # Format context for domain detection
        context = {
            "task": "cross_document_reasoning",
            "query": query,
            "graph_info": graph_info or {
                "entity_types": list(entity_types),
                "relationship_types": list(relationship_types),
                "document_metadata": document_metadata
            }
        }

        # Start timing for statistics recording (if optimizer exists)
        query_start_time = time.time()
        retrieved_context = []
        execution_info = {}
        optimizer_used = False

        # --- Retrieval Step ---
        if self.query_optimizer and query_vector is not None:
            optimizer_used = True
            try:
                # Prepare query for optimizer
                optimizer_query = {
                    "query_vector": query_vector,
                    "query_text": query,
                    # Pass relevant info if available
                    "doc_trace_ids": doc_trace_ids,
                    "root_cids": root_cids,
                    # Add other potential parameters the optimizer might use
                    "max_vector_results": 10, # Example default
                    "max_traversal_depth": 2, # Example default
                }

                # Use the optimizer's execute_query method for retrieval & budget tracking
                # Pass 'self' as the processor implementing search/expand/rank methods
                retrieved_context, execution_info = self.query_optimizer.execute_query(
                    processor=self,
                    query=optimizer_query,
                    priority="normal", # Or determine priority based on context
                    skip_cache=skip_cache
                )
                # Add optimizer plan to context for adaptive prompting
                if "plan" in execution_info:
                     context["optimized_plan"] = execution_info["plan"]

            except Exception as e:
                logging.error(f"Error during optimized query execution: {str(e)}")
                logging.debug(traceback.format_exc())
                # Fallback or handle error - for now, proceed without retrieved context
                retrieved_context = []
                execution_info = {"error": str(e)}
        else:
            # Fallback: Simple retrieval if no optimizer or vector
            # For now, just use the initially provided documents as context
            # TODO: Implement a basic retrieval fallback if needed
            logging.warning("Query optimizer not used. Using provided documents as context.")
            retrieved_context = documents # Use input documents directly

        # --- LLM Synthesis Step ---
        # Detect domain and enhance context (using potentially optimized context)
        context["retrieved_context"] = retrieved_context # Add retrieved context for domain detection
        enhanced_context = self.domain_processor.enhance_context_with_domain(context)
        domain = enhanced_context.get("domain", "academic")

        # Update adaptive prompting context
        self.adaptive_prompting.update_context(enhanced_context)

        # Get the appropriate template using adaptive prompting
        template = self.adaptive_prompting.select_prompt(
            task="cross_document_reasoning",
            default_template="cross_document_reasoning"
        )
        # Format retrieved context for prompt
        # Use retrieved_context instead of the original documents list
        doc_text = self._format_documents_for_domain(retrieved_context, domain)

        # Enhance connections description (remains the same, based on original input)
        enhanced_connections = connections

        # Log parameters for performance monitoring (using LLM start time)
        llm_start_time = time.time()

        try:
            # Format prompt
            prompt = template.format(
                query=query,
                documents=doc_text,
                connections=enhanced_connections,
                reasoning_depth=reasoning_depth
            )

            # Get domain-specific schema
            schema = self._get_cross_document_reasoning_schema(domain, reasoning_depth)

            # Get structured output
            result = self.llm.generate_with_structured_output(prompt, schema)

            # Record successful interaction
            latency = time.time() - llm_start_time
            self.performance_monitor.record_interaction(
                task="cross_document_reasoning",
                model=self.llm.config.model_name,
                input_tokens=self.llm.count_tokens(prompt),
                output_tokens=self.llm.count_tokens(json.dumps(result)),
                latency=latency,
                success=True,
                metadata={
                    "domain": domain,
                    "reasoning_depth": reasoning_depth,
                    "num_documents": len(retrieved_context), # Use count of retrieved docs
                    "optimizer_used": optimizer_used,
                    "execution_info": execution_info # Include optimizer execution info
                }
            )

            # Enhance result with domain-specific post-processing
            enhanced_result = self._enhance_result_for_domain(result, domain, reasoning_depth)

            # Add optimizer execution info to the final result
            enhanced_result["execution_info"] = execution_info

            # Cache result (using original cache key)
            self._response_cache[cache_key] = enhanced_result

            return enhanced_result

        except Exception as e:
            # Record failed interaction
            latency = time.time() - llm_start_time
            error_msg = str(e)
            self.performance_monitor.record_interaction(
                task="cross_document_reasoning",
                model=self.llm.config.model_name,
                input_tokens=self.llm.count_tokens(prompt) if "prompt" in locals() else 0,
                output_tokens=0,
                latency=latency,
                success=False,
                error_msg=error_msg,
                metadata={
                    "domain": domain,
                    "reasoning_depth": reasoning_depth,
                    "num_documents": len(retrieved_context), # Use count of retrieved docs
                    "optimizer_used": optimizer_used,
                    "execution_info": execution_info # Include optimizer execution info
                }
            )

            # Log error
            logging.error(f"Error in synthesize_cross_document_reasoning: {error_msg}")
            logging.debug(traceback.format_exc())

            # Return basic result on error
            return {
                "answer": f"Error synthesizing information: {error_msg}",
                "reasoning": "Unable to synthesize information due to error",
                "confidence": 0.0,
                "execution_info": execution_info # Include execution info even on error
            }
        # Note: The overall query time recording was moved to the optimizer's execute_query method

    def _format_documents_for_domain(
        self,
        documents: List[Dict[str, Any]],
        domain: str
    ) -> str:
        """
        Format documents based on domain.

        Args:
            documents: List of documents
            domain: Domain name

        Returns:
            Formatted document text
        """
        # Base formatting
        if domain == "academic":
            paper_texts = []
            for i, doc in enumerate(documents):
                title = doc.get('title', f'Document {doc.get("id", i)}')
                authors = doc.get('authors', 'Unknown')
                year = doc.get('year', 'Unknown')
                abstract = doc.get('abstract', doc.get('content', 'No content'))

                paper_text = f"PAPER {i+1}: {title}\n"
                paper_text += f"AUTHORS: {authors}\n"
                paper_text += f"YEAR: {year}\n"
                paper_text += f"ABSTRACT: {abstract}"
                paper_texts.append(paper_text)

            return "\n\n".join(paper_texts)
        elif domain == "medical":
            med_texts = []
            for i, doc in enumerate(documents):
                title = doc.get('title', f'Document {doc.get("id", i)}')
                date = doc.get('date', 'Unknown')
                source = doc.get('source', 'Unknown')
                content = doc.get('content', 'No content')

                med_text = f"CLINICAL DOCUMENT {i+1}: {title}\n"
                med_text += f"DATE: {date}\n"
                med_text += f"SOURCE: {source}\n"
                med_text += f"CONTENT: {content}"
                med_texts.append(med_text)

            return "\n\n".join(med_texts)
        elif domain == "legal":
            legal_texts = []
            for i, doc in enumerate(documents):
                title = doc.get('title', f'Document {doc.get("id", i)}')
                jurisdiction = doc.get('jurisdiction', 'Unknown')
                date = doc.get('date', 'Unknown')
                content = doc.get('content', 'No content')

                legal_text = f"LEGAL DOCUMENT {i+1}: {title}\n"
                legal_text += f"JURISDICTION: {jurisdiction}\n"
                legal_text += f"DATE: {date}\n"
                legal_text += f"CONTENT: {content}"
                legal_texts.append(legal_text)

            return "\n\n".join(legal_texts)
        elif domain == "financial":
            financial_texts = []
            for i, doc in enumerate(documents):
                title = doc.get('title', f'Document {doc.get("id", i)}')
                company = doc.get('company', 'Unknown')
                period = doc.get('period', 'Unknown')
                content = doc.get('content', 'No content')

                financial_text = f"FINANCIAL DOCUMENT {i+1}: {title}\n"
                financial_text += f"COMPANY: {company}\n"
                financial_text += f"PERIOD: {period}\n"
                financial_text += f"CONTENT: {content}"
                financial_texts.append(financial_text)

            return "\n\n".join(financial_texts)
        elif domain == "technical":
            tech_texts = []
            for i, doc in enumerate(documents):
                title = doc.get('title', f'Document {doc.get("id", i)}')
                component = doc.get('component', 'Unknown')
                version = doc.get('version', 'Unknown')
                content = doc.get('content', 'No content')

                tech_text = f"TECHNICAL DOCUMENT {i+1}: {title}\n"
                tech_text += f"COMPONENT: {component}\n"
                tech_text += f"VERSION: {version}\n"
                tech_text += f"CONTENT: {content}"
                tech_texts.append(tech_text)

            return "\n\n".join(tech_texts)
        else:
            # Generic formatting for other domains
            generic_texts = []
            for i, doc in enumerate(documents):
                title = doc.get('title', f'Document {doc.get("id", i)}')
                content = doc.get('content', 'No content')

                generic_text = f"DOCUMENT {i+1}: {title}\n{content}"
                generic_texts.append(generic_text)

            return "\n\n".join(generic_texts)

    def _get_cross_document_reasoning_schema(
        self,
        domain: str,
        reasoning_depth: str
    ) -> Dict[str, Any]:
        """
        Get cross document reasoning schema for a specific domain and reasoning depth.

        Args:
            domain: Domain name
            reasoning_depth: Reasoning depth level

        Returns:
            JSON schema for cross document reasoning
        """
        # Base schema
        base_schema = {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
                "references": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "knowledge_gaps": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["answer", "reasoning", "confidence"]
        }

        # Add depth-specific properties
        if reasoning_depth in ["moderate", "deep"]:
            base_schema["properties"]["evidence_strength"] = {
                "type": "string",
                "enum": ["strong", "moderate", "weak", "inconclusive"]
            }

            if reasoning_depth == "deep":
                base_schema["properties"]["alternative_interpretations"] = {
                    "type": "array",
                    "items": {"type": "string"}
                }
                base_schema["properties"]["implications"] = {
                    "type": "array",
                    "items": {"type": "string"}
                }

        # Add domain-specific properties
        if domain == "academic":
            base_schema["properties"]["research_implications"] = {"type": "string"}
            base_schema["properties"]["future_research_directions"] = {
                "type": "array",
                "items": {"type": "string"}
            }
        elif domain == "medical":
            base_schema["properties"]["clinical_significance"] = {"type": "string"}
            base_schema["properties"]["certainty_level"] = {
                "type": "string",
                "enum": ["high", "moderate", "low", "inconclusive"]
            }
        elif domain == "legal":
            base_schema["properties"]["legal_principle"] = {"type": "string"}
            base_schema["properties"]["precedent_value"] = {
                "type": "string",
                "enum": ["binding", "persuasive", "distinguishable", "not_applicable"]
            }
        elif domain == "financial":
            base_schema["properties"]["market_impact"] = {"type": "string"}
            base_schema["properties"]["risk_assessment"] = {
                "type": "string",
                "enum": ["high", "moderate", "low", "negligible"]
            }
        elif domain == "technical":
            base_schema["properties"]["technical_implications"] = {"type": "string"}
            base_schema["properties"]["implementation_considerations"] = {
                "type": "array",
                "items": {"type": "string"}
            }

        return base_schema

    def _enhance_result_for_domain(
        self,
        result: Dict[str, Any],
        domain: str,
        reasoning_depth: str
    ) -> Dict[str, Any]:
        """
        Enhance result based on domain and reasoning depth.

        Args:
            result: Original result
            domain: Domain name
            reasoning_depth: Reasoning depth level

        Returns:
            Enhanced result
        """
        # Copy the result to avoid modifying the original
        enhanced = result.copy()

        # Add domain and reasoning depth
        enhanced["domain"] = domain
        enhanced["reasoning_depth"] = reasoning_depth

        # Ensure all required fields exist
        if "references" not in enhanced:
            enhanced["references"] = []
        if "knowledge_gaps" not in enhanced:
            enhanced["knowledge_gaps"] = []

        # Add domain-specific enhancements
        if domain == "academic" and reasoning_depth == "deep":
            if "research_implications" in enhanced and "implications" not in enhanced:
                implications = enhanced["research_implications"].split(". ")
                enhanced["implications"] = implications

            if "future_research_directions" in enhanced:
                enhanced["future_work"] = enhanced["future_research_directions"]

        return enhanced


class ReasoningEnhancer:
    """
    Enhances cross-document reasoning with LLM capabilities.

    This class provides a bridge between the VectorAugmentedGraphDataset's
    cross_document_reasoning method and LLM-powered analysis.
    """

    def __init__(
        self,
        llm_processor: Optional[GraphRAGLLMProcessor] = None,
        performance_recorder: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        query_optimizer: Optional['UnifiedGraphRAGQueryOptimizer'] = None
    ):
        """
        Initialize reasoning enhancer.

        Args:
            llm_processor: LLM processor to use (creates default if None)
            performance_recorder: Optional function to record performance metrics
            query_optimizer: Query optimizer for GraphRAG operations
        """
        # Initialize query optimizer first if provided
        self.query_optimizer = query_optimizer

        # Create LLM processor with the query optimizer
        self.processor = llm_processor or GraphRAGLLMProcessor(
            query_optimizer=query_optimizer
        )

        self.performance_recorder = performance_recorder

    def enhance_document_connections(
        self,
        doc1: Dict[str, Any],
        doc2: Dict[str, Any],
        entity: Dict[str, Any],
        doc1_context: str,
        doc2_context: str,
        reasoning_depth: str,
        graph_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Enhance document connection analysis with LLM reasoning.

        Args:
            doc1: First document metadata
            doc2: Second document metadata
            entity: Connecting entity metadata
            doc1_context: Relevant context from first document
            doc2_context: Relevant context from second document
            reasoning_depth: Reasoning depth level
            graph_info: Additional information about the graph

        Returns:
            Enhanced connection analysis
        """
        start_time = time.time()

        try:
            # Basic evidence chain analysis
            evidence_analysis = self.processor.analyze_evidence_chain(
                doc1, doc2, entity, doc1_context, doc2_context, graph_info
            )

            # For basic reasoning, return just the evidence analysis
            if reasoning_depth == "basic":
                result = {
                    "connection_type": evidence_analysis["relationship_type"],
                    "explanation": evidence_analysis["explanation"],
                    "inference": evidence_analysis["inference"],
                    "confidence": evidence_analysis["confidence"],
                    "reasoning_depth": reasoning_depth
                }

                # Record performance if recorder is provided
                if self.performance_recorder:
                    self.performance_recorder("enhance_document_connections", {
                        "reasoning_depth": reasoning_depth,
                        "duration": time.time() - start_time,
                        "success": True,
                        "doc1_id": doc1.get("id", "unknown"),
                        "doc2_id": doc2.get("id", "unknown"),
                        "entity_id": entity.get("id", "unknown")
                    })

                return result

            # For moderate/deep reasoning, add knowledge gap analysis
            knowledge_gaps = self.processor.identify_knowledge_gaps(
                entity, doc1_context, doc2_context
            )

            result = {
                "connection_type": evidence_analysis["relationship_type"],
                "explanation": evidence_analysis["explanation"],
                "inference": evidence_analysis["inference"],
                "confidence": evidence_analysis["confidence"],
                "knowledge_gaps": knowledge_gaps["summary"],
                "specific_gaps": {
                    "doc1_to_doc2": knowledge_gaps["gaps_doc1_to_doc2"],
                    "doc2_to_doc1": knowledge_gaps["gaps_doc2_to_doc1"]
                },
                "reasoning_depth": reasoning_depth
            }

            # Get domain-specific fields if present
            for field in evidence_analysis:
                if field not in ["relationship_type", "explanation", "inference", "confidence"]:
                    result[field] = evidence_analysis[field]

            # For deep reasoning, add additional inference generation
            if reasoning_depth == "deep":
                deep_inference = self.processor.generate_deep_inference(
                    entity, doc1, doc2, doc1_context, doc2_context,
                    evidence_analysis["relationship_type"], knowledge_gaps
                )

                result.update({
                    "deep_inferences": deep_inference["inferences"],
                    "implications": deep_inference.get("implications", []),
                    "deep_explanation": deep_inference["explanation"],
                    "deep_confidence": deep_inference["confidence"]
                })

            # Record performance if recorder is provided
            if self.performance_recorder:
                self.performance_recorder("enhance_document_connections", {
                    "reasoning_depth": reasoning_depth,
                    "duration": time.time() - start_time,
                    "success": True,
                    "doc1_id": doc1.get("id", "unknown"),
                    "doc2_id": doc2.get("id", "unknown"),
                    "entity_id": entity.get("id", "unknown")
                })

            return result

        except Exception as e:
            # Log error
            logging.error(f"Error in enhance_document_connections: {str(e)}")
            logging.debug(traceback.format_exc())

            # Record failure if recorder is provided
            if self.performance_recorder:
                self.performance_recorder("enhance_document_connections", {
                    "reasoning_depth": reasoning_depth,
                    "duration": time.time() - start_time,
                    "success": False,
                    "error": str(e),
                    "doc1_id": doc1.get("id", "unknown"),
                    "doc2_id": doc2.get("id", "unknown"),
                    "entity_id": entity.get("id", "unknown")
                })

            # Return basic result on error
            return {
                "connection_type": "unknown",
                "explanation": f"Error analyzing document connection: {str(e)}",
                "inference": "Unable to generate inference due to error",
                "confidence": 0.0,
                "reasoning_depth": reasoning_depth,
                "error": str(e)
            }

    def enhance_cross_document_reasoning(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        connections: List[Dict[str, Any]],
        reasoning_depth: str,
        graph_info: Optional[Dict[str, Any]] = None,
        query_vector: Optional[np.ndarray] = None,
        doc_trace_ids: Optional[List[str]] = None,
        root_cids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Enhance cross-document reasoning results with LLM synthesis.

        Args:
            query: User query
            documents: List of relevant documents
            connections: List of document connections
            reasoning_depth: Reasoning depth level
            graph_info: Additional information about the graph
            query_vector: Query embedding vector for optimizer
            doc_trace_ids: Document trace IDs for Wikipedia knowledge graphs
            root_cids: Root CIDs for IPLD-based knowledge graphs

        Returns:
            Enhanced reasoning results
        """
        start_time = time.time()

        try:
            # Format connections for LLM
            connections_text = self._format_connections_for_llm(connections, reasoning_depth)

            # Extract entity types and relationship types for domain detection
            entity_types = set()
            relationship_types = set()

            for conn in connections:
                if "entity" in conn and "type" in conn["entity"]:
                    entity_types.add(conn["entity"]["type"])
                if "connection_type" in conn:
                    relationship_types.add(conn["connection_type"])

            # Enhance graph_info with connection information
            enhanced_graph_info = graph_info or {}
            enhanced_graph_info.update({
                "entity_types": list(entity_types),
                "relationship_types": list(relationship_types)
            })

            # Get LLM synthesis with optimizer integration
            synthesis = self.processor.synthesize_cross_document_reasoning(
                query=query,
                documents=documents,
                connections=connections_text,
                reasoning_depth=reasoning_depth,
                graph_info=enhanced_graph_info,
                query_vector=query_vector,
                doc_trace_ids=doc_trace_ids,
                root_cids=root_cids
            )

            # Format final result
            result = {
                "answer": synthesis["answer"],
                "reasoning": synthesis["reasoning"],
                "confidence": synthesis["confidence"],
                "references": synthesis.get("references", []),
                "knowledge_gaps": synthesis.get("knowledge_gaps", []),
                "raw_connections": connections,
                "reasoning_depth": reasoning_depth,
                "domain": synthesis.get("domain", "general")
            }

            # Add optimizer information if available
            if "optimizer_info" in synthesis:
                result["optimizer_info"] = synthesis["optimizer_info"]

            # Add domain-specific fields
            if "domain" in synthesis:
                domain = synthesis["domain"]
                if domain == "academic" and "research_implications" in synthesis:
                    result["research_implications"] = synthesis["research_implications"]
                elif domain == "medical" and "clinical_significance" in synthesis:
                    result["clinical_significance"] = synthesis["clinical_significance"]
                elif domain == "legal" and "legal_principle" in synthesis:
                    result["legal_principle"] = synthesis["legal_principle"]
                elif domain == "financial" and "market_impact" in synthesis:
                    result["market_impact"] = synthesis["market_impact"]
                elif domain == "technical" and "technical_implications" in synthesis:
                    result["technical_implications"] = synthesis["technical_implications"]

            # Add reasoning-depth-specific fields
            if reasoning_depth == "deep":
                if "implications" in synthesis:
                    result["implications"] = synthesis["implications"]
                if "alternative_interpretations" in synthesis:
                    result["alternative_interpretations"] = synthesis["alternative_interpretations"]

            # Record performance if recorder is provided
            if self.performance_recorder:
                self.performance_recorder("enhance_cross_document_reasoning", {
                    "reasoning_depth": reasoning_depth,
                    "duration": time.time() - start_time,
                    "success": True,
                    "num_documents": len(documents),
                    "num_connections": len(connections),
                    "domain": result.get("domain", "general"),
                    "optimizer_used": "optimizer_info" in synthesis
                })

            return result

        except Exception as e:
            # Log error
            logging.error(f"Error in enhance_cross_document_reasoning: {str(e)}")
            logging.debug(traceback.format_exc())

            # Record failure if recorder is provided
            if self.performance_recorder:
                self.performance_recorder("enhance_cross_document_reasoning", {
                    "reasoning_depth": reasoning_depth,
                    "duration": time.time() - start_time,
                    "success": False,
                    "error": str(e),
                    "num_documents": len(documents),
                    "num_connections": len(connections) if connections else 0
                })

            # Return basic result on error
            return {
                "answer": f"Error synthesizing information: {str(e)}",
                "reasoning": "Unable to synthesize information due to error",
                "confidence": 0.0,
                "references": [],
                "knowledge_gaps": [],
                "raw_connections": connections,
                "reasoning_depth": reasoning_depth,
                "error": str(e)
            }

    def optimize_and_reason(
        self,
        query: str,
        query_vector: np.ndarray,
        documents: List[Dict[str, Any]],
        connections: List[Dict[str, Any]],
        reasoning_depth: str = "moderate",
        graph_info: Optional[Dict[str, Any]] = None,
        doc_trace_ids: Optional[List[str]] = None,
        root_cids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Perform optimized cross-document reasoning using both query optimization and LLM synthesis.

        This is a convenience method that combines query optimization and cross-document reasoning
        in a single call, providing a streamlined interface for GraphRAG operations.

        Args:
            query: User query text
            query_vector: Query embedding vector
            documents: List of relevant documents
            connections: List of document connections
            reasoning_depth: Reasoning depth level (basic, moderate, deep)
            graph_info: Additional information about the graph
            doc_trace_ids: Document trace IDs for Wikipedia knowledge graphs
            root_cids: Root CIDs for IPLD-based knowledge graphs

        Returns:
            Dict: Enhanced reasoning results with optimization information
        """
        if not self.query_optimizer:
            # If no optimizer is available, use the standard reasoning method
            return self.enhance_cross_document_reasoning(
                query=query,
                documents=documents,
                connections=connections,
                reasoning_depth=reasoning_depth,
                graph_info=graph_info
            )

        # Use the optimized reasoning method with the query vector and CIDs
        return self.enhance_cross_document_reasoning(
            query=query,
            documents=documents,
            connections=connections,
            reasoning_depth=reasoning_depth,
            graph_info=graph_info,
            query_vector=query_vector,
            doc_trace_ids=doc_trace_ids,
            root_cids=root_cids
        )

    def _format_connections_for_llm(
        self,
        connections: List[Dict[str, Any]],
        reasoning_depth: str
    ) -> str:
        """
        Format document connections for LLM prompt.

        Args:
            connections: List of document connections
            reasoning_depth: Reasoning depth level

        Returns:
            Formatted connection text
        """
        if not connections:
            return "No connections found between documents."

        formatted = []
        for i, conn in enumerate(connections):
            conn_str = f"CONNECTION {i+1}:\n"

            # Extract document titles or IDs
            doc1_title = conn['doc1'].get('title', f"Document {conn['doc1'].get('id', 'unknown')}")
            doc2_title = conn['doc2'].get('title', f"Document {conn['doc2'].get('id', 'unknown')}")

            # Extract entity name, type, and other basic info
            entity_name = conn['entity'].get('name', conn['entity'].get('id', 'unknown'))
            entity_type = conn['entity'].get('type', 'Entity')

            # Format based on reasoning depth
            if reasoning_depth == "basic":
                conn_str += f"Document 1: {doc1_title}\n"
                conn_str += f"Document 2: {doc2_title}\n"
                conn_str += f"Connected by: {entity_name} ({entity_type})\n"

                if "connection_type" in conn:
                    conn_str += f"Relationship: {conn['connection_type']}\n"

            elif reasoning_depth == "moderate":
                conn_str += f"Document 1: {doc1_title}\n"
                conn_str += f"Document 2: {doc2_title}\n"
                conn_str += f"Connected by: {entity_name} ({entity_type})\n"

                if "connection_type" in conn:
                    conn_str += f"Relationship: {conn['connection_type']}\n"

                if "explanation" in conn:
                    conn_str += f"Explanation: {conn['explanation']}\n"

                if "inference" in conn:
                    conn_str += f"Inference: {conn['inference']}\n"

                if "knowledge_gaps" in conn:
                    conn_str += f"Knowledge Gaps: {conn['knowledge_gaps']}\n"

            else:  # deep reasoning
                conn_str += f"Document 1: {doc1_title}\n"
                conn_str += f"Document 2: {doc2_title}\n"
                conn_str += f"Connected by: {entity_name} ({entity_type})\n"

                if "connection_type" in conn:
                    conn_str += f"Relationship: {conn['connection_type']}\n"

                if "explanation" in conn:
                    conn_str += f"Explanation: {conn['explanation']}\n"

                if "inference" in conn:
                    conn_str += f"Inference: {conn['inference']}\n"

                if "knowledge_gaps" in conn:
                    conn_str += f"Knowledge Gaps: {conn['knowledge_gaps']}\n"

                if "deep_inferences" in conn and conn["deep_inferences"]:
                    conn_str += "Deep Inferences:\n"
                    for j, inf in enumerate(conn["deep_inferences"]):
                        conn_str += f"  - {inf}\n"

                if "implications" in conn and conn["implications"]:
                    conn_str += "Implications:\n"
                    for j, imp in enumerate(conn["implications"]):
                        conn_str += f"  - {imp}\n"

            formatted.append(conn_str)

        return "\n\n".join(formatted)
