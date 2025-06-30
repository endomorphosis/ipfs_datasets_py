#!/usr/bin/env python3
"""
Example script demonstrating the use of the IPFS Datasets Python library.

This script shows how to:
1. Create and manipulate datasets
2. Store and retrieve datasets using IPLD
3. Create a vector index for similarity search
4. Create a knowledge graph with nodes and relationships
5. Export and import datasets using CAR files
"""

import os
import sys
import numpy as np

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.append(parent_dir)

# Import components from the library
from ipfs_datasets_py import (
    IPLDStorage,
    DatasetSerializer,
    GraphDataset,
    GraphNode,
    VectorAugmentedGraphDataset,
    IPFSKnnIndex,
    GraphRAGQueryOptimizer,
    GraphRAGQueryStats,
    VectorIndexPartitioner,
    KnowledgeGraph,
    KnowledgeGraphExtractor,
    Entity,
    Relationship,
    load_dataset,
    # LLM Integration Components
    LLMInterface,
    MockLLMInterface,
    LLMConfig,
    GraphRAGLLMProcessor,
    ReasoningEnhancer,
    enhance_dataset_with_llm
)

def original_example():
    """The original example from the file."""
    # Test loading a dataset
    dataset = load_dataset.from_auto_download("cifar10")
    print(dir(dataset))
    ## OPTIONAL S3 Caching ##

    #model = T5Model.from_auto_download(
    #    model_name="google-bert/t5_11b_trueteacher_and_anli",
    #    s3cfg={
    #        "bucket": "cloud",
    #        "endpoint": "https://storage.googleapis.com",
    #        "secret_key": "",
    #        "access_key": "",
    #    }
    #)
    #print(dir(model))

def ipld_example():
    """Example showing IPLD-based dataset handling."""
    print("IPFS Datasets Python - IPLD Example")
    print("==================================")

    # Create a temporary directory for our examples
    import tempfile
    temp_dir = tempfile.mkdtemp()
    print(f"Using temporary directory: {temp_dir}")

    try:
        # Initialize storage and serializer
        storage = IPLDStorage(base_dir=os.path.join(temp_dir, "ipld_blocks"))
        serializer = DatasetSerializer(storage=storage)

        # Example 1: Storing structured data with schema validation
        print("\nExample 1: Storing structured data with schema validation")
        print("--------------------------------------------------------")
        dataset = {
            "type": "dataset",
            "schema": {
                "fields": [
                    {"name": "id", "type": "integer"},
                    {"name": "name", "type": "string"},
                    {"name": "value", "type": "float"}
                ]
            },
            "rows": [
                {"id": 1, "name": "Item 1", "value": 10.5},
                {"id": 2, "name": "Item 2", "value": 20.3},
                {"id": 3, "name": "Item 3", "value": 15.7}
            ]
        }

        # Store with schema validation
        cid = storage.store_with_schema(dataset, "dataset")
        print(f"Stored dataset with CID: {cid}")

        # Retrieve with schema validation
        retrieved_dataset = storage.get_with_schema(cid, "dataset")
        print(f"Retrieved dataset has {len(retrieved_dataset['rows'])} rows")

        # Example 2: Vector similarity search
        print("\nExample 2: Vector similarity search")
        print("--------------------------------")
        # Create some vectors
        vectors = np.array([
            [1.0, 0.0, 0.0],  # Item pointing in x direction
            [0.0, 1.0, 0.0],  # Item pointing in y direction
            [0.0, 0.0, 1.0],  # Item pointing in z direction
            [0.7, 0.7, 0.0],  # Item in xy plane
            [0.0, 0.7, 0.7],  # Item in yz plane
            [0.7, 0.0, 0.7]   # Item in xz plane
        ])

        # Create metadata for each vector
        metadata = [
            {"id": "item1", "description": "X axis"},
            {"id": "item2", "description": "Y axis"},
            {"id": "item3", "description": "Z axis"},
            {"id": "item4", "description": "XY plane"},
            {"id": "item5", "description": "YZ plane"},
            {"id": "item6", "description": "XZ plane"}
        ]

        # Create and populate a KNN index
        index = IPFSKnnIndex(dimension=3, metric="cosine")
        index.add_vectors(vectors, metadata)

        # Search for vectors similar to [0.9, 0.1, 0.0]
        query = np.array([0.9, 0.1, 0.0])
        results = index.search(query, k=3)

        print("Query results for vector [0.9, 0.1, 0.0]:")
        for i, (idx, similarity, meta) in enumerate(results):
            print(f"  {i+1}. {meta['id']} - {meta['description']} (similarity: {similarity:.3f})")

        # Save the index to IPFS
        index_cid = index.save_to_ipfs()
        print(f"Saved index to IPFS with CID: {index_cid}")

        # Export the index to a CAR file
        car_path = os.path.join(temp_dir, "vector_index.car")
        root_cid = index.export_to_car(car_path)
        print(f"Exported index to CAR file: {car_path}")
        print(f"Root CID: {root_cid}")

        # Example 3: Knowledge Graph
        print("\nExample 3: Knowledge Graph")
        print("-----------------------")
        # Create a graph dataset
        graph = GraphDataset(name="example_graph")

        # Create some nodes
        person1 = GraphNode(id="person1", type="person", data={"name": "Alice", "age": 30})
        person2 = GraphNode(id="person2", type="person", data={"name": "Bob", "age": 28})
        product1 = GraphNode(id="product1", type="product", data={"name": "Laptop", "price": 1200})
        product2 = GraphNode(id="product2", type="product", data={"name": "Phone", "price": 800})

        # Add nodes to the graph
        graph.add_node(person1)
        graph.add_node(person2)
        graph.add_node(product1)
        graph.add_node(product2)

        # Add relationships
        graph.add_edge("person1", "purchased", "product1")
        graph.add_edge("person1", "viewed", "product2")
        graph.add_edge("person2", "purchased", "product2")
        graph.add_edge("person2", "viewed", "product1")
        graph.add_edge("person1", "knows", "person2")

        # Print graph stats
        print(f"Graph has {len(graph.nodes)} nodes")
        print(f"Node types: {', '.join(graph.node_types)}")
        print(f"Edge types: {', '.join(graph.edge_types)}")

        # Serialize the graph
        graph_cid = serializer.serialize_graph_dataset(graph)
        print(f"Serialized graph to IPLD with CID: {graph_cid}")

        # Deserialize the graph
        retrieved_graph = serializer.deserialize_graph_dataset(graph_cid)
        print(f"Retrieved graph has {len(retrieved_graph.nodes)} nodes")

        # Find all products purchased by person1
        person1_node = retrieved_graph.get_node("person1")
        purchased_products = person1_node.edges.get("purchased", [])
        print(f"Products purchased by {person1_node.data['name']}:")
        for product in purchased_products:
            print(f"  - {product.data['name']} (${product.data['price']})")

    finally:
        # Clean up
        import shutil
        shutil.rmtree(temp_dir)
        print("\nCleaned up temporary directory")


