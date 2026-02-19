"""Core Graph Engine.

This module contains the low-level graph CRUD + traversal engine used by the
Neo4j-compat driver surface and the query execution layer.

It was extracted from `core/query_executor.py` to keep that module focused on
query execution.

Design notes:
- `storage_backend` is optional; when absent the engine is in-memory only.
- Persistence uses the IPLD backend API (`store`, `retrieve_json`, `store_graph`,
  `retrieve_graph`) when available.
"""

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..neo4j_compat.types import Node, Relationship
from ..exceptions import StorageError

if TYPE_CHECKING:
    from ..storage.ipld_backend import IPLDBackend

logger = logging.getLogger(__name__)


class GraphEngine:
    """
    Core graph engine for node and relationship operations.

    Provides CRUD operations for graph elements and integrates with
    IPLD storage backend.

    Phase 1: Basic CRUD operations
    Phase 2: Path traversal and pattern matching
    Phase 3: Advanced algorithms (shortest path, centrality, etc.)
    """

    def __init__(self, storage_backend: Optional['IPLDBackend'] = None):
        """
        Initialize the graph engine.

        Args:
            storage_backend: IPLD storage backend
        """
        self.storage = storage_backend
        self._node_cache = {}
        self._relationship_cache = {}
        self._node_id_counter = 0
        self._rel_id_counter = 0
        self._enable_persistence = storage_backend is not None
        logger.debug("GraphEngine initialized (persistence=%s)", self._enable_persistence)

    def create_node(
        self,
        labels: Optional[List[str]] = None,
        properties: Optional[Dict[str, Any]] = None
    ) -> Node:
        """
        Create a new node.

        Args:
            labels: Node labels
            properties: Node properties

        Returns:
            Created Node object

        Example:
            node = engine.create_node(
                labels=["Person"],
                properties={"name": "Alice", "age": 30}
            )
        """
        # Generate node ID (Phase 1: simple counter, Phase 3: CID-based)
        node_id = self._generate_node_id()

        node = Node(
            node_id=node_id,
            labels=labels or [],
            properties=properties or {}
        )

        # Store in cache
        self._node_cache[node_id] = node

        # Persist to IPLD storage if available
        if self._enable_persistence and self.storage:
            try:
                node_data = {
                    "id": node_id,
                    "labels": labels or [],
                    "properties": properties or {}
                }
                cid = self.storage.store(node_data, pin=True, codec="dag-json")
                # Store CID mapping for retrieval
                self._node_cache[f"cid:{node_id}"] = cid
                logger.debug("Node %s persisted with CID: %s", node_id, cid)
            except StorageError as e:
                logger.warning("Failed to persist node %s: %s", node_id, e)

        logger.info("Created node: %s (labels=%s)", node_id, labels)
        return node

    def get_node(self, node_id: str) -> Optional[Node]:
        """
        Retrieve a node by ID.

        Args:
            node_id: Node identifier

        Returns:
            Node object or None if not found
        """
        # Check cache first
        if node_id in self._node_cache:
            logger.debug("Node found in cache: %s", node_id)
            return self._node_cache[node_id]

        # Load from IPLD storage if available
        if self._enable_persistence and self.storage:
            try:
                # Try to get CID for this node
                cid_key = f"cid:{node_id}"
                if cid_key in self._node_cache:
                    cid = self._node_cache[cid_key]
                    node_data = self.storage.retrieve_json(cid)
                    node = Node(
                        node_id=node_data["id"],
                        labels=node_data.get("labels", []),
                        properties=node_data.get("properties", {})
                    )
                    # Cache the loaded node
                    self._node_cache[node_id] = node
                    logger.debug("Node %s loaded from IPLD (CID: %s)", node_id, cid)
                    return node
            except (StorageError, KeyError, TypeError, ValueError) as e:
                logger.debug("Failed to load node %s from storage: %s", node_id, e)

        logger.debug("Node not found: %s", node_id)
        return None

    def update_node(
        self,
        node_id: str,
        properties: Dict[str, Any]
    ) -> Optional[Node]:
        """
        Update node properties.

        Args:
            node_id: Node identifier
            properties: Properties to update

        Returns:
            Updated Node object or None if not found
        """
        node = self.get_node(node_id)
        if not node:
            logger.warning("Node not found: %s", node_id)
            return None

        # Update properties
        node._properties.update(properties)
        self._node_cache[node_id] = node

        # Update in IPLD storage if persistence is enabled
        if self._enable_persistence and self.storage:
            try:
                node_data = {
                    "id": node_id,
                    "labels": node._labels,
                    "properties": node._properties
                }
                cid = self.storage.store(node_data, pin=True, codec="dag-json")
                self._node_cache[f"cid:{node_id}"] = cid
                logger.debug("Node %s updated in storage (CID: %s)", node_id, cid)
            except StorageError as e:
                logger.warning("Failed to update node %s in storage: %s", node_id, e)

        logger.info("Updated node: %s", node_id)
        return node

    def delete_node(self, node_id: str) -> bool:
        """
        Delete a node.

        Args:
            node_id: Node identifier

        Returns:
            True if deleted, False if not found
        """
        if node_id not in self._node_cache:
            return False

        del self._node_cache[node_id]

        # Also delete CID mapping if exists
        cid_key = f"cid:{node_id}"
        if cid_key in self._node_cache:
            del self._node_cache[cid_key]

        # Note: We don't unpin from IPFS as other references may exist
        logger.info("Deleted node: %s", node_id)
        return True

    def create_relationship(
        self,
        rel_type: str,
        start_node: str,
        end_node: str,
        properties: Optional[Dict[str, Any]] = None
    ) -> Relationship:
        """
        Create a relationship between two nodes.

        Args:
            rel_type: Relationship type
            start_node: Start node ID
            end_node: End node ID
            properties: Relationship properties

        Returns:
            Created Relationship object
        """
        rel_id = self._generate_relationship_id()

        relationship = Relationship(
            rel_id=rel_id,
            rel_type=rel_type,
            start_node=start_node,
            end_node=end_node,
            properties=properties or {}
        )

        self._relationship_cache[rel_id] = relationship

        # Persist to IPLD storage if available
        if self._enable_persistence and self.storage:
            try:
                rel_data = {
                    "id": rel_id,
                    "type": rel_type,
                    "start_node": start_node,
                    "end_node": end_node,
                    "properties": properties or {}
                }
                cid = self.storage.store(rel_data, pin=True, codec="dag-json")
                self._relationship_cache[f"cid:{rel_id}"] = cid
                logger.debug("Relationship %s persisted with CID: %s", rel_id, cid)
            except StorageError as e:
                logger.warning("Failed to persist relationship %s: %s", rel_id, e)

        logger.info("Created relationship: %s -%s-> %s", start_node, rel_type, end_node)
        return relationship

    def get_relationship(self, rel_id: str) -> Optional[Relationship]:
        """Retrieve a relationship by ID."""
        return self._relationship_cache.get(rel_id)

    def delete_relationship(self, rel_id: str) -> bool:
        """Delete a relationship."""
        if rel_id not in self._relationship_cache:
            return False

        del self._relationship_cache[rel_id]

        # Also delete CID mapping if exists
        cid_key = f"cid:{rel_id}"
        if cid_key in self._relationship_cache:
            del self._relationship_cache[cid_key]

        logger.info("Deleted relationship: %s", rel_id)
        return True

    def find_nodes(
        self,
        labels: Optional[List[str]] = None,
        properties: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Node]:
        """Find nodes matching criteria."""
        results = []

        # Filter only Node objects (exclude CID mappings)
        for key, value in self._node_cache.items():
            if key.startswith("cid:"):
                continue  # Skip CID mapping entries

            node = value
            if not isinstance(node, Node):
                continue

            # Check labels
            if labels and not any(label in node.labels for label in labels):
                continue

            # Check properties
            if properties:
                if not all(node.get(k) == v for k, v in properties.items()):
                    continue

            results.append(node)

            if limit and len(results) >= limit:
                break

        logger.debug("Found %d nodes", len(results))
        return results

    def _generate_node_id(self) -> str:
        """Generate a unique node ID."""
        import uuid
        return f"node-{uuid.uuid4().hex[:12]}"

    def _generate_relationship_id(self) -> str:
        """Generate a unique relationship ID."""
        import uuid
        return f"rel-{uuid.uuid4().hex[:12]}"

    def save_graph(self) -> Optional[str]:
        """Save the entire graph to IPLD storage."""
        if not self._enable_persistence or not self.storage:
            logger.warning("Graph persistence is disabled")
            return None

        try:
            # Extract nodes (exclude CID mappings)
            nodes = []
            for key, value in self._node_cache.items():
                if not key.startswith("cid:") and isinstance(value, Node):
                    nodes.append({
                        "id": value._id,
                        "labels": value._labels,
                        "properties": value._properties
                    })

            # Extract relationships (exclude CID mappings)
            relationships = []
            for key, value in self._relationship_cache.items():
                if not key.startswith("cid:") and isinstance(value, Relationship):
                    relationships.append({
                        "id": value._id,
                        "type": value._type,
                        "start_node": value._start_node,
                        "end_node": value._end_node,
                        "properties": value._properties
                    })

            cid = self.storage.store_graph(
                nodes=nodes,
                relationships=relationships,
                metadata={
                    "node_count": len(nodes),
                    "relationship_count": len(relationships),
                    "version": "1.0"
                }
            )

            logger.info(
                "Graph saved with CID: %s (%d nodes, %d relationships)",
                cid, len(nodes), len(relationships)
            )
            return cid
        except (StorageError, AttributeError, KeyError, TypeError, ValueError) as e:
            logger.error("Failed to save graph (%s): %s", type(e).__name__, e)
            return None

    def load_graph(self, root_cid: str) -> bool:
        """Load a graph from IPLD storage."""
        if not self._enable_persistence or not self.storage:
            logger.warning("Graph persistence is disabled")
            return False

        try:
            graph_data = self.storage.retrieve_graph(root_cid)

            # Clear current caches
            self._node_cache.clear()
            self._relationship_cache.clear()

            # Load nodes
            for node_data in graph_data.get("nodes", []):
                node = Node(
                    node_id=node_data["id"],
                    labels=node_data.get("labels", []),
                    properties=node_data.get("properties", {})
                )
                self._node_cache[node.id] = node

            # Load relationships
            for rel_data in graph_data.get("relationships", []):
                rel = Relationship(
                    rel_id=rel_data["id"],
                    rel_type=rel_data["type"],
                    start_node=rel_data["start_node"],
                    end_node=rel_data["end_node"],
                    properties=rel_data.get("properties", {})
                )
                self._relationship_cache[rel.id] = rel

            logger.info(
                "Graph loaded from CID: %s (%d nodes, %d relationships)",
                root_cid, len(self._node_cache), len(self._relationship_cache)
            )
            return True
        except (StorageError, AttributeError, KeyError, TypeError, ValueError) as e:
            logger.error(
                "Failed to load graph from %s (%s): %s",
                root_cid,
                type(e).__name__,
                e,
            )
            return False

    def get_relationships(
        self,
        node_id: str,
        direction: str = "out",
        rel_type: Optional[str] = None
    ) -> List[Relationship]:
        """Get relationships for a node with optional filtering."""
        results = []

        for key, rel in self._relationship_cache.items():
            if key.startswith("cid:"):
                continue  # Skip CID mappings

            if not isinstance(rel, Relationship):
                continue

            match = False
            if direction == "out" and rel._start_node == node_id:
                match = True
            elif direction == "in" and rel._end_node == node_id:
                match = True
            elif direction == "both":
                if rel._start_node == node_id or rel._end_node == node_id:
                    match = True

            if not match:
                continue

            if rel_type and rel._type != rel_type:
                continue

            results.append(rel)

        logger.debug(
            "Found %d relationships for node %s (direction=%s, type=%s)",
            len(results), node_id, direction, rel_type
        )
        return results

    def traverse_pattern(
        self,
        start_nodes: List[Node],
        pattern: List[Dict[str, Any]],
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Traverse a graph pattern starting from given nodes."""
        results = []

        for start_node in start_nodes:
            bindings = {"start": start_node}
            current_matches = [bindings]

            for i, step in enumerate(pattern):
                if "rel_type" in step:
                    new_matches = []
                    for match in current_matches:
                        last_var = list(match.keys())[-1]
                        last_node = match[last_var]

                        rels = self.get_relationships(
                            last_node.id,
                            direction=step.get("direction", "out"),
                            rel_type=step.get("rel_type")
                        )

                        for rel in rels:
                            if step.get("direction") == "in":
                                target_id = rel._start_node
                            else:
                                target_id = rel._end_node

                            target_node = self.get_node(target_id)
                            if not target_node:
                                continue

                            new_match = match.copy()
                            if "variable" in step:
                                new_match[step["variable"]] = rel

                            if i + 1 < len(pattern):
                                next_step = pattern[i + 1]
                                if "variable" in next_step:
                                    if "labels" in next_step:
                                        if not any(
                                            label in target_node.labels
                                            for label in next_step["labels"]
                                        ):
                                            continue
                                    new_match[next_step["variable"]] = target_node

                            new_matches.append(new_match)

                    current_matches = new_matches

            results.extend(current_matches)

            if limit and len(results) >= limit:
                results = results[:limit]
                break

        logger.debug("Pattern traversal found %d matches", len(results))
        return results

    def find_paths(
        self,
        start_node_id: str,
        end_node_id: str,
        max_depth: int = 5,
        rel_type: Optional[str] = None
    ) -> List[List[Relationship]]:
        """Find paths between two nodes."""
        paths = []

        queue = [(start_node_id, [], {start_node_id})]

        while queue:
            current_id, path, visited = queue.pop(0)

            if len(path) >= max_depth:
                continue

            rels = self.get_relationships(current_id, "out", rel_type)

            for rel in rels:
                target_id = rel._end_node

                if target_id == end_node_id:
                    paths.append(path + [rel])
                    continue

                if target_id in visited:
                    continue

                new_visited = visited.copy()
                new_visited.add(target_id)
                queue.append((target_id, path + [rel], new_visited))

        logger.debug(
            "Found %d paths from %s to %s",
            len(paths), start_node_id, end_node_id
        )
        return paths


__all__ = ["GraphEngine"]
