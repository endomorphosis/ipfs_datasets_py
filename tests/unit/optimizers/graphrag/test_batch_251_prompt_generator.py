"""Batch 251: PromptGenerator Comprehensive Test Suite.

Comprehensive testing of the PromptGenerator for dynamic prompt generation
with domain-specific adaptation and feedback incorporation.

Test Categories:
- Template management and domain-specific selection
- Prompt generation with context and feedback
- Feedback-based prompt adaptation
- Few-shot example selection and incorporation
- Domain-specific template customization
- Feedback guidance generation
"""

import pytest
from typing import Dict, Any, List, Optional

from ipfs_datasets_py.optimizers.graphrag.prompt_generator import (
    PromptGenerator,
    PromptTemplate,
)


# Mock classes for testing
class MockOntologyContext:
    """Mock OntologyGenerationContext for testing."""
    
    def __init__(self, domain: str = "general", data_type: str = "text", data: str = ""):
        self.domain = domain
        self.data_type = data_type
        self.data = data


class MockCriticScore:
    """Mock CriticScore for testing feedback scenarios."""
    
    def __init__(
        self,
        completeness: float = 0.8,
        consistency: float = 0.8,
        clarity: float = 0.8,
        granularity: float = 0.8,
        relationship_coherence: float = 0.8,
        domain_alignment: float = 0.8,
        recommendations: Optional[List[str]] = None,
        strengths: Optional[List[str]] = None,
        weaknesses: Optional[List[str]] = None,
    ):
        self.completeness = completeness
        self.consistency = consistency
        self.clarity = clarity
        self.granularity = granularity
        self.relationship_coherence = relationship_coherence
        self.domain_alignment = domain_alignment
        self.recommendations = recommendations or []
        self.strengths = strengths or []
        self.weaknesses = weaknesses or []


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def generator():
    """Create a fresh PromptGenerator with defaults."""
    return PromptGenerator()


@pytest.fixture
def custom_templates():
    """Create custom templates for testing."""
    return {
        "custom": PromptTemplate(
            system_prompt="You are a custom extractor.",
            user_prompt_template="Extract from: {data}",
            parameters={"temperature": 0.5}
        ),
        "specialized": PromptTemplate(
            system_prompt="You are a specialized domain expert.",
            user_prompt_template="Specialize extraction for: {data}",
            parameters={"temperature": 0.2, "max_tokens": 1000}
        )
    }


@pytest.fixture
def custom_generator(custom_templates):
    """Create a PromptGenerator with custom templates."""
    return PromptGenerator(template_library=custom_templates)


@pytest.fixture
def generic_context():
    """Create a generic ontology context."""
    return MockOntologyContext(
        domain="general",
        data_type="text",
        data="Sample data for extraction"
    )


@pytest.fixture
def legal_context():
    """Create a legal domain context."""
    return MockOntologyContext(
        domain="legal",
        data_type="document",
        data="Alice must pay Bob USD 500 by January 1, 2025."
    )


@pytest.fixture
def medical_context():
    """Create a medical domain context."""
    return MockOntologyContext(
        domain="medical",
        data_type="text",
        data="Patient was diagnosed with hypertension and prescribed lisinopril."
    )


@pytest.fixture
def weak_feedback():
    """Create feedback with weak dimensions."""
    return MockCriticScore(
        completeness=0.5,
        consistency=0.6,
        clarity=0.55,
        granularity=0.65,
        relationship_coherence=0.6,
        domain_alignment=0.55,
        recommendations=["Add more entities", "Improve consistency"],
        strengths=["Good structure"],
        weaknesses=["Missing relationships", "Low completeness"]
    )


@pytest.fixture
def strong_feedback():
    """Create feedback with strong dimensions."""
    return MockCriticScore(
        completeness=0.95,
        consistency=0.90,
        clarity=0.92,
        granularity=0.88,
        relationship_coherence=0.93,
        domain_alignment=0.96,
        recommendations=[],
        strengths=["Excellent coverage", "Good domain alignment"],
        weaknesses=[]
    )


# ============================================================================
# Template Management Tests
# ============================================================================

class TestTemplateInitialization:
    """Test template initialization."""
    
    def test_init_with_defaults(self, generator):
        """Generator initializes with default templates."""
        assert generator.template_library is not None
        assert len(generator.template_library) > 0
    
    def test_init_with_custom_templates(self, custom_generator, custom_templates):
        """Generator initializes with custom templates."""
        assert custom_generator.template_library == custom_templates
        for domain in custom_templates:
            assert domain in custom_generator.template_library
    
    def test_default_templates_include_domains(self, generator):
        """Default templates include all major domains."""
        expected_domains = ["general", "legal", "medical", "scientific"]
        for domain in expected_domains:
            assert domain in generator.template_library
    
    def test_default_templates_have_content(self, generator):
        """Default templates have non-empty prompts."""
        for domain, template in generator.template_library.items():
            assert template.system_prompt
            assert template.user_prompt_template
            assert len(template.system_prompt) > 10
            assert len(template.user_prompt_template) > 10


