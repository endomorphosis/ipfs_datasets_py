"""Simple Knowledge Graph Example using New API"""

from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase
from ipfs_datasets_py.knowledge_graphs.core import GraphEngine


def main():
    print("=" * 60)
    print("Knowledge Graphs - Simple Example")
    print("=" * 60)
    print()
    
    driver = GraphDatabase.driver("ipfs://localhost:5001")
    engine = GraphEngine()
    
    print("Creating nodes...")
    alice = engine.create_node(labels=["Person"], properties={"name": "Alice", "age": 30})
    bob = engine.create_node(labels=["Person"], properties={"name": "Bob", "age": 25})
    
    print(f"✓ Created: {alice.get('name')}")
    print(f"✓ Created: {bob.get('name')}")
    print()
    
    print("Creating relationship...")
    rel = engine.create_relationship("KNOWS", alice.id, bob.id, {"since": 2020})
    print(f"✓ {alice.get('name')} KNOWS {bob.get('name')}")
    print()
    
    print("Querying nodes...")
    persons = engine.find_nodes(labels=["Person"])
    print(f"✓ Found {len(persons)} person nodes")
    print()
    
    driver.close()
    print("✅ Example completed successfully!")


if __name__ == "__main__":
    main()
