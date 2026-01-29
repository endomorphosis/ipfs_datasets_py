#!/usr/bin/env python3
"""
Test Copilot Invocation Methods

This script tests different methods to invoke GitHub Copilot agents
and reports which ones are available and working.
"""

import subprocess
import json
import sys
from typing import Dict, List, Any


class CopilotInvocationTester:
    """Test different methods of invoking GitHub Copilot agents."""
    
    def __init__(self):
        self.test_results = {}
    
    def run_command(self, cmd: List[str], timeout: int = 30) -> Dict[str, Any]:
        """Run a command and return result."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return {
                'success': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            }
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Command timed out'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def test_gh_agent_task(self) -> Dict[str, Any]:
        """Test if gh agent-task is available."""
        print("🔍 Testing: gh agent-task...")
        
        result = self.run_command(['gh', 'agent-task', '--help'])
        
        if result['success']:
            print("✅ gh agent-task is available")
            return {
                'available': True,
                'method': 'gh_agent_task',
                'description': 'GitHub CLI agent task creation',
                'command_example': 'gh agent-task create --title "..." --body "..."'
            }
        else:
            print("❌ gh agent-task not available")
            print(f"   Error: {result.get('stderr', result.get('error', 'Unknown'))}")
            return {
                'available': False,
                'method': 'gh_agent_task',
                'error': result.get('stderr', result.get('error'))
            }
    
    def test_gh_copilot_extension(self) -> Dict[str, Any]:
        """Test if GitHub Copilot CLI extension is available."""
        print("🔍 Testing: gh copilot extension...")
        
        # Check if extension is installed
        list_result = self.run_command(['gh', 'extension', 'list'])
        
        has_copilot_ext = False
        if list_result['success']:
            has_copilot_ext = 'copilot' in list_result['stdout'].lower()
        
        if not has_copilot_ext:
            print("❌ GitHub Copilot extension not installed")
            return {
                'available': False,
                'method': 'gh_copilot_extension',
                'error': 'Extension not installed',
                'install_command': 'gh extension install github/gh-copilot'
            }
        
        # Test copilot command
        result = self.run_command(['gh', 'copilot', '--help'])
        
        if result['success']:
            print("✅ gh copilot extension is available")
            return {
                'available': True,
                'method': 'gh_copilot_extension',
                'description': 'GitHub Copilot CLI extension',
                'command_example': 'gh copilot suggest "..."'
            }
        else:
            print("❌ gh copilot extension not working")
            return {
                'available': False,
                'method': 'gh_copilot_extension',
                'error': result.get('stderr', result.get('error'))
            }
    
    def test_copilot_cli(self) -> Dict[str, Any]:
        """Test if standalone Copilot CLI is available."""
        print("🔍 Testing: copilot CLI...")
        
        result = self.run_command(['copilot', '--version'])
        
        if result['success']:
            print("✅ copilot CLI is available")
            return {
                'available': True,
                'method': 'copilot_cli',
                'description': 'Standalone GitHub Copilot CLI',
                'version': result['stdout'].strip(),
                'command_example': 'copilot -p "..."'
            }
        else:
            print("❌ copilot CLI not available")
            return {
                'available': False,
                'method': 'copilot_cli',
                'error': result.get('stderr', result.get('error')),
                'install_command': 'npm install -g @github/copilot'
            }
    
    def test_workflow_dispatch(self) -> Dict[str, Any]:
        """Test if workflow dispatch method is available."""
        print("🔍 Testing: workflow dispatch method...")
        
        # Test if we can list workflows
        result = self.run_command(['gh', 'workflow', 'list'])
        
        if not result['success']:
            print("❌ Cannot access workflows")
            return {
                'available': False,
                'method': 'workflow_dispatch',
                'error': 'Cannot access workflows'
            }
        
        # Check for copilot-related workflows
        workflows = result['stdout']
        copilot_workflows = []
        
        for line in workflows.split('\n'):
            if 'copilot' in line.lower() or 'agent' in line.lower():
                copilot_workflows.append(line.strip())
        
        if copilot_workflows:
            print(f"✅ Found {len(copilot_workflows)} potential Copilot workflow(s)")
            return {
                'available': True,
                'method': 'workflow_dispatch',
                'description': 'GitHub Actions workflow dispatch',
                'workflows': copilot_workflows,
                'command_example': 'gh workflow run copilot-workflow --field pr_number=123'
            }
        else:
            print("⚠️ No Copilot workflows found")
            return {
                'available': False,
                'method': 'workflow_dispatch',
                'error': 'No Copilot workflows available'
            }
    
    def test_github_pull_request_copilot_coding_agent(self) -> Dict[str, Any]:
        """Test the github-pull-request_copilot-coding-agent workflow specifically."""
        print("🔍 Testing: github-pull-request_copilot-coding-agent workflow...")
        
        # Test if we can access this specific workflow
        result = self.run_command([
            'gh', 'workflow', 'view', 'github-pull-request_copilot-coding-agent'
        ])
        
        if result['success']:
            print("✅ github-pull-request_copilot-coding-agent workflow is available")
            return {
                'available': True,
                'method': 'github_pull_request_copilot_coding_agent',
                'description': 'GitHub Pull Request Copilot Coding Agent workflow',
                'command_example': 'gh workflow run github-pull-request_copilot-coding-agent --field title="..." --field body="..." --field existingPullRequest=123'
            }
        else:
            print("❌ github-pull-request_copilot-coding-agent workflow not available")
            return {
                'available': False,
                'method': 'github_pull_request_copilot_coding_agent',
                'error': result.get('stderr', result.get('error'))
            }
    
    def test_comment_method(self) -> Dict[str, Any]:
        """Test the @copilot comment method (always available)."""
        print("🔍 Testing: @copilot comment method...")
        
        # This method is always available if we have gh CLI access
        result = self.run_command(['gh', '--version'])
        
        if result['success']:
            print("✅ @copilot comment method is available")
            return {
                'available': True,
                'method': 'copilot_comment',
                'description': '@copilot mentions in PR comments (proven to work)',
                'command_example': 'gh pr comment 123 --body "@copilot /fix Please fix this PR"',
                'note': 'This method has been proven to work and create child PRs'
            }
        else:
            print("❌ GitHub CLI not available")
            return {
                'available': False,
                'method': 'copilot_comment',
                'error': 'GitHub CLI not available'
            }
    
    def run_all_tests(self) -> Dict[str, Any]:
        """Run all Copilot invocation tests."""
        print("🚀 Testing all available Copilot invocation methods...\n")
        
        test_methods = [
            self.test_gh_agent_task,
            self.test_github_pull_request_copilot_coding_agent,
            self.test_gh_copilot_extension,
            self.test_copilot_cli,
            self.test_workflow_dispatch,
            self.test_comment_method
        ]
        
        results = {}
        available_methods = []
        
        for test_method in test_methods:
            try:
                result = test_method()
                method_name = result['method']
                results[method_name] = result
                
                if result['available']:
                    available_methods.append(result)
                
                print()  # Add spacing between tests
                
            except Exception as e:
                print(f"❌ Error testing method: {e}\n")
        
        return {
            'all_results': results,
            'available_methods': available_methods,
            'total_available': len(available_methods)
        }
    
    def print_summary(self, results: Dict[str, Any]):
        """Print a summary of available methods."""
        available = results['available_methods']
        total = results['total_available']
        
        print(f"{'='*80}")
        print(f"📊 COPILOT INVOCATION METHODS SUMMARY")
        print(f"{'='*80}")
        print(f"Total available methods: {total}")
        print()
        
        if total == 0:
            print("❌ No Copilot invocation methods are available!")
            print("💡 Consider installing GitHub Copilot CLI or enabling workflows.")
            return
        
        print("✅ Available methods (in order of preference):")
        
        # Sort by preference
        preference_order = [
            'github_pull_request_copilot_coding_agent',
            'gh_agent_task',
            'gh_copilot_extension', 
            'copilot_cli',
            'workflow_dispatch',
            'copilot_comment'
        ]
        
        sorted_methods = []
        for method_name in preference_order:
            for method in available:
                if method['method'] == method_name:
                    sorted_methods.append(method)
                    break
        
        for i, method in enumerate(sorted_methods, 1):
            print(f"\n{i}. **{method['method']}**")
            print(f"   Description: {method['description']}")
            if 'command_example' in method:
                print(f"   Example: {method['command_example']}")
            if 'note' in method:
                print(f"   Note: {method['note']}")
        
        print(f"\n{'='*80}")
        print("💡 Recommendation:")
        
        if any(m['method'] == 'github_pull_request_copilot_coding_agent' for m in available):
            print("   Use github-pull-request_copilot-coding-agent workflow for best results")
        elif any(m['method'] == 'copilot_comment' for m in available):
            print("   Use @copilot comments (proven to work with child PR creation)")
        else:
            print("   Install GitHub Copilot CLI or enable workflows for better integration")
        
        print(f"{'='*80}")


def main():
    """Main execution."""
    tester = CopilotInvocationTester()
    
    try:
        results = tester.run_all_tests()
        tester.print_summary(results)
        
        # Exit with success if any methods are available
        sys.exit(0 if results['total_available'] > 0 else 1)
        
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()