#!/usr/bin/env python3
"""
Invoke GitHub Copilot on Pull Requests using Copilot CLI with Queue Management

This script properly invokes GitHub Copilot using the Copilot CLI tool instead of
GitHub CLI comments. It integrates with the queue management system to prevent
overloading Copilot with too many concurrent tasks, and uses caching to avoid
duplicate requests.

Key features:
1. Uses GitHub Copilot CLI (gh copilot) for AI-powered assistance
2. Integrates with queue manager to respect agent capacity limits
3. Caches requests to avoid duplicate Copilot invocations
4. Generates structured instructions from failure analysis or issue details

Usage:
    # Invoke Copilot with queue management and caching
    python scripts/invoke_copilot_with_queue.py --pr 123 --context-file /tmp/analysis.json
    
    # Check queue status first
    python scripts/invoke_copilot_with_queue.py --status
    
    # Force invocation bypassing queue
    python scripts/invoke_copilot_with_queue.py --pr 123 --force

Requirements:
    - GitHub Copilot CLI installed (gh copilot extension)
    - Queue manager for capacity planning
    - Cache tools for request deduplication
"""

import argparse
import json
import logging
import os
import sys
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
from scripts.queue_manager import QueueManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CopilotInvokerWithQueue:
    """Invoke GitHub Copilot with queue management and caching."""
    
    def __init__(self, max_agents: int = 3, enable_cache: bool = True, dry_run: bool = False):
        """
        Initialize the invoker.
        
        Args:
            max_agents: Maximum concurrent Copilot agents (default: 3)
            enable_cache: Enable request caching (default: True)
            dry_run: If True, show what would be done without making changes
        """
        self.dry_run = dry_run
        self.max_agents = max_agents
        self.enable_cache = enable_cache
        
        # Initialize Copilot CLI with caching
        try:
            self.copilot = CopilotCLI(enable_cache=enable_cache)
            if not self.copilot.installed:
                logger.warning("GitHub Copilot CLI not installed, attempting installation...")
                install_result = self.copilot.install()
                if not install_result['success']:
                    raise RuntimeError(f"Failed to install Copilot CLI: {install_result.get('error')}")
            logger.info("✅ GitHub Copilot CLI ready")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Copilot CLI: {e}")
            raise
        
        # Initialize queue manager
        try:
            self.queue_manager = QueueManager(max_agents=max_agents)
            logger.info(f"✅ Queue manager initialized (max_agents={max_agents})")
        except Exception as e:
            logger.error(f"❌ Failed to initialize queue manager: {e}")
            raise
        
        # Simple file-based cache for requests
        self.cache_dir = Path('/tmp/copilot_cache')
        if enable_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"✅ Cache enabled at {self.cache_dir}")
    
    def _get_cache_key(self, pr_number: int, instruction_hash: str) -> str:
        """Generate cache key for a request."""
        return f"pr_{pr_number}_{instruction_hash}"
    
    def _check_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Check if request is already cached."""
        if not self.enable_cache:
            return None
        
        cache_file = self.cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    cached = json.load(f)
                # Check if cache is recent (within 1 hour)
                cached_time = datetime.fromisoformat(cached['timestamp'])
                age_seconds = (datetime.now() - cached_time).total_seconds()
                if age_seconds < 3600:  # 1 hour
                    logger.info(f"✅ Cache hit for {cache_key} (age: {age_seconds:.0f}s)")
                    return cached
                else:
                    logger.debug(f"Cache entry expired for {cache_key}")
            except Exception as e:
                logger.warning(f"Failed to read cache: {e}")
        return None
    
    def _save_cache(self, cache_key: str, data: Dict[str, Any]):
        """Save request to cache."""
        if not self.enable_cache:
            return
        
        cache_file = self.cache_dir / f"{cache_key}.json"
        try:
            data['timestamp'] = datetime.now().isoformat()
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Cached result for {cache_key}")
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")
    
    def check_queue_capacity(self) -> Dict[str, Any]:
        """Check if queue has capacity for new tasks."""
        try:
            agent_status = self.queue_manager.get_active_agents()
            logger.info(f"Queue capacity: {agent_status['available_slots']}/{self.max_agents} slots available")
            return agent_status
        except Exception as e:
            logger.error(f"Failed to check queue capacity: {e}")
            return {'available_slots': 0, 'error': str(e)}
    
    def generate_instruction_from_context(self, context_data: Dict[str, Any], context_type: str) -> str:
        """
        Generate comprehensive Copilot instruction from context.
        
        Args:
            context_data: Context information (failure analysis, validation report, issue details)
            context_type: Type of context ('failure', 'validation', 'issue')
        
        Returns:
            Formatted instruction string for Copilot
        """
        if context_type == 'failure':
            return self._generate_failure_instruction(context_data)
        elif context_type == 'validation':
            return self._generate_validation_instruction(context_data)
        elif context_type == 'issue':
            return self._generate_issue_instruction(context_data)
        else:
            return "Please implement the necessary fixes for this PR."
    
    def _generate_failure_instruction(self, analysis: Dict[str, Any]) -> str:
        """Generate instruction from workflow failure analysis."""
        error_type = analysis.get('error_type', 'Unknown')
        root_cause = analysis.get('root_cause', 'Not identified')
        fix_confidence = analysis.get('fix_confidence', 0)
        captured_values = analysis.get('captured_values', [])
        recommendations = analysis.get('recommendations', [])
        affected_files = analysis.get('affected_files', [])
        
        # Format recommendations
        rec_text = '\n'.join([f'  {i+1}. {rec}' for i, rec in enumerate(recommendations)])
        
        # Format affected files
        files_text = '\n'.join([f'  - {file}' for file in affected_files])
        
        instruction = f"""Please analyze and fix the workflow failure detected.

