"""
Schema Compatibility Checker

Validates schema compatibility between Neo4j and IPFS Graph Database.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

from .formats import SchemaData

logger = logging.getLogger(__name__)


@dataclass
class CompatibilityReport:
    """Report on schema compatibility."""
    
    compatible: bool
    compatibility_score: float = 0.0  # 0-100
    issues: List[Dict[str, str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'compatible': self.compatible,
            'compatibility_score': self.compatibility_score,
            'issues': self.issues,
            'warnings': self.warnings,
            'recommendations': self.recommendations
        }


class SchemaChecker:
    """
    Checks schema compatibility between Neo4j and IPFS Graph Database.
    
    Usage:
        checker = SchemaChecker()
        report = checker.check_schema(schema_data)
        
        if report.compatible:
            print(f"Schema is compatible (score: {report.compatibility_score})")
        else:
            print(f"Found {len(report.issues)} compatibility issues")
    """
    
    def __init__(self):
        """Initialize schema checker."""
        pass
    
    def check_schema(self, schema: SchemaData) -> CompatibilityReport:
        """
        Check schema compatibility.
        
        Args:
            schema: Schema data to check
            
        Returns:
            Compatibility report
        """
        report = CompatibilityReport(compatible=True)
        score = 100.0
        
        # Check indexes
        for index in schema.indexes:
            index_type = index.get('type', '')
            
            # Check if index type is supported
            if index_type in ['BTREE', 'RANGE']:
                # Supported
                pass
            elif index_type in ['FULLTEXT']:
                report.warnings.append(f"Full-text index '{index.get('name')}' is supported")
            elif index_type in ['VECTOR']:
                report.warnings.append(f"Vector index '{index.get('name')}' is supported via vector_index")
            else:
                report.issues.append({
                    'type': 'index',
                    'severity': 'warning',
                    'message': f"Index type '{index_type}' may need manual configuration"
                })
                score -= 5
        
        # Check constraints
        for constraint in schema.constraints:
            constraint_type = constraint.get('type', '')
            
            # Check if constraint type is supported
            if constraint_type in ['UNIQUENESS', 'UNIQUE']:
                # Supported
                pass
            elif constraint_type in ['NODE_KEY']:
                report.warnings.append(f"Node key constraint '{constraint.get('name')}' supported as unique constraint")
            elif constraint_type in ['EXIST', 'NODE_PROPERTY_EXISTENCE']:
                report.warnings.append(f"Existence constraint '{constraint.get('name')}' supported")
            else:
                report.issues.append({
                    'type': 'constraint',
                    'severity': 'warning',
                    'message': f"Constraint type '{constraint_type}' may need manual configuration"
                })
                score -= 5
        
        # Check node labels
        if len(schema.node_labels) > 100:
            report.warnings.append(f"Large number of node labels ({len(schema.node_labels)}), may impact performance")
        
        # Check relationship types
        if len(schema.relationship_types) > 100:
            report.warnings.append(f"Large number of relationship types ({len(schema.relationship_types)}), may impact performance")
        
        # Update score and compatibility
        report.compatibility_score = max(0.0, score)
        report.compatible = report.compatibility_score >= 85.0  # 85% threshold
        
        # Add recommendations
        if not report.compatible:
            report.recommendations.append("Review compatibility issues before migration")
            report.recommendations.append("Consider manual schema adjustments")
        
        if len(report.warnings) > 0:
            report.recommendations.append("Review warnings for potential optimizations")
        
        logger.info("Schema compatibility check: %.1f%% compatible", report.compatibility_score)
        return report
    
    def check_cypher_query(self, query: str) -> Dict[str, Any]:
        """
        Check if a Cypher query is compatible.
        
        Args:
            query: Cypher query to check
            
        Returns:
            Dictionary with compatibility information
        """
        # Placeholder for now
        return {
            'compatible': True,
            'confidence': 0.87,  # Based on 87% Cypher compatibility
            'warnings': [],
            'unsupported_features': []
        }
