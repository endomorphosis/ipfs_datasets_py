"""Unified Neurosymbolic GraphRAG Pipeline.

This module provides the NeurosymbolicGraphRAG class that integrates:
- TDFOL parsing and theorem proving (Phase 1-2)
- Neural-symbolic reasoning (Phase 3)
- Logic-enhanced GraphRAG (Phase 4)

Creating a complete end-to-end pipeline for legal/contractual document analysis.
"""

from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import logging

# Phase 1-2: TDFOL Core
from ipfs_datasets_py.logic.TDFOL import (
    parse_tdfol,
    TDFOLProver,
    Formula
)

# Phase 3: Neurosymbolic
try:
    from ipfs_datasets_py.logic.integration.neurosymbolic import (
        NeuralSymbolicCoordinator,
        ReasoningStrategy
    )
    HAS_NEUROSYMBOLIC = True
except ImportError:
    NeuralSymbolicCoordinator = None
    ReasoningStrategy = None
    HAS_NEUROSYMBOLIC = False

# Phase 4: Logic-Enhanced GraphRAG
from ipfs_datasets_py.rag import LogicEnhancedRAG, RAGQueryResult

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result from the complete neurosymbolic pipeline.
    
    Attributes:
        doc_id: Document identifier
        text: Original text
        entities: Extracted logical entities
        formulas: Parsed TDFOL formulas
        proven_theorems: List of proven theorems
        knowledge_graph_stats: Statistics about the knowledge graph
        rag_result: RAG query result
        reasoning_chain: Complete reasoning chain
        confidence: Overall confidence score
    """
    
    doc_id: str
    text: str
    entities: List[Any] = field(default_factory=list)
    formulas: List[Formula] = field(default_factory=list)
    proven_theorems: List[Tuple[str, Formula]] = field(default_factory=list)
    knowledge_graph_stats: Dict[str, int] = field(default_factory=dict)
    rag_result: Optional[RAGQueryResult] = None
    reasoning_chain: List[str] = field(default_factory=list)
    confidence: float = 0.0


class NeurosymbolicGraphRAG:
    """Unified neurosymbolic GraphRAG system.
    
    This class provides a complete pipeline that:
    1. Ingests text documents (contracts, legal documents, etc.)
    2. Extracts logical entities (obligations, permissions, etc.)
    3. Parses text into TDFOL formulas
    4. Proves theorems using symbolic + neural reasoning
    5. Builds logic-aware knowledge graphs
    6. Answers queries with explainable reasoning
    
    Example:
        >>> pipeline = NeurosymbolicGraphRAG()
        >>> result = pipeline.process_document("Alice must pay Bob", "contract1")
        >>> query_result = pipeline.query("What are Alice's obligations?")
    """
    
    def __init__(
        self,
        use_neural: bool = True,
        enable_proof_caching: bool = True,
        proving_strategy: str = "AUTO"
    ):
        """Initialize the neurosymbolic pipeline.
        
        Args:
            use_neural: Whether to use neural components
            enable_proof_caching: Whether to enable proof caching for performance
            proving_strategy: Strategy for theorem proving ("AUTO", "SYMBOLIC_ONLY", "NEURAL_ONLY", "HYBRID")
        """
        self.use_neural = use_neural and HAS_NEUROSYMBOLIC
        self.enable_proof_caching = enable_proof_caching
        self.proving_strategy = proving_strategy
        
        # Initialize components
        self._init_components()
        
        # Track processed documents
        self.documents: Dict[str, PipelineResult] = {}
        
        logger.info(
            f"NeurosymbolicGraphRAG initialized "
            f"(neural={self.use_neural}, caching={enable_proof_caching}, "
            f"strategy={proving_strategy})"
        )
    
    def _init_components(self) -> None:
        """Initialize all pipeline components."""
        # Phase 1-2: TDFOL prover
        self.prover = TDFOLProver()
        if self.enable_proof_caching:
            try:
                self.prover.enable_cache()
                logger.info("Proof caching enabled")
            except Exception as e:
                logger.warning(f"Could not enable proof caching: {e}")
        
        # Phase 3: Neurosymbolic reasoning
        if self.use_neural and HAS_NEUROSYMBOLIC:
            try:
                # Map string strategy to enum
                strategy_map = {
                    "AUTO": ReasoningStrategy.AUTO,
                    "SYMBOLIC_ONLY": ReasoningStrategy.SYMBOLIC_ONLY,
                    "NEURAL_ONLY": ReasoningStrategy.NEURAL_ONLY,
                    "HYBRID": ReasoningStrategy.HYBRID
                }
                strategy = strategy_map.get(self.proving_strategy, ReasoningStrategy.AUTO)
                
                self.reasoning_coordinator = NeuralSymbolicCoordinator(
                    default_strategy=strategy
                )
                logger.info("Neurosymbolic reasoning coordinator initialized")
            except Exception as e:
                logger.warning(f"Could not initialize reasoning coordinator: {e}")
                self.reasoning_coordinator = None
        else:
            self.reasoning_coordinator = None
        
        # Phase 4: Logic-enhanced RAG
        self.rag = LogicEnhancedRAG(use_neural=self.use_neural)
        logger.info("Logic-enhanced RAG initialized")
    
    def process_document(
        self,
        text: str,
        doc_id: str,
        auto_prove: bool = True
    ) -> PipelineResult:
        """Process a document through the complete pipeline.
        
        Args:
            text: Document text to process
            doc_id: Unique document identifier
            auto_prove: Whether to automatically prove extracted theorems
            
        Returns:
            PipelineResult with all extracted information
        """
        logger.info(f"Processing document: {doc_id}")
        
        reasoning_chain = []
        reasoning_chain.append(f"Processing document '{doc_id}'")
        
        # Step 1: Ingest into RAG (extracts entities, builds knowledge graph)
        logger.info("Step 1: Extracting entities and building knowledge graph")
        ingest_result = self.rag.ingest_document(text, doc_id)
        reasoning_chain.append(
            f"Extracted {ingest_result['entities_extracted']} entities, "
            f"created {ingest_result['nodes_created']} nodes"
        )
        
        # Step 2: Extract potential TDFOL formulas from entities
        logger.info("Step 2: Parsing TDFOL formulas")
        formulas = self._extract_formulas(text)
        reasoning_chain.append(f"Parsed {len(formulas)} TDFOL formulas")
        
        # Step 3: Prove theorems
        proven_theorems = []
        if auto_prove and formulas:
            logger.info("Step 3: Proving theorems")
            proven_theorems = self._prove_theorems(formulas, doc_id)
            reasoning_chain.append(f"Proved {len(proven_theorems)} theorems")
            
            # Add proven theorems to knowledge graph
            for name, formula in proven_theorems:
                self.rag.add_theorem(name, formula, auto_prove=False)
        
        # Step 4: Get knowledge graph statistics
        kg_stats = self.rag.get_stats()
        
        # Create result
        result = PipelineResult(
            doc_id=doc_id,
            text=text,
            entities=ingest_result['entities_extracted'],  # This is an integer
            formulas=formulas,
            proven_theorems=proven_theorems,
            knowledge_graph_stats=kg_stats,
            reasoning_chain=reasoning_chain,
            confidence=0.9 if ingest_result['is_consistent'] else 0.6
        )
        
        # Store result
        self.documents[doc_id] = result
        
        logger.info(f"Document '{doc_id}' processed successfully")
        return result
    
    def _extract_formulas(self, text: str) -> List[Formula]:
        """Extract TDFOL formulas from text.
        
        Args:
            text: Input text
            
        Returns:
            List of parsed TDFOL formulas
        """
        formulas = []
        
        # Simple heuristic: look for patterns that suggest logical formulas
        # This could be enhanced with more sophisticated NLP
        
        # Look for obligation patterns and convert to TDFOL
        import re
        
        # Pattern: "X must Y"
        must_pattern = r'(\w+)\s+must\s+(\w+)'
        for match in re.finditer(must_pattern, text, re.IGNORECASE):
            agent, action = match.groups()
            try:
                # O(predicate(agent))
                formula_str = f"O({action}({agent.lower()}))"
                formula = parse_tdfol(formula_str)
                formulas.append(formula)
            except Exception as e:
                logger.debug(f"Could not parse formula '{formula_str}': {e}")
        
        return formulas
    
    def _prove_theorems(
        self,
        formulas: List[Formula],
        doc_id: str
    ) -> List[Tuple[str, Formula]]:
        """Prove theorems from formulas.
        
        Args:
            formulas: List of formulas to prove
            doc_id: Document identifier for naming theorems
            
        Returns:
            List of (theorem_name, formula) tuples for proven theorems
        """
        proven = []
        
        for i, formula in enumerate(formulas):
            theorem_name = f"{doc_id}_theorem_{i}"
            
            try:
                if self.reasoning_coordinator:
                    # Use neurosymbolic reasoning
                    result = self.reasoning_coordinator.prove(
                        formula,
                        strategy=self.proving_strategy
                    )
                    if result.proven:
                        proven.append((theorem_name, formula))
                        logger.info(f"Proved theorem: {theorem_name}")
                else:
                    # Use symbolic prover only
                    result = self.prover.prove(formula)
                    if result.proven:
                        proven.append((theorem_name, formula))
                        logger.info(f"Proved theorem: {theorem_name}")
            except Exception as e:
                logger.debug(f"Could not prove {theorem_name}: {e}")
        
        return proven
    
    def query(
        self,
        query_text: str,
        use_inference: bool = True,
        top_k: int = 10
    ) -> RAGQueryResult:
        """Query the knowledge graph with logical reasoning.
        
        Args:
            query_text: Query text
            use_inference: Whether to use theorem-based inference
            top_k: Maximum number of results
            
        Returns:
            RAGQueryResult with reasoning chain
        """
        logger.info(f"Processing query: {query_text}")
        
        result = self.rag.query(query_text, use_inference=use_inference, top_k=top_k)
        
        logger.info(f"Query returned {len(result.relevant_nodes)} nodes")
        return result
    
    def get_document_summary(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get summary of a processed document.
        
        Args:
            doc_id: Document identifier
            
        Returns:
            Dictionary with document summary or None if not found
        """
        if doc_id not in self.documents:
            return None
        
        result = self.documents[doc_id]
        entities_count = result.entities if isinstance(result.entities, int) else len(result.entities)
        
        return {
            'doc_id': result.doc_id,
            'entities_count': entities_count,
            'formulas_count': len(result.formulas),
            'proven_theorems_count': len(result.proven_theorems),
            'confidence': result.confidence,
            'is_consistent': result.confidence > 0.7,
            'reasoning_steps': len(result.reasoning_chain)
        }
    
    def get_pipeline_stats(self) -> Dict[str, Any]:
        """Get overall pipeline statistics.
        
        Returns:
            Dictionary with pipeline statistics
        """
        total_entities = 0
        for d in self.documents.values():
            if isinstance(d.entities, int):
                total_entities += d.entities
            else:
                total_entities += len(d.entities)
        
        return {
            'documents_processed': len(self.documents),
            'total_entities': total_entities,
            'total_formulas': sum(len(d.formulas) for d in self.documents.values()),
            'total_proven_theorems': sum(len(d.proven_theorems) for d in self.documents.values()),
            'knowledge_graph': self.rag.get_stats(),
            'use_neural': self.use_neural,
            'proof_caching': self.enable_proof_caching
        }
    
    def export_knowledge_graph(self) -> Dict[str, Any]:
        """Export the complete knowledge graph.
        
        Returns:
            Dictionary representation of the knowledge graph
        """
        return self.rag.export_knowledge_graph()
    
    def check_consistency(self) -> Tuple[bool, List[str]]:
        """Check knowledge graph for logical consistency.
        
        Returns:
            Tuple of (is_consistent, list of inconsistencies)
        """
        return self.rag.check_consistency()
