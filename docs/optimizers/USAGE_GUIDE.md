# Agentic Optimizer - Usage Guide

## Quick Start

This guide shows you how to use the agentic optimizer system to enable recursive self-improvement of your codebase.

## Installation

The agentic optimizer is part of the `ipfs_datasets_py` package:

```bash
# Install with optimizer dependencies
pip install -e ".[all]"

# Or just the optimizer extras
pip install -e ".[optimizer]"
```

## Basic Usage

### 1. Simple Single-Agent Optimization

```python
from pathlib import Path
from ipfs_datasets_py.llm_router import LLMRouter
from ipfs_datasets_py.optimizers.agentic import (
    TestDrivenOptimizer,
    OptimizationTask,
    ChangeControlMethod,
    OptimizationMethod,
)

# Initialize LLM router
router = LLMRouter()

# Create optimizer
optimizer = TestDrivenOptimizer(
    agent_id="test-optimizer-1",
    llm_router=router,
    change_control=ChangeControlMethod.PATCH,
)

# Define optimization task
task = OptimizationTask(
    task_id="optimize-ml-module",
    description="Optimize machine learning module for performance",
    target_files=[
        Path("ipfs_datasets_py/ml/model_loader.py"),
        Path("ipfs_datasets_py/ml/inference.py"),
    ],
    method=OptimizationMethod.TEST_DRIVEN,
    priority=80,
    constraints={
        "min_improvement": 10,  # 10% minimum performance improvement
        "maintain_coverage": True,
    },
)

# Run optimization
result = optimizer.optimize(task)

# Check results
if result.success:
    print(f"✓ Optimization successful!")
    print(f"  Patch: {result.patch_path}")
    print(f"  Improvement: {result.metrics['improvement_percent']:.1f}%")
    print(f"  Tests passed: {result.metrics['tests_passed']}")
else:
    print(f"✗ Optimization failed: {result.error_message}")

# Validate the optimization
validation = optimizer.validate(result)
if validation.passed:
    print("✓ Validation passed")
else:
    print(f"✗ Validation failed: {validation.errors}")
```

### 2. Multi-Agent Coordination

```python
from pathlib import Path
import asyncio
from ipfs_datasets_py.optimizers.agentic import (
    AgentCoordinator,
    TestDrivenOptimizer,
    OptimizationTask,
)
from ipfs_datasets_py.llm_router import LLMRouter
import ipfshttpclient

# Setup
router = LLMRouter()
ipfs_client = ipfshttpclient.connect()
repo_path = Path("/path/to/your/repo")

# Create coordinator
coordinator = AgentCoordinator(
    repo_path=repo_path,
    ipfs_client=ipfs_client,
    max_agents=5,
)

# Register multiple agents
agent_ids = []
for i in range(3):
    optimizer = TestDrivenOptimizer(
        agent_id=f"agent-{i}",
        llm_router=router,
    )
    agent_id = coordinator.register_agent(optimizer)
    agent_ids.append(agent_id)

# Create tasks
tasks = [
    OptimizationTask(
        task_id="task-1",
        description="Optimize data loading",
        target_files=[Path("ipfs_datasets_py/data_loader.py")],
    ),
    OptimizationTask(
        task_id="task-2",
        description="Optimize embeddings",
        target_files=[Path("ipfs_datasets_py/embeddings/faiss_store.py")],
    ),
    OptimizationTask(
        task_id="task-3",
        description="Optimize search",
        target_files=[Path("ipfs_datasets_py/search/engine.py")],
    ),
]

# Queue tasks
for task in tasks:
    coordinator.queue_task(task)

# Process queue asynchronously
async def main():
    results = await coordinator.process_queue()
    
    # Print results
    for result in results:
        print(f"Task {result.task_id}: {'✓' if result.success else '✗'}")
    
    # Get statistics
    stats = coordinator.get_statistics()
    print(f"\nStatistics:")
    print(f"  Total agents: {stats['total_agents']}")
    print(f"  Completed: {stats['total_completed']}")
    print(f"  Failed: {stats['total_failed']}")
    print(f"  Success rate: {stats['success_rate']:.1%}")

asyncio.run(main())
```

