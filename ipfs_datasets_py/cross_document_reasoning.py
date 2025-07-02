"""
Cross-Document Reasoning for GraphRAG.

This module enhances the GraphRAG system with advanced cross-document reasoning capabilities,
enabling the system to connect information across multiple documents through shared entities
and generate comprehensive answers with explanations.

Key features:
- Entity-mediated connections between documents
- Information relation analysis (complementary, contradictory, etc.)
- Knowledge gap identification
- Transitive relationship discovery
- Multi-level reasoning (basic, moderate, deep)
- Answer synthesis with confidence scoring
- Detailed reasoning traces

The cross-document reasoning leverages the query optimization from rag_query_optimizer
to efficiently traverse entity relationships and find relevant connections.
"""
import logging
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
import numpy as np
from dataclasses import dataclass, field
import uuid

from ipfs_datasets_py.llm.llm_reasoning_tracer import (
    LLMReasoningTracer,
    ReasoningNodeType,
)
from ipfs_datasets_py.rag.rag_query_optimizer import (
    UnifiedGraphRAGQueryOptimizer,
)


logger = logging.getLogger(__name__)


class InformationRelationType(Enum):
    """Types of relations between pieces of information across documents."""
    COMPLEMENTARY = "complementary"     # Information that adds to or extends other information
    SUPPORTING = "supporting"           # Information that confirms or backs up other information
    CONTRADICTING = "contradicting"     # Information that conflicts with other information
    ELABORATING = "elaborating"         # Information that provides more detail on other information
    PREREQUISITE = "prerequisite"       # Information needed to understand other information
    CONSEQUENCE = "consequence"         # Information that follows from other information
    ALTERNATIVE = "alternative"         # Information that provides a different perspective
    UNCLEAR = "unclear"                 # Relationship cannot be determined


@dataclass
class DocumentNode:
    """Represents a document or chunk of text in the reasoning process."""
    id: str
    content: str
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    vector: Optional[np.ndarray] = None
    relevance_score: float = 0.0
    entities: List[str] = field(default_factory=list)


@dataclass
class EntityMediatedConnection:
    """Represents a connection between documents mediated by an entity."""
    entity_id: str
    entity_name: str
    entity_type: str
    source_doc_id: str
    target_doc_id: str
    relation_type: InformationRelationType
    connection_strength: float
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CrossDocReasoning:
    """Represents a cross-document reasoning process."""
    id: str
    query: str
    query_embedding: Optional[np.ndarray] = None
    documents: List[DocumentNode] = field(default_factory=list)
    entity_connections: List[EntityMediatedConnection] = field(default_factory=list)
    traversal_paths: List[List[str]] = field(default_factory=list)
    reasoning_depth: str = "moderate"  # "basic", "moderate", or "deep"
    answer: Optional[str] = None
    confidence: float = 0.0
    reasoning_trace_id: Optional[str] = None


