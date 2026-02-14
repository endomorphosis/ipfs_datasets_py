# Agentic Optimizer Examples

This directory contains examples demonstrating the agentic optimizer framework.

## Examples

### 1. `simple_optimization.py`
**Purpose**: Single-agent optimization with test-driven development

Demonstrates:
- Creating an optimization task
- Configuring a test-driven optimizer
- Running optimization on a single file
- Handling optimization results

Usage:
```bash
python examples/agentic/simple_optimization.py
```

### 2. `validation_example.py`
**Purpose**: Code validation at different strictness levels

Demonstrates:
- ValidationLevel.BASIC - Fast syntax checking
- ValidationLevel.STANDARD - Production validation
- ValidationLevel.STRICT - High-quality enforcement
- ValidationLevel.PARANOID - Maximum validation

Usage:
```bash
python examples/agentic/validation_example.py
```

### 3. CLI Usage Examples

**Optimize code:**
```bash
python -m ipfs_datasets_py.optimizers.agentic.cli optimize \
  --method test_driven \
  --target ipfs_datasets_py/cache.py \
  --description "Optimize caching performance"
```

**Validate code:**
```bash
python -m ipfs_datasets_py.optimizers.agentic.cli validate \
  path/to/file.py \
  --level standard
```

**View stats:**
```bash
python -m ipfs_datasets_py.optimizers.agentic.cli stats
```

**Rollback changes:**
```bash
python -m ipfs_datasets_py.optimizers.agentic.cli rollback patch-123
```

## Configuration

All examples require an LLM router to be configured. Example configuration:

```python
from ipfs_datasets_py.llm_router import LLMRouter

llm_router = LLMRouter(
    providers=["openai", "anthropic"],
    default_provider="openai",
    api_keys={
        "openai": os.getenv("OPENAI_API_KEY"),
        "anthropic": os.getenv("ANTHROPIC_API_KEY"),
    },
)
```

## Optimization Methods

### Test-Driven (`test_driven`)
- Generates tests first
- Optimizes code to pass tests
- Validates performance improvements

### Adversarial (`adversarial`)
- Generates N competing solutions
- Benchmarks all alternatives
- Selects best using multi-criteria scoring

### Actor-Critic (`actor_critic`)
- Learns from feedback
- Improves over time
- Stores successful patterns

### Chaos Engineering (`chaos`)
- Injects faults
- Identifies weaknesses
- Generates fixes for issues

## Change Control Methods

### Patch-Based (`ChangeControlMethod.PATCH`)
- Git worktrees for isolation
- IPFS for distributed storage
- Easy rollback via reversal patches

### GitHub-Based (`ChangeControlMethod.GITHUB`)
- Creates GitHub issues
- Draft PRs for review
- API caching for rate limits

## Next Steps

1. Configure LLM router
2. Start with simple examples
3. Try different optimization methods
4. Explore validation levels
5. Experiment with CLI commands

For more information, see:
- `ipfs_datasets_py/optimizers/USAGE_GUIDE.md`
- `ipfs_datasets_py/optimizers/ARCHITECTURE_AGENTIC_OPTIMIZERS.md`
