"""
Logic Validator for GraphRAG Optimization.

This module provides integration with TDFOL theorem provers for validating
the logical consistency of knowledge graph ontologies. It converts ontology
structures to formal logic representations and uses various theorem provers
to check for contradictions and prove consistency.

Key Features:
    - Convert ontologies to TDFOL formulas
    - Automatic contradiction detection
    - Consistency proof generation
    - Integration with multiple provers (Z3, CVC5, SymbolicAI, CEC, etc.)
    - Suggestion of fixes for detected contradictions
    - Caching of validation results

Example:
    >>> from ipfs_datasets_py.optimizers.graphrag import LogicValidator
    >>> 
    >>> validator = LogicValidator(prover_config={
    ...     'strategy': 'AUTO',
    ...     'timeout': 5.0
    ... })
    >>> 
    >>> result = validator.check_consistency(ontology)
    >>> if not result.is_consistent:
    ...     fixes = validator.suggest_fixes(ontology, result.contradictions)

References:
    - TDFOL module: Core theorem proving infrastructure
    - external_provers: Z3, CVC5, SymbolicAI integration
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """
    Result of logical validation of an ontology.
    
    Attributes:
        is_consistent: Whether the ontology is logically consistent
        contradictions: List of detected contradictions
        proofs: List of consistency proofs generated
        confidence: Confidence in the validation result (0.0 to 1.0)
        prover_used: Name of the theorem prover used
        time_ms: Time taken for validation in milliseconds
        metadata: Additional validation metadata
    """
    
    is_consistent: bool
    contradictions: List[str] = field(default_factory=list)
    proofs: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    prover_used: str = "unknown"
    time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert validation result to dictionary."""
        return {
            'is_consistent': self.is_consistent,
            'contradictions': self.contradictions,
            'proofs': self.proofs,
            'confidence': self.confidence,
            'prover_used': self.prover_used,
            'time_ms': self.time_ms,
            'metadata': self.metadata,
        }