def graph_rag_example():
    """Example showing GraphRAG capabilities with vector-augmented graph search."""
    print("IPFS Datasets Python - GraphRAG Example")
    print("======================================")

    # Create a temporary directory for our examples
    import tempfile
    temp_dir = tempfile.mkdtemp()
    print(f"Using temporary directory: {temp_dir}")

    try:
        # Initialize storage
        storage = IPLDStorage(base_dir=os.path.join(temp_dir, "ipld_blocks"))

        # Create a vector-augmented graph dataset
        graph = VectorAugmentedGraphDataset(
            name="knowledge_graph",
            vector_dimension=3,  # Using small dimension for example
            vector_metric="cosine",
            storage=storage
        )

        # Step 1: Create nodes with embeddings for a document graph
        print("\nStep 1: Creating document graph with embeddings")
        print("----------------------------------------------")

        # Document nodes with embeddings representing their semantic content
        document1 = GraphNode(
            id="doc1",
            type="document",
            data={
                "title": "Introduction to Machine Learning",
                "content": "Machine learning is a field of AI that enables systems to learn from data.",
                "author": "Alice Smith"
            }
        )
        document2 = GraphNode(
            id="doc2",
            type="document",
            data={
                "title": "Deep Learning Fundamentals",
                "content": "Deep learning uses neural networks with multiple layers.",
                "author": "Bob Johnson"
            }
        )
        document3 = GraphNode(
            id="doc3",
            type="document",
            data={
                "title": "Python Programming",
                "content": "Python is a versatile programming language used in many fields.",
                "author": "Charlie Davis"
            }
        )
        document4 = GraphNode(
            id="doc4",
            type="document",
            data={
                "title": "Machine Learning with Python",
                "content": "Python is widely used for implementing machine learning algorithms.",
                "author": "Alice Smith"
            }
        )
        document5 = GraphNode(
            id="doc5",
            type="document",
            data={
                "title": "Neural Network Architectures",
                "content": "Various neural network architectures are used in deep learning applications.",
                "author": "Bob Johnson"
            }
        )

        # Create simple embeddings (in a real application, these would come from a language model)
        # For simplicity, we're using a 3D space where:
        # - First dimension represents "machine learning" content (1.0 = highly relevant)
        # - Second dimension represents "programming" content (1.0 = highly relevant)
        # - Third dimension represents "neural networks" content (1.0 = highly relevant)

        embedding1 = np.array([0.9, 0.2, 0.3])  # ML focused
        embedding2 = np.array([0.5, 0.1, 0.9])  # Deep learning focused
        embedding3 = np.array([0.1, 0.9, 0.1])  # Programming focused
        embedding4 = np.array([0.7, 0.7, 0.2])  # ML + Programming
        embedding5 = np.array([0.3, 0.2, 0.9])  # Neural network focused

        # Add nodes with embeddings
        graph.add_node_with_embedding(document1, embedding1, {"source": "documentation"})
        graph.add_node_with_embedding(document2, embedding2, {"source": "documentation"})
        graph.add_node_with_embedding(document3, embedding3, {"source": "tutorial"})
        graph.add_node_with_embedding(document4, embedding4, {"source": "tutorial"})
        graph.add_node_with_embedding(document5, embedding5, {"source": "research"})

        # Add author nodes
        author1 = GraphNode(
            id="author1",
            type="author",
            data={"name": "Alice Smith", "expertise": "Machine Learning"}
        )
        author2 = GraphNode(
            id="author2",
            type="author",
            data={"name": "Bob Johnson", "expertise": "Deep Learning"}
        )
        author3 = GraphNode(
            id="author3",
            type="author",
            data={"name": "Charlie Davis", "expertise": "Programming"}
        )

        graph.add_node(author1)
        graph.add_node(author2)
        graph.add_node(author3)

        # Add concept nodes
        concept1 = GraphNode(
            id="concept1",
            type="concept",
            data={"name": "Machine Learning", "definition": "Field of AI that uses data to learn"}
        )
        concept2 = GraphNode(
            id="concept2",
            type="concept",
            data={"name": "Deep Learning", "definition": "Subset of ML using neural networks"}
        )
        concept3 = GraphNode(
            id="concept3",
            type="concept",
            data={"name": "Python", "definition": "Programming language"}
        )

        graph.add_node(concept1)
        graph.add_node(concept2)
        graph.add_node(concept3)

        # Step 2: Add relationships (edges with properties)
        print("\nStep 2: Adding relationships with properties")
        print("-----------------------------------------")

        # Document authorship
        graph.add_edge("doc1", "authored_by", "author1", {"year": 2022})
        graph.add_edge("doc2", "authored_by", "author2", {"year": 2021})
        graph.add_edge("doc3", "authored_by", "author3", {"year": 2023})
        graph.add_edge("doc4", "authored_by", "author1", {"year": 2023})
        graph.add_edge("doc5", "authored_by", "author2", {"year": 2022})

        # Document references
        graph.add_edge("doc4", "references", "doc1", {"relevance": 0.9})
        graph.add_edge("doc5", "references", "doc2", {"relevance": 0.8})
        graph.add_edge("doc4", "references", "doc3", {"relevance": 0.6})

        # Document topics
        graph.add_edge("doc1", "about", "concept1", {"strength": 0.9})
        graph.add_edge("doc2", "about", "concept2", {"strength": 0.9})
        graph.add_edge("doc3", "about", "concept3", {"strength": 0.9})
        graph.add_edge("doc4", "about", "concept1", {"strength": 0.7})
        graph.add_edge("doc4", "about", "concept3", {"strength": 0.6})
        graph.add_edge("doc5", "about", "concept2", {"strength": 0.8})

        # Concept relationships
        graph.add_edge("concept2", "sub_field_of", "concept1", {"certainty": 0.95})
        graph.add_edge("concept3", "used_in", "concept1", {"certainty": 0.8})
        graph.add_edge("concept3", "used_in", "concept2", {"certainty": 0.9})

        # Author expertise
        graph.add_edge("author1", "expert_in", "concept1", {"level": "high"})
        graph.add_edge("author2", "expert_in", "concept2", {"level": "high"})
        graph.add_edge("author3", "expert_in", "concept3", {"level": "high"})
        graph.add_edge("author1", "familiar_with", "concept3", {"level": "medium"})
        graph.add_edge("author2", "familiar_with", "concept1", {"level": "medium"})

        # Print graph stats
        print(f"Graph has {len(graph.nodes)} nodes of {len(graph.node_types)} types")
        print(f"Node types: {', '.join(graph.node_types)}")
        print(f"Graph has {sum(len(edges) for edges in graph._edges_by_type.values())} edges of {len(graph.edge_types)} types")
        print(f"Edge types: {', '.join(graph.edge_types)}")

        # Step 3: Vector similarity search
        print("\nStep 3: Vector similarity search")
        print("-----------------------------")

        # Query for documents related to machine learning
        ml_query = np.array([0.9, 0.3, 0.2])  # ML with some programming
        results = graph.vector_search(ml_query, k=3)

        print("Documents related to machine learning:")
        for i, (node, similarity) in enumerate(results):
            print(f"  {i+1}. {node.data['title']} (similarity: {similarity:.3f})")

        # Step 4: Basic graph traversal
        print("\nStep 4: Basic graph traversal")
        print("---------------------------")

        # Find all documents by author1
        node = graph.get_node("author1")
        print(f"Documents by {node.data['name']}:")

        # Get documents through traversal
        authored_docs = graph.traverse(
            start_node_id="author1",
            edge_type="authored_by",
            direction="incoming",  # Follow authored_by edges backwards
            max_depth=1
        )

        for doc in authored_docs:
            print(f"  - {doc.data['title']}")

        # Step 5: GraphRAG semantic + structural search
        print("\nStep 5: GraphRAG (combined semantic + structural search)")
        print("----------------------------------------------------")

        # Query for content related to machine learning and python
        ml_python_query = np.array([0.7, 0.7, 0.2])  # ML + Programming
        results = graph.graph_rag_search(
            query_vector=ml_python_query,
            max_vector_results=2,
            max_traversal_depth=2
        )

        print("Documents related to both machine learning and python with context:")
        for i, (node, similarity, context) in enumerate(results):
            print(f"  {i+1}. {node.data['title']} (similarity: {similarity:.3f})")
            print(f"     Context: {len(context)-1} related documents/concepts")
            for ctx_node in context[1:3]:  # Show first two context nodes
                print(f"     - {ctx_node.type}: {ctx_node.data.get('title', ctx_node.data.get('name', 'unknown'))}")
            if len(context) > 3:
                print(f"     - ...and {len(context)-3} more")

        # Step 6: Advanced GraphRAG with weighted paths
        print("\nStep 6: Advanced GraphRAG with weighted paths")
        print("-----------------------------------------")

        # Define relation weights
        relation_weights = {
            "about": 1.0,        # Direct topic relationship
            "references": 0.8,   # Referenced documents
            "authored_by": 0.5,  # Same author
            "used_in": 0.7       # Related concepts
        }

        # Perform weighted path search
        weighted_results = graph.search_with_weighted_paths(
            query_vector=ml_python_query,
            max_initial_results=2,
            max_path_length=2,
            path_weight_strategy="decay",
            relation_weights=relation_weights
        )

        print("Weighted paths between relevant documents:")
        for i, result in enumerate(weighted_results[:3]):  # Show top 3 paths
            start = result["start_node"].data['title']
            end = result["end_node"].data['title']
            weight = result["weight"]
            path_len = len(result["path"])

            print(f"  {i+1}. Path: {start} → {end} (weight: {weight:.3f}, length: {path_len})")
            print(f"     Semantic relevance: {result['semantic_weight']:.3f}")
            print(f"     Relation strength: {result['relation_weight']:.3f}")

            # Show the path
            path_str = []
            for j, (node, edge_type, props) in enumerate(result["path"]):
                node_name = node.data.get('title', node.data.get('name', node.id))
                if j < len(result["path"]) - 1:
                    path_str.append(f"{node_name} -[{edge_type}]→")
                else:
                    path_str.append(node_name)

            print(f"     Path: {' '.join(path_str)}")

        # Step 7: Save to IPFS and export to CAR
        print("\nStep 7: Save to IPFS and export to CAR")
        print("-----------------------------------")

        # Save to IPFS
        cid = graph.save_to_ipfs()
        print(f"Saved vector-augmented graph to IPFS with CID: {cid}")

        # Export to CAR file
        car_path = os.path.join(temp_dir, "vector_graph.car")
        root_cid = graph.export_to_car(car_path)
        print(f"Exported to CAR file: {car_path}")
        print(f"Root CID: {root_cid}")

        # Load from IPFS to verify
        loaded_graph = VectorAugmentedGraphDataset.load_from_ipfs(cid, storage=storage)
        print(f"Successfully loaded graph with {len(loaded_graph.nodes)} nodes and {len(loaded_graph.vector_index._metadata)} vectors")

    finally:
        # Clean up
        import shutil
        shutil.rmtree(temp_dir)
        print("\nCleaned up temporary directory")


def optimized_graphrag_example():
    """Example showing optimized GraphRAG capabilities with knowledge graph integration."""
    print("IPFS Datasets Python - Optimized GraphRAG with Knowledge Graph Example")
    print("==================================================================")

    # Create a temporary directory for our examples
    import tempfile
    temp_dir = tempfile.mkdtemp()
    print(f"Using temporary directory: {temp_dir}")

    try:
        # Initialize storage
        storage = IPLDStorage(base_dir=os.path.join(temp_dir, "ipld_blocks"))

        # Step 1: Create a knowledge graph using the extraction module
        print("\nStep 1: Creating knowledge graph using extraction module")
        print("--------------------------------------------------")

        # Sample text with entity and relationship information
        sample_text = """
        John Smith is the CEO of Acme Corporation. He founded the company in 2010 with Jane Doe,
        who is now the CTO. Acme Corporation is headquartered in New York City and has offices
        in San Francisco and London. The company specializes in artificial intelligence and
        machine learning technologies. In 2022, Acme Corporation released its flagship product,
        AI Assistant Pro, which has been adopted by several Fortune 500 companies including
        Tech Innovations Inc and Global Solutions LLC.

        Jane Doe previously worked at Tech University as a Professor of Computer Science.
        She is married to Michael Johnson, who is the founder of Global Solutions LLC.
        """

        # Create an extractor
        extractor = KnowledgeGraphExtractor()

        # Extract knowledge graph
        kg = extractor.extract_knowledge_graph(sample_text)

        # Print knowledge graph statistics
        print(f"Extracted {len(kg.entities)} entities of {len(kg.entity_types)} types")
        print(f"Entity types: {', '.join(kg.entity_types)}")
        print(f"Extracted {len(kg.relationships)} relationships of {len(kg.relationship_types)} types")
        print(f"Relationship types: {', '.join(kg.relationship_types)}")

        # Print some entities and relationships
        print("\nSample entities:")
        for i, entity in enumerate(list(kg.entities.values())[:3]):
            print(f"  {i+1}. {entity.name} ({entity.entity_type})")

        print("\nSample relationships:")
        for i, rel in enumerate(list(kg.relationships.values())[:3]):
            print(f"  {i+1}. {rel.source_entity.name} --[{rel.relation_type}]--> {rel.target_entity.name}")

        # Step 2: Create a vector-augmented graph dataset
        print("\nStep 2: Creating vector-augmented graph dataset with knowledge graph")
        print("--------------------------------------------------------------")

        # Create mock embeddings for our entities
        entity_embeddings = {}
        for entity_id, entity in kg.entities.items():
            if entity.entity_type == "person":
                # Person entities get embeddings with high values in the first dimension
                embedding = np.array([0.8, 0.3, 0.2])
            elif entity.entity_type == "organization":
                # Organization entities get embeddings with high values in the second dimension
                embedding = np.array([0.3, 0.9, 0.2])
            elif entity.entity_type == "location":
                # Location entities get embeddings with high values in the third dimension
                embedding = np.array([0.2, 0.3, 0.9])
            else:
                # Other entities get balanced embeddings
                embedding = np.array([0.4, 0.4, 0.4])

            # Add small random variations
            embedding += np.random.normal(0, 0.1, 3)

            # Normalize
            embedding = embedding / np.linalg.norm(embedding)

            entity_embeddings[entity_id] = embedding

        # Create a vector-augmented graph dataset
        graph = VectorAugmentedGraphDataset(
            name="knowledge_graph",
            vector_dimension=3,
            vector_metric="cosine",
            storage=storage
        )

        # Create a mock embedding model
        class MockEmbeddingModel:
            def encode(self, texts):
                # This is a mock that returns random embeddings
                # In a real scenario, you'd use a proper embedding model
                return np.random.normal(0, 1, (len(texts), 3))

        mock_model = MockEmbeddingModel()

        # Import the knowledge graph
        added_nodes = graph.import_knowledge_graph(kg, embedding_model=mock_model)
        print(f"Imported {len(added_nodes)} entities from knowledge graph")
        print(f"Graph has {len(graph.nodes)} nodes and {len(graph.edge_types)} edge types")

        # Step 3: Enable query optimization
        print("\nStep 3: Enabling query optimization")
        print("-------------------------------")

        # Enable query optimization
        graph.enable_query_optimization(
            vector_weight=0.7,
            graph_weight=0.3,
            cache_enabled=True
        )

        # Enable vector partitioning
        graph.enable_vector_partitioning(num_partitions=2)

        print("Query optimization enabled with:")
        print("  - Vector weight: 0.7")
        print("  - Graph weight: 0.3")
        print("  - Query result caching: Enabled")
        print("  - Vector partitioning: 2 partitions")

        # Step 4: Perform GraphRAG queries
        print("\nStep 4: Performing GraphRAG queries")
        print("-------------------------------")

        # Query for person entities
        person_query = np.array([0.8, 0.3, 0.2])
        person_results = graph.graph_rag_search(
            query_vector=person_query,
            max_vector_results=2,
            max_traversal_depth=2,
            use_optimizer=True
        )

        print("Person query results:")
        for i, (node, similarity, context) in enumerate(person_results):
            print(f"  {i+1}. {node.data.get('name', 'Unknown')} (similarity: {similarity:.3f})")
            print(f"     Related nodes: {len(context)-1}")
            for ctx in context[1:3]:
                print(f"      - {ctx.type}: {ctx.data.get('name', 'Unknown')}")

        # Query for organization entities
        org_query = np.array([0.3, 0.9, 0.2])
        org_results = graph.graph_rag_search(
            query_vector=org_query,
            max_vector_results=2,
            max_traversal_depth=2,
            use_optimizer=True
        )

        print("\nOrganization query results:")
        for i, (node, similarity, context) in enumerate(org_results):
            print(f"  {i+1}. {node.data.get('name', 'Unknown')} (similarity: {similarity:.3f})")
            print(f"     Related nodes: {len(context)-1}")
            for ctx in context[1:3]:
                print(f"      - {ctx.type}: {ctx.data.get('name', 'Unknown')}")

        # Step 5: Use advanced query features
        print("\nStep 5: Using advanced query features")
        print("-------------------------------")

        # Use advanced graph RAG search
        weighted_results = graph.advanced_graph_rag_search(
            query_vector=person_query,
            max_vector_results=3,
            max_traversal_depth=2,
            semantic_weight=0.6,
            structural_weight=0.4,
            path_decay_factor=0.8
        )

        print("Advanced GraphRAG search results:")
        for i, result in enumerate(weighted_results[:2]):
            node = result["node"]
            score = result["score"]
            print(f"  {i+1}. {node.data.get('name', 'Unknown')} (score: {score:.3f})")
            print(f"     Semantic score: {result['semantic_score']:.3f}")
            print(f"     Structural score: {result['structural_score']:.3f}")

            for path in result["paths"][:1]:
                end_node = path["end_node"]
                print(f"     Path to: {end_node.data.get('name', 'Unknown')}")
                print(f"     Path score: {path['structural_score']:.3f}")

        # Step 6: Save to IPFS and export to CAR
        print("\nStep 6: Save to IPFS and export to CAR")
        print("-----------------------------------")

        # Save to IPFS
        cid = graph.save_to_ipfs()
        print(f"Saved vector-augmented graph to IPFS with CID: {cid}")

        # Export to CAR file
        car_path = os.path.join(temp_dir, "kg_vector_graph.car")
        root_cid = graph.export_to_car(car_path)
        print(f"Exported to CAR file: {car_path}")
        print(f"Root CID: {root_cid}")

        # Load from IPFS to verify
        loaded_graph = VectorAugmentedGraphDataset.load_from_ipfs(cid, storage=storage)
        print(f"Successfully loaded graph with {len(loaded_graph.nodes)} nodes and {len(loaded_graph.vector_index._metadata)} vectors")

    finally:
        # Clean up
        import shutil
        shutil.rmtree(temp_dir)
        print("\nCleaned up temporary directory")


