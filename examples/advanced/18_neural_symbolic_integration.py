"""
Neural-Symbolic Integration - Bridging Neural Networks and Logic

This example demonstrates advanced integration of neural networks (LLMs,
embeddings) with symbolic reasoning (theorem provers, logic systems) for
enhanced AI capabilities.

Requirements:
    - transformers, torch: pip install transformers torch
    - z3-solver: pip install z3-solver
    - Optional: Prover9/Mace4 for advanced theorem proving

Usage:
    python examples/advanced/18_neural_symbolic_integration.py
"""

import asyncio


async def demo_llm_guided_theorem_proving():
    """Use LLMs to guide theorem proving."""
    print("\n" + "="*70)
    print("DEMO 1: LLM-Guided Theorem Proving")
    print("="*70)
    
    print("\n🤖+🔬 LLM-Guided Proving")
    print("   Use neural networks to guide symbolic provers")
    
    example_code = '''
from ipfs_datasets_py.logic import LLMGuidedProver

prover = LLMGuidedProver(
    llm_model="gpt-4",
    theorem_prover="z3",
    guidance_strategy="learned"
)

# Theorem to prove
theorem = {
    "premises": [
        "∀x (Human(x) → Mortal(x))",
        "Human(Socrates)"
    ],
    "conclusion": "Mortal(Socrates)"
}

# Use LLM to suggest proof strategies
strategies = await prover.suggest_strategies(theorem)

print("LLM suggested strategies:")
for i, strategy in enumerate(strategies, 1):
    print(f"  {i}. {strategy.name}")
    print(f"     Confidence: {strategy.confidence:.2f}")
    print(f"     Steps: {strategy.estimated_steps}")

# Execute proof with best strategy
result = await prover.prove(
    theorem=theorem,
    strategy=strategies[0],
    max_iterations=100
)

if result.proved:
    print(f"\\n✅ Theorem proved!")
    print(f"Proof steps: {len(result.proof_steps)}")
    
    for i, step in enumerate(result.proof_steps, 1):
        print(f"  {i}. {step.formula}")
        print(f"     Rule: {step.rule}")
        print(f"     Justification: {step.justification}")
else:
    print(f"\\n❌ Could not prove theorem")
    print(f"Reason: {result.failure_reason}")
    '''
    
    print(example_code)


async def demo_neural_constraint_learning():
    """Learn constraints from examples."""
    print("\n" + "="*70)
    print("DEMO 2: Neural Constraint Learning")
    print("="*70)
    
    print("\n📚 Learn Constraints")
    print("   Extract logical rules from neural network patterns")
    
    example_code = '''
from ipfs_datasets_py.logic import NeuralConstraintLearner

learner = NeuralConstraintLearner(
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    logic_system="fol"
)

# Training examples (positive and negative)
examples = [
    {"text": "John is 25 and can vote", "label": "valid"},
    {"text": "Sarah is 16 and can vote", "label": "invalid"},
    {"text": "Mike is 18 and can vote", "label": "valid"},
    {"text": "Emma is 15 and can vote", "label": "invalid"},
    # ... more examples
]

# Learn constraints
constraints = await learner.learn(
    examples=examples,
    min_confidence=0.8,
    max_constraints=10
)

print("Learned constraints:")
for constraint in constraints:
    print(f"  {constraint.formula}")
    print(f"  Confidence: {constraint.confidence:.2f}")
    print(f"  Support: {constraint.support_count} examples")
    print(f"  Natural language: {constraint.description}")

# Validate on new examples
new_examples = [
    "Alice is 20 and can vote",
    "Bob is 17 and can vote"
]

for example in new_examples:
    validation = await learner.validate(example, constraints)
    print(f"\\n{example}")
    print(f"  Valid: {validation.is_valid}")
    print(f"  Violated constraints: {validation.violations}")
    '''
    
    print(example_code)


async def demo_symbolic_attention():
    """Add symbolic attention to neural models."""
    print("\n" + "="*70)
    print("DEMO 3: Symbolic Attention Mechanisms")
    print("="*70)
    
    print("\n🎯 Symbolic Attention")
    print("   Guide neural attention with logical constraints")
    
    example_code = '''
from ipfs_datasets_py.ml import SymbolicAttentionModel

model = SymbolicAttentionModel(
    base_model="bert-base-uncased",
    attention_type="logical",
    constraint_weight=0.3
)

# Define symbolic constraints
constraints = [
    "attend_to(X) IF entity_type(X, 'Person')",
    "attend_to(X) IF related_to(X, query_entity)",
    "NOT attend_to(X) IF low_confidence(X)"
]

# Text with entities
text = """
Steve Jobs founded Apple in 1976. He was known for his
innovative products like the iPhone. Tim Cook succeeded
him as CEO in 2011.
"""

# Query with symbolic constraints
query = "Who founded Apple?"

result = await model.query(
    text=text,
    query=query,
    constraints=constraints
)

print("Answer:", result.answer)
print("\\nAttention distribution:")
for token, attention in result.attention_weights.items():
    if attention > 0.1:  # Only show significant attention
        print(f"  {token}: {attention:.2f}")

print("\\nConstraint satisfaction:")
for constraint in constraints:
    satisfaction = result.constraint_satisfaction[constraint]
    print(f"  {constraint}: {satisfaction:.2f}")
    '''
    
    print(example_code)


