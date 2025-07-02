"""
LLM Reasoning Tracer for GraphRAG.

This module provides detailed tracing of reasoning steps in GraphRAG queries,
visualization and auditing of knowledge graph traversal, and explanation
generation for cross-document reasoning.

Key Components:
- ReasoningTrace: Captures and stores the reasoning steps in a structured format
- TracingManager: Manages and organizes reasoning traces
- WikipediaKnowledgeGraphTracer: Specialized tracer for Wikipedia knowledge graphs
- Visualization utilities for reasoning paths and knowledge graph traversal

NOTE: This is a mock implementation that defines the interfaces but leaves the
actual LLM integration for future work. A full implementation will be integrated
with the ipfs_accelerate_py package.

Future Implementation TODOs:
- Replace mock LLM calls with actual integration with ipfs_accelerate_py
- Implement more sophisticated reasoning tracing algorithms
- Add support for model-specific prompt formats
- Implement advanced visualization capabilities for reasoning paths
"""
import datetime
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Any, Optional


# Configure logging
logger = logging.getLogger(__name__)


class ReasoningNodeType(Enum):
    """Types of reasoning nodes in a reasoning trace."""
    QUERY = "query"
    DOCUMENT = "document"
    ENTITY = "entity"
    RELATIONSHIP = "relationship"
    INFERENCE = "inference"
    CONCLUSION = "conclusion"
    EVIDENCE = "evidence"
    CONTRADICTION = "contradiction"