### 3. Using Patch-Based Change Control

```python
from pathlib import Path
from ipfs_datasets_py.optimizers.agentic import (
    PatchBasedChangeController,
    PatchManager,
    WorktreeManager,
    IPFSPatchStore,
)
import ipfshttpclient

# Setup
repo_path = Path("/path/to/repo")
ipfs_client = ipfshttpclient.connect()

# Create change controller
controller = PatchBasedChangeController(
    repo_path=repo_path,
    ipfs_client=ipfs_client,
)

# After optimization (with result object)
# Create change request
patch_cid = controller.create_change(result)
print(f"Patch stored at: ipfs://{patch_cid}")

# Check approval (e.g., via marker file or external system)
if controller.check_approval(patch_cid):
    # Apply the change
    if controller.apply_change(patch_cid):
        print("✓ Change applied successfully")
    else:
        print("✗ Failed to apply change")
else:
    print("Change pending approval")

# If something goes wrong, rollback
if controller.rollback_change(patch_cid):
    print("✓ Change rolled back")
```

### 4. Using GitHub-Based Change Control

```python
from pathlib import Path
from ipfs_datasets_py.optimizers.agentic import (
    GitHubChangeController,
    CacheBackend,
)
from github import Github

# Setup
github_client = Github(token="your-github-token")
repo = "owner/repo"

# Create change controller with caching
controller = GitHubChangeController(
    github_client=github_client,
    repo=repo,
    cache_backend=CacheBackend.FILE,
    cache_dir=Path(".cache/github-api"),
    rate_limit_threshold=100,  # Switch to patch mode if < 100 requests remaining
)

# After optimization
try:
    # Create issue and draft PR
    pr_url = controller.create_change(result)
    print(f"Draft PR created: {pr_url}")
    
    # Check approval status
    if controller.check_approval(pr_url):
        # Apply (merge) the PR
        if controller.apply_change(pr_url):
            print("✓ PR merged successfully")
except RuntimeError as e:
    # Rate limit exceeded - fallback to patch system
    print(f"GitHub rate limit reached: {e}")
    print("Falling back to patch-based system...")
```

## Configuration

### Environment Variables

```bash
# GitHub Integration
export OPTIMIZER_GITHUB_TOKEN=ghp_xxx
export OPTIMIZER_GITHUB_REPO=owner/repo
export OPTIMIZER_GITHUB_CACHE_TTL=300  # 5 minutes
export OPTIMIZER_GITHUB_RATE_LIMIT_THRESHOLD=100

# IPFS Configuration
export OPTIMIZER_IPFS_API=/ip4/127.0.0.1/tcp/5001
export OPTIMIZER_IPFS_GATEWAY=http://localhost:8080

# LLM Router
export OPTIMIZER_LLM_PROVIDER=gpt-4
export OPTIMIZER_LLM_FALLBACK=claude-3-opus

# Agent Configuration
export OPTIMIZER_MAX_AGENTS=5
export OPTIMIZER_WORKTREE_BASE=/tmp/optimizer-worktrees
export OPTIMIZER_PATCH_HISTORY_LIMIT=1000

# Validation
export OPTIMIZER_RUN_INTEGRATION_TESTS=true
export OPTIMIZER_RUN_PERFORMANCE_TESTS=true
export OPTIMIZER_MIN_TEST_COVERAGE=80
```

### Configuration File

Create `optimizer_config.yaml`:

```yaml
github:
  token: ${OPTIMIZER_GITHUB_TOKEN}
  repo: ${OPTIMIZER_GITHUB_REPO}
  cache:
    backend: file
    ttl_seconds: 300
    directory: .cache/github-api
  rate_limit:
    threshold: 100
    fallback_to_patch: true

ipfs:
  api_url: /ip4/127.0.0.1/tcp/5001
  gateway: http://localhost:8080

llm:
  provider: gpt-4
  fallback_providers:
    - claude-3-opus
    - codex
  max_tokens: 4000
  temperature: 0.2

agents:
  max_concurrent: 5
  worktree_base: /tmp/optimizer-worktrees

validation:
  run_integration_tests: true
  run_performance_tests: true
  min_test_coverage: 80
  min_performance_improvement: 10

optimization:
  methods:
    - test_driven
    - adversarial
    - actor_critic
    - chaos
  default_method: test_driven
  auto_approve_threshold: 95  # Auto-approve if validation score > 95%
```

