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
        # Create initial artifact
        return artifact
    
    def critique(self, artifact, context):
        # Evaluate quality (0-1) and provide feedback
        return (score, feedback_list)
    
    def optimize(self, artifact, score, feedback, context):
        # Improve artifact based on feedback
        return improved_artifact
    
    def validate(self, artifact, context):
        # Optional: verify artifact is valid
        return True

# Use it
optimizer = MyOptimizer(config=OptimizerConfig())
result = optimizer.run_session(input_data, context)
```

### Key Features

- **Automatic Optimization Loop**: `run_session()` handles the iteration logic
- **Early Stopping**: Stops when score plateaus or target reached
- **Metrics Collection**: Tracks performance automatically
- **Validation**: Optional verification step
- **Configurable**: All parameters tunable via `OptimizerConfig`

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
