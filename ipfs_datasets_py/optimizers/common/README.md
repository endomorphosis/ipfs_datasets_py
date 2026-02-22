# Common Optimizer Framework

## Overview

This directory contains the shared base classes and utilities used by all optimizer types in `ipfs_datasets_py/optimizers/`.

## Purpose

Provides a unified framework that enables:
- **Code Reuse**: Eliminate 40-50% duplication across optimizers
- **Consistency**: Common interfaces and patterns
- **Extensibility**: Easy to add new optimizer types
- **Integration**: Seamless interop between optimizers

## Architecture

All optimizers follow a consistent pipeline:

```
Input Data → Generate → Critique → Optimize → Validate → Result
             (Create)   (Evaluate)  (Improve)  (Check)
```

## Base Classes

### BaseOptimizer

Abstract base class that all optimizers extend. Defines the core optimization workflow.

```python
from ipfs_datasets_py.optimizers.common import (
    BaseOptimizer,
    OptimizerConfig,
    OptimizationContext,
)

class MyOptimizer(BaseOptimizer):
    def generate(self, input_data, context):
        return artifact
    
    def critique(self, artifact, context):
        return (score, feedback_list)
    
    def optimize(self, artifact, score, feedback, context):
        return improved_artifact

optimizer = MyOptimizer(config=OptimizerConfig())
result = optimizer.run_session(input_data, context)
```

### BaseCritic

Abstract base for all domain critics.  Returns a typed `CriticResult` with score,
multi-dimensional breakdown, strengths, and weaknesses.

```python
from ipfs_datasets_py.optimizers.common import BaseCritic, CriticResult

class MyCritic(BaseCritic):
    def evaluate(self, artifact, context=None) -> CriticResult:
        return CriticResult(
            score=0.85,
            feedback=["Good coverage", "Needs more relationships"],
            dimensions={"completeness": 0.9, "consistency": 0.8},
            strengths=["Well-structured entities"],
            weaknesses=["Missing temporal relationships"],
            metadata={"evaluator": "MyCritic", "domain": "legal"},
        )

critic = MyCritic()
result = critic.evaluate(my_artifact)
print(result.score, result.feedback)

# Convenience wrappers
score = critic.score_only(my_artifact)        # float
feedback = critic.feedback_only(my_artifact)  # list[str]
```

#### `CriticResult` Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `score` | `float` | Overall quality score, clamped to [0.0, 1.0]. |
| `feedback` | `list[str]` | Ordered list of actionable improvement suggestions. |
| `dimensions` | `dict[str, float]` | Per-dimension scores keyed by dimension name (e.g. `"completeness"`, `"consistency"`). Values in [0.0, 1.0]. |
| `strengths` | `list[str]` | Observed strengths in the evaluated artifact. |
| `weaknesses` | `list[str]` | Observed weaknesses; typically drives the next refinement round. |
| `metadata` | `dict[str, Any]` | Arbitrary extra data: evaluator name, domain, backend, timing, etc. |

> **Tip**: Use `result.dimensions` to build per-dimension progress dashboards across multiple refinement rounds.  Use `result.weaknesses` as the seed for the next mediator action set.

### BaseSession

Tracks the full state of one optimization session (all rounds, best score,
convergence, timings).

```python
from ipfs_datasets_py.optimizers.common import BaseSession

session = BaseSession(target_score=0.85, convergence_threshold=0.005)
session.start_round()
session.record_round(score=0.72, feedback=["add more props"])
session.start_round()
session.record_round(score=0.81, feedback=["nearly there"])
print(session.best_score)   # 0.81
print(session.trend)        # "improving"
print(session.converged)    # False
report = session.to_dict()
```

`RoundRecord` fields: `round_number`, `score`, `feedback`, `duration_s`, `timestamp`.

### BaseHarness

Orchestrates the full generate → critique → optimize loop using a `BaseSession`.
Concrete harnesses implement `_generate()`, `_critique()`, `_optimize()`.

```python
from ipfs_datasets_py.optimizers.common import BaseHarness, HarnessConfig

class MyHarness(BaseHarness):
    def _generate(self, data, context):
        return self.generator.extract(data, context)

    def _critique(self, artifact, context):
        return self.critic.evaluate(artifact, context)

    def _optimize(self, artifact, critique, context):
        return self.optimizer.refine(artifact, critique.feedback)

harness = MyHarness(
    generator=gen, critic=critic, optimizer=opt,
    config=HarnessConfig(max_rounds=5, target_score=0.8),
)
session = harness.run(data, context)
print(session.best_score)
```

