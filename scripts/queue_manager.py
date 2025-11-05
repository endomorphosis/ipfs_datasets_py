#!/usr/bin/env python3
"""
Queue Management Utilities

This script provides utilities for managing the PR and issue queues,
including capacity planning and agent status monitoring.
"""

import subprocess
import json
import sys
import argparse
import time
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta


class QueueManager:
    """Manages PR and issue queues with agent capacity planning."""
    
    def __init__(self, max_agents: int = 3):
        self.max_agents = max_agents
        
    def run_gh_command(self, cmd: List[str]) -> Dict[str, Any]:
        """Run GitHub CLI command and return result."""
        try:
            result = subprocess.run(
                ['gh'] + cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            return {
                'success': result.returncode == 0,
                'data': result.stdout if result.returncode == 0 else None,
                'error': result.stderr if result.returncode != 0 else None
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_active_agents(self) -> Dict[str, Any]:
        """Get count of currently active Copilot agents."""
        print("🔍 Checking active Copilot agents...")
        
        # Search for recent @copilot mentions in PRs and issues
        cutoff_time = datetime.now() - timedelta(hours=6)
        cutoff_str = cutoff_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # Get PRs with recent Copilot activity
        pr_result = self.run_gh_command([
            'search', 'issues',
            '--limit', '100',
            f'is:pr is:open @copilot updated:>{cutoff_str}',
            '--json', 'number,title,updatedAt,author'
        ])
        
        active_pr_agents = []
        if pr_result['success'] and pr_result['data']:
            try:
                prs = json.loads(pr_result['data'])
                active_pr_agents = [pr['number'] for pr in prs]
            except json.JSONDecodeError:
                pass
        
        # Get issues with recent Copilot activity
        issue_result = self.run_gh_command([
            'search', 'issues',
            '--limit', '100', 
            f'is:issue is:open @copilot updated:>{cutoff_str}',
            '--json', 'number,title,updatedAt,author'
        ])
        
        active_issue_agents = []
        if issue_result['success'] and issue_result['data']:
            try:
                issues = json.loads(issue_result['data'])
                active_issue_agents = [issue['number'] for issue in issues]
            except json.JSONDecodeError:
                pass
        
        total_active = len(active_pr_agents) + len(active_issue_agents)
        available_slots = max(0, self.max_agents - total_active)
        
        return {
            'active_pr_agents': active_pr_agents,
            'active_issue_agents': active_issue_agents,
            'total_active': total_active,
            'available_slots': available_slots,
            'utilization_pct': (total_active / self.max_agents) * 100
        }
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get comprehensive queue status."""
        print("📊 Analyzing queue status...")
        
        # Get all open PRs
        pr_result = self.run_gh_command([
            'pr', 'list', '--state', 'open', '--limit', '100',
            '--json', 'number,title,isDraft,author,updatedAt,labels'
        ])
        
        prs = []
        if pr_result['success']:
            try:
                prs = json.loads(pr_result['data'])
            except json.JSONDecodeError:
                pass
        
        # Get all open issues
        issue_result = self.run_gh_command([
            'issue', 'list', '--state', 'open', '--limit', '100',
            '--json', 'number,title,author,updatedAt,labels'
        ])
        
        issues = []
        if issue_result['success']:
            try:
                issues = json.loads(issue_result['data'])
            except json.JSONDecodeError:
                pass
        
        # Analyze PRs
        incomplete_prs = []
        for pr in prs:
            if pr['isDraft'] or any(
                keyword in pr['title'].lower() for keyword in 
                ['auto-fix', 'wip', 'draft', 'todo', 'fix:', 'unknown']
            ):
                incomplete_prs.append(pr['number'])
        
        # Analyze issues
        actionable_issues = []
        for issue in issues:
            is_actionable = any(
                label['name'].lower() in ['bug', 'enhancement', 'feature', 'task', 'auto-healing']
                for label in issue.get('labels', [])
            ) or any(
                keyword in issue['title'].lower() for keyword in
                ['fix', 'add', 'implement', 'create', 'update', 'error', 'failure']
            )
            if is_actionable:
                actionable_issues.append(issue['number'])
        
        return {
            'total_prs': len(prs),
            'incomplete_prs': incomplete_prs,
            'total_issues': len(issues),
            'actionable_issues': actionable_issues,
            'queue_size': len(incomplete_prs) + len(actionable_issues)
        }
    
    def plan_work_distribution(self, queue_status: Dict[str, Any], agent_status: Dict[str, Any]) -> Dict[str, Any]:
        """Plan optimal work distribution across available agents."""
        available_slots = agent_status['available_slots']
        incomplete_prs = queue_status['incomplete_prs']
        actionable_issues = queue_status['actionable_issues']
        
        # Prioritize PRs over issues
        pr_batch = incomplete_prs[:available_slots]
        remaining_slots = available_slots - len(pr_batch)
        issue_batch = actionable_issues[:remaining_slots]
        
        strategy = "maintain"
        if available_slots == 0:
            strategy = "monitor"
        elif len(pr_batch) > 0 or len(issue_batch) > 0:
            strategy = "assign"
        
        return {
            'strategy': strategy,
            'pr_batch': pr_batch,
            'issue_batch': issue_batch,
            'total_assignments': len(pr_batch) + len(issue_batch)
        }
    
    def generate_summary_report(self) -> Dict[str, Any]:
        """Generate comprehensive status report."""
        agent_status = self.get_active_agents()
        queue_status = self.get_queue_status()
        work_plan = self.plan_work_distribution(queue_status, agent_status)
        
        return {
            'timestamp': datetime.now().isoformat(),
            'agent_status': agent_status,
            'queue_status': queue_status,
            'work_plan': work_plan,
            'recommendations': self.generate_recommendations(agent_status, queue_status, work_plan)
        }
    
    def generate_recommendations(self, agent_status: Dict[str, Any], queue_status: Dict[str, Any], work_plan: Dict[str, Any]) -> List[str]:
        """Generate actionable recommendations."""
        recommendations = []
        
        utilization = agent_status['utilization_pct']
        queue_size = queue_status['queue_size']
        
        if utilization < 50:
            recommendations.append("🟡 Low agent utilization - consider triggering queue processing")
        elif utilization >= 100:
            recommendations.append("🔴 All agents busy - monitor for completion")
        else:
            recommendations.append("🟢 Good agent utilization")
        
        if queue_size > 20:
            recommendations.append("⚠️ Large queue detected - consider increasing max agents")
        elif queue_size == 0:
            recommendations.append("✅ Queue is empty - excellent!")
        
        if work_plan['strategy'] == 'assign':
            recommendations.append(f"🚀 Ready to assign {work_plan['total_assignments']} new tasks")
        elif work_plan['strategy'] == 'monitor':
            recommendations.append("👀 All agents busy - monitoring progress")
        
        return recommendations
    
    def print_report(self, report: Dict[str, Any]):
        """Print formatted status report."""
        print(f"\n{'='*80}")
        print(f"🤖 Queue Management Status Report")
        print(f"{'='*80}")
        print(f"Timestamp: {report['timestamp']}")
        print(f"Max Agents: {self.max_agents}")
        print()
        
        agent_status = report['agent_status']
        print(f"📊 Agent Status:")
        print(f"  Active PR agents: {len(agent_status['active_pr_agents'])}")
        print(f"  Active issue agents: {len(agent_status['active_issue_agents'])}")
        print(f"  Total active: {agent_status['total_active']}")
        print(f"  Available slots: {agent_status['available_slots']}")
        print(f"  Utilization: {agent_status['utilization_pct']:.1f}%")
        print()
        
        queue_status = report['queue_status']
        print(f"📋 Queue Status:")
        print(f"  Total PRs: {queue_status['total_prs']}")
        print(f"  Incomplete PRs: {len(queue_status['incomplete_prs'])}")
        print(f"  Total Issues: {queue_status['total_issues']}")
        print(f"  Actionable Issues: {len(queue_status['actionable_issues'])}")
        print(f"  Total queue size: {queue_status['queue_size']}")
        print()
        
        work_plan = report['work_plan']
        print(f"🎯 Work Plan:")
        print(f"  Strategy: {work_plan['strategy']}")
        print(f"  PRs to assign: {len(work_plan['pr_batch'])}")
        print(f"  Issues to assign: {len(work_plan['issue_batch'])}")
        print(f"  Total new assignments: {work_plan['total_assignments']}")
        print()
        
        print(f"💡 Recommendations:")
        for rec in report['recommendations']:
            print(f"  {rec}")
        
        print(f"{'='*80}")
    
    def trigger_workflow(self, dry_run: bool = False) -> bool:
        """Trigger the continuous queue management workflow."""
        print("🚀 Triggering continuous queue management workflow...")
        
        cmd = [
            'workflow', 'run', 'continuous-queue-management.yml',
            '--field', f'max_agents={self.max_agents}'
        ]
        
        if dry_run:
            cmd.extend(['--field', 'dry_run=true'])
        
        result = self.run_gh_command(cmd)
        
        if result['success']:
            print("✅ Workflow triggered successfully")
            return True
        else:
            print(f"❌ Failed to trigger workflow: {result['error']}")
            return False


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(description='Queue Management Utilities')
    parser.add_argument(
        '--max-agents',
        type=int,
        default=3,
        help='Maximum number of concurrent agents (default: 3)'
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='Show current queue status'
    )
    parser.add_argument(
        '--trigger',
        action='store_true',
        help='Trigger the queue management workflow'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run mode for workflow trigger'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output results in JSON format'
    )
    
    args = parser.parse_args()
    
    manager = QueueManager(max_agents=args.max_agents)
    
    if args.status:
        report = manager.generate_summary_report()
        
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            manager.print_report(report)
    
    if args.trigger:
        success = manager.trigger_workflow(dry_run=args.dry_run)
        sys.exit(0 if success else 1)
    
    # If no specific action, show status
    if not args.status and not args.trigger:
        report = manager.generate_summary_report()
        manager.print_report(report)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)