async def demo_logic_enhanced_generation():
    """Generate text with logical constraints."""
    print("\n" + "="*70)
    print("DEMO 4: Logic-Enhanced Text Generation")
    print("="*70)
    
    print("\n✍️  Constrained Generation")
    print("   Generate text that satisfies logical constraints")
    
    example_code = '''
from ipfs_datasets_py.ml import LogicEnhancedGenerator

generator = LogicEnhancedGenerator(
    llm="gpt-3.5-turbo",
    verifier="z3",
    max_retries=5
)

# Generation task with constraints
prompt = "Generate a story about a person applying for a job"

constraints = [
    "age(Person) >= 18",  # Must be adult
    "has_degree(Person) OR has_experience(Person)",  # Qualified
    "NOT discriminatory_content(Text)"  # No discrimination
]

# Generate with constraint checking
result = await generator.generate(
    prompt=prompt,
    constraints=constraints,
    verify_each_step=True
)

print("Generated text:")
print(result.text)

print("\\nConstraint verification:")
for constraint in constraints:
    verified = result.constraint_checks[constraint]
    print(f"  {constraint}: {'✅' if verified else '❌'}")

if not result.all_constraints_satisfied:
    print("\\nRetries needed:", result.retry_count)
    print("Violations fixed:", result.violations_fixed)
    '''
    
    print(example_code)


async def demo_neuro_symbolic_reasoning():
    """Combine neural and symbolic for complex reasoning."""
    print("\n" + "="*70)
    print("DEMO 5: Neuro-Symbolic Reasoning")
    print("="*70)
    
    print("\n🧠+🔬 Hybrid Reasoning")
    print("   Best of both approaches for complex problems")
    
    example_code = '''
from ipfs_datasets_py.logic import NeuroSymbolicReasoner

reasoner = NeuroSymbolicReasoner(
    neural_component="embedding",  # or "llm"
    symbolic_component="fol",      # or "temporal", "deontic"
    integration="cascaded"         # or "parallel", "hierarchical"
)

# Complex reasoning task
problem = """
Given:
- All employees must be over 18
- Interns are employees
- Sarah is an intern
- Sarah's age is unknown

Question: Can Sarah legally work?
"""

# Hybrid reasoning
result = await reasoner.reason(
    problem=problem,
    use_neural_for=["entity_extraction", "relationship_inference"],
    use_symbolic_for=["constraint_checking", "logical_deduction"]
)

print("Reasoning trace:")
print("\\nNeural steps:")
for step in result.neural_steps:
    print(f"  {step.operation}: {step.result}")
    print(f"  Confidence: {step.confidence:.2f}")

print("\\nSymbolic steps:")
for step in result.symbolic_steps:
    print(f"  {step.formula}")
    print(f"  Rule: {step.rule_applied}")

print("\\nConclusion:", result.conclusion)
print("Certainty:", result.certainty)

# Explanation combines both
print("\\nExplanation:")
print(result.explanation)
    '''
    
    print(example_code)


async def demo_verifiable_neural_outputs():
    """Verify neural network outputs with logic."""
    print("\n" + "="*70)
    print("DEMO 6: Verifiable Neural Outputs")
    print("="*70)
    
    print("\n✓ Output Verification")
    print("   Ensure neural outputs are logically consistent")
    
    example_code = '''
from ipfs_datasets_py.ml import VerifiableNeuralModel

model = VerifiableNeuralModel(
    neural_model="llm",
    verifier="z3",
    verification_mode="strict"  # strict, warn, or log
)

# Task: Extract structured data
text = """
Our company, TechCorp, was founded in 2005 in San Francisco.
We have 500 employees and revenue of $50 million.
"""

# Extract with verification rules
rules = [
    "founded_year >= 1900 AND founded_year <= 2024",
    "employees >= 0",
    "revenue >= 0",
    "IF founded_year > 2020 THEN employees < 10000"
]

result = await model.extract_with_verification(
    text=text,
    schema={
        "company_name": "string",
        "founded_year": "int",
        "location": "string",
        "employees": "int",
        "revenue": "float"
    },
    verification_rules=rules
)

print("Extracted data:")
for field, value in result.data.items():
    verified = "✅" if result.field_verified[field] else "❌"
    print(f"  {field}: {value} {verified}")

if not result.all_verified:
    print("\\nVerification failures:")
    for failure in result.failures:
        print(f"  Field: {failure.field}")
        print(f"  Rule: {failure.violated_rule}")
        print(f"  Suggested fix: {failure.suggestion}")
    '''
    
    print(example_code)


