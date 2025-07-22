"""
GraphRAG Integration Module

This module implements a comprehensive GraphRAG (Graph Retrieval Augmented Generation)
system that combines vector search with knowledge graph traversal for enhanced retrieval
and reasoning capabilities. It integrates vector embeddings, graph traversal, LLM-based
reasoning, and cross-document connections into a unified framework.

The system patches existing VectorAugmentedGraphDataset classes to add GraphRAG
capabilities without modifying the original implementations, following an
extension-oriented architecture pattern.

Key Features:
- Hybrid vector + graph traversal search mechanisms
- Multi-model embeddings with weighted fusion
- Entity-mediated connections between documents
- Cross-document reasoning with evidence chains
- Query optimization with budget management
- Confidence scoring and uncertainty handling
- Detailed reasoning traces and visualizations

Main Components:
- GraphRAGIntegration: Main integration class for enhancing operations with LLM capabilities
- HybridVectorGraphSearch: Hybrid search combining vector similarity with graph traversal
- CrossDocumentReasoner: Cross-document reasoning across connected documents
- GraphRAGQueryEngine: Query engine combining vector search and knowledge graph traversal
- GraphRAGFactory: Factory for creating and composing GraphRAG components

Usage Example:

    # Create a complete GraphRAG system
    graphrag = GraphRAGFactory.create_graphrag_system(
        dataset,
        config={
            "vector_weight": 0.6,
            "graph_weight": 0.4,
            "max_graph_hops": 2,
            "enable_cross_document_reasoning": True,
            "vector_stores": vector_stores,
            "graph_store": graph_store
        }
    )

    # Use the query engine for advanced queries
    result = graphrag["query_engine"].query(
        query_text="How does IPFS handle content addressing?",
        top_k=5,
        include_cross_document_reasoning=True,
        reasoning_depth="moderate"
    )

    # Access the reasoning result
    answer = result["reasoning_result"]["answer"]
    evidence = result["evidence_chains"]

    # Visualize the reasoning process
    visualization = graphrag["query_engine"].visualize_query_result(
        result, format="mermaid"
    )
"""
import time
import logging
from typing import Dict, List, Any, Optional, Union, Tuple, Callable, Set
import numpy as np

from ipfs_datasets_py.llm.llm_graphrag import (
    ReasoningEnhancer, GraphRAGLLMProcessor, GraphRAGPerformanceMonitor
)
from ipfs_datasets_py.llm.llm_semantic_validation import (
    SchemaValidator, SemanticAugmenter, SemanticValidator
)
from ipfs_datasets_py.llm.llm_reasoning_tracer import (
    ReasoningTrace, ReasoningNodeType # Removed ReasoningStep, TracingManager, StepType, ConfidenceLevel
)
from ipfs_datasets_py.knowledge_graph_extraction import (
    Entity, Relationship, KnowledgeGraph
)

# Forward references for type hints
class GraphRAGQueryEngine: pass
class HybridVectorGraphSearch: pass


