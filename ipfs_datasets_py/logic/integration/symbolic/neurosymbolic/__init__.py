"""
Neural-Symbolic Bridge Module (TDFOL Phase 3)

This module implements the neural-symbolic bridge, combining:
- Symbolic reasoning (TDFOL 40 rules + CEC 87 rules)
- Neural capabilities (embeddings, pattern matching, confidence scoring)
- Hybrid proof search (neural-guided symbolic proving)

Components:
- reasoning_coordinator.py: Main orchestrator for hybrid reasoning
- embedding_prover.py: Embedding-enhanced theorem retrieval
- neural_guided_search.py: Neural-guided proof search
- hybrid_confidence.py: Combined symbolic + neural confidence scoring

Phase: 3 (Weeks 5-6) - Neural-Symbolic Bridge
Status: IN PROGRESS
"""

from .reasoning_coordinator import NeuralSymbolicCoordinator
from .embedding_prover import EmbeddingEnhancedProver
from .hybrid_confidence import HybridConfidenceScorer

__all__ = [
    'NeuralSymbolicCoordinator',
    'EmbeddingEnhancedProver',
    'HybridConfidenceScorer',
]

__version__ = '0.3.0'  # Phase 3
