#!/usr/bin/env python3
"""
Apply workflow fixes based on the generated proposal.

This script takes a fix proposal and applies the changes to the repository,
creating the necessary modifications to workflow files and related files.
"""

import argparse
import json
import re
import yaml
from pathlib import Path
from typing import Dict, List, Any


class WorkflowFixApplier:
    """Applies workflow fixes to repository files."""
    
    def __init__(self, proposal: Dict[str, Any], repo_path: Path):
        self.proposal = proposal
        self.repo_path = Path(repo_path)
        self.changes_applied = []
    
    def apply(self) -> List[Dict[str, str]]:
        """Apply all fixes from the proposal."""
        print(f"🔧 Applying fixes from proposal...")
        
        fixes = self.proposal.get('fixes', [])
        
        for fix in fixes:
            try:
                if fix['action'] == 'add_install_step':
                    self._apply_add_install_step(fix)
                
                elif fix['action'] == 'add_line':
                    self._apply_add_line(fix)
                
                elif fix['action'] == 'add_timeout':
                    self._apply_add_timeout(fix)
                
                elif fix['action'] == 'add_permissions':
                    self._apply_add_permissions(fix)
                
                elif fix['action'] == 'add_retry_action':
                    self._apply_add_retry_action(fix)
                
                elif fix['action'] == 'add_docker_setup':
                    self._apply_add_docker_setup(fix)
                
                elif fix['action'] == 'change_runner':
                    self._apply_change_runner(fix)
                
                elif fix['action'] == 'add_env':
                    self._apply_add_env(fix)
                
                elif fix['action'] == 'review_required':
                    self._create_review_note(fix)
                
                else:
                    print(f"⚠️  Unknown action: {fix['action']}")
                
            except Exception as e:
                print(f"❌ Error applying fix to {fix['file']}: {e}")
        
        return self.changes_applied
    
    def _apply_add_install_step(self, fix: Dict[str, Any]):
        """Add a pip install step to workflow."""
        file_path = self.repo_path / fix['file']
        
        if not file_path.exists():
            print(f"⚠️  Workflow file not found: {file_path}")
            return
        
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Parse YAML
        try:
            workflow = yaml.safe_load(content)
        except Exception as e:
            print(f"❌ Could not parse YAML: {e}")
            return
        
        # Find the first job with steps
        for job_name, job_config in workflow.get('jobs', {}).items():
            if 'steps' in job_config:
                # Find install dependencies step
                install_step_idx = -1
                for idx, step in enumerate(job_config['steps']):
                    step_name = step.get('name', '').lower()
                    if 'install' in step_name and 'dependenc' in step_name:
                        install_step_idx = idx
                        break
                
                if install_step_idx >= 0:
                    # Add to existing install step
                    install_step = job_config['steps'][install_step_idx]
                    if 'run' in install_step:
                        # Extract package name from fix changes
                        package_match = re.search(r'pip install (\S+)', fix['changes'])
                        if package_match:
                            package = package_match.group(1)
                            install_step['run'] += f"\n    pip install {package}"
                            
                            # Write back
                            with open(file_path, 'w') as f:
                                yaml.dump(workflow, f, default_flow_style=False, sort_keys=False)
                            
                            self.changes_applied.append({
                                'file': fix['file'],
                                'action': 'modified',
                                'description': fix['description'],
                            })
                            print(f"✅ Added install step to {file_path}")
                break
    
    def _apply_add_line(self, fix: Dict[str, Any]):
        """Add a line to a file (e.g., requirements.txt)."""
        file_path = self.repo_path / fix['file']
        
        # Create file if it doesn't exist
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        content = ""
        if file_path.exists():
            with open(file_path, 'r') as f:
                content = f.read()
        
        # Check if line already exists
        line_to_add = fix['changes'].strip()
        if line_to_add not in content:
            # Add line
            if content and not content.endswith('\n'):
                content += '\n'
            content += line_to_add + '\n'
            
            with open(file_path, 'w') as f:
                f.write(content)
            
            self.changes_applied.append({
                'file': fix['file'],
                'action': 'modified',
                'description': fix['description'],
            })
            print(f"✅ Added line to {file_path}")
    
    def _apply_add_timeout(self, fix: Dict[str, Any]):
        """Add timeout to workflow steps."""
        file_path = self.repo_path / fix['file']
        
        if not file_path.exists():
            print(f"⚠️  Workflow file not found: {file_path}")
            return
        
        with open(file_path, 'r') as f:
            content = f.read()
        
        try:
            workflow = yaml.safe_load(content)
        except Exception as e:
            print(f"❌ Could not parse YAML: {e}")
            return
        
        # Add timeout to jobs or steps
        modified = False
        for job_name, job_config in workflow.get('jobs', {}).items():
            if 'timeout-minutes' not in job_config:
                job_config['timeout-minutes'] = 30
                modified = True
        
        if modified:
            with open(file_path, 'w') as f:
                yaml.dump(workflow, f, default_flow_style=False, sort_keys=False)
            
            self.changes_applied.append({
                'file': fix['file'],
                'action': 'modified',
                'description': fix['description'],
            })
            print(f"✅ Added timeout to {file_path}")
    
    def _apply_add_permissions(self, fix: Dict[str, Any]):
        """Add permissions to workflow."""
        file_path = self.repo_path / fix['file']
        
        if not file_path.exists():
            print(f"⚠️  Workflow file not found: {file_path}")
            return
        
        with open(file_path, 'r') as f:
            content = f.read()
        
        try:
            workflow = yaml.safe_load(content)
        except Exception as e:
            print(f"❌ Could not parse YAML: {e}")
            return
        
        # Add permissions if not present
        if 'permissions' not in workflow:
            workflow['permissions'] = {
                'contents': 'write',
                'pull-requests': 'write',
                'issues': 'write',
                'actions': 'read',
            }
            
            with open(file_path, 'w') as f:
                yaml.dump(workflow, f, default_flow_style=False, sort_keys=False)
            
            self.changes_applied.append({
                'file': fix['file'],
                'action': 'modified',
                'description': fix['description'],
            })
            print(f"✅ Added permissions to {file_path}")
    
    def _apply_add_retry_action(self, fix: Dict[str, Any]):
        """Add retry action to workflow."""
        # This is more complex - create a note for manual review
        self._create_review_note(fix)
    
    def _apply_add_docker_setup(self, fix: Dict[str, Any]):
        """Add Docker setup steps to workflow."""
        # This is more complex - create a note for manual review
        self._create_review_note(fix)
    
    def _apply_change_runner(self, fix: Dict[str, Any]):
        """Change runner type in workflow."""
        file_path = self.repo_path / fix['file']
        
        if not file_path.exists():
            print(f"⚠️  Workflow file not found: {file_path}")
            return
        
        with open(file_path, 'r') as f:
            content = f.read()
        
        try:
            workflow = yaml.safe_load(content)
        except Exception as e:
            print(f"❌ Could not parse YAML: {e}")
            return
        
        # Change runs-on for all jobs
        modified = False
        for job_name, job_config in workflow.get('jobs', {}).items():
            if 'runs-on' in job_config and job_config['runs-on'] == 'ubuntu-latest':
                job_config['runs-on'] = 'ubuntu-latest-4-cores'
                modified = True
        
        if modified:
            with open(file_path, 'w') as f:
                yaml.dump(workflow, f, default_flow_style=False, sort_keys=False)
            
            self.changes_applied.append({
                'file': fix['file'],
                'action': 'modified',
                'description': fix['description'],
            })
            print(f"✅ Changed runner in {file_path}")
    
    def _apply_add_env(self, fix: Dict[str, Any]):
        """Add environment variables to workflow."""
        file_path = self.repo_path / fix['file']
        
        if not file_path.exists():
            print(f"⚠️  Workflow file not found: {file_path}")
            return
        
        with open(file_path, 'r') as f:
            content = f.read()
        
        try:
            workflow = yaml.safe_load(content)
        except Exception as e:
            print(f"❌ Could not parse YAML: {e}")
            return
        
        # Add env section if not present
        if 'env' not in workflow:
            workflow['env'] = {}
        
        # Note: We can't automatically add the actual env var without knowing its value
        # So we add a comment placeholder
        self._create_review_note(fix)
    
    def _create_review_note(self, fix: Dict[str, Any]):
        """Create a review note file for manual fixes."""
        notes_file = self.repo_path / 'AUTOFIX_REVIEW_NOTES.md'
        
        note = f"""
## {fix['description']}

**File**: `{fix['file']}`
**Action**: {fix['action']}

### Suggested Changes
```yaml
{fix.get('changes', 'See fix description')}
```

---
"""
        
        # Append to notes file
        with open(notes_file, 'a') as f:
            f.write(note)
        
        self.changes_applied.append({
            'file': 'AUTOFIX_REVIEW_NOTES.md',
            'action': 'created',
            'description': 'Added review notes for manual fixes',
        })
        print(f"📝 Created review note for {fix['description']}")


def main():
    parser = argparse.ArgumentParser(
        description='Apply workflow fixes from proposal'
    )
    parser.add_argument('--proposal', required=True, help='Path to fix proposal JSON')
    parser.add_argument('--repo-path', required=True, help='Repository path')
    
    args = parser.parse_args()
    
    # Load proposal
    with open(args.proposal, 'r') as f:
        proposal = json.load(f)
    
    # Apply fixes
    applier = WorkflowFixApplier(
        proposal=proposal,
        repo_path=Path(args.repo_path),
    )
    
    changes = applier.apply()
    
    print(f"\n✅ Applied {len(changes)} changes:")
    for change in changes:
        print(f"   - {change['action']}: {change['file']}")


if __name__ == '__main__':
    main()