`HarnessConfig` fields: `max_rounds`, `target_score`, `convergence_threshold`.

### Exceptions

Typed exception hierarchy rooted at `OptimizerError`:

```
OptimizerError
├── ExtractionError    – entity / relationship extraction failures
├── ValidationError    – ontology / logic validation failures
├── ProvingError       – theorem-prover failures
├── RefinementError    – refinement / mediator failures
└── ConfigurationError – invalid optimizer configuration
```

```python
from ipfs_datasets_py.optimizers.common import (
    ExtractionError, ValidationError, ProvingError,
)

try:
    result = extractor.extract(data)
except ExtractionError as exc:
    logger.error("Extraction failed: %s", exc)
```

## Usage

### Basic Example

```python
from ipfs_datasets_py.optimizers.common import (
    BaseOptimizer,
    OptimizerConfig,
    OptimizationContext,
    OptimizationStrategy,
)

# Configure optimizer
config = OptimizerConfig(
    strategy=OptimizationStrategy.SGD,
    max_iterations=10,
    target_score=0.85,
    early_stopping=True,
)

# Create context
context = OptimizationContext(
    session_id="session-1",
    input_data=my_data,
    domain="my_domain",
)

# Run optimization
optimizer = MyOptimizer(config=config)
result = optimizer.run_session(my_data, context)

print(f"Score: {result['score']}")
print(f"Iterations: {result['iterations']}")
print(f"Valid: {result['valid']}")
```

### Integration with Existing Optimizers

#### Logic Theorem Optimizer

```python
from ipfs_datasets_py.optimizers.common import BaseOptimizer
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    LogicExtractor,
    LogicCritic,
)

class UnifiedLogicOptimizer(BaseOptimizer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.extractor = LogicExtractor()
        self.critic = LogicCritic()
    
    def generate(self, input_data, context):
        return self.extractor.extract(input_data)
    
    def critique(self, artifact, context):
        score = self.critic.evaluate(artifact)
        feedback = self.critic.get_feedback()
        return (score.overall, feedback)
```

#### GraphRAG Optimizer

```python
from ipfs_datasets_py.optimizers.common import BaseOptimizer
from ipfs_datasets_py.optimizers.graphrag import (
    OntologyGenerator,
    OntologyCritic,
)

class UnifiedGraphRAGOptimizer(BaseOptimizer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.generator = OntologyGenerator()
        self.critic = OntologyCritic()
    
    def generate(self, input_data, context):
        return self.generator.generate_ontology(input_data)
    
    def critique(self, artifact, context):
        score = self.critic.evaluate_ontology(artifact)
        feedback = score.feedback
        return (score.overall, feedback)
```

#### GraphRAG ExtractionConfig: custom_rules

```python
from ipfs_datasets_py.optimizers.graphrag import (
    OntologyGenerator,
    OntologyGenerationContext,
    ExtractionConfig,
    ExtractionStrategy,
    DataType,
)

config = ExtractionConfig(
    custom_rules=[(r"\b(?:Widget|Gadget)\b", "Product")]
)
context = OntologyGenerationContext(
    data_source="unit-test",
    data_type=DataType.TEXT,
    domain="general",
    extraction_strategy=ExtractionStrategy.RULE_BASED,
    config=config,
)

generator = OntologyGenerator(use_ipfs_accelerate=False)
ontology = generator.generate_ontology("The Widget ships with a Gadget.", context)
```

## Configuration

### OptimizerConfig

```python
from ipfs_datasets_py.optimizers.common import OptimizerConfig, OptimizationStrategy

config = OptimizerConfig(
    strategy=OptimizationStrategy.SGD,  # SGD, EVOLUTIONARY, REINFORCEMENT, HYBRID
    max_iterations=10,                   # Maximum optimization iterations
    target_score=0.85,                   # Target quality score (0-1)
    learning_rate=0.1,                   # Learning rate for SGD
    convergence_threshold=0.01,          # Min improvement to continue
    early_stopping=True,                 # Enable early stopping
    validation_enabled=True,             # Enable validation step
    metrics_enabled=True,                # Collect performance metrics
)
```

### OptimizationContext

