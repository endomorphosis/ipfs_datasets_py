# Performance Tuning Guide - Agentic Optimizer

**Document Version:** 1.0  
**Last Updated:** 2026-02-14  
**Target Audience:** DevOps, System Administrators, Performance Engineers

## Overview

This guide provides comprehensive performance tuning strategies for the agentic optimizer framework to maximize throughput, minimize latency, and optimize resource usage.

---

## Performance Metrics

### Key Performance Indicators (KPIs)

| Metric | Target | Good | Needs Improvement |
|--------|--------|------|-------------------|
| Optimization Time | < 30s | 30-60s | > 60s |
| Memory Usage | < 500MB | 500-1000MB | > 1000MB |
| LLM API Latency | < 2s | 2-5s | > 5s |
| Validation Time | < 10s | 10-30s | > 30s |
| Test Execution | < 20s | 20-60s | > 60s |

### Monitoring

**Built-in Resource Monitoring:**
```python
from ipfs_datasets_py.optimizers.agentic import ResourceMonitor

monitor = ResourceMonitor()
with monitor.monitor():
    # Your code here
    result = optimize_code()

stats = monitor.get_stats()
print(f"Time: {stats['elapsed_time']:.2f}s")
print(f"Memory: {stats['peak_memory_mb']:.1f}MB")
```

---

## LLM Optimization Strategies

### 1. Provider Selection

**Choose the Right Provider:**
```python
from ipfs_datasets_py.optimizers.agentic import OptimizerLLMRouter, LLMProvider

# Fast, code-focused tasks → Use Codex or Copilot
router = OptimizerLLMRouter(
    preferred_provider=LLMProvider.CODEX,
    fallback_providers=[LLMProvider.COPILOT, LLMProvider.LOCAL],
)

# Complex reasoning → Use Claude or GPT-4
router = OptimizerLLMRouter(
    preferred_provider=LLMProvider.CLAUDE,
    fallback_providers=[LLMProvider.GPT4],
)

# Budget-conscious → Use Local models
router = OptimizerLLMRouter(
    preferred_provider=LLMProvider.LOCAL,
)
```

**Provider Performance Characteristics:**
| Provider | Latency | Cost | Best For |
|----------|---------|------|----------|
| Codex | Low (1-2s) | Free | Code generation |
| Copilot | Very Low (0.5-1s) | Free | Simple code tasks |
| GPT-4 | Medium (2-4s) | High ($0.03/1K) | Complex reasoning |
| Claude | Medium (2-3s) | Medium ($0.008/1K) | Large context |
| Gemini | Medium (2-3s) | Free | Multi-modal tasks |
| Local | High (5-10s) | Free | Privacy, offline |

### 2. Prompt Optimization

**Minimize Prompt Size:**
```python
# ❌ DON'T: Include entire codebase
prompt = f"Optimize this code:\n{entire_codebase}"  # 100KB+

# ✅ DO: Include only relevant context
prompt = f"Optimize this function:\n{target_function}"  # 2KB
```

**Use Efficient Templates:**
```python
# ✅ Concise, focused prompts
template = """
Optimize the following function for performance:

{code}

Focus on: {optimization_goal}
Constraints: {constraints}
"""

# ❌ Verbose, unfocused prompts
template = """
Please carefully review the following code and think about
all possible ways it could be optimized, considering performance,
memory usage, readability, and maintainability...
"""
```

### 3. Token Management

**Track and Optimize Token Usage:**
```python
router = OptimizerLLMRouter(enable_tracking=True)

# After operations
stats = router.get_statistics()
print(f"Total tokens: {stats['total_tokens']:,}")
print(f"Total cost: ${stats['total_cost']:.4f}")
print(f"Success rate: {stats['success_rate']:.1%}")

# Identify expensive operations
for provider, tokens in stats['tokens_by_provider'].items():
    cost = tokens * PROVIDER_CAPABILITIES[provider].cost_per_1k_tokens / 1000
    print(f"{provider}: {tokens:,} tokens (${cost:.4f})")
```

**Token Reduction Strategies:**
- Use smaller context windows when possible
- Batch similar operations together
- Cache LLM responses for identical inputs
- Use cheaper providers for simple tasks

### 4. Circuit Breaker Configuration

**Tune for Your Workload:**
```python
from ipfs_datasets_py.optimizers.agentic.production_hardening import CircuitBreaker

# High-availability (more tolerant)
breaker = CircuitBreaker(
    failure_threshold=5,  # Allow more failures
    timeout=60,  # Longer recovery time
)

# Fast-fail (less tolerant)
breaker = CircuitBreaker(
    failure_threshold=2,  # Fail faster
    timeout=15,  # Quick recovery
)
```

