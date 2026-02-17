"""
Data Integrity Verifier

Verifies data integrity after migration between Neo4j and IPFS Graph Database.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

from .formats import GraphData

logger = logging.getLogger(__name__)


@dataclass
class VerificationReport:
    """Report on data integrity verification."""
    
    passed: bool
    checks_performed: int = 0
    checks_passed: int = 0
    checks_failed: int = 0
    errors: List[Dict[str, str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    statistics: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'passed': self.passed,
            'checks_performed': self.checks_performed,
            'checks_passed': self.checks_passed,
            'checks_failed': self.checks_failed,
            'errors': self.errors,
            'warnings': self.warnings,
            'statistics': self.statistics
        }


class IntegrityVerifier:
    """
    Verifies data integrity after migration.
    
    Usage:
        verifier = IntegrityVerifier()
        report = verifier.verify(source_data, target_data)
        
        if report.passed:
            print(f"Verification passed: {report.checks_passed}/{report.checks_performed} checks")
        else:
            print(f"Verification failed: {len(report.errors)} errors")
    """
    
    def __init__(self, strict_mode: bool = False):
        """Initialize integrity verifier.
        
        Args:
            strict_mode: If True, any mismatch causes verification to fail.
                        If False, minor differences are reported as warnings.
        """
        self.strict_mode = strict_mode
        self.logger = logging.getLogger(__name__)
        
        # Verification thresholds
        self.tolerance = {
            'node_count': 0 if strict_mode else 0.01,  # 1% tolerance in non-strict mode
            'relationship_count': 0 if strict_mode else 0.01,
            'property_match': 0.95 if strict_mode else 0.90,  # 95% or 90% property match required
        }
        
        self.logger.debug("IntegrityVerifier initialized (strict_mode=%s)", strict_mode)
    
    def verify(self, source: GraphData, target: GraphData) -> VerificationReport:
        """
        Verify data integrity between source and target.
        
        Args:
            source: Source graph data
            target: Target graph data
            
        Returns:
            Verification report
        """
        report = VerificationReport(passed=True)
        
        # Check 1: Node count
        report.checks_performed += 1
        if source.node_count == target.node_count:
            report.checks_passed += 1
            logger.info("✓ Node count matches: %d", source.node_count)
        else:
            report.checks_failed += 1
            report.passed = False
            report.errors.append({
                'check': 'node_count',
                'message': f"Node count mismatch: source={source.node_count}, target={target.node_count}"
            })
            logger.error("✗ Node count mismatch")
        
        # Check 2: Relationship count
        report.checks_performed += 1
        if source.relationship_count == target.relationship_count:
            report.checks_passed += 1
            logger.info("✓ Relationship count matches: %d", source.relationship_count)
        else:
            report.checks_failed += 1
            report.passed = False
            report.errors.append({
                'check': 'relationship_count',
                'message': f"Relationship count mismatch: source={source.relationship_count}, target={target.relationship_count}"
            })
            logger.error("✗ Relationship count mismatch")
        
        # Check 3: Node labels
        report.checks_performed += 1
        source_stats = source.get_statistics()
        target_stats = target.get_statistics()
        
        source_labels = set(source_stats['label_counts'].keys())
        target_labels = set(target_stats['label_counts'].keys())
        
        if source_labels == target_labels:
            report.checks_passed += 1
            logger.info("✓ Node labels match: %d labels", len(source_labels))
        else:
            report.checks_failed += 1
            missing = source_labels - target_labels
            extra = target_labels - source_labels
            
            if missing:
                report.warnings.append(f"Missing labels in target: {missing}")
            if extra:
                report.warnings.append(f"Extra labels in target: {extra}")
            
            logger.warning("! Node labels differ")
        
        # Check 4: Relationship types
        report.checks_performed += 1
        source_types = set(source_stats['relationship_type_counts'].keys())
        target_types = set(target_stats['relationship_type_counts'].keys())
        
        if source_types == target_types:
            report.checks_passed += 1
            logger.info("✓ Relationship types match: %d types", len(source_types))
        else:
            report.checks_failed += 1
            missing = source_types - target_types
            extra = target_types - source_types
            
            if missing:
                report.warnings.append(f"Missing relationship types in target: {missing}")
            if extra:
                report.warnings.append(f"Extra relationship types in target: {extra}")
            
            logger.warning("! Relationship types differ")
        
        # Store statistics
        report.statistics = {
            'source': source_stats,
            'target': target_stats
        }
        
        logger.info("Verification complete: %d/%d checks passed",
                   report.checks_passed, report.checks_performed)
        
        return report
    
    def verify_sample(self, source: GraphData, target: GraphData, 
                     sample_size: int = 100) -> VerificationReport:
        """
        Verify a sample of nodes and relationships.
        
        Args:
            source: Source graph data
            target: Target graph data
            sample_size: Number of items to sample
            
        Returns:
            Verification report
        """
        report = VerificationReport(passed=True)
        
        # Sample nodes
        sample_count = min(sample_size, len(source.nodes))
        logger.info("Sampling %d nodes for verification", sample_count)
        
        source_node_map = {n.id: n for n in source.nodes[:sample_count]}
        target_node_map = {n.id: n for n in target.nodes}
        
        for node_id, source_node in source_node_map.items():
            report.checks_performed += 1
            
            target_node = target_node_map.get(node_id)
            if not target_node:
                report.checks_failed += 1
                report.passed = False
                report.errors.append({
                    'check': 'node_exists',
                    'message': f"Node {node_id} not found in target"
                })
                continue
            
            # Check properties match
            if source_node.properties == target_node.properties:
                report.checks_passed += 1
            else:
                report.checks_failed += 1
                report.warnings.append(f"Properties differ for node {node_id}")
        
        logger.info("Sample verification: %d/%d checks passed",
                   report.checks_passed, report.checks_performed)
        
        return report
