#!/usr/bin/env python3
"""
Thin wrapper for GitHub API Counter - imports from optimizers module.

This script provides backward compatibility for existing workflows while
using the unified implementation from ipfs_datasets_py.optimizers.agentic.

All functionality is now consolidated in the optimizers module to maximize
code reuse and maintain a single source of truth.
"""

import sys
from pathlib import Path

# Add repository root to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import from unified optimizers module
from ipfs_datasets_py.optimizers.agentic.github_api_unified import (
    UnifiedGitHubAPICache as GitHubAPICounter,
    CacheBackend,
    CacheEntry,
    APICallRecord,
)

# Re-export for backward compatibility
__all__ = [
    'GitHubAPICounter',
    'CacheBackend',
    'CacheEntry',
    'APICallRecord',
]


def main():
    """Main entry point for CLI usage."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='GitHub API call counter and cache manager'
    )
    parser.add_argument(
        'action',
        choices=['report', 'clear', 'stats'],
        help='Action to perform'
    )
    parser.add_argument(
        '--config',
        help='Path to cache-config.yml'
    )
    
    args = parser.parse_args()
    
    # Create counter with config
    config_file = Path(args.config) if args.config else None
    counter = GitHubAPICounter(config_file=config_file)
    
    if args.action == 'report':
        print(counter.report())
    elif args.action == 'clear':
        counter.clear()
        print("Cache cleared")
    elif args.action == 'stats':
        import json
        stats = counter.get_statistics()
        print(json.dumps(stats, indent=2))
    
    # Save metrics
    counter.save_metrics()


if __name__ == '__main__':
    main()