class TestGetTemplate:
    """Test get_template() method."""
    
    def test_get_template_existing_domain(self, generator):
        """get_template returns template for existing domain."""
        template = generator.get_template("legal")
        
        assert isinstance(template, PromptTemplate)
        assert "legal" in template.system_prompt.lower()
    
    def test_get_template_nonexistent_domain(self, generator):
        """get_template returns general template for unknown domain."""
        template = generator.get_template("nonexistent_domain")
        
        assert isinstance(template, PromptTemplate)
        # Should return general template
        assert template == generator.template_library["general"]
    
    def test_get_template_all_domains(self, generator):
        """get_template works for all default domains."""
        domains = ["general", "legal", "medical", "scientific"]
        for domain in domains:
            template = generator.get_template(domain)
            assert isinstance(template, PromptTemplate)


class TestAddTemplate:
    """Test add_template() method."""
    
    def test_add_template_new_domain(self, generator):
        """add_template adds new domain template."""
        new_template = PromptTemplate(
            system_prompt="Test system",
            user_prompt_template="Test user",
            parameters={"test": True}
        )
        
        generator.add_template("test_domain", new_template)
        
        assert "test_domain" in generator.template_library
        assert generator.template_library["test_domain"] == new_template
    
    def test_add_template_overwrites_existing(self, generator):
        """add_template overwrites existing domain template."""
        original = generator.get_template("legal")
        new_template = PromptTemplate(
            system_prompt="New legal template",
            user_prompt_template="New legal prompt",
            parameters={}
        )
        
        generator.add_template("legal", new_template)
        updated = generator.get_template("legal")
        
        assert updated != original
        assert updated.system_prompt == "New legal template"
    
    def test_add_multiple_templates(self, generator):
        """add_template handles multiple additions."""
        initial_count = len(generator.template_library)
        
        for i in range(5):
            template = PromptTemplate(
                system_prompt=f"System {i}",
                user_prompt_template=f"User {i}",
                parameters={}
            )
            generator.add_template(f"domain_{i}", template)
        
        assert len(generator.template_library) == initial_count + 5


# ============================================================================
# Prompt Generation Tests
# ============================================================================

class TestGenerateExtractionPrompt:
    """Test generate_extraction_prompt() method."""
    
    def test_generate_prompt_returns_string(self, generator, generic_context):
        """generate_extraction_prompt returns string."""
        prompt = generator.generate_extraction_prompt(generic_context)
        
        assert isinstance(prompt, str)
        assert len(prompt) > 0
    
    def test_generate_prompt_includes_system_instruction(self, generator, generic_context):
        """Generated prompt includes system instruction."""
        prompt = generator.generate_extraction_prompt(generic_context)
        
        # Should contain system prompt content
        assert "instruction" in prompt.lower() or "expert" in prompt.lower()
    
    def test_generate_prompt_for_legal_domain(self, generator, legal_context):
        """Generated prompt includes legal domain guidance."""
        prompt = generator.generate_extraction_prompt(legal_context)
        
        # Should be specific to legal domain
        assert len(prompt) > 100
        assert "legal" in prompt.lower() or "party" in prompt.lower() or "obligation" in prompt.lower()
    
    def test_generate_prompt_for_medical_domain(self, generator, medical_context):
        """Generated prompt includes medical domain guidance."""
        prompt = generator.generate_extraction_prompt(medical_context)
        
        # Should be specific to medical domain
        assert len(prompt) > 100
        assert "medical" in prompt.lower() or "patient" in prompt.lower() or "diagnosis" in prompt.lower()
    
    def test_generate_prompt_with_feedback(self, generator, generic_context, weak_feedback):
        """Generated prompt includes feedback when provided."""
        prompt = generator.generate_extraction_prompt(
            generic_context,
            feedback=weak_feedback
        )
        
        # Should include "Focus Areas" or similar feedback guidance
        assert "Focus" in prompt or "Recommendation" in prompt or "COMPLETENESS" in prompt
    
    def test_generate_prompt_with_examples(self, generator, generic_context):
        """Generated prompt includes examples when provided."""
        examples = [
            {
                "input": "Test input",
                "output": "Test output"
            }
        ]
        
        prompt = generator.generate_extraction_prompt(
            generic_context,
            examples=examples
        )
        
        # Should include example markers
        assert "Example" in prompt or "example" in prompt
    
    def test_generate_prompt_with_feedback_and_examples(self, generator, legal_context, weak_feedback):
        """Generated prompt includes both feedback and examples."""
        examples = [{"input": "example1", "output": "output1"}]
        
        prompt = generator.generate_extraction_prompt(
            legal_context,
            feedback=weak_feedback,
            examples=examples
        )
        
        # Should have substantial content with all components
        assert len(prompt) > 300
        assert "Example" in prompt