**Error Analysis:**
- Error Type: {error_type}
- Root Cause: {root_cause}
- Fix Confidence: {fix_confidence}%
- Captured Values: {', '.join(str(v) for v in captured_values) if captured_values else 'None'}

**Recommended Actions:**
{rec_text if rec_text else '  No specific recommendations'}

**Affected Files:**
{files_text if files_text else '  None identified'}

**Instructions:**
1. Review the error analysis and recommendations above
2. Implement minimal, surgical fixes to address the root cause
3. Focus on the affected files listed
4. Ensure all tests pass after your changes
5. Follow existing code patterns and conventions
6. Document any significant changes

Use the Copilot CLI to analyze the code and suggest fixes."""

        return instruction
    
    def _generate_validation_instruction(self, report: Dict[str, Any]) -> str:
        """Generate instruction from scraper validation report."""
        total_scrapers = report.get('total_scrapers', 0)
        passed = report.get('passed', 0)
        failed = report.get('failed', 0)
        results = report.get('results', [])
        
        # Summarize failures
        failures_summary = []
        for result in results:
            if not (result.get('execution_success') and result.get('schema_valid') and result.get('hf_compatible')):
                scraper = result.get('scraper_name', 'Unknown')
                issues = []
                if not result.get('execution_success'):
                    issues.append('execution failed')
                if not result.get('schema_valid'):
                    issues.append(f"schema: {', '.join(result.get('schema_issues', []))}")
                if not result.get('hf_compatible'):
                    issues.append(f"HF: {', '.join(result.get('hf_issues', []))}")
                failures_summary.append(f"  - {scraper}: {'; '.join(issues)}")
        
        failures_text = '\n'.join(failures_summary)
        
        instruction = f"""Please fix the scraper validation failures.

**Validation Summary:**
- Total Scrapers: {total_scrapers}
- Passed: {passed}
- Failed: {failed}

**Failed Scrapers:**
{failures_text if failures_text else '  None'}

**Instructions:**
1. Review each failed scraper and its specific issues
2. Ensure all scrapers produce data with required fields: 'title' and 'text'
3. Fix schema validation issues
4. Ensure HuggingFace dataset compatibility
5. Improve data quality scores where needed
6. Test each fix before committing

Focus on making the scrapers compliant with the validation requirements."""

        return instruction
    
    def _generate_issue_instruction(self, issue_data: Dict[str, Any]) -> str:
        """Generate instruction from issue details."""
        issue_number = issue_data.get('issue_number', 'Unknown')
        issue_title = issue_data.get('issue_title', 'Unknown')
        categories = issue_data.get('categories', [])
        keywords = issue_data.get('keywords', [])
        
        categories_text = ', '.join(categories) if categories else 'general'
        keywords_text = ', '.join(keywords[:5]) if keywords else 'none'
        
        instruction = f"""Please implement a solution for this issue.