---

## Validation Optimization

### 1. Validation Level Selection

**Choose Appropriate Level:**
```python
from ipfs_datasets_py.optimizers.agentic import OptimizationValidator, ValidationLevel

# Development: Fast iteration
validator = OptimizationValidator(level=ValidationLevel.BASIC)
# Checks: Syntax only (~1-2s)

# Standard: Balanced
validator = OptimizationValidator(level=ValidationLevel.STANDARD)
# Checks: Syntax + types + tests (~10-20s)

# Production: Comprehensive
validator = OptimizationValidator(level=ValidationLevel.STRICT)
# Checks: Standard + performance (~20-40s)

# Critical: Maximum safety
validator = OptimizationValidator(level=ValidationLevel.PARANOID)
# Checks: Everything (~30-60s)
```

**Performance Impact:**
| Level | Time | Coverage | Use Case |
|-------|------|----------|----------|
| BASIC | 1-2s | 20% | Development, fast iteration |
| STANDARD | 10-20s | 60% | CI/CD, pull requests |
| STRICT | 20-40s | 80% | Production deployments |
| PARANOID | 30-60s | 95% | Security-critical code |

### 2. Parallel Validation

**Enable Parallel Execution:**
```python
# ✅ Parallel validation (faster)
validator = OptimizationValidator(
    level=ValidationLevel.STRICT,
    parallel=True,  # Run validators in parallel
)

# Time: ~20s (multiple validators run simultaneously)

# ❌ Sequential validation (slower)
validator = OptimizationValidator(
    level=ValidationLevel.STRICT,
    parallel=False,
)

# Time: ~40s (validators run one after another)
```

**Speedup:**
- Parallel execution: 40-60% faster
- Best for multi-core systems
- Trade-off: Higher peak memory usage

### 3. Caching

**Cache Validation Results:**
```python
# Implement validation result caching
validation_cache = {}

def validate_with_cache(code: str, level: ValidationLevel):
    # Create cache key
    import hashlib
    cache_key = hashlib.sha256(
        f"{code}{level.value}".encode()
    ).hexdigest()
    
    # Check cache
    if cache_key in validation_cache:
        print("✅ Using cached validation result")
        return validation_cache[cache_key]
    
    # Validate
    validator = OptimizationValidator(level=level)
    result = validator.validate_sync(code, [], {})
    
    # Cache result
    validation_cache[cache_key] = result
    return result
```

---

## Resource Management

### 1. Memory Optimization

**Configure Memory Limits:**
```python
from ipfs_datasets_py.optimizers.agentic.production_hardening import SecurityConfig

config = SecurityConfig(
    max_memory_mb=512,  # Limit memory usage
    # Adjust based on available RAM
)

# System with 4GB RAM → 512MB
# System with 8GB RAM → 1024MB
# System with 16GB+ RAM → 2048MB
```

**Monitor Memory Usage:**
```python
monitor = ResourceMonitor()

with monitor.monitor():
    # Your code
    large_optimization()

stats = monitor.get_stats()
if stats['peak_memory_mb'] > 1000:
    print("⚠️ High memory usage detected!")
    print("Consider reducing batch size or optimization scope")
```

### 2. CPU Optimization

**Configure CPU Limits:**
```python
config = SecurityConfig(
    max_cpu_percent=80,  # Allow up to 80% CPU
)

# Development machine → 50% (leave room for IDE, browser)
# CI/CD server → 80% (maximize throughput)
# Shared server → 30% (be nice to others)
```

**Parallel Workloads:**
```python
import multiprocessing

# Optimal worker count
optimal_workers = max(1, multiprocessing.cpu_count() - 1)

# For parallel validation
validator = OptimizationValidator(
    level=ValidationLevel.STANDARD,
    parallel=True,
    max_workers=optimal_workers,
)
```

### 3. Timeout Configuration

**Set Appropriate Timeouts:**
```python
config = SecurityConfig(
    sandbox_timeout=60,  # 60s default
)

# Fast operations → 30s
# Standard operations → 60s
# Complex operations → 120s
# Long-running tests → 300s
```

---

## Caching Strategies

### 1. File-Based Caching

**Enable GitHub API Caching:**
```python
from ipfs_datasets_py.optimizers.agentic import UnifiedGitHubAPICache

cache = UnifiedGitHubAPICache(
    cache_dir=".cache/github-api",
    ttl=300,  # 5 minutes
)

# Cache reduces API calls by 70-90%
# Significant speedup for repeated operations
```