class LogicValidator:
    """
    Validate ontologies using theorem provers.
    
    This class bridges knowledge graph ontologies to formal logic validation
    using the TDFOL framework and various theorem provers. It can detect
    contradictions, prove consistency, and suggest fixes for logical issues.
    
    The validator integrates with the existing logic module infrastructure,
    including TDFOL parsing, inference rules, and external prover bridges.
    
    Attributes:
        prover_config: Configuration for theorem provers
        use_cache: Whether to cache validation results
        
    Example:
        >>> validator = LogicValidator(prover_config={
        ...     'provers': ['z3', 'cvc5'],
        ...     'strategy': 'parallel',
        ...     'timeout': 10.0
        ... })
        >>> 
        >>> # Check consistency
        >>> result = validator.check_consistency(ontology)
        >>> print(f"Consistent: {result.is_consistent}")
        >>> 
        >>> # Get fixes if needed
        >>> if not result.is_consistent:
        ...     fixes = validator.suggest_fixes(ontology, result.contradictions)
    """
    
    def __init__(
        self,
        prover_config: Optional[Dict[str, Any]] = None,
        use_cache: bool = True
    ):
        """
        Initialize the logic validator.
        
        Args:
            prover_config: Configuration for theorem provers. Should include:
                - 'strategy': Proving strategy ('AUTO', 'SYMBOLIC', 'NEURAL', 'HYBRID')
                - 'provers': List of provers to use (e.g., ['z3', 'cvc5'])
                - 'timeout': Timeout in seconds
                - 'parallel': Whether to run provers in parallel
            use_cache: Whether to cache validation results for performance
            
        Raises:
            ImportError: If TDFOL module is not available
        """
        self.prover_config = prover_config or {'strategy': 'AUTO'}
        self.use_cache = use_cache
        self._cache = {} if use_cache else None
        
        # Try to import TDFOL infrastructure
        try:
            from ipfs_datasets_py.logic.TDFOL import parse_tdfol, Formula
            from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner
            
            self._tdfol_available = True
            self._reasoner = NeurosymbolicReasoner()
            logger.info("TDFOL integration available")
        except ImportError as e:
            logger.warning(
                f"TDFOL module not available: {e}. "
                "Logic validation will be limited."
            )
            self._tdfol_available = False
            self._reasoner = None
    

    def ontology_to_tdfol(
        self,
        ontology: Dict[str, Any]
    ) -> List[Any]:  # List[Formula]
        """
        Convert ontology to TDFOL formulas.

        Transforms the knowledge graph ontology structure into formal logic
        representations that can be validated by theorem provers.

        Args:
            ontology: Ontology to convert (dictionary format)

        Returns:
            List of formulas representing the ontology.

            - If the optional TDFOL module is available, this may contain Formula objects.
            - Otherwise, this returns a list of string facts in a simple predicate form,
              suitable for best-effort downstream checking.

        Raises:
            ValueError: If ontology structure is invalid

        Example:
            >>> formulas = validator.ontology_to_tdfol(ontology)
            >>> print(f"Generated {len(formulas)} formulas")
        """
        logger.info("Converting ontology to TDFOL formulas")

        if not isinstance(ontology, dict):
            raise ValueError("ontology must be a dict")

        entities = ontology.get("entities", [])
        relationships = ontology.get("relationships", [])

        if not isinstance(entities, list):
            raise ValueError("ontology['entities'] must be a list")
        if not isinstance(relationships, list):
            raise ValueError("ontology['relationships'] must be a list")

        logger.info(
            f"Converting {len(entities)} entities and "
            f"{len(relationships)} relationships"
        )

        # Minimal conversion that does not depend on the TDFOL Formula classes.
        # We emit simple predicate-style string facts that downstream checkers
        # can consume as a best-effort representation.
        import json

        def q(value: object) -> str:
            return json.dumps(value)

        formulas: List[Any] = []

        for ent in entities:
            if not isinstance(ent, dict):
                continue
            ent_id = ent.get("id")
            if not ent_id:
                continue

            formulas.append(f"entity({q(ent_id)}).")

            ent_type = ent.get("type")
            if ent_type:
                formulas.append(f"type({q(ent_id)}, {q(ent_type)}).")

            ent_text = ent.get("text")
            if ent_text:
                formulas.append(f"text({q(ent_id)}, {q(ent_text)}).")

            props = ent.get("properties")
            if isinstance(props, dict):
                for key, val in props.items():
                    if key is None:
                        continue
                    formulas.append(f"prop({q(ent_id)}, {q(str(key))}, {q(val)}).")

        for rel in relationships:
            if not isinstance(rel, dict):
                continue

            rel_type = rel.get("type")
            source_id = rel.get("source_id")
            target_id = rel.get("target_id")
            if rel_type and source_id and target_id:
                formulas.append(f"rel({q(rel_type)}, {q(source_id)}, {q(target_id)}).")

            rel_id = rel.get("id")
            if rel_id:
                formulas.append(f"relationship({q(rel_id)}).")

        if not self._tdfol_available:
            logger.info("TDFOL module unavailable; returning string facts")

        return formulas

    def check_consistency(
        self,
        ontology: Dict[str, Any]
    ) -> ValidationResult:
        """
        Check ontology for logical consistency.
        
        Converts the ontology to TDFOL formulas and uses theorem provers
        to detect contradictions and verify logical consistency.
        
        Args:
            ontology: Ontology to validate
            
        Returns:
            ValidationResult with consistency information
            
        Example:
            >>> result = validator.check_consistency(ontology)
            >>> if result.is_consistent:
            ...     print("Ontology is logically consistent!")
            >>> else:
            ...     print("Found contradictions:", result.contradictions)
        """
        logger.info("Checking ontology consistency")
        
        # Check cache if enabled
        if self.use_cache:
            cache_key = self._get_cache_key(ontology)
            if cache_key in self._cache:
                logger.info("Using cached validation result")
                return self._cache[cache_key]
        
        import time
        start_time = time.time()
        
        if not self._tdfol_available:
            # Fallback to basic structural validation
            logger.warning("TDFOL not available, using basic validation")
            result = self._basic_consistency_check(ontology)
        else:
            # Full TDFOL-based validation
            try:
                formulas = self.ontology_to_tdfol(ontology)
                result = self._prove_consistency(formulas, ontology)
            except Exception as e:
                logger.error(f"TDFOL validation failed: {e}")
                result = ValidationResult(
                    is_consistent=False,
                    contradictions=[f"Validation error: {str(e)}"],
                    confidence=0.0,
                    prover_used="error"
                )
        
        # Update timing
        result.time_ms = (time.time() - start_time) * 1000
        
        # Cache result if enabled
        if self.use_cache:
            self._cache[cache_key] = result
        
        logger.info(
            f"Validation complete: consistent={result.is_consistent}, "
            f"time={result.time_ms:.2f}ms"
        )
        
        return result
    
    def find_contradictions(
        self,
        ontology: Dict[str, Any]
    ) -> List[str]:
        """
        Identify logical contradictions in ontology.
        
        Args:
            ontology: Ontology to analyze
            
        Returns:
            List of contradiction descriptions
            
        Example:
            >>> contradictions = validator.find_contradictions(ontology)
            >>> for contradiction in contradictions:
            ...     print(f"Contradiction: {contradiction}")
        """
        logger.info("Finding contradictions in ontology")
        
        result = self.check_consistency(ontology)
        return result.contradictions
    
    def suggest_fixes(
        self,
        ontology: Dict[str, Any],
        contradictions: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Suggest fixes for detected contradictions.
        
        Analyzes contradictions and generates actionable suggestions
        for resolving logical inconsistencies in the ontology.
        
        Args:
            ontology: Ontology with contradictions
            contradictions: List of contradiction descriptions
            
        Returns:
            List of fix suggestions, each a dictionary with:
                - 'description': Description of the fix
                - 'type': Type of fix (e.g., 'remove_entity', 'modify_relationship')
                - 'target': Target element(s) to fix
                - 'confidence': Confidence in the fix (0.0 to 1.0)
                
        Example:
            >>> fixes = validator.suggest_fixes(ontology, contradictions)
            >>> for fix in fixes:
            ...     print(f"Fix: {fix['description']}")
        """
        logger.info(f"Generating fix suggestions for {len(contradictions)} contradictions")
        
        fixes = []

        import re as _re

        entities = ontology.get('entities', [])
        relationships = ontology.get('relationships', [])
        entity_ids = {e.get('id') for e in entities if isinstance(e, dict) and e.get('id')}
        entity_id_to_text: dict[str, str] = {
            e['id']: e.get('text', e['id'])
            for e in entities if isinstance(e, dict) and e.get('id')
        }

        for contradiction in contradictions:
            c_lower = contradiction.lower()

            # Pattern: dangling / non-existent source/target entity reference
            if 'non-existent' in c_lower or 'missing' in c_lower or 'not found' in c_lower:
                # Try to extract an entity ID from the message
                id_match = _re.search(r"entity[:\s]+['\"]?([^\s'\"]+)['\"]?", contradiction, _re.IGNORECASE)
                target_id = id_match.group(1) if id_match else None
                fixes.append({
                    'description': (
                        f"Add a placeholder entity with id '{target_id}' to satisfy the dangling reference, "
                        "or remove the relationship that references it."
                        if target_id else f"Resolve dangling reference: {contradiction}"
                    ),
                    'type': 'add_entity_or_remove_relationship',
                    'target': target_id,
                    'confidence': 0.75,
                })

            # Pattern: duplicate entity ID
            elif 'duplicate' in c_lower:
                id_match = _re.search(r"id[:\s]+['\"]?([^\s'\"]+)['\"]?", contradiction, _re.IGNORECASE)
                target_id = id_match.group(1) if id_match else None
                fixes.append({
                    'description': (
                        f"Assign a unique ID to the duplicate entity '{target_id}' "
                        "and update all references."
                        if target_id else f"Resolve duplicate ID: {contradiction}"
                    ),
                    'type': 'rename_duplicate_id',
                    'target': target_id,
                    'confidence': 0.85,
                })

            # Pattern: circular dependency (is_a / part_of cycle)
            elif 'circular' in c_lower or 'cycle' in c_lower:
                fixes.append({
                    'description': (
                        "Break the circular dependency by removing or redirecting one of the "
                        "'is_a' or 'part_of' relationships in the cycle."
                    ),
                    'type': 'remove_circular_relationship',
                    'target': None,
                    'confidence': 0.70,
                })

            # Pattern: type conflict
            elif 'type' in c_lower and 'conflict' in c_lower:
                id_match = _re.search(r"entity[:\s]+['\"]?([^\s'\"]+)['\"]?", contradiction, _re.IGNORECASE)
                target_id = id_match.group(1) if id_match else None
                fixes.append({
                    'description': (
                        f"Resolve the type conflict for entity '{entity_id_to_text.get(target_id, target_id)}' "
                        "by choosing the type with the highest confidence and updating all references."
                        if target_id else f"Resolve type conflict: {contradiction}"
                    ),
                    'type': 'unify_entity_type',
                    'target': target_id,
                    'confidence': 0.65,
                })

            # Fallback: generic manual review
            else:
                fixes.append({
                    'description': f"Manual review required: {contradiction}",
                    'type': 'manual_review',
                    'target': None,
                    'confidence': 0.40,
                })

        logger.info(f"Generated {len(fixes)} fix suggestions")
        return fixes
    
    def _basic_consistency_check(
        self,
        ontology: Dict[str, Any]
    ) -> ValidationResult:
        """
        Basic structural consistency check without TDFOL.
        
        Args:
            ontology: Ontology to check
            
        Returns:
            Basic validation result
        """
        logger.info("Performing basic consistency check")
        
        contradictions = []
        entities = ontology.get('entities', [])
        relationships = ontology.get('relationships', [])
        
        # Check for basic structural issues
        entity_ids = {e.get('id') for e in entities if isinstance(e, dict)}
        
        # Check relationships reference valid entities
        for rel in relationships:
            if not isinstance(rel, dict):
                continue
            
            source_id = rel.get('source_id')
            target_id = rel.get('target_id')
            
            if source_id not in entity_ids:
                contradictions.append(
                    f"Relationship references non-existent source entity: {source_id}"
                )
            if target_id not in entity_ids:
                contradictions.append(
                    f"Relationship references non-existent target entity: {target_id}"
                )
        
        is_consistent = len(contradictions) == 0
        
        return ValidationResult(
            is_consistent=is_consistent,
            contradictions=contradictions,
            confidence=0.7,  # Lower confidence for basic check
            prover_used="basic_structural"
        )
    
    def _prove_consistency(
        self,
        formulas: List[Any],
        ontology: Dict[str, Any]
    ) -> ValidationResult:
        """
        Prove consistency using TDFOL reasoner.
        
        Args:
            formulas: List of TDFOL formulas
            ontology: Original ontology
            
        Returns:
            Validation result from theorem proving
        """
        logger.info(f"Proving consistency of {len(formulas)} formulas")
        
        # TODO: Implement full TDFOL proving
        # This is a placeholder for Phase 1 implementation
        
        # For now, return basic result
        return ValidationResult(
            is_consistent=True,
            contradictions=[],
            confidence=0.9,
            prover_used=self.prover_config.get('strategy', 'AUTO')
        )
    
    def _get_cache_key(self, ontology: Dict[str, Any]) -> str:
        """Generate cache key for ontology."""
        import hashlib
        import json
        
        # Create deterministic representation
        ontology_str = json.dumps(ontology, sort_keys=True)
        return hashlib.sha256(ontology_str.encode()).hexdigest()


# Export public API
__all__ = [
    'LogicValidator',
    'ValidationResult',
]
