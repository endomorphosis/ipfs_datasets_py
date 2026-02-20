"""Query budget management for GraphRAG query optimization."""

from __future__ import annotations

from typing import Any, Dict, List


class QueryBudgetManager:
    """
    Manages query execution resources through adaptive budgeting.
    
    Features:
    - Dynamic resource allocation based on query priority and complexity
    - Early stopping based on result quality and diminishing returns
    - Adaptive computation budgeting based on query history
    - Progressive query expansion driven by initial results
    - Timeout management and cost estimation
    """
    
    def __init__(self, default_budget: Dict[str, float] = None):
        """
        Initialize the budget manager.
        
        Args:
            default_budget (Dict[str, float], optional): Default budget values for
                different resource types
        """
        self.default_budget = default_budget or {
            "vector_search_ms": 500.0,    # Vector search budget in milliseconds
            "graph_traversal_ms": 1000.0, # Graph traversal budget in milliseconds
            "ranking_ms": 200.0,          # Ranking budget in milliseconds
            "max_nodes": 1000,            # Maximum nodes to visit
            "max_edges": 5000,            # Maximum edges to traverse
            "timeout_ms": 2000.0          # Total query timeout in milliseconds
        }
        
        # Track budget consumption history
        self.budget_history = {
            "vector_search_ms": [],
            "graph_traversal_ms": [],
            "ranking_ms": [],
            "nodes_visited": [],
            "edges_traversed": []
        }
        
        self.current_consumption = {}
        
    def allocate_budget(self, query: Dict[str, Any], priority: str = "normal") -> Dict[str, float]:
        """
        Allocate budget for a query based on its characteristics and priority.
        
        Args:
            query (Dict): Query to execute
            priority (str): Priority level ("low", "normal", "high", "critical")
            
        Returns:
            Dict: Allocated budget
        """
        # Start with default budget
        budget = self.default_budget.copy()
        
        # Adjust based on query complexity
        query_complexity = self._estimate_complexity(query)
        complexity_multiplier = {
            "low": 0.7,
            "medium": 1.0,
            "high": 1.5,
            "very_high": 2.0
        }
        
        # Apply complexity multiplier
        for resource in budget:
            budget[resource] *= complexity_multiplier.get(query_complexity, 1.0)
            
        # Apply priority multiplier
        priority_multiplier = {
            "low": 0.5,
            "normal": 1.0,
            "high": 2.0,
            "critical": 5.0
        }
        
        for resource in budget:
            budget[resource] *= priority_multiplier.get(priority, 1.0)
            
        # Adjust based on historical consumption
        self._apply_historical_adjustment(budget)
        
        # Initialize consumption tracking
        self.current_consumption = {
            "vector_search_ms": 0.0,
            "graph_traversal_ms": 0.0,
            "ranking_ms": 0.0,
            "nodes_visited": 0,
            "edges_traversed": 0
        }
        
        return budget
        
    def track_consumption(self, resource: str, amount: float) -> None:
        """
        Track resource consumption during query execution.
        
        Args:
            resource (str): Resource type
            amount (float): Amount consumed
        """
        if resource in self.current_consumption:
            self.current_consumption[resource] += amount
            
    def is_budget_exceeded(self, resource: str) -> bool:
        """
        Check if a resource's budget has been exceeded.
        
        Args:
            resource (str): Resource type
            
        Returns:
            bool: Whether the budget has been exceeded
        """
        if resource not in self.current_consumption or resource not in self.default_budget:
            return False
        
        # Check if consumption exceeds budget
        return self.current_consumption[resource] > self.default_budget[resource]
    
    def record_completion(self, success: bool = True) -> None:
        """
        Record query completion and update budget history.
        
        Args:
            success (bool): Whether the query completed successfully
        """
        # Update budget history
        for resource, consumed in self.current_consumption.items():
            if resource in self.budget_history:
                self.budget_history[resource].append(consumed)
                
                # Keep history manageable
                if len(self.budget_history[resource]) > 100:
                    self.budget_history[resource] = self.budget_history[resource][-100:]
    
    def _estimate_complexity(self, query: Dict[str, Any]) -> str:
        """
        Estimate query complexity for budget allocation.
        
        Args:
            query (Dict): Query to analyze
            
        Returns:
            str: Complexity level
        """
        # Vector search complexity
        vector_params = query.get("vector_params", {})
        complexity_score = 0
        complexity_score += vector_params.get("top_k", 5) * 0.5
        
        # Traversal complexity
        traversal = query.get("traversal", {})
        max_depth = traversal.get("max_depth", 0)
        complexity_score += max_depth * 2  # Depth has exponential impact
        
        # Edge type complexity
        edge_types = traversal.get("edge_types", [])
        complexity_score += len(edge_types) * 0.3
        
        # Determine complexity level
        if complexity_score < 5:
            return "low"
        elif complexity_score < 10:
            return "medium"
        elif complexity_score < 20:
            return "high"
        else:
            return "very_high"
    
    def _apply_historical_adjustment(self, budget: Dict[str, float]) -> None:
        """
        Adjust budget based on historical consumption patterns.
        
        Args:
            budget (Dict): Budget to adjust
        """
        # For each resource, analyze historical usage
        for resource, history in self.budget_history.items():
            if not history:
                continue
                
            # Calculate average consumption
            avg_consumption = sum(history) / len(history)
            
            # Calculate 95th percentile (approximation)
            sorted_history = sorted(history)
            p95_idx = min(int(len(sorted_history) * 0.95), len(sorted_history) - 1)
            p95_consumption = sorted_history[p95_idx]
            
            # Adjust budget to be between average and 95th percentile
            if resource in budget:
                adjusted = (avg_consumption + p95_consumption) / 2
                # Ensure budget is not reduced below 80% of default
                min_budget = self.default_budget.get(resource, 0) * 0.8
                budget[resource] = max(adjusted, min_budget)
    
    def suggest_early_stopping(self, current_results: List[Dict[str, Any]], budget_consumed_ratio: float) -> bool:
        """
        Suggest whether to stop query execution early based on result quality
        and resource consumption.
        
        Args:
            current_results (List[Dict]): Current query results
            budget_consumed_ratio (float): Ratio of consumed budget
            
        Returns:
            bool: Whether to stop early
        """
        # If minimal results, don't stop
        if len(current_results) < 3:
            return False
            
        # If budget heavily consumed, check result quality
        if budget_consumed_ratio > 0.7:
            # Calculate average score of top 3 results
            if all("score" in r for r in current_results[:3]):
                avg_top_score = sum(r["score"] for r in current_results[:3]) / 3
                
                # If high quality results already found
                if avg_top_score > 0.85:
                    return True
                    
        # Check for score diminishing returns
        if len(current_results) > 5:
            # Check if scores are plateauing
            if all("score" in r for r in current_results):
                scores = [r["score"] for r in current_results]
                top_score = scores[0]
                fifth_score = scores[4]
                
                # If drop-off is significant
                if top_score - fifth_score > 0.3:
                    return True
        
        return False
        
    def get_current_consumption_report(self) -> Dict[str, Any]:
        """
        Get a report of current resource consumption.
        
        Returns:
            Dict: Resource consumption report
        """
        report = self.current_consumption.copy()
        
        # Add budget info
        report["budget"] = self.default_budget.copy()
        
        # Calculate consumption ratios
        report["ratios"] = {}
        for resource, consumed in self.current_consumption.items():
            if resource in self.default_budget and self.default_budget[resource] > 0:
                report["ratios"][resource] = consumed / self.default_budget[resource]
            else:
                report["ratios"][resource] = 0.0
                
        # Overall consumption
        if report["ratios"]:
            report["overall_consumption_ratio"] = sum(report["ratios"].values()) / len(report["ratios"])
        else:
            report["overall_consumption_ratio"] = 0.0
            
        return report