def llm_graphrag_example():
    """Example showcasing LLM integration with GraphRAG for enhanced reasoning."""
    print("IPFS Datasets Python - LLM-Enhanced GraphRAG Example")
    print("==================================================")

    # Create a temporary directory for our examples
    import tempfile
    temp_dir = tempfile.mkdtemp()
    print(f"Using temporary directory: {temp_dir}")

    try:
        # Initialize storage
        storage = IPLDStorage(base_dir=os.path.join(temp_dir, "ipld_blocks"))

        # Initialize LLM components
        llm = MockLLMInterface(LLMConfig(
            model_name="mock-graphrag-llm",
            temperature=0.7,
            max_tokens=1024,
            embedding_dimensions=3  # Match our example's dimension
        ))

        processor = GraphRAGLLMProcessor(llm)

        print("\nStep 1: LLM components initialized")
        print("--------------------------------")
        print(f"Using LLM model: {llm.config.model_name}")
        print(f"LLM temperature: {llm.config.temperature}")
        print(f"LLM max tokens: {llm.config.max_tokens}")
        print(f"Embedding dimensions: {llm.config.embedding_dimensions}")

        # Step 2: Create a simple example knowledge graph
        print("\nStep 2: Creating example knowledge graph")
        print("-------------------------------------")

        # Create a vector-augmented graph dataset
        graph = VectorAugmentedGraphDataset(
            name="example_graph",
            vector_dimension=3,
            vector_metric="cosine",
            storage=storage
        )

        # Create document nodes
        doc1 = GraphNode(
            id="doc1",
            type="document",
            data={
                "title": "Climate Change Effects on Marine Ecosystems",
                "content": "This document discusses how rising ocean temperatures are affecting coral reefs."
            }
        )

        doc2 = GraphNode(
            id="doc2",
            type="document",
            data={
                "title": "Conservation Efforts for Ocean Life",
                "content": "This document outlines conservation strategies to protect marine biodiversity."
            }
        )

        doc3 = GraphNode(
            id="doc3",
            type="document",
            data={
                "title": "Economic Impact of Climate Change",
                "content": "This document analyzes the cost of climate change on global economies."
            }
        )

        # Create concept nodes
        concept1 = GraphNode(
            id="concept1",
            type="concept",
            data={
                "name": "Climate Change",
                "definition": "Long-term changes in temperature and weather patterns."
            }
        )

        concept2 = GraphNode(
            id="concept2",
            type="concept",
            data={
                "name": "Marine Conservation",
                "definition": "The protection and preservation of marine ecosystems."
            }
        )

        concept3 = GraphNode(
            id="concept3",
            type="concept",
            data={
                "name": "Economics",
                "definition": "The study of production, consumption, and wealth transfer."
            }
        )

        # Add nodes with embeddings (simplified for example)
        # Use 3D embeddings:
        # - First dimension: climate relevance
        # - Second dimension: conservation relevance
        # - Third dimension: economic relevance

        graph.add_node_with_embedding(doc1, np.array([0.9, 0.6, 0.2]))
        graph.add_node_with_embedding(doc2, np.array([0.5, 0.9, 0.3]))
        graph.add_node_with_embedding(doc3, np.array([0.7, 0.2, 0.9]))

        graph.add_node_with_embedding(concept1, np.array([0.9, 0.4, 0.3]))
        graph.add_node_with_embedding(concept2, np.array([0.4, 0.9, 0.2]))
        graph.add_node_with_embedding(concept3, np.array([0.3, 0.2, 0.9]))

        # Add relationships
        graph.add_edge("doc1", "about", "concept1", {"relevance": 0.9})
        graph.add_edge("doc1", "mentions", "concept2", {"relevance": 0.6})

        graph.add_edge("doc2", "about", "concept2", {"relevance": 0.9})
        graph.add_edge("doc2", "mentions", "concept1", {"relevance": 0.5})

        graph.add_edge("doc3", "about", "concept3", {"relevance": 0.9})
        graph.add_edge("doc3", "mentions", "concept1", {"relevance": 0.7})

        graph.add_edge("concept1", "related_to", "concept2", {"strength": 0.6})
        graph.add_edge("concept1", "related_to", "concept3", {"strength": 0.7})

        print(f"Created graph with {len(graph.nodes)} nodes and {len(graph.edge_types)} edge types")
        print(f"Node types: {', '.join(graph.node_types)}")
        print(f"Edge types: {', '.join(graph.edge_types)}")

        # Step 3: Enhance the graph with LLM capabilities
        print("\nStep 3: Enhancing graph with LLM capabilities")
        print("------------------------------------------")

        # Enhance the graph with LLM capabilities
        enhanced_graph = enhance_dataset_with_llm(graph)

        print("Graph enhanced with LLM capabilities")
        print("Original cross_document_reasoning method has been patched with LLM integration")

        # Step 4: Perform cross-document reasoning with LLM enhancement
        print("\nStep 4: Performing cross-document reasoning with LLM")
        print("------------------------------------------------")

        # Query using the enhanced reasoning
        basic_query = "How does climate change affect marine conservation efforts?"

        # Run basic reasoning
        basic_result = enhanced_graph.cross_document_reasoning(
            query=basic_query,
            document_node_types=["document"],
            max_hops=2,
            reasoning_depth="basic"
        )

        print(f"Basic reasoning query: '{basic_query}'")
        print(f"Result confidence: {basic_result['confidence']:.2f}")
        print(f"Documents used: {len(basic_result['documents'])}")
        print("Answer:")
        print(basic_result["answer"])

        # Step 5: Deep reasoning with LLM enhancement
        print("\nStep 5: Performing deep reasoning with LLM")
        print("---------------------------------------")

        # Query using the enhanced reasoning with deep reasoning
        complex_query = "What are the economic implications of marine conservation in the context of climate change?"

        # Run deep reasoning
        deep_result = enhanced_graph.cross_document_reasoning(
            query=complex_query,
            document_node_types=["document"],
            max_hops=2,
            reasoning_depth="deep"
        )

        print(f"Deep reasoning query: '{complex_query}'")
        print(f"Result confidence: {deep_result['confidence']:.2f}")
        print(f"Documents used: {len(deep_result['documents'])}")
        print("Answer:")
        print(deep_result["answer"])

        # Step 6: Compare reasoning quality with and without LLM enhancement
        print("\nStep 6: Comparing reasoning with and without LLM enhancement")
        print("-------------------------------------------------------")

        # Create a copy of the graph without LLM enhancement
        graph_without_llm = VectorAugmentedGraphDataset(
            name="example_graph_without_llm",
            vector_dimension=3,
            vector_metric="cosine",
            storage=storage
        )

        # Copy all nodes and edges from the original graph
        for node_id, node in graph.nodes.items():
            # Copy the node
            node_copy = GraphNode(
                id=node.id,
                type=node.type,
                data=node.data.copy()
            )

            # Get the node's embedding
            node_idx = graph._node_to_vector_idx.get(node.id)
            if node_idx is not None:
                if graph.vector_index._faiss_available:
                    vector = graph.vector_index._index.reconstruct(node_idx)
                else:
                    vector = np.vstack(graph.vector_index._vectors)[node_idx]

                # Add the node with its embedding
                graph_without_llm.add_node_with_embedding(node_copy, vector)
            else:
                # Add the node without an embedding
                graph_without_llm.add_node(node_copy)

        # Copy edges
        for source_id, edges_by_type in graph._edges_by_type.items():
            for edge_type, edges in edges_by_type.items():
                for edge in edges:
                    target_id = edge["target"].id
                    properties = edge.get("properties", {})
                    graph_without_llm.add_edge(source_id, edge_type, target_id, properties)

        print("Created a copy of the graph without LLM enhancement")

        # Run the same query on both graphs
        comparison_query = "What is the relationship between climate change, marine conservation, and economics?"

        # Run with LLM enhancement
        llm_result = enhanced_graph.cross_document_reasoning(
            query=comparison_query,
            document_node_types=["document"],
            max_hops=2,
            reasoning_depth="moderate"
        )

        print(f"Query: '{comparison_query}'")
        print("\nWith LLM enhancement:")
        print(f"Confidence: {llm_result['confidence']:.2f}")
        print(f"Answer: {llm_result['answer']}")

        # For demonstration purposes, run a simplified version to represent non-LLM behavior
        # Note: In a real scenario, this would use the original implementation
        mock_result = {
            "answer": "There appears to be a relationship between climate change, marine conservation, and economics based on document connections.",
            "confidence": 0.65,
            "documents": basic_result["documents"][:2],
            "reasoning_trace": [
                {"step": "Retrieved documents", "description": "Found documents related to the query"},
                {"step": "Found connections", "description": "Identified connections between documents"},
                {"step": "Generated answer", "description": "Simple synthesis of information"}
            ]
        }

        print("\nWithout LLM enhancement (simulated):")
        print(f"Confidence: {mock_result['confidence']:.2f}")
        print(f"Answer: {mock_result['answer']}")

        print("\nComparison:")
        print(f"Confidence improvement: {(llm_result['confidence'] - mock_result['confidence']) * 100:.1f}%")
        print(f"Answer complexity: LLM enhanced provides more nuanced synthesis across documents")

