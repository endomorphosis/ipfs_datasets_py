"""Logic Extractor - Extracts logical statements from arbitrary data.

This module implements an LLM-based agent that extracts formal logical
statements from various data types (text, structured data, knowledge graphs).

Analogous to the Complainant agent in the adversarial harness, the
LogicExtractor generates logical statements that can be verified and
optimized through iterative refinement.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ExtractionMode(Enum):
    """Mode of logic extraction."""
    TDFOL = "tdfol"  # Temporal Deontic First-Order Logic
    FOL = "fol"  # First-Order Logic
    CEC = "cec"  # Cognitive Event Calculus
    MODAL = "modal"  # Modal Logic
    DEONTIC = "deontic"  # Deontic Logic
    AUTO = "auto"  # Automatic mode selection


class DataType(Enum):
    """Type of input data."""
    TEXT = "text"
    JSON = "json"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    STRUCTURED = "structured"
    MIXED = "mixed"


@dataclass
class LogicExtractionContext:
    """Context for logic extraction.
    
    Attributes:
        data: Input data to extract logic from
        data_type: Type of input data
        extraction_mode: Logic formalism to extract
        domain: Domain context (legal, medical, general, etc.)
        ontology: Knowledge graph ontology to align with
        previous_extractions: Previous extraction results for consistency
        hints: Optional hints for extraction
    """
    data: Any
    data_type: DataType = DataType.TEXT
    extraction_mode: ExtractionMode = ExtractionMode.AUTO
    domain: str = "general"
    ontology: Optional[Dict[str, Any]] = None
    previous_extractions: List['ExtractionResult'] = field(default_factory=list)
    hints: Optional[List[str]] = None


@dataclass
class LogicalStatement:
    """A single extracted logical statement.
    
    Attributes:
        formula: The logical formula in target formalism
        natural_language: Natural language representation
        confidence: Confidence score (0.0-1.0)
        formalism: Logic formalism used
        metadata: Additional metadata about the statement
    """
    formula: str
    natural_language: str
    confidence: float
    formalism: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    """Result of logic extraction.
    
    Attributes:
        statements: List of extracted logical statements
        context: The extraction context
        success: Whether extraction succeeded
        errors: Any errors encountered
        reasoning_trace: Step-by-step reasoning process
        ontology_alignment: How statements align with ontology
    """
    statements: List[LogicalStatement]
    context: LogicExtractionContext
    success: bool = True
    errors: List[str] = field(default_factory=list)
    reasoning_trace: List[str] = field(default_factory=list)
    ontology_alignment: Dict[str, float] = field(default_factory=dict)


class LogicExtractor:
    """LLM-based agent for extracting logical statements from arbitrary data.
    
    This agent uses AI models (via ipfs_accelerate_py) to extract formal
    logical statements from various data types. It can:
    - Parse natural language into formal logic
    - Extract logical structure from structured data
    - Maintain consistency with knowledge graph ontologies
    - Adapt extraction based on feedback
    
    Example:
        >>> extractor = LogicExtractor(model="gpt-4")
        >>> context = LogicExtractionContext(
        ...     data="All employees must complete training within 30 days",
        ...     extraction_mode=ExtractionMode.TDFOL,
        ...     domain="legal"
        ... )
        >>> result = extractor.extract(context)
        >>> print(result.statements[0].formula)
        ∀x (Employee(x) → ◇≤30 Completed(x, training))
    """
    
    def __init__(
        self,
        model: Optional[str] = None,
        backend: Optional[Any] = None,
        use_ipfs_accelerate: bool = True,
        enable_formula_translation: bool = True
    ):
        """Initialize the logic extractor.
        
        Args:
            model: Model name to use (e.g., "gpt-4", "claude-3")
            backend: Backend for LLM inference
            use_ipfs_accelerate: Use ipfs_accelerate_py for model inference
            enable_formula_translation: Use TDFOL/CEC translation (Phase 2 feature)
        """
        self.model = model or "gpt-4"
        self.backend = backend
        self.use_ipfs_accelerate = use_ipfs_accelerate
        self.enable_formula_translation = enable_formula_translation
        self._init_backend()
        
        # Track extraction history for improvement
        self.extraction_history: List[ExtractionResult] = []
        
        # Phase 2: Initialize formula translator
        self.formula_translator = None
        if enable_formula_translation:
            self._init_formula_translator()
    
    def _init_formula_translator(self) -> None:
        """Initialize formula translator (Phase 2)."""
        try:
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_translation import UnifiedFormulaTranslator
            self.formula_translator = UnifiedFormulaTranslator()
            logger.info("Formula translator initialized")
        except Exception as e:
            logger.warning(f"Could not initialize formula translator: {e}")
            self.formula_translator = None
        
    def _init_backend(self) -> None:
        """Initialize the LLM backend."""
        if self.backend is None and self.use_ipfs_accelerate:
            try:
                # Try to import ipfs_accelerate_py
                import ipfs_accelerate_py
                logger.info("Using ipfs_accelerate_py for model inference")
                # Initialize backend here
                # self.backend = ipfs_accelerate_py.get_backend(self.model)
            except ImportError:
                logger.warning("ipfs_accelerate_py not available, using fallback")
                self.backend = None
    
    def extract(self, context: LogicExtractionContext) -> ExtractionResult:
        """Extract logical statements from data.
        
        Args:
            context: Extraction context with data and configuration
            
        Returns:
            ExtractionResult with extracted statements
        """
        try:
            # Determine the extraction mode if auto
            if context.extraction_mode == ExtractionMode.AUTO:
                context.extraction_mode = self._determine_mode(context)
            
            # Phase 2: Use formula translation if available
            if self.formula_translator and context.extraction_mode in [ExtractionMode.TDFOL, ExtractionMode.CEC]:
                return self._extract_with_translation(context)
            
            # Phase 1: Legacy extraction method
            # Build the extraction prompt
            prompt = self._build_extraction_prompt(context)
            
            # Get LLM response
            response = self._query_llm(prompt, context)
            
            # Parse response into logical statements
            statements = self._parse_response(response, context)
            
            # Check ontology alignment
            alignment = self._check_ontology_alignment(statements, context)
            
            result = ExtractionResult(
                statements=statements,
                context=context,
                success=True,
                ontology_alignment=alignment
            )
            
            # Track for improvement
            self.extraction_history.append(result)
            
            return result
            
        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            return ExtractionResult(
                statements=[],
                context=context,
                success=False,
                errors=[str(e)]
            )
    
    def _extract_with_translation(
        self,
        context: LogicExtractionContext
    ) -> ExtractionResult:
        """Extract using formula translation (Phase 2).
        
        Args:
            context: Extraction context
            
        Returns:
            ExtractionResult with translated formulas
        """
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_translation import FormulaFormalism
        
        # Map extraction mode to formalism
        formalism_map = {
            ExtractionMode.TDFOL: FormulaFormalism.TDFOL,
            ExtractionMode.CEC: FormulaFormalism.CEC,
            ExtractionMode.DEONTIC: FormulaFormalism.DEONTIC,
            ExtractionMode.MODAL: FormulaFormalism.MODAL,
            ExtractionMode.FOL: FormulaFormalism.FOL
        }
        
        formalism = formalism_map.get(context.extraction_mode, FormulaFormalism.TDFOL)
        
        # Translate data to formal logic
        translation_result = self.formula_translator.translate(
            str(context.data),
            formalism=formalism,
            context={'domain': context.domain}
        )
        
        if not translation_result.success:
            logger.warning(f"Translation failed: {translation_result.errors}")
            # Fallback to legacy extraction
            return self._extract_legacy(context)
        
        # Create logical statement from translation
        statement = LogicalStatement(
            formula=str(translation_result.formula),
            natural_language=translation_result.original_text,
            confidence=0.85,  # Higher confidence for formal translation
            formalism=translation_result.formalism.value,
            metadata={
                'translation_metadata': translation_result.metadata,
                'translator': 'formula_translation'
            }
        )
        
        # Check ontology alignment
        alignment = self._check_ontology_alignment([statement], context)
        
        result = ExtractionResult(
            statements=[statement],
            context=context,
            success=True,
            ontology_alignment=alignment,
            reasoning_trace=[f"Translated to {formalism.value} using formula translator"]
        )
        
        self.extraction_history.append(result)
        return result
    
    def _extract_legacy(self, context: LogicExtractionContext) -> ExtractionResult:
        """Legacy extraction method (Phase 1).
        
        Args:
            context: Extraction context
            
        Returns:
            ExtractionResult
        """
        prompt = self._build_extraction_prompt(context)
        response = self._query_llm(prompt, context)
        statements = self._parse_response(response, context)
        alignment = self._check_ontology_alignment(statements, context)
        
        return ExtractionResult(
            statements=statements,
            context=context,
            success=True,
            ontology_alignment=alignment
        )
    
    def extract_batch(
        self,
        contexts: List[LogicExtractionContext]
    ) -> List[ExtractionResult]:
        """Extract logical statements from multiple contexts.
        
        Args:
            contexts: List of extraction contexts
            
        Returns:
            List of extraction results
        """
        return [self.extract(ctx) for ctx in contexts]
    
    def _determine_mode(self, context: LogicExtractionContext) -> ExtractionMode:
        """Automatically determine the best extraction mode.
        
        Args:
            context: Extraction context
            
        Returns:
            Chosen extraction mode
        """
        # Simple heuristic - can be made smarter
        if context.domain == "legal":
            return ExtractionMode.TDFOL
        elif "time" in str(context.data).lower():
            return ExtractionMode.CEC
        elif "must" in str(context.data).lower() or "obligation" in str(context.data).lower():
            return ExtractionMode.DEONTIC
        else:
            return ExtractionMode.FOL
    
    def _build_extraction_prompt(self, context: LogicExtractionContext) -> str:
        """Build the prompt for LLM extraction.
        
        Args:
            context: Extraction context
            
        Returns:
            Prompt string
        """
        prompt_parts = []
        
        # System context
        prompt_parts.append(f"You are an expert in {context.extraction_mode.value} formal logic.")
        prompt_parts.append(f"Domain: {context.domain}")
        
        # Task description
        prompt_parts.append("\nTask: Extract formal logical statements from the following data:")
        prompt_parts.append(f"\nData: {context.data}")
        
        # Ontology context if available
        if context.ontology:
            prompt_parts.append(f"\nOntology context: {context.ontology}")
        
        # Previous extractions for consistency
        if context.previous_extractions:
            prompt_parts.append("\nPrevious extractions for consistency:")
            for prev in context.previous_extractions[-3:]:  # Last 3
                for stmt in prev.statements[:2]:  # Top 2 statements
                    prompt_parts.append(f"  - {stmt.formula}")
        
        # Hints
        if context.hints:
            prompt_parts.append("\nHints:")
            for hint in context.hints:
                prompt_parts.append(f"  - {hint}")
        
        # Output format
        prompt_parts.append("\nProvide:")
        prompt_parts.append("1. Formal logical formula")
        prompt_parts.append("2. Natural language explanation")
        prompt_parts.append("3. Confidence score (0.0-1.0)")
        
        return "\n".join(prompt_parts)
    
    def _query_llm(self, prompt: str, context: LogicExtractionContext) -> str:
        """Query the LLM with the extraction prompt.
        
        Args:
            prompt: The prompt to send
            context: Extraction context
            
        Returns:
            LLM response text
        """
        if self.backend:
            # Use actual backend
            # response = self.backend.generate(prompt)
            # return response
            pass
        
        # Fallback mock response for testing
        logger.warning("Using mock LLM response")
        return self._mock_llm_response(context)
    
    def _mock_llm_response(self, context: LogicExtractionContext) -> str:
        """Generate a mock LLM response for testing.
        
        Args:
            context: Extraction context
            
        Returns:
            Mock response
        """
        data_str = str(context.data)
        
        # Simple pattern matching for demo
        if "must" in data_str.lower():
            return """
            Formula: ∀x (Subject(x) → Obligated(x, Action))
            Explanation: All subjects have an obligation to perform the action
            Confidence: 0.85
            """
        else:
            return """
            Formula: ∀x (P(x) → Q(x))
            Explanation: For all x, if P holds for x, then Q holds for x
            Confidence: 0.75
            """
    
    def _parse_response(
        self,
        response: str,
        context: LogicExtractionContext
    ) -> List[LogicalStatement]:
        """Parse LLM response into logical statements.
        
        Args:
            response: LLM response text
            context: Extraction context
            
        Returns:
            List of logical statements
        """
        statements = []
        
        # Simple parsing - can be made more sophisticated
        lines = response.strip().split('\n')
        formula = None
        explanation = None
        confidence = 0.5
        
        for line in lines:
            line = line.strip()
            if line.startswith('Formula:'):
                formula = line.split(':', 1)[1].strip()
            elif line.startswith('Explanation:'):
                explanation = line.split(':', 1)[1].strip()
            elif line.startswith('Confidence:'):
                try:
                    confidence = float(line.split(':', 1)[1].strip())
                except ValueError:
                    confidence = 0.5
        
        if formula and explanation:
            statements.append(LogicalStatement(
                formula=formula,
                natural_language=explanation,
                confidence=confidence,
                formalism=context.extraction_mode.value,
                metadata={'source': 'llm_extraction'}
            ))
        
        return statements
    
    def _check_ontology_alignment(
        self,
        statements: List[LogicalStatement],
        context: LogicExtractionContext
    ) -> Dict[str, float]:
        """Check how well statements align with the ontology.
        
        Args:
            statements: Extracted statements
            context: Extraction context
            
        Returns:
            Alignment scores by category
        """
        if not context.ontology:
            return {}
        
        # Simple alignment check - can be made more sophisticated
        alignment = {
            'terminology': 0.0,
            'structure': 0.0,
            'consistency': 0.0
        }
        
        # Check if terms from ontology appear in statements
        if statements:
            ontology_terms = set(str(context.ontology).lower().split())
            statement_terms = set()
            for stmt in statements:
                statement_terms.update(stmt.formula.lower().split())
            
            overlap = len(ontology_terms & statement_terms)
            if ontology_terms:
                alignment['terminology'] = overlap / len(ontology_terms)
        
        # Default scores for structure and consistency
        alignment['structure'] = 0.7
        alignment['consistency'] = 0.8
        
        return alignment
    
    def improve_from_feedback(
        self,
        feedback: Dict[str, Any]
    ) -> None:
        """Improve extraction based on critic feedback.
        
        This is the SGD-like update step where the extractor
        learns from critic evaluations.
        
        Args:
            feedback: Feedback from the critic
        """
        # Update extraction strategy based on feedback
        # This could adjust prompts, confidence thresholds, etc.
        logger.info(f"Received feedback: {feedback}")
        
        # Example: adjust confidence threshold based on accuracy feedback
        if 'accuracy' in feedback and feedback['accuracy'] < 0.5:
            logger.info("Low accuracy detected, adjusting extraction strategy")
