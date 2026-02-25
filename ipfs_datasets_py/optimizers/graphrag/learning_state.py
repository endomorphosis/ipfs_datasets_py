"""Learning state management for query optimization.

This module handles persistent learning state, query fingerprinting,
and failure tracking for adaptive query optimization.
"""

import json
import os
import datetime
import logging
from typing import Dict, Any, List, Optional

logging.basicConfig(level=logging.INFO)


class LearningStateManager:
    """Manages learning state, persistence, and query fingerprinting.
    
    Tracks query statistics, failure patterns, and entity importance
    scores to enable adaptive optimization over time.
    """

    def __init__(self):
        """Initialize learning state manager."""
        self._learning_enabled = False
        self._learning_cycle = 50
        self._learning_parameters: Dict[str, Any] = {}
        self._traversal_stats = {
            "paths_explored": [],
            "path_scores": {},
            "entity_frequency": {},
            "entity_connectivity": {},
            "relation_usefulness": {}
        }
        self._entity_importance_cache: Dict[str, float] = {}
        self._query_stats: List[Dict] = []
        self._failure_count = 0
        self._max_consecutive_failures = 3

    def enable_statistical_learning(
        self,
        enabled: bool = True,
        learning_cycle: int = 50
    ) -> None:
        """Enable or disable statistical learning from past query performance.
        
        When enabled, the optimizer automatically analyzes past query performance
        and adjusts optimization parameters to improve future query results.
        
        Args:
            enabled: Whether to enable statistical learning
            learning_cycle: Number of recent queries to analyze for learning
        """
        self._learning_enabled = enabled
        self._learning_cycle = learning_cycle
        
        # Initialize entity importance cache if not exists
        if not self._entity_importance_cache:
            self._entity_importance_cache = {}

    def check_learning_cycle(self) -> None:
        """Check if it's time to trigger a statistical learning cycle.
        
        This method should be called at the beginning of query optimization to 
        determine if enough queries have been processed since the last
        learning cycle to trigger a new learning cycle.
        
        Implements a circuit breaker pattern to disable learning after repeated failures.
        """
        if not self._learning_enabled:
            return
        
        try:
            # Check if we've processed enough queries for a learning cycle
            if len(self._query_stats) >= self._learning_cycle:
                self._apply_learning_hook()
                
                # Reset stats after learning cycle
                self._query_stats = self._query_stats[-self._learning_cycle:]
        
        except (TypeError, AttributeError, ValueError) as e:
            # Log the error but don't break the query
            # TypeError: _query_stats not a sequence
            # AttributeError: _learning_enabled or _learning_cycle missing
            # ValueError: numeric comparison issues
            logging.debug(f"Learning cycle check failed: {e}")
            
            # Track consecutive failures
            self._failure_count += 1
            if self._failure_count >= self._max_consecutive_failures:
                logging.warning("Learning disabled due to repeated failures")
                self._learning_enabled = False
                self._failure_count = 0

    def save_learning_state(self, filepath: Optional[str] = None) -> Optional[str]:
        """Save the current learning state to disk.
        
        Args:
            filepath: Path to save the state file. If None, uses default location.
        
        Returns:
            str: Path where the state was saved, or None if not saved
        """
        if not self._learning_enabled:
            return None
        
        # Use default path if none provided
        if filepath is None:
            return None
        
        # Create state object
        state = {
            "learning_enabled": self._learning_enabled,
            "learning_cycle": self._learning_cycle,
            "learning_parameters": self._learning_parameters,
            "traversal_stats": self._traversal_stats,
            "entity_importance_cache": self._entity_importance_cache,
            "failure_count": self._failure_count,
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        # Ensure directory exists
        try:
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        except (OSError, ValueError):
            return None
        
        try:
            # Make state serializable (handle numpy arrays if present)
            serializable_state = self._make_json_serializable(state)
            
            # Save state to file
            with open(filepath, 'w') as f:
                json.dump(serializable_state, f, indent=2)
            
            logging.info(f"Learning state saved to {filepath}")
            return filepath
        
        except (TypeError, ValueError, RuntimeError, OSError, json.JSONDecodeError) as e:
            # Handle serialization errors gracefully
            logging.error(f"Error saving learning state: {e}")
            return None

    def load_learning_state(self, filepath: Optional[str] = None) -> bool:
        """Load learning state from disk.
        
        Args:
            filepath: Path to the state file. If None, uses default location.
        
        Returns:
            bool: True if state was loaded successfully, False otherwise
        """
        if filepath is None:
            return False
        
        # Check if file exists
        if not os.path.exists(filepath):
            return False
        
        try:
            # Load state from file
            with open(filepath, 'r') as f:
                state = json.load(f)
            
            # Set learning parameters
            self._learning_enabled = state.get("learning_enabled", False)
            self._learning_cycle = state.get("learning_cycle", 50)
            
            # Set learning parameters if present
            if "learning_parameters" in state:
                self._learning_parameters = state["learning_parameters"]
            
            # Set traversal stats if present
            if "traversal_stats" in state:
                self._traversal_stats = state["traversal_stats"]
            
            # Set entity importance cache if present
            if "entity_importance_cache" in state:
                self._entity_importance_cache = state["entity_importance_cache"]
            
            # Set failure count
            self._failure_count = state.get("failure_count", 0)
            
            logging.info(f"Learning state loaded from {filepath}")
            return True
        
        except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
            logging.error(f"Error loading learning state: {e}")
            return False

    def record_query_performance(
        self,
        query: Dict[str, Any],
        success_score: float
    ) -> None:
        """Record query performance for learning.
        
        Args:
            query: The query that was executed
            success_score: Success score (0.0-1.0) for this query
        """
        if not self._learning_enabled:
            return
        
        try:
            fingerprint = self.create_query_fingerprint(query)
            
            stat = {
                "fingerprint": fingerprint,
                "success_score": success_score,
                "timestamp": datetime.datetime.now().isoformat()
            }
            
            self._query_stats.append(stat)
            
            # Reset failure count on success
            if success_score > 0.7:
                self._failure_count = 0
        
        except (AttributeError, KeyError, TypeError, ValueError, RuntimeError) as e:
            logging.debug(f"Error recording query performance: {e}")

    def record_path_performance(
        self,
        path: List[str],
        success_score: float,
        relation_types: Optional[List[str]] = None
    ) -> None:
        """Record traversal path performance.
        
        Args:
            path: Traversal path (list of entity IDs)
            success_score: Success score for this path
            relation_types: Relation types used in traversal
        """
        if not self._learning_enabled:
            return
        
        try:
            # Record path
            self._traversal_stats["paths_explored"].append(path)
            
            # Record path score
            path_key = "|".join(path)
            self._traversal_stats["path_scores"][path_key] = success_score
            
            # Update relation usefulness if provided
            if relation_types:
                for rel_type in relation_types:
                    current = self._traversal_stats["relation_usefulness"].get(rel_type, 0.5)
                    # Exponential moving average
                    alpha = 0.3
                    new_score = alpha * success_score + (1 - alpha) * current
                    self._traversal_stats["relation_usefulness"][rel_type] = new_score
        
        except (AttributeError, KeyError, TypeError, ValueError, RuntimeError) as e:
            logging.debug(f"Error recording path performance: {e}")

    def create_query_fingerprint(self, query: Dict[str, Any]) -> str:
        """Create a fingerprint for query deduplication and caching.
        
        Args:
            query: Query dictionary
            
        Returns:
            str: Query fingerprint/hash
        """
        parts = []
        
        # Vector query signature (ignore actual vector data)
        if "query_vector" in query:
            vector_len = len(query.get("query_vector", []))
            parts.append(f"vec_{vector_len}")
            parts.append(f"vr_{query.get('max_vector_results', 5)}")
        
        # Text query signature
        query_text = query.get("query", query.get("query_text", ""))
        if query_text:
            # Use hash for text to keep signature small
            text_hash = hash(str(query_text)[:100]) % (2**31)
            parts.append(f"txt_{text_hash}")
        
        # Traversal parameters
        traversal = query.get("traversal", {})
        if isinstance(traversal, dict):
            parts.append(f"td_{traversal.get('max_depth', 2)}")
            edge_types = traversal.get("edge_types", [])
            if edge_types:
                parts.append(f"et_{len(edge_types)}")
        
        # Priority
        priority = query.get("priority", "normal")
        parts.append(f"p_{priority}")
        
        return "|".join(parts)

    def detect_fingerprint_collision(self, fingerprint: str) -> bool:
        """Check if a query fingerprint has been seen before.
        
        Args:
            fingerprint: Query fingerprint
            
        Returns:
            bool: True if fingerprint seen before, False otherwise
        """
        for stat in self._query_stats:
            if stat.get("fingerprint") == fingerprint:
                return True
        return False

    def get_similar_queries(self, fingerprint: str, count: int = 5) -> List[Dict]:
        """Get recent similar queries based on fingerprint.
        
        Args:
            fingerprint: Query fingerprint to search for
            count: Maximum number of queries to return
            
        Returns:
            list: Recent similar queries
        """
        similar = []
        for stat in reversed(self._query_stats[-100:]):  # Check last 100 queries
            if stat.get("fingerprint") == fingerprint:
                similar.append(stat)
                if len(similar) >= count:
                    break
        return similar

    def _apply_learning_hook(self) -> None:
        """Apply learning from accumulated statistics.
        
        Analyzes recent query statistics and adjusts parameters
        for future optimization.
        """
        if not self._learning_enabled or len(self._query_stats) < self._learning_cycle:
            return
        
        try:
            # Analyze recent statistics
            recent_stats = self._query_stats[-self._learning_cycle:]
            
            # Calculate average success rate
            success_scores = [s.get("success_score", 0.5) for s in recent_stats]
            avg_success = sum(success_scores) / len(success_scores) if success_scores else 0.5
            
            # Adjust learning parameters based on results
            self._learning_parameters["recent_avg_success"] = avg_success
            self._learning_parameters["last_learning_cycle"] = datetime.datetime.now().isoformat()
            
            logging.info(f"Learning hook applied: avg_success={avg_success:.2f}")
        
        except (TypeError, ValueError, AttributeError) as e:
            logging.debug(f"Error in learning hook: {e}")

    @staticmethod
    def _make_json_serializable(obj: Any) -> Any:
        """Convert object to JSON-serializable format.
        
        Args:
            obj: Object to convert
            
        Returns:
            JSON-serializable version of object
        """
        if isinstance(obj, dict):
            return {k: LearningStateManager._make_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [LearningStateManager._make_json_serializable(item) for item in obj]
        elif isinstance(obj, (int, float, str, bool, type(None))):
            return obj
        else:
            # For numpy arrays and other non-standard types
            return str(obj)

    def get_learning_stats(self) -> Dict[str, Any]:
        """Get current learning statistics.
        
        Returns:
            dict: Learning statistics
        """
        return {
            "enabled": self._learning_enabled,
            "cycle": self._learning_cycle,
            "parameters": self._learning_parameters,
            "query_count": len(self._query_stats),
            "failure_count": self._failure_count,
            "relation_usefulness": self._traversal_stats.get("relation_usefulness", {})
        }

    def reset_learning_state(self) -> None:
        """Reset all learning state."""
        self._learning_enabled = False
        self._learning_cycle = 50
        self._learning_parameters = {}
        self._traversal_stats = {
            "paths_explored": [],
            "path_scores": {},
            "entity_frequency": {},
            "entity_connectivity": {},
            "relation_usefulness": {}
        }
        self._entity_importance_cache = {}
        self._query_stats = []
        self._failure_count = 0
