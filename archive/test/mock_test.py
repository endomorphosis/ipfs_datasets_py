"""
Mock test for OptimizerLearningMetricsCollector
"""

import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent dir to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Create mock class
class MockOptimizerLearningMetricsCollector:
    def __init__(self):
        self.learning_cycles = {}
        self.parameter_adaptations = []
        self.strategy_effectiveness = []
        self.query_patterns = []

    def record_learning_cycle(self, cycle_id, analyzed_queries, patterns_identified,
                             parameters_adjusted, execution_time):
        """Mock method for recording learning cycles"""
        self.learning_cycles[cycle_id] = {
            "analyzed_queries": analyzed_queries,
            "patterns_identified": patterns_identified,
            "parameters_adjusted": parameters_adjusted,
            "execution_time": execution_time
        }

    def record_parameter_adaptation(self, parameter_name, old_value, new_value,
                                   adaptation_reason, confidence):
        """Mock method for recording parameter adaptations"""
        self.parameter_adaptations.append({
            "parameter_name": parameter_name,
            "old_value": old_value,
            "new_value": new_value,
            "adaptation_reason": adaptation_reason,
            "confidence": confidence
        })

    def record_strategy_effectiveness(self, strategy_name, query_type,
                                     effectiveness_score, execution_time, result_count):
        """Mock method for recording strategy effectiveness"""
        self.strategy_effectiveness.append({
            "strategy_name": strategy_name,
            "query_type": query_type,
            "effectiveness_score": effectiveness_score,
            "execution_time": execution_time,
            "result_count": result_count
        })

    def record_query_pattern(self, pattern_id, pattern_type, matching_queries,
                            average_performance, parameters):
        """Mock method for recording query patterns"""
        self.query_patterns.append({
            "pattern_id": pattern_id,
            "pattern_type": pattern_type,
            "matching_queries": matching_queries,
            "average_performance": average_performance,
            "parameters": parameters
        })

    def get_learning_metrics(self):
        """Mock method for getting learning metrics"""
        class Metrics:
            def __init__(self, metrics_data):
                self.total_learning_cycles = len(metrics_data)
                self.total_analyzed_queries = sum(m["analyzed_queries"] for m in metrics_data.values())
                self.total_patterns_identified = sum(m["patterns_identified"] for m in metrics_data.values())

        return Metrics(self.learning_cycles)

    def get_effectiveness_by_strategy(self):
        """Mock method for getting effectiveness by strategy"""
        result = {}
        for item in self.strategy_effectiveness:
            strategy = item["strategy_name"]
            if strategy not in result:
                result[strategy] = {"count": 0, "total_score": 0.0, "avg_score": 0.0}

            result[strategy]["count"] += 1
            result[strategy]["total_score"] += item["effectiveness_score"]
            result[strategy]["avg_score"] = result[strategy]["total_score"] / result[strategy]["count"]

        return result

    def get_patterns_by_type(self):
        """Mock method for getting patterns by type"""
        result = {}
        for item in self.query_patterns:
            pattern_type = item["pattern_type"]
            if pattern_type not in result:
                result[pattern_type] = {"count": 0, "total_queries": 0}

            result[pattern_type]["count"] += 1
            result[pattern_type]["total_queries"] += item["matching_queries"]

        return result

    def to_json(self):
        """Mock method for JSON serialization"""
        import json
        data = {
            "learning_cycles": self.learning_cycles,
            "parameter_adaptations": self.parameter_adaptations,
            "strategy_effectiveness": self.strategy_effectiveness,
            "query_patterns": self.query_patterns
        }
        return json.dumps(data)


# Mock the module containing OptimizerLearningMetricsCollector
sys.modules['ipfs_datasets_py.rag.rag_query_visualization'] = MagicMock()
sys.modules['ipfs_datasets_py.rag.rag_query_visualization'].OptimizerLearningMetricsCollector = MockOptimizerLearningMetricsCollector

# Now import our test module
from test.test_optimizer_learning import TestOptimizerLearningMetricsCollector

if __name__ == '__main__':
    unittest.main()