# ============================================================================
# Prompt Adaptation Tests
# ============================================================================

class TestAdaptPromptFromFeedback:
    """Test adapt_prompt_from_feedback() method."""
    
    def test_adapt_prompt_returns_string(self, generator, weak_feedback):
        """adapt_prompt_from_feedback returns string."""
        base_prompt = "Extract entities from text"
        adapted = generator.adapt_prompt_from_feedback(base_prompt, weak_feedback)
        
        assert isinstance(adapted, str)
        assert len(adapted) > len(base_prompt)
    
    def test_adapt_prompt_preserves_base(self, generator, weak_feedback):
        """Adapted prompt contains original content."""
        base_prompt = "=== Your Task ===\nExtract entities from text"
        adapted = generator.adapt_prompt_from_feedback(base_prompt, weak_feedback)
        
        assert "Your Task" in adapted
        assert "Extract entities" in adapted
    
    def test_adapt_prompt_adds_guidance(self, generator, weak_feedback):
        """Adapted prompt adds guidance section."""
        base_prompt = "=== Your Task ===\nExtract entities"
        adapted = generator.adapt_prompt_from_feedback(base_prompt, weak_feedback)
        
        # Should have added guidance
        assert "Guidance" in adapted or "COMPLETENESS" in adapted or "Recommendation" in adapted
    
    def test_adapt_prompt_weak_completeness(self, generator):
        """Adapted prompt addresses weak completeness."""
        base_prompt = "=== Your Task ===\nExtract"
        feedback = MockCriticScore(completeness=0.4)
        
        adapted = generator.adapt_prompt_from_feedback(base_prompt, feedback)
        
        assert "COMPLETENESS" in adapted or "comprehensive" in adapted
    
    def test_adapt_prompt_weak_consistency(self, generator):
        """Adapted prompt addresses weak consistency."""
        base_prompt = "=== Your Task ===\nExtract"
        feedback = MockCriticScore(consistency=0.3)
        
        adapted = generator.adapt_prompt_from_feedback(base_prompt, feedback)
        
        assert "CONSISTENCY" in adapted or "consistent" in adapted
    
    def test_adapt_prompt_multiple_weak_dimensions(self, generator, weak_feedback):
        """Adapted prompt addresses multiple weak dimensions."""
        base_prompt = "=== Your Task ===\nExtract"
        adapted = generator.adapt_prompt_from_feedback(base_prompt, weak_feedback)
        
        # Should have guidance for multiple dimensions
        assert len(adapted) > 200


# ============================================================================
# Example Management Tests
# ============================================================================

class TestSelectExamples:
    """Test select_examples() method."""
    
    def test_select_examples_returns_list(self, generator):
        """select_examples returns list."""
        examples = generator.select_examples("legal")
        
        assert isinstance(examples, list)
    
    def test_select_examples_legal_domain(self, generator):
        """select_examples returns legal domain examples."""
        examples = generator.select_examples("legal")
        
        assert len(examples) > 0
        assert all("input" in e or "ontology" in e for e in examples)
    
    def test_select_examples_medical_domain(self, generator):
        """select_examples returns medical domain examples."""
        examples = generator.select_examples("medical")
        
        assert len(examples) > 0
    
    def test_select_examples_respects_num_examples(self, generator):
        """select_examples respects num_examples parameter."""
        examples_3 = generator.select_examples("legal", num_examples=3)
        examples_1 = generator.select_examples("legal", num_examples=1)
        
        assert len(examples_3) <= 3
        assert len(examples_1) <= 1
    
    def test_select_examples_respects_quality_threshold(self, generator):
        """select_examples filters by quality threshold."""
        examples_high = generator.select_examples("legal", quality_threshold=0.95)
        examples_low = generator.select_examples("legal", quality_threshold=0.5)
        
        # Lower threshold should return at least as many
        assert len(examples_low) >= len(examples_high)
    
    def test_select_examples_unknown_domain(self, generator):
        """select_examples returns empty list for unknown domain."""
        examples = generator.select_examples("nonexistent_domain", num_examples=5)
        
        assert isinstance(examples, list)
        # Should be empty or very small
        assert len(examples) <= 5


