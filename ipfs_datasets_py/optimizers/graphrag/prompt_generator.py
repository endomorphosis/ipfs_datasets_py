"""
Prompt Generator for Ontology Extraction.

This module provides dynamic prompt generation for AI model-based ontology
extraction. It incorporates critic feedback, domain knowledge, and few-shot
examples to guide the extraction process.

Key Features:
    - Context-aware prompt generation
    - Critic feedback incorporation
    - Few-shot example selection
    - Domain-specific templates
    - Adaptive prompt refinement

Example:
    >>> from ipfs_datasets_py.optimizers.graphrag import (
    ...     PromptGenerator,
    ...     OntologyGenerationContext
    ... )
    >>> 
    >>> generator = PromptGenerator()
    >>> 
    >>> prompt = generator.generate_extraction_prompt(
    ...     context=context,
    ...     feedback=critic_score,
    ...     examples=example_ontologies
    ... )
    >>> print(prompt)

References:
    - complaint-generator: Dynamic prompt engineering patterns
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PromptTemplate:
    """
    Template for extraction prompts.
    
    Defines the structure of prompts used for ontology extraction, including
    system instructions, user message template, and examples.
    
    Attributes:
        system_prompt: System-level instructions for the AI model
        user_prompt_template: Template for user messages with placeholders
        examples: Few-shot examples to include
        parameters: Additional parameters for prompt generation
        
    Example:
        >>> template = PromptTemplate(
        ...     system_prompt="You are an expert ontology extractor...",
        ...     user_prompt_template="Extract entities from: {text}",
        ...     examples=[{'input': '...', 'output': '...'}],
        ...     parameters={'temperature': 0.7}
        ... )
    """
    
    system_prompt: str
    user_prompt_template: str
    examples: List[Dict[str, Any]] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    def format(self, **kwargs) -> str:
        """
        Format the template with provided values.
        
        Args:
            **kwargs: Values to substitute into template
            
        Returns:
            Formatted prompt string
        """
        return self.user_prompt_template.format(**kwargs)


class PromptGenerator:
    """
    Generate dynamic prompts for ontology extraction.
    
    Creates context-aware prompts that incorporate domain knowledge, critic
    feedback, and few-shot examples to guide AI models in extracting high-quality
    ontologies from arbitrary data.
    
    The generator adapts prompts based on previous results, focusing on areas
    identified as weak by the critic and incorporating successful patterns from
    high-scoring ontologies.
    
    Example:
        >>> generator = PromptGenerator()
        >>> 
        >>> # Generate initial prompt
        >>> prompt = generator.generate_extraction_prompt(context)
        >>> 
        >>> # Generate refined prompt with feedback
        >>> refined_prompt = generator.generate_extraction_prompt(
        ...     context,
        ...     feedback=critic_score
        ... )
        >>> 
        >>> # Adapt existing prompt
        >>> adapted = generator.adapt_prompt_from_feedback(
        ...     base_prompt,
        ...     critic_score
        ... )
    """
    
    def __init__(self, template_library: Optional[Dict[str, PromptTemplate]] = None):
        """
        Initialize the prompt generator.
        
        Args:
            template_library: Optional dictionary of domain-specific templates.
                If None, uses default templates.
        """
        self.template_library = template_library or self._create_default_templates()
        logger.info(f"Initialized PromptGenerator with {len(self.template_library)} templates")
    
    def _create_default_templates(self) -> Dict[str, PromptTemplate]:
        """Create default prompt templates for common domains."""
        templates = {}
        
        # General template
        templates['general'] = PromptTemplate(
            system_prompt=(
                "You are an expert knowledge engineer extracting structured ontologies. "
                "Your task is to identify entities, their types, properties, and relationships "
                "from the given text. Be precise, comprehensive, and maintain logical consistency."
            ),
            user_prompt_template=(
                "Extract a complete ontology from the following {data_type} data:\n\n"
                "{data}\n\n"
                "Provide:\n"
                "1. All entities with their types and properties\n"
                "2. All relationships between entities\n"
                "3. Confidence scores for each extraction\n"
            ),
            parameters={'temperature': 0.3}
        )
        
        # Legal domain template
        templates['legal'] = PromptTemplate(
            system_prompt=(
                "You are a legal knowledge engineer specialized in extracting formal "
                "ontologies from legal documents. Focus on:\n"
                "- Agents (parties, organizations, individuals)\n"
                "- Obligations (must, shall, required to)\n"
                "- Permissions (may, allowed to, can)\n"
                "- Prohibitions (must not, forbidden, prohibited)\n"
                "- Temporal constraints (deadlines, durations)\n"
                "- Conditions (if, when, provided that)\n"
                "Maintain strict logical consistency suitable for formal verification."
            ),
            user_prompt_template=(
                "Extract legal ontology from:\n\n"
                "{data}\n\n"
                "Identify:\n"
                "1. All parties and their roles\n"
                "2. All obligations, permissions, and prohibitions\n"
                "3. Temporal constraints and conditions\n"
                "4. Relationships between legal concepts\n"
            ),
            parameters={'temperature': 0.2}
        )
        
        # Medical domain template
        templates['medical'] = PromptTemplate(
            system_prompt=(
                "You are a medical knowledge engineer extracting clinical ontologies. "
                "Focus on:\n"
                "- Patients, providers, and healthcare entities\n"
                "- Diagnoses and conditions\n"
                "- Treatments and procedures\n"
                "- Medications and dosages\n"
                "- Symptoms and observations\n"
                "- Temporal relationships (onset, duration, resolution)\n"
                "Use standard medical terminology where applicable."
            ),
            user_prompt_template=(
                "Extract medical ontology from:\n\n"
                "{data}\n\n"
                "Identify:\n"
                "1. All medical entities (patients, conditions, treatments)\n"
                "2. Relationships between entities\n"
                "3. Temporal information\n"
                "4. Clinical significance and confidence\n"
            ),
            parameters={'temperature': 0.2}
        )
        
        # Scientific domain template
        templates['scientific'] = PromptTemplate(
            system_prompt=(
                "You are a scientific knowledge engineer extracting research ontologies. "
                "Focus on:\n"
                "- Entities (objects, materials, organisms, concepts)\n"
                "- Processes and mechanisms\n"
                "- Measurements and observations\n"
                "- Hypotheses and conclusions\n"
                "- Experimental relationships\n"
                "Maintain scientific rigor and precision."
            ),
            user_prompt_template=(
                "Extract scientific ontology from:\n\n"
                "{data}\n\n"
                "Identify:\n"
                "1. All scientific entities and their properties\n"
                "2. Processes and mechanisms\n"
                "3. Causal and correlational relationships\n"
                "4. Measurements and their uncertainties\n"
            ),
            parameters={'temperature': 0.3}
        )
        
        return templates
    
    def generate_extraction_prompt(
        self,
        context: Any,  # OntologyGenerationContext
        feedback: Optional[Any] = None,  # Optional[CriticScore]
        examples: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        Generate extraction prompt for ontology generation.
        
        Creates a comprehensive prompt that guides the AI model to extract
        high-quality ontologies. Incorporates domain knowledge, critic feedback,
        and few-shot examples as appropriate.
        
        Args:
            context: Generation context with domain and configuration
            feedback: Optional critic feedback from previous attempt
            examples: Optional few-shot examples to include
            
        Returns:
            Generated prompt string
            
        Example:
            >>> prompt = generator.generate_extraction_prompt(
            ...     context=OntologyGenerationContext(
            ...         data_source='contract.pdf',
            ...         data_type='pdf',
            ...         domain='legal'
            ...     ),
            ...     feedback=CriticScore(completeness=0.65, ...),
            ...     examples=[good_ontology_example]
            ... )
        """
        logger.info(f"Generating extraction prompt for domain: {getattr(context, 'domain', 'general')}")
        
        # Get appropriate template
        domain = getattr(context, 'domain', 'general')
        template = self.template_library.get(domain, self.template_library['general'])
        
        # Build prompt components
        components = []
        
        # System prompt
        components.append(f"=== Instructions ===\n{template.system_prompt}\n")
        
        # Add few-shot examples if provided
        if examples:
            components.append("\n=== Examples ===")
            for i, example in enumerate(examples[:3], 1):  # Limit to 3 examples
                components.append(f"\nExample {i}:")
                if 'input' in example:
                    components.append(f"Input: {example['input'][:200]}...")
                if 'output' in example:
                    components.append(f"Output: {example['output']}")
            components.append("")
        
        # Add feedback-based guidance if provided
        if feedback:
            components.append("\n=== Focus Areas ===")
            components.append(self._generate_feedback_guidance(feedback))
            components.append("")
        
        # Main extraction request
        components.append("\n=== Your Task ===")
        # Note: Actual data would be filled in by the caller
        user_prompt = template.user_prompt_template.format(
            data_type=getattr(context, 'data_type', 'text'),
            data="{data}"  # Placeholder
        )
        components.append(user_prompt)
        
        prompt = "\n".join(components)
        
        logger.debug(f"Generated prompt length: {len(prompt)} characters")
        return prompt
    
    def adapt_prompt_from_feedback(
        self,
        base_prompt: str,
        feedback: Any  # CriticScore
    ) -> str:
        """
        Adapt existing prompt based on critic feedback.
        
        Modifies a prompt to address specific weaknesses identified by the critic,
        adding targeted instructions to improve extraction quality.
        
        Args:
            base_prompt: Original prompt to adapt
            feedback: Critic feedback with scores and recommendations
            
        Returns:
            Adapted prompt string
            
        Example:
            >>> adapted = generator.adapt_prompt_from_feedback(
            ...     "Extract entities from text...",
            ...     CriticScore(
            ...         completeness=0.60,
            ...         consistency=0.85,
            ...         recommendations=["Add more entities"]
            ...     )
            ... )
        """
        logger.info("Adapting prompt based on critic feedback")
        
        # Generate adaptation guidance
        guidance = self._generate_feedback_guidance(feedback)
        
        # Insert guidance into prompt
        if "=== Your Task ===" in base_prompt:
            # Insert before task section
            parts = base_prompt.split("=== Your Task ===")
            adapted = (
                f"{parts[0]}\n"
                f"=== Additional Guidance ===\n"
                f"{guidance}\n\n"
                f"=== Your Task ===\n"
                f"{parts[1]}"
            )
        else:
            # Append to end
            adapted = f"{base_prompt}\n\n=== Additional Guidance ===\n{guidance}"
        
        return adapted
    
    def _generate_feedback_guidance(self, feedback: Any) -> str:
        """
        Generate targeted guidance from critic feedback.
        
        Args:
            feedback: Critic feedback with scores and recommendations
            
        Returns:
            Guidance text addressing specific weaknesses
        """
        guidance_parts = []
        
        # Check each dimension and add specific guidance
        if hasattr(feedback, 'completeness') and feedback.completeness < 0.7:
            guidance_parts.append(
                "📌 COMPLETENESS: Ensure comprehensive coverage of ALL concepts. "
                "Don't miss any entities or relationships mentioned in the text."
            )
        
        if hasattr(feedback, 'consistency') and feedback.consistency < 0.7:
            guidance_parts.append(
                "📌 CONSISTENCY: Verify logical consistency. Ensure all relationships "
                "reference valid entities and there are no contradictions."
            )
        
        if hasattr(feedback, 'clarity') and feedback.clarity < 0.7:
            guidance_parts.append(
                "📌 CLARITY: Provide clear, detailed descriptions for each entity. "
                "Include relevant properties and avoid ambiguous references."
            )
        
        if hasattr(feedback, 'granularity') and feedback.granularity < 0.7:
            guidance_parts.append(
                "📌 GRANULARITY: Adjust the level of detail appropriately. "
                "Not too coarse, not too fine-grained."
            )
        
        if hasattr(feedback, 'domain_alignment') and feedback.domain_alignment < 0.7:
            guidance_parts.append(
                "📌 DOMAIN ALIGNMENT: Use standard domain terminology and follow "
                "domain-specific conventions."
            )
        
        # Add specific recommendations if available
        if hasattr(feedback, 'recommendations') and feedback.recommendations:
            guidance_parts.append("\n📋 Specific Recommendations:")
            for rec in feedback.recommendations[:5]:  # Limit to 5 recommendations
                guidance_parts.append(f"  • {rec}")
        
        return "\n".join(guidance_parts) if guidance_parts else "Continue with careful extraction."
    
    def select_examples(
        self,
        domain: str,
        num_examples: int = 3,
        quality_threshold: float = 0.8
    ) -> List[Dict[str, Any]]:
        """
        Select high-quality few-shot examples for a domain.
        
        In a full implementation, this would query a database of successful
        ontologies filtered by domain and quality score.
        
        Args:
            domain: Target domain for examples
            num_examples: Number of examples to select
            quality_threshold: Minimum quality score for examples
            
        Returns:
            List of example dictionaries
        """
        # TODO: Implement example database integration
        # This is a placeholder for Phase 2 full implementation
        
        logger.info(
            f"Selecting {num_examples} examples for domain '{domain}' "
            f"with quality >= {quality_threshold}"
        )
        
        # Placeholder: return empty list
        # In full implementation, would query example database
        return []
    
    def get_template(self, domain: str) -> PromptTemplate:
        """
        Get prompt template for a specific domain.
        
        Args:
            domain: Domain name (e.g., 'legal', 'medical', 'scientific')
            
        Returns:
            PromptTemplate for the domain, or general template if not found
        """
        return self.template_library.get(domain, self.template_library['general'])
    
    def add_template(self, domain: str, template: PromptTemplate):
        """
        Add or update a prompt template for a domain.
        
        Args:
            domain: Domain name
            template: PromptTemplate to add
        """
        self.template_library[domain] = template
        logger.info(f"Added template for domain: {domain}")


# Export public API
__all__ = [
    'PromptGenerator',
    'PromptTemplate',
]