**Issue Details:**
- Issue Number: #{issue_number}
- Title: {issue_title}
- Categories: {categories_text}
- Keywords: {keywords_text}

**Instructions:**
1. Review the full issue description in the PR
2. Understand the requirements and desired outcome
3. Implement minimal, surgical changes to address the issue
4. Follow existing code patterns and style in the repository
5. Add or update tests as appropriate
6. Update documentation if directly related to your changes
7. Verify the fix works as expected

Focus on making clean, maintainable changes that directly address the issue."""

        return instruction
    
    def invoke_copilot(
        self,
        pr_number: int,
        instruction: str,
        context_data: Optional[Dict[str, Any]] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Invoke GitHub Copilot with queue management and caching.
        
        Args:
            pr_number: Pull request number
            instruction: Instruction for Copilot
            context_data: Optional context data for logging
            force: Force invocation bypassing queue and cache
        
        Returns:
            Dictionary with invocation result
        """
        logger.info(f"{'[DRY RUN] ' if self.dry_run else ''}Invoking Copilot for PR #{pr_number}...")
        
        # Generate cache key
        instruction_hash = hashlib.md5(instruction.encode()).hexdigest()[:12]
        cache_key = self._get_cache_key(pr_number, instruction_hash)
        
        # Check cache first (unless forced)
        if not force:
            cached_result = self._check_cache(cache_key)
            if cached_result:
                logger.info("✅ Returning cached result (use --force to bypass)")
                return cached_result
        
        # Check queue capacity (unless forced)
        if not force:
            agent_status = self.check_queue_capacity()
            if agent_status.get('available_slots', 0) <= 0:
                logger.warning("⚠️  No queue capacity available")
                return {
                    'success': False,
                    'error': 'Queue at capacity',
                    'queue_status': agent_status,
                    'recommendation': 'Wait for active agents to complete or use --force'
                }
        
        if self.dry_run:
            logger.info(f"\n[DRY RUN] Would invoke Copilot with:")
            logger.info(f"PR: #{pr_number}")
            logger.info(f"Instruction length: {len(instruction)} chars")
            logger.info(f"Cache key: {cache_key}")
            logger.info(f"\nInstruction preview:\n{'-'*80}\n{instruction[:500]}...\n{'-'*80}\n")
            return {
                'success': True,
                'dry_run': True,
                'pr_number': pr_number,
                'cache_key': cache_key
            }
        
        # Use Copilot CLI to generate suggestions
        try:
            # For now, we use suggest_command to get Copilot's help
            # In a real implementation, this would interact with the PR
            result = self.copilot.suggest_command(
                description=f"Fix issues in PR #{pr_number}: {instruction}",
                use_cache=self.enable_cache
            )
            
            if result['success']:
                response = {
                    'success': True,
                    'pr_number': pr_number,
                    'instruction': instruction,
                    'copilot_response': result.get('suggestions'),
                    'cache_key': cache_key,
                    'timestamp': datetime.now().isoformat()
                }
                
                # Cache the result
                self._save_cache(cache_key, response)
                
                logger.info(f"✅ Successfully invoked Copilot for PR #{pr_number}")
                return response
            else:
                logger.error(f"❌ Copilot invocation failed: {result.get('error')}")
                return {
                    'success': False,
                    'error': result.get('error'),
                    'pr_number': pr_number
                }
        
        except Exception as e:
            logger.error(f"❌ Exception during Copilot invocation: {e}")
            return {
                'success': False,
                'error': str(e),
                'pr_number': pr_number
            }
    
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive status including Copilot, queue, and cache."""
        copilot_status = self.copilot.get_status()
        queue_report = self.queue_manager.generate_summary_report()
        cache_stats = self.copilot.get_cache_stats() if self.enable_cache else None
        
        # Count cached files
        cached_items = 0
        if self.enable_cache and self.cache_dir.exists():
            cached_items = len(list(self.cache_dir.glob('*.json')))
        
        return {
            'copilot_cli': copilot_status,
            'queue': queue_report,
            'cache': {
                'enabled': self.enable_cache,
                'directory': str(self.cache_dir),
                'cached_items': cached_items,
                'copilot_cache_stats': cache_stats
            },
            'max_agents': self.max_agents,
            'timestamp': datetime.now().isoformat()
        }
    
    def print_status(self):
        """Print formatted status report."""
        status = self.get_status()
        
        print(f"\n{'='*80}")
        print(f"🤖 Copilot Invoker Status")
        print(f"{'='*80}")
        
        print(f"\n📊 Copilot CLI:")
        copilot = status['copilot_cli']
        print(f"  Installed: {'✅' if copilot['installed'] else '❌'}")
        print(f"  GitHub CLI: {'✅' if copilot['github_cli_available'] else '❌'}")
        if copilot.get('version_info'):
            print(f"  Version: {copilot['version_info']}")
        
        print(f"\n📋 Queue Status:")
        queue = status['queue']
        agent_status = queue['agent_status']
        print(f"  Active agents: {agent_status['total_active']}/{self.max_agents}")
        print(f"  Available slots: {agent_status['available_slots']}")
        print(f"  Utilization: {agent_status['utilization_pct']:.1f}%")
        print(f"  Queue size: {queue['queue_status']['queue_size']}")
        
        print(f"\n💾 Cache Status:")
        cache = status['cache']
        print(f"  Enabled: {'✅' if cache['enabled'] else '❌'}")
        if cache['enabled']:
            print(f"  Cached items: {cache['cached_items']}")
            print(f"  Location: {cache['directory']}")
            if cache['copilot_cache_stats']:
                stats = cache['copilot_cache_stats']
                print(f"  Copilot cache hits: {stats.get('hits', 0)}")
                print(f"  Copilot cache misses: {stats.get('misses', 0)}")
        
        print(f"\n💡 Recommendations:")
        for rec in queue['recommendations']:
            print(f"  {rec}")
        
        print(f"{'='*80}\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Invoke GitHub Copilot with queue management and caching'
    )
    parser.add_argument(
        '--pr',
        type=int,
        help='Pull request number to invoke Copilot on'
    )
    parser.add_argument(
        '--instruction',
        type=str,
        help='Custom instruction for Copilot (optional)'
    )
    parser.add_argument(
        '--context-file',
        type=str,
        help='Path to JSON file with context (failure analysis, validation report, issue data)'
    )
    parser.add_argument(
        '--context-type',
        type=str,
        choices=['failure', 'validation', 'issue'],
        default='failure',
        help='Type of context data (default: failure)'
    )
    parser.add_argument(
        '--max-agents',
        type=int,
        default=3,
        help='Maximum concurrent Copilot agents (default: 3)'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force invocation bypassing queue and cache'
    )
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Disable caching'
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='Show status of Copilot, queue, and cache'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    
    args = parser.parse_args()
    
    try:
        invoker = CopilotInvokerWithQueue(
            max_agents=args.max_agents,
            enable_cache=not args.no_cache,
            dry_run=args.dry_run
        )
        
        if args.status:
            invoker.print_status()
            return
        
        if not args.pr:
            parser.print_help()
            print("\n💡 Tip: Use --status to check Copilot and queue status")
            sys.exit(1)
        
        # Load context if provided
        context_data = None
        instruction = args.instruction
        
        if args.context_file:
            try:
                with open(args.context_file, 'r') as f:
                    context_data = json.load(f)
                logger.info(f"✅ Loaded context from {args.context_file}")
                
                # Generate instruction from context if not provided
                if not instruction:
                    instruction = invoker.generate_instruction_from_context(
                        context_data,
                        args.context_type
                    )
                    logger.info(f"✅ Generated {args.context_type} instruction")
            except Exception as e:
                logger.error(f"❌ Failed to load context file: {e}")
                sys.exit(1)
        
        if not instruction:
            instruction = "Please implement the necessary fixes for this PR based on the description and linked issues."
        
        # Invoke Copilot
        result = invoker.invoke_copilot(
            pr_number=args.pr,
            instruction=instruction,
            context_data=context_data,
            force=args.force
        )
        
        # Print result
        if result['success']:
            print(f"\n✅ Successfully invoked Copilot for PR #{args.pr}")
            if result.get('copilot_response'):
                print(f"\n📝 Copilot Response:\n{'-'*80}\n{result['copilot_response']}\n{'-'*80}")
            sys.exit(0)
        else:
            print(f"\n❌ Failed to invoke Copilot: {result.get('error')}")
            if result.get('queue_status'):
                print(f"\n📊 Queue Status: {result['queue_status']}")
            sys.exit(1)
    
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