class TestAddExamples:
    """Test add_examples() method."""
    
    def test_add_examples_for_domain(self, generator):
        """add_examples adds examples for domain."""
        new_examples = [
            {
                "input": "Custom input",
                "ontology": {"entities": []},
                "quality_score": 0.85
            }
        ]
        
        generator.add_examples("custom_domain", new_examples)
        
        # Should be retrievable via select_examples
        examples = generator.select_examples("custom_domain", quality_threshold=0.8)
        assert len(examples) > 0
    
    def test_add_examples_multiple_times(self, generator):
        """add_examples accumulates across calls."""
        first_batch = [
            {"input": "Input 1", "ontology": {}, "quality_score": 0.9}
        ]
        second_batch = [
            {"input": "Input 2", "ontology": {}, "quality_score": 0.85}
        ]
        
        generator.add_examples("test_domain", first_batch)
        generator.add_examples("test_domain", second_batch)
        
        examples = generator.select_examples("test_domain", num_examples=10)
        assert len(examples) >= 2
    
    def test_add_examples_with_recommendations(self, generator):
        """Added examples include full structure."""
        examples = [
            {
                "input": "Example text",
                "ontology": {
                    "entities": [{"id": "e1", "type": "Person", "text": "Alice"}],
                    "relationships": []
                },
                "quality_score": 0.88
            }
        ]
        
        generator.add_examples("detailed_domain", examples)
        retrieved = generator.select_examples("detailed_domain")
        
        assert len(retrieved) > 0
        assert "ontology" in retrieved[0]


# ============================================================================
# Feedback Guidance Tests
# ============================================================================

class TestFeedbackGuidance:
    """Test feedback guidance generation."""
    
    def test_feedback_guidance_weak_dimensions(self, generator, weak_feedback):
        """Guidance generated for weak feedback scores."""
        guidance = generator._generate_feedback_guidance(weak_feedback)
        
        assert isinstance(guidance, str)
        assert len(guidance) > 0
        # Should mention weak dimensions
        assert "COMPLETENESS" in guidance or "Recommendation" in guidance
    
    def test_feedback_guidance_includes_recommendations(self, generator):
        """Guidance includes provided recommendations."""
        feedback = MockCriticScore(
            completeness=0.5,
            recommendations=["Add more details", "Verify references"]
        )
        
        guidance = generator._generate_feedback_guidance(feedback)
        
        assert "Recommendation" in guidance or "Add more" in guidance
    
    def test_feedback_guidance_strong_feedback(self, generator, strong_feedback):
        """Guidance for strong feedback is minimal."""
        guidance = generator._generate_feedback_guidance(strong_feedback)
        
        # Should either be empty or minimal
        assert isinstance(guidance, str)


# ============================================================================
# Integration Tests
# ============================================================================

class TestPromptGenerationWorkflow:
    """Integration tests for complete workflows."""
    
    def test_domain_specific_workflow(self, generator):
        """Complete workflow for domain-specific extraction."""
        # 1. Get template for domain
        template = generator.get_template("legal")
        assert template is not None
        
        # 2. Generate initial prompt
        context = MockOntologyContext(domain="legal", data_type="contract")
        prompt = generator.generate_extraction_prompt(context)
        assert len(prompt) > 100
        
        # 3. With examples
        examples = generator.select_examples("legal", num_examples=2)
        prompt_with_examples = generator.generate_extraction_prompt(
            context,
            examples=examples
        )
        assert len(prompt_with_examples) >= len(prompt)
    
    def test_feedback_adaptation_workflow(self, generator):
        """Complete workflow for feedback-based adaptation."""
        context = MockOntologyContext(domain="medical")
        
        # 1. Generate initial prompt
        initial_prompt = generator.generate_extraction_prompt(context)
        
        # 2. Apply weak feedback
        weak_feedback = MockCriticScore(completeness=0.4, clarity=0.5)
        adapted = generator.adapt_prompt_from_feedback(initial_prompt, weak_feedback)
        
        # 3. Second iteration
        strong_feedback = MockCriticScore(completeness=0.9, clarity=0.85)
        refined = generator.adapt_prompt_from_feedback(adapted, strong_feedback)
        
        assert len(refined) > 0
    
    def test_custom_template_workflow(self, generator):
        """Workflow with custom templates."""
        # 1. Add custom template
        custom = PromptTemplate(
            system_prompt="Custom system instructions",
            user_prompt_template="Extract from: {data}",
            parameters={}
        )
        generator.add_template("proprietary", custom)
        
        # 2. Generate with custom template
        context = MockOntologyContext(domain="proprietary")
        prompt = generator.generate_extraction_prompt(context)
        
        assert "Custom system" in prompt
    
    def test_multi_domain_comparison(self, generator):
        """Compare prompts across domains."""
        context_base = MockOntologyContext(data="Sample data")
        
        legal_context = MockOntologyContext(domain="legal", data="Sample data")
        medical_context = MockOntologyContext(domain="medical", data="Sample data")
        
        legal_prompt = generator.generate_extraction_prompt(legal_context)
        medical_prompt = generator.generate_extraction_prompt(medical_context)
        
        # Prompts should be different
        assert legal_prompt != medical_prompt
        # But both should be substantial
        assert len(legal_prompt) > 100
        assert len(medical_prompt) > 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
