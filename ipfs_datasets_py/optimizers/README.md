# Optimizers Module

A comprehensive framework for code optimization using multiple approaches including agentic AI-driven optimization, logic theorem optimization, and GraphRAG optimization.

## Overview

The optimizers module provides:

1. **Agentic Optimizers** - AI-powered code optimization with multiple methodologies
2. **Logic Theorem Optimizers** - Formal logic and theorem proving optimization
3. **GraphRAG Optimizers** - Knowledge graph-based optimization
4. **Common Infrastructure** - Shared base classes and utilities

## Directory Structure

```
optimizers/
├── agentic/                    # AI-powered agentic optimization
│   ├── base.py                 # Base classes and interfaces
│   ├── coordinator.py          # Multi-agent coordination
│   ├── github_control.py       # GitHub-based change control
│   ├── patch_control.py        # Patch-based change control
│   ├── validation.py           # Comprehensive validation framework
│   ├── cli.py                  # Command-line interface
│   ├── github_api_unified.py   # Unified GitHub API with caching
│   └── methods/                # Optimization methods
│       ├── test_driven.py      # Test-driven optimization
│       ├── adversarial.py      # Adversarial optimization
│       ├── actor_critic.py     # Actor-critic optimization
│       └── chaos.py            # Chaos engineering optimization
│
├── common/                     # Shared infrastructure
│   ├── base_optimizer.py       # BaseOptimizer abstract class
│   └── README.md               # Common infrastructure guide
│
├── logic_theorem_optimizer/    # Logic and theorem proving
│   ├── logic_optimizer.py      # Main logic optimizer
│   ├── logic_critic.py         # Logic critic
│   ├── theorem_session.py      # Theorem proving sessions
│   └── ...                     # Additional logic components
│
└── graphrag/                   # GraphRAG optimization
    ├── ontology_optimizer.py   # Ontology optimization
    ├── ontology_critic.py      # Ontology critic
    ├── query_optimizer.py      # Query optimization
    └── ...                     # Additional GraphRAG components
```

## Quick Start

### Agentic Optimizer CLI

```bash
# Optimize code using test-driven development
python -m ipfs_datasets_py.optimizers.agentic.cli optimize \
  --method test_driven \
  --target ipfs_datasets_py/cache.py \
  --description "Optimize caching performance"

# Validate code
python -m ipfs_datasets_py.optimizers.agentic.cli validate \
  path/to/file.py \
  --level standard

# View optimization statistics
python -m ipfs_datasets_py.optimizers.agentic.cli stats

# Rollback changes
python -m ipfs_datasets_py.optimizers.agentic.cli rollback patch-id-123
```

### Programmatic Usage

```python
from ipfs_datasets_py.optimizers.agentic import (
    TestDrivenOptimizer,
    OptimizationTask,
    ChangeControlMethod,
)

# Create optimization task
task = OptimizationTask(
    task_id="task-001",
    description="Optimize data loading",
    target_files=[Path("ipfs_datasets_py/data_loader.py")],
    priority=75,
)

# Create optimizer (requires LLM router)
optimizer = TestDrivenOptimizer(
    agent_id="opt-001",
    llm_router=llm_router,
    change_control=ChangeControlMethod.PATCH,
)

# Run optimization
result = optimizer.optimize(task)
```

## Agentic Optimization Methods

### 1. Test-Driven (`test_driven`)
- Generates comprehensive tests first
- Optimizes code to pass tests
- Validates performance improvements
- **Use when**: Code needs test coverage improvements

### 2. Adversarial (`adversarial`)
- Generates N competing solutions (default: 5)
- Benchmarks all alternatives
- Selects best using multi-criteria scoring
- **Use when**: Exploring multiple approaches to optimization

### 3. Actor-Critic (`actor_critic`)
- Learns from feedback over time
- Stores successful patterns in policy
- Improves with each optimization
- **Use when**: Repeated optimizations on similar code

### 4. Chaos Engineering (`chaos`)
- Injects 10 types of faults
- Identifies resilience weaknesses
- Generates fixes automatically
- **Use when**: Improving error handling and robustness

## Validation Framework

### Validation Levels

