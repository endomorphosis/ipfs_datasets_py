# Comprehensive Refactoring Plan: .github/ and utils/ Directories

## Executive Summary

This document outlines a comprehensive refactoring plan to eliminate 60-80% code duplication between `.github/`, `utils/`, and `optimizers/` directories while creating unified infrastructure for caching, GitHub operations, CLI tools, and workflow utilities.

**Key Goals:**
1. Create single source of truth for GitHub API operations
2. Implement unified caching with P2P support throughout codebase
3. Standardize CLI tool wrappers with consistent interfaces
4. Make .github/scripts thin wrappers (10-20 lines) that import from utils/
5. Enable code reuse across workflows, optimizers, and utility functions

**Expected Impact:**
- ~3,400 lines of duplicate code eliminated
- 60-80% reduction in GitHub API code duplication
- Single cache shared across all workflows and optimizers
- P2P cache sharing available to all components
- Improved testability and maintainability

## Table of Contents

1. [Current State Analysis](#current-state-analysis)
2. [Problem Statement](#problem-statement)
3. [Solution Architecture](#solution-architecture)
4. [Implementation Plan](#implementation-plan)
5. [Usage Examples](#usage-examples)
6. [Migration Strategy](#migration-strategy)
7. [Testing Strategy](#testing-strategy)
8. [Success Metrics](#success-metrics)

## Current State Analysis

### .github/ Directory

**Size:** 7,118 lines across 37+ Python scripts

**Key Components:**
- `scripts/github_api_counter.py` (300+ lines) - API call tracking
- `scripts/copilot_workflow_helper.py` (250+ lines) - Copilot integration
- `scripts/github_api_counter_thin.py` (60 lines) - Thin wrapper
- `scripts/copilot_workflow_helper_thin.py` (150 lines) - Thin wrapper
- 20+ GitHub Actions workflows
- Configuration files: `cache-config.yml`, `p2p-config.yml`

**Functionality:**
- GitHub API operations (counters, wrappers)
- Workflow automation (autohealing, autofix)
- Copilot CLI integration
- Test automation
- Metrics collection

**Issues:**
- Duplicate GitHub API functionality
- No use of utils/ directory
- Embedded Python logic in workflows
- Ad-hoc caching implementations

### utils/ Directory

**Size:** 16,161 lines across 33+ Python files

**Key Components:**
- `github_wrapper.py` (30KB) - GitHub CLI wrapper with caching
- `github_cli.py` (21KB) - Alternative GitHub CLI interface
- `query_cache.py` (10KB) - TTL-based cache
- `copilot_cli.py`, `claude_cli.py`, `vscode_cli.py`, `gemini_cli.py` - CLI wrappers
- Various utilities: text processing, embedding adapters, credential management

**Functionality:**
- GitHub operations (separate from .github/)
- Generic caching (not integrated with .github/)
- CLI tool wrappers
- Data transformation utilities

**Issues:**
- Duplicate GitHub functionality vs .github/
- No P2P cache support
- Not used by .github/scripts
- No integration with optimizers/

### optimizers/agentic/ Directory

**Size:** Already has some integration

**Key Components:**
- `github_api_unified.py` (600 lines) - Unified GitHub API
- `github_control.py` - Uses unified API
- `patch_control.py` - Change management
- Support for `cache-config.yml` and `p2p-config.yml`

**Functionality:**
- GitHub API with caching
- Rate limiting
- API call tracking
- P2P ready (via config)

**Issues:**
- Not shared with .github/ or utils/
- Duplicate functionality exists elsewhere
- Should be in utils/ for wider reuse

## Problem Statement

### Code Duplication Identified

#### High Priority (60-80% duplication)

**1. GitHub API Caching - 3 implementations:**
- `.github/scripts/github_api_counter.py` (300 lines)
- `utils/github_wrapper.py` (contains GitHubAPICache)
- `optimizers/agentic/github_api_unified.py` (600 lines)

**2. GitHub CLI Wrappers - 2 implementations:**
- `utils/github_wrapper.py` (GitHubCLI class)
- `utils/github_cli.py` (separate implementation)

#### Medium Priority (40-50% duplication)

**3. Query Caching - 2+ implementations:**
- `utils/query_cache.py` (TTLCache-based)
- Ad-hoc caches in various .github/scripts
- No P2P support in any implementation

**4. CLI Tool Wrappers - Scattered across utils/:**
- `copilot_cli.py`, `claude_cli.py`, `vscode_cli.py`, `gemini_cli.py`
- Similar patterns, different implementations
- No shared base class

### Integration Issues

**5. No Code Reuse Between Directories:**
- .github/scripts don't import from utils/
- utils/ doesn't have .github/ functionality
- P2P config exists but not implemented in utils/
- optimizers/ has own implementations

## Solution Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────────────┐
│                    ipfs_datasets_py/                         │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌────────────┐         ┌──────────────┐                    │
│  │ .github/   │────────▶│   utils/     │◀───────┐          │
│  │ workflows  │         │  (unified)   │         │          │
│  └────────────┘         └──────────────┘         │          │
│       │ thin                    ▲                 │          │
│       │ wrappers                │                 │          │
│       │                         │                 │          │
│  ┌────▼─────────┐              │           ┌─────┴────────┐ │
│  │ .github/     │              │           │ optimizers/  │ │
│  │ scripts/     │              └───────────│  agentic/    │ │
│  │ (10-20 lines)│                          │              │ │
│  └──────────────┘                          └──────────────┘ │
│                                                               │
│  Configuration files:                                        │
│  - .github/cache-config.yml (loads in utils.cache)          │
│  - .github/p2p-config.yml (loads in utils.cache.p2p)        │
└─────────────────────────────────────────────────────────────┘
```

### New utils/ Structure

```
utils/
├── cache/                      # NEW - Unified caching infrastructure
│   ├── __init__.py            # Public API exports
│   ├── base.py                # Abstract base cache classes
│   ├── local.py               # Local TTL cache implementation
│   ├── p2p.py                 # P2P distributed cache
│   ├── github_cache.py        # GitHub API-specific cache
│   ├── config_loader.py       # Load cache-config.yml & p2p-config.yml
│   └── README.md              # Usage guide
│
├── github/                     # NEW - Unified GitHub operations
│   ├── __init__.py            # Public API exports
│   ├── api_client.py          # Unified GitHub API client
│   ├── cli_wrapper.py         # Unified CLI wrapper
│   ├── counter.py             # API call tracking and metrics
│   ├── rate_limiter.py        # Rate limit management
│   └── README.md              # Usage guide
│
├── cli_tools/                  # NEW - Unified CLI tool wrappers
│   ├── __init__.py            # Public API exports
│   ├── base.py                # Base CLI tool abstraction
│   ├── copilot.py             # Copilot wrapper (refactored)
│   ├── claude.py              # Claude wrapper (refactored)
│   ├── vscode.py              # VSCode wrapper (refactored)
│   ├── gemini.py              # Gemini wrapper (refactored)
│   └── README.md              # Usage guide
│
├── workflows/                  # NEW - Workflow utilities
│   ├── __init__.py            # Public API exports
│   ├── helpers.py             # Common workflow helpers
│   ├── metrics.py             # Metrics collection infrastructure
│   ├── logging_utils.py       # Logging utilities
│   ├── error_handling.py      # Error handling patterns
│   └── README.md              # Usage guide
│
├── __init__.py                # Re-export for backward compatibility
├── github_wrapper.py          # DEPRECATED - Imports from utils.github
├── github_cli.py              # DEPRECATED - Imports from utils.github
├── query_cache.py             # DEPRECATED - Imports from utils.cache
├── copilot_cli.py             # DEPRECATED - Imports from utils.cli_tools
├── claude_cli.py              # DEPRECATED - Imports from utils.cli_tools
├── vscode_cli.py              # DEPRECATED - Imports from utils.cli_tools
└── gemini_cli.py              # DEPRECATED - Imports from utils.cli_tools
```

### New .github/scripts/ Structure

```
.github/scripts/
├── github_api_counter_thin.py      # NEW - 10-20 lines, imports utils
├── copilot_helper_thin.py          # NEW - 10-20 lines, imports utils
├── workflow_helper_thin.py         # NEW - 10-20 lines, imports utils
├── github_api_counter.py           # LEGACY - Kept for compatibility
├── copilot_workflow_helper.py      # LEGACY - Kept for compatibility
└── README.md                       # Updated with new structure
```

### Updated optimizers/agentic/ Structure

```
optimizers/agentic/
├── github_api_unified.py           # DEPRECATED - Import from utils.github
├── github_control.py               # UPDATED - Use utils.github
├── patch_control.py                # UPDATED - Use utils.cache
└── coordinator.py                  # UPDATED - Use utils.cache for P2P
```

## Implementation Plan

### Phase 1: Foundation (Week 1)

#### 1.1 Create utils/cache/ Module

**Files to create:**
1. `utils/cache/__init__.py`
2. `utils/cache/base.py`
3. `utils/cache/local.py`
4. `utils/cache/p2p.py`
5. `utils/cache/github_cache.py`
6. `utils/cache/config_loader.py`
7. `utils/cache/README.md`

**Key features:**
- Abstract base cache interface
- Local TTL cache (consolidates query_cache.py)
- P2P distributed cache (loads p2p-config.yml)
- GitHub API-specific cache (loads cache-config.yml)
- ETag support for conditional requests
- Thread-safe operations
- Statistics tracking

#### 1.2 Create utils/github/ Module

**Files to create:**
1. `utils/github/__init__.py`
2. `utils/github/api_client.py`
3. `utils/github/cli_wrapper.py`
4. `utils/github/counter.py`
5. `utils/github/rate_limiter.py`
6. `utils/github/README.md`

**Key features:**
- Unified GitHub API client (consolidates 3 implementations)
- Unified CLI wrapper (consolidates 2 implementations)
- API call tracking and statistics
- Rate limit monitoring and management
- Uses utils.cache for caching

#### 1.3 Create utils/cli_tools/ Module

**Files to create:**
1. `utils/cli_tools/__init__.py`
2. `utils/cli_tools/base.py`
3. `utils/cli_tools/copilot.py`
4. `utils/cli_tools/claude.py`
5. `utils/cli_tools/vscode.py`
6. `utils/cli_tools/gemini.py`
7. `utils/cli_tools/README.md`

**Key features:**
- Abstract base CLI tool class
- Consistent interface across all tools
- Shared error handling and logging
- Uses utils.cache for caching

#### 1.4 Create utils/workflows/ Module

**Files to create:**
1. `utils/workflows/__init__.py`
2. `utils/workflows/helpers.py`
3. `utils/workflows/metrics.py`
4. `utils/workflows/logging_utils.py`
5. `utils/workflows/error_handling.py`
6. `utils/workflows/README.md`

**Key features:**
- Common workflow helper functions
- Metrics collection infrastructure
- Standardized logging
- Error handling patterns

### Phase 2: Migration (Week 2)

#### 2.1 Update Deprecated Files

**Files to update:**
1. `utils/github_wrapper.py` - Add deprecation warning, import from utils.github
2. `utils/github_cli.py` - Add deprecation warning, import from utils.github
3. `utils/query_cache.py` - Add deprecation warning, import from utils.cache
4. `utils/copilot_cli.py` - Add deprecation warning, import from utils.cli_tools
5. `utils/claude_cli.py` - Add deprecation warning, import from utils.cli_tools
6. `utils/vscode_cli.py` - Add deprecation warning, import from utils.cli_tools
7. `utils/gemini_cli.py` - Add deprecation warning, import from utils.cli_tools

**Pattern:**
```python
"""DEPRECATED: This module has been moved to utils.github.
Please update imports:
    from ipfs_datasets_py.utils.github import GitHubClient
"""
import warnings
warnings.warn(
    "utils.github_wrapper is deprecated. Use utils.github instead.",
    DeprecationWarning,
    stacklevel=2
)

from .github import GitHubClient as GitHubCLI
__all__ = ['GitHubCLI']
```

#### 2.2 Create Thin Wrappers in .github/scripts

**Files to create:**
1. `.github/scripts/github_api_counter_thin.py`
2. `.github/scripts/copilot_helper_thin.py`
3. `.github/scripts/workflow_helper_thin.py`

**Example:**
```python
#!/usr/bin/env python3
"""Thin wrapper for GitHub API counter - imports from utils."""
import sys
from pathlib import Path

# Add repository root to path
repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root))

from ipfs_datasets_py.utils.github import APICounter

if __name__ == '__main__':
    counter = APICounter()
    counter.run_from_cli(sys.argv[1:])
```

#### 2.3 Update optimizers/agentic

**Files to update:**
1. `optimizers/agentic/github_control.py` - Use utils.github
2. `optimizers/agentic/patch_control.py` - Use utils.cache
3. `optimizers/agentic/coordinator.py` - Use utils.cache.p2p
4. `optimizers/agentic/__init__.py` - Update exports

### Phase 3: Integration Testing (Week 3)

#### 3.1 Unit Tests

**Test files to create:**
1. `tests/unit_tests/utils/cache/test_local_cache.py`
2. `tests/unit_tests/utils/cache/test_p2p_cache.py`
3. `tests/unit_tests/utils/cache/test_github_cache.py`
4. `tests/unit_tests/utils/github/test_api_client.py`
5. `tests/unit_tests/utils/github/test_cli_wrapper.py`
6. `tests/unit_tests/utils/github/test_counter.py`
7. `tests/unit_tests/utils/cli_tools/test_base.py`
8. `tests/unit_tests/utils/cli_tools/test_copilot.py`

#### 3.2 Integration Tests

**Test files to create:**
1. `tests/integration/test_cache_integration.py`
2. `tests/integration/test_github_integration.py`
3. `tests/integration/test_cli_tools_integration.py`
4. `tests/integration/test_workflow_utils_integration.py`

#### 3.3 Workflow Tests

**Test workflows to create:**
1. `.github/workflows/test-unified-cache.yml`
2. `.github/workflows/test-thin-wrappers.yml`

### Phase 4: Documentation (Week 4)

#### 4.1 Module Documentation

**Files to create/update:**
1. `docs/REFACTORING_PLAN_GITHUB_UTILS.md` (this file)
2. `utils/cache/README.md`
3. `utils/github/README.md`
4. `utils/cli_tools/README.md`
5. `utils/workflows/README.md`
6. `docs/guides/UNIFIED_UTILS_GUIDE.md`
7. `docs/guides/MIGRATION_GUIDE_GITHUB_UTILS.md`

#### 4.2 API Documentation

Auto-generate API docs for all new modules.

### Phase 5: Deployment (Week 5)

#### 5.1 Gradual Rollout

1. Enable unified cache in staging
2. Monitor cache effectiveness
3. Test P2P cache sharing
4. Update workflows one at a time
5. Monitor for issues

#### 5.2 Deprecation Timeline

- Week 5: Add deprecation warnings
- Week 8: Update all internal usage
- Week 12: Consider removing deprecated files

## Usage Examples

### Unified Cache

```python
from ipfs_datasets_py.utils.cache import UnifiedCache, P2PCache

# Local TTL cache
cache = UnifiedCache(backend='local', ttl=300)
cache.set('key', 'value')
value = cache.get('key')

# P2P distributed cache (loads config from .github/p2p-config.yml)
p2p_cache = P2PCache()
p2p_cache.broadcast('shared_key', 'shared_value')
value = p2p_cache.get_from_network('shared_key')

# GitHub API-specific cache (loads config from .github/cache-config.yml)
from ipfs_datasets_py.utils.cache import GitHubCache
gh_cache = GitHubCache()
gh_cache.cache_response('repos/owner/repo', response, operation_type='get_repo_info')
```

### Unified GitHub Client

```python
from ipfs_datasets_py.utils.github import GitHubClient

# Single client for all GitHub operations
client = GitHubClient()

# List repositories
repos = client.list_repos()

# Create issue
issue = client.create_issue(title='Bug found', body='Description')

# Get API statistics
stats = client.get_api_stats()
print(f"API calls: {stats['total_calls']}")
print(f"Cache hit rate: {stats['cache_hit_rate']:.2%}")

# Rate limit info
limits = client.get_rate_limits()
print(f"Remaining: {limits['remaining']}/{limits['limit']}")
```

### Unified CLI Tools

```python
from ipfs_datasets_py.utils.cli_tools import Copilot, Claude, VSCode

# Copilot
copilot = Copilot()
suggestion = copilot.suggest('Fix this code')
explanation = copilot.explain('def func(): pass')

# Claude (same interface)
claude = Claude()
response = claude.query('Explain this concept')

# VSCode (same interface)
vscode = VSCode()
result = vscode.execute(['code', '--list-extensions'])
```

### Thin Wrapper in .github/scripts

```python
#!/usr/bin/env python3
# .github/scripts/github_api_counter_thin.py

import sys
from pathlib import Path

# Add repo to path
repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root))

from ipfs_datasets_py.utils.github import APICounter

if __name__ == '__main__':
    counter = APICounter()
    counter.run_gh_command(sys.argv[1:])
    counter.save_metrics()
    print(counter.report())
```

### Workflow Usage

```yaml
# .github/workflows/example.yml
- name: Track API calls
  run: |
    python .github/scripts/github_api_counter_thin.py gh pr list
    
- name: Get Copilot suggestion
  run: |
    python .github/scripts/copilot_helper_thin.py suggest-fix workflow.yml
```

## Migration Strategy

### Backward Compatibility

1. **Keep all existing files** - No breaking changes
2. **Add deprecation warnings** - Warn users about new locations
3. **Create aliases** - Old imports still work via re-exports
4. **Gradual migration** - Update code over time

### Example Deprecation

```python
# utils/github_wrapper.py (old location)
"""
DEPRECATED: This module has been moved.

Old import (deprecated):
    from ipfs_datasets_py.utils.github_wrapper import GitHubCLI

New import:
    from ipfs_datasets_py.utils.github import GitHubClient
"""

import warnings
warnings.warn(
    "utils.github_wrapper is deprecated. Use utils.github.GitHubClient instead.",
    DeprecationWarning,
    stacklevel=2
)

# Backward compatible re-export
from .github import GitHubClient as GitHubCLI

__all__ = ['GitHubCLI']
```

### Migration Steps for Users

1. **No action required initially** - Everything works via re-exports
2. **Update imports gradually** - Follow deprecation warnings
3. **Use new interfaces** - Take advantage of new features
4. **Remove deprecated usage** - Before they're removed

## Testing Strategy

### Unit Tests

**Coverage goals:**
- utils/cache/: 90%+ coverage
- utils/github/: 85%+ coverage
- utils/cli_tools/: 80%+ coverage
- utils/workflows/: 85%+ coverage

**Test categories:**
1. Basic functionality tests
2. Edge case tests
3. Error handling tests
4. Thread safety tests (for cache)
5. P2P communication tests

### Integration Tests

**Test scenarios:**
1. Cache sharing between workflows
2. P2P cache synchronization
3. GitHub API with caching and rate limiting
4. CLI tools with caching
5. Workflow helpers in real workflows

### Performance Tests

**Benchmarks:**
1. Cache hit/miss performance
2. P2P broadcast latency
3. API rate limit effectiveness
4. Memory usage under load

### Workflow Tests

**Test workflows:**
1. End-to-end workflow using thin wrappers
2. P2P cache sharing between runners
3. Rate limit protection in action
4. Metrics collection accuracy

## Success Metrics

### Code Quality Metrics

**Before Refactoring:**
- GitHub API code: ~3,000 lines (3 implementations)
- Cache code: ~2,000 lines (2+ implementations)
- CLI wrapper code: ~1,500 lines (scattered)
- Total: ~6,500 lines

**After Refactoring:**
- Unified GitHub code: ~900 lines
- Unified cache code: ~800 lines
- Unified CLI wrappers: ~500 lines
- Workflow utilities: ~300 lines
- Total: ~2,500 lines

**Reduction: ~4,000 lines (62% reduction)**

### Performance Metrics

**Targets:**
- Cache hit rate: >70%
- P2P cache sharing: Working across runners
- API rate limit usage: Reduced by 30%
- Workflow execution time: 10-20% faster

### Maintainability Metrics

**Improvements:**
- Single source of truth for each functionality
- All .github/scripts < 50 lines
- Consistent interfaces across all tools
- Comprehensive documentation
- Easy to test and extend

### Developer Experience Metrics

**Improvements:**
- Learn once, use everywhere
- Clear module ownership
- Comprehensive usage examples
- Easy to find functionality
- Better error messages

## Risks and Mitigation

### Risk 1: Breaking Changes

**Mitigation:**
- Keep all existing files with deprecation warnings
- Create backward-compatible re-exports
- Gradual migration timeline
- Comprehensive testing

### Risk 2: P2P Cache Complexity

**Mitigation:**
- P2P is optional (falls back to local cache)
- Comprehensive testing in isolated environment
- Clear documentation
- Monitoring and alerting

### Risk 3: Performance Regression

**Mitigation:**
- Benchmark before and after
- Load testing
- Gradual rollout
- Quick rollback capability

### Risk 4: Adoption Resistance

**Mitigation:**
- Clear benefits documentation
- Migration guide with examples
- Support for questions
- Gradual, optional migration

## Conclusion

This refactoring plan addresses the core issues of code duplication and lack of integration between `.github/`, `utils/`, and `optimizers/` directories. By creating a unified infrastructure for caching, GitHub operations, and CLI tools, we:

1. **Eliminate ~4,000 lines of duplicate code** (62% reduction)
2. **Create single source of truth** for each functionality
3. **Enable P2P cache sharing** throughout the codebase
4. **Improve developer experience** with consistent interfaces
5. **Maintain backward compatibility** with gradual migration

The implementation is structured in phases to minimize risk and allow for iterative improvement. All changes maintain backward compatibility, allowing for gradual adoption.

**Next Steps:**
1. Review and approve this plan
2. Begin Phase 1: Foundation (Week 1)
3. Iterative implementation and testing
4. Gradual rollout and migration
5. Deprecate old implementations (Week 12+)

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-14  
**Authors:** Copilot Agent  
**Status:** Proposed