@dataclass
class ReasoningNode:
    """A node in a reasoning trace."""
    node_id: str
    node_type: ReasoningNodeType
    content: str
    source: Optional[str] = None
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class ReasoningEdge:
    """An edge in a reasoning trace."""
    source_id: str
    target_id: str
    edge_type: str
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReasoningTrace:
    """A complete reasoning trace."""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    query: str = ""
    nodes: Dict[str, ReasoningNode] = field(default_factory=dict)
    edges: List[ReasoningEdge] = field(default_factory=list)
    root_node_id: Optional[str] = None
    conclusion_node_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def add_node(self, node_type: ReasoningNodeType, content: str,
                source: Optional[str] = None, confidence: float = 1.0,
                metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Add a node to the reasoning trace.

        Args:
            node_type: Type of the reasoning node
            content: Content of the node
            source: Optional source of the node
            confidence: Confidence score (0.0 to 1.0)
            metadata: Additional metadata

        Returns:
            str: ID of the created node
        """
        node_id = f"{node_type.value}_{len(self.nodes)}"
        self.nodes[node_id] = ReasoningNode(
            node_id=node_id,
            node_type=node_type,
            content=content,
            source=source,
            confidence=confidence,
            metadata=metadata if metadata is not None else {}
        )

        # If this is the first node and it's a query, set as root
        if len(self.nodes) == 1 and node_type == ReasoningNodeType.QUERY:
            self.root_node_id = node_id

        # If this is a conclusion node, add to conclusion list
        if node_type == ReasoningNodeType.CONCLUSION:
            self.conclusion_node_ids.append(node_id)

        return node_id

    def add_edge(self, source_id: str, target_id: str, edge_type: str,
                weight: float = 1.0, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Add an edge to the reasoning trace.

        Args:
            source_id: ID of the source node
            target_id: ID of the target node
            edge_type: Type of the edge
            weight: Weight of the edge (0.0 to 1.0)
            metadata: Additional metadata
        """
        if source_id not in self.nodes:
            raise ValueError(f"Source node {source_id} not found in trace")
        if target_id not in self.nodes:
            raise ValueError(f"Target node {target_id} not found in trace")

        self.edges.append(ReasoningEdge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            weight=weight,
            metadata=metadata or {}
        ))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "trace_id": self.trace_id,
            "query": self.query,
            "nodes": {k: asdict(v) for k, v in self.nodes.items()},
            "edges": [asdict(edge) for edge in self.edges],
            "root_node_id": self.root_node_id,
            "conclusion_node_ids": self.conclusion_node_ids,
            "metadata": self.metadata,
            "created_at": self.created_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ReasoningTrace':
        """Create from dictionary."""
        trace = cls(
            trace_id=data.get("trace_id", str(uuid.uuid4())),
            query=data.get("query", ""),
            root_node_id=data.get("root_node_id"),
            conclusion_node_ids=data.get("conclusion_node_ids", []),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time())
        )

        # Recreate nodes
        for node_id, node_data in data.get("nodes", {}).items():
            trace.nodes[node_id] = ReasoningNode(
                node_id=node_data["node_id"],
                node_type=ReasoningNodeType(node_data["node_type"]),
                content=node_data["content"],
                source=node_data.get("source"),
                confidence=node_data.get("confidence", 1.0),
                metadata=node_data.get("metadata", {}),
                created_at=node_data.get("created_at", time.time())
            )

        # Recreate edges
        for edge_data in data.get("edges", []):
            trace.edges.append(ReasoningEdge(
                source_id=edge_data["source_id"],
                target_id=edge_data["target_id"],
                edge_type=edge_data["edge_type"],
                weight=edge_data.get("weight", 1.0),
                metadata=edge_data.get("metadata", {})
            ))

        return trace

    def save(self, directory: str) -> str:
        """
        Save the reasoning trace to a file.

        Args:
            directory: Directory to save the trace

        Returns:
            str: Path to the saved file
        """
        os.makedirs(directory, exist_ok=True)

        filename = os.path.join(directory, f"{self.trace_id}.json")
        with open(filename, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

        return filename

    @classmethod
    def load(cls, filename: str) -> 'ReasoningTrace':
        """
        Load a reasoning trace from a file.

        Args:
            filename: Path to the trace file

        Returns:
            ReasoningTrace: The loaded trace
        """
        with open(filename, "r") as f:
            data = json.load(f)

        return cls.from_dict(data)

    def get_explanation(self, detail_level: str = "medium") -> str:
        """
        Generate a natural language explanation of the reasoning trace.

        Args:
            detail_level: Level of detail ("low", "medium", "high")

        Returns:
            str: Natural language explanation
        """
        # Mock implementation - future version will use LLM to generate
        # actual explanations based on the reasoning graph

        # Get conclusion nodes
        conclusions = [self.nodes[node_id] for node_id in self.conclusion_node_ids]

        if not conclusions:
            return "No conclusions were reached for this query."

        # Count evidence nodes
        evidence_count = sum(1 for node in self.nodes.values()
                          if node.node_type == ReasoningNodeType.EVIDENCE)

        # Simple templated explanation
        if detail_level == "low":
            conclusion_texts = [c.content for c in conclusions]
            return f"Based on {evidence_count} pieces of evidence, the system concluded: " + " ".join(conclusion_texts)

        elif detail_level == "medium":
            # Include some key evidence nodes
            evidence_nodes = [n for n in self.nodes.values() if n.node_type == ReasoningNodeType.EVIDENCE]
            evidence_sample = evidence_nodes[:3] if len(evidence_nodes) > 3 else evidence_nodes

            evidence_text = ""
            if evidence_sample:
                evidence_text = "Key evidence:\n" + "\n".join([f"- {e.content}" for e in evidence_sample])
                if len(evidence_nodes) > 3:
                    evidence_text += f"\n- and {len(evidence_nodes) - 3} more evidence points..."

            conclusion_texts = [c.content for c in conclusions]
            return f"Query: {self.query}\n\n{evidence_text}\n\nConclusions:\n" + "\n".join([f"- {c}" for c in conclusion_texts])

        elif detail_level == "high":
            # This would be much more detailed in a real implementation
            # with full reasoning path reconstruction
            steps = []
            steps.append(f"Query: {self.query}")
            steps.append(f"Evidence collected: {evidence_count} pieces")

            # Add inferences
            inferences = [n for n in self.nodes.values() if n.node_type == ReasoningNodeType.INFERENCE]
            if inferences:
                steps.append("Reasoning steps:")
                for i, inf in enumerate(inferences):
                    steps.append(f"  {i+1}. {inf.content}")

            # Add contradictions if any
            contradictions = [n for n in self.nodes.values() if n.node_type == ReasoningNodeType.CONTRADICTION]
            if contradictions:
                steps.append("Contradictions found:")
                for c in contradictions:
                    steps.append(f"  - {c.content}")

            # Add conclusions
            steps.append("Conclusions:")
            for c in conclusions:
                steps.append(f"  - {c.content} (confidence: {c.confidence:.2f})")

            return "\n".join(steps)

        else:
            return f"Unknown detail level: {detail_level}"


class LLMReasoningTracer:
    """
    Tracer for GraphRAG reasoning using LLMs.

    This is a mock implementation that defines the interfaces but leaves
    the actual LLM integration for future work.
    """

    def __init__(
        self,
        storage_dir: Optional[str] = None,
        llm_provider: str = "mock",
        llm_config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the reasoning tracer.

        Args:
            storage_dir: Directory for storing traces
            llm_provider: LLM provider to use ("mock" for now, future: "openai", "anthropic", etc.)
            llm_config: Configuration for the LLM provider
        """
        self.storage_dir = storage_dir or os.path.join(os.getcwd(), ".reasoning_traces")
        os.makedirs(self.storage_dir, exist_ok=True)

        self.llm_provider = llm_provider
        self.llm_config = llm_config or {}

        # This would be replaced with actual LLM clients in the future
        if llm_provider != "mock":
            logger.warning(f"LLM provider '{llm_provider}' not supported in mock implementation. Using mock provider.")

        # Store traces in memory for this mock implementation
        self.traces: Dict[str, ReasoningTrace] = {}

    def create_trace(self, query: str, metadata: Optional[Dict[str, Any]] = None) -> ReasoningTrace:
        """
        Create a new reasoning trace.

        Args:
            query: Query text
            metadata: Additional metadata

        Returns:
            ReasoningTrace: The created trace
        """
        trace = ReasoningTrace(query=query, metadata=metadata or {})

        # Add query node
        query_node_id = trace.add_node(
            node_type=ReasoningNodeType.QUERY,
            content=query
        )

        # Store trace
        self.traces[trace.trace_id] = trace

        return trace

    def trace_document_access(
        self,
        trace: ReasoningTrace,
        document_content: str,
        document_id: str,
        relevance_score: float,
        parent_node_id: Optional[str] = None
    ) -> str:
        """
        Trace access to a document during reasoning.

        Args:
            trace: The reasoning trace
            document_content: Content of the document
            document_id: Identifier for the document
            relevance_score: Relevance score to the query
            parent_node_id: ID of the node that led to this document

        Returns:
            str: ID of the created document node
        """
        # Create document node
        doc_node_id = trace.add_node(
            node_type=ReasoningNodeType.DOCUMENT,
            content=document_content[:500] + ("..." if len(document_content) > 500 else ""),
            source=document_id,
            confidence=relevance_score,
            metadata={"document_id": document_id, "relevance_score": relevance_score}
        )

        # Connect to parent if provided
        if parent_node_id:
            trace.add_edge(
                source_id=parent_node_id,
                target_id=doc_node_id,
                edge_type="retrieves",
                weight=relevance_score
            )
        # Otherwise connect to query node
        elif trace.root_node_id:
            trace.add_edge(
                source_id=trace.root_node_id,
                target_id=doc_node_id,
                edge_type="retrieves",
                weight=relevance_score
            )

        return doc_node_id

    def trace_entity_access(
        self,
        trace: ReasoningTrace,
        entity_name: str,
        entity_id: str,
        entity_type: str,
        relevance_score: float,
        parent_node_id: Optional[str] = None
    ) -> str:
        """
        Trace access to an entity during reasoning.

        Args:
            trace: The reasoning trace
            entity_name: Name of the entity
            entity_id: Identifier for the entity
            entity_type: Type of the entity
            relevance_score: Relevance score to the query
            parent_node_id: ID of the node that led to this entity

        Returns:
            str: ID of the created entity node
        """
        # Create entity node
        entity_node_id = trace.add_node(
            node_type=ReasoningNodeType.ENTITY,
            content=f"{entity_name} ({entity_type})",
            source=entity_id,
            confidence=relevance_score,
            metadata={
                "entity_id": entity_id,
                "entity_name": entity_name,
                "entity_type": entity_type,
                "relevance_score": relevance_score
            }
        )

        # Connect to parent if provided
        if parent_node_id:
            trace.add_edge(
                source_id=parent_node_id,
                target_id=entity_node_id,
                edge_type="identifies",
                weight=relevance_score
            )
        # Otherwise connect to query node
        elif trace.root_node_id:
            trace.add_edge(
                source_id=trace.root_node_id,
                target_id=entity_node_id,
                edge_type="identifies",
                weight=relevance_score
            )

        return entity_node_id

    def trace_relationship(
        self,
        trace: ReasoningTrace,
        source_node_id: str,
        target_node_id: str,
        relationship_type: str,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Trace a relationship between nodes during reasoning.

        Args:
            trace: The reasoning trace
            source_node_id: ID of the source node
            target_node_id: ID of the target node
            relationship_type: Type of the relationship
            confidence: Confidence in the relationship
            metadata: Additional metadata
        """
        trace.add_edge(
            source_id=source_node_id,
            target_id=target_node_id,
            edge_type=relationship_type,
            weight=confidence,
            metadata=metadata or {}
        )

    def trace_inference(
        self,
        trace: ReasoningTrace,
        inference_text: str,
        source_node_ids: List[str],
        confidence: float = 1.0
    ) -> str:
        """
        Trace an inference made during reasoning.

        Args:
            trace: The reasoning trace
            inference_text: Text of the inference
            source_node_ids: IDs of the nodes that led to this inference
            confidence: Confidence in the inference

        Returns:
            str: ID of the created inference node
        """
        # Create inference node
        inference_node_id = trace.add_node(
            node_type=ReasoningNodeType.INFERENCE,
            content=inference_text,
            confidence=confidence
        )

        # Connect from source nodes
        for source_id in source_node_ids:
            trace.add_edge(
                source_id=source_id,
                target_id=inference_node_id,
                edge_type="supports",
                weight=confidence
            )

        return inference_node_id

    def trace_evidence(
        self,
        trace: ReasoningTrace,
        evidence_text: str,
        source_node_id: str,
        confidence: float = 1.0
    ) -> str:
        """
        Trace evidence found during reasoning.

        Args:
            trace: The reasoning trace
            evidence_text: Text of the evidence
            source_node_id: ID of the node that provided this evidence
            confidence: Confidence in the evidence

        Returns:
            str: ID of the created evidence node
        """
        # Create evidence node
        evidence_node_id = trace.add_node(
            node_type=ReasoningNodeType.EVIDENCE,
            content=evidence_text,
            confidence=confidence
        )

        # Connect from source node
        trace.add_edge(
            source_id=source_node_id,
            target_id=evidence_node_id,
            edge_type="provides",
            weight=confidence
        )

        return evidence_node_id

    def trace_contradiction(
        self,
        trace: ReasoningTrace,
        contradiction_text: str,
        conflicting_node_ids: List[str],
        confidence: float = 1.0
    ) -> str:
        """
        Trace a contradiction found during reasoning.

        Args:
            trace: The reasoning trace
            contradiction_text: Text describing the contradiction
            conflicting_node_ids: IDs of the nodes in conflict
            confidence: Confidence in the contradiction

        Returns:
            str: ID of the created contradiction node
        """
        # Create contradiction node
        contradiction_node_id = trace.add_node(
            node_type=ReasoningNodeType.CONTRADICTION,
            content=contradiction_text,
            confidence=confidence
        )

        # Connect from conflicting nodes
        for node_id in conflicting_node_ids:
            trace.add_edge(
                source_id=node_id,
                target_id=contradiction_node_id,
                edge_type="conflicts",
                weight=confidence
            )

        return contradiction_node_id

    def trace_conclusion(
        self,
        trace: ReasoningTrace,
        conclusion_text: str,
        supporting_node_ids: List[str],
        confidence: float = 1.0
    ) -> str:
        """
        Trace a conclusion reached during reasoning.

        Args:
            trace: The reasoning trace
            conclusion_text: Text of the conclusion
            supporting_node_ids: IDs of the nodes that support this conclusion
            confidence: Confidence in the conclusion

        Returns:
            str: ID of the created conclusion node
        """
        # Create conclusion node
        conclusion_node_id = trace.add_node(
            node_type=ReasoningNodeType.CONCLUSION,
            content=conclusion_text,
            confidence=confidence
        )

        # Connect from supporting nodes
        for node_id in supporting_node_ids:
            trace.add_edge(
                source_id=node_id,
                target_id=conclusion_node_id,
                edge_type="supports",
                weight=confidence
            )

        return conclusion_node_id

    def analyze_trace(self, trace: ReasoningTrace) -> Dict[str, Any]:
        """
        Analyze a reasoning trace.

        Args:
            trace: The reasoning trace

        Returns:
            Dict[str, Any]: Analysis results
        """
        # This would be replaced with actual LLM-driven analysis in the future
        # For now, provide a simple summary analysis

        node_types = {}
        for node in trace.nodes.values():
            if node.node_type.value not in node_types:
                node_types[node.node_type.value] = 0
            node_types[node.node_type.value] += 1

        edge_types = {}
        for edge in trace.edges:
            if edge.edge_type not in edge_types:
                edge_types[edge.edge_type] = 0
            edge_types[edge.edge_type] += 1

        # Calculate average confidence
        confidences = [node.confidence for node in trace.nodes.values()]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0

        # Count evidence -> conclusion paths
        conclusion_nodes = [node_id for node_id in trace.nodes
                           if trace.nodes[node_id].node_type == ReasoningNodeType.CONCLUSION]

        evidence_to_conclusion_paths = 0
        if conclusion_nodes:
            for edge in trace.edges:
                if edge.target_id in conclusion_nodes and \
                   trace.nodes[edge.source_id].node_type == ReasoningNodeType.EVIDENCE:
                    evidence_to_conclusion_paths += 1

        return {
            "trace_id": trace.trace_id,
            "query": trace.query,
            "node_count": len(trace.nodes),
            "edge_count": len(trace.edges),
            "node_types": node_types,
            "edge_types": edge_types,
            "avg_confidence": avg_confidence,
            "conclusion_count": len(conclusion_nodes),
            "evidence_to_conclusion_paths": evidence_to_conclusion_paths,
            "reasoning_complexity": len(trace.edges) / len(trace.nodes) if trace.nodes else 0
        }

    def get_trace(self, trace_id: str) -> Optional[ReasoningTrace]:
        """
        Get a reasoning trace by ID.

        Args:
            trace_id: ID of the trace

        Returns:
            Optional[ReasoningTrace]: The trace or None if not found
        """
        return self.traces.get(trace_id)

    def save_trace(self, trace: ReasoningTrace) -> str:
        """
        Save a reasoning trace to disk.

        Args:
            trace: The reasoning trace

        Returns:
            str: Path to the saved file
        """
        return trace.save(self.storage_dir)

    def load_trace(self, trace_id: str) -> Optional[ReasoningTrace]:
        """
        Load a reasoning trace from disk.

        Args:
            trace_id: ID of the trace

        Returns:
            Optional[ReasoningTrace]: The loaded trace or None if not found
        """
        filename = os.path.join(self.storage_dir, f"{trace_id}.json")
        if not os.path.exists(filename):
            return None

        return ReasoningTrace.load(filename)

    def generate_explanation(
        self,
        trace: ReasoningTrace,
        detail_level: str = "medium",
        max_tokens: int = 1000
    ) -> str:
        """
        Generate a natural language explanation of a reasoning trace.

        Args:
            trace: The reasoning trace
            detail_level: Level of detail ("low", "medium", "high")
            max_tokens: Maximum number of tokens in the explanation

        Returns:
            str: Natural language explanation
        """
        # This would use actual LLM to generate explanations in the future
        return trace.get_explanation(detail_level)

    def export_visualization(
        self,
        trace: ReasoningTrace,
        output_format: str = "json",
        output_file: Optional[str] = None
    ) -> Any:
        """
        Export a visualization of a reasoning trace.

        Args:
            trace: The reasoning trace
            output_format: Format of the visualization
            output_file: Path to the output file

        Returns:
            Any: The visualization data or file path
        """
        if output_format == "json":
            data = trace.to_dict()

            if output_file:
                with open(output_file, "w") as f:
                    json.dump(data, f, indent=2)
                return output_file

            return data

        elif output_format == "d3":
            # Create D3.js compatible graph structure
            nodes = []
            for node_id, node in trace.nodes.items():
                nodes.append({
                    "id": node_id,
                    "type": node.node_type.value,
                    "label": node.content[:50] + ("..." if len(node.content) > 50 else ""),
                    "confidence": node.confidence,
                    "data": {
                        "content": node.content,
                        "source": node.source,
                        "metadata": node.metadata
                    }
                })

            links = []
            for edge in trace.edges:
                links.append({
                    "source": edge.source_id,
                    "target": edge.target_id,
                    "type": edge.edge_type,
                    "weight": edge.weight
                })

            d3_data = {
                "trace_id": trace.trace_id,
                "query": trace.query,
                "nodes": nodes,
                "links": links
            }

            if output_file:
                with open(output_file, "w") as f:
                    json.dump(d3_data, f, indent=2)
                return output_file

            return d3_data

        else:
            raise ValueError(f"Unsupported output format: {output_format}")


# Example usage (mock implementation)
def create_example_trace() -> ReasoningTrace:
    """Create an example reasoning trace for demonstration."""
    tracer = LLMReasoningTracer(storage_dir="/tmp/reasoning_traces")

    # Create a new trace for a query
    trace = tracer.create_trace(
        query="What are the environmental impacts of electric vehicles compared to gas vehicles?"
    )

    # Trace document access
    doc1_id = tracer.trace_document_access(
        trace=trace,
        document_content="Electric vehicles produce zero direct emissions, which significantly improves air quality in urban areas.",
        document_id="doc_ev_emissions",
        relevance_score=0.95
    )

    doc2_id = tracer.trace_document_access(
        trace=trace,
        document_content="Manufacturing batteries for electric vehicles has significant environmental impacts, including mining of rare earth metals and energy-intensive production processes.",
        document_id="doc_battery_production",
        relevance_score=0.87
    )

    doc3_id = tracer.trace_document_access(
        trace=trace,
        document_content="Gas vehicles emit carbon dioxide and other pollutants during operation, contributing to climate change and air pollution.",
        document_id="doc_gas_emissions",
        relevance_score=0.92
    )

    # Trace entity access
    entity1_id = tracer.trace_entity_access(
        trace=trace,
        entity_name="Electric Vehicle",
        entity_id="entity_ev",
        entity_type="Vehicle",
        relevance_score=0.98
    )

    entity2_id = tracer.trace_entity_access(
        trace=trace,
        entity_name="Gas Vehicle",
        entity_id="entity_gas",
        entity_type="Vehicle",
        relevance_score=0.96
    )

    entity3_id = tracer.trace_entity_access(
        trace=trace,
        entity_name="Lithium-ion Battery",
        entity_id="entity_battery",
        entity_type="Component",
        relevance_score=0.85,
        parent_node_id=entity1_id
    )

    # Trace relationships
    tracer.trace_relationship(
        trace=trace,
        source_node_id=entity1_id,
        target_node_id=entity3_id,
        relationship_type="contains",
        confidence=0.99
    )

    # Trace evidence
    evidence1_id = tracer.trace_evidence(
        trace=trace,
        evidence_text="Electric vehicles produce zero direct emissions during operation",
        source_node_id=doc1_id,
        confidence=0.95
    )

    evidence2_id = tracer.trace_evidence(
        trace=trace,
        evidence_text="Battery production involves environmental impacts from mining and manufacturing",
        source_node_id=doc2_id,
        confidence=0.9
    )

    evidence3_id = tracer.trace_evidence(
        trace=trace,
        evidence_text="Gas vehicles produce CO2 and other pollutants during operation",
        source_node_id=doc3_id,
        confidence=0.95
    )

    # Trace inferences
    inference1_id = tracer.trace_inference(
        trace=trace,
        inference_text="Electric vehicles have better operational environmental impact than gas vehicles",
        source_node_ids=[evidence1_id, evidence3_id],
        confidence=0.92
    )

    inference2_id = tracer.trace_inference(
        trace=trace,
        inference_text="Electric vehicles have manufacturing impacts that gas vehicles don't have",
        source_node_ids=[evidence2_id],
        confidence=0.85
    )

    # Trace conclusions
    conclusion_id = tracer.trace_conclusion(
        trace=trace,
        conclusion_text="Electric vehicles typically have lower overall environmental impact than gas vehicles over their lifetime, despite higher manufacturing impacts.",
        supporting_node_ids=[inference1_id, inference2_id],
        confidence=0.88
    )

    # Save the trace
    tracer.save_trace(trace)

    return trace


class WikipediaKnowledgeGraphTracer:
    """
    Specialized tracer for Wikipedia knowledge graph extraction and validation.

    This class provides tracing capabilities specific to Wikipedia knowledge graphs,
    with support for:
    - Entity extraction tracing
    - Relationship extraction tracing
    - SPARQL validation against Wikidata
    - Extraction confidence scoring
    - Visualization of extraction steps
    """

    def __init__(self, enable_wikidata_validation: bool = True):
        """
        Initialize Wikipedia knowledge graph tracer.

        Args:
            enable_wikidata_validation: Whether to enable validation against Wikidata
        """
        self.enable_wikidata_validation = enable_wikidata_validation
        self.traces = {}
        self.validation_results = {}

    def create_extraction_trace(self, document_title: str, text_snippet: str) -> str:
        """
        Create a new extraction trace for a Wikipedia document.

        Args:
            document_title: Title of the Wikipedia document
            text_snippet: Text snippet being processed

        Returns:
            Trace ID
        """
        trace_id = f"wiki-kg-{uuid.uuid4()}"

        trace = ReasoningTrace(
            trace_id=trace_id,
            query=f"Extract knowledge graph from: {document_title}",
            timestamp=datetime.datetime.now(),
            metadata={
                "document_title": document_title,
                "text_length": len(text_snippet),
                "extraction_source": "wikipedia"
            }
        )

        # Add initial nodes for document
        root_node_id = trace.add_node(
            node_type=ReasoningNodeType.DOCUMENT,
            content=f"Document: {document_title}",
            metadata={"title": document_title}
        )

        text_node_id = trace.add_node(
            node_type=ReasoningNodeType.EVIDENCE,
            content=f"Text snippet: {text_snippet[:100]}...",
            metadata={"full_text": text_snippet}
        )

        # Link text to document
        trace.add_edge(text_node_id, root_node_id, "extracted_from")

        # Store the trace
        self.traces[trace_id] = trace
        return trace_id

    def trace_entity_extraction(
        self,
        trace_id: str,
        entity_text: str,
        entity_type: str,
        confidence: float,
        source_text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Trace the extraction of an entity.

        Args:
            trace_id: Trace ID
            entity_text: Extracted entity text
            entity_type: Type of the entity
            confidence: Extraction confidence score
            source_text: Source text from which the entity was extracted
            metadata: Additional entity metadata

        Returns:
            Node ID of the entity in the trace
        """
        if trace_id not in self.traces:
            raise ValueError(f"Trace {trace_id} not found")

        trace = self.traces[trace_id]

        # Create entity node
        entity_node_id = trace.add_node(
            node_type=ReasoningNodeType.ENTITY,
            content=f"Entity: {entity_text} (Type: {entity_type})",
            metadata={
                "entity_text": entity_text,
                "entity_type": entity_type,
                "confidence": confidence,
                "source_text": source_text,
                **(metadata or {})
            }
        )

        # Find the text evidence node to link to
        # In a real implementation, we would find the specific text node
        # that contains this entity
        text_nodes = [n for n in trace.nodes if n.node_type == ReasoningNodeType.EVIDENCE]
        if text_nodes:
            trace.add_edge(entity_node_id, text_nodes[0].node_id, "extracted_from")

        return entity_node_id

    def trace_relationship_extraction(
        self,
        trace_id: str,
        relationship_type: str,
        source_entity_id: str,
        target_entity_id: str,
        confidence: float,
        source_text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Trace the extraction of a relationship.

        Args:
            trace_id: Trace ID
            relationship_type: Type of the relationship
            source_entity_id: Source entity node ID
            target_entity_id: Target entity node ID
            confidence: Extraction confidence score
            source_text: Source text from which the relationship was extracted
            metadata: Additional relationship metadata

        Returns:
            Node ID of the relationship in the trace
        """
        if trace_id not in self.traces:
            raise ValueError(f"Trace {trace_id} not found")

        trace = self.traces[trace_id]

        # Create relationship node
        relationship_node_id = trace.add_node(
            node_type=ReasoningNodeType.RELATIONSHIP,
            content=f"Relationship: {relationship_type}",
            metadata={
                "relationship_type": relationship_type,
                "confidence": confidence,
                "source_text": source_text,
                **(metadata or {})
            }
        )

        # Link to source and target entities
        trace.add_edge(relationship_node_id, source_entity_id, "source_entity")
        trace.add_edge(relationship_node_id, target_entity_id, "target_entity")

        # Find the text evidence node to link to
        text_nodes = [n for n in trace.nodes if n.node_type == ReasoningNodeType.EVIDENCE]
        if text_nodes:
            trace.add_edge(relationship_node_id, text_nodes[0].node_id, "extracted_from")

        return relationship_node_id

    def trace_wikidata_validation(
        self,
        trace_id: str,
        entity_id: str,
        wikidata_id: Optional[str],
        validation_result: bool,
        confidence: float,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Trace the validation of an entity against Wikidata.

        Args:
            trace_id: Trace ID
            entity_id: Entity node ID to validate
            wikidata_id: Wikidata ID if found, None otherwise
            validation_result: Whether validation succeeded
            confidence: Validation confidence score
            metadata: Additional validation metadata

        Returns:
            Node ID of the validation node in the trace
        """
        if trace_id not in self.traces:
            raise ValueError(f"Trace {trace_id} not found")

        trace = self.traces[trace_id]

        # Create validation node
        base_metadata = {
            "wikidata_id": wikidata_id,
            "validation_result": validation_result,
            "confidence": confidence,
        }
        if metadata:
            base_metadata.update(metadata)

        validation_node_id = trace.add_node(
            node_type=ReasoningNodeType.INFERENCE,
            content=f"Wikidata validation: {'Successful' if validation_result else 'Failed'}",
            metadata=base_metadata
        )

        # Link to entity
        trace.add_edge(validation_node_id, entity_id, "validates")

        # Store validation result
        if trace_id not in self.validation_results:
            self.validation_results[trace_id] = {}
        self.validation_results[trace_id][entity_id] = {
            "wikidata_id": wikidata_id,
            "validation_result": validation_result,
            "confidence": confidence
        }

        return validation_node_id

    def trace_sparql_validation(
        self,
        trace_id: str,
        relationship_id: str,
        sparql_query: str,
        validation_result: bool,
        confidence: float,
        result_count: int,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Trace the validation of a relationship using SPARQL against Wikidata.

        Args:
            trace_id: Trace ID
            relationship_id: Relationship node ID to validate
            sparql_query: SPARQL query used for validation
            validation_result: Whether validation succeeded
            confidence: Validation confidence score
            result_count: Number of results returned by the query
            metadata: Additional validation metadata

        Returns:
            Node ID of the validation node in the trace
        """
        if trace_id not in self.traces:
            raise ValueError(f"Trace {trace_id} not found")

        trace = self.traces[trace_id]

        # Create validation node
        validation_node_id = trace.add_node(
            node_type=ReasoningNodeType.INFERENCE,
            content=f"SPARQL validation: {'Successful' if validation_result else 'Failed'}",
            metadata={
                "sparql_query": sparql_query,
                "validation_result": validation_result,
                "confidence": confidence,
                "result_count": result_count,
                **(metadata or {})
            }
        )

        # Link to relationship
        trace.add_edge(validation_node_id, relationship_id, "validates")

        # Store validation result
        if trace_id not in self.validation_results:
            self.validation_results[trace_id] = {}
        self.validation_results[trace_id][relationship_id] = {
            "sparql_query": sparql_query,
            "validation_result": validation_result,
            "confidence": confidence,
            "result_count": result_count
        }

        return validation_node_id

    def trace_integration_decision(
        self,
        trace_id: str,
        entity_or_relation_id: str,
        decision: str,
        confidence: float,
        reasoning: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Trace a decision about integrating an entity or relationship.

        Args:
            trace_id: Trace ID
            entity_or_relation_id: Entity or relationship node ID
            decision: Integration decision (include, exclude, modify)
            confidence: Decision confidence score
            reasoning: Reasoning behind the decision
            metadata: Additional decision metadata

        Returns:
            Node ID of the decision node in the trace
        """
        if trace_id not in self.traces:
            raise ValueError(f"Trace {trace_id} not found")

        trace = self.traces[trace_id]

        # Create decision node
        decision_node_id = trace.add_node(
            node_type=ReasoningNodeType.CONCLUSION,
            content=f"Integration decision: {decision}",
            metadata={
                "decision": decision,
                "confidence": confidence,
                "reasoning": reasoning,
                **(metadata or {})
            }
        )

        # Link to entity or relationship
        trace.add_edge(decision_node_id, entity_or_relation_id, "decides_on")

        return decision_node_id

    def get_trace(self, trace_id: str) -> Optional[ReasoningTrace]:
        """
        Get a trace by ID.

        Args:
            trace_id: Trace ID

        Returns:
            Trace or None if not found
        """
        return self.traces.get(trace_id)

    def get_trace_visualization(
        self,
        trace_id: str,
        format: str = "text"
    ) -> str:
        """
        Get a visualization of the trace.

        Args:
            trace_id: Trace ID
            format: Visualization format (text, html, mermaid)

        Returns:
            Visualization string
        """
        if trace_id not in self.traces:
            return f"Trace {trace_id} not found"

        trace = self.traces[trace_id]

        if format == "text":
            return self._get_text_visualization(trace)
        elif format == "mermaid":
            return self._get_mermaid_visualization(trace)
        elif format == "html":
            return self._get_html_visualization(trace)
        else:
            return f"Unsupported format: {format}"

    def _get_text_visualization(self, trace: ReasoningTrace) -> str:
        """
        Get a text visualization of the trace.

        Args:
            trace: Reasoning trace

        Returns:
            Text visualization
        """
        lines = [
            f"Knowledge Graph Extraction Trace: {trace.trace_id}",
            f"Document: {trace.metadata.get('document_title', 'Unknown')}",
            "-" * 80
        ]

        # Add entity nodes
        entity_nodes = [n for n in trace.nodes.values() if n.node_type == ReasoningNodeType.ENTITY]
        lines.append(f"Entities ({len(entity_nodes)}):")
        for node in entity_nodes:
            metadata = node.metadata or {}
            confidence = metadata.get("confidence", "Unknown")
            entity_type = metadata.get("entity_type", "Unknown")
            lines.append(f"  - {metadata.get('entity_text', 'Unknown')} "
                       f"(Type: {entity_type}, Confidence: {confidence:.2f})")

        # Add relationship nodes
        relationship_nodes = [n for n in trace.nodes.values() if n.node_type == ReasoningNodeType.RELATIONSHIP]
        lines.append(f"\nRelationships ({len(relationship_nodes)}):")
        for node in relationship_nodes:
            metadata = node.metadata or {}
            confidence = metadata.get("confidence", "Unknown")
            rel_type = metadata.get("relationship_type", "Unknown")

            # Find source and target entities
            source_edges = [e for e in trace.edges if e.target_id == node.node_id and e.edge_type == "source_entity"]
            target_edges = [e for e in trace.edges if e.target_id == node.node_id and e.edge_type == "target_entity"]

            source_entity = "Unknown"
            target_entity = "Unknown"

            if source_edges and source_edges[0].source_id in trace.nodes:
                source_node = trace.nodes[source_edges[0].source_id]
                source_entity = source_node.metadata.get("entity_text", "Unknown") if source_node.metadata else "Unknown"

            if target_edges and target_edges[0].source_id in trace.nodes:
                target_node = trace.nodes[target_edges[0].source_id]
                target_entity = target_node.metadata.get("entity_text", "Unknown") if target_node.metadata else "Unknown"

            lines.append(f"  - {source_entity} --[{rel_type}]--> {target_entity} "
                       f"(Confidence: {confidence:.2f})")

        # Add validation results
        validation_nodes = [n for n in trace.nodes.values() if
                          n.node_type == ReasoningNodeType.INFERENCE and
                          (n.content.startswith("Wikidata validation") or
                           n.content.startswith("SPARQL validation"))]

        if validation_nodes:
            lines.append(f"\nValidation Results ({len(validation_nodes)}):")
            for node in validation_nodes:
                metadata = node.metadata or {}
                result = "✓" if metadata.get("validation_result", False) else "✗"
                confidence = metadata.get("confidence", "Unknown")

                if "wikidata_id" in metadata:
                    # Entity validation
                    wikidata_id = metadata.get("wikidata_id", "Not found")
                    lines.append(f"  - Entity Validation: {result} "
                               f"(Wikidata ID: {wikidata_id}, Confidence: {confidence:.2f})")
                else:
                    # Relationship validation
                    lines.append(f"  - Relationship Validation: {result} "
                               f"(Results: {metadata.get('result_count', 0)}, "
                               f"Confidence: {confidence:.2f})")

        return "\n".join(lines)

    def _get_mermaid_visualization(self, trace: ReasoningTrace) -> str:
        """
        Get a Mermaid diagram visualization of the trace.

        Args:
            trace: Reasoning trace

        Returns:
            Mermaid diagram code
        """
        mermaid_lines = [
            "```mermaid",
            "graph TD",
            f"    title[\"Knowledge Graph Extraction: {trace.metadata.get('document_title', 'Unknown')}\"]",
            "    style title fill:#f9f,stroke:#333,stroke-width:2px"
        ]

        # Add nodes
        for node in trace.nodes:
            node_style = ""
            label = ""

            if node.node_type == ReasoningNodeType.DOCUMENT:
                node_style = "style document fill:#d4f1f9,stroke:#333,stroke-width:1px"
                label = f"\"{node.content}\""
                mermaid_lines.append(f"    document{node.node_id}[{label}]")
                mermaid_lines.append(f"    {node_style}")

            elif node.node_type == ReasoningNodeType.ENTITY:
                metadata = node.metadata or {}
                confidence = metadata.get("confidence", 0)
                entity_text = metadata.get("entity_text", "Unknown")
                entity_type = metadata.get("entity_type", "Unknown")

                # Color based on confidence
                fill_color = "#d5f5e3" if confidence >= 0.7 else "#fcf3cf"
                node_style = f"style entity{node.node_id} fill:{fill_color},stroke:#333,stroke-width:1px"

                label = f"\"{entity_text}<br/>(Type: {entity_type})\""
                mermaid_lines.append(f"    entity{node.node_id}[{label}]")
                mermaid_lines.append(f"    {node_style}")

            elif node.node_type == ReasoningNodeType.RELATIONSHIP:
                metadata = node.metadata or {}
                confidence = metadata.get("confidence", 0)
                rel_type = metadata.get("relationship_type", "Unknown")

                # Color based on confidence
                fill_color = "#d5f5e3" if confidence >= 0.7 else "#fcf3cf"
                node_style = f"style relation{node.node_id} fill:{fill_color},stroke:#333,stroke-width:1px"

                label = f"\"{rel_type}\""
                mermaid_lines.append(f"    relation{node.node_id}({label})")
                mermaid_lines.append(f"    {node_style}")

            elif node.node_type == ReasoningNodeType.INFERENCE and "validation" in node.content.lower():
                metadata = node.metadata or {}
                result = metadata.get("validation_result", False)

                # Color based on validation result
                fill_color = "#d5f5e3" if result else "#f5b7b1"
                node_style = f"style validation{node.node_id} fill:{fill_color},stroke:#333,stroke-width:1px"

                if "wikidata_id" in metadata:
                    wikidata_id = metadata.get("wikidata_id", "Not found")
                    label = f"\"Wikidata: {wikidata_id if wikidata_id else 'Not found'}\""
                else:
                    result_count = metadata.get("result_count", 0)
                    label = f"\"SPARQL: {result_count} results\""

                mermaid_lines.append(f"    validation{node.node_id}[{label}]")
                mermaid_lines.append(f"    {node_style}")

        # Add edges
        for edge in trace.edges:
            source_id = edge.source_id
            target_id = edge.target_id
            label = edge.edge_type

            # Determine node types for source and target
            source_node = trace.nodes.get(source_id)
            target_node = trace.nodes.get(target_id)

            if not source_node or not target_node:
                continue

            source_prefix = self._get_node_prefix(source_node.node_type)
            target_prefix = self._get_node_prefix(target_node.node_type)

            mermaid_lines.append(f"    {source_prefix}{source_id} -->|{label}| {target_prefix}{target_id}")

        mermaid_lines.append("```")
        return "\n".join(mermaid_lines)

    def _get_node_prefix(self, node_type: ReasoningNodeType) -> str:
        """Get prefix for node ID based on type."""
        if node_type == ReasoningNodeType.DOCUMENT:
            return "document"
        elif node_type == ReasoningNodeType.ENTITY:
            return "entity"
        elif node_type == ReasoningNodeType.RELATIONSHIP:
            return "relation"
        elif node_type == ReasoningNodeType.INFERENCE:
            return "validation"
        elif node_type == ReasoningNodeType.EVIDENCE:
            return "evidence"
        elif node_type == ReasoningNodeType.CONCLUSION:
            return "decision"
        else:
            return "node"

    def _get_html_visualization(self, trace: ReasoningTrace) -> str:
        """
        Get an HTML visualization of the trace.

        Args:
            trace: Reasoning trace

        Returns:
            HTML visualization
        """
        # In a real implementation, this would generate an interactive HTML
        # visualization. For the mock implementation, we'll return a basic HTML
        # representation based on the text visualization.
        text_viz = self._get_text_visualization(trace)
        html_lines = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            "    <title>Knowledge Graph Extraction Trace</title>",
            "    <style>",
            "        body { font-family: Arial, sans-serif; margin: 20px; }",
            "        pre { background-color: #f5f5f5; padding: 10px; border-radius: 5px; }",
            "        h1 { color: #333366; }",
            "        .entity { color: #006600; }",
            "        .relationship { color: #0000cc; }",
            "        .validation { color: #cc0000; }",
            "    </style>",
            "</head>",
            "<body>",
            f"    <h1>Knowledge Graph Extraction Trace: {trace.trace_id}</h1>",
            f"    <h2>Document: {trace.metadata.get('document_title', 'Unknown')}</h2>",
            "    <pre>"
        ]

        # Add text visualization with some HTML formatting
        for line in text_viz.split('\n'):
            if "Entities" in line or "Relationships" in line or "Validation Results" in line:
                line = f"<b>{line}</b>"
            elif line.strip().startswith("-") and "Type:" in line:
                line = f"<span class='entity'>{line}</span>"
            elif line.strip().startswith("-") and "--[" in line:
                line = f"<span class='relationship'>{line}</span>"
            elif line.strip().startswith("-") and "Validation:" in line:
                line = f"<span class='validation'>{line}</span>"

            html_lines.append(f"        {line}")

        html_lines.extend([
            "    </pre>",
            "</body>",
            "</html>"
        ])

        return "\n".join(html_lines)

    def export_trace(self, trace_id: str, format: str = "json") -> str:
        """
        Export a trace to a specific format.

        Args:
            trace_id: Trace ID
            format: Export format (json, mermaid, html)

        Returns:
            Exported trace
        """
        if trace_id not in self.traces:
            return f"Trace {trace_id} not found"

        trace = self.traces[trace_id]

        if format == "json":
            return json.dumps(trace.to_dict(), indent=2)
        elif format == "mermaid":
            return self._get_mermaid_visualization(trace)
        elif format == "html":
            return self._get_html_visualization(trace)
        else:
            return f"Unsupported format: {format}"


# This is a mock implementation that will be replaced with actual LLM integration in the future
if __name__ == "__main__":
    # Create an example trace
    example_trace = create_example_trace()

    # Print an explanation
    print(example_trace.get_explanation("high"))

    # Create a Wikipedia knowledge graph extraction trace example
    wiki_tracer = WikipediaKnowledgeGraphTracer()
    trace_id = wiki_tracer.create_extraction_trace(
        document_title="Artificial Intelligence",
        text_snippet="Artificial Intelligence (AI) is intelligence demonstrated by machines. " +
                   "Machine learning is a subset of AI that focuses on data and algorithms."
    )

    # Trace entity extraction
    entity1_id = wiki_tracer.trace_entity_extraction(
        trace_id=trace_id,
        entity_text="Artificial Intelligence",
        entity_type="concept",
        confidence=0.95,
        source_text="Artificial Intelligence (AI) is intelligence demonstrated by machines."
    )

    entity2_id = wiki_tracer.trace_entity_extraction(
        trace_id=trace_id,
        entity_text="Machine learning",
        entity_type="concept",
        confidence=0.92,
        source_text="Machine learning is a subset of AI that focuses on data and algorithms."
    )

    # Trace relationship extraction
    relation_id = wiki_tracer.trace_relationship_extraction(
        trace_id=trace_id,
        relationship_type="is_subset_of",
        source_entity_id=entity2_id,
        target_entity_id=entity1_id,
        confidence=0.88,
        source_text="Machine learning is a subset of AI that focuses on data and algorithms."
    )

    # Trace validation
    wiki_tracer.trace_wikidata_validation(
        trace_id=trace_id,
        entity_id=entity1_id,
        wikidata_id="Q11660",
        validation_result=True,
        confidence=0.95
    )

    wiki_tracer.trace_wikidata_validation(
        trace_id=trace_id,
        entity_id=entity2_id,
        wikidata_id="Q2539",
        validation_result=True,
        confidence=0.93
    )

    # Print the visualization
    print("\nWikipedia Knowledge Graph Extraction Trace:")
    print(wiki_tracer.get_trace_visualization(trace_id))

    # This is where actual LLM integration would occur in the future
    print("\nNOTE: This is a mock implementation. Actual LLM integration will be implemented")
    print("in the future with the ipfs_accelerate_py package.")
