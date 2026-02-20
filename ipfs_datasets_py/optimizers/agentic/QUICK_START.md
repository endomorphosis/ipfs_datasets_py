# Agentic Optimizers: Quick Start Guide

This guide shows how to use agentic optimizers for code quality improvement in 5 minutes.

## Installation

```bash
# Assumes ipfs_datasets_py is installed with agentic support
pip install ipfs_datasets_py[agentic]
```

## Basic Usage: Optimize Code

```python
from ipfs_datasets_py.optimizers.agentic import (
    AgenticOptimizer,
    OptimizationStrategy,
)
from ipfs_datasets_py.optimizers.common import OptimizerConfig

# Create configuration
config = OptimizerConfig(
    max_iterations=3,
    target_score=0.85,
    validation_enabled=True,
)

# Create optimizer with strategy
optimizer = AgenticOptimizer(
    config=config,
    strategy=OptimizationStrategy.ACTOR_CRITIC,
)

# Code to optimize
code = """
def factorize(n):
    result = []
    i = 2
    while i * i <= n:
        while n % i == 0:
            result.append(i)
            n = n // i
        i += 1
    if n > 1:
        result.append(n)
    return result
"""

# Run optimization
result = optimizer.run_session(code)

print(f"Optimization score: {result['score']:.2f}")
print(f"Improvements: {result['improvements']}")
print(f"Optimized code quality: {result['metrics']['complexity_reduction']:.1%}")
```

## Validation Framework

```python
from ipfs_datasets_py.optimizers.agentic import (
    OptimizationValidator,
    ValidationLevel,
)

validator = OptimizationValidator()

# Validate syntax and structure
is_valid, errors = validator.validate(
    code,
    level=ValidationLevel.STRICT,
)

if is_valid:
    print("Code passed all validation checks!")
else:
    print(f"Validation errors: {errors}")
```

## Optimization Strategies

```python
from ipfs_datasets_py.optimizers.agentic import OptimizationStrategy

strategies = [
    OptimizationStrategy.ADVERSARIAL,    # Adversarial learning
    OptimizationStrategy.ACTOR_CRITIC,   # Actor-critic approach
    OptimizationStrategy.CHAOS,          # Chaos-based exploration
]

for strategy in strategies:
    optimizer = AgenticOptimizer(config=config, strategy=strategy)
    result = optimizer.run_session(code)
    print(f"{strategy.name}: score={result['score']:.2f}")
```

## Security & Sandboxing

```python
from ipfs_datasets_py.optimizers.agentic import (
    get_input_sanitizer,
    get_sandbox_executor,
)

# Sanitize user input
sanitizer = get_input_sanitizer()
is_safe, issues = sanitizer.validate_code(user_code)

if is_safe:
    # Execute in sandbox
    executor = get_sandbox_executor()
    success, stdout, stderr = executor.execute_code(user_code)
    
    print(f"Execution successful: {success}")
    print(f"Output: {stdout[:100]}...")
else:
    print(f"Code validation issues: {issues}")
```

## Iterative Optimization Loop

```python
# Progressive improvement over multiple cycles
best_score = 0.0
best_code = code

for cycle in range(5):
    result = optimizer.run_session(best_code)
    
    if result['score'] > best_score:
        best_score = result['score']
        best_code = result['optimized_code']
        
        print(f"Cycle {cycle+1}: Improved to {best_score:.2f} ✓")
    else:
        print(f"Cycle {cycle+1}: No improvement {result['score']:.2f}")
    
    # Check convergence
    if best_score >= config.target_score:
        print(f"Converged at cycle {cycle+1}!")
        break
```

## CLI Usage

```bash
# Optimize code file
python -m ipfs_datasets_py.optimizers.agentic.cli_wrapper optimize \
  --input mycode.py \
  --strategy actor_critic \
  --target-score 0.85

# Validate code
python -m ipfs_datasets_py.optimizers.agentic.cli_wrapper validate \
  --input mycode.py \
  --level strict
```

## Logging & Monitoring

```python
import logging

# Enable detailed logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Optimizer accepts optional logger for DI
optimizer = AgenticOptimizer(
    config=config,
    strategy=OptimizationStrategy.ACTOR_CRITIC,
    logger=logger
)

# Monitor optimization progress
result = optimizer.run_session(code)
logger.info(f"Final score: {result['score']:.2f}")
```

## Optimization Categories

```python
# Different optimization focus areas
optimization_focus = {
    "performance": {
        "max_iterations": 5,
        "metrics": ["time_complexity", "memory_usage"],
    },
    "readability": {
        "max_iterations": 3,
        "metrics": ["complexity", "documentation"],
    },
    "correctness": {
        "max_iterations": 10,
        "metrics": ["test_coverage", "edge_cases"],
    },
}

for focus, config_dict in optimization_focus.items():
    custom_config = OptimizerConfig(**config_dict)
    optimizer = AgenticOptimizer(config=custom_config)
    result = optimizer.run_session(code)
    print(f"{focus.capitalize()}: {result['score']:.2f}")
```

## Token Security

```python
from ipfs_datasets_py.optimizers.agentic import get_input_sanitizer

sanitizer = get_input_sanitizer()

# Sensitive log message with API keys
message = """
Config: api_key=sk-aBcDeFgHiJkLmNoPqRsT1234567890UvWxVyZ
GitHub token: ghp_1234567890AbCdEfGhIjKlMnOpQrStUvWx
"""

# Remove tokens before logging
safe_message = sanitizer.sanitize_log_message(message)
print(safe_message)  # Prints with [TOKEN_REDACTED]
```

## Configuration

```python
from ipfs_datasets_py.optimizers.common import OptimizerConfig
from ipfs_datasets_py.optimizers.agentic.production_hardening import SecurityConfig

# Optimization config
opt_config = OptimizerConfig(
    max_iterations=5,
    target_score=0.85,
    early_stopping=True,
    validation_enabled=True,
    metrics_enabled=True,
)

# Security config
sec_config = SecurityConfig(
    enable_sandbox=True,
    sandbox_timeout=30,
    max_memory_mb=512,
    mask_tokens_in_logs=True,
)

optimizer = AgenticOptimizer(
    config=opt_config,
    security_config=sec_config,
)
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **Sandbox execution timeout** | Increase `sandbox_timeout` in SecurityConfig or optimize code to run faster. |
| **Token masking not working** | Ensure token patterns match known formats (OpenAI: `sk-` + 48 chars, GitHub: `ghp_` + 36 chars). |
|  **Validation always fails** | Check code syntax with `python -m py_compile` first. |
| **Low improvement scores** | Try different strategies or increase `max_iterations`. |

## Next Steps

- **API Reference:** See [README.md](README.md) for full API documentation
- **Security:** See [SECURITY_AUDIT.md](SECURITY_AUDIT.md) for security model
- **Performance:** See [PERFORMANCE_TUNING.md](PERFORMANCE_TUNING.md) for optimization tips
- **Examples:** See [../examples/](../examples/) for complete examples

---

**Last updated:** 2026-02-20  
**Test coverage:** 164 tests in `tests/unit/optimizers/agentic/`  
**Security:** InputSanitizer, TokenMasker, SandboxExecutor, CircuitBreaker, RetryHandler
