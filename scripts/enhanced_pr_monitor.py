#!/usr/bin/env python3
"""
Enhanced PR Monitoring and Copilot Assignment System

This script provides comprehensive PR monitoring with intelligent Copilot assignment
and progressive escalation to ensure PRs are completed properly.

Features:
- Comprehensive PR completion detection
- Progressive Copilot assignment strategy
- State management to avoid duplicate work
- Human notification for stale PRs
- Integration with auto-healing system
"""

import subprocess
import json
import sys
import argparse
import time
import os
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from pathlib import Path
import logging


class EnhancedPRMonitor:
    """Enhanced PR monitoring with intelligent Copilot assignment."""
    
    def __init__(self, notification_user: str, dry_run: bool = False):
        self.notification_user = notification_user
        self.dry_run = dry_run
        self.state_file = Path('.github/pr_monitor_state.json')
        self.setup_logging()
        
    def setup_logging(self):
        """Setup logging configuration."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def run_command(self, cmd: List[str]) -> Dict[str, Any]:
        """Run a shell command and return the result."""
        try:
            self.logger.debug(f"Running command: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            return {
                'success': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            }
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': 'Command timed out',
                'timeout': True
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def load_state(self) -> Dict[str, Any]:
        """Load monitoring state from file."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.warning(f"Failed to load state: {e}")
        
        return {
            'processed_prs': {},
            'assignments': {},
            'last_run': None
        }
    
    def save_state(self, state: Dict[str, Any]):
        """Save monitoring state to file."""
        if self.dry_run:
            self.logger.info("DRY RUN: Would save state")
            return
        
        try:
            self.state_file.parent.mkdir(exist_ok=True)
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")
    
    def get_open_prs(self, pr_number: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all open PRs or a specific PR."""
        if pr_number:
            cmd = [
                'gh', 'pr', 'view', pr_number,
                '--json', 'number,title,body,isDraft,state,author,labels,comments,files,reviews,statusCheckRollup,updatedAt,createdAt,headRefName'
            ]
        else:
            cmd = [
                'gh', 'pr', 'list',
                '--state', 'open',
                '--limit', '100',
                '--json', 'number,title,body,isDraft,state,author,labels,comments,files,reviews,statusCheckRollup,updatedAt,createdAt,headRefName'
            ]
        
        result = self.run_command(cmd)
        
        if not result['success']:
            self.logger.error(f"Failed to get PRs: {result.get('error', result.get('stderr'))}")
            return []
        
        try:
            if pr_number:
                return [json.loads(result['stdout'])]
            else:
                return json.loads(result['stdout'])
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse PR data: {e}")
            return []
    
    def analyze_pr_completion(self, pr: Dict[str, Any]) -> Dict[str, Any]:
        """
        Comprehensive analysis of PR completion status.
        
        Returns analysis with completion status, reasons, and recommendations.
        """
        pr_number = pr['number']
        title = pr['title'].lower()
        body = pr.get('body', '').lower()
        is_draft = pr['isDraft']
        comments = pr.get('comments', [])
        files = pr.get('files', [])
        reviews = pr.get('reviews', [])
        status_checks = pr.get('statusCheckRollup', [])
        updated_at = pr['updatedAt']
        created_at = pr['createdAt']
        
        analysis = {
            'is_complete': True,
            'completion_score': 100,
            'incomplete_reasons': [],
            'priority': 'normal',
            'recommended_action': 'none',
            'task_type': 'review'
        }
        
        # Check 1: Draft status
        if is_draft:
            analysis['is_complete'] = False
            analysis['completion_score'] -= 30
            analysis['incomplete_reasons'].append("PR is marked as draft")
            analysis['task_type'] = 'implement'
        
        # Check 2: TODO items in description or comments
        todo_patterns = ['todo', 'fixme', '- [ ]', 'wip', 'work in progress']
        if any(pattern in body for pattern in todo_patterns):
            analysis['is_complete'] = False
            analysis['completion_score'] -= 25
            analysis['incomplete_reasons'].append("Contains TODO items or incomplete tasks")
        
        # Check 3: Failed status checks
        if status_checks:
            failed_checks = [check for check in status_checks if check.get('state') == 'FAILURE']
            if failed_checks:
                analysis['is_complete'] = False
                analysis['completion_score'] -= 20
                analysis['incomplete_reasons'].append(f"{len(failed_checks)} status checks failing")
                analysis['task_type'] = 'fix'
                analysis['priority'] = 'high'
        
        # Check 4: No commits or minimal commits
        try:
            commit_result = self.run_command([
                'gh', 'pr', 'view', str(pr_number),
                '--json', 'commits',
                '--jq', '.commits | length'
            ])
            if commit_result['success']:
                commit_count = int(commit_result['stdout'].strip())
                if commit_count <= 1 and is_draft:
                    analysis['is_complete'] = False
                    analysis['completion_score'] -= 35
                    analysis['incomplete_reasons'].append("Draft PR with minimal commits")
        except (ValueError, TypeError):
            pass
        
        # Check 5: Stale PR (no updates in last 48 hours)
        try:
            updated_time = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            if datetime.now().astimezone() - updated_time > timedelta(hours=48):
                analysis['is_complete'] = False
                analysis['completion_score'] -= 15
                analysis['incomplete_reasons'].append("No activity for 48+ hours")
                analysis['priority'] = 'high'
        except Exception:
            pass
        
        # Check 6: Missing requested reviews or unresolved conversations
        requested_reviewers = [r for r in reviews if r.get('state') == 'REQUESTED']
        changes_requested = [r for r in reviews if r.get('state') == 'CHANGES_REQUESTED']
        
        if changes_requested:
            analysis['is_complete'] = False
            analysis['completion_score'] -= 30
            analysis['incomplete_reasons'].append("Changes requested by reviewers")
            analysis['task_type'] = 'fix'
        
        # Check 7: Auto-generated PRs need special handling
        if 'auto-generated' in body or 'auto-fix' in title:
            analysis['task_type'] = 'fix'
            analysis['priority'] = 'high'
            if not analysis['incomplete_reasons']:
                analysis['incomplete_reasons'].append("Auto-generated PR needs implementation")
                analysis['is_complete'] = False
                analysis['completion_score'] -= 20
        
        # Check 8: Workflow fix PRs
        if 'workflow' in title or any('workflow' in f.get('path', '') for f in files):
            analysis['task_type'] = 'fix'
            analysis['priority'] = 'high'
        
        # Determine recommended action
        if analysis['completion_score'] < 50:
            analysis['recommended_action'] = 'assign_copilot'
        elif analysis['completion_score'] < 70:
            analysis['recommended_action'] = 'escalate_copilot'
        elif analysis['completion_score'] < 85:
            analysis['recommended_action'] = 'notify_human'
        
        return analysis
    
    def check_copilot_assignment(self, pr: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        """Check if and how Copilot has been assigned to this PR."""
        pr_number = str(pr['number'])
        comments = pr.get('comments', [])
        
        assignment_info = {
            'has_copilot_mention': False,
            'last_mention_time': None,
            'mention_count': 0,
            'has_recent_activity': False,
            'assignment_history': state.get('assignments', {}).get(pr_number, [])
        }
        
        # Check comments for @copilot mentions
        for comment in comments:
            body = comment.get('body', '')
            if '@copilot' in body.lower():
                assignment_info['has_copilot_mention'] = True
                assignment_info['mention_count'] += 1
                
                # Track most recent mention
                created_at = comment.get('createdAt')
                if created_at:
                    if not assignment_info['last_mention_time'] or created_at > assignment_info['last_mention_time']:
                        assignment_info['last_mention_time'] = created_at
        
        # Check for recent Copilot activity (comments or commits)
        if assignment_info['last_mention_time']:
            try:
                mention_time = datetime.fromisoformat(assignment_info['last_mention_time'].replace('Z', '+00:00'))
                if datetime.now().astimezone() - mention_time < timedelta(hours=6):
                    assignment_info['has_recent_activity'] = True
            except Exception:
                pass
        
        return assignment_info
    
    def create_copilot_assignment(self, pr: Dict[str, Any], analysis: Dict[str, Any], assignment_info: Dict[str, Any]) -> str:
        """Create an appropriate Copilot assignment comment."""
        pr_number = pr['number']
        title = pr['title']
        task_type = analysis['task_type']
        priority = analysis['priority']
        reasons = analysis['incomplete_reasons']
        
        # Determine assignment level based on history
        assignment_level = len(assignment_info['assignment_history']) + 1
        
        if assignment_level == 1:
            # Initial assignment - general help
            if task_type == 'fix':
                comment = f"""@copilot /fix

Please help fix the issues in this PR.

**Issues identified:**
{chr(10).join(f'- {reason}' for reason in reasons)}

**Priority:** {priority.upper()}

Please analyze the problems and implement the necessary fixes."""
            
            elif task_type == 'implement':
                comment = f"""@copilot Please help implement the changes described in this PR.

**Status:** This PR appears to need implementation work.

**Issues identified:**
{chr(10).join(f'- {reason}' for reason in reasons)}

**Priority:** {priority.upper()}

Please review the requirements and implement the solution."""
            
            else:  # review
                comment = f"""@copilot /review

Please review this PR and help with any needed improvements.

**Issues identified:**
{chr(10).join(f'- {reason}' for reason in reasons)}

**Priority:** {priority.upper()}

Please provide feedback and suggestions for completion."""
        
        elif assignment_level == 2:
            # Escalated assignment - more specific instructions
            comment = f"""@copilot This PR still needs attention after the initial assignment.

**Previous assignment:** {assignment_info['assignment_history'][-1].get('type', 'unknown')} at {assignment_info['assignment_history'][-1].get('timestamp', 'unknown')}

**Remaining issues:**
{chr(10).join(f'- {reason}' for reason in reasons)}

**Escalated Instructions:**
1. Review all previous comments and suggestions
2. Identify any blocking issues
3. Implement specific, actionable fixes
4. Ensure all status checks pass
5. Address any reviewer feedback

**Priority:** HIGH

Please provide a comprehensive solution to complete this PR."""
        
        else:
            # Final escalation - detailed requirements
            comment = f"""@copilot **FINAL ESCALATION** - This PR requires immediate attention.

**Assignment History:** {assignment_level - 1} previous assignments
**Last Assignment:** {assignment_info['assignment_history'][-1].get('timestamp', 'unknown')}

**Critical Issues:**
{chr(10).join(f'- {reason}' for reason in reasons)}

**Detailed Requirements:**
1. **Complete Code Review:** Analyze all changed files thoroughly
2. **Fix All Issues:** Address every identified problem
3. **Test Coverage:** Ensure adequate test coverage
4. **Documentation:** Update relevant documentation
5. **Status Checks:** Make all CI/CD checks pass
6. **Ready for Merge:** Prepare PR for final review

**PRIORITY:** CRITICAL

If this PR cannot be completed, please provide a detailed explanation of blockers and recommend next steps.

@{self.notification_user} - This PR has been escalated multiple times and may need human intervention."""
        
        return comment
    
    def assign_copilot_to_pr(self, pr: Dict[str, Any], analysis: Dict[str, Any], assignment_info: Dict[str, Any]) -> bool:
        """Assign Copilot to a PR with appropriate instructions."""
        pr_number = pr['number']
        
        comment = self.create_copilot_assignment(pr, analysis, assignment_info)
        
        if self.dry_run:
            self.logger.info(f"DRY RUN: Would assign Copilot to PR #{pr_number}")
            self.logger.info(f"Comment: {comment[:200]}...")
            return True
        
        result = self.run_command([
            'gh', 'pr', 'comment', str(pr_number),
            '--body', comment
        ])
        
        if result['success']:
            self.logger.info(f"✅ Assigned Copilot to PR #{pr_number}")
            return True
        else:
            self.logger.error(f"❌ Failed to assign Copilot to PR #{pr_number}: {result.get('error', result.get('stderr'))}")
            return False
    
    def notify_human_intervention(self, pr: Dict[str, Any], analysis: Dict[str, Any]) -> bool:
        """Notify human that a PR needs manual intervention."""
        pr_number = pr['number']
        title = pr['title']
        reasons = analysis['incomplete_reasons']
        
        comment = f"""@{self.notification_user} **Human intervention requested** for PR #{pr_number}

**PR Title:** {title}

**Issues requiring attention:**
{chr(10).join(f'- {reason}' for reason in reasons)}

**Completion Score:** {analysis['completion_score']}/100

This PR has been flagged as needing manual review and intervention. Please check the status and provide guidance.

**Recommended actions:**
1. Review the PR description and requirements
2. Check Copilot's previous work and feedback
3. Provide specific instructions or close if no longer needed
4. Consider breaking into smaller tasks if too complex

Generated by Enhanced PR Monitor"""
        
        if self.dry_run:
            self.logger.info(f"DRY RUN: Would notify human for PR #{pr_number}")
            self.logger.info(f"Comment: {comment[:200]}...")
            return True
        
        result = self.run_command([
            'gh', 'pr', 'comment', str(pr_number),
            '--body', comment
        ])
        
        if result['success']:
            self.logger.info(f"✅ Notified human for PR #{pr_number}")
            return True
        else:
            self.logger.error(f"❌ Failed to notify human for PR #{pr_number}: {result.get('error', result.get('stderr'))}")
            return False
    
    def process_pr(self, pr: Dict[str, Any], state: Dict[str, Any], force_reassign: bool = False) -> Dict[str, Any]:
        """Process a single PR for completion and Copilot assignment."""
        pr_number = str(pr['number'])
        title = pr['title']
        
        self.logger.info(f"\n{'='*80}")
        self.logger.info(f"Processing PR #{pr_number}: {title}")
        self.logger.info(f"{'='*80}")
        
        # Analyze PR completion
        analysis = self.analyze_pr_completion(pr)
        
        self.logger.info(f"Completion Status: {'Complete' if analysis['is_complete'] else 'Incomplete'}")
        self.logger.info(f"Completion Score: {analysis['completion_score']}/100")
        self.logger.info(f"Priority: {analysis['priority']}")
        
        if analysis['incomplete_reasons']:
            self.logger.info(f"Issues: {', '.join(analysis['incomplete_reasons'])}")
        
        # Check Copilot assignment status
        assignment_info = self.check_copilot_assignment(pr, state)
        
        result = {
            'pr_number': pr_number,
            'title': title,
            'analysis': analysis,
            'assignment_info': assignment_info,
            'action_taken': 'none',
            'success': True
        }
        
        # Skip if complete and not forcing
        if analysis['is_complete'] and not force_reassign:
            self.logger.info("✅ PR appears complete - no action needed")
            result['action_taken'] = 'skipped_complete'
            return result
        
        # Skip if Copilot recently assigned and not forcing
        if assignment_info['has_recent_activity'] and not force_reassign:
            self.logger.info("✅ Copilot recently active - no action needed")
            result['action_taken'] = 'skipped_recent_activity'
            return result
        
        # Determine action based on analysis
        action = analysis['recommended_action']
        
        if action == 'assign_copilot':
            if self.assign_copilot_to_pr(pr, analysis, assignment_info):
                result['action_taken'] = 'assigned_copilot'
                # Update state
                if pr_number not in state['assignments']:
                    state['assignments'][pr_number] = []
                state['assignments'][pr_number].append({
                    'timestamp': datetime.now().isoformat(),
                    'type': analysis['task_type'],
                    'level': len(assignment_info['assignment_history']) + 1
                })
            else:
                result['success'] = False
                result['action_taken'] = 'failed_assignment'
        
        elif action == 'notify_human':
            if self.notify_human_intervention(pr, analysis):
                result['action_taken'] = 'notified_human'
            else:
                result['success'] = False
                result['action_taken'] = 'failed_notification'
        
        else:
            result['action_taken'] = 'no_action_needed'
        
        # Update processed PRs
        state['processed_prs'][pr_number] = {
            'last_processed': datetime.now().isoformat(),
            'completion_score': analysis['completion_score'],
            'action_taken': result['action_taken']
        }
        
        return result
    
    def run_monitoring(self, pr_number: Optional[str] = None, force_reassign: bool = False) -> Dict[str, Any]:
        """Run the complete PR monitoring process."""
        self.logger.info("🔍 Starting Enhanced PR Monitoring")
        
        if self.dry_run:
            self.logger.info("🔍 DRY RUN MODE - No actual changes will be made")
        
        # Load state
        state = self.load_state()
        
        # Get PRs to process
        prs = self.get_open_prs(pr_number)
        
        if not prs:
            self.logger.warning("No PRs found to process")
            return {'total': 0, 'processed': 0, 'errors': 0}
        
        stats = {
            'total': len(prs),
            'processed': 0,
            'complete': 0,
            'assigned_copilot': 0,
            'notified_human': 0,
            'skipped': 0,
            'errors': 0,
            'results': []
        }
        
        self.logger.info(f"Found {stats['total']} PR(s) to process")
        
        # Process each PR
        for pr in prs:
            try:
                result = self.process_pr(pr, state, force_reassign)
                stats['results'].append(result)
                stats['processed'] += 1
                
                if result['success']:
                    action = result['action_taken']
                    if action == 'assigned_copilot':
                        stats['assigned_copilot'] += 1
                    elif action == 'notified_human':
                        stats['notified_human'] += 1
                    elif action.startswith('skipped'):
                        stats['skipped'] += 1
                        if result['analysis']['is_complete']:
                            stats['complete'] += 1
                else:
                    stats['errors'] += 1
                
            except Exception as e:
                self.logger.error(f"Error processing PR #{pr['number']}: {e}")
                stats['errors'] += 1
        
        # Update state
        state['last_run'] = datetime.now().isoformat()
        self.save_state(state)
        
        # Print summary
        self.print_summary(stats)
        
        return stats
    
    def print_summary(self, stats: Dict[str, Any]):
        """Print monitoring summary."""
        self.logger.info(f"\n{'='*80}")
        self.logger.info("📊 Enhanced PR Monitoring Summary")
        self.logger.info(f"{'='*80}")
        self.logger.info(f"Total PRs:              {stats['total']}")
        self.logger.info(f"Processed:              {stats['processed']}")
        self.logger.info(f"Complete PRs:           {stats['complete']}")
        self.logger.info(f"Copilot Assigned:       {stats['assigned_copilot']}")
        self.logger.info(f"Human Notified:         {stats['notified_human']}")
        self.logger.info(f"Skipped:                {stats['skipped']}")
        self.logger.info(f"Errors:                 {stats['errors']}")
        self.logger.info(f"{'='*80}")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Enhanced PR Monitoring with Intelligent Copilot Assignment'
    )
    parser.add_argument(
        '--pr-number',
        type=str,
        help='Specific PR number to process'
    )
    parser.add_argument(
        '--force-reassign',
        action='store_true',
        help='Force reassignment even if Copilot recently assigned'
    )
    parser.add_argument(
        '--notification-user',
        type=str,
        required=True,
        help='GitHub username to notify for human intervention'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    monitor = EnhancedPRMonitor(
        notification_user=args.notification_user,
        dry_run=args.dry_run
    )
    
    try:
        stats = monitor.run_monitoring(
            pr_number=args.pr_number,
            force_reassign=args.force_reassign
        )
        
        # Exit with error code if there were errors
        sys.exit(0 if stats['errors'] == 0 else 1)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()