def advanced_graphrag_example():
    """Example showcasing the advanced GraphRAG methods for knowledge graphs and semantic search."""
    print("IPFS Datasets Python - Advanced GraphRAG Methods Example")
    print("=====================================================")

    # Create a temporary directory for our examples
    import tempfile
    temp_dir = tempfile.mkdtemp()
    print(f"Using temporary directory: {temp_dir}")

    try:
        # Initialize storage
        storage = IPLDStorage(base_dir=os.path.join(temp_dir, "ipld_blocks"))

        # Create a vector-augmented graph dataset
        graph = VectorAugmentedGraphDataset(
            name="research_knowledge_graph",
            vector_dimension=3,  # Using small dimension for example
            vector_metric="cosine",
            storage=storage
        )

        # Step 1: Create nodes with embeddings for a research paper graph
        print("\nStep 1: Creating research paper graph with embeddings")
        print("--------------------------------------------------")

        # Create research paper nodes
        ai_paper = GraphNode(
            id="paper1",
            type="paper",
            data={
                "title": "Advances in Artificial Intelligence",
                "year": 2020,
                "citation_count": 150,
                "keywords": ["AI", "machine learning", "neural networks"]
            }
        )

        ml_paper = GraphNode(
            id="paper2",
            type="paper",
            data={
                "title": "Machine Learning Applications in Healthcare",
                "year": 2021,
                "citation_count": 75,
                "keywords": ["machine learning", "healthcare", "prediction models"]
            }
        )

        nlp_paper = GraphNode(
            id="paper3",
            type="paper",
            data={
                "title": "Natural Language Processing with Transformers",
                "year": 2022,
                "citation_count": 90,
                "keywords": ["NLP", "transformers", "BERT"]
            }
        )

        cv_paper = GraphNode(
            id="paper4",
            type="paper",
            data={
                "title": "Computer Vision Techniques for Autonomous Vehicles",
                "year": 2021,
                "citation_count": 120,
                "keywords": ["computer vision", "autonomous vehicles", "object detection"]
            }
        )

        rl_paper = GraphNode(
            id="paper5",
            type="paper",
            data={
                "title": "Reinforcement Learning Algorithms",
                "year": 2019,
                "citation_count": 110,
                "keywords": ["reinforcement learning", "Q-learning", "policy gradients"]
            }
        )

        # Create author nodes
        author1 = GraphNode(
            id="author1",
            type="author",
            data={
                "name": "Dr. Alice Johnson",
                "affiliation": "Stanford University",
                "h_index": 25
            }
        )

        author2 = GraphNode(
            id="author2",
            type="author",
            data={
                "name": "Prof. Bob Smith",
                "affiliation": "MIT",
                "h_index": 32
            }
        )

        author3 = GraphNode(
            id="author3",
            type="author",
            data={
                "name": "Dr. Carol Davis",
                "affiliation": "Google Research",
                "h_index": 19
            }
        )

        # Create concept nodes
        ai_concept = GraphNode(
            id="concept1",
            type="concept",
            data={
                "name": "Artificial Intelligence",
                "definition": "The simulation of human intelligence in machines"
            }
        )

        ml_concept = GraphNode(
            id="concept2",
            type="concept",
            data={
                "name": "Machine Learning",
                "definition": "Systems that learn from data without explicit programming"
            }
        )

        nlp_concept = GraphNode(
            id="concept3",
            type="concept",
            data={
                "name": "Natural Language Processing",
                "definition": "Processing and analyzing natural language text"
            }
        )

        cv_concept = GraphNode(
            id="concept4",
            type="concept",
            data={
                "name": "Computer Vision",
                "definition": "Systems that can interpret visual information"
            }
        )

        rl_concept = GraphNode(
            id="concept5",
            type="concept",
            data={
                "name": "Reinforcement Learning",
                "definition": "Learning through interaction with an environment"
            }
        )

        # Create embeddings for all nodes (simplified for example)
        # For simplicity, we're using a 3D space where:
        # - First dimension represents "theoretical research" content
        # - Second dimension represents "applied research" content
        # - Third dimension represents "experimental research" content

        # Paper embeddings
        ai_paper_emb = np.array([0.9, 0.6, 0.3])  # Theoretical and somewhat applied
        ml_paper_emb = np.array([0.4, 0.9, 0.7])  # Applied and experimental
        nlp_paper_emb = np.array([0.6, 0.8, 0.5])  # Both theoretical and applied
        cv_paper_emb = np.array([0.3, 0.8, 0.9])  # Highly applied and experimental
        rl_paper_emb = np.array([0.8, 0.4, 0.7])  # Theoretical and experimental

        # Concept embeddings (don't need to add vectors for authors in this example)
        ai_concept_emb = np.array([0.9, 0.5, 0.4])  # Theoretical foundation
        ml_concept_emb = np.array([0.7, 0.7, 0.6])  # Balanced
        nlp_concept_emb = np.array([0.6, 0.8, 0.6])  # More applied
        cv_concept_emb = np.array([0.4, 0.8, 0.8])  # Applied and experimental
        rl_concept_emb = np.array([0.8, 0.5, 0.8])  # Theoretical and experimental

        # Add nodes with embeddings
        graph.add_node_with_embedding(ai_paper, ai_paper_emb)
        graph.add_node_with_embedding(ml_paper, ml_paper_emb)
        graph.add_node_with_embedding(nlp_paper, nlp_paper_emb)
        graph.add_node_with_embedding(cv_paper, cv_paper_emb)
        graph.add_node_with_embedding(rl_paper, rl_paper_emb)

        # Add author and concept nodes
        graph.add_node(author1)
        graph.add_node(author2)
        graph.add_node(author3)

        graph.add_node_with_embedding(ai_concept, ai_concept_emb)
        graph.add_node_with_embedding(ml_concept, ml_concept_emb)
        graph.add_node_with_embedding(nlp_concept, nlp_concept_emb)
        graph.add_node_with_embedding(cv_concept, cv_concept_emb)
        graph.add_node_with_embedding(rl_concept, rl_concept_emb)

        # Step 2: Add relationships with properties
        print("\nStep 2: Adding relationships with properties")
        print("-----------------------------------------")

        # Paper authorship
        graph.add_edge("paper1", "authored_by", "author1", {"contribution": "primary"})
        graph.add_edge("paper1", "authored_by", "author2", {"contribution": "secondary"})
        graph.add_edge("paper2", "authored_by", "author1", {"contribution": "primary"})
        graph.add_edge("paper3", "authored_by", "author3", {"contribution": "primary"})
        graph.add_edge("paper4", "authored_by", "author2", {"contribution": "primary"})
        graph.add_edge("paper4", "authored_by", "author3", {"contribution": "secondary"})
        graph.add_edge("paper5", "authored_by", "author2", {"contribution": "primary"})

        # Paper citations
        graph.add_edge("paper2", "cites", "paper1", {"relevance": "high", "section": "background"})
        graph.add_edge("paper3", "cites", "paper1", {"relevance": "medium", "section": "related work"})
        graph.add_edge("paper3", "cites", "paper2", {"relevance": "high", "section": "methodology"})
        graph.add_edge("paper4", "cites", "paper1", {"relevance": "low", "section": "introduction"})
        graph.add_edge("paper4", "cites", "paper5", {"relevance": "high", "section": "methodology"})
        graph.add_edge("paper5", "cites", "paper1", {"relevance": "high", "section": "background"})

        # Paper topics
        graph.add_edge("paper1", "about", "concept1", {"centrality": "primary"})
        graph.add_edge("paper1", "about", "concept2", {"centrality": "secondary"})
        graph.add_edge("paper2", "about", "concept2", {"centrality": "primary"})
        graph.add_edge("paper3", "about", "concept3", {"centrality": "primary"})
        graph.add_edge("paper3", "about", "concept2", {"centrality": "secondary"})
        graph.add_edge("paper4", "about", "concept4", {"centrality": "primary"})
        graph.add_edge("paper5", "about", "concept5", {"centrality": "primary"})
        graph.add_edge("paper5", "about", "concept1", {"centrality": "secondary"})

        # Concept hierarchies
        graph.add_edge("concept2", "part_of", "concept1", {"strength": 0.8})
        graph.add_edge("concept3", "part_of", "concept1", {"strength": 0.7})
        graph.add_edge("concept4", "part_of", "concept1", {"strength": 0.6})
        graph.add_edge("concept5", "part_of", "concept1", {"strength": 0.9})
        graph.add_edge("concept3", "related_to", "concept2", {"strength": 0.5})
        graph.add_edge("concept4", "related_to", "concept2", {"strength": 0.4})
        graph.add_edge("concept5", "related_to", "concept2", {"strength": 0.6})

        # Print graph stats
        print(f"Graph has {len(graph.nodes)} nodes of {len(graph.node_types)} types")
        print(f"Node types: {', '.join(graph.node_types)}")
        print(f"Graph has {sum(len(edges) for edges in graph._edges_by_type.values())} edges of {len(graph.edge_types)} types")
        print(f"Edge types: {', '.join(graph.edge_types)}")

        # Step 3: Find similar connected nodes
        print("\nStep 3: Finding semantically similar and connected nodes")
        print("---------------------------------------------------")

        # Query for theoretical ML research
        query_vector = np.array([0.8, 0.6, 0.5])

        # Find nodes that are both semantically similar and connected through specific patterns
        results = graph.find_similar_connected_nodes(
            query_vector=query_vector,
            max_hops=2,
            min_similarity=0.7,
            edge_filters=[("relevance", "=", "high")],
            max_results=5
        )

        print("Papers that are semantically similar and connected by high relevance citations:")
        for i, result in enumerate(results):
            start_node = result["start_node"]
            end_node = result["end_node"]
            combined_score = result["combined_score"]

            print(f"  {i+1}. {start_node.data['title']} → {end_node.data['title']}")
            print(f"     Combined score: {combined_score:.3f}")
            print(f"     Start similarity: {result['start_similarity']:.3f}")
            print(f"     End similarity: {result['end_similarity']:.3f}")
            print(f"     Path length: {len(result['path'])}")

        # Step 4: Extract semantic subgraph
        print("\nStep 4: Extracting semantic subgraph")
        print("--------------------------------")

        # Create a focused subgraph of semantically similar nodes
        subgraph = graph.semantic_subgraph(
            query_vector=query_vector,
            similarity_threshold=0.7,
            include_connections=True,
            max_distance=2
        )

        print(f"Extracted subgraph with {len(subgraph.nodes)} nodes and {sum(len(edges) for edges in subgraph._edges_by_type.values())} edges")
        print("Nodes in subgraph:")
        for i, (node_id, node) in enumerate(list(subgraph.nodes.items())[:5]):
            if node.type == "paper":
                print(f"  {i+1}. Paper: {node.data['title']}")
            elif node.type == "concept":
                print(f"  {i+1}. Concept: {node.data['name']}")
            else:
                print(f"  {i+1}. {node.type}: {node.data.get('name', node_id)}")

        # Step 5: Perform logical query operations
        print("\nStep 5: Performing logical query operations")
        print("---------------------------------------")

        # Create query vectors
        theoretical_vector = np.array([0.9, 0.3, 0.4])  # Theoretical research
        applied_vector = np.array([0.3, 0.9, 0.5])      # Applied research

        # Find papers that are both theoretical AND applied
        and_results = graph.logical_query(
            query_vectors=[theoretical_vector, applied_vector],
            operators=["AND"],
            similarity_threshold=0.65
        )

        print("Papers that are both theoretical AND applied:")
        for i, (node, score) in enumerate(and_results):
            if node.type == "paper":  # Only show papers
                print(f"  {i+1}. {node.data['title']} (score: {score:.3f})")

        # Find papers that are theoretical OR experimental but NOT applied
        experimental_vector = np.array([0.4, 0.4, 0.9])  # Experimental research

        complex_results = graph.logical_query(
            query_vectors=[theoretical_vector, experimental_vector, applied_vector],
            operators=["OR", "NOT"],
            similarity_threshold=0.6
        )

        print("\nPapers that are theoretical OR experimental but NOT applied:")
        for i, (node, score) in enumerate(complex_results):
            if node.type == "paper":  # Only show papers
                print(f"  {i+1}. {node.data['title']} (score: {score:.3f})")

        # Step 6: Use incremental graph updates
        print("\nStep 6: Performing incremental graph updates")
        print("----------------------------------------")

        # Create new paper to add
        new_paper = GraphNode(
            id="paper6",
            type="paper",
            data={
                "title": "Survey of Deep Learning Models",
                "year": 2023,
                "citation_count": 40,
                "keywords": ["deep learning", "survey", "neural networks"]
            }
        )

        # Edges to add
        new_edges = [
            ("paper6", "authored_by", "author3", {"contribution": "primary"}),
            ("paper6", "cites", "paper1", {"relevance": "high", "section": "introduction"}),
            ("paper6", "cites", "paper3", {"relevance": "high", "section": "methodology"}),
            ("paper6", "about", "concept2", {"centrality": "primary"})
        ]

        # Edges to remove
        edges_to_remove = [
            ("paper3", "cites", "paper2")  # Remove this citation
        ]

        # Perform incremental update
        nodes_added, edges_added, nodes_removed, edges_removed = graph.incremental_graph_update(
            nodes_to_add=[new_paper],
            edges_to_add=new_edges,
            nodes_to_remove=[],
            edges_to_remove=edges_to_remove,
            maintain_index=True
        )

        print(f"Incremental update stats:")
        print(f"  - Nodes added: {nodes_added}")
        print(f"  - Edges added: {edges_added}")
        print(f"  - Nodes removed: {nodes_removed}")
        print(f"  - Edges removed: {edges_removed}")

        # Verify the new paper is in the graph
        new_paper_node = graph.get_node("paper6")
        print(f"\nAdded new paper: {new_paper_node.data['title']}")

        # Check its connections
        authors = graph.traverse(
            start_node_id="paper6",
            edge_type="authored_by",
            max_depth=1
        )

        cites = graph.traverse(
            start_node_id="paper6",
            edge_type="cites",
            max_depth=1
        )

        print(f"  - Authors: {', '.join([a.data['name'] for a in authors])}")
        print(f"  - Cites: {', '.join([c.data['title'] for c in cites])}")

        # Step 7: Generate path explanations
        print("\nStep 7: Generating path explanations")
        print("--------------------------------")

        # Find paths between two papers and explain them
        explanations = graph.explain_path(
            start_node_id="paper6",  # Our new paper
            end_node_id="paper2",    # Machine Learning in Healthcare paper
            max_paths=3,
            max_depth=3
        )

        print(f"Found {len(explanations)} paths between papers")

        for i, explanation in enumerate(explanations):
            print(f"\nPath {i+1} (confidence: {explanation['confidence']:.2f}):")
            print(f"Explanation: {explanation['explanation']}")

            print("Nodes in path:")
            for j, node_info in enumerate(explanation["nodes"]):
                print(f"  {j+1}. {node_info['type']}: {node_info['data'].get('title', node_info['data'].get('name', node_info['id']))}")

        # Step 8: Hybrid structured semantic search
        print("\nStep 8: Performing hybrid structured semantic search")
        print("------------------------------------------------")

        # Find papers similar to theoretical AI research, with high citations,
        # that cite papers with high relevance
        results = graph.hybrid_structured_semantic_search(
            query_vector=np.array([0.8, 0.5, 0.4]),  # Theoretical AI research
            node_filters=[
                ("citation_count", ">=", 90),  # Only highly cited papers
                ("year", ">", 2019)            # Recent papers
            ],
            relationship_patterns=[
                {
                    "direction": "outgoing",
                    "edge_type": "cites",
                    "edge_filters": [
                        ("relevance", "=", "high")
                    ]
                }
            ],
            max_results=5,
            min_similarity=0.6
        )

        print(f"Found {len(results)} papers matching all criteria:")
        for i, result in enumerate(results):
            node = result["node"]
            similarity = result["similarity"]

            print(f"  {i+1}. {node['data']['title']} (similarity: {similarity:.3f})")
            print(f"     Citation count: {node['data']['citation_count']}")
            print(f"     Year: {node['data']['year']}")
            print(f"     Matches all filters: {result['matches_filters'] and result['matches_patterns']}")

        # Step 9: Rank nodes by centrality
        print("\nStep 9: Ranking nodes by centrality (PageRank)")
        print("------------------------------------------")

        # Rank nodes using PageRank algorithm with semantic influence
        centrality_results = graph.rank_nodes_by_centrality(
            query_vector=np.array([0.7, 0.7, 0.3]),  # Both theoretical and applied research
            damping_by_similarity=True,  # Adjust PageRank based on similarity to query
            weight_by_edge_properties={"cites": "relevance", "about": "centrality"}  # Weight edges by properties
        )

        print("Most central nodes in the knowledge graph:")
        for i, (node, score) in enumerate(centrality_results[:5]):
            print(f"  {i+1}. {node.type.capitalize()}: {node.data.get('title', node.data.get('name', node.id))}")
            print(f"     Centrality score: {score:.4f}")

            # Show connections
            outgoing_edges = sum(len(edges) for edges in node.edges.values())
            incoming_edges = sum(
                1 for source in graph.nodes.values()
                for edges in source.edges.values()
                for edge in edges
                if edge["target"].id == node.id
            )
            print(f"     Connections: {outgoing_edges} outgoing, {incoming_edges} incoming")

        # Step 10: Multi-hop inference
        print("\nStep 10: Multi-hop inference")
        print("-------------------------")

        # Infer potential collaborators based on citation patterns
        # A-authored->P1-cites->P2-authored_by->B suggests A and B might collaborate
        inferred_relationships = graph.multi_hop_inference(
            start_node_id="author1",  # First author
            relationship_pattern=["authored", "cites", "authored_by"],
            confidence_threshold=0.3,
            max_results=5
        )

        print(f"Inferred potential collaborators for {graph.nodes['author1'].data['name']}:")
        for i, inferred in enumerate(inferred_relationships):
            end_node = inferred["end_node"]
            confidence = inferred["confidence"]

            print(f"  {i+1}. {end_node.data.get('name', end_node.id)} (confidence: {confidence:.2f})")
            print(f"     Inferred relationship: {inferred['inferred_relationship']}")

            # Print the path
            path_str = []
            for j, (node, edge_type, props) in enumerate(inferred["path"]):
                if j == 0:
                    # First node
                    path_str.append(node.data.get('name', node.id))

                if edge_type:
                    # Add edge
                    path_str.append(f"-[{edge_type}]->")
                    # Add next node if not the last step
                    if j < len(inferred["path"]) - 1:
                        next_node = inferred["path"][j+1][0]
                        if next_node.type == "paper":
                            path_str.append(next_node.data.get('title', next_node.id))
                        else:
                            path_str.append(next_node.data.get('name', next_node.id))

            print(f"     Path: {' '.join(path_str)}")

        # Step 11: Identify entity clusters
        print("\nStep 11: Identifying entity clusters")
        print("--------------------------------")

        # Find clusters of related entities
        clusters = graph.find_entity_clusters(
            similarity_threshold=0.65,
            min_community_size=2,
            max_communities=3,
            relationship_weight=0.4  # Weight of structural relationships vs semantic similarity
        )

        print(f"Found {len(clusters)} entity clusters:")
        for i, cluster in enumerate(clusters):
            # Show cluster stats
            cohesion = cluster["cohesion"]
            size = cluster["size"]
            themes = cluster["themes"]

            print(f"  Cluster {i+1} (size: {size}, cohesion: {cohesion:.2f})")
            print(f"     Themes: {', '.join(themes[:3]) if themes else 'None identified'}")

            # Show some cluster members
            print(f"     Members:")
            for j, node in enumerate(cluster["nodes"][:3]):
                if node.type == "paper":
                    print(f"       - Paper: {node.data.get('title', node.id)}")
                elif node.type == "concept":
                    print(f"       - Concept: {node.data.get('name', node.id)}")
                else:
                    print(f"       - {node.type.capitalize()}: {node.data.get('name', node.id)}")

            if len(cluster["nodes"]) > 3:
                print(f"       - ... and {len(cluster['nodes']) - 3} more nodes")

        # Step 12: Query expansion
        print("\nStep 12: Performing query expansion")
        print("------------------------------")

        # Original query vector for theoretical AI research
        original_query = np.array([0.8, 0.2, 0.3])
        print(f"Original query vector: {original_query}")

        # Try different expansion strategies
        expansion_strategies = [
            "neighbor_vectors",     # Use vectors of semantically similar nodes
            "cluster_centroids",    # Use centroids of relevant clusters
            "concept_enrichment"    # Emphasize conceptual dimensions
        ]

        for strategy in expansion_strategies:
            # Expand the query
            expanded_query = graph.expand_query(
                query_vector=original_query,
                expansion_strategy=strategy,
                expansion_factor=0.3,  # Weight of expansion terms
                max_terms=3,           # Max number of expansion terms
                min_similarity=0.6     # Minimum similarity threshold
            )

            # Show the expanded query
            print(f"\nExpanded query using {strategy}:")
            print(f"  Expanded vector: {expanded_query}")

            # Compare with original
            similarity = np.dot(expanded_query, original_query / np.linalg.norm(original_query))
            print(f"  Similarity to original: {similarity:.3f}")

            # Demonstrate improved search with expanded query
            results_original = graph.vector_search(original_query, k=3)
            results_expanded = graph.vector_search(expanded_query, k=3)

            print(f"\n  Top results with original query:")
            for i, (node, score) in enumerate(results_original):
                print(f"    {i+1}. {node.data.get('title', node.data.get('name', node.id))} (score: {score:.3f})")

            print(f"\n  Top results with expanded query:")
            for i, (node, score) in enumerate(results_expanded):
                print(f"    {i+1}. {node.data.get('title', node.data.get('name', node.id))} (score: {score:.3f})")

        # Step 13: Entity resolution
        print("\nStep 13: Entity resolution and deduplication")
        print("---------------------------------------")

        # Create a duplicated paper with slightly modified properties
        original_paper = graph.nodes["paper1"]
        duplicate_paper = GraphNode(
            id="paper1_duplicate",
            type="paper",
            data={
                "title": original_paper.data["title"] + " (Preprint)",
                "year": original_paper.data["year"] - 1,  # Published a year earlier
                "citation_count": original_paper.data["citation_count"] // 2  # Fewer citations
            }
        )

        # Add the duplicate with the same embedding
        original_idx = graph._node_to_vector_idx[original_paper.id]
        if graph.vector_index._faiss_available:
            original_vector = graph.vector_index._index.reconstruct(original_idx)
        else:
            original_vector = np.vstack(graph.vector_index._vectors)[original_idx]

        graph.add_node_with_embedding(duplicate_paper, original_vector)

        # Create another paper with similar but not identical content
        similar_paper = GraphNode(
            id="paper1_similar",
            type="paper",
            data={
                "title": "Advances in Machine Intelligence",  # Similar but different title
                "year": original_paper.data["year"] + 1,
                "citation_count": original_paper.data["citation_count"] + 20
            }
        )

        # Add with a similar but not identical vector
        similar_vector = original_vector.copy()
        similar_vector += np.random.normal(0, 0.2, size=len(similar_vector))  # Add noise
        similar_vector = similar_vector / np.linalg.norm(similar_vector)  # Normalize
        graph.add_node_with_embedding(similar_paper, similar_vector)

        # Add edges to connect the papers
        graph.add_edge("paper1_similar", "cites", "paper1", {"relevance": "high"})
        graph.add_edge("paper1_duplicate", "cites", "paper2", {"relevance": "medium"})

        # Now run entity resolution
        candidates = [
            graph.nodes["paper1"],
            graph.nodes["paper1_duplicate"],
            graph.nodes["paper1_similar"],
            graph.nodes["paper2"]
        ]

        print("Running entity resolution:")
        for strategy in ["vector_similarity", "property_matching", "hybrid"]:
            entity_groups = graph.resolve_entities(
                candidate_nodes=candidates,
                resolution_strategy=strategy,
                similarity_threshold=0.7
            )

            print(f"\n  Using {strategy} strategy:")
            for canonical_id, group in entity_groups.items():
                if len(group) > 1:  # Only show groups with more than one entity
                    canonical_entity = group[0]
                    print(f"    Group for {canonical_entity.data.get('title', canonical_id)} has {len(group)} entities:")
                    for entity in group:
                        print(f"      - {entity.id}: {entity.data.get('title')}")

        # Step 14: Contextual embeddings
        print("\nStep 14: Generating contextual embeddings")
        print("-----------------------------------")

        # Generate contextual embeddings for a paper
        paper_id = "paper1"
        author_id = "author1"

        # Show the different context strategies
        context_strategies = [
            "neighborhood",    # Simple neighborhood averaging
            "weighted_edges",  # Weight by edge properties
            "type_specific"    # Node type-specific context rules
        ]

        print(f"Generating contextual embeddings for paper: {graph.nodes[paper_id].data['title']}")

        # Get the original embedding for comparison
        original_idx = graph._node_to_vector_idx[paper_id]
        if graph.vector_index._faiss_available:
            original_vector = graph.vector_index._index.reconstruct(original_idx)
        else:
            original_vector = np.vstack(graph.vector_index._vectors)[original_idx]

        original_vector = original_vector / np.linalg.norm(original_vector)

        # Generate contextual embeddings with different strategies
        for strategy in context_strategies:
            contextual_embedding = graph.generate_contextual_embeddings(
                node_id=paper_id,
                context_strategy=strategy,
                context_depth=1,
                edge_weight_property="relevance"  # For weighted_edges strategy
            )

            # Show the contextual embedding and compare to original
            similarity = np.dot(contextual_embedding, original_vector)

            print(f"\n  Using {strategy} strategy:")
            print(f"    Similarity to original: {similarity:.3f}")

            # Show what this contextual embedding is more similar to
            contextual_results = graph.vector_search(contextual_embedding, k=3)
            print(f"    Top matches for contextual embedding:")
            for i, (node, score) in enumerate(contextual_results):
                print(f"      {i+1}. {node.data.get('title', node.data.get('name', node.id))} (score: {score:.3f})")

        # Also show author contextual embedding
        print(f"\nGenerating contextual embedding for author: {graph.nodes[author_id].data['name']}")
        author_contextual = graph.generate_contextual_embeddings(
            node_id=author_id,
            context_strategy="type_specific",
            context_depth=1
        )

        # Show top matches for the author's contextual embedding
        if author_contextual is not None:
            author_results = graph.vector_search(author_contextual, k=3)
            print(f"  Top matches for author's contextual embedding:")
            for i, (node, score) in enumerate(author_results):
                print(f"    {i+1}. {node.data.get('title', node.data.get('name', node.id))} (score: {score:.3f})")

        # Step 15: Compare subgraphs
        print("\nStep 15: Comparing subgraphs")
        # Extract two subgraphs: ML-focused and CV-focused
        ml_focus_query = np.array([0.8, 0.2, 0.3])  # Focus on ML
        cv_focus_query = np.array([0.3, 0.2, 0.9])  # Focus on CV/deep learning

        ml_subgraph = graph.semantic_subgraph(
            query_vector=ml_focus_query,
            similarity_threshold=0.7,
            include_connections=True
        )

        cv_subgraph = graph.semantic_subgraph(
            query_vector=cv_focus_query,
            similarity_threshold=0.7,
            include_connections=True
        )

        # Compare the subgraphs
        comparison = graph.compare_subgraphs(
            subgraph1=ml_subgraph,
            subgraph2=cv_subgraph,
            comparison_method="hybrid",
            semantic_weight=0.6,
            structural_weight=0.4
        )

        print(f"Comparison results between ML and CV subgraphs:")
        print(f"  Overall similarity: {comparison['overall_similarity']:.3f}")
        print(f"  Semantic similarity: {comparison['semantic_similarity']:.3f}")
        print(f"  Structural similarity: {comparison['structural_similarity']:.3f}")
        print(f"  Shared nodes: {len(comparison['shared_nodes'])}")

        # Step 16: Temporal graph analysis
        print("\nStep 16: Temporal graph analysis")
        # Ensure all paper nodes have a year property
        for node_id, node in graph.nodes.items():
            if node.type == "paper" and "year" not in node.data:
                node.data["year"] = 2020  # Default year

        # Define time intervals
        time_intervals = [(2018, 2019), (2020, 2021), (2022, 2023)]

        # Perform temporal analysis
        time_analysis = graph.temporal_graph_analysis(
            time_property="year",
            time_intervals=time_intervals,
            metrics=["node_count", "edge_count", "density", "centrality"],
            reference_node_id="paper1"  # Track a specific paper over time
        )

        print(f"Temporal analysis across {len(time_analysis['snapshots'])} time periods:")
        for i, snapshot in enumerate(time_analysis["snapshots"]):
            print(f"  Time period {i+1} ({snapshot['interval'][0]}-{snapshot['interval'][1]}):")
            print(f"    Nodes: {snapshot.get('node_count', 0)}")
            print(f"    Edges: {snapshot.get('edge_count', 0)}")
            print(f"    Density: {snapshot.get('density', 0):.3f}")

        if "trends" in time_analysis and time_analysis["trends"]:
            print("\n  Growth trends:")
            for metric, values in time_analysis["trends"].items():
                if values:
                    avg_growth = sum(values) / len(values)
                    print(f"    {metric}: {avg_growth:.2f}")

        # Step 17: Knowledge graph completion
        print("\nStep 17: Knowledge graph completion (predicting missing relationships)")
        # Predict missing citation relationships
        predicted_edges = graph.knowledge_graph_completion(
            completion_method="combined",
            target_relation_types=["cites"],
            min_confidence=0.5,
            max_candidates=5
        )

        if predicted_edges:
            print(f"Top predicted relationships:")
            for i, prediction in enumerate(predicted_edges[:3]):
                source = prediction["source_node"].data.get("title", prediction["source_node"].id)
                target = prediction["target_node"].data.get("title", prediction["target_node"].id)
                confidence = prediction["confidence"]
                reason = prediction["explanation"]

                print(f"  {i+1}. {source} should cite {target}")
                print(f"     Confidence: {confidence:.2f}")
                print(f"     Reason: {reason}")
        else:
            print("No relationships predicted with current confidence threshold.")

        # Step 18: Cross-document reasoning
        print("\nStep 18: Cross-document reasoning")

        # Add some document content for better reasoning
        for paper_id in ["paper1", "paper2", "paper3", "paper4", "paper5"]:
            if paper_id in graph.nodes:
                paper = graph.nodes[paper_id]
                title = paper.data.get("title", "")
                paper.data["content"] = f"This paper discusses {title} in detail, focusing on recent advances."

        # Perform cross-document reasoning with a complex query
        reasoning_result = graph.cross_document_reasoning(
            query="How has deep learning influenced computer vision?",
            document_node_types=["paper"],
            max_hops=2,
            reasoning_depth="moderate"
        )

        # Show the reasoning results
        print(f"Query: 'How has deep learning influenced computer vision?'")
        print(f"Answer confidence: {reasoning_result['confidence']:.2f}")
        print(f"Documents used: {len(reasoning_result['documents'])}")
        print("\nAnswer:")
        print(reasoning_result["answer"])

        print("\nReasoning process:")
        for i, step in enumerate(reasoning_result["reasoning_trace"]):
            print(f"  {i+1}. {step}")

        # Try a more complex query with deep reasoning
        deep_reasoning = graph.cross_document_reasoning(
            query="What potential collaborations exist between researchers with different expertise areas?",
            document_node_types=["paper"],
            max_hops=3,
            reasoning_depth="deep"
        )

        print("\nComplex query using deep reasoning:")
        print(f"Answer confidence: {deep_reasoning['confidence']:.2f}")
        print("\nAnswer:")
        print(deep_reasoning["answer"])

    finally:
        # Clean up
        import shutil
        shutil.rmtree(temp_dir)
        print("\nCleaned up temporary directory")