- **BASIC**: Syntax checking only (fast)
- **STANDARD**: Syntax + types + unit tests (recommended)
- **STRICT**: Standard + performance validation (critical paths)
- **PARANOID**: All validators + security + style (sensitive code)

### Validators

1. **SyntaxValidator**: AST parsing and syntax verification
2. **TypeValidator**: mypy type checking
3. **TestValidator**: pytest test execution
4. **PerformanceValidator**: Benchmarking and improvement thresholds
5. **SecurityValidator**: Dangerous patterns and vulnerability detection
6. **StyleValidator**: PEP 8 compliance and code quality

### Usage

```python
from ipfs_datasets_py.optimizers.agentic.validation import (
    OptimizationValidator,
    ValidationLevel,
)

validator = OptimizationValidator(
    level=ValidationLevel.STANDARD,
    parallel=True,
)

result = validator.validate_sync(
    code=code_to_validate,
    target_files=[Path("file.py")],
    context={},
)

print(f"Passed: {result.passed}")
print(f"Errors: {len(result.errors)}")
```

## Change Control Methods

### Patch-Based Control (`ChangeControlMethod.PATCH`)

- Uses git worktrees for isolation
- Stores patches in IPFS with CIDs
- Supports easy rollback via reversal patches
- **Best for**: Compute-constrained environments, offline work

### GitHub-Based Control (`ChangeControlMethod.GITHUB`)

- Creates GitHub issues for tracking
- Draft PRs for code review
- API caching to minimize rate limits
- **Best for**: Team collaboration, API-enabled environments

## CLI Commands Reference

| Command | Description | Example |
|---------|-------------|---------|
| `optimize` | Start optimization task | `optimize --method adversarial --target *.py` |
| `agents list` | List all agents | `agents list` |
| `agents status` | Show agent details | `agents status agent-123` |
| `queue process` | Process task queue | `queue process` |
| `stats` | Show statistics | `stats` |
| `rollback` | Revert changes | `rollback patch-123 --force` |
| `config` | Manage configuration | `config set --key max_agents --value 10` |
| `validate` | Validate code | `validate file.py --level strict` |

## Configuration

Configuration is stored in `.optimizer-config.json`:

```json
{
  "change_control": "patch",
  "validation_level": "standard",
  "max_agents": 5,
  "ipfs_gateway": "http://127.0.0.1:5001",
  "github_repo": null,
  "github_token": null
}
```

## Examples

See `examples/agentic/` for practical examples:

- `simple_optimization.py` - Single-agent optimization
- `validation_example.py` - Validation at all levels
- `README.md` - Comprehensive examples guide

## Architecture Documentation

- **ARCHITECTURE_UNIFIED.md** - Unified optimizer architecture
- **ARCHITECTURE_AGENTIC_OPTIMIZERS.md** - Agentic optimizer design
- **IMPLEMENTATION_PLAN.md** - Implementation roadmap
- **USAGE_GUIDE.md** - Detailed usage guide
- **GITHUB_INTEGRATION.md** - GitHub integration guide

## Backlog

- See `TODO.md` for the living refactor/feature backlog and inline TODO inventory.

## Implementation Status

### Completed ✅
- Base infrastructure (Phase 1)
- All 4 optimization methods (Phase 2)
- Comprehensive validation framework (Phase 4)
- CLI interface with 8 commands (Phase 5)
- Practical examples (Phase 7 partial)

### In Progress 🚧
- Test suite (Phase 6)
- LLM router integration (Phase 3)
- Additional examples (Phase 7)

### Planned 📋
- Dashboard for monitoring
- GitHub Actions workflows (Phase 8)
- Production hardening (Phase 9)

## Requirements

- Python 3.12+
- Git (for patch-based control)
- IPFS daemon (optional, for IPFS storage)
- mypy (optional, for type validation)
- pytest (optional, for test validation)

## Contributing

When contributing to the optimizers module:

1. Follow the unified architecture in `common/`
2. Add comprehensive docstrings
3. Include type hints
4. Write tests for new functionality
5. Update relevant documentation
6. Use validation framework for code quality

## Support

For issues, questions, or contributions:
- See documentation in `docs/`
- Check examples in `examples/agentic/`
- Review architecture documents in this directory

## License

See repository LICENSE file for details.
