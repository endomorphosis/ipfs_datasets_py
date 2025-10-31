#!/usr/bin/env python3
"""
Automated PR Review System with GitHub Copilot Agents

This script automatically examines all open pull requests and intelligently
decides whether to invoke GitHub Copilot coding agents to work on them.

Features:
- Automatic PR scanning and analysis
- Intelligent decision-making for Copilot invocation
- Multiple criteria evaluation (draft status, labels, title keywords, etc.)
- Configurable thresholds and rules
- Dry-run mode for testing
- Integration with existing GitHub CLI and Copilot tools

Based on:
- https://github.blog/news-insights/company-news/welcome-home-agents/
- https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent
- https://docs.github.com/en/copilot/concepts/agents/code-review

Usage:
    # Dry run to see what would be done
    python scripts/automated_pr_review.py --dry-run
    
    # Actually invoke Copilot on qualifying PRs
    python scripts/automated_pr_review.py
    
    # Custom configuration
    python scripts/automated_pr_review.py --min-confidence 70 --limit 50
    
    # Review specific PR
    python scripts/automated_pr_review.py --pr 123
"""

import subprocess
import json
import sys
import argparse
from typing import Dict, List, Any, Optional
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AutomatedPRReviewer:
    """
    Automated PR Review System
    
    Scans open PRs and intelligently decides whether to invoke GitHub Copilot
    coding agents based on multiple criteria.
    """
    
    # Decision criteria weights
    CRITERIA_WEIGHTS = {
        'is_draft': 30,
        'has_auto_fix_label': 40,
        'workflow_failure': 45,
        'permission_issue': 40,
        'has_wip_label': -20,
        'has_do_not_merge_label': -100,
        'recent_activity': 10,
        'has_description': 15,
        'file_count_reasonable': 10,
        'no_conflicts': 15,
        'autohealing_pr': 50,
        'has_linked_issue': 20
    }
    
    # Minimum confidence score to invoke Copilot (0-100)
    DEFAULT_MIN_CONFIDENCE = 60
    
    def __init__(self, dry_run: bool = False, min_confidence: int = None):
        """
        Initialize the automated PR reviewer.
        
        Args:
            dry_run: If True, only show what would be done without invoking Copilot
            min_confidence: Minimum confidence score (0-100) to invoke Copilot
        """
        self.dry_run = dry_run
        self.min_confidence = min_confidence or self.DEFAULT_MIN_CONFIDENCE
        self._verify_tools()
    
    def _verify_tools(self):
        """Verify that required tools are installed."""
        # Check gh CLI
        result = subprocess.run(['gh', '--version'], capture_output=True)
        if result.returncode != 0:
            logger.error("GitHub CLI (gh) not found. Please install it first.")
            sys.exit(1)
        
        logger.info("✅ GitHub CLI verified")
    
    def run_command(self, cmd: List[str], timeout: int = 30) -> Dict[str, Any]:
        """Run a command and return the result."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout
            )
            return {
                'success': True,
                'stdout': result.stdout,
                'stderr': result.stderr
            }
        except subprocess.CalledProcessError as e:
            return {
                'success': False,
                'error': str(e),
                'stdout': e.stdout,
                'stderr': e.stderr
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_pr_details(self, pr_number: int) -> Optional[Dict[str, Any]]:
        """Get detailed information about a PR."""
        result = self.run_command([
            'gh', 'pr', 'view', str(pr_number),
            '--json', 'number,title,body,isDraft,state,author,labels,comments,files,mergeable,updatedAt,headRefName'
        ])
        
        if not result['success']:
            logger.error(f"Failed to get PR #{pr_number}: {result.get('error')}")
            return None
        
        try:
            return json.loads(result['stdout'])
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse PR data: {e}")
            return None
    
    def get_all_open_prs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all open PRs."""
        result = self.run_command([
            'gh', 'pr', 'list',
            '--state', 'open',
            '--limit', str(limit),
            '--json', 'number,title,isDraft,author,labels,updatedAt'
        ])
        
        if not result['success']:
            logger.error(f"Failed to get PRs: {result.get('error')}")
            return []
        
        try:
            return json.loads(result['stdout'])
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse PR list: {e}")
            return []
    
    def check_copilot_already_invoked(self, pr_details: Dict[str, Any]) -> bool:
        """
        Check if Copilot agent has already been invoked on this PR.
        
        Checks for existing agent tasks associated with the PR.
        """
        pr_number = pr_details['number']
        
        # Check for agent tasks associated with this PR
        result = self.run_command([
            'gh', 'agent-task', 'list', '--limit', '50'
        ])
        
        if not result['success']:
            # Fallback: check for @copilot mentions in comments
            logger.debug("Could not check agent tasks, falling back to comment check")
            comments = pr_details.get('comments', [])
            for comment in comments:
                body = comment.get('body', '').lower()
                if '@copilot' in body or '@github-copilot' in body or 'agent task' in body:
                    return True
            return False
        
        # Parse agent task list output to see if any are for this PR
        output = result['stdout']
        if output and str(pr_number) in output:
            logger.debug(f"Found existing agent task for PR #{pr_number}")
            return True
        
        return False
    
    def analyze_pr(self, pr_details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a PR to determine if Copilot should be invoked.
        
        Returns a dictionary with:
            - should_invoke: bool
            - confidence: int (0-100)
            - task_type: str
            - reasons: List[str]
            - criteria_scores: Dict[str, int]
        """
        pr_number = pr_details['number']
        title = pr_details['title'].lower()
        body = (pr_details.get('body') or '').lower()
        is_draft = pr_details['isDraft']
        labels = [label['name'].lower() for label in pr_details.get('labels', [])]
        files = pr_details.get('files', [])
        mergeable = pr_details.get('mergeable', 'UNKNOWN')
        branch_name = pr_details.get('headRefName', '').lower()
        
        criteria_scores = {}
        reasons = []
        task_type = 'review'
        
        # Criterion 1: Is it a draft PR?
        if is_draft:
            criteria_scores['is_draft'] = self.CRITERIA_WEIGHTS['is_draft']
            reasons.append("Draft PR needing implementation")
            task_type = 'implement_draft'
        
        # Criterion 2: Has auto-fix or autohealing labels?
        auto_fix_labels = ['auto-fix', 'autofix', 'automated-fix', 'autohealing']
        if any(label in labels for label in auto_fix_labels):
            criteria_scores['has_auto_fix_label'] = self.CRITERIA_WEIGHTS['has_auto_fix_label']
            reasons.append("Auto-fix label detected")
            task_type = 'implement_fix'
        
        # Criterion 3: Is it from autohealing branch?
        if 'autohealing' in branch_name or 'auto-fix' in branch_name:
            criteria_scores['autohealing_pr'] = self.CRITERIA_WEIGHTS['autohealing_pr']
            reasons.append("Autohealing branch")
            task_type = 'implement_fix'
        
        # Criterion 4: Workflow-related PR?
        workflow_keywords = ['workflow', 'ci', 'github actions', 'pipeline']
        workflow_files = any('.github/workflows/' in f.get('path', '') for f in files)
        if any(keyword in title for keyword in workflow_keywords) or workflow_files:
            criteria_scores['workflow_failure'] = self.CRITERIA_WEIGHTS['workflow_failure']
            reasons.append("Workflow fix needed")
            task_type = 'fix_workflow'
        
        # Criterion 5: Permission-related issues?
        permission_keywords = ['permission', 'permissions', 'denied', 'forbidden', 'unauthorized']
        if any(keyword in title or keyword in body for keyword in permission_keywords):
            criteria_scores['permission_issue'] = self.CRITERIA_WEIGHTS['permission_issue']
            reasons.append("Permission issue")
            task_type = 'fix_permissions'
        
        # Criterion 6: Has WIP label? (negative)
        wip_labels = ['wip', 'work in progress', 'do-not-review']
        if any(label in labels for label in wip_labels):
            criteria_scores['has_wip_label'] = self.CRITERIA_WEIGHTS['has_wip_label']
            reasons.append("WIP label (caution)")
        
        # Criterion 7: Has do-not-merge label? (strongly negative)
        dnm_labels = ['do-not-merge', 'dnm', 'hold']
        if any(label in labels for label in dnm_labels):
            criteria_scores['has_do_not_merge_label'] = self.CRITERIA_WEIGHTS['has_do_not_merge_label']
            reasons.append("Do-not-merge label (blocking)")
        
        # Criterion 8: Recent activity?
        try:
            from datetime import datetime, timedelta
            updated = datetime.fromisoformat(pr_details['updatedAt'].replace('Z', '+00:00'))
            if (datetime.now(updated.tzinfo) - updated).days < 2:
                criteria_scores['recent_activity'] = self.CRITERIA_WEIGHTS['recent_activity']
                reasons.append("Recent activity")
        except:
            pass
        
        # Criterion 9: Has meaningful description?
        if body and len(body) > 100:
            criteria_scores['has_description'] = self.CRITERIA_WEIGHTS['has_description']
            reasons.append("Has description")
        
        # Criterion 10: Reasonable file count (not too large)?
        file_count = len(files)
        if 1 <= file_count <= 50:
            criteria_scores['file_count_reasonable'] = self.CRITERIA_WEIGHTS['file_count_reasonable']
            reasons.append("Reasonable scope")
        elif file_count > 50:
            reasons.append(f"Large PR ({file_count} files)")
        
        # Criterion 11: No merge conflicts?
        if mergeable == 'MERGEABLE':
            criteria_scores['no_conflicts'] = self.CRITERIA_WEIGHTS['no_conflicts']
            reasons.append("No conflicts")
        elif mergeable == 'CONFLICTING':
            reasons.append("Has merge conflicts")
        
        # Criterion 12: Has linked issue?
        issue_references = ['#', 'fixes', 'closes', 'resolves']
        if any(ref in body for ref in issue_references):
            criteria_scores['has_linked_issue'] = self.CRITERIA_WEIGHTS['has_linked_issue']
            reasons.append("Has linked issue")
        
        # Calculate total confidence score
        total_score = sum(criteria_scores.values())
        # Normalize to 0-100 range (max possible score is ~270)
        confidence = min(100, max(0, int((total_score / 270) * 100)))
        
        # Adjust confidence based on negative indicators
        if criteria_scores.get('has_do_not_merge_label', 0) < 0:
            confidence = 0  # Block completely
        
        should_invoke = confidence >= self.min_confidence
        
        return {
            'should_invoke': should_invoke,
            'confidence': confidence,
            'task_type': task_type,
            'reasons': reasons,
            'criteria_scores': criteria_scores
        }
    
    def create_agent_task_description(self, pr_details: Dict[str, Any], analysis: Dict[str, Any]) -> str:
        """Create an appropriate task description for GitHub Copilot agent."""
        task_type = analysis['task_type']
        confidence = analysis['confidence']
        reasons = ', '.join(analysis['reasons'])
        pr_number = pr_details['number']
        pr_title = pr_details['title']
        
        # Task-specific templates for agent-task create
        if task_type == 'implement_fix':
            return f"""Implement the auto-fix described in PR #{pr_number}: {pr_title}

**Context**: This PR was automatically flagged for Copilot agent assistance (Confidence: {confidence}%).

**Analysis**: {reasons}

**Task**:
1. Review the PR description and understand the failure or issue
2. Examine the proposed fix or solution
3. Implement the fix with minimal, surgical changes
4. Ensure the fix follows repository patterns and best practices
5. Run relevant tests to validate the fix

**Instructions**:
- Make minimal changes to address the specific issue
- Follow existing code patterns in the repository
- Ensure all tests pass after your changes
- Update documentation if directly related to the fix

Please proceed with implementing this fix on PR #{pr_number}."""

        elif task_type == 'fix_workflow':
            return f"""Fix the workflow issue in PR #{pr_number}: {pr_title}

**Context**: This PR addresses a GitHub Actions workflow failure (Confidence: {confidence}%).

**Analysis**: {reasons}

**Task**:
1. Review the workflow file and any error logs in the PR
2. Identify the root cause of the failure
3. Implement the fix following GitHub Actions best practices
4. Ensure the fix doesn't break existing functionality
5. Test the workflow configuration if possible

**Instructions**:
- Focus on workflow files in .github/workflows/
- Check for permission issues, missing dependencies, or syntax errors
- Validate YAML syntax
- Ensure backwards compatibility

Please implement the necessary workflow fixes on PR #{pr_number}."""

        elif task_type == 'fix_permissions':
            return f"""Resolve permission issues in PR #{pr_number}: {pr_title}

**Context**: This PR addresses permission-related errors (Confidence: {confidence}%).

**Analysis**: {reasons}

**Task**:
1. Identify the specific permission errors from the PR description
2. Review required permissions for the failing operations
3. Update permissions configuration appropriately
4. Ensure security best practices are maintained
5. Document any permission changes made

**Instructions**:
- Check workflow permissions in .github/workflows/
- Review GITHUB_TOKEN permissions
- Ensure principle of least privilege
- Add comments explaining permission requirements

Please fix the permission issues on PR #{pr_number}."""

        elif task_type == 'implement_draft':
            return f"""Implement the changes described in draft PR #{pr_number}: {pr_title}

**Context**: This draft PR has been flagged for implementation assistance (Confidence: {confidence}%).

**Analysis**: {reasons}

**Task**:
1. Review the PR description and understand requirements
2. Examine any linked issues or documentation
3. Implement the solution following repository patterns
4. Add or update tests as appropriate
5. Update documentation if directly related

**Instructions**:
- Follow existing code patterns and conventions
- Write tests for new functionality
- Update relevant documentation
- Ensure code quality and maintainability

Please implement the proposed changes on PR #{pr_number}."""

        else:  # review
            return f"""Review pull request #{pr_number}: {pr_title}

**Context**: This PR has been automatically flagged for Copilot agent review (Confidence: {confidence}%).

**Analysis**: {reasons}

**Review Focus**:
- Code quality and best practices
- Test coverage and correctness
- Documentation completeness
- Potential issues or improvements
- Security considerations

**Instructions**:
- Provide constructive feedback
- Identify any bugs or issues
- Suggest improvements where appropriate
- Check for proper error handling
- Verify test coverage

Please provide a comprehensive review of PR #{pr_number}."""
    
    def invoke_copilot_on_pr(self, pr_number: int) -> Dict[str, Any]:
        """
        Invoke Copilot on a specific PR.
        
        Returns a dictionary with results.
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"📋 Analyzing PR #{pr_number}")
        logger.info(f"{'='*80}")
        
        # Get PR details
        pr_details = self.get_pr_details(pr_number)
        if not pr_details:
            return {
                'success': False,
                'pr_number': pr_number,
                'error': 'Failed to get PR details'
            }
        
        logger.info(f"📄 Title: {pr_details['title']}")
        logger.info(f"📊 Draft: {pr_details['isDraft']}")
        logger.info(f"👤 Author: {pr_details['author']['login']}")
        
        # Check if Copilot already invoked
        if self.check_copilot_already_invoked(pr_details):
            logger.info(f"✅ Copilot already invoked on PR #{pr_number}")
            return {
                'success': True,
                'pr_number': pr_number,
                'action': 'skipped',
                'reason': 'already_invoked'
            }
        
        # Analyze the PR
        analysis = self.analyze_pr(pr_details)
        
        logger.info(f"🎯 Task Type: {analysis['task_type']}")
        logger.info(f"📊 Confidence: {analysis['confidence']}%")
        logger.info(f"📝 Reasons: {', '.join(analysis['reasons'])}")
        logger.info(f"📈 Criteria Scores: {analysis['criteria_scores']}")
        
        if not analysis['should_invoke']:
            logger.info(f"⏭️  Confidence too low ({analysis['confidence']}% < {self.min_confidence}%) - skipping")
            return {
                'success': True,
                'pr_number': pr_number,
                'action': 'skipped',
                'reason': 'low_confidence',
                'confidence': analysis['confidence']
            }
        
        # Create agent task description
        task_description = self.create_agent_task_description(pr_details, analysis)
        
        if self.dry_run:
            logger.info(f"\n{'─'*80}")
            logger.info("🔍 DRY RUN - Would create agent task with description:")
            logger.info(f"{'─'*80}")
            logger.info(task_description)
            logger.info(f"{'─'*80}\n")
            return {
                'success': True,
                'pr_number': pr_number,
                'action': 'dry_run',
                'confidence': analysis['confidence'],
                'task_type': analysis['task_type']
            }
        
        # Create GitHub Copilot agent task using gh agent-task create
        # First, checkout the PR branch to work on it
        logger.info(f"🔄 Checking out PR #{pr_number}...")
        checkout_result = self.run_command([
            'gh', 'pr', 'checkout', str(pr_number)
        ])
        
        if not checkout_result['success']:
            logger.warning(f"⚠️  Could not checkout PR #{pr_number}, will create task anyway")
        
        # Create the agent task
        logger.info(f"🤖 Creating GitHub Copilot agent task for PR #{pr_number}...")
        result = self.run_command([
            'gh', 'agent-task', 'create', task_description
        ], timeout=60)
        
        if result['success']:
            logger.info(f"✅ Successfully created Copilot agent task for PR #{pr_number}")
            # Extract session ID from output if available
            session_id = None
            if result['stdout']:
                # Look for session ID in output
                for line in result['stdout'].split('\n'):
                    if 'session' in line.lower() or 'task' in line.lower():
                        logger.info(f"   {line.strip()}")
                        # Try to extract session ID
                        import re
                        match = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', line)
                        if match:
                            session_id = match.group(1)
            
            return {
                'success': True,
                'pr_number': pr_number,
                'action': 'invoked',
                'confidence': analysis['confidence'],
                'task_type': analysis['task_type'],
                'session_id': session_id,
                'output': result['stdout']
            }
        else:
            logger.error(f"❌ Failed to create Copilot agent task: {result.get('error')}")
            logger.error(f"   stderr: {result.get('stderr', 'N/A')}")
            return {
                'success': False,
                'pr_number': pr_number,
                'action': 'failed',
                'error': result.get('error'),
                'stderr': result.get('stderr')
            }
    
    def review_all_prs(self, limit: int = 100) -> Dict[str, Any]:
        """
        Review all open PRs and invoke Copilot where appropriate.
        
        Returns statistics dictionary.
        """
        logger.info("🔍 Fetching open pull requests...")
        
        prs = self.get_all_open_prs(limit=limit)
        
        if not prs:
            logger.info("No open PRs found.")
            return {
                'total': 0,
                'analyzed': 0,
                'invoked': 0,
                'skipped': 0,
                'failed': 0
            }
        
        logger.info(f"📊 Found {len(prs)} open PRs\n")
        
        stats = {
            'total': len(prs),
            'analyzed': 0,
            'invoked': 0,
            'skipped': 0,
            'failed': 0,
            'results': []
        }
        
        for pr in prs:
            pr_number = pr['number']
            stats['analyzed'] += 1
            
            result = self.invoke_copilot_on_pr(pr_number)
            stats['results'].append(result)
            
            if result['success']:
                if result['action'] == 'invoked':
                    stats['invoked'] += 1
                elif result['action'] in ['skipped', 'dry_run']:
                    stats['skipped'] += 1
            else:
                stats['failed'] += 1
        
        return stats
    
    def print_summary(self, stats: Dict[str, Any]):
        """Print summary statistics."""
        logger.info(f"\n{'='*80}")
        logger.info("📊 SUMMARY")
        logger.info(f"{'='*80}")
        logger.info(f"Total PRs:              {stats['total']}")
        logger.info(f"Analyzed:               {stats['analyzed']}")
        logger.info(f"Copilot Invoked:        {stats['invoked']}")
        logger.info(f"Skipped:                {stats['skipped']}")
        logger.info(f"Failed:                 {stats['failed']}")
        logger.info(f"{'='*80}\n")
        
        if stats['invoked'] > 0:
            logger.info(f"✨ Successfully invoked Copilot on {stats['invoked']} PR(s)!")
        else:
            logger.info("ℹ️  No new Copilot invocations made.")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Automated PR Review System with GitHub Copilot Agents',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Dry run to see what would be done
    python scripts/automated_pr_review.py --dry-run
    
    # Actually invoke Copilot on qualifying PRs
    python scripts/automated_pr_review.py
    
    # Custom minimum confidence threshold
    python scripts/automated_pr_review.py --min-confidence 70
    
    # Review specific PR
    python scripts/automated_pr_review.py --pr 123 --dry-run
        """
    )
    parser.add_argument(
        '--pr',
        type=int,
        help='Specific PR number to analyze'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without actually invoking Copilot'
    )
    parser.add_argument(
        '--min-confidence',
        type=int,
        default=60,
        help='Minimum confidence score (0-100) to invoke Copilot (default: 60)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=100,
        help='Maximum number of PRs to process (default: 100)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.dry_run:
        logger.info("🔍 DRY RUN MODE - No actual changes will be made\n")
    
    reviewer = AutomatedPRReviewer(
        dry_run=args.dry_run,
        min_confidence=args.min_confidence
    )
    
    if args.pr:
        # Analyze specific PR
        result = reviewer.invoke_copilot_on_pr(args.pr)
        sys.exit(0 if result['success'] else 1)
    else:
        # Analyze all open PRs
        stats = reviewer.review_all_prs(limit=args.limit)
        reviewer.print_summary(stats)
        sys.exit(0 if stats['failed'] == 0 else 1)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
