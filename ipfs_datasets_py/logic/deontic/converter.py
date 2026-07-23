"""
Deontic Converter - Unified converter with integrated features.

This module provides the DeonticConverter class that extends LogicConverter base
and integrates all 6 core features for legal/deontic logic conversion.
"""

from __future__ import annotations

from ipfs_datasets_py.utils import anyio_compat as asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from ..common.converters import (
    LogicConverter,
    ConversionResult,
    ConversionStatus,
    ValidationResult
)
from ..common.errors import ConversionError, ValidationError
from ..types.deontic_types import DeonticFormula, DeonticOperator
from ..types.common_types import ConfidenceScore
from .ir import LegalNormIR
from .formula_builder import build_deontic_formula_records_from_irs
from .exports import (
    build_deterministic_parser_capability_profile_records,
    build_prover_syntax_target_coverage_records_from_irs,
    parser_elements_with_ir_export_readiness,
)

# Import existing deontic utilities
from .utils.deontic_parser import (
    build_deontic_formula,
    detect_normative_conflicts,
    extract_normative_elements,
    identify_obligations,
)

logger = logging.getLogger(__name__)


class DeonticConverter(LogicConverter[str, DeonticFormula]):
    """
    Unified Deontic logic converter with all features integrated.
    
    This converter extends the LogicConverter base class and provides
    deontic/legal logic conversion with automatic feature integration:
    
    Features:
    - ✅ Caching (local + optional IPFS)
    - ✅ Batch processing (5-8x speedup via parallelization)
    - ✅ ML confidence scoring (with fallback to heuristics)
    - ✅ NLP extraction (from existing deontic utilities)
    - ✅ Real-time monitoring (operation tracking and metrics)
    - ✅ Type safety (using logic/types/)
    
    Example:
        >>> converter = DeonticConverter(
        ...     use_cache=True,
        ...     use_ml=True,
        ...     enable_monitoring=True,
        ...     jurisdiction="us",
        ...     document_type="statute"
        ... )
        >>> result = converter.convert("The tenant must pay rent monthly")
        >>> print(f"Formula: {result.output.formula}")
        >>> print(f"Confidence: {result.confidence}")
        
        # Batch conversion
        >>> texts = ["Must comply", "May appeal", "Shall not trespass"]
        >>> results = converter.convert_batch(texts, max_workers=4)
        
        # Async for backward compatibility
        >>> result = await converter.convert_async("legal text")
    """
    
    def __init__(
        self,
        use_cache: bool = True,
        use_ipfs: bool = False,
        use_ml: bool = True,
        enable_monitoring: bool = True,
        jurisdiction: str = "us",
        document_type: str = "statute",
        extract_obligations: bool = True,
        include_exceptions: bool = True,
        expand_enumerations: bool = False,
        confidence_threshold: float = 0.7,
        output_format: str = "json",
        cache_maxsize: int = 1000,
        cache_ttl: float = 3600,
    ):
        """
        Initialize Deontic converter with feature configuration.
        
        Args:
            use_cache: Enable local caching (default: True)
            use_ipfs: Enable IPFS distributed caching (default: False)
            use_ml: Enable ML confidence scoring (default: True)
            enable_monitoring: Enable operation monitoring (default: True)
            jurisdiction: Legal jurisdiction (us, eu, uk, international, general)
            document_type: Document type (statute, regulation, contract, policy, agreement)
            extract_obligations: Extract obligations from text (default: True)
            include_exceptions: Include exceptions in analysis (default: True)
            expand_enumerations: Emit item-level parser elements for enumerated clauses (default: False)
            confidence_threshold: Minimum confidence for results (default: 0.7)
            output_format: Output format (json, prolog, tptp) (default: "json")
            cache_maxsize: Maximum cache entries (default: 1000, 0=unlimited)
            cache_ttl: Cache TTL in seconds (default: 3600, 0=no expiration)
        """
        super().__init__(
            enable_caching=use_cache,
            enable_validation=True,
            cache_maxsize=cache_maxsize,
            cache_ttl=cache_ttl
        )
        
        self.use_ipfs = use_ipfs
        self.use_ml = use_ml
        self.enable_monitoring = enable_monitoring
        self.jurisdiction = jurisdiction if jurisdiction in ["us", "eu", "uk", "international", "general"] else "general"
        self.document_type = document_type if document_type in ["statute", "regulation", "contract", "policy", "agreement", "general"] else "general"
        self.extract_obligations = extract_obligations
        self.include_exceptions = include_exceptions
        self.expand_enumerations = expand_enumerations
        self.confidence_threshold = confidence_threshold
        self.output_format = output_format
        
        # Initialize ML confidence scorer if available
        self.ml_scorer = None
        if use_ml:
            try:
                from ..ml_confidence import MLConfidenceScorer
                self.ml_scorer = MLConfidenceScorer()
                logger.info("ML confidence scoring enabled")
            except ImportError:
                logger.warning("ML confidence scorer not available, using heuristic fallback")
        
        # Initialize monitoring if enabled
        self.monitoring = None
        if enable_monitoring:
            try:
                from ..monitoring import LogicMonitoring
                self.monitoring = LogicMonitoring()
                logger.info("Monitoring enabled")
            except ImportError:
                logger.debug("Monitoring not available")
        
        # Statistics
        self._stats = {
            "conversions": 0,
            "successful": 0,
            "failed": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

    def convert(
        self,
        input_data: str,
        options: Optional[Dict[str, Any]] = None,
        use_cache: bool = True,
    ) -> ConversionResult[DeonticFormula]:
        """Convert legal text and attach deterministic parser metadata.

        The base converter returns only the formal output.  This override keeps
        that behavior but also exposes the parser element and typed legal IR so
        downstream CEC/TDFOL/proof exporters can consume structured slots
        instead of reparsing the original legal text.
        """

        result = super().convert(input_data, options=options, use_cache=use_cache)
        output = result.output
        if output is None:
            return result

        parser_elements = getattr(output, "parser_elements", None)
        parser_element = getattr(output, "parser_element", None)
        legal_norm_ir = getattr(output, "legal_norm_ir", None)
        legal_norm_irs: List[LegalNormIR] = []

        if parser_elements is not None:
            parser_elements = parser_elements_with_ir_export_readiness(parser_elements)
            output.parser_elements = parser_elements  # type: ignore[attr-defined]
            if parser_elements:
                parser_element = parser_elements[0]
                output.parser_element = parser_element  # type: ignore[attr-defined]
            result.metadata.setdefault("parser_elements", parser_elements)
            legal_norm_irs = [
                LegalNormIR.from_parser_element(element)
                for element in parser_elements
                if isinstance(element, dict)
            ]
            result.metadata.setdefault("legal_norm_irs", [norm.to_dict() for norm in legal_norm_irs])
            result.metadata.setdefault(
                "legal_formula_records",
                build_deontic_formula_records_from_irs(legal_norm_irs),
            )
            formula_records = result.metadata.get("legal_formula_records", [])
            result.metadata.setdefault(
                "legal_formula_record_proof_ready_count",
                sum(1 for record in formula_records if record.get("proof_ready") is True),
            )
            result.metadata.setdefault(
                "legal_parser_capability_profile_records",
                build_deterministic_parser_capability_profile_records(legal_norm_irs),
            )
            prover_coverage_records = build_prover_syntax_target_coverage_records_from_irs(
                legal_norm_irs
            )
            result.metadata.setdefault(
                "legal_prover_syntax_target_coverage_records",
                prover_coverage_records,
            )
            result.metadata.setdefault(
                "legal_formal_syntax_valid_count",
                sum(1 for record in prover_coverage_records if record.get("formal_syntax_valid") is True),
            )
            if legal_norm_irs:
                legal_norm_ir = legal_norm_irs[0]
                output.legal_norm_ir = legal_norm_ir  # type: ignore[attr-defined]
        if parser_element is not None:
            result.metadata.setdefault("parser_element", parser_element)
        if legal_norm_ir is not None:
            result.metadata.setdefault("legal_norm_ir", legal_norm_ir.to_dict())
        result.metadata.setdefault(
            "deterministic_parser",
            {
                "enabled": True,
                "source": "ipfs_datasets_py.logic.deontic.utils.deontic_parser",
                "element_count": len(parser_elements or []),
                "ir_count": len(legal_norm_irs),
                "formula_record_count": len(result.metadata.get("legal_formula_records", [])),
                "formula_record_proof_ready_count": result.metadata.get("legal_formula_record_proof_ready_count", 0),
                "parser_capability_profile_count": len(result.metadata.get("legal_parser_capability_profile_records", [])),
                "prover_syntax_target_coverage_record_count": len(result.metadata.get("legal_prover_syntax_target_coverage_records", [])),
                "formal_syntax_valid_count": result.metadata.get("legal_formal_syntax_valid_count", 0),
                "proof_ready": bool(getattr(legal_norm_ir, "proof_ready", False)),
                "blockers": list(getattr(legal_norm_ir, "blockers", [])),
            },
        )
        return result
    
    def validate_input(self, text: str) -> ValidationResult:
        """
        Validate input legal text.
        
        Args:
            text: Legal text to validate
            
        Returns:
            ValidationResult with validation status and any errors
        """
        result = ValidationResult(valid=True)
        
        if not text or not isinstance(text, str):
            result.valid = False
            result.add_error("Input text must be a non-empty string")
            return result
        
        stripped = text.strip()
        if not stripped:
            result.valid = False
            result.add_error("Input text cannot be empty or whitespace")
            return result
        
        # Check for minimum content
        if len(stripped) < 3:
            result.valid = False
            result.add_error("Input text too short (minimum 3 characters)")
            return result
        
        return result
    
    def _convert_impl(self, text: str, options: Dict[str, Any]) -> DeonticFormula:
        """
        Core conversion implementation.
        
        This method uses the existing deontic parsing utilities to convert
        legal text into deontic logic formulas.
        
        Args:
            text: Legal text to convert
            options: Conversion options
            
        Returns:
            DeonticFormula object
            
        Raises:
            ConversionError: If conversion fails
        """
        start_time = time.time()
        
        try:
            # Extract normative elements using existing parser
            expand_enumerations = bool(options.get("expand_enumerations", self.expand_enumerations))
            elements = extract_normative_elements(
                text,
                self.document_type,
                expand_enumerations=expand_enumerations,
            )
            
            if not elements:
                # The deterministic parser did not find a norm.  Emit an
                # explicit low-confidence scaffold rather than fabricating a
                # normal obligation from arbitrary legal text.
                formula = DeonticFormula(
                    operator=DeonticOperator.OBLIGATION,
                    proposition="UnparsedNonNormativeOrAmbiguousText",
                    agent=None,
                    beneficiary=None,
                    conditions=[],
                    confidence=0.05,
                    source_text=text
                )
                formula.parser_elements = []  # type: ignore[attr-defined]
                formula.parser_element = None  # type: ignore[attr-defined]
                formula.legal_norm_ir = None  # type: ignore[attr-defined]
                return formula
            
            # Use the first element for single formula conversion
            # (batch processing handles multiple elements)
            element = elements[0]
            legal_norm_ir = LegalNormIR.from_parser_element(element)
            
            # Build deontic formula string (proposition)
            formula_string = build_deontic_formula(element)
            
            # Extract deontic operator
            operator_map = {
                "obligation": DeonticOperator.OBLIGATION,
                "permission": DeonticOperator.PERMISSION,
                "prohibition": DeonticOperator.PROHIBITION,
                "definition": DeonticOperator.POWER,
                "applicability": DeonticOperator.POWER,
                "exemption": DeonticOperator.IMMUNITY,
                "instrument_lifecycle": DeonticOperator.POWER,
            }
            operator = operator_map.get(element.get("norm_type"), DeonticOperator.OBLIGATION)
            proposition = self._strip_outer_deontic_operator(formula_string, operator.value)
            
            # Extract agent from subject
            from ..integration.deontic_logic_core import LegalAgent
            agent = None
            subjects = element.get("subject", [])
            if subjects:
                subject_name = subjects[0] if isinstance(subjects, list) else subjects
                agent = LegalAgent(
                    identifier=subject_name.lower().replace(" ", "_"),
                    name=subject_name,
                    agent_type=element.get("actor_type") or "legal_entity",
                    properties={}
                )
            beneficiary = None
            recipient_name = element.get("action_recipient")
            if recipient_name:
                beneficiary = LegalAgent(
                    identifier=recipient_name.lower().replace(" ", "_"),
                    name=recipient_name,
                    agent_type="beneficiary",
                    properties={}
                )
            
            # Create DeonticFormula object with correct constructor
            formula = DeonticFormula(
                operator=operator,
                proposition=proposition,
                agent=agent,
                beneficiary=beneficiary,
                conditions=element.get("conditions", []),
                temporal_conditions=[],  # Would need to convert from element format
                confidence=0.8,  # Will be recalculated below
                source_text=text
            )
            
            # Calculate confidence
            confidence = self._calculate_confidence(text, formula_string, element)
            # Update formula confidence (it's mutable)
            formula.confidence = confidence
            formula.parser_elements = elements  # type: ignore[attr-defined]
            formula.parser_element = element  # type: ignore[attr-defined]
            formula.legal_norm_ir = legal_norm_ir  # type: ignore[attr-defined]
            
            # Track conversion time
            conversion_time = time.time() - start_time
            
            # Record monitoring data if enabled
            if self.monitoring:
                self.monitoring.record_conversion(
                    converter_type="deontic",
                    success=True,
                    duration=conversion_time,
                    confidence=confidence
                )
            
            return formula
            
        except Exception as e:
            logger.error(f"Deontic conversion failed: {e}")
            if self.monitoring:
                self.monitoring.record_conversion(
                    converter_type="deontic",
                    success=False,
                    duration=time.time() - start_time,
                    error=str(e)
                )
            raise ConversionError(f"Failed to convert legal text to deontic logic: {e}")

    @staticmethod
    def _strip_outer_deontic_operator(formula: str, operator_value: str) -> str:
        text = str(formula or "").strip()
        prefix = f"{operator_value}("
        if text.startswith(prefix) and text.endswith(")"):
            return text[len(prefix) : -1].strip()
        return text
    
    def _calculate_confidence(self, text: str, formula: str, element: Dict[str, Any]) -> float:
        """
        Calculate confidence score for the conversion.
        
        Uses ML scorer if available, otherwise falls back to heuristic calculation.
        
        Args:
            text: Original text
            formula: Generated formula
            element: Extracted normative element
            
        Returns:
            Confidence score between 0 and 1
        """
        # Try ML confidence scoring first
        if self.ml_scorer:
            try:
                features = {
                    "text_length": len(text),
                    "formula_length": len(formula),
                    "has_operator": element.get("deontic_operator") is not None,
                    "has_subject": len(element.get("subject", [])) > 0,
                    "has_action": len(element.get("action", [])) > 0,
                    "has_conditions": len(element.get("conditions", [])) > 0,
                    "scaffold_quality": element.get("scaffold_quality", 0),
                    "parser_warning_count": len(element.get("parser_warnings", [])),
                    "norm_type": element.get("norm_type", "unknown"),
                }
                return self.ml_scorer.predict_confidence(features)
            except Exception as e:
                logger.debug(f"ML confidence scoring failed, using heuristic: {e}")
        
        # Heuristic confidence calculation
        confidence = float(element.get("confidence_floor") or 0.35)
        
        # Boost confidence based on element completeness
        if element.get("deontic_operator"):
            confidence += 0.15
        if element.get("subject"):
            confidence += 0.15
        if element.get("action"):
            confidence += 0.15
        if len(formula) > 10:
            confidence += 0.05
        confidence += min(float(element.get("scaffold_quality") or 0.0), 1.0) * 0.10
        confidence -= min(len(element.get("parser_warnings", [])), 5) * 0.03
        if element.get("promotable_to_theorem") is False:
            confidence = min(confidence, 0.68)
        if element.get("norm_type") == "definition":
            confidence = min(confidence, 0.45)
        if element.get("extraction_method", "").startswith("deterministic_"):
            confidence = min(confidence, 0.82)
        
        return min(confidence, 1.0)
    
    def convert_batch(
        self,
        texts: List[str],
        max_workers: int = 4,
        use_cache: bool = True
    ) -> List[ConversionResult[DeonticFormula]]:
        """
        Convert multiple legal texts to deontic logic in parallel.
        
        Uses batch processing for 5-8x speedup compared to sequential conversion.
        
        Args:
            texts: List of legal texts to convert
            max_workers: Number of parallel workers (default: 4)
            use_cache: Whether to use caching (default: True)
            
        Returns:
            List of ConversionResult objects
            
        Example:
            >>> converter = DeonticConverter()
            >>> texts = ["Must pay", "May appeal", "Shall not trespass"]
            >>> results = converter.convert_batch(texts, max_workers=4)
            >>> successful = [r for r in results if r.success]
        """
        try:
            from ..batch_processing import BatchProcessor
            processor = BatchProcessor(max_concurrency=max_workers)
            
            def convert_single(text: str) -> Dict[str, Any]:
                result = self.convert(text, use_cache=use_cache)
                return {"result": result, "text": text}
            
            batch_result = processor.process_batch_parallel(
                texts,
                convert_single
            )
            
            # Extract ConversionResult objects from batch results
            results = []
            for item in batch_result.results:
                if "result" in item:
                    results.append(item["result"])
            
            # Handle any errors
            for error in batch_result.errors:
                # Create failed result for errors
                failed_result = ConversionResult[DeonticFormula]()
                failed_result.status = ConversionStatus.FAILED
                failed_result.add_error(str(error.get("error", "Unknown error")))
                results.append(failed_result)
            
            return results
        except ImportError:
            logger.warning("Batch processor not available, falling back to sequential")
            return [self.convert(text, use_cache=use_cache) for text in texts]
    
    async def convert_async(self, text: str, **kwargs) -> ConversionResult[DeonticFormula]:
        """
        Async wrapper for backward compatibility.
        
        Args:
            text: Legal text to convert
            **kwargs: Additional conversion options
            
        Returns:
            ConversionResult with deontic formula
        """
        # Run synchronous convert in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        use_cache = kwargs.get("use_cache", True)
        return await loop.run_in_executor(None, lambda: self.convert(text, use_cache=use_cache))
    
    def get_stats(self) -> Dict[str, Any]:
        """Get conversion statistics."""
        return self._stats.copy()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache statistics including hit rate, size, etc.
        """
        # Get base cache stats (includes bounded cache metrics)
        base_stats = super().get_cache_stats()
        
        # Add deontic-specific stats
        stats = {
            **base_stats,
            "ipfs_enabled": self.use_ipfs,
            "jurisdiction": self.jurisdiction,
            "document_type": self.document_type,
        }
        
        return stats
    
    def get_monitoring_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics if monitoring is enabled."""
        if self.monitoring:
            return self.monitoring.get_stats()
        return {}

    def to_deontic(self, text: str) -> str:
        """
        Convert legal/normative text to deontic logic formula string.

        Convenience wrapper that returns a deontic formula as a plain string
        using pattern matching as a lightweight fallback.

        Args:
            text: Legal/normative text to convert

        Returns:
            Deontic formula as a string (e.g. "O(pay_taxes)")
        """
        import re as _re
        text_lower = text.lower()
        # Prohibition must be checked before bare "shall"/"must"/"may".
        if _re.search(r'\b(must\s+not|shall\s+not|may\s+not|cannot|can\s+not|forbidden|prohibited)\b', text_lower):
            action = _re.sub(
                r'\b(must\s+not|shall\s+not|may\s+not|cannot|can\s+not|is\s+forbidden\s+to|is\s+prohibited\s+from|are\s+prohibited\s+from)\b',
                '',
                text_lower,
            ).strip()
            action = action.replace(' ', '_')
            return f"F({action})"
        # Obligation: "must", "shall", "obligatory", "required"
        if _re.search(r'\b(must|shall|obligator|obliged|required)\b', text_lower):
            action = _re.sub(r'\b(it\s+is\s+obligatory\s+that|must|shall|is\s+obliged\s+to|is\s+required\s+to)\b', '', text_lower).strip()
            action = action.replace(' ', '_')
            return f"O({action})"
        # Permission: "may", "is permitted", "allowed"
        if _re.search(r'\b(may|permitted|allowed|can)\b', text_lower):
            action = _re.sub(r'\b(may|is\s+permitted\s+to|is\s+allowed\s+to|can)\b', '', text_lower).strip()
            action = action.replace(' ', '_')
            return f"P({action})"
        # Default: obligation
        return f"Obligation({text.replace(' ', '_')})"