class GraphRAGIntegration:
    """
    Integration class for enhancing GraphRAG operations with LLM capabilities.

    This class patches VectorAugmentedGraphDataset methods to incorporate
    LLM reasoning without directly modifying the original class. It supports
    domain-specific processing and performance monitoring. The integration
    follows an extension pattern that preserves the original implementation
    while adding enhanced capabilities.

    Key Features:
    - Non-intrusive patching of existing dataset methods
    - LLM-enhanced cross-document reasoning
    - Domain-specific content processing and adaptation
    - Detailed reasoning tracing and visualization
    - Performance monitoring and metrics collection
    - Semantic validation of LLM outputs
    - Confidence scoring and uncertainty assessment

    The integration provides several enhancements:
    - More sophisticated reasoning across multiple documents
    - Domain-aware processing for specialized fields (academic, medical, legal, etc.)
    - Detailed explanations of reasoning steps and confidence levels
    - Enhanced information synthesis with semantic validation
    - Comprehensive performance metrics for system optimization
    """

    def __init__(
        self,
        dataset,
        llm_processor: Optional[GraphRAGLLMProcessor] = None,
        performance_monitor: Optional[GraphRAGPerformanceMonitor] = None,
        validator: Optional[SemanticValidator] = None,
        # tracing_manager: Optional[TracingManager] = None, # Removed TracingManager
        validate_outputs: bool = True,
        enable_tracing: bool = True # Keep flag, but functionality will be limited
    ):
        """
        Initialize GraphRAG integration.

        Args:
            dataset: The VectorAugmentedGraphDataset instance to enhance
            llm_processor: Optional LLM processor to use
            performance_monitor: Optional performance monitor
            validator: Optional semantic validator
            tracing_manager: Optional tracing manager
            validate_outputs: Whether to validate and augment LLM outputs
            enable_tracing: Whether to enable detailed reasoning tracing
        """
        self.dataset = dataset
        self.performance_monitor = performance_monitor or GraphRAGPerformanceMonitor()
        self.llm_processor = llm_processor or GraphRAGLLMProcessor(
            performance_monitor=self.performance_monitor
        )

        # Create semantic validator
        self.validator = validator or SemanticValidator()
        self.validate_outputs = validate_outputs
        # Initialize tracing (functionality limited without TracingManager)
        self.enable_tracing = enable_tracing
        # self.tracing_manager = tracing_manager or TracingManager() # Removed TracingManager

        # Create reasoning enhancer with performance monitoring
        self.enhancer = ReasoningEnhancer(
            llm_processor=self.llm_processor,
            performance_recorder=self._record_performance
        )

        # Initialize metrics
        self.metrics = {
            "queries_processed": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "validation_failures": 0,
            "processing_times": [],
            "traces_created": 0
        }

        # Patch the dataset's methods with enhanced versions
        self._patch_methods()

    def _record_performance(self, operation: str, metrics: Dict[str, Any]) -> None:
        """
        Record performance metrics.

        Args:
            operation: Name of the operation
            metrics: Performance metrics
        """
        # Record success or failure
        if metrics.get("success", False):
            self.metrics["successful_queries"] += 1
        else:
            self.metrics["failed_queries"] += 1

        # Record processing time
        if "duration" in metrics:
            self.metrics["processing_times"].append(metrics["duration"])

        # Log any errors
        if "error" in metrics and not metrics.get("success", False):
            logging.error(f"Error in {operation}: {metrics['error']}")

    def _patch_methods(self):
        """Patch dataset methods with enhanced versions."""
        # Store original method for later use
        self.dataset._original_synthesize_cross_document_information = getattr(
            self.dataset,
            '_synthesize_cross_document_information',
            lambda *args, **kwargs: {"answer": "Not implemented", "reasoning_trace": []}
        )

        # Patch the synthesis method
        self.dataset._synthesize_cross_document_information = self._enhanced_synthesize_cross_document_information

    def _get_graph_info(self) -> Dict[str, Any]:
        """
        Get information about the graph for domain detection.

        Returns:
            Dictionary of graph information
        """
        # Extract entity types from the graph
        entity_types = set()
        relationship_types = set()

        # Look at node types
        if hasattr(self.dataset, 'nodes') and isinstance(self.dataset.nodes, dict):
             for node in self.dataset.nodes.values():
                 if hasattr(node, 'type'):
                     entity_types.add(node.type)

        # Look at edge types
        if hasattr(self.dataset, '_edges_by_type') and isinstance(self.dataset._edges_by_type, dict):
             for edge_type in self.dataset._edges_by_type:
                 relationship_types.add(edge_type)

        return {
            "entity_types": list(entity_types),
            "relationship_types": list(relationship_types),
            "node_count": len(self.dataset.nodes) if hasattr(self.dataset, 'nodes') else 0,
            "graph_name": getattr(self.dataset, 'name', 'unknown')
        }

    def _enhanced_synthesize_cross_document_information(
        self,
        query: str,
        documents: List[Tuple[Any, float]],
        evidence_chains: List[Dict[str, Any]],
        reasoning_depth: str
    ) -> Dict[str, Any]:
        """
        Enhanced method for synthesizing information across documents using LLM.

        Args:
            query: User query
            documents: List of relevant documents with scores
            evidence_chains: Document evidence chains
            reasoning_depth: Reasoning depth level

        Returns:
            Synthesized information
        """
        start_time = time.time()
        self.metrics["queries_processed"] += 1

        # Initialize reasoning trace if tracing is enabled (limited functionality)
        trace = None
        trace_id = None # Initialize trace_id
        if self.enable_tracing:
            # Cannot use TracingManager, create a basic trace object directly for structure
            # Note: This trace won't be managed or saved by a manager
            graph_info = self._get_graph_info()
            trace = ReasoningTrace(
                query=query,
                metadata={
                    "dataset_name": getattr(self.dataset, "name", "unknown"),
                    "start_time": time.time(),
                    "reasoning_depth": reasoning_depth,
                    "graph_info": graph_info,
                    "num_documents": len(documents),
                    "num_connections": len(evidence_chains)
                }
            )
            trace_id = trace.trace_id # Store the ID
            self.metrics["traces_created"] += 1

        try:
            # Create initial query node in trace
            query_node_id = None
            if trace:
                query_node_id = trace.add_node(
                    node_type=ReasoningNodeType.QUERY,
                    content=query
                )

            # Format documents for LLM
            formatted_docs = []
            for doc, score in documents:
                # Extract all available document data
                doc_data = {
                    "id": getattr(doc, "id", "unknown"),
                    "title": getattr(doc, "data", {}).get("title", "Untitled"),
                    "content": getattr(doc, "data", {}).get("content", "No content"),
                    "score": float(score),
                    "type": getattr(doc, "type", "document")
                }

                # Add any additional metadata that might be useful for domain detection
                if hasattr(doc, "data") and isinstance(doc.data, dict):
                    for key, value in doc.data.items():
                        if key not in ["title", "content"] and value and not isinstance(value, (dict, list)):
                            doc_data[key] = value

                formatted_docs.append(doc_data)
            # Create document retrieval nodes in trace
            doc_node_ids = {}
            if trace and query_node_id:
                for doc_data in formatted_docs:
                    doc_node_id = trace.add_node(
                        node_type=ReasoningNodeType.DOCUMENT,
                        content=f"Doc: {doc_data['title']}",
                        source=doc_data['id'],
                        confidence=doc_data['score'], # Use float score
                        metadata=doc_data
                    )
                    trace.add_edge(query_node_id, doc_node_id, "retrieved", weight=doc_data['score'])
                    doc_node_ids[doc_data['id']] = doc_node_id

            # Format evidence chains for LLM
            formatted_chains = []
            for chain in evidence_chains:
                # Get document 1 data
                doc1 = chain.get("doc1", {})
                doc1_data = {
                    "id": getattr(doc1, "id", chain.get("doc1", {}).get("id", "unknown")), # Handle direct dict or object
                    "title": getattr(doc1, "data", {}).get("title", chain.get("doc1", {}).get("title", "Untitled")),
                    "type": getattr(doc1, "type", chain.get("doc1", {}).get("type", "document"))
                }

                # Get document 2 data
                doc2 = chain.get("doc2", {})
                doc2_data = {
                    "id": getattr(doc2, "id", chain.get("doc2", {}).get("id", "unknown")),
                    "title": getattr(doc2, "data", {}).get("title", chain.get("doc2", {}).get("title", "Untitled")),
                    "type": getattr(doc2, "type", chain.get("doc2", {}).get("type", "document"))
                }

                # Get entity data
                entity = chain.get("entity", {})
                entity_data = {
                    "id": getattr(entity, "id", chain.get("entity", {}).get("id", "unknown")),
                    "name": getattr(entity, "data", {}).get("name", chain.get("entity", {}).get("name", "Unnamed Entity")),
                    "type": getattr(entity, "type", chain.get("entity", {}).get("type", "Entity"))
                }

                # Create formatted chain
                formatted_chain = {
                    "doc1": doc1_data,
                    "doc2": doc2_data,
                    "entity": entity_data
                }

                # Add any additional fields from the chain
                for key, value in chain.items():
                    if key not in ["doc1", "doc2", "entity"] and not callable(value):
                        formatted_chain[key] = value

                formatted_chains.append(formatted_chain)
            # Create evidence chain nodes in trace
            chain_node_ids = []
            if trace and query_node_id: # Link chains conceptually to query for now
                 for i, chain_data in enumerate(formatted_chains):
                     entity_node_id = trace.add_node(
                         node_type=ReasoningNodeType.ENTITY,
                         content=f"Entity: {chain_data['entity']['name']}",
                         source=chain_data['entity']['id'],
                         metadata=chain_data['entity']
                     )
                     # Link entity to documents if nodes exist
                     doc1_node_id = doc_node_ids.get(chain_data['doc1']['id'])
                     doc2_node_id = doc_node_ids.get(chain_data['doc2']['id'])
                     if doc1_node_id:
                         trace.add_edge(entity_node_id, doc1_node_id, "mentioned_in")
                     if doc2_node_id:
                         trace.add_edge(entity_node_id, doc2_node_id, "mentioned_in")
                     chain_node_ids.append(entity_node_id) # Use entity node to represent chain link
            # Connection finding step is implicitly represented by entity links above

            # Get graph info for domain detection
            graph_info = self._get_graph_info()
            # Domain identification step
            domain_node_id = None
            # Detect domain from context (simplified logic from original)
            domain = graph_info.get("domain", "general")
            if "entity_types" in graph_info:
                entity_types = set(graph_info["entity_types"])
                if entity_types & {"paper", "author", "concept", "publication"}:
                    domain = "academic"
                elif entity_types & {"condition", "treatment", "medication", "symptom"}:
                    domain = "medical"
                elif entity_types & {"case", "statute", "regulation", "court"}:
                    domain = "legal"
                elif entity_types & {"company", "stock", "market", "report"}:
                    domain = "financial"
                elif entity_types & {"technology", "device", "software", "system"}:
                    domain = "technical"

            if trace and query_node_id: # Link domain to query
                domain_node_id = trace.add_node(
                    node_type=ReasoningNodeType.METADATA, # Using METADATA type
                    content=f"Domain: {domain}"
                )
                trace.add_edge(query_node_id, domain_node_id, "has_domain")

            # Use LLM enhancer for synthesis
            # Track the start time for synthesis
            synthesis_start_time = time.time()
            # Synthesis start step (implicit)

            # Call the enhancer
            enhanced_result = self.enhancer.enhance_cross_document_reasoning(
                query, formatted_docs, formatted_chains, reasoning_depth, graph_info
            )
            # Synthesis result step
            synthesis_node_id = None
            if trace:
                synthesis_confidence_val = 0.5 # Default medium
                if "confidence" in enhanced_result and isinstance(enhanced_result["confidence"], (int, float)):
                    synthesis_confidence_val = enhanced_result["confidence"]

                synthesis_node_id = trace.add_node(
                    node_type=ReasoningNodeType.INFERENCE, # Represent synthesis as inference
                    content=f"Synthesis: {enhanced_result.get('answer', '')[:50]}...",
                    confidence=synthesis_confidence_val, # Use float
                    metadata={
                        "full_answer": enhanced_result.get('answer'),
                        "reasoning": enhanced_result.get('reasoning')
                    }
                )
                # Link synthesis node to evidence/chain nodes
                for chain_node_id in chain_node_ids:
                    trace.add_edge(synthesis_node_id, chain_node_id, "based_on")
                for doc_node_id in doc_node_ids.values():
                     trace.add_edge(synthesis_node_id, doc_node_id, "based_on") # Link to docs too
            # Semantic validation step
            validation_node_id = None
            if self.validate_outputs:
                # Track start time for validation
                validation_start_time = time.time()

                # Validate and augment
                success, validated_result, errors = self.validator.process(
                    enhanced_result,
                    domain=domain,
                    task="cross_document_reasoning",
                    context={"query": query, "graph_info": graph_info},
                    auto_repair=True
                )
                if success:
                    enhanced_result = validated_result
                    if trace and synthesis_node_id:
                        validation_node_id = trace.add_node(
                            node_type=ReasoningNodeType.METADATA, # Use METADATA for validation status
                            content="Validation: Success",
                            confidence=1.0, # Use float
                            metadata={"validated_result": validated_result}
                        )
                        trace.add_edge(validation_node_id, synthesis_node_id, "validates")
                else:
                    # Record validation failure but continue with original result
                    logging.warning(f"Semantic validation failed: {errors}")
                    self.metrics["validation_failures"] += 1
                    if trace and synthesis_node_id:
                         validation_node_id = trace.add_node(
                            node_type=ReasoningNodeType.METADATA,
                            content="Validation: Failed",
                            confidence=0.1, # Use float
                            metadata={"errors": errors}
                         )
                         trace.add_edge(validation_node_id, synthesis_node_id, "validates")
            # Conclusion step
            conclusion_node_id = None
            if trace:
                answer = enhanced_result.get("answer", "No answer available")
                conclusion_confidence_val = 0.5 # Default medium
                if "confidence" in enhanced_result and isinstance(enhanced_result["confidence"], (int, float)):
                     conclusion_confidence_val = enhanced_result["confidence"]

                # Adjust confidence based on reasoning depth (example logic)
                if reasoning_depth == "deep":
                    conclusion_confidence_val = min(1.0, conclusion_confidence_val + 0.1)
                elif reasoning_depth == "basic":
                     conclusion_confidence_val = max(0.0, conclusion_confidence_val - 0.1)

                conclusion_node_id = trace.add_node(
                    node_type=ReasoningNodeType.CONCLUSION,
                    content=f"Final Answer: {answer[:50]}...",
                    confidence=conclusion_confidence_val, # Use float
                    metadata={"full_answer": answer}
                )
                # Link conclusion to synthesis/validation node
                link_from_node = validation_node_id if validation_node_id else synthesis_node_id
                if link_from_node:
                    trace.add_edge(conclusion_node_id, link_from_node, "concludes")

            # Ensure the result has the expected fields
            result = {
                "answer": enhanced_result.get("answer", "No answer available"),
                "reasoning_trace": [
                    {"step": "Initial query", "description": query},
                    {"step": "Document retrieval", "description": f"Retrieved {len(documents)} relevant documents"},
                    {"step": "Entity extraction", "description": "Extracted key entities from documents"},
                    {"step": "Connection finding", "description": f"Found {len(evidence_chains)} connections between documents"},
                    {"step": "Information synthesis", "description": enhanced_result.get("reasoning", "No reasoning trace available")}
                ]
            }

            # Add semantic information to reasoning trace if available
            if "key_concepts" in enhanced_result:
                key_concepts = enhanced_result["key_concepts"]
                if key_concepts:
                    concepts_str = ", ".join(key_concepts[:3])
                    result["reasoning_trace"].append({
                        "step": "Key concept identification",
                        "description": f"Identified key concepts: {concepts_str}"
                    })

            # Add uncertainty assessment to reasoning trace if available
            if "uncertainty_assessment" in enhanced_result:
                uncertainty = enhanced_result["uncertainty_assessment"]
                if "interpretation" in uncertainty:
                    result["reasoning_trace"].append({
                        "step": "Uncertainty assessment",
                        "description": f"Assessment: {uncertainty['interpretation']}"
                    })

            # Add domain information if available
            if "domain" in enhanced_result:
                result["reasoning_trace"].append({
                    "step": "Domain identification",
                    "description": f"Identified domain: {enhanced_result['domain']}"
                })

            # Add additional reasoning information based on depth
            if reasoning_depth in ["moderate", "deep"]:
                result["reasoning_trace"].append({
                    "step": "Advanced reasoning",
                    "description": "Applied deeper reasoning across document connections"
                })

                if reasoning_depth == "deep":
                    if "implications" in enhanced_result and enhanced_result["implications"]:
                        implications = enhanced_result["implications"]
                        if isinstance(implications, list) and implications:
                            result["reasoning_trace"].append({
                                "step": "Implication analysis",
                                "description": "Analyzed broader implications: " +
                                            ", ".join(implications[:2])
                            })

                    if "alternative_interpretations" in enhanced_result and enhanced_result["alternative_interpretations"]:
                        result["reasoning_trace"].append({
                            "step": "Alternative interpretations",
                            "description": "Considered alternative viewpoints"
                        })

            # Add domain-specific information based on domain
            if "domain" in enhanced_result:
                domain = enhanced_result["domain"]
                if domain == "academic" and "research_implications" in enhanced_result:
                    result["reasoning_trace"].append({
                        "step": "Research implications",
                        "description": enhanced_result["research_implications"]
                    })
                elif domain == "medical" and "clinical_significance" in enhanced_result:
                    result["reasoning_trace"].append({
                        "step": "Clinical significance",
                        "description": enhanced_result["clinical_significance"]
                    })
                elif domain == "legal" and "legal_principle" in enhanced_result:
                    result["reasoning_trace"].append({
                        "step": "Legal principle",
                        "description": enhanced_result["legal_principle"]
                    })
                elif domain == "financial" and "market_impact" in enhanced_result:
                    result["reasoning_trace"].append({
                        "step": "Market impact",
                        "description": enhanced_result["market_impact"]
                    })
                elif domain == "technical" and "technical_implications" in enhanced_result:
                    result["reasoning_trace"].append({
                        "step": "Technical implications",
                        "description": enhanced_result["technical_implications"]
                    })
            # Complete the reasoning trace (no manager to call complete_trace)
            if trace:
                # Add trace object directly to result if needed (not just ID)
                # result["trace_object"] = trace.to_dict() # Optional: include full trace
                result["trace_id"] = trace_id # Use the stored trace_id

            # Track successful processing
            processing_time = time.time() - start_time
            self._record_performance("synthesize_cross_document_information", {
                "success": True,
                "duration": processing_time,
                "reasoning_depth": reasoning_depth,
                "num_documents": len(documents),
                "num_connections": len(evidence_chains),
                "has_trace": trace is not None
            })

            return result

        except Exception as e:
            # Log error
            logging.error(f"Error in synthesize_cross_document_information: {str(e)}")
            # Create error node in trace if enabled
            if trace:
                 error_node_id = trace.add_node(
                     node_type=ReasoningNodeType.METADATA,
                     content=f"Error: {str(e)}",
                     confidence=0.0 # Use float
                 )
                 # Link error to query node if possible
                 if query_node_id:
                     trace.add_edge(error_node_id, query_node_id, "occurred_during")
                 # result["trace_id"] = trace_id # Include trace ID even on error # result not defined here

            # Track failed processing
            processing_time = time.time() - start_time
            self._record_performance("synthesize_cross_document_information", {
                "success": False,
                "duration": processing_time,
                "error": str(e),
                "reasoning_depth": reasoning_depth,
                "num_documents": len(documents),
                "num_connections": len(evidence_chains),
                "has_trace": trace is not None
            })

            # Return basic result on error
            return {
                "answer": f"Error synthesizing information: {str(e)}",
                "reasoning_trace": [
                    {"step": "Initial query", "description": query},
                    {"step": "Error", "description": f"An error occurred: {str(e)}"}
                ]
            }

    def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Get performance metrics for the integration.

        Returns:
            Dictionary of performance metrics
        """
        metrics = self.metrics.copy()

        # Calculate additional metrics
        if metrics["queries_processed"] > 0:
            metrics["success_rate"] = metrics["successful_queries"] / metrics["queries_processed"]
            if "validation_failures" in metrics:
                metrics["validation_success_rate"] = 1.0 - (metrics["validation_failures"] / metrics["queries_processed"])
        else:
            metrics["success_rate"] = 0.0
            metrics["validation_success_rate"] = 1.0

        if metrics["processing_times"]:
            metrics["avg_processing_time"] = sum(metrics["processing_times"]) / len(metrics["processing_times"])
            metrics["min_processing_time"] = min(metrics["processing_times"])
            metrics["max_processing_time"] = max(metrics["processing_times"])
        else:
            metrics["avg_processing_time"] = 0.0
            metrics["min_processing_time"] = 0.0
            metrics["max_processing_time"] = 0.0

        # Add LLM metrics
        metrics["llm_metrics"] = {
            "task_metrics": self.performance_monitor.get_task_metrics(),
            "model_metrics": self.performance_monitor.get_model_metrics()
        }

        # Add latency percentiles
        metrics["latency_percentiles"] = self.performance_monitor.get_latency_percentiles()

        # Add validation metrics
        if self.validate_outputs:
            metrics["validation"] = {
                "enabled": True,
                "failures": metrics.get("validation_failures", 0),
                "success_rate": metrics.get("validation_success_rate", 1.0)
            }
        else:
            metrics["validation"] = {
                "enabled": False
            }

        # Add tracing metrics
        if self.enable_tracing:
            # Cannot use TracingManager
            metrics["tracing"] = {
                "enabled": True,
                "traces_created": metrics.get("traces_created", 0),
                "stored_traces": "N/A (TracingManager not available)"
            }
        else:
            metrics["tracing"] = {
                "enabled": False
            }

        return metrics

    def get_reasoning_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a reasoning trace by ID.
        Args:
            trace_id: ID of the trace to get

        Returns:
            Trace data or None if not found
        """
        if not self.enable_tracing:
            logging.warning("Tracing is disabled, cannot get trace.")
            return None
        # Cannot use TracingManager, return None or handle differently
        logging.warning("TracingManager not available in this context.")
        return None

    def get_recent_traces(self, limit: int = 10, query_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get a list of recent reasoning traces.
        Args:
            limit: Maximum number of traces to return
            query_filter: Optional filter by query text

        Returns:
            List of trace summaries
        """
        if not self.enable_tracing:
            logging.warning("Tracing is disabled, cannot get recent traces.")
            return []
        # Cannot use TracingManager, return empty list
        logging.warning("TracingManager not available in this context.")
        return []

    def explain_trace(
        self,
        trace_id: str,
        explanation_type: str = "summary",
        target_audience: str = "general"
    ) -> Dict[str, Any]:
        """
        Generate an explanation for a reasoning trace.

        Args:
            trace_id: ID of the trace to explain
            explanation_type: Type of explanation ('summary', 'detailed', 'critical_path', 'confidence')
            target_audience: Target audience ('general', 'technical', 'expert')

        Returns:
            Explanation data
        """
        if not self.enable_tracing:
            return {"error": "Tracing is disabled"}
        # Cannot use TracingManager, return error
        logging.warning("TracingManager not available in this context.")
        return {"error": "TracingManager not available"}

    def visualize_trace(self, trace_id: str, format: str = "text") -> Dict[str, Any]:
        """
        Generate a visualization of a reasoning trace.

        Args:
            trace_id: ID of the trace to visualize
            format: Visualization format ('text', 'html', 'mermaid')

        Returns:
            Visualization data
        """
        if not self.enable_tracing:
            return {"error": "Tracing is disabled"}
        # Cannot use TracingManager, return error
        logging.warning("TracingManager not available in this context.")
        return {"error": "TracingManager not available"}


class HybridVectorGraphSearch:
    """
    Implements hybrid search combining vector similarity with graph traversal.

    This class provides mechanisms for augmenting vector-based similarity search
    with graph traversal to improve retrieval quality by considering both semantic
    similarity and structural relationships. It enables a form of "graph-enhanced RAG"
    where traditional vector retrieval is complemented by the rich relational
    information in a knowledge graph.

    Key Features:
    - Combined scoring using both vector similarity and graph traversal
    - Configurable weighting between vector and graph components
    - Multi-hop graph expansion from seed nodes
    - Bidirectional relationship traversal option
    - Path-aware relevance scoring with hop distance penalties
    - Entity-mediated search for connecting documents through shared entities
    - Caching for performance optimization

    The hybrid approach provides several advantages over pure vector or graph search:
    - More comprehensive results capturing both semantic and relational relevance
    - Ability to find relevant content not discoverable through vector similarity alone
    - Enhanced precision through structural context
    - Improved recall through relationship-based expansion
    """

    def __init__(
        self,
        dataset,
        vector_weight: float = 0.6,
        graph_weight: float = 0.4,
        max_graph_hops: int = 2,
        min_score_threshold: float = 0.5,
        use_bidirectional_traversal: bool = True
    ):
        """
        Initialize hybrid search.

        Args:
            dataset: VectorAugmentedGraphDataset instance
            vector_weight: Weight for vector similarity scores (0.0 to 1.0)
            graph_weight: Weight for graph traversal scores (0.0 to 1.0)
            max_graph_hops: Maximum graph traversal hops from seed nodes
            min_score_threshold: Minimum score threshold for results
            use_bidirectional_traversal: Whether to traverse relationships in both directions
        """
        self.dataset = dataset
        self.vector_weight = vector_weight
        self.graph_weight = graph_weight
        self.max_graph_hops = max_graph_hops
        self.min_score_threshold = min_score_threshold
        self.use_bidirectional_traversal = use_bidirectional_traversal

        # Normalize weights
        total_weight = self.vector_weight + self.graph_weight
        self.vector_weight = self.vector_weight / total_weight
        self.graph_weight = self.graph_weight / total_weight

        # Initialize metrics
        self.metrics = {
            "queries_processed": 0,
            "nodes_visited": 0,
            "edges_traversed": 0,
            "average_hops": 0,
            "cache_hits": 0
        }

        # Cache for recent searches to avoid redundant computation
        self._search_cache = {}
        self._max_cache_size = 100

    def hybrid_search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
        relationship_types: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None,
        min_vector_score: float = 0.0,
        rerank_with_llm: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Perform hybrid vector + graph search.

        Args:
            query_embedding: Query embedding vector
            top_k: Number of results to return
            relationship_types: Types of relationships to traverse
            entity_types: Types of entities to include
            min_vector_score: Minimum vector similarity score
            rerank_with_llm: Whether to rerank results with LLM

        Returns:
            List of search results with scores and traversal paths
        """
        # Create cache key
        cache_key = f"hybrid:{hash(query_embedding.tobytes())}:{top_k}:{relationship_types}:{entity_types}:{min_vector_score}"

        # Check cache
        if cache_key in self._search_cache:
            self.metrics["cache_hits"] += 1
            return self._search_cache[cache_key]

        self.metrics["queries_processed"] += 1

        # Phase 1: Vector search to find seed nodes
        vector_results = self._perform_vector_search(
            query_embedding,
            top_k * 2,  # Get more results for expansion
            min_score=min_vector_score,
            entity_types=entity_types
        )

        # Phase 2: Graph traversal to expand results
        expanded_results = self._expand_through_graph(
            vector_results,
            max_hops=self.max_graph_hops,
            relationship_types=relationship_types,
            entity_types=entity_types
        )

        # Phase 3: Score and rank combined results
        ranked_results = self._score_and_rank_results(
            query_embedding,
            expanded_results
        )

        # Apply minimum score threshold
        filtered_results = [r for r in ranked_results if r.get("combined_score", 0) >= self.min_score_threshold]

        # Rerank with LLM if requested
        if rerank_with_llm and len(filtered_results) > 1:
            # This would require integration with the LLM component
            # For now, just return the ranked results
            pass

        # Limit to top_k results
        results = filtered_results[:top_k]

        # Update cache
        if len(self._search_cache) >= self._max_cache_size:
            # Remove oldest entry
            oldest_key = next(iter(self._search_cache))
            del self._search_cache[oldest_key]

        self._search_cache[cache_key] = results

        return results

    def _perform_vector_search(
        self,
        query_embedding: np.ndarray,
        top_k: int,
        min_score: float = 0.0,
        entity_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform vector similarity search to find seed nodes.

        Args:
            query_embedding: Query embedding vector
            top_k: Number of results to return
            min_score: Minimum similarity score
            entity_types: Types of entities to include

        Returns:
            List of vector search results
        """
        # Use the dataset's vector search capability
        raw_results = self.dataset.search_vectors(
            query_embedding,
            top_k=top_k,
            min_score=min_score
        )

        # Convert to standard format and filter by entity type if needed
        results = []
        for result in raw_results:
            # Extract node ID from vector result
            node_id = result.get("id", result.get("node_id"))

            # Get node data
            node = self.dataset.get_node(node_id)

            # Filter by entity type if specified
            if entity_types and node.get("type") not in entity_types:
                continue

            # Create result entry
            results.append({
                "id": node_id,
                "node": node,
                "vector_score": result.get("score", 0.0),
                "graph_score": 0.0,  # Initial graph score is 0
                "combined_score": result.get("score", 0.0) * self.vector_weight,  # Initial combined score
                "path": [],  # Empty path for direct vector matches
                "hops": 0,  # No hops for direct matches
                "source": "vector"
            })

        return results

    def _expand_through_graph(
        self,
        seed_results: List[Dict[str, Any]],
        max_hops: int,
        relationship_types: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Expand seed results through graph traversal.

        Args:
            seed_results: Initial seed results from vector search
            max_hops: Maximum number of hops for traversal
            relationship_types: Types of relationships to traverse
            entity_types: Types of entities to include

        Returns:
            List of expanded results with traversal paths
        """
        all_results = seed_results.copy()

        # Set to track visited nodes
        visited_nodes: Set[str] = set()
        for result in seed_results:
            visited_nodes.add(result["id"])

        # Queue for BFS traversal
        queue = [(result["id"], result, 0) for result in seed_results]  # (node_id, seed_result, hop_count)

        # Track metrics
        nodes_visited = len(visited_nodes)
        edges_traversed = 0
        total_hops = 0

        # BFS traversal
        while queue:
            current_id, seed_result, hop_count = queue.pop(0)

            # Skip if we've reached max hops
            if hop_count >= max_hops:
                continue

            # Get neighboring nodes
            neighbors = self._get_neighbors(
                current_id,
                relationship_types,
                entity_types,
                hop_count
            )

            # Track edges traversed
            edges_traversed += len(neighbors)

            for neighbor_id, relationship, weight in neighbors:
                # Skip if already visited
                if neighbor_id in visited_nodes:
                    continue

                # Mark as visited
                visited_nodes.add(neighbor_id)
                nodes_visited += 1

                # Get node data
                neighbor_node = self.dataset.get_node(neighbor_id)

                # Calculate graph score
                # Graph score decreases with distance from seed node
                graph_score = weight * max(0.0, 1.0 - (hop_count / max_hops))

                # Calculate combined score
                # We use seed node's vector score and the graph traversal score
                combined_score = (
                    seed_result["vector_score"] * self.vector_weight +
                    graph_score * self.graph_weight
                )

                # Create path info
                hop_path = seed_result.get("path", []).copy()
                hop_path.append({
                    "from": current_id,
                    "to": neighbor_id,
                    "relationship": relationship,
                    "weight": weight
                })

                # Create result entry
                result = {
                    "id": neighbor_id,
                    "node": neighbor_node,
                    "vector_score": seed_result["vector_score"],  # Inherit from seed
                    "graph_score": graph_score,
                    "combined_score": combined_score,
                    "path": hop_path,
                    "hops": hop_count + 1,
                    "source": "graph"
                }

                # Add to results
                all_results.append(result)
                total_hops += (hop_count + 1)

                # Add to queue for next iteration
                queue.append((neighbor_id, seed_result, hop_count + 1))

        # Update metrics
        self.metrics["nodes_visited"] += nodes_visited
        self.metrics["edges_traversed"] += edges_traversed
        self.metrics["average_hops"] = total_hops / max(1, len(all_results) - len(seed_results))

        return all_results

    def _get_neighbors(
        self,
        node_id: str,
        relationship_types: Optional[List[str]],
        entity_types: Optional[List[str]],
        hop_count: int
    ) -> List[Tuple[str, str, float]]:
        """
        Get neighboring nodes for a given node.

        Args:
            node_id: ID of the node
            relationship_types: Types of relationships to traverse
            entity_types: Types of entities to include
            hop_count: Current hop count

        Returns:
            List of tuples (neighbor_id, relationship_type, weight)
        """
        # Get node's relationships
        relationships = self.dataset.get_node_relationships(node_id)

        neighbors = []
        for rel in relationships:
            # Determine target node based on relationship direction
            if rel["source"] == node_id:
                target_id = rel["target"]
                direction = "outgoing"
            elif rel["target"] == node_id and self.use_bidirectional_traversal:
                target_id = rel["source"]
                direction = "incoming"
            else:
                continue

            # Filter by relationship type if specified
            if relationship_types and rel["type"] not in relationship_types:
                continue

            # Get target node
            target_node = self.dataset.get_node(target_id)

            # Filter by entity type if specified
            if entity_types and target_node.get("type") not in entity_types:
                continue

            # Get relationship weight
            weight = rel.get("weight", 1.0)

            # Adjust weight based on relationship confidence
            if "confidence" in rel:
                weight *= rel["confidence"]

            # Penalize weight based on hop count
            weight *= 0.8 ** hop_count

            # Add to neighbors
            neighbors.append((target_id, rel["type"], weight))

        return neighbors

    def _score_and_rank_results(
        self,
        query_embedding: np.ndarray,
        results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Score and rank the combined results.

        Args:
            query_embedding: Original query embedding
            results: Combined results from vector search and graph traversal

        Returns:
            Ranked results
        """
        # For nodes discovered via graph traversal, we might want to compute
        # their actual vector similarity with the query
        # This is optional and can be expensive for large result sets

        for result in results:
            if result["source"] == "graph" and result.get("vector_score", 0) == 0:
                # Try to get node's embedding
                node_embedding = self.dataset.get_node_embedding(result["id"])

                if node_embedding is not None:
                    # Compute similarity with query
                    similarity = self._compute_similarity(query_embedding, node_embedding)

                    # Update scores
                    result["vector_score"] = similarity
                    result["combined_score"] = (
                        similarity * self.vector_weight +
                        result["graph_score"] * self.graph_weight
                    )

        # Sort results by combined score
        ranked_results = sorted(results, key=lambda x: x.get("combined_score", 0), reverse=True)

        return ranked_results

    def _compute_similarity(
        self,
        query_embedding: np.ndarray,
        node_embedding: np.ndarray
    ) -> float:
        """
        Compute similarity between query and node embeddings.

        Args:
            query_embedding: Query embedding vector
            node_embedding: Node embedding vector

        Returns:
            Similarity score
        """
        # Use cosine similarity
        dot_product = np.dot(query_embedding, node_embedding)
        query_norm = np.linalg.norm(query_embedding)
        node_norm = np.linalg.norm(node_embedding)

        if query_norm == 0 or node_norm == 0:
            return 0

        similarity = dot_product / (query_norm * node_norm)

        return float(similarity)

    def entity_mediated_search(
        self,
        query_embedding: np.ndarray,
        entity_types: List[str],
        top_k: int = 10,
        max_connecting_entities: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Perform entity-mediated search to find connected documents.

        This search method finds documents that share common entities,
        enabling cross-document reasoning.

        Args:
            query_embedding: Query embedding vector
            entity_types: Types of entities to consider as connectors
            top_k: Number of final results to return
            max_connecting_entities: Maximum number of connecting entities to use

        Returns:
            List of connected document pairs with connecting entities
        """
        # First, find the most relevant documents using vector search
        seed_documents = self._perform_vector_search(
            query_embedding,
            top_k=top_k * 2,  # Get more results for expansion
            entity_types=["document"]  # Only consider document nodes
        )

        # Extract document IDs
        doc_ids = [result["id"] for result in seed_documents]

        # Find entities connected to these documents
        connecting_entities = self._find_connecting_entities(
            doc_ids,
            entity_types,
            max_entities=max_connecting_entities
        )

        # Find document pairs connected by these entities
        connected_pairs = self._find_connected_document_pairs(
            connecting_entities,
            seed_documents,
            doc_ids,
            top_k
        )

        return connected_pairs

    def _find_connecting_entities(
        self,
        doc_ids: List[str],
        entity_types: List[str],
        max_entities: int
    ) -> List[Dict[str, Any]]:
        """
        Find entities connected to multiple documents.

        Args:
            doc_ids: List of document IDs
            entity_types: Types of entities to consider
            max_entities: Maximum number of entities to return

        Returns:
            List of connecting entities with their connections
        """
        # Map to count connections for each entity
        entity_connections: Dict[str, Set[str]] = {}

        # Find all entities connected to the documents
        for doc_id in doc_ids:
            # Get document's relationships
            relationships = self.dataset.get_node_relationships(doc_id)

            for rel in relationships:
                # Check if relationship connects to an entity of interest
                entity_id = None
                if rel["source"] == doc_id and rel["target"] != doc_id:
                    entity_id = rel["target"]
                elif rel["target"] == doc_id and rel["source"] != doc_id:
                    entity_id = rel["source"]

                if entity_id:
                    # Get entity data
                    entity = self.dataset.get_node(entity_id)

                    # Check entity type
                    if entity.get("type") in entity_types:
                        # Track connection
                        if entity_id not in entity_connections:
                            entity_connections[entity_id] = set()
                        entity_connections[entity_id].add(doc_id)

        # Find entities connected to multiple documents
        connecting_entities = []
        for entity_id, connections in entity_connections.items():
            if len(connections) > 1:  # Connected to at least 2 documents
                entity = self.dataset.get_node(entity_id)
                connecting_entities.append({
                    "id": entity_id,
                    "entity": entity,
                    "connected_docs": list(connections),
                    "connection_count": len(connections)
                })

        # Sort by connection count and limit
        sorted_entities = sorted(connecting_entities, key=lambda x: x["connection_count"], reverse=True)
        return sorted_entities[:max_entities]

    def _find_connected_document_pairs(
        self,
        connecting_entities: List[Dict[str, Any]],
        seed_documents: List[Dict[str, Any]],
        doc_ids: List[str],
        top_k: int
    ) -> List[Dict[str, Any]]:
        """
        Find document pairs connected by common entities.

        Args:
            connecting_entities: List of connecting entities
            seed_documents: List of seed document results
            doc_ids: List of document IDs
            top_k: Number of document pairs to return

        Returns:
            List of connected document pairs
        """
        # Create a map of document ID to vector score
        doc_scores = {result["id"]: result["vector_score"] for result in seed_documents}

        # Create document pairs
        doc_pairs = []
        for entity_data in connecting_entities:
            entity = entity_data["entity"]
            connected_docs = entity_data["connected_docs"]

            # Create all possible document pairs
            for i in range(len(connected_docs)):
                for j in range(i + 1, len(connected_docs)):
                    doc1_id = connected_docs[i]
                    doc2_id = connected_docs[j]

                    # Get document data
                    doc1 = self.dataset.get_node(doc1_id)
                    doc2 = self.dataset.get_node(doc2_id)

                    # Calculate pair score
                    # Consider both vector relevance and entity connection strength
                    doc1_score = doc_scores.get(doc1_id, 0.0)
                    doc2_score = doc_scores.get(doc2_id, 0.0)

                    # Combined score - average of document scores
                    pair_score = (doc1_score + doc2_score) / 2

                    # Create pair entry
                    pair = {
                        "doc1": {
                            "id": doc1_id,
                            "title": doc1.get("title", f"Document {doc1_id}"),
                            "score": doc1_score,
                            "type": doc1.get("type", "document")
                        },
                        "doc2": {
                            "id": doc2_id,
                            "title": doc2.get("title", f"Document {doc2_id}"),
                            "score": doc2_score,
                            "type": doc2.get("type", "document")
                        },
                        "entity": {
                            "id": entity_data["id"],
                            "name": entity.get("name", entity_data["id"]),
                            "type": entity.get("type", "entity")
                        },
                        "pair_score": pair_score
                    }

                    doc_pairs.append(pair)

        # Sort by pair score and limit
        sorted_pairs = sorted(doc_pairs, key=lambda x: x["pair_score"], reverse=True)

        # Remove duplicates (same doc pair connected by different entities)
        unique_pairs = []
        seen_pairs = set()
        for pair in sorted_pairs:
            # Create a unique key for the document pair
            pair_key = f"{min(pair['doc1']['id'], pair['doc2']['id'])}:{max(pair['doc1']['id'], pair['doc2']['id'])}"

            if pair_key not in seen_pairs:
                seen_pairs.add(pair_key)
                unique_pairs.append(pair)

        return unique_pairs[:top_k]

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get search performance metrics.

        Returns:
            Dictionary of search metrics
        """
        return self.metrics


def enhance_dataset_with_hybrid_search(
    dataset,
    vector_weight: float = 0.6,
    graph_weight: float = 0.4,
    max_graph_hops: int = 2,
    min_score_threshold: float = 0.5,
    use_bidirectional_traversal: bool = True
) -> HybridVectorGraphSearch:
    """
    Enhance a dataset with hybrid vector + graph search capabilities.

    Args:
        dataset: VectorAugmentedGraphDataset instance
        vector_weight: Weight for vector similarity scores (0.0 to 1.0)
        graph_weight: Weight for graph traversal scores (0.0 to 1.0)
        max_graph_hops: Maximum graph traversal hops from seed nodes
        min_score_threshold: Minimum score threshold for results
        use_bidirectional_traversal: Whether to traverse relationships in both directions

    Returns:
        HybridVectorGraphSearch instance attached to the dataset
    """
    hybrid_search = HybridVectorGraphSearch(
        dataset,
        vector_weight=vector_weight,
        graph_weight=graph_weight,
        max_graph_hops=max_graph_hops,
        min_score_threshold=min_score_threshold,
        use_bidirectional_traversal=use_bidirectional_traversal
    )

    # For convenience, we can also attach it to the dataset as an attribute
    # This makes it accessible as dataset.hybrid_search
    setattr(dataset, "hybrid_search", hybrid_search)

    return hybrid_search


def enhance_dataset_with_llm(
    dataset,
    validate_outputs: bool = True,
    llm_processor: Optional[GraphRAGLLMProcessor] = None,
    performance_monitor: Optional[GraphRAGPerformanceMonitor] = None,
    validator: Optional[SemanticValidator] = None,
    # tracing_manager: Optional[TracingManager] = None, # Removed TracingManager type hint
    enable_tracing: bool = True
) -> GraphRAGIntegration:
    """
    Enhance a VectorAugmentedGraphDataset with LLM capabilities.

    Args:
        dataset: VectorAugmentedGraphDataset instance
        validate_outputs: Whether to validate and enhance LLM outputs
        llm_processor: Optional LLM processor to use
        performance_monitor: Optional performance monitor
        validator: Optional semantic validator
        tracing_manager: Optional tracing manager
        enable_tracing: Whether to enable detailed reasoning tracing

    Returns:
        The same dataset instance with enhanced capabilities
    """
    integration = GraphRAGIntegration(
        dataset,
        llm_processor=llm_processor,
        performance_monitor=performance_monitor,
        validator=validator,
        # tracing_manager=tracing_manager, # Removed TracingManager usage
        validate_outputs=validate_outputs,
        enable_tracing=enable_tracing
    )
    return dataset


class CrossDocumentReasoner:
    """
    Implements cross-document reasoning capabilities for GraphRAG.

    This class provides methods for reasoning across multiple documents
    connected by shared entities, enabling more complex information synthesis.
    Cross-document reasoning goes beyond simple retrieval to answer complex
    queries by connecting information across multiple sources.

    Key Features:
    - Entity-mediated connections between documents
    - Evidence chain discovery and validation
    - Multi-document information synthesis
    - Confidence scoring with uncertainty assessment
    - Knowledge subgraph creation for focused reasoning
    - Domain-aware processing for specialized contexts

    The cross-document reasoning approach enables:
    - Answering questions that require integrating multiple sources
    - Identifying complementary or contradictory information
    - Discovering non-obvious connections through shared entities
    - Generating comprehensive, well-supported answers
    - Providing explicit reasoning traces and evidence chains
    """

    def __init__(
        self,
        dataset,
        hybrid_search: Optional[HybridVectorGraphSearch] = None,
        llm_integration: Optional[GraphRAGIntegration] = None
    ):
        """
        Initialize cross-document reasoner.

        Args:
            dataset: VectorAugmentedGraphDataset instance
            hybrid_search: Optional hybrid search instance
            llm_integration: Optional LLM integration instance
        """
        self.dataset = dataset
        self.hybrid_search = hybrid_search or HybridVectorGraphSearch(dataset)
        self.llm_integration = llm_integration

        # Initialize metrics
        self.metrics = {
            "queries_processed": 0,
            "evidence_chains_found": 0,
            "avg_evidence_chain_length": 0.0,
            "entity_count": 0
        }

    def find_evidence_chains(
        self,
        query_embedding: np.ndarray,
        entity_types: List[str] = ["concept", "entity", "topic"],
        max_docs: int = 10,
        max_entities: int = 5,
        min_doc_score: float = 0.6
    ) -> List[Dict[str, Any]]:
        """
        Find evidence chains connecting documents.

        Args:
            query_embedding: Query embedding vector
            entity_types: Types of entities to consider as connectors
            max_docs: Maximum number of documents to consider
            max_entities: Maximum number of connecting entities to use
            min_doc_score: Minimum document relevance score

        Returns:
            List of evidence chains with connected documents and entities
        """
        self.metrics["queries_processed"] += 1

        # First, use entity-mediated search to find connected document pairs
        connected_pairs = self.hybrid_search.entity_mediated_search(
            query_embedding,
            entity_types=entity_types,
            top_k=max_docs,
            max_connecting_entities=max_entities
        )

        # Filter out pairs with low scores
        filtered_pairs = []
        for pair in connected_pairs:
            if (pair["doc1"]["score"] >= min_doc_score or
                pair["doc2"]["score"] >= min_doc_score):
                filtered_pairs.append(pair)

        # Structure as evidence chains
        evidence_chains = []
        for pair in filtered_pairs:
            # Get context from documents
            doc1_context = self._get_document_context(pair["doc1"]["id"])
            doc2_context = self._get_document_context(pair["doc2"]["id"])

            # Create evidence chain
            chain = {
                "doc1": {
                    "id": pair["doc1"]["id"],
                    "title": pair["doc1"]["title"],
                    "type": pair["doc1"]["type"],
                    "score": pair["doc1"]["score"],
                    "context": doc1_context
                },
                "doc2": {
                    "id": pair["doc2"]["id"],
                    "title": pair["doc2"]["title"],
                    "type": pair["doc2"]["type"],
                    "score": pair["doc2"]["score"],
                    "context": doc2_context
                },
                "entity": {
                    "id": pair["entity"]["id"],
                    "name": pair["entity"]["name"],
                    "type": pair["entity"]["type"]
                },
                "chain_score": pair["pair_score"]
            }

            evidence_chains.append(chain)

        # Update metrics
        self.metrics["evidence_chains_found"] += len(evidence_chains)
        if evidence_chains:
            self.metrics["avg_evidence_chain_length"] = 2.0  # Each chain connects 2 docs

        entities_used = set()
        for chain in evidence_chains:
            entities_used.add(chain["entity"]["id"])
        self.metrics["entity_count"] = len(entities_used)

        return evidence_chains

    def _get_document_context(self, doc_id: str, max_length: int = 500) -> str:
        """
        Get context from a document.

        Args:
            doc_id: Document ID
            max_length: Maximum context length

        Returns:
            Document context as string
        """
        # Get document data
        doc = self.dataset.get_node(doc_id)

        # Try to get content from various field names
        for field in ["content", "text", "body", "fulltext"]:
            if field in doc and doc[field]:
                content = doc[field]
                if isinstance(content, str):
                    # Truncate if needed
                    if len(content) > max_length:
                        return content[:max_length] + "..."
                    return content

        # If no content field found, use title or description
        if "title" in doc and "description" in doc:
            return f"{doc['title']}: {doc['description']}"
        elif "title" in doc:
            return doc["title"]

        # Fallback
        return "No content available"

    def reason_across_documents(
        self,
        query: str,
        query_embedding: np.ndarray,
        reasoning_depth: str = "moderate",
        entity_types: List[str] = ["concept", "entity", "topic"],
        max_docs: int = 10,
        max_evidence_chains: int = 5
    ) -> Dict[str, Any]:
        """
        Reason across multiple documents to answer a query.

        Args:
            query: User query
            query_embedding: Query embedding vector
            reasoning_depth: Reasoning depth ('basic', 'moderate', 'deep')
            entity_types: Types of entities to consider as connectors
            max_docs: Maximum number of documents to consider
            max_evidence_chains: Maximum number of evidence chains to use

        Returns:
            Reasoning results with answer and explanation
        """
        # Find evidence chains
        evidence_chains = self.find_evidence_chains(
            query_embedding,
            entity_types=entity_types,
            max_docs=max_docs
        )

        # Limit evidence chains
        evidence_chains = evidence_chains[:max_evidence_chains]

        # Get relevant documents
        doc_ids = set()
        for chain in evidence_chains:
            doc_ids.add(chain["doc1"]["id"])
            doc_ids.add(chain["doc2"]["id"])

        # Get document data
        documents = []
        for doc_id in doc_ids:
            node = self.dataset.get_node(doc_id)

            # Format document for reasoning
            doc = {
                "id": doc_id,
                "title": node.get("title", f"Document {doc_id}"),
                "content": self._get_document_context(doc_id, max_length=1000),
                "type": node.get("type", "document")
            }

            # Get document score by finding it in evidence chains
            doc_score = 0.0
            for chain in evidence_chains:
                if chain["doc1"]["id"] == doc_id:
                    doc_score = max(doc_score, chain["doc1"]["score"])
                if chain["doc2"]["id"] == doc_id:
                    doc_score = max(doc_score, chain["doc2"]["score"])

            doc["score"] = doc_score
            documents.append(doc)

        # If we have LLM integration, use it for cross-document reasoning
        if self.llm_integration:
            result = self._synthesize_with_llm(
                query,
                documents,
                evidence_chains,
                reasoning_depth
            )
        else:
            # Basic synthesis without LLM
            result = self._basic_synthesis(
                query,
                documents,
                evidence_chains
            )

        return result

    def _synthesize_with_llm(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        evidence_chains: List[Dict[str, Any]],
        reasoning_depth: str
    ) -> Dict[str, Any]:
        """
        Synthesize information using LLM integration.

        Args:
            query: User query
            documents: List of relevant documents
            evidence_chains: List of evidence chains
            reasoning_depth: Reasoning depth level

        Returns:
            Synthesis results
        """
        # Let the LLM integration handle the synthesis
        return self.llm_integration._enhanced_synthesize_cross_document_information(
            query,
            [(doc, doc.get("score", 0.0)) for doc in documents],
            evidence_chains,
            reasoning_depth
        )

    def _basic_synthesis(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        evidence_chains: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Simple information synthesis without LLM.

        Args:
            query: User query
            documents: List of relevant documents
            evidence_chains: List of evidence chains

        Returns:
            Synthesis results
        """
        # Sort documents by relevance score
        sorted_docs = sorted(documents, key=lambda x: x.get("score", 0), reverse=True)

        # Extract connecting entities
        connecting_entities = set()
        for chain in evidence_chains:
            connecting_entities.add(chain["entity"]["name"])

        # Basic synthesis - extract most relevant info
        synthesis = {
            "answer": f"Found {len(documents)} relevant documents connected by {len(connecting_entities)} key concepts: {', '.join(list(connecting_entities)[:3])}.",
            "reasoning_trace": [
                {"step": "Document retrieval", "description": f"Retrieved {len(documents)} relevant documents"},
                {"step": "Connection analysis", "description": f"Found connections through entities: {', '.join(list(connecting_entities))}"},
                {"step": "Key information", "description": f"Most relevant document: {sorted_docs[0]['title'] if sorted_docs else 'None'}"}
            ],
            "documents": sorted_docs,
            "evidence_chains": evidence_chains,
            "connecting_entities": list(connecting_entities)
        }

        return synthesis

    def create_knowledge_subgraph(
        self,
        evidence_chains: List[Dict[str, Any]]
    ) -> KnowledgeGraph:
        """
        Create a focused knowledge graph from evidence chains.

        Args:
            evidence_chains: List of evidence chains

        Returns:
            KnowledgeGraph representing the evidence network
        """
        # Create a new knowledge graph
        kg = KnowledgeGraph(name="evidence_graph")

        # Track entities and documents we've already added
        added_entities = {}
        added_documents = {}

        # Add entities and documents from evidence chains
        for chain in evidence_chains:
            # Add the connecting entity if not already added
            entity_id = chain["entity"]["id"]
            if entity_id not in added_entities:
                entity = kg.add_entity(
                    entity_type=chain["entity"]["type"],
                    name=chain["entity"]["name"],
                    entity_id=entity_id
                )
                added_entities[entity_id] = entity
            else:
                entity = added_entities[entity_id]

            # Add document 1 if not already added
            doc1_id = chain["doc1"]["id"]
            if doc1_id not in added_documents:
                doc1 = kg.add_entity(
                    entity_type=chain["doc1"]["type"],
                    name=chain["doc1"]["title"],
                    entity_id=doc1_id,
                    properties={"score": chain["doc1"]["score"]}
                )
                added_documents[doc1_id] = doc1
            else:
                doc1 = added_documents[doc1_id]

            # Add document 2 if not already added
            doc2_id = chain["doc2"]["id"]
            if doc2_id not in added_documents:
                doc2 = kg.add_entity(
                    entity_type=chain["doc2"]["type"],
                    name=chain["doc2"]["title"],
                    entity_id=doc2_id,
                    properties={"score": chain["doc2"]["score"]}
                )
                added_documents[doc2_id] = doc2
            else:
                doc2 = added_documents[doc2_id]

            # Add relationships
            kg.add_relationship(
                relationship_type="mentions",
                source=doc1,
                target=entity,
                properties={"confidence": chain["chain_score"]}
            )

            kg.add_relationship(
                relationship_type="mentions",
                source=doc2,
                target=entity,
                properties={"confidence": chain["chain_score"]}
            )

        return kg

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get cross-document reasoning metrics.

        Returns:
            Dictionary of metrics
        """
        return self.metrics


class GraphRAGFactory:
    """
    Factory for creating and composing GraphRAG components.

    This class provides methods for creating and composing various
    GraphRAG components for different use cases and configurations.
    It implements the Factory pattern to simplify the creation of
    complex GraphRAG systems with appropriate component integration.

    Key Features:
    - Component creation with sensible defaults
    - Easy composition of multiple components
    - Configuration-driven system creation
    - Component sharing and reference management
    - Integration of complementary features

    The factory enables various configurations:
    - Basic vector search augmentation with HybridVectorGraphSearch
    - LLM-enhanced reasoning with GraphRAGIntegration
    - Cross-document reasoning with CrossDocumentReasoner
    - Comprehensive query processing with GraphRAGQueryEngine
    - Complete GraphRAG systems with all integrated components
    """

    @staticmethod
    def create_hybrid_search(
        dataset,
        vector_weight: float = 0.6,
        graph_weight: float = 0.4,
        max_graph_hops: int = 2,
        min_score_threshold: float = 0.5,
        use_bidirectional_traversal: bool = True
    ) -> HybridVectorGraphSearch:
        """
        Create a hybrid vector + graph search for a dataset.

        Args:
            dataset: VectorAugmentedGraphDataset instance
            vector_weight: Weight for vector similarity scores
            graph_weight: Weight for graph traversal scores
            max_graph_hops: Maximum graph traversal hops
            min_score_threshold: Minimum score threshold
            use_bidirectional_traversal: Whether to traverse in both directions

        Returns:
            HybridVectorGraphSearch instance
        """
        return enhance_dataset_with_hybrid_search(
            dataset,
            vector_weight=vector_weight,
            graph_weight=graph_weight,
            max_graph_hops=max_graph_hops,
            min_score_threshold=min_score_threshold,
            use_bidirectional_traversal=use_bidirectional_traversal
        )

    @staticmethod
    def create_llm_integration(
        dataset,
        validate_outputs: bool = True,
        llm_processor: Optional[GraphRAGLLMProcessor] = None,
        performance_monitor: Optional[GraphRAGPerformanceMonitor] = None,
        validator: Optional[SemanticValidator] = None,
        # tracing_manager: Optional[TracingManager] = None, # Removed TracingManager type hint
        enable_tracing: bool = True
    ) -> GraphRAGIntegration:
        """
        Create an LLM-enhanced integration for a dataset.

        Args:
            dataset: VectorAugmentedGraphDataset instance
            validate_outputs: Whether to validate outputs
            llm_processor: Optional LLM processor
            performance_monitor: Optional performance monitor
            validator: Optional semantic validator
            tracing_manager: Optional tracing manager
            enable_tracing: Whether to enable tracing

        Returns:
            GraphRAGIntegration instance
        """
        integration = GraphRAGIntegration(
            dataset,
            llm_processor=llm_processor,
            performance_monitor=performance_monitor,
            validator=validator,
            # tracing_manager=tracing_manager, # Removed TracingManager usage
            validate_outputs=validate_outputs,
            enable_tracing=enable_tracing
        )
        return integration

    @staticmethod
    def create_cross_document_reasoner(
        dataset,
        hybrid_search: Optional[HybridVectorGraphSearch] = None,
        llm_integration: Optional[GraphRAGIntegration] = None
    ) -> CrossDocumentReasoner:
        """
        Create a cross-document reasoner.

        Args:
            dataset: VectorAugmentedGraphDataset instance
            hybrid_search: Optional hybrid search instance
            llm_integration: Optional LLM integration instance

        Returns:
            CrossDocumentReasoner instance
        """
        # Create hybrid search if not provided
        if hybrid_search is None:
            hybrid_search = GraphRAGFactory.create_hybrid_search(dataset)

        # Create cross-document reasoner
        reasoner = CrossDocumentReasoner(
            dataset,
            hybrid_search=hybrid_search,
            llm_integration=llm_integration
        )

        # Attach to dataset for convenience
        setattr(dataset, "cross_document_reasoner", reasoner)

        return reasoner

    @staticmethod
    def create_query_engine(
        dataset,
        vector_stores: Dict[str, Any],
        graph_store: Any,
        model_weights: Optional[Dict[str, float]] = None,
        query_optimizer = None,
        hybrid_search: Optional[HybridVectorGraphSearch] = None,
        llm_integration: Optional[GraphRAGIntegration] = None,
        enable_cross_document_reasoning: bool = True,
        enable_query_rewriting: bool = True,
        enable_budget_management: bool = True
    ) -> GraphRAGQueryEngine:
        """
        Create a GraphRAG query engine.

        Args:
            dataset: VectorAugmentedGraphDataset instance
            vector_stores: Dictionary mapping model names to vector stores
            graph_store: Knowledge graph store instance
            model_weights: Optional weights for each model's results
            query_optimizer: Optional query optimizer instance
            hybrid_search: Optional hybrid search instance
            llm_integration: Optional LLM integration instance
            enable_cross_document_reasoning: Whether to enable cross-document reasoning
            enable_query_rewriting: Whether to enable query rewriting
            enable_budget_management: Whether to enable budget management

        Returns:
            GraphRAGQueryEngine instance
        """
        # Create hybrid search if not provided
        if hybrid_search is None:
            hybrid_search = GraphRAGFactory.create_hybrid_search(dataset)

        # Create query engine
        query_engine = GraphRAGQueryEngine(
            dataset=dataset,
            vector_stores=vector_stores,
            graph_store=graph_store,
            model_weights=model_weights,
            hybrid_search=hybrid_search,
            llm_integration=llm_integration,
            query_optimizer=query_optimizer,
            enable_cross_document_reasoning=enable_cross_document_reasoning,
            enable_query_rewriting=enable_query_rewriting,
            enable_budget_management=enable_budget_management
        )

        # Attach to dataset for convenience
        setattr(dataset, "query_engine", query_engine)

        return query_engine

    @staticmethod
    def create_complete_integration(
        dataset,
        vector_weight: float = 0.6,
        graph_weight: float = 0.4,
        max_graph_hops: int = 2,
        validate_outputs: bool = True,
        enable_tracing: bool = True
    ) -> Tuple[HybridVectorGraphSearch, GraphRAGIntegration, CrossDocumentReasoner]:
        """
        Create a complete GraphRAG integration with hybrid search, LLM enhancement,
        and cross-document reasoning.

        Args:
            dataset: VectorAugmentedGraphDataset instance
            vector_weight: Weight for vector similarity scores
            graph_weight: Weight for graph traversal scores
            max_graph_hops: Maximum graph traversal hops
            validate_outputs: Whether to validate outputs
            enable_tracing: Whether to enable tracing

        Returns:
            Tuple of (HybridVectorGraphSearch, GraphRAGIntegration, CrossDocumentReasoner)
        """
        # Create performance monitor to share between components
        performance_monitor = GraphRAGPerformanceMonitor()

        # Create LLM processor with shared performance monitor
        llm_processor = GraphRAGLLMProcessor(performance_monitor=performance_monitor)


        # Create semantic validator
        validator = SemanticValidator()

        # Create hybrid search
        hybrid_search = GraphRAGFactory.create_hybrid_search(
            dataset,
            vector_weight=vector_weight,
            graph_weight=graph_weight,
            max_graph_hops=max_graph_hops
        )

        # Create LLM integration
        llm_integration = GraphRAGFactory.create_llm_integration(
            dataset,
            validate_outputs=validate_outputs,
            llm_processor=llm_processor,
            performance_monitor=performance_monitor,
            validator=validator,
            enable_tracing=enable_tracing
        )

        # Create cross-document reasoner
        cross_doc_reasoner = GraphRAGFactory.create_cross_document_reasoner(
            dataset,
            hybrid_search=hybrid_search,
            llm_integration=llm_integration
        )

        # Setup GraphRAG as complete system on the dataset
        setattr(dataset, "graphrag", {
            "hybrid_search": hybrid_search,
            "llm_integration": llm_integration,
            "cross_document_reasoner": cross_doc_reasoner,
            "performance_monitor": performance_monitor
        })

        return hybrid_search, llm_integration, cross_doc_reasoner

    @staticmethod
    def create_graphrag_system(dataset, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Create a complete GraphRAG system with configuration options.

        Args:
            dataset: VectorAugmentedGraphDataset instance
            config: Configuration options for the GraphRAG system
                   (vector_weight, graph_weight, max_graph_hops, etc.)

        Returns:
            Dictionary of GraphRAG components
        """
        config = config or {}

        # Extract configuration options
        vector_weight = config.get("vector_weight", 0.6)
        graph_weight = config.get("graph_weight", 0.4)
        max_graph_hops = config.get("max_graph_hops", 2)
        min_score_threshold = config.get("min_score_threshold", 0.5)
        use_bidirectional_traversal = config.get("use_bidirectional_traversal", True)
        validate_outputs = config.get("validate_outputs", True)
        enable_tracing = config.get("enable_tracing", True)
        enable_query_rewriting = config.get("enable_query_rewriting", True)
        enable_budget_management = config.get("enable_budget_management", True)

        # Create the components
        hybrid_search, llm_integration, cross_doc_reasoner = GraphRAGFactory.create_complete_integration(
            dataset,
            vector_weight=vector_weight,
            graph_weight=graph_weight,
            max_graph_hops=max_graph_hops,
            validate_outputs=validate_outputs,
            enable_tracing=enable_tracing
        )

        # Get the shared performance monitor
        performance_monitor = getattr(dataset, "graphrag", {}).get("performance_monitor")

        # Check if query engine should be created
        query_engine = None
        vector_stores = config.get("vector_stores")
        graph_store = config.get("graph_store")
        if vector_stores and graph_store:
            # Get query optimizer if available
            query_optimizer = config.get("query_optimizer")

            # Create query engine
            query_engine = GraphRAGFactory.create_query_engine(
                dataset=dataset,
                vector_stores=vector_stores,
                graph_store=graph_store,
                model_weights=config.get("model_weights"),
                query_optimizer=query_optimizer,
                hybrid_search=hybrid_search,
                llm_integration=llm_integration,
                enable_cross_document_reasoning=config.get("enable_cross_document_reasoning", True),
                enable_query_rewriting=enable_query_rewriting,
                enable_budget_management=enable_budget_management
            )

        # Return the GraphRAG system
        system = {
            "hybrid_search": hybrid_search,
            "llm_integration": llm_integration,
            "cross_document_reasoner": cross_doc_reasoner,
            "performance_monitor": performance_monitor,
            "config": config
        }

        # Add query engine if created
        if query_engine:
            system["query_engine"] = query_engine

        return system


class GraphRAGQueryEngine:
    """
    Query engine combining vector search and knowledge graph traversal.

    This class provides a unified interface for querying across vector stores
    and knowledge graphs, supporting multi-model embeddings and advanced query
    optimization techniques.
    """

    def __init__(
        self,
        dataset,
        vector_stores: Dict[str, Any],
        graph_store: Any,
        model_weights: Optional[Dict[str, float]] = None,
        hybrid_search: Optional[HybridVectorGraphSearch] = None,
        llm_integration: Optional[GraphRAGIntegration] = None,
        query_optimizer = None,
        enable_cross_document_reasoning: bool = True,
        enable_query_rewriting: bool = True,
        enable_budget_management: bool = True
    ):
        """
        Initialize the GraphRAG query engine.

        Args:
            dataset: The underlying vector-augmented graph dataset
            vector_stores: Dictionary mapping model names to vector stores
            graph_store: Knowledge graph store instance
            model_weights: Optional weights for each model's results
            hybrid_search: Optional hybrid search instance
            llm_integration: Optional LLM integration instance
            query_optimizer: Optional query optimizer instance
            enable_cross_document_reasoning: Whether to enable cross-document reasoning
            enable_query_rewriting: Whether to enable query rewriting
            enable_budget_management: Whether to enable budget management
        """
        self.dataset = dataset
        self.vector_stores = vector_stores
        self.graph_store = graph_store
        self.model_weights = model_weights or {
            model_name: 1.0 / len(vector_stores) for model_name in vector_stores
        }

        # Normalize weights
        total_weight = sum(self.model_weights.values())
        self.model_weights = {
            model_name: weight / total_weight
            for model_name, weight in self.model_weights.items()
        }

        # Set up hybrid search if not provided
        self.hybrid_search = hybrid_search or HybridVectorGraphSearch(
            dataset,
            vector_weight=0.6,
            graph_weight=0.4,
            max_graph_hops=2
        )

        # Set up LLM integration if enabled
        self.llm_integration = llm_integration

        # Set up cross-document reasoner if enabled
        self.cross_document_reasoner = None
        if enable_cross_document_reasoning:
            self.cross_document_reasoner = CrossDocumentReasoner(
                dataset,
                hybrid_search=self.hybrid_search,
                llm_integration=self.llm_integration
            )

        # Set up query optimizer if provided
        self.query_optimizer = query_optimizer
        self.enable_query_rewriting = enable_query_rewriting
        self.enable_budget_management = enable_budget_management

        # Initialize metrics
        self.metrics = {
            "queries_processed": 0,
            "total_query_time": 0.0,
            "avg_query_time": 0.0,
            "vector_searches": 0,
            "graph_traversals": 0,
            "cross_document_reasoning_uses": 0
        }

    def query(
        self,
        query_text: str,
        query_embeddings: Optional[Dict[str, np.ndarray]] = None,
        top_k: int = 10,
        include_vector_results: bool = True,
        include_graph_results: bool = True,
        include_cross_document_reasoning: bool = True,
        entity_types: Optional[List[str]] = None,
        relationship_types: Optional[List[str]] = None,
        min_relevance: float = 0.5,
        max_graph_hops: int = 2,
        reasoning_depth: str = "moderate",
        return_trace: bool = False
    ) -> Dict[str, Any]:
        """
        Perform a GraphRAG query combining vector search and graph traversal.

        Args:
            query_text: Natural language query text
            query_embeddings: Optional pre-computed embeddings for each model
            top_k: Number of results to return
            include_vector_results: Whether to include vector search results
            include_graph_results: Whether to include graph traversal results
            include_cross_document_reasoning: Whether to include cross-document reasoning
            entity_types: Types of entities to include in traversal
            relationship_types: Types of relationships to traverse
            min_relevance: Minimum relevance score for results
            max_graph_hops: Maximum graph traversal hops
            reasoning_depth: Reasoning depth for cross-document reasoning
            return_trace: Whether to return reasoning trace

        Returns:
            Dictionary containing query results, potentially including:
            - vector_results: Results from vector search
            - graph_results: Results from graph traversal
            - hybrid_results: Combined results from hybrid search
            - evidence_chains: Cross-document evidence chains
            - reasoning_result: Result of cross-document reasoning
            - trace_id: ID of the reasoning trace if return_trace is True
        """
        start_time = time.time()
        self.metrics["queries_processed"] += 1

        # Apply query optimization if enabled and optimizer is available
        optimized_query = query_text
        optimization_info = {}
        if self.enable_query_rewriting and self.query_optimizer:
            optimized_query, optimization_info = self.query_optimizer.rewrite_query(
                query_text,
                context={
                    "entity_types": entity_types,
                    "relationship_types": relationship_types,
                    "reasoning_depth": reasoning_depth
                }
            )

        # Compute query embeddings if not provided
        if query_embeddings is None:
            query_embeddings = self._compute_query_embeddings(optimized_query)

        # Initialize results dictionary
        results = {
            "query": query_text,
            "optimized_query": optimized_query,
            "optimization_info": optimization_info,
            "query_time": 0.0
        }

        # Prepare budget if budget management is enabled
        budget = None
        if self.enable_budget_management and self.query_optimizer:
            budget = self.query_optimizer.allocate_budget(
                optimized_query,
                context={
                    "entity_types": entity_types,
                    "relationship_types": relationship_types,
                    "reasoning_depth": reasoning_depth,
                    "include_vector": include_vector_results,
                    "include_graph": include_graph_results,
                    "include_reasoning": include_cross_document_reasoning
                }
            )
            results["budget"] = budget

        # Perform search based on enabled components

        # 1. Vector search if enabled
        if include_vector_results:
            results["vector_results"] = self._perform_vector_search(
                query_embeddings,
                top_k=top_k,
                min_relevance=min_relevance
            )
            self.metrics["vector_searches"] += 1

        # 2. Hybrid search if both vector and graph are enabled
        if include_vector_results and include_graph_results:
            # Use the default model's embedding or the first one available
            default_model = next(iter(query_embeddings))
            default_embedding = query_embeddings[default_model]

            results["hybrid_results"] = self.hybrid_search.hybrid_search(
                query_embedding=default_embedding,
                top_k=top_k,
                relationship_types=relationship_types,
                entity_types=entity_types,
                min_vector_score=min_relevance
            )
            self.metrics["graph_traversals"] += 1

        # 3. Cross-document reasoning if enabled
        if include_cross_document_reasoning and self.cross_document_reasoner:
            # Use the default model's embedding for cross-document reasoning
            default_model = next(iter(query_embeddings))
            default_embedding = query_embeddings[default_model]

            evidence_chains = self.cross_document_reasoner.find_evidence_chains(
                query_embedding=default_embedding,
                entity_types=entity_types or ["concept", "entity", "topic"],
                max_docs=top_k * 2,
                max_entities=5
            )

            reasoning_result = self.cross_document_reasoner.reason_across_documents(
                query=optimized_query,
                query_embedding=default_embedding,
                reasoning_depth=reasoning_depth,
                entity_types=entity_types or ["concept", "entity", "topic"],
                max_docs=top_k * 2,
                max_evidence_chains=len(evidence_chains)
            )

            results["evidence_chains"] = evidence_chains
            results["reasoning_result"] = reasoning_result
            self.metrics["cross_document_reasoning_uses"] += 1

            # Add trace ID if requested and available
            if return_trace and "trace_id" in reasoning_result:
                results["trace_id"] = reasoning_result["trace_id"]

        # Check early stopping if budget management is enabled
        if budget and self.query_optimizer:
            should_stop = self.query_optimizer.check_early_stopping(
                results=results,
                state={"query_time": time.time() - start_time},
                budget=budget
            )
            results["early_stopping"] = should_stop

        # Record query time
        query_time = time.time() - start_time
        results["query_time"] = query_time
        self.metrics["total_query_time"] += query_time
        self.metrics["avg_query_time"] = (
            self.metrics["total_query_time"] / self.metrics["queries_processed"]
        )

        return results

    def _compute_query_embeddings(self, query_text: str) -> Dict[str, np.ndarray]:
        """
        Compute embeddings for the query across all models.

        Args:
            query_text: Query text to embed

        Returns:
            Dictionary mapping model names to embeddings
        """
        embeddings = {}

        for model_name, vector_store in self.vector_stores.items():
            # Get the embedder for this model
            # This assumes vector stores have an 'embed_query' method or similar
            if hasattr(vector_store, 'embed_query'):
                embeddings[model_name] = vector_store.embed_query(query_text)
            elif hasattr(vector_store, 'encoder') and hasattr(vector_store.encoder, 'encode'):
                embeddings[model_name] = vector_store.encoder.encode(query_text)
            else:
                # Fallback to dataset's encode method if available
                if hasattr(self.dataset, 'encode_query'):
                    embeddings[model_name] = self.dataset.encode_query(query_text, model_name=model_name)

        return embeddings

    def _perform_vector_search(
        self,
        query_embeddings: Dict[str, np.ndarray],
        top_k: int = 10,
        min_relevance: float = 0.5
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Perform vector search across all models.

        Args:
            query_embeddings: Dictionary mapping model names to embeddings
            top_k: Number of results to return per model
            min_relevance: Minimum relevance score

        Returns:
            Dictionary mapping model names to search results
        """
        results = {}

        for model_name, embedding in query_embeddings.items():
            if model_name in self.vector_stores:
                vector_store = self.vector_stores[model_name]

                # This assumes vector stores have a 'search' method
                if hasattr(vector_store, 'search'):
                    model_results = vector_store.search(
                        embedding,
                        top_k=top_k,
                        min_score=min_relevance
                    )
                    results[model_name] = model_results

        return results

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get query engine metrics.

        Returns:
            Dictionary of metrics
        """
        metrics = self.metrics.copy()

        # Add component-specific metrics
        if self.hybrid_search:
            metrics["hybrid_search"] = self.hybrid_search.get_metrics()

        if self.cross_document_reasoner:
            metrics["cross_doc_reasoning"] = self.cross_document_reasoner.get_metrics()

        if self.llm_integration:
            metrics["llm_integration"] = self.llm_integration.get_performance_metrics()

        if self.query_optimizer:
            metrics["query_optimization"] = self.query_optimizer.get_metrics()

        return metrics

    def explain_query_result(
        self,
        result: Dict[str, Any],
        explanation_type: str = "summary",
        target_audience: str = "general"
    ) -> Dict[str, Any]:
        """
        Generate an explanation for a query result.

        Args:
            result: Query result to explain
            explanation_type: Type of explanation ('summary', 'detailed', 'technical')
            target_audience: Target audience ('general', 'technical', 'expert')

        Returns:
            Explanation data
        """
        # If we have LLM integration and a trace ID, use that for explanation
        if self.llm_integration and "trace_id" in result:
            return self.llm_integration.explain_trace(
                result["trace_id"],
                explanation_type=explanation_type,
                target_audience=target_audience
            )

        # Otherwise, generate a basic explanation
        explanation = {
            "summary": "Query processed using GraphRAG technology.",
            "details": []
        }

        # Add information about the query optimization
        if "optimization_info" in result and result["optimization_info"]:
            optimization = result["optimization_info"]
            explanation["details"].append(
                f"Query was optimized: {result['query']} → {result['optimized_query']}"
            )

            if "transformation_applied" in optimization:
                explanation["details"].append(
                    f"Transformation: {optimization['transformation_applied']}"
                )

        # Add information about the search results
        if "hybrid_results" in result:
            explanation["details"].append(
                f"Found {len(result['hybrid_results'])} results using hybrid vector + graph search."
            )

        if "reasoning_result" in result:
            explanation["details"].append(
                f"Performed cross-document reasoning across multiple sources."
            )

            if "answer" in result["reasoning_result"]:
                explanation["answer"] = result["reasoning_result"]["answer"]

        if "query_time" in result:
            explanation["details"].append(
                f"Query processed in {result['query_time']:.2f} seconds."
            )

        if "early_stopping" in result and result["early_stopping"]:
            explanation["details"].append(
                "Query processing was stopped early due to sufficient results."
            )

        return explanation

    def visualize_query_result(
        self,
        result: Dict[str, Any],
        format: str = "text"
    ) -> Dict[str, Any]:
        """
        Generate a visualization of a query result.

        Args:
            result: Query result to visualize
            format: Visualization format ('text', 'html', 'mermaid')

        Returns:
            Visualization data
        """
        # If we have LLM integration and a trace ID, use that for visualization
        if self.llm_integration and "trace_id" in result:
            return self.llm_integration.visualize_trace(
                result["trace_id"],
                format=format
            )

        # Otherwise, return a basic text visualization
        if format == "text":
            lines = [
                "GraphRAG Query Result",
                "===================",
                f"Query: {result.get('query', 'Unknown')}",
                f"Time: {result.get('query_time', 0):.2f} seconds",
                ""
            ]

            if "vector_results" in result:
                lines.append("Vector Search Results:")
                for model, model_results in result["vector_results"].items():
                    lines.append(f"  Model: {model}")
                    for i, res in enumerate(model_results[:3]):
                        lines.append(f"  - Result {i+1}: Score={res.get('score', 0):.2f}")
                lines.append("")

            if "hybrid_results" in result:
                lines.append("Hybrid Search Results:")
                for i, res in enumerate(result["hybrid_results"][:3]):
                    lines.append(f"  - Result {i+1}: Score={res.get('combined_score', 0):.2f}")
                    if "path" in res and res["path"]:
                        path_desc = " → ".join([p.get("relationship", "related") for p in res["path"]])
                        lines.append(f"    Path: {path_desc}")
                lines.append("")

            if "reasoning_result" in result and "answer" in result["reasoning_result"]:
                lines.append("Cross-Document Reasoning:")
                lines.append(f"  {result['reasoning_result']['answer']}")
                lines.append("")

            return {"visualization": "\n".join(lines)}

        elif format == "mermaid":
            # Create a simple Mermaid graph diagram
            mermaid = [
                "graph TD",
                f"    Q[Query: {result.get('query', 'Unknown')}]"
            ]

            # Add vector search results
            if "vector_results" in result:
                mermaid.append("    Q --> V[Vector Search]")
                for model, model_results in result["vector_results"].items():
                    model_id = f"V_{model.replace('-', '_')}"
                    mermaid.append(f"    V --> {model_id}[{model}]")
                    for i, res in enumerate(model_results[:2]):
                        res_id = f"{model_id}_{i}"
                        mermaid.append(f"    {model_id} --> {res_id}[Result {i+1}: {res.get('score', 0):.2f}]")

            # Add hybrid search results
            if "hybrid_results" in result:
                mermaid.append("    Q --> H[Hybrid Search]")
                for i, res in enumerate(result["hybrid_results"][:2]):
                    res_id = f"H_{i}"
                    mermaid.append(f"    H --> {res_id}[Result {i+1}: {res.get('combined_score', 0):.2f}]")

            # Add reasoning result
            if "reasoning_result" in result:
                mermaid.append("    Q --> R[Cross-Document Reasoning]")
                if "answer" in result["reasoning_result"]:
                    answer = result["reasoning_result"]["answer"]
                    if len(answer) > 50:
                        answer = answer[:47] + "..."
                    mermaid.append(f"    R --> A[Answer: {answer}]")

            return {"visualization": "\n".join(mermaid)}

        else:
            return {"error": f"Unsupported visualization format: {format}"}


def example_graphrag_usage(dataset, query: str) -> Dict[str, Any]:
    """
    Example function demonstrating a complete GraphRAG workflow.

    This function shows a comprehensive workflow for using the GraphRAG system:
    1. Initialize the GraphRAG components with factory
    2. Convert query to embeddings (potentially using multiple models)
    3. Perform hybrid search combining vector similarity and graph traversal
    4. Find evidence chains for cross-document reasoning through entity-mediated connections
    5. Synthesize information across documents using cross-document reasoning
    6. Generate visualizations and explanations of the reasoning process

    Args:
        dataset: VectorAugmentedGraphDataset instance
        query: User query as string

    Returns:
        Dictionary containing:
        - query: Original query
        - search_results: Results from hybrid search
        - evidence_chains: Connections between documents via shared entities
        - reasoning_result: Cross-document reasoning result with synthesized answer
        - subgraph_entity_count: Number of entities in the knowledge subgraph
        - subgraph_relationship_count: Number of relationships in the knowledge subgraph
    """
    # Initialize GraphRAG system
    graphrag = GraphRAGFactory.create_graphrag_system(dataset)

    # Get the components
    hybrid_search = graphrag["hybrid_search"]
    cross_doc_reasoner = graphrag["cross_document_reasoner"]

    # Step 1: Convert query to embedding
    # In a real implementation, this would use the appropriate embedding model
    # For demonstration, we'll assume the dataset provides a method for this
    query_embedding = dataset.encode_query(query)

    # Step 2: Perform hybrid search combining vector similarity with graph traversal
    search_results = hybrid_search.hybrid_search(
        query_embedding,
        top_k=10,
        relationship_types=None,  # Use all relationship types
        entity_types=None,  # Use all entity types
        min_vector_score=0.5
    )

    # Step 3: Find evidence chains for cross-document reasoning
    evidence_chains = cross_doc_reasoner.find_evidence_chains(
        query_embedding,
        entity_types=["concept", "entity", "topic"],
        max_docs=10,
        max_entities=5
    )

    # Step 4: Create a knowledge subgraph from the evidence chains
    knowledge_subgraph = cross_doc_reasoner.create_knowledge_subgraph(evidence_chains)

    # Step 5: Perform cross-document reasoning
    reasoning_result = cross_doc_reasoner.reason_across_documents(
        query=query,
        query_embedding=query_embedding,
        reasoning_depth="moderate",
        entity_types=["concept", "entity", "topic"],
        max_docs=10,
        max_evidence_chains=5
    )

    # Return the combined results
    return {
        "query": query,
        "search_results": search_results,
        "evidence_chains": evidence_chains,
        "reasoning_result": reasoning_result,
        "subgraph_entity_count": knowledge_subgraph.entity_count,
        "subgraph_relationship_count": knowledge_subgraph.relationship_count
    }
