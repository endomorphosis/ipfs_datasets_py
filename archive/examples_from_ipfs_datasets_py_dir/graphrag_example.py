"""
GraphRAG Example Module

This module demonstrates how to use the GraphRAG system by integrating the IPLDVectorStore,
IPLDKnowledgeGraph, and GraphRAGQueryEngine components together.

It shows a complete workflow from vector storage, knowledge graph building,
to advanced GraphRAG queries combining vector similarity and graph traversal.
"""

import os
import numpy as np
import json
import uuid
import tempfile
from typing import Dict, List, Any, Optional, Union, Tuple

from ipfs_datasets_py.ipld import (
    IPLDStorage, IPLDVectorStore, SearchResult,
    IPLDKnowledgeGraph, Entity, Relationship
)
from ipfs_datasets_py.logic.integrations.graphrag_integration import (
    GraphRAGFactory, HybridVectorGraphSearch, GraphRAGQueryEngine,
    CrossDocumentReasoner
)
from ipfs_datasets_py.rag.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer

class GraphRAGDemo:
    """
    Demonstrates a complete GraphRAG workflow.

    This class shows how to:
    1. Create and populate an IPLDVectorStore
    2. Build an IPLDKnowledgeGraph with entities and relationships
    3. Connect the components using the GraphRAGQueryEngine
    4. Perform advanced GraphRAG queries
    5. Implement cross-document reasoning
    """

    def __init__(self, dimension: int = 768, data_dir: Optional[str] = None):
        """
        Initialize GraphRAG demonstration.

        Args:
            dimension: Dimension of the vector embeddings
            data_dir: Optional directory for storing data files
        """
        self.dimension = dimension
        self.data_dir = data_dir or tempfile.mkdtemp()
        os.makedirs(self.data_dir, exist_ok=True)

        # Initialize IPLD storage
        self.storage = IPLDStorage()

        # Initialize vector store
        self.vector_store = IPLDVectorStore(
            dimension=dimension,
            metric="cosine",
            storage=self.storage
        )

        # Initialize knowledge graph
        self.kg = IPLDKnowledgeGraph(
            name="demo_graph",
            storage=self.storage,
            vector_store=self.vector_store
        )

        # Initialize query optimizer
        self.query_optimizer = UnifiedGraphRAGQueryOptimizer()

        # Component tracking
        self.vector_stores = {"default": self.vector_store}
        self.documents = []
        self.entities = []
        self.relationships = []

    def add_document(
        self,
        title: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        vector: Optional[np.ndarray] = None
    ) -> Entity:
        """
        Add a document to the system.

        Args:
            title: Document title
            content: Document content
            metadata: Optional document metadata
            vector: Optional document embedding vector

        Returns:
            Entity representing the document
        """
        # Generate vector if not provided
        if vector is None:
            # Generate a random vector for demonstration
            # In a real application, this would come from an embedding model
            vector = np.random.randn(self.dimension).astype(np.float32)
            # Normalize the vector
            vector = vector / np.linalg.norm(vector)

        # Create document properties
        doc_properties = {
            "title": title,
            "content": content
        }

        # Add metadata if provided
        if metadata:
            doc_properties.update(metadata)

        # Add document entity to knowledge graph
        document = self.kg.add_entity(
            entity_type="document",
            name=title,
            properties=doc_properties,
            vector=vector
        )

        # Track the document
        self.documents.append(document)

        return document

    def add_concept(
        self,
        name: str,
        description: str,
        vector: Optional[np.ndarray] = None
    ) -> Entity:
        """
        Add a concept to the knowledge graph.

        Args:
            name: Concept name
            description: Concept description
            vector: Optional concept embedding vector

        Returns:
            Entity representing the concept
        """
        # Generate vector if not provided
        if vector is None:
            # Generate a random vector for demonstration
            vector = np.random.randn(self.dimension).astype(np.float32)
            # Normalize the vector
            vector = vector / np.linalg.norm(vector)

        # Add concept entity to knowledge graph
        concept = self.kg.add_entity(
            entity_type="concept",
            name=name,
            properties={"description": description},
            vector=vector
        )

        # Track the entity
        self.entities.append(concept)

        return concept

    def add_document_concept_relation(
        self,
        document: Entity,
        concept: Entity,
        confidence: float = 1.0
    ) -> Relationship:
        """
        Add a relationship between a document and a concept.

        Args:
            document: Document entity
            concept: Concept entity
            confidence: Relationship confidence score

        Returns:
            Relationship between document and concept
        """
        # Add relationship to knowledge graph
        relationship = self.kg.add_relationship(
            relationship_type="mentions",
            source=document,
            target=concept,
            properties={"confidence": confidence},
            confidence=confidence
        )

        # Track the relationship
        self.relationships.append(relationship)

        return relationship

    def add_concept_concept_relation(
        self,
        source_concept: Entity,
        target_concept: Entity,
        relationship_type: str = "related_to",
        properties: Optional[Dict[str, Any]] = None,
        confidence: float = 1.0
    ) -> Relationship:
        """
        Add a relationship between two concepts.

        Args:
            source_concept: Source concept entity
            target_concept: Target concept entity
            relationship_type: Type of relationship
            properties: Optional relationship properties
            confidence: Relationship confidence score

        Returns:
            Relationship between concepts
        """
        # Add relationship to knowledge graph
        relationship = self.kg.add_relationship(
            relationship_type=relationship_type,
            source=source_concept,
            target=target_concept,
            properties=properties or {},
            confidence=confidence
        )

        # Track the relationship
        self.relationships.append(relationship)

        return relationship

    def create_query_engine(self) -> GraphRAGQueryEngine:
        """
        Create a GraphRAG query engine.

        Returns:
            GraphRAGQueryEngine for querying the system
        """
        # Create hybrid search
        hybrid_search = HybridVectorGraphSearch(
            self.kg,
            vector_weight=0.6,
            graph_weight=0.4,
            max_graph_hops=2
        )

        # Create GraphRAG query engine
        query_engine = GraphRAGFactory.create_query_engine(
            dataset=self.kg,
            vector_stores=self.vector_stores,
            graph_store=self.kg,
            query_optimizer=self.query_optimizer,
            hybrid_search=hybrid_search,
            enable_cross_document_reasoning=True,
            enable_query_rewriting=True,
            enable_budget_management=True
        )

        return query_engine

    def execute_query(
        self,
        query_text: str,
        query_vector: Optional[np.ndarray] = None,
        include_graph_results: bool = True,
        include_cross_document_reasoning: bool = True,
        reasoning_depth: str = "moderate"
    ) -> Dict[str, Any]:
        """
        Execute a GraphRAG query.

        Args:
            query_text: Natural language query
            query_vector: Optional query embedding vector
            include_graph_results: Whether to include graph traversal results
            include_cross_document_reasoning: Whether to include cross-document reasoning
            reasoning_depth: Reasoning depth ('basic', 'moderate', or 'deep')

        Returns:
            Query results
        """
        # Create query engine if not created yet
        query_engine = self.create_query_engine()

        # Generate query vector if not provided
        if query_vector is None:
            # Generate a random vector for demonstration
            # In a real application, this would come from an embedding model
            query_vector = np.random.randn(self.dimension).astype(np.float32)
            # Normalize the vector
            query_vector = query_vector / np.linalg.norm(query_vector)

        # Create query embeddings dictionary
        query_embeddings = {"default": query_vector}

        # Execute query
        results = query_engine.query(
            query_text=query_text,
            query_embeddings=query_embeddings,
            top_k=10,
            include_vector_results=True,
            include_graph_results=include_graph_results,
            include_cross_document_reasoning=include_cross_document_reasoning,
            entity_types=None,  # Use all entity types
            relationship_types=None,  # Use all relationship types
            min_relevance=0.5,
            max_graph_hops=2,
            reasoning_depth=reasoning_depth,
            return_trace=True
        )

        return results

    def visualize_results(self, results: Dict[str, Any], format: str = "text") -> Dict[str, Any]:
        """
        Visualize query results.

        Args:
            results: Query results from execute_query
            format: Visualization format ('text', 'html', 'mermaid')

        Returns:
            Visualization data
        """
        # Create query engine
        query_engine = self.create_query_engine()

        # Generate visualization
        visualization = query_engine.visualize_query_result(results, format=format)

        return visualization

    def export_to_car(self, output_dir: Optional[str] = None) -> Dict[str, str]:
        """
        Export vector store and knowledge graph to CAR files.

        Args:
            output_dir: Optional directory for output files

        Returns:
            Dictionary mapping component names to CAR file paths
        """
        output_dir = output_dir or self.data_dir
        os.makedirs(output_dir, exist_ok=True)

        # Export vector store
        vector_store_path = os.path.join(output_dir, "vector_store.car")
        vector_store_cid = self.vector_store.export_to_car(vector_store_path)

        # Export knowledge graph
        kg_path = os.path.join(output_dir, "knowledge_graph.car")
        kg_cid = self.kg.export_to_car(kg_path)

        return {
            "vector_store": vector_store_path,
            "knowledge_graph": kg_path,
            "vector_store_cid": vector_store_cid,
            "knowledge_graph_cid": kg_cid
        }

    @classmethod
    def from_car_files(
        cls,
        vector_store_path: str,
        knowledge_graph_path: str,
        dimension: int = 768
    ) -> 'GraphRAGDemo':
        """
        Create a GraphRAG demo from CAR files.

        Args:
            vector_store_path: Path to vector store CAR file
            knowledge_graph_path: Path to knowledge graph CAR file
            dimension: Dimension of the vector embeddings

        Returns:
            GraphRAGDemo instance
        """
        # Create a new demo instance
        demo = cls(dimension=dimension)

        # Import vector store
        demo.vector_store = IPLDVectorStore.from_car(vector_store_path, storage=demo.storage)

        # Update vector stores dictionary
        demo.vector_stores = {"default": demo.vector_store}

        # Import knowledge graph
        demo.kg = IPLDKnowledgeGraph.from_car(
            knowledge_graph_path,
            storage=demo.storage,
            vector_store=demo.vector_store
        )

        # Rebuild demo.documents and demo.entities lists
        for entity in demo.kg.entities.values():
            if entity.type == "document":
                demo.documents.append(entity)
            else:
                demo.entities.append(entity)

        # Rebuild demo.relationships list
        demo.relationships = list(demo.kg.relationships.values())

        return demo

    def create_sample_graph(self) -> None:
        """Create a sample knowledge graph for demonstration."""
        # Add documents
        doc1 = self.add_document(
            title="Introduction to IPFS",
            content="""
            IPFS (InterPlanetary File System) is a protocol and peer-to-peer network
            for storing and sharing data in a distributed file system. IPFS uses
            content-addressing to uniquely identify each file in a global namespace
            connecting all computing devices.
            """,
        )

        doc2 = self.add_document(
            title="Understanding Content Addressing",
            content="""
            Content addressing is a technique where content is identified by its
            cryptographic hash rather than its location. This provides immutability,
            deduplication, and verifiability. IPFS uses CIDs (Content Identifiers)
            as a form of content addressing.
            """,
        )

        doc3 = self.add_document(
            title="IPLD Data Structures",
            content="""
            IPLD (InterPlanetary Linked Data) is a data model for distributed data
            structures like the ones used in IPFS. It allows different protocols
            to interoperate by translating between their data structures. IPLD
            uses content addressing and provides a unified way to work with data.
            """,
        )

        # Add concepts
        ipfs = self.add_concept(
            name="IPFS",
            description="InterPlanetary File System, a protocol and network for distributed content addressing"
        )

        content_addressing = self.add_concept(
            name="Content Addressing",
            description="Method of identifying data by its content rather than location"
        )

        cid = self.add_concept(
            name="CID",
            description="Content Identifier, a self-describing content-addressed identifier"
        )

        ipld = self.add_concept(
            name="IPLD",
            description="InterPlanetary Linked Data, a data model for content-addressed data"
        )

        # Add document-concept relationships
        self.add_document_concept_relation(doc1, ipfs, 0.9)
        self.add_document_concept_relation(doc1, content_addressing, 0.7)

        self.add_document_concept_relation(doc2, content_addressing, 0.9)
        self.add_document_concept_relation(doc2, cid, 0.8)

        self.add_document_concept_relation(doc3, ipld, 0.9)
        self.add_document_concept_relation(doc3, content_addressing, 0.6)
        self.add_document_concept_relation(doc3, ipfs, 0.5)

        # Add concept-concept relationships
        self.add_concept_concept_relation(ipfs, content_addressing, "uses", {"importance": "high"}, 0.9)
        self.add_concept_concept_relation(content_addressing, cid, "implements_as", {"in_context": "IPFS"}, 0.8)
        self.add_concept_concept_relation(ipld, ipfs, "used_by", {"as": "data model"}, 0.9)
        self.add_concept_concept_relation(ipld, content_addressing, "uses", {"for": "addressing blocks"}, 0.8)