## Advanced Usage

### Creating Custom Optimizers

```python
from ipfs_datasets_py.optimizers.agentic import (
    AgenticOptimizer,
    OptimizationMethod,
    OptimizationResult,
    OptimizationTask,
    ValidationResult,
)

class MyCustomOptimizer(AgenticOptimizer):
    """Custom optimization strategy."""
    
    def _get_method(self) -> OptimizationMethod:
        return OptimizationMethod.ADVERSARIAL  # Or create custom enum
    
    def optimize(self, task: OptimizationTask) -> OptimizationResult:
        """Implement your optimization logic."""
        # Your implementation here
        pass
    
    def validate(self, result: OptimizationResult) -> ValidationResult:
        """Implement your validation logic."""
        # Your implementation here
        pass
```

### Monitoring and Metrics

```python
# Get coordinator statistics
stats = coordinator.get_statistics()

print(f"Total agents: {stats['total_agents']}")
print(f"Active agents: {stats['status_distribution']}")
print(f"Queued tasks: {stats['queued_tasks']}")
print(f"Success rate: {stats['success_rate']:.1%}")
print(f"Conflicts detected: {stats['conflicts_detected']}")

# Get individual agent status
for agent_id in coordinator.list_agents():
    state = coordinator.get_agent_status(agent_id)
    print(f"{agent_id}: {state.status.value}")
    print(f"  Completed: {len(state.completed_tasks)}")
    print(f"  Failed: {len(state.failed_tasks)}")
```

## Troubleshooting

### Rate Limit Issues

```python
# Check rate limit status
limiter = controller.rate_limiter
status = limiter.get_status()

if not status['can_make_request']:
    print(f"Rate limit reached. Reset in {status['time_until_reset']:.0f}s")
    print("Switching to patch-based system...")
    
    # Use patch controller instead
    patch_controller = PatchBasedChangeController(...)
```

### Conflict Resolution

```python
# Get conflict history
conflicts = coordinator.conflict_resolver.get_conflict_history()

for conflict in conflicts:
    print(f"Conflict between {conflict.patch1_id} and {conflict.patch2_id}")
    print(f"  Files: {conflict.conflicting_files}")
    print(f"  Severity: {conflict.severity}/10")
    print(f"  Resolution: {conflict.resolution}")
```

### Patch Rollback

```python
# Rollback a specific patch
if controller.rollback_change(patch_cid):
    print("✓ Patch rolled back successfully")
else:
    print("✗ Rollback failed")

# View patch history
history = patch_manager.get_patch_history(task_id="task-1")
for patch in history:
    print(f"{patch.patch_id}: {patch.description}")
    print(f"  Applied: {patch.applied}")
    print(f"  CID: {patch.ipfs_cid}")
```

## Best Practices

1. **Start Small**: Begin with single-file optimizations before tackling larger modules
2. **Use Constraints**: Always specify constraints to guide optimization
3. **Monitor Rate Limits**: Keep an eye on GitHub API usage
4. **Review Changes**: Always review optimizations before applying to production
5. **Use IPFS Pinning**: Pin important patches to ensure availability
6. **Track Metrics**: Monitor success rates and performance improvements
7. **Test Thoroughly**: Run full test suite after applying optimizations
8. **Backup First**: Create git branches or backups before large-scale optimizations

## Next Steps

- Read the [Architecture Documentation](ARCHITECTURE_AGENTIC_OPTIMIZERS.md)
- Review the [Implementation Plan](IMPLEMENTATION_PLAN.md)
- Check the [API Reference](API_REFERENCE.md) (coming soon)
- Try the [Examples](../../examples/agentic/) (coming soon)

## Support

For issues or questions:
- Create an issue on GitHub
- Check existing documentation
- Review test cases for usage examples