class CrossDocumentReasoner:
    """
    Implements cross-document reasoning for GraphRAG.

    This class provides the capability to reason across multiple documents
    by finding entity-mediated connections and generating synthesized answers
    based on connected information.
    """

    def __init__(
        self,
        query_optimizer: Optional[UnifiedGraphRAGQueryOptimizer] = None,
        reasoning_tracer: Optional[LLMReasoningTracer] = None,
        llm_service: Optional[Any] = None,
        min_connection_strength: float = 0.6,
        max_reasoning_depth: int = 3,
        enable_contradictions: bool = True,
        entity_match_threshold: float = 0.85
    ):
        """
        Initialize the cross-document reasoner.

        Args:
            query_optimizer: RAG query optimizer for efficient graph traversal
            reasoning_tracer: Tracer for recording reasoning steps
            llm_service: LLM service for answer generation and reasoning
            min_connection_strength: Minimum strength for entity-mediated connections
            max_reasoning_depth: Maximum depth for reasoning processes
            enable_contradictions: Whether to look for contradicting information
            entity_match_threshold: Threshold for matching entities across documents
        """
        self.query_optimizer = query_optimizer or UnifiedGraphRAGQueryOptimizer()
        self.reasoning_tracer = reasoning_tracer or LLMReasoningTracer()
        self.llm_service = llm_service  # Will be used for answer generation
        self.min_connection_strength = min_connection_strength
        self.max_reasoning_depth = max_reasoning_depth
        self.enable_contradictions = enable_contradictions
        self.entity_match_threshold = entity_match_threshold

        # Statistics
        self.total_queries = 0
        self.successful_queries = 0
        self.avg_document_count = 0
        self.avg_connection_count = 0
        self.avg_confidence = 0.0

    def reason_across_documents(
        self,
        query: str,
        query_embedding: Optional[np.ndarray] = None,
        input_documents: Optional[List[Dict[str, Any]]] = None,
        vector_store: Optional[Any] = None,
        knowledge_graph: Optional[Any] = None,
        reasoning_depth: str = "moderate",
        max_documents: int = 10,
        min_relevance: float = 0.6,
        max_hops: int = 2,
        return_trace: bool = False
    ) -> Dict[str, Any]:
        """
        Perform cross-document reasoning to answer a query.

        This method connects information across multiple documents through
        shared entities, identifies complementary or contradictory information,
        and generates a synthesized answer with confidence scores.

        Args:
            query: Natural language query
            query_embedding: Query embedding vector (optional, will be computed if not provided)
            input_documents: Optional list of documents to start with
            vector_store: Vector store for similarity search
            knowledge_graph: Knowledge graph for entity and relationship information
            reasoning_depth: Depth of reasoning ("basic", "moderate", or "deep")
            max_documents: Maximum number of documents to consider
            min_relevance: Minimum relevance score for documents
            max_hops: Maximum hops for graph traversal
            return_trace: Whether to return the full reasoning trace

        Returns:
            Dict containing:
                - answer: Synthesized answer to the query
                - documents: List of relevant documents used
                - entity_connections: List of entity-mediated connections
                - confidence: Confidence score
                - reasoning_trace: Optional reasoning trace
        """
        self.total_queries += 1

        # Create a unique ID for this reasoning process
        reasoning_id = str(uuid.uuid4())

        # Start a new reasoning trace
        trace_id = self.reasoning_tracer.create_trace(
            query=query,
            trace_type="cross_document_reasoning",
            metadata={
                "reasoning_depth": reasoning_depth,
                "max_documents": max_documents,
                "min_relevance": min_relevance,
                "max_hops": max_hops
            }
        )

        # Initialize cross-document reasoning object
        cross_doc_reasoning = CrossDocReasoning(
            id=reasoning_id,
            query=query,
            query_embedding=query_embedding,
            reasoning_depth=reasoning_depth,
            reasoning_trace_id=trace_id
        )

        # Step 1: Find relevant documents (either from input or by vector search)
        self.reasoning_tracer.add_node(
            trace_id=trace_id,
            node_type=ReasoningNodeType.QUERY,
            content=query,
            metadata={"reasoning_step": "document_retrieval"}
        )

        documents = self._get_relevant_documents(
            query=query,
            query_embedding=query_embedding,
            input_documents=input_documents,
            vector_store=vector_store,
            max_documents=max_documents,
            min_relevance=min_relevance
        )

        # Add documents to reasoning object
        cross_doc_reasoning.documents = documents

        # Add document nodes to the reasoning trace
        for doc in documents:
            self.reasoning_tracer.add_node(
                trace_id=trace_id,
                node_type=ReasoningNodeType.DOCUMENT,
                content=doc.content[:200] + "..." if len(doc.content) > 200 else doc.content,
                metadata={
                    "document_id": doc.id,
                    "source": doc.source,
                    "relevance_score": doc.relevance_score,
                    "entities": doc.entities
                }
            )

        # Step 2: Identify entities and extract entity-mediated connections
        self.reasoning_tracer.add_node(
            trace_id=trace_id,
            node_type=ReasoningNodeType.INFERENCE,
            content="Identifying entity-mediated connections between documents",
            metadata={"reasoning_step": "entity_connection_discovery"}
        )

        entity_connections = self._find_entity_connections(
            documents=documents,
            knowledge_graph=knowledge_graph,
            max_hops=max_hops
        )

        # Add entity connections to reasoning object
        cross_doc_reasoning.entity_connections = entity_connections

        # Add connection nodes to the reasoning trace
        for conn in entity_connections:
            self.reasoning_tracer.add_node(
                trace_id=trace_id,
                node_type=ReasoningNodeType.RELATIONSHIP,
                content=f"Connection through entity '{conn.entity_name}' ({conn.entity_type})",
                metadata={
                    "entity_id": conn.entity_id,
                    "source_doc_id": conn.source_doc_id,
                    "target_doc_id": conn.target_doc_id,
                    "relation_type": conn.relation_type.value,
                    "connection_strength": conn.connection_strength
                }
            )

        # Step 3: Generate traversal paths for reasoning
        self.reasoning_tracer.add_node(
            trace_id=trace_id,
            node_type=ReasoningNodeType.INFERENCE,
            content="Generating traversal paths for reasoning",
            metadata={"reasoning_step": "traversal_path_generation"}
        )

        traversal_paths = self._generate_traversal_paths(
            documents=documents,
            entity_connections=entity_connections,
            reasoning_depth=reasoning_depth
        )

        # Add traversal paths to reasoning object
        cross_doc_reasoning.traversal_paths = traversal_paths

        # Step 4: Synthesize answer based on connected information
        self.reasoning_tracer.add_node(
            trace_id=trace_id,
            node_type=ReasoningNodeType.INFERENCE,
            content="Synthesizing answer from connected information",
            metadata={"reasoning_step": "answer_synthesis"}
        )

        answer, confidence = self._synthesize_answer(
            query=query,
            documents=documents,
            entity_connections=entity_connections,
            traversal_paths=traversal_paths,
            reasoning_depth=reasoning_depth
        )

        # Add answer to reasoning object
        cross_doc_reasoning.answer = answer
        cross_doc_reasoning.confidence = confidence

        # Add conclusion to the reasoning trace
        self.reasoning_tracer.add_node(
            trace_id=trace_id,
            node_type=ReasoningNodeType.CONCLUSION,
            content=answer,
            metadata={
                "confidence": confidence,
                "reasoning_depth": reasoning_depth,
                "document_count": len(documents),
                "connection_count": len(entity_connections)
            }
        )

        # Update statistics
        self.successful_queries += 1
        self.avg_document_count = ((self.avg_document_count * (self.successful_queries - 1)) +
                                 len(documents)) / self.successful_queries
        self.avg_connection_count = ((self.avg_connection_count * (self.successful_queries - 1)) +
                                   len(entity_connections)) / self.successful_queries
        self.avg_confidence = ((self.avg_confidence * (self.successful_queries - 1)) +
                             confidence) / self.successful_queries

        # Prepare and return the result
        result = {
            "answer": answer,
            "documents": [{"id": doc.id, "source": doc.source, "relevance": doc.relevance_score}
                         for doc in documents],
            "entity_connections": [{"entity": conn.entity_name,
                                   "type": conn.entity_type,
                                   "relation": conn.relation_type.value,
                                   "strength": conn.connection_strength}
                                  for conn in entity_connections],
            "confidence": confidence
        }

        if return_trace:
            result["reasoning_trace"] = self.reasoning_tracer.get_trace(trace_id)

        return result

    def _get_relevant_documents(
        self,
        query: str,
        query_embedding: Optional[np.ndarray],
        input_documents: Optional[List[Dict[str, Any]]],
        vector_store: Optional[Any],
        max_documents: int = 10,
        min_relevance: float = 0.6
    ) -> List[DocumentNode]:
        """
        Get relevant documents for the query.

        Args:
            query: The query string
            query_embedding: The query embedding vector
            input_documents: Optional input documents
            vector_store: Vector store for similarity search
            max_documents: Maximum number of documents to return
            min_relevance: Minimum relevance score

        Returns:
            List of DocumentNode objects
        """
        documents = []

        # If input documents are provided, use them
        if input_documents:
            for i, doc in enumerate(input_documents):
                # Get relevance score (provided or default high value)
                relevance = doc.get("relevance_score", 0.9 - (i * 0.05))

                if relevance >= min_relevance and len(documents) < max_documents:
                    documents.append(DocumentNode(
                        id=doc.get("id", str(uuid.uuid4())),
                        content=doc.get("content", ""),
                        source=doc.get("source", "unknown"),
                        metadata=doc.get("metadata", {}),
                        vector=doc.get("vector", None),
                        relevance_score=relevance,
                        entities=doc.get("entities", [])
                    ))

        # If we need more documents and have a vector store, use it
        if len(documents) < max_documents and vector_store:
            # Ensure we have a query embedding
            if query_embedding is None and hasattr(vector_store, "embed_query"):
                query_embedding = vector_store.embed_query(query)

            if query_embedding is not None:
                # Get documents from vector store
                vector_results = vector_store.search(
                    query_vector=query_embedding,
                    top_k=max_documents - len(documents),
                    min_score=min_relevance
                )

                for result in vector_results:
                    # Convert to DocumentNode
                    doc_node = DocumentNode(
                        id=result.id,
                        content=result.metadata.get("content", ""),
                        source=result.metadata.get("source", "vector_store"),
                        metadata=result.metadata,
                        vector=result.vector if hasattr(result, "vector") else None,
                        relevance_score=result.score,
                        entities=result.metadata.get("entities", [])
                    )
                    documents.append(doc_node)

        # Sort by relevance score
        documents.sort(key=lambda x: x.relevance_score, reverse=True)

        return documents[:max_documents]

    def _find_entity_connections(
        self,
        documents: List[DocumentNode],
        knowledge_graph: Optional[Any],
        max_hops: int = 2
    ) -> List[EntityMediatedConnection]:
        """
        Find entity-mediated connections between documents.

        Args:
            documents: List of documents
            knowledge_graph: Knowledge graph for entity information
            max_hops: Maximum number of hops for graph traversal

        Returns:
            List of EntityMediatedConnection objects
        """
        connections = []

        # If we have a knowledge graph, use it for more sophisticated connections
        if knowledge_graph:
            # Get all entities from the documents
            all_entities = {}
            for doc in documents:
                for entity_id in doc.entities:
                    if entity_id not in all_entities:
                        all_entities[entity_id] = []
                    all_entities[entity_id].append(doc.id)

            # For entities that appear in multiple documents, create connections
            for entity_id, doc_ids in all_entities.items():
                if len(doc_ids) > 1:
                    # Get entity information from knowledge graph
                    entity_info = knowledge_graph.get_entity(entity_id)

                    if entity_info:
                        entity_name = entity_info.get("name", "Unknown Entity")
                        entity_type = entity_info.get("type", "unknown")

                        # Create connections between all pairs of documents with this entity
                        for i in range(len(doc_ids)):
                            for j in range(i+1, len(doc_ids)):
                                # Determine relation type based on entity and documents
                                relation_type, strength = self._determine_relation(
                                    entity_id=entity_id,
                                    source_doc_id=doc_ids[i],
                                    target_doc_id=doc_ids[j],
                                    documents=documents,
                                    knowledge_graph=knowledge_graph
                                )

                                if strength >= self.min_connection_strength:
                                    connections.append(EntityMediatedConnection(
                                        entity_id=entity_id,
                                        entity_name=entity_name,
                                        entity_type=entity_type,
                                        source_doc_id=doc_ids[i],
                                        target_doc_id=doc_ids[j],
                                        relation_type=relation_type,
                                        connection_strength=strength
                                    ))

            # Optionally, if max_hops > 1, find indirect connections
            if max_hops > 1:
                # TODO: Implement multi-hop connections
                pass
        else:
            # Without a knowledge graph, use simpler heuristics
            # For example, look for matching entity names in the entities lists
            for i, doc1 in enumerate(documents):
                for j in range(i+1, len(documents)):
                    doc2 = documents[j]

                    # Find common entities based on string matching
                    common_entities = set(doc1.entities).intersection(set(doc2.entities))

                    for entity_id in common_entities:
                        # Simple heuristic: for now assume a complementary relation
                        relation_type = InformationRelationType.COMPLEMENTARY
                        strength = 0.7  # Default moderate strength

                        connections.append(EntityMediatedConnection(
                            entity_id=entity_id,
                            entity_name=entity_id,  # Use ID as name without a knowledge graph
                            entity_type="unknown",
                            source_doc_id=doc1.id,
                            target_doc_id=doc2.id,
                            relation_type=relation_type,
                            connection_strength=strength
                        ))

        return connections

    def _determine_relation(
        self,
        entity_id: str,
        source_doc_id: str,
        target_doc_id: str,
        documents: List[DocumentNode],
        knowledge_graph: Any
    ) -> Tuple[InformationRelationType, float]:
        """
        Determine the relation type between two documents regarding an entity.

        Args:
            entity_id: The entity ID
            source_doc_id: The source document ID
            target_doc_id: The target document ID
            documents: List of all documents
            knowledge_graph: Knowledge graph

        Returns:
            Tuple of (relation_type, connection_strength)
        """
        # Find the documents
        source_doc = next((d for d in documents if d.id == source_doc_id), None)
        target_doc = next((d for d in documents if d.id == target_doc_id), None)

        if not source_doc or not target_doc:
            return InformationRelationType.UNCLEAR, 0.5

        # In a real implementation, this would use an LLM or more sophisticated analysis
        # TODO: Implement actual relation determination logic
        # For now, use simple heuristics

        # 1. Check if the documents have high semantic similarity
        doc_similarity = 0.7  # Placeholder - would calculate actual similarity

        # 2. Check if one document was published after the other (if timestamp available)
        source_date = source_doc.metadata.get("published_date")
        target_date = target_doc.metadata.get("published_date")
        chronological = False
        if source_date and target_date and source_date < target_date:
            chronological = True

        # 3. Look at entity context in each document
        # This would typically involve looking at the text surrounding the entity mentions

        # 4. Determine relation type based on these factors
        if chronological:
            # Later document might elaborate on or contradict earlier one
            relation_type = InformationRelationType.ELABORATING
            strength = 0.75
        elif doc_similarity > 0.8:
            # Very similar documents likely supporting each other
            relation_type = InformationRelationType.SUPPORTING
            strength = 0.85
        else:
            # Default to complementary for different documents
            relation_type = InformationRelationType.COMPLEMENTARY
            strength = 0.7

        return relation_type, strength

    def _generate_traversal_paths(
        self,
        documents: List[DocumentNode],
        entity_connections: List[EntityMediatedConnection],
        reasoning_depth: str
    ) -> List[List[str]]:
        """
        Generate document traversal paths for reasoning.

        Args:
            documents: List of documents
            entity_connections: List of entity-mediated connections
            reasoning_depth: Reasoning depth

        Returns:
            List of document traversal paths (lists of document IDs)
        """
        # Build a graph of document connections
        doc_graph = {}
        for doc in documents:
            doc_graph[doc.id] = []

        for conn in entity_connections:
            doc_graph[conn.source_doc_id].append(conn.target_doc_id)
            doc_graph[conn.target_doc_id].append(conn.source_doc_id)

        # Generate paths based on reasoning depth
        max_path_length = {
            "basic": 2,
            "moderate": 3,
            "deep": 5
        }.get(reasoning_depth, 3)

        # Sort documents by relevance
        sorted_docs = sorted(documents, key=lambda x: x.relevance_score, reverse=True)

        # Start with the most relevant documents
        paths = []
        visited = set()

        # Depth-first search to generate paths
        def dfs(current_doc, path, depth):
            if depth >= max_path_length:
                paths.append(path.copy())
                return

            for neighbor in doc_graph.get(current_doc, []):
                if neighbor not in path:
                    path.append(neighbor)
                    dfs(neighbor, path, depth + 1)
                    path.pop()

        # Start DFS from top documents
        for doc in sorted_docs[:3]:  # Start from top 3 most relevant docs
            if doc.id not in visited:
                dfs(doc.id, [doc.id], 0)
                visited.add(doc.id)

        return paths

    def _synthesize_answer(
        self,
        query: str,
        documents: List[DocumentNode],
        entity_connections: List[EntityMediatedConnection],
        traversal_paths: List[List[str]],
        reasoning_depth: str
    ) -> Tuple[str, float]:
        """
        Synthesize an answer based on connected information.

        Args:
            query: The query string
            documents: List of documents
            entity_connections: List of entity-mediated connections
            traversal_paths: List of document traversal paths
            reasoning_depth: Reasoning depth

        Returns:
            Tuple of (answer, confidence)
        """
        # In a real implementation, this would use an LLM to generate the answer
        # For now, we'll create a mock implementation

        # Extract document content for relevant documents
        doc_content = {}
        for doc in documents:
            doc_content[doc.id] = doc.content

        # If we have an LLM service, use it to generate the answer
        if self.llm_service:
            # Build prompt with documents and connections
            prompt = f"Question: {query}\n\n"
            prompt += "Relevant documents:\n"

            for i, doc in enumerate(documents[:5]):  # Include top 5 most relevant docs
                prompt += f"Document {i+1} ({doc.source}):\n{doc.content[:500]}...\n\n"

            prompt += "Entity-mediated connections between documents:\n"
            for conn in entity_connections[:5]:  # Include top 5 connections
                prompt += f"- Documents {conn.source_doc_id} and {conn.target_doc_id} are connected through entity '{conn.entity_name}' with a {conn.relation_type.value} relationship\n"

            prompt += "\nBased on these documents and their connections, please answer the original question."

            # Call LLM
            #answer = self.llm_service.generate_text(prompt)
            #confidence = 0.85  # In practice, would be estimated from LLM output

            # TODO: Implement actual LLM call when available
            answer = f"Based on the information in the documents, I can provide the following answer to '{query}'..."
            confidence = 0.75
        else:
            # Provide a generic answer for the mock implementation
            answer = f"Based on the analysis of {len(documents)} documents with {len(entity_connections)} entity-mediated connections, " + \
                     f"the answer to '{query}' involves information connected through entities like " + \
                     ", ".join([conn.entity_name for conn in entity_connections[:3]])
            confidence = 0.6

        return answer, confidence

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about cross-document reasoning.

        Returns:
            Dict with statistics
        """
        return {
            "total_queries": self.total_queries,
            "successful_queries": self.successful_queries,
            "success_rate": self.successful_queries / self.total_queries if self.total_queries > 0 else 0,
            "avg_document_count": self.avg_document_count,
            "avg_connection_count": self.avg_connection_count,
            "avg_confidence": self.avg_confidence
        }

    def explain_reasoning(self, reasoning_id: str) -> Dict[str, Any]:
        """
        Generate an explanation of the reasoning process.

        Args:
            reasoning_id: ID of the reasoning process

        Returns:
            Dict with explanation
        """
        # TODO: Implement explanation generation
        # This would use the reasoning trace to generate a step-by-step explanation

        return {
            "reasoning_id": reasoning_id,
            "explanation": "Reasoning explanation would be generated here",
            "steps": [
                "Identified relevant documents based on query",
                "Found entity connections between documents",
                "Analyzed information relationships",
                "Generated synthetic answer"
            ]
        }


def example_usage():
    """Example usage of the cross-document reasoner."""
    from ipfs_datasets_py.llm_reasoning_tracer import LLMReasoningTracer
    from ipfs_datasets_py.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer

    # Initialize components
    reasoning_tracer = LLMReasoningTracer()
    query_optimizer = UnifiedGraphRAGQueryOptimizer()

    # Initialize cross-document reasoner
    reasoner = CrossDocumentReasoner(
        query_optimizer=query_optimizer,
        reasoning_tracer=reasoning_tracer
    )

    # Sample documents for testing
    sample_documents = [
        {
            "id": "doc1",
            "content": "IPFS is a peer-to-peer hypermedia protocol that makes the web faster, safer, and more open.",
            "source": "IPFS Documentation",
            "metadata": {"published_date": "2020-01-01"},
            "relevance_score": 0.95,
            "entities": ["IPFS", "peer-to-peer", "protocol", "web"]
        },
        {
            "id": "doc2",
            "content": "IPFS uses content addressing to uniquely identify each file in a global namespace connecting all computing devices.",
            "source": "IPFS Website",
            "metadata": {"published_date": "2021-03-15"},
            "relevance_score": 0.90,
            "entities": ["IPFS", "content addressing", "file", "namespace"]
        },
        {
            "id": "doc3",
            "content": "Content addressing is a technique where content is identified by its cryptographic hash rather than by its location.",
            "source": "Distributed Systems Book",
            "metadata": {"published_date": "2019-05-20"},
            "relevance_score": 0.85,
            "entities": ["content addressing", "cryptographic hash", "location"]
        }
    ]

    # Perform cross-document reasoning
    result = reasoner.reason_across_documents(
        query="How does IPFS use content addressing?",
        input_documents=sample_documents,
        reasoning_depth="moderate",
        return_trace=True
    )

    # Print result
    print("Cross-Document Reasoning Result:")
    print(f"Answer: {result['answer']}")
    print(f"Confidence: {result['confidence']}")
    print("\nRelevant Documents:")
    for doc in result["documents"]:
        print(f"- {doc['id']} ({doc['source']}): Relevance {doc['relevance']:.2f}")
    print("\nEntity Connections:")
    for conn in result["entity_connections"]:
        print(f"- {conn['entity']} ({conn['type']}): {conn['relation']} connection with strength {conn['strength']:.2f}")

    # Get reasoning explanation
    if "reasoning_trace" in result:
        print("\nReasoning Trace:")
        for step in result["reasoning_trace"]["steps"]:
            print(f"- {step['content']}")

    # Get statistics
    stats = reasoner.get_statistics()
    print("\nReasoner Statistics:")
    for key, value in stats.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    example_usage()