def run_example():
    """Run a complete GraphRAG example."""
    print("Initializing GraphRAG system...")
    # Create a smaller dimension for the example
    demo = GraphRAGDemo(dimension=128)

    print("Creating sample knowledge graph...")
    demo.create_sample_graph()

    print(f"Created {len(demo.documents)} documents, {len(demo.entities)} concepts, "
          f"and {len(demo.relationships)} relationships")

    # Create a sample query
    query_text = "How does IPFS use content addressing?"

    # Generate a query vector that's similar to both IPFS and content addressing
    # In a real application, this would come from an embedding model
    query_vector = np.zeros(demo.dimension, dtype=np.float32)

    # Execute query
    print(f"\nExecuting query: '{query_text}'")
    results = demo.execute_query(
        query_text=query_text,
        query_vector=query_vector,
        include_graph_results=True,
        include_cross_document_reasoning=True,
        reasoning_depth="moderate"
    )

    # Display results
    print("\nQuery Results:")
    print("--------------")

    if "vector_results" in results:
        print(f"Vector search found {len(results['vector_results'].get('default', []))} results")

    if "hybrid_results" in results:
        print(f"Hybrid search found {len(results['hybrid_results'])} results")

        print("\nTop 3 Hybrid Results:")
        for i, result in enumerate(results["hybrid_results"][:3]):
            entity = result["entity"]
            print(f"  {i+1}. {entity.name} (Type: {entity.type})")
            if "path" in result and result["path"]:
                path_str = " → ".join([p.get("relationship", "related") for p in result["path"]])
                print(f"     Path: {path_str}")

    if "reasoning_result" in results and "answer" in results["reasoning_result"]:
        print("\nReasoning Result:")
        print(results["reasoning_result"]["answer"])

        print("\nReasoning Trace:")
        for step in results["reasoning_result"].get("reasoning_trace", []):
            print(f"- {step}")

    # Generate visualization
    visualization = demo.visualize_results(results, format="text")
    print("\nVisualization:")
    print(visualization.get("visualization", "No visualization available"))

    # Export to CAR files
    print("\nExporting to CAR files...")
    car_files = demo.export_to_car()

    print(f"Vector store exported to: {car_files['vector_store']}")
    print(f"Knowledge graph exported to: {car_files['knowledge_graph']}")

    # Reload from CAR files
    print("\nReloading from CAR files...")
    reloaded_demo = GraphRAGDemo.from_car_files(
        car_files["vector_store"],
        car_files["knowledge_graph"],
        dimension=128
    )

    print(f"Reloaded {len(reloaded_demo.documents)} documents, "
          f"{len(reloaded_demo.entities)} concepts, and "
          f"{len(reloaded_demo.relationships)} relationships")

    # Execute the same query on the reloaded system
    print("\nExecuting query on reloaded system...")
    reloaded_results = reloaded_demo.execute_query(
        query_text=query_text,
        query_vector=query_vector
    )

    if "reasoning_result" in reloaded_results and "answer" in reloaded_results["reasoning_result"]:
        print("\nReloaded Reasoning Result:")
        print(reloaded_results["reasoning_result"]["answer"])

    print("\nGraphRAG example completed successfully!")


if __name__ == "__main__":
    run_example()
