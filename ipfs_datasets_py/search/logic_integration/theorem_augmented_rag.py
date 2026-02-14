"""Theorem-augmented RAG for integrating proven theorems with knowledge graphs.

This module provides capabilities to augment a knowledge graph with
proven logical theorems from the TDFOL prover.
"""

from typing import List, Dict, Optional, Any
import logging

from ipfs_datasets_py.search.logic_integration.logic_aware_knowledge_graph import (
    LogicAwareKnowledgeGraph,
    LogicNode
)

logger = logging.getLogger(__name__)


class TheoremAugmentedRAG:
    """RAG system augmented with proven theorems.
    
    This class integrates the TDFOL theorem prover with a knowledge graph,
    allowing theorems to be stored alongside factual knowledge and used
    for logical inference during retrieval.
    
    Example:
        >>> rag = TheoremAugmentedRAG()
        >>> rag.add_theorem("modus_ponens", "P -> Q, P |- Q")
        >>> nodes = rag.query_with_theorems("What can we infer?")
    """
    
    def __init__(self, kg: Optional[LogicAwareKnowledgeGraph] = None):
        """Initialize theorem-augmented RAG.
        
        Args:
            kg: Optional existing knowledge graph to use
        """
        self.kg = kg if kg is not None else LogicAwareKnowledgeGraph()
        self.prover = None
        self._init_prover()
    
    def _init_prover(self) -> None:
        """Initialize the TDFOL prover if available."""
        try:
            from ipfs_datasets_py.logic.TDFOL.tdfol_prover import TDFOLProver
            self.prover = TDFOLProver()
            logger.info("TDFOL prover initialized successfully")
        except ImportError:
            logger.warning("TDFOL prover not available, theorem proving disabled")
    
    def add_theorem(
        self, 
        name: str, 
        formula: Any, 
        auto_prove: bool = False
    ) -> bool:
        """Add a theorem to the knowledge graph.
        
        Args:
            name: Theorem name
            formula: Theorem formula (string or Formula object)
            auto_prove: Whether to automatically prove the theorem
            
        Returns:
            True if theorem was proven (or auto_prove is False), False otherwise
        """
        proven = True
        
        if auto_prove and self.prover is not None:
            # Try to prove the theorem
            try:
                result = self.prover.prove(formula)
                proven = result.proven if hasattr(result, 'proven') else False
                logger.info(f"Theorem '{name}' proven: {proven}")
            except Exception as e:
                logger.warning(f"Failed to prove theorem '{name}': {e}")
                proven = False
        
        # Add to knowledge graph
        self.kg.add_theorem(name, formula, proven=proven)
        return proven
    
    def query_with_theorems(
        self, 
        query_text: str, 
        use_inference: bool = True
    ) -> List[LogicNode]:
        """Query the knowledge graph with theorem support.
        
        Args:
            query_text: Query text
            use_inference: Whether to use logical inference
            
        Returns:
            List of relevant nodes including theorems
        """
        # First, get basic query results
        results = self.kg.query(query_text)
        
        if use_inference:
            # Get related theorems for each result
            enriched_results = []
            for node in results:
                theorems = self.kg.get_related_theorems(node.id)
                if theorems:
                    # Add theorem information to node metadata
                    node.metadata['related_theorems'] = [
                        {'name': name, 'formula': str(formula)}
                        for name, formula in theorems
                    ]
                enriched_results.append(node)
            
            return enriched_results
        
        return results
    
    def prove_and_add(self, formula_str: str, name: Optional[str] = None) -> bool:
        """Prove a formula and add it as a theorem if successful.
        
        Args:
            formula_str: Formula string to prove
            name: Optional theorem name (auto-generated if None)
            
        Returns:
            True if proven and added, False otherwise
        """
        if self.prover is None:
            logger.warning("Prover not available")
            return False
        
        try:
            result = self.prover.prove(formula_str)
            proven = result.proven if hasattr(result, 'proven') else False
            
            if proven:
                if name is None:
                    name = f"theorem_{len(self.kg.theorems)}"
                self.kg.add_theorem(name, formula_str, proven=True)
                logger.info(f"Successfully proved and added theorem '{name}'")
                return True
        except Exception as e:
            logger.error(f"Failed to prove formula: {e}")
        
        return False
    
    def get_theorem_stats(self) -> Dict[str, int]:
        """Get statistics about theorems in the knowledge graph.
        
        Returns:
            Dictionary with theorem statistics
        """
        total = len(self.kg.theorems)
        proven = sum(1 for name in self.kg.theorems if 
                    self.kg.graph and 
                    self.kg.graph.has_node(f"theorem_{name}") and
                    self.kg.graph.nodes[f"theorem_{name}"].get('proven', False))
        
        return {
            'total_theorems': total,
            'proven_theorems': proven,
            'unproven_theorems': total - proven
        }