```python
from ipfs_datasets_py.optimizers.common import OptimizationContext

context = OptimizationContext(
    session_id="unique-session-id",
    input_data=my_data,
    domain="code",  # or "logic", "graph", etc.
    constraints={
        "max_size": 1000,
        "timeout": 300,
    },
    metadata={
        "user": "agent-1",
        "priority": "high",
    },
)
```

## Extending the Framework

### Adding New Optimizer Types

1. Create a new module (e.g., `optimizers/my_optimizer/`)
2. Extend `BaseOptimizer`
3. Implement required methods: `generate()`, `critique()`, `optimize()`
4. Optionally override `validate()`
5. Use existing infrastructure (LLM backend, metrics, etc.)

### Example: Custom Optimizer

```python
from ipfs_datasets_py.optimizers.common import BaseOptimizer, OptimizerConfig
from typing import Any, List, Tuple

class CustomOptimizer(BaseOptimizer):
    """My custom optimizer implementation."""
    
    def generate(self, input_data: Any, context) -> Any:
        """Generate initial artifact."""
        # Your generation logic here
        artifact = self._create_initial_artifact(input_data)
        return artifact
    
    def critique(self, artifact: Any, context) -> Tuple[float, List[str]]:
        """Evaluate artifact quality."""
        # Your evaluation logic here
        score = self._calculate_score(artifact)
        feedback = self._generate_feedback(artifact, score)
        return (score, feedback)
    
    def optimize(self, artifact: Any, score: float, feedback: List[str], context) -> Any:
        """Improve artifact."""
        # Your optimization logic here
        improved = self._apply_improvements(artifact, feedback)
        return improved
    
    def validate(self, artifact: Any, context) -> bool:
        """Validate artifact."""
        # Optional validation logic
        return self._check_constraints(artifact, context.constraints)
```

## Shared Utilities (Planned)

The common framework will expand to include:

- **LLM Integration** (`llm_integration.py`): Unified LLM backend
- **Prompt Templates** (`prompt_templates.py`): Shared prompt system
- **Metrics Framework** (`metrics_framework.py`): Common metrics collection
- **Visualization** (`visualization_base.py`): Shared visualization
- **Distributed Processing** (`distributed_base.py`): Common distribution logic

## Integration with Agentic Framework

The common base can be combined with the agentic framework:

```python
from ipfs_datasets_py.optimizers.common import BaseOptimizer
from ipfs_datasets_py.optimizers.agentic import PatchManager, WorktreeManager

class AgenticBaseOptimizer(BaseOptimizer):
    """Combines common base with agentic capabilities."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.patch_manager = PatchManager()
        self.worktree_manager = WorktreeManager()
    
    def run_session(self, input_data, context):
        # Create isolated worktree
        worktree = self.worktree_manager.create_worktree(context.session_id)
        
        # Run optimization
        result = super().run_session(input_data, context)
        
        # Create patch
        if result['valid']:
            patch = self.patch_manager.create_patch(
                agent_id=context.session_id,
                task_id=context.session_id,
                worktree_path=worktree,
                description=f"Optimization result (score: {result['score']})",
            )
            result['patch_path'] = self.patch_manager.save_patch(patch)
        
        return result
```

## Benefits

### For Developers

- **Less Code**: Inherit common functionality instead of reimplementing
- **Focus on Domain Logic**: Spend time on optimization algorithms, not infrastructure
- **Consistency**: Follow established patterns
- **Testing**: Leverage shared test infrastructure

### For Users

- **Consistent API**: All optimizers work the same way
- **Interoperability**: Mix and match optimizers
- **Better Quality**: Shared improvements benefit all optimizers
- **Easier Learning**: Learn once, use everywhere

## Migration Guide

See `ARCHITECTURE_UNIFIED.md` for detailed migration instructions for:
- Logic Theorem Optimizer → BaseOptimizer
- GraphRAG Optimizer → BaseOptimizer
- Agentic Optimizer → BaseOptimizer

## Next Steps

1. ✅ Create common base layer
2. ⏳ Add LLM integration utilities
3. ⏳ Add prompt template system
4. ⏳ Add metrics framework
5. ⏳ Migrate logic_theorem_optimizer
6. ⏳ Migrate graphrag optimizer
7. ⏳ Full integration with agentic framework

## Questions?

See:
- `ARCHITECTURE_UNIFIED.md` - Complete architecture documentation
- Parent directory README - Overview of all optimizers
- Individual optimizer READMEs - Specific optimizer documentation