async def demo_concept_learning():
    """Learn symbolic concepts from neural representations."""
    print("\n" + "="*70)
    print("DEMO 7: Symbolic Concept Learning")
    print("="*70)
    
    print("\n💡 Concept Learning")
    print("   Extract symbolic concepts from neural embeddings")
    
    example_code = '''
from ipfs_datasets_py.logic import ConceptLearner

learner = ConceptLearner(
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    clustering_method="hierarchical",
    concept_extraction="decision_tree"
)

# Examples of concepts
examples = {
    "fruit": ["apple", "banana", "orange", "grape"],
    "vehicle": ["car", "bus", "train", "airplane"],
    "animal": ["dog", "cat", "bird", "fish"]
}

# Learn concept definitions
concepts = await learner.learn_concepts(
    examples=examples,
    learn_hierarchy=True
)

print("Learned concepts:")
for concept_name, concept in concepts.items():
    print(f"\\n{concept_name}:")
    print(f"  Definition: {concept.symbolic_definition}")
    print(f"  Features: {', '.join(concept.features)}")
    print(f"  Parent: {concept.parent_concept or 'None'}")

# Test concept membership
test_items = ["strawberry", "bicycle", "elephant"]

for item in test_items:
    memberships = await learner.test_membership(
        item=item,
        concepts=concepts
    )
    
    print(f"\\n{item}:")
    for concept, score in memberships.items():
        print(f"  {concept}: {score:.2f}")

# Export concepts as logical rules
rules = await learner.export_as_rules(concepts)
print("\\nExtracted rules:")
for rule in rules:
    print(f"  {rule}")
    '''
    
    print(example_code)


def show_tips():
    """Show tips for neural-symbolic integration."""
    print("\n" + "="*70)
    print("TIPS FOR NEURAL-SYMBOLIC INTEGRATION")
    print("="*70)
    
    print("\n1. When to Integrate:")
    print("   - Need both learning and reasoning")
    print("   - Require explainable decisions")
    print("   - Working with structured + unstructured data")
    print("   - Need to enforce hard constraints")
    
    print("\n2. Integration Strategies:")
    print("   - Cascaded: Neural → Symbolic or vice versa")
    print("   - Parallel: Both systems run independently")
    print("   - Hierarchical: Nested integration")
    print("   - Hybrid: Tight coupling throughout")
    
    print("\n3. Neural Components:")
    print("   - LLMs for text understanding")
    print("   - Embeddings for similarity")
    print("   - Neural attention for focus")
    print("   - Generative models for synthesis")
    
    print("\n4. Symbolic Components:")
    print("   - FOL for general reasoning")
    print("   - Temporal logic for time")
    print("   - Deontic logic for rules/policies")
    print("   - Theorem provers for verification")
    
    print("\n5. Common Patterns:")
    print("   - Neural extraction → Symbolic verification")
    print("   - Symbolic constraints → Neural generation")
    print("   - Neural similarity → Symbolic rules")
    print("   - LLM guidance → Theorem proving")
    
    print("\n6. Verification:")
    print("   - Always verify neural outputs")
    print("   - Use symbolic systems for validation")
    print("   - Implement retry mechanisms")
    print("   - Log verification failures")
    
    print("\n7. Performance:")
    print("   - Neural steps are fast but approximate")
    print("   - Symbolic steps are slow but exact")
    print("   - Cache symbolic verifications")
    print("   - Use approximate reasoning when possible")
    
    print("\n8. Explainability:")
    print("   - Symbolic reasoning is inherently explainable")
    print("   - Generate natural language from proofs")
    print("   - Show which rules were applied")
    print("   - Trace neural-symbolic interactions")
    
    print("\n9. Next Steps:")
    print("   - See 13_logic_reasoning.py for logic basics")
    print("   - See 16_logic_enhanced_rag.py for RAG integration")


async def main():
    """Run all neural-symbolic integration demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - NEURAL-SYMBOLIC INTEGRATION")
    print("="*70)
    
    await demo_llm_guided_theorem_proving()
    await demo_neural_constraint_learning()
    await demo_symbolic_attention()
    await demo_logic_enhanced_generation()
    await demo_neuro_symbolic_reasoning()
    await demo_verifiable_neural_outputs()
    await demo_concept_learning()
    
    show_tips()
    
    print("\n" + "="*70)
    print("✅ NEURAL-SYMBOLIC INTEGRATION EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