def sharded_dataset_example():
    """Example demonstrating sharded datasets across multiple IPFS nodes."""
    print("IPFS Datasets Python - Sharded Datasets Example")
    print("===========================================")

    # Import required components
    import pandas as pd
    import numpy as np
    import asyncio

    try:
        # Import libp2p components
        from ipfs_datasets_py.libp2p_kit import (
            DistributedDatasetManager,
            NodeRole,
            LibP2PNotAvailableError
        )
    except ImportError:
        print("LibP2P is not available. Install with: pip install py-libp2p")
        return

    # Create a temporary directory for our examples
    import tempfile
    temp_dir = tempfile.mkdtemp()
    print(f"Using temporary directory: {temp_dir}")

    try:
        # Initialize a coordinator node for managing the dataset
        print("\nStep 1: Setting up a coordinator node")
        print("-----------------------------------")
        coordinator = DistributedDatasetManager(
            storage_dir=os.path.join(temp_dir, "coordinator"),
            node_id="coordinator-node",
            listen_addresses=["/ip4/127.0.0.1/tcp/0"],
            role=NodeRole.COORDINATOR,
            auto_start=True
        )

        # Initialize worker nodes
        print("\nStep 2: Setting up worker nodes")
        print("----------------------------")
        worker1 = DistributedDatasetManager(
            storage_dir=os.path.join(temp_dir, "worker1"),
            node_id="worker-node-1",
            listen_addresses=["/ip4/127.0.0.1/tcp/0"],
            bootstrap_peers=[f"/ip4/127.0.0.1/tcp/{addr.port}/p2p/{addr.peer_id}"
                            for addr in coordinator.node.host.get_addrs()],
            role=NodeRole.WORKER,
            auto_start=True
        )

        worker2 = DistributedDatasetManager(
            storage_dir=os.path.join(temp_dir, "worker2"),
            node_id="worker-node-2",
            listen_addresses=["/ip4/127.0.0.1/tcp/0"],
            bootstrap_peers=[f"/ip4/127.0.0.1/tcp/{addr.port}/p2p/{addr.peer_id}"
                            for addr in coordinator.node.host.get_addrs()],
            role=NodeRole.WORKER,
            auto_start=True
        )

        # Create a sample dataset
        print("\nStep 3: Creating a sample dataset")
        print("------------------------------")
        sample_data = pd.DataFrame({
            "id": list(range(1000)),
            "text": [f"Sample text {i}" for i in range(1000)],
            "value": [float(i) for i in range(1000)],
            "vector": [np.random.rand(128).tolist() for _ in range(1000)]
        })
        print(f"Created sample dataset with {len(sample_data)} records")

        async def distribute_dataset():
            try:
                # Create a dataset definition
                dataset = coordinator.create_dataset(
                    name="Sharded Test Dataset",
                    description="A test dataset distributed across nodes",
                    schema={"id": "integer", "text": "string", "value": "float", "vector": "float[]"},
                    vector_dimensions=128,
                    tags=["example", "sharded", "test"]
                )
                print(f"Created dataset with ID: {dataset.dataset_id}")

                # Shard and distribute the dataset
                print("\nStep 4: Sharding and distributing the dataset")
                print("------------------------------------------")
                shards = await coordinator.shard_dataset(
                    dataset_id=dataset.dataset_id,
                    data=sample_data,
                    format="parquet",
                    shard_size=200,  # 5 shards of 200 records each
                    replication_factor=2,  # Replicate each shard to 2 nodes
                    use_consistent_hashing=True
                )
                print(f"Created {len(shards)} shards")

                # Allow some time for distribution to complete
                print("Waiting for distribution to complete...")
                await asyncio.sleep(2)

                # Synchronize with the network
                print("\nStep 5: Synchronizing metadata across nodes")
                print("----------------------------------------")
                sync_results1 = await worker1.sync_with_network()
                print(f"Worker 1 sync results: {sync_results1}")

                sync_results2 = await worker2.sync_with_network()
                print(f"Worker 2 sync results: {sync_results2}")

                # Get network status
                coordinator_status = await coordinator.get_network_status()
                worker1_status = await worker1.get_network_status()
                worker2_status = await worker2.get_network_status()

                print("\nStep 6: Checking network status")
                print("----------------------------")
                print(f"Coordinator: {coordinator_status['node_id']}")
                print(f"  - Connected peers: {coordinator_status['peer_count']}")
                print(f"  - Datasets: {coordinator_status['dataset_count']}")
                print(f"  - Shards: {coordinator_status['shard_count']}")

                print(f"\nWorker 1: {worker1_status['node_id']}")
                print(f"  - Connected peers: {worker1_status['peer_count']}")
                print(f"  - Datasets: {worker1_status['dataset_count']}")
                print(f"  - Shards: {worker1_status['shard_count']}")

                print(f"\nWorker 2: {worker2_status['node_id']}")
                print(f"  - Connected peers: {worker2_status['peer_count']}")
                print(f"  - Datasets: {worker2_status['dataset_count']}")
                print(f"  - Shards: {worker2_status['shard_count']}")

                # Perform a federated search
                print("\nStep 7: Performing federated search across nodes")
                print("--------------------------------------------")
                query_vector = np.random.rand(128)
                search_results = await coordinator.vector_search(
                    dataset_id=dataset.dataset_id,
                    query_vector=query_vector,
                    top_k=5
                )

                print(f"Search results: Found {search_results.get('total_results', 0)} matches")
                print(f"Nodes queried: {len(search_results.get('nodes_queried', []))}")

                # Rebalance shards
                print("\nStep 8: Rebalancing shards across nodes")
                print("------------------------------------")
                rebalance_results = await coordinator.rebalance_shards(
                    dataset_id=dataset.dataset_id,
                    target_replication=2
                )
                print(f"Rebalanced {rebalance_results.get('total_shards_rebalanced', 0)} shards")

                return "Completed successfully"
            except Exception as e:
                print(f"Error in distributed operations: {str(e)}")
                return f"Error: {str(e)}"

        # Run the async example
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(distribute_dataset())
        print(f"\nResult: {result}")

    except LibP2PNotAvailableError:
        print("LibP2P is not available. Install with: pip install py-libp2p")
    except Exception as e:
        print(f"Error running sharded dataset example: {str(e)}")
    finally:
        # Clean up
        import shutil
        shutil.rmtree(temp_dir)
        print("\nCleaned up temporary directory")