**Configure Cache TTL:**
```python
# Fast-changing data → 60s (1 minute)
# Moderate data → 300s (5 minutes)
# Stable data → 3600s (1 hour)
# Static data → 86400s (24 hours)
```

### 2. Policy Caching (Actor-Critic)

**Reuse Learned Policies:**
```python
from ipfs_datasets_py.optimizers.agentic import ActorCriticOptimizer

optimizer = ActorCriticOptimizer(
    llm_router=router,
    policy_file="learned_policies.json",  # Cache policies
)

# First run: Learns patterns (slow)
# Subsequent runs: Reuses patterns (fast)
```

---

## Benchmarking

### 1. Baseline Measurement

**Establish Baseline:**
```bash
# Time a complete optimization
time python -m ipfs_datasets_py.optimizers.agentic.cli optimize \
  --method test_driven \
  --target my_code.py \
  --description "Baseline measurement"

# Record: Total time, memory usage, API calls
```

### 2. A/B Testing

**Compare Configurations:**
```python
import time

configs = [
    {"level": ValidationLevel.BASIC, "parallel": True},
    {"level": ValidationLevel.STANDARD, "parallel": True},
    {"level": ValidationLevel.STANDARD, "parallel": False},
]

for config in configs:
    validator = OptimizationValidator(**config)
    
    start = time.time()
    result = validator.validate_sync(code, files, {})
    elapsed = time.time() - start
    
    print(f"Config: {config}")
    print(f"Time: {elapsed:.2f}s")
    print(f"Passed: {result.passed}")
    print()
```

### 3. Profiling

**Profile Slow Operations:**
```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# Your code
optimizer.optimize(task)

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 slowest functions
```

---

## Production Recommendations

### Small Projects (< 10 files):
```python
config = {
    "validation_level": ValidationLevel.STANDARD,
    "parallel": True,
    "max_agents": 3,
    "preferred_provider": LLMProvider.CODEX,
}
```

### Medium Projects (10-100 files):
```python
config = {
    "validation_level": ValidationLevel.STANDARD,
    "parallel": True,
    "max_agents": 5,
    "preferred_provider": LLMProvider.CLAUDE,
}
```

### Large Projects (100+ files):
```python
config = {
    "validation_level": ValidationLevel.BASIC,  # Faster iteration
    "parallel": True,
    "max_agents": 10,
    "preferred_provider": LLMProvider.CLAUDE,
    "enable_caching": True,
}
```

---

## Troubleshooting

### Slow Performance?

**1. Check Validation Level:**
```bash
# Switch to faster level temporarily
python -m ipfs_datasets_py.optimizers.agentic.cli validate \
  code.py --level basic  # Instead of paranoid
```

**2. Enable Parallel Validation:**
```python
validator = OptimizationValidator(parallel=True)
```

**3. Reduce Scope:**
```bash
# Optimize fewer files at once
python -m ipfs_datasets_py.optimizers.agentic.cli optimize \
  --target single_file.py  # Instead of entire directory
```

### High Memory Usage?

**1. Reduce Memory Limits:**
```python
config = SecurityConfig(max_memory_mb=256)  # Lower limit
```

**2. Process Files in Batches:**
```python
# Instead of processing 100 files at once
# Process 10 files at a time
```

### LLM Timeouts?

**1. Increase Circuit Breaker Timeout:**
```python
breaker = CircuitBreaker(timeout=60)  # From 30s default
```

**2. Switch to Faster Provider:**
```python
router = OptimizerLLMRouter(
    preferred_provider=LLMProvider.CODEX,  # Faster than GPT-4
)
```

---

## Summary

**Quick Wins (Immediate Impact):**
1. ✅ Enable parallel validation
2. ✅ Use appropriate validation level
3. ✅ Enable GitHub API caching
4. ✅ Choose optimal LLM provider

**Medium-Term Optimizations:**
1. ✅ Implement validation result caching
2. ✅ Tune circuit breaker thresholds
3. ✅ Optimize prompt templates
4. ✅ Monitor and track token usage

**Long-Term Strategies:**
1. ✅ Profile and optimize hot paths
2. ✅ Implement custom caching layers
3. ✅ Consider local LLM deployment
4. ✅ Scale horizontally with multiple workers

**Expected Results:**
- 40-60% faster with parallel validation
- 70-90% fewer API calls with caching
- 30-50% cost reduction with provider optimization
- 2-3x throughput with tuned configuration
