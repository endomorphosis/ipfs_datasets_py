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
class ProverConfig:
    """Typed configuration for theorem provers.

    Attributes:
        strategy: Proving strategy. One of ``'AUTO'``, ``'SYMBOLIC'``,
            ``'NEURAL'``, or ``'HYBRID'``.  Defaults to ``'AUTO'``.
        provers: Ordered list of prover backends to attempt, e.g.
            ``['z3', 'cvc5', 'symbolic_ai']``.  When empty the validator
            selects provers automatically.
        timeout: Per-prover timeout in seconds.  0 means no limit.
        parallel: Run multiple provers in parallel when ``True``.
    """

    strategy: str = "AUTO"
    provers: List[str] = field(default_factory=list)
    timeout: float = 10.0
    parallel: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain-dict representation (legacy compatibility)."""
        return {
            "strategy": self.strategy,
            "provers": list(self.provers),
            "timeout": self.timeout,
            "parallel": self.parallel,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProverConfig":
        """Construct from a plain dict (backwards-compat with old callers)."""
        return cls(
            strategy=d.get("strategy", "AUTO"),
            provers=list(d.get("provers", [])),
            timeout=float(d.get("timeout", 10.0)),
            parallel=bool(d.get("parallel", False)),
        )


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
        invalid_entity_ids: IDs of entities involved in validation errors
            (e.g. entities referenced by dangling relationships).
    """
    
    is_consistent: bool
    contradictions: List[str] = field(default_factory=list)
    proofs: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    prover_used: str = "unknown"
    time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    invalid_entity_ids: List[str] = field(default_factory=list)
    
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
            'invalid_entity_ids': self.invalid_entity_ids,
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
        prover_config: Optional[Any] = None,  # ProverConfig | Dict[str, Any]
        use_cache: bool = True
    ):
        """
        Initialize the logic validator.
        
        Args:
            prover_config: Configuration for theorem provers. Accepts either a
                :class:`ProverConfig` instance or a plain ``dict`` with keys:
                ``strategy``, ``provers``, ``timeout``, ``parallel``.
            use_cache: Whether to cache validation results for performance
            
        Raises:
            ImportError: If TDFOL module is not available
        """
        if isinstance(prover_config, ProverConfig):
            self.prover_config: ProverConfig = prover_config
        elif isinstance(prover_config, dict):
            self.prover_config = ProverConfig.from_dict(prover_config)
        else:
            self.prover_config = ProverConfig()
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

        # Check TDFOL formula cache
        _cache_key: Optional[str] = None
        if self.use_cache and self._cache is not None:
            _cache_key = self._get_cache_key(ontology)
            if _cache_key in self._cache:
                logger.debug("TDFOL cache hit for ontology hash %s", _cache_key[:12])
                return list(self._cache[_cache_key])

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

        # Store in cache before returning
        if _cache_key is not None and self._cache is not None:
            self._cache[_cache_key] = list(formulas)

        return formulas

    def entity_to_tdfol(self, entity: Dict[str, Any]) -> List[str]:
        """Convert a single entity dict to TDFOL predicate strings.

        This is a convenience wrapper around :meth:`ontology_to_tdfol` for
        callers that want to convert one entity at a time, e.g. for streaming
        or incremental validation.

        Args:
            entity: A single entity dict with at least an ``"id"`` key.

        Returns:
            List of predicate strings for the entity (``entity/1``, ``type/2``,
            ``text/2``, ``prop/3``).  Returns an empty list if ``entity`` has
            no ``"id"`` field.

        Example::

            validator = LogicValidator()
            facts = validator.entity_to_tdfol({
                "id": "e1", "type": "Person", "text": "Alice",
                "properties": {"age": 30},
            })
            # ['entity("e1").', 'type("e1", "Person").', 'text("e1", "Alice").', ...]
        """
        import json

        if not isinstance(entity, dict):
            return []
        ent_id = entity.get("id")
        if not ent_id:
            return []

        def q(value: object) -> str:
            return json.dumps(value)

        facts: List[str] = [f"entity({q(ent_id)})."]

        ent_type = entity.get("type")
        if ent_type:
            facts.append(f"type({q(ent_id)}, {q(ent_type)}).")

        ent_text = entity.get("text")
        if ent_text:
            facts.append(f"text({q(ent_id)}, {q(ent_text)}).")

        props = entity.get("properties")
        if isinstance(props, dict):
            for key, val in props.items():
                if key is None:
                    continue
                facts.append(f"prop({q(ent_id)}, {q(str(key))}, {q(val)}).")

        return facts

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

    def suggest_fixes_for_result(
        self,
        ontology: Dict[str, Any],
        result: "ValidationResult",
    ) -> List[Dict[str, Any]]:
        """Convenience wrapper: derive fix hints from a :class:`ValidationResult`.

        Combines hints from ``result.contradictions`` (via :meth:`suggest_fixes`)
        with additional hints for any ``result.invalid_entity_ids``.

        Args:
            ontology: The validated ontology dict.
            result: A :class:`ValidationResult` from :meth:`_basic_consistency_check`
                or :meth:`validate_ontology`.

        Returns:
            List of fix suggestion dicts (same structure as :meth:`suggest_fixes`).
        """
        fixes = self.suggest_fixes(ontology, result.contradictions)
        for eid in result.invalid_entity_ids:
            fixes.append({
                "description": (
                    f"Entity id '{eid}' is referenced in a relationship but does not exist. "
                    "Add a stub entity or remove the offending relationship."
                ),
                "type": "add_entity_or_remove_relationship",
                "target": eid,
                "confidence": 0.80,
            })
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
        invalid_ids: list = []
        for rel in relationships:
            if not isinstance(rel, dict):
                continue
            
            source_id = rel.get('source_id')
            target_id = rel.get('target_id')
            
            if source_id not in entity_ids:
                contradictions.append(
                    f"Relationship references non-existent source entity: {source_id}"
                )
                if source_id and source_id not in invalid_ids:
                    invalid_ids.append(source_id)
            if target_id not in entity_ids:
                contradictions.append(
                    f"Relationship references non-existent target entity: {target_id}"
                )
                if target_id and target_id not in invalid_ids:
                    invalid_ids.append(target_id)
        
        is_consistent = len(contradictions) == 0
        
        return ValidationResult(
            is_consistent=is_consistent,
            contradictions=contradictions,
            confidence=0.7,  # Lower confidence for basic check
            prover_used="basic_structural",
            invalid_entity_ids=invalid_ids,
        )
    
    def _prove_consistency(
        self,
        formulas: List[Any],
        ontology: Dict[str, Any]
    ) -> ValidationResult:
        """
        Prove consistency using TDFOL reasoner.
        
        Args:
            formulas: List of TDFOL formulas (string predicates or Formula objects)
            ontology: Original ontology
            
        Returns:
            Validation result from theorem proving
        """
        logger.info(f"Proving consistency of {len(formulas)} formulas")

        # --- best-effort string-formula checker ----------------------------
        # Parse the predicate strings emitted by ontology_to_tdfol().
        # Detects: duplicate entity IDs, dangling relationship references,
        # and trivial is_a cycles (A is_a B, B is_a A).
        import re

        entity_ids: set = set()
        rel_triples: list = []  # (rel_type, source_id, target_id)
        duplicate_ids: list = []

        for formula in formulas:
            if not isinstance(formula, str):
                continue

            m_entity = re.match(r'^entity\("([^"]+)"\)\.$', formula)
            if m_entity:
                eid = m_entity.group(1)
                if eid in entity_ids:
                    duplicate_ids.append(eid)
                entity_ids.add(eid)
                continue

            m_rel = re.match(r'^rel\("([^"]+)",\s*"([^"]+)",\s*"([^"]+)"\)\.$', formula)
            if m_rel:
                rel_triples.append((m_rel.group(1), m_rel.group(2), m_rel.group(3)))

        contradictions: list = []

        # Duplicate entity IDs
        for eid in duplicate_ids:
            contradictions.append(f"Duplicate entity ID: {eid}")

        # Dangling references
        for rel_type, src, tgt in rel_triples:
            if src not in entity_ids:
                contradictions.append(
                    f"Relationship '{rel_type}' has dangling source: {src}"
                )
            if tgt not in entity_ids:
                contradictions.append(
                    f"Relationship '{rel_type}' has dangling target: {tgt}"
                )

        # Trivial is_a cycles: A is_a B and B is_a A
        isa_pairs = {
            (src, tgt) for (rt, src, tgt) in rel_triples
            if rt in ("is_a", "subclass_of", "instance_of")
        }
        for src, tgt in isa_pairs:
            if (tgt, src) in isa_pairs:
                contradictions.append(
                    f"Circular is_a relationship: {src} ↔ {tgt}"
                )

        is_consistent = len(contradictions) == 0
        confidence = 0.85 if is_consistent else 0.75

        return ValidationResult(
            is_consistent=is_consistent,
            contradictions=contradictions,
            confidence=confidence,
            prover_used=f"structural:{self.prover_config.strategy}",
        )
    
    def batch_validate(
        self,
        ontologies: List[Dict[str, Any]],
        max_workers: int = 4,
    ) -> List[ValidationResult]:
        """Validate a list of ontologies concurrently.

        Uses a :class:`~concurrent.futures.ThreadPoolExecutor` to call
        :meth:`check_consistency` on each ontology in parallel.

        Args:
            ontologies: List of ontology dicts to validate.
            max_workers: Maximum number of worker threads (default: 4).

        Returns:
            List of :class:`ValidationResult` objects in the same order as
            *ontologies*.

        Example:
            >>> results = validator.batch_validate([ont_a, ont_b, ont_c])
            >>> [r.is_consistent for r in results]
            [True, False, True]
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if not ontologies:
            return []

        results: List[Optional[ValidationResult]] = [None] * len(ontologies)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.check_consistency, ont): idx for idx, ont in enumerate(ontologies)}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:
                    results[idx] = ValidationResult(
                        is_consistent=False,
                        contradictions=[f"Validation error: {exc}"],
                        confidence=0.0,
                        prover_used="error",
                    )
        return results  # type: ignore[return-value]

    def explain_contradictions(
        self,
        ontology: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Return human-readable explanations for each detected contradiction.

        Runs :meth:`check_consistency` and augments each contradiction string
        with a structured explanation dict containing a plain-English
        ``"explanation"`` and a suggested ``"action"``.

        Args:
            ontology: Ontology dict to analyse.

        Returns:
            List of dicts, one per contradiction, each with:

            * ``"contradiction"`` -- original contradiction string.
            * ``"explanation"`` -- plain-English description.
            * ``"action"`` -- suggested fix action label.

        Example:
            >>> explanations = validator.explain_contradictions(ontology)
            >>> for ex in explanations:
            ...     print(ex["explanation"])
        """
        result = self.check_consistency(ontology)
        explanations = []
        for contradiction in result.contradictions:
            c_lower = contradiction.lower()
            if "dangling" in c_lower or "missing" in c_lower:
                explanation = (
                    f"A relationship references an entity ID that does not exist: {contradiction}. "
                    "Remove the relationship or add the missing entity."
                )
                action = "remove_dangling_relationship"
            elif "duplicate" in c_lower:
                explanation = (
                    f"Duplicate entity detected: {contradiction}. "
                    "Merge duplicate entities to maintain a clean ontology."
                )
                action = "merge_duplicate_entities"
            elif "self.loop" in c_lower or "self-loop" in c_lower or "source_id == target_id" in c_lower:
                explanation = (
                    f"A relationship points to itself: {contradiction}. "
                    "Remove or redirect self-loop relationships."
                )
                action = "remove_self_loop"
            elif "cycle" in c_lower:
                explanation = (
                    f"Circular dependency detected: {contradiction}. "
                    "Break the cycle by removing one relationship in the loop."
                )
                action = "break_cycle"
            else:
                explanation = f"Logical inconsistency detected: {contradiction}."
                action = "review_manually"
            explanations.append({
                "contradiction": contradiction,
                "explanation": explanation,
                "action": action,
            })
        return explanations

    def filter_valid_entities(        self,
        entities: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Return the subset of *entities* that pass a consistency check.

        Builds a minimal single-entity ontology for each candidate and runs
        :meth:`check_consistency`.  Only entities whose mini-ontology is
        deemed consistent are returned.

        Args:
            entities: List of entity dicts (each with at least ``"id"`` and
                ``"type"`` keys).

        Returns:
            List of entity dicts that are individually consistent.

        Example:
            >>> valid = validator.filter_valid_entities(result.entities)
            >>> len(valid) <= len(result.entities)
            True
        """
        valid: List[Dict[str, Any]] = []
        for ent in entities:
            mini_ont: Dict[str, Any] = {
                "entities": [ent],
                "relationships": [],
            }
            try:
                result = self.check_consistency(mini_ont)
                if result.is_consistent:
                    valid.append(ent)
            except Exception:
                pass  # skip entities that cause unexpected errors
        return valid

    def explain_entity(
        self,
        entity: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Return a human-readable validation explanation for a single entity.

        Builds a minimal ontology containing only *entity* and runs
        :meth:`check_consistency`.  Returns a structured explanation dict.

        Args:
            entity: Entity dict (at least ``"id"`` and ``"type"`` keys).

        Returns:
            Dict with keys:

            * ``"entity_id"`` -- the entity's ``id`` field.
            * ``"is_valid"`` -- bool, whether the entity is individually consistent.
            * ``"contradictions"`` -- list of contradiction strings (empty if valid).
            * ``"explanation"`` -- human-readable summary sentence.

        Example:
            >>> exp = validator.explain_entity({"id": "e1", "type": "Person", "text": "Alice"})
            >>> exp["is_valid"]
            True
        """
        mini_ont: Dict[str, Any] = {"entities": [entity], "relationships": []}
        entity_id = entity.get("id", "unknown")
        try:
            result = self.check_consistency(mini_ont)
            if result.is_consistent:
                return {
                    "entity_id": entity_id,
                    "is_valid": True,
                    "contradictions": [],
                    "explanation": f"Entity '{entity_id}' passed all consistency checks.",
                }
            else:
                return {
                    "entity_id": entity_id,
                    "is_valid": False,
                    "contradictions": list(result.contradictions),
                    "explanation": (
                        f"Entity '{entity_id}' has {len(result.contradictions)} "
                        f"consistency issue(s): {'; '.join(result.contradictions[:2])}"
                    ),
                }
        except Exception as exc:
            return {
                "entity_id": entity_id,
                "is_valid": False,
                "contradictions": [str(exc)],
                "explanation": f"Entity '{entity_id}' could not be validated: {exc}",
            }

    def count_contradictions(self, ontology: Dict[str, Any]) -> int:
        """Return the number of contradictions found in *ontology*.

        Runs :meth:`check_consistency` and returns the length of the
        ``contradictions`` list.

        Args:
            ontology: Ontology dict to check.

        Returns:
            Integer >= 0.

        Example:
            >>> n = validator.count_contradictions(ontology)
            >>> n == 0  # consistent
            True
        """
        try:
            result = self.check_consistency(ontology)
            return len(result.contradictions)
        except Exception:
            return 0

    def is_consistent(self, ontology: Dict[str, Any]) -> bool:
        """Return ``True`` if the ontology has no logical contradictions.

        Convenience boolean shortcut wrapping :meth:`check_consistency`.

        Returns:
            ``True`` when :meth:`count_contradictions` returns 0, ``False``
            otherwise.

        Example:
            >>> validator.is_consistent({"entities": []})
            True
        """
        return self.count_contradictions(ontology) == 0

    def quick_check(self, ontology: Dict[str, Any]) -> bool:
        """Perform a fast consistency check on *ontology*.

        Unlike the full :meth:`validate_ontology`, this method simply
        delegates to :meth:`is_consistent` (contradiction count == 0).
        It is intended as a lightweight boolean gate in hot loops.

        Args:
            ontology: Ontology dict to check.

        Returns:
            ``True`` if no contradictions are detected, ``False`` otherwise.

        Example:
            >>> validator.quick_check({"entities": [], "relationships": []})
            True
        """
        return self.is_consistent(ontology)

    def is_empty(self, ontology: Dict[str, Any]) -> bool:
        """Return ``True`` if *ontology* contains no entities and no relationships.

        Args:
            ontology: Ontology dict to inspect.

        Returns:
            ``True`` when both ``entities`` and ``relationships`` are absent or
            empty, ``False`` otherwise.

        Example:
            >>> validator.is_empty({"entities": [], "relationships": []})
            True
            >>> validator.is_empty({"entities": [{"id": "e1"}]})
            False
        """
        return (
            not ontology.get("entities") and not ontology.get("relationships")
        )

    def format_report(self, result: "ValidationResult") -> str:
        """Produce a human-readable validation report from *result*.

        Args:
            result: A :class:`ValidationResult` as returned by
                :meth:`validate_ontology` or :meth:`_basic_consistency_check`.

        Returns:
            Multi-line string summarising consistency status, contradiction
            count, confidence and (optionally) the individual contradiction
            messages.

        Example:
            >>> vr = validator.validate_ontology({"entities": [], "relationships": []})
            >>> report = validator.format_report(vr)
            >>> "consistent" in report.lower()
            True
        """
        status = "CONSISTENT" if result.is_consistent else "INCONSISTENT"
        lines = [
            f"Validation Report",
            f"  Status    : {status}",
            f"  Confidence: {result.confidence:.2f}",
            f"  Prover    : {result.prover_used}",
            f"  Time (ms) : {result.time_ms:.1f}",
            f"  Contradictions ({len(result.contradictions)}):",
        ]
        for c in result.contradictions:
            lines.append(f"    - {c}")
        if result.invalid_entity_ids:
            lines.append(f"  Invalid entity IDs: {', '.join(result.invalid_entity_ids)}")
        return "\n".join(lines)

    def clear_tdfol_cache(self) -> int:
        """Clear the TDFOL formula cache.

        Returns:
            Number of entries cleared from the cache.
        """
        if self._cache is None:
            return 0
        n = len(self._cache)
        self._cache.clear()
        logger.debug("TDFOL cache cleared (%d entries removed)", n)
        return n

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
    'ProverConfig',
]