def federated_search_example():
    """Example demonstrating advanced federated search across distributed dataset fragments."""
    print("IPFS Datasets Python - Federated Search Example")
    print("============================================")

    # Import required components
    import pandas as pd
    import numpy as np
    import asyncio
    import random

    try:
        # Import required components
        from ipfs_datasets_py.libp2p_kit import (
            DistributedDatasetManager,
            NodeRole,
            LibP2PNotAvailableError
        )
        from ipfs_datasets_py.federated_search import (
            FederatedSearch,
            SearchQuery,
            SearchType,
            RankingStrategy,
            DistributedSearchIndex
        )
    except ImportError:
        print("Required dependencies are not available. Install with: pip install py-libp2p")
        return

    # Create a temporary directory for our examples
    import tempfile
    temp_dir = tempfile.mkdtemp()
    print(f"Using temporary directory: {temp_dir}")

    try:
        # Initialize a coordinator node and worker nodes
        print("\nStep 1: Setting up a coordinator node and worker nodes")
        print("--------------------------------------------------")
        coordinator = DistributedDatasetManager(
            storage_dir=os.path.join(temp_dir, "coordinator"),
            node_id="coordinator-node",
            listen_addresses=["/ip4/127.0.0.1/tcp/0"],
            role=NodeRole.COORDINATOR,
            auto_start=True
        )

        # Wait for the coordinator to start
        coordinator_address = f"/ip4/127.0.0.1/tcp/{coordinator.node.host.get_addrs()[0].port}/p2p/{coordinator.node.host.get_id()}"

        # Initialize worker nodes
        worker1 = DistributedDatasetManager(
            storage_dir=os.path.join(temp_dir, "worker1"),
            node_id="worker-node-1",
            listen_addresses=["/ip4/127.0.0.1/tcp/0"],
            bootstrap_peers=[coordinator_address],
            role=NodeRole.WORKER,
            auto_start=True
        )

        worker2 = DistributedDatasetManager(
            storage_dir=os.path.join(temp_dir, "worker2"),
            node_id="worker-node-2",
            listen_addresses=["/ip4/127.0.0.1/tcp/0"],
            bootstrap_peers=[coordinator_address],
            role=NodeRole.WORKER,
            auto_start=True
        )

        print(f"Created coordinator and 2 worker nodes")

        # Create synthetic data for our examples
        # This time, let's create data with different categories and features
        # for demonstrating different types of search
        print("\nStep 2: Creating sample datasets with rich features")
        print("------------------------------------------------")

        # Categories for our documents
        categories = ["technology", "science", "health", "business", "entertainment"]

        # Create sample text data
        def generate_sample_document(idx, category):
            # Create text based on category
            if category == "technology":
                text = f"This is a technology article about {random.choice(['AI', 'blockchain', 'cloud computing', 'mobile devices'])}"
                text += f" discussing {random.choice(['recent advances', 'industry trends', 'security challenges'])}"
            elif category == "science":
                text = f"Science research on {random.choice(['quantum physics', 'astronomy', 'biology', 'chemistry'])}"
                text += f" exploring {random.choice(['new discoveries', 'theoretical models', 'experimental results'])}"
            elif category == "health":
                text = f"Health information about {random.choice(['nutrition', 'exercise', 'mental health', 'disease prevention'])}"
                text += f" focusing on {random.choice(['latest studies', 'best practices', 'medical advice'])}"
            elif category == "business":
                text = f"Business news on {random.choice(['stock market', 'startups', 'corporate strategy', 'economics'])}"
                text += f" analyzing {random.choice(['market trends', 'company performance', 'investment opportunities'])}"
            else:  # entertainment
                text = f"Entertainment updates about {random.choice(['movies', 'music', 'celebrities', 'gaming'])}"
                text += f" featuring {random.choice(['new releases', 'award ceremonies', 'industry events'])}"

            # Create a document with various fields
            return {
                "id": idx,
                "title": f"{category.capitalize()} article {idx}",
                "text": text,
                "category": category,
                "date": f"2023-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}",
                "rating": round(random.uniform(1, 5), 1),
                "views": random.randint(100, 10000)
            }

        # Generate 1000 documents
        print("Generating 1000 sample documents...")
        documents = []
        for i in range(1000):
            category = random.choice(categories)
            doc = generate_sample_document(i, category)

            # Generate a "category-biased" vector
            # Higher values in dimensions that correspond to the category
            vec = np.random.normal(0, 0.3, 128)  # base vector with random noise

            # Boost specific dimensions based on category
            category_idx = categories.index(category)
            category_dimensions = list(range(category_idx * 25, (category_idx + 1) * 25))
            vec[category_dimensions] += np.random.uniform(0.5, 1.0, len(category_dimensions))

            # Normalize the vector
            vec = vec / np.linalg.norm(vec)

            # Add to document
            doc["vector"] = vec.tolist()
            documents.append(doc)

        # Create a pandas DataFrame
        sample_data = pd.DataFrame(documents)
        print(f"Created sample dataset with {len(sample_data)} documents across {len(categories)} categories")

        async def setup_and_search():
            try:
                # Create a dataset definition
                dataset = coordinator.create_dataset(
                    name="Rich Feature Dataset",
                    description="A dataset with text, categories, and vector embeddings",
                    schema={
                        "id": "integer",
                        "title": "string",
                        "text": "string",
                        "category": "string",
                        "date": "string",
                        "rating": "float",
                        "views": "integer",
                        "vector": "float[]"
                    },
                    vector_dimensions=128,
                    tags=["example", "federated", "search"]
                )
                print(f"Created dataset with ID: {dataset.dataset_id}")

                # Shard and distribute the dataset
                print("\nStep 3: Sharding and distributing the dataset")
                print("------------------------------------------")

                # Create smaller shard size to distribute across more shards
                shards = await coordinator.shard_dataset(
                    dataset_id=dataset.dataset_id,
                    data=sample_data,
                    format="parquet",
                    shard_size=100,  # 10 shards of 100 records each
                    replication_factor=2,  # Replicate each shard to 2 nodes
                    use_consistent_hashing=True
                )
                print(f"Created {len(shards)} shards")

                # Allow some time for distribution to complete
                print("Waiting for distribution to complete...")
                await asyncio.sleep(2)

                # Synchronize with the network
                print("\nStep 4: Synchronizing metadata across nodes")
                print("----------------------------------------")
                sync_results1 = await worker1.sync_with_network()
                print(f"Worker 1 sync results: {sync_results1}")

                sync_results2 = await worker2.sync_with_network()
                print(f"Worker 2 sync results: {sync_results2}")

                # Initialize the federated search engines on each node
                print("\nStep 5: Setting up federated search engines")
                print("----------------------------------------")
                coordinator_search = FederatedSearch(
                    node=coordinator.node,
                    storage_dir=os.path.join(temp_dir, "coordinator_search"),
                    ranking_strategy=RankingStrategy.SCORE
                )

                worker1_search = FederatedSearch(
                    node=worker1.node,
                    storage_dir=os.path.join(temp_dir, "worker1_search"),
                    ranking_strategy=RankingStrategy.SCORE
                )

                worker2_search = FederatedSearch(
                    node=worker2.node,
                    storage_dir=os.path.join(temp_dir, "worker2_search"),
                    ranking_strategy=RankingStrategy.SCORE
                )

                print("Federated search engines initialized")

                # Allow nodes to build local indices
                print("\nStep 6: Building search indices")
                print("----------------------------")

                # Build indices on coordinator
                coord_index = await DistributedSearchIndex.build_for_dataset(
                    dataset_id=dataset.dataset_id,
                    shard_manager=coordinator.shard_manager,
                    base_dir=os.path.join(temp_dir, "coordinator_indices"),
                    vector_dimensions=128,
                    distance_metric="cosine",
                    vector_field="vector",
                    text_fields=["title", "text", "category"],
                    include_all_text_fields=True
                )

                # Build indices on workers
                worker1_index = await DistributedSearchIndex.build_for_dataset(
                    dataset_id=dataset.dataset_id,
                    shard_manager=worker1.shard_manager,
                    base_dir=os.path.join(temp_dir, "worker1_indices"),
                    vector_dimensions=128,
                    distance_metric="cosine",
                    vector_field="vector",
                    text_fields=["title", "text", "category"],
                    include_all_text_fields=True
                )

                worker2_index = await DistributedSearchIndex.build_for_dataset(
                    dataset_id=dataset.dataset_id,
                    shard_manager=worker2.shard_manager,
                    base_dir=os.path.join(temp_dir, "worker2_indices"),
                    vector_dimensions=128,
                    distance_metric="cosine",
                    vector_field="vector",
                    text_fields=["title", "text", "category"],
                    include_all_text_fields=True
                )

                print("Search indices built on all nodes")

                # Perform different types of federated searches
                print("\nStep 7: Performing federated vector search")
                print("----------------------------------------")

                # Create a technology-biased query vector
                tech_query_vector = np.random.normal(0, 0.3, 128)
                tech_dimensions = list(range(0, 25))  # Technology category dimensions
                tech_query_vector[tech_dimensions] += np.random.uniform(0.5, 1.0, len(tech_dimensions))
                tech_query_vector = tech_query_vector / np.linalg.norm(tech_query_vector)

                # Perform vector search from coordinator
                vector_results = await coordinator_search.vector_search(
                    dataset_id=dataset.dataset_id,
                    query_vector=tech_query_vector.tolist(),
                    top_k=5,
                    distance_metric="cosine",
                    include_metadata=True
                )

                print(f"Vector search results: {vector_results.total_results} total matches")
                print(f"Nodes queried: {len(vector_results.nodes_queried)}")
                print(f"Nodes responded: {len(vector_results.nodes_responded)}")
                print("Top results:")

                for i, result in enumerate(vector_results.results[:3]):
                    print(f"  {i+1}. {result.metadata.get('title')} (Score: {result.score:.3f})")
                    print(f"     Category: {result.metadata.get('category')}")
                    print(f"     Text: {result.metadata.get('text')[:100]}...")
                    print(f"     From node: {result.node_id}, Shard: {result.shard_id}")

                # Perform keyword search
                print("\nStep 8: Performing federated keyword search")
                print("-----------------------------------------")

                keyword_results = await coordinator_search.keyword_search(
                    dataset_id=dataset.dataset_id,
                    query_text="AI technology advances",
                    fields=["title", "text"],
                    top_k=5,
                    include_metadata=True
                )

                print(f"Keyword search results: {keyword_results.total_results} total matches")
                print(f"Nodes queried: {len(keyword_results.nodes_queried)}")
                print(f"Nodes responded: {len(keyword_results.nodes_responded)}")
                print("Top results:")

                for i, result in enumerate(keyword_results.results[:3]):
                    print(f"  {i+1}. {result.metadata.get('title')} (Score: {result.score:.3f})")
                    print(f"     Category: {result.metadata.get('category')}")
                    print(f"     Matched terms: {', '.join(result.matched_terms or [])}")
                    print(f"     From node: {result.node_id}, Shard: {result.shard_id}")

                # Perform hybrid search (vector + keyword)
                print("\nStep 9: Performing federated hybrid search")
                print("-----------------------------------------")

                hybrid_results = await coordinator_search.hybrid_search(
                    dataset_id=dataset.dataset_id,
                    query_text="science research discoveries",
                    query_vector=tech_query_vector.tolist(),  # Intentionally using tech vector to show hybrid effect
                    fields=["title", "text"],
                    top_k=5,
                    vector_weight=0.6,
                    text_weight=0.4,
                    include_metadata=True
                )

                print(f"Hybrid search results: {hybrid_results.total_results} total matches")
                print(f"Nodes queried: {len(hybrid_results.nodes_queried)}")
                print(f"Nodes responded: {len(hybrid_results.nodes_responded)}")
                print("Top results:")

                for i, result in enumerate(hybrid_results.results[:3]):
                    print(f"  {i+1}. {result.metadata.get('title')} (Score: {result.score:.3f})")
                    print(f"     Category: {result.metadata.get('category')}")
                    print(f"     Text: {result.metadata.get('text')[:100]}...")
                    print(f"     From node: {result.node_id}, Shard: {result.shard_id}")

                # Perform filter search
                print("\nStep 10: Performing federated filter search")
                print("-----------------------------------------")

                filter_results = await coordinator_search.filter_search(
                    dataset_id=dataset.dataset_id,
                    filters=[
                        {"field": "category", "operator": "eq", "value": "health"},
                        {"field": "rating", "operator": "gte", "value": 4.0}
                    ],
                    top_k=5,
                    include_metadata=True
                )

                print(f"Filter search results: {filter_results.total_results} total matches")
                print(f"Nodes queried: {len(filter_results.nodes_queried)}")
                print(f"Nodes responded: {len(filter_results.nodes_responded)}")
                print("Top results:")

                for i, result in enumerate(filter_results.results[:3]):
                    print(f"  {i+1}. {result.metadata.get('title')}")
                    print(f"     Category: {result.metadata.get('category')}")
                    print(f"     Rating: {result.metadata.get('rating')}")
                    print(f"     From node: {result.node_id}, Shard: {result.shard_id}")

                # Get search statistics
                print("\nStep 11: Reviewing search statistics")
                print("----------------------------------")

                stats = coordinator_search.get_statistics()
                print(f"Total queries: {stats['total_queries']}")
                print(f"Average execution time: {stats['avg_execution_time_ms']:.2f} ms")
                print(f"Cache hit rate: {stats['cache_hit_rate']:.2f}")
                print(f"Total nodes queried: {stats['nodes_queried_count']}")

                return "Federated search examples completed successfully"
            except Exception as e:
                print(f"Error in federated search operations: {str(e)}")
                import traceback
                traceback.print_exc()
                return f"Error: {str(e)}"

        # Run the async example
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(setup_and_search())
        print(f"\nResult: {result}")

    except LibP2PNotAvailableError:
        print("LibP2P is not available. Install with: pip install py-libp2p")
    except Exception as e:
        print(f"Error running federated search example: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up
        import shutil
        shutil.rmtree(temp_dir)
        print("\nCleaned up temporary directory")


def resilient_operations_example():
    """Example showing resilient operations for distributed datasets."""

    # Import the resilient operations example module
    from ipfs_datasets_py.resilient_operations_example import resilient_operations_example as run_example

    # Run the example
    import asyncio
    asyncio.run(run_example())


def llm_reasoning_example():
    """Example showing the LLM reasoning tracer for GraphRAG."""

    # Import the LLM reasoning example module
    from ipfs_datasets_py.llm_reasoning_example import llm_reasoning_example as run_example

    # Run the example
    run_example()


def monitoring_example():
    """Example showing comprehensive monitoring and metrics collection capabilities."""

    # Import the monitoring example module
    from ipfs_datasets_py.monitoring_example import monitoring_example as run_example

    # Run the example
    run_example()


def admin_dashboard_example():
    """Example showing the admin dashboard for system monitoring and management."""

    # Import the admin dashboard example module
    from ipfs_datasets_py.admin_dashboard_example import admin_dashboard_example as run_example

    # Run the example
    run_example()


if __name__ == "__main__":
    # Uncomment to run the original example
    # original_example()

    # Uncomment to run the IPLD example
    # ipld_example()

    # Uncomment to run the GraphRAG example
    # graph_rag_example()

    # Uncomment to run the optimized GraphRAG example
    # optimized_graphrag_example()

    # Uncomment to run the advanced GraphRAG example
    # advanced_graphrag_example()

    # Uncomment to run the LLM-enhanced GraphRAG example
    # llm_graphrag_example()

    # Uncomment to run the resilient operations example
    # resilient_operations_example()

    # Uncomment to run the LLM reasoning tracer example
    # llm_reasoning_example()

    # Uncomment to run the monitoring example
    # monitoring_example()

    # Uncomment to run the admin dashboard example
    # admin_dashboard_example()

    # Run the sharded dataset example
    sharded_dataset_example()
