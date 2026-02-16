#!/usr/bin/env python3
"""
Optimize checkout actions by adding fetch-depth: 1 where appropriate
"""
import re
from pathlib import Path

def optimize_checkout(workflow_path):
    """Add fetch-depth: 1 to checkout actions without it"""
    with open(workflow_path, 'r') as f:
        content = f.read()
    
    # Skip if already optimized or if it's a workflow that needs full history
    if 'fetch-depth: 1' in content or 'fetch-depth: 0' in content:
        return False
    
    # Workflows that need full git history (skip these)
    skip_patterns = [
        'documentation-maintenance',
        'issue-to-draft-pr',
        'copilot-agent-autofix'
    ]
    
    if any(pattern in workflow_path.name for pattern in skip_patterns):
        return False
    
    lines = content.split('\n')
    modified = False
    new_lines = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        new_lines.append(line)
        
        # Look for checkout action
        if 'uses: actions/checkout@v' in line:
            # Check if next few lines have 'with:'
            j = i + 1
            has_with = False
            with_indent = 0
            
            while j < len(lines) and j < i + 5:
                if lines[j].strip().startswith('with:'):
                    has_with = True
                    with_indent = len(lines[j]) - len(lines[j].lstrip())
                    break
                elif lines[j].strip() and not lines[j].strip().startswith('#'):
                    if not lines[j].startswith(' ' * (len(line) - len(line.lstrip()) + 2)):
                        break
                j += 1
            
            if has_with:
                # with: exists, add fetch-depth after it if not present
                new_lines.append(lines[i+1])
                indent = ' ' * (with_indent + 2)
                new_lines.append(f'{indent}fetch-depth: 1')
                modified = True
                i += 1  # Skip the 'with:' line we just added
            else:
                # No with:, add it
                indent = ' ' * (len(line) - len(line.lstrip()) + 2)
                new_lines.append(f'{indent}with:')
                new_lines.append(f'{indent}  fetch-depth: 1')
                modified = True
        
        i += 1
    
    if modified:
        with open(workflow_path, 'w') as f:
            f.write('\n'.join(new_lines))
    
    return modified

def main():
    workflows_dir = Path('.github/workflows')
    
    optimized = []
    
    for workflow_file in workflows_dir.glob('*.yml'):
        if workflow_file.name.startswith('.'):
            continue
        
        if optimize_checkout(workflow_file):
            optimized.append(workflow_file.name)
            print(f"✅ Optimized {workflow_file.name}")
    
    print(f"\n{'='*60}")
    print(f"Checkout Optimization Summary:")
    print(f"  Workflows optimized: {len(optimized)}")
    print(f"{'='*60}")
    
    if optimized:
        print("\nOptimized workflows:")
        for name in sorted(optimized):
            print(f"  - {name}")

if __name__ == '__main__':
    main()
