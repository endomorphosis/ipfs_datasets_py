#!/usr/bin/env python3
"""
Add dependency caching to workflows missing it
"""
import re
from pathlib import Path

def add_pip_cache(workflow_path):
    """Add pip caching to Python setup actions"""
    with open(workflow_path, 'r') as f:
        content = f.read()
    
    # Skip if already has cache or isn't using Python
    if "cache: 'pip'" in content or 'setup-python' not in content:
        return False
    
    lines = content.split('\n')
    modified = False
    new_lines = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        new_lines.append(line)
        
        # Look for setup-python action
        if 'uses: actions/setup-python@v' in line:
            # Check if next line has 'with:'
            j = i + 1
            while j < len(lines) and j < i + 5:
                if lines[j].strip().startswith('with:'):
                    # Find python-version line
                    k = j + 1
                    while k < len(lines) and k < j + 5:
                        if 'python-version' in lines[k]:
                            new_lines.append(lines[j])  # Add 'with:' line
                            new_lines.append(lines[k])  # Add python-version line
                            # Add cache line
                            indent = ' ' * (len(lines[k]) - len(lines[k].lstrip()))
                            new_lines.append(f"{indent}cache: 'pip'")
                            modified = True
                            i = k  # Skip to after python-version
                            break
                        k += 1
                    break
                j += 1
        
        i += 1
    
    if modified:
        with open(workflow_path, 'w') as f:
            f.write('\n'.join(new_lines))
    
    return modified

def main():
    workflows_dir = Path('.github/workflows')
    
    cached = []
    
    for workflow_file in workflows_dir.glob('*.yml'):
        if workflow_file.name.startswith('.'):
            continue
        
        if add_pip_cache(workflow_file):
            cached.append(workflow_file.name)
            print(f"✅ Added caching to {workflow_file.name}")
    
    print(f"\n{'='*60}")
    print(f"Caching Optimization Summary:")
    print(f"  Workflows with cache added: {len(cached)}")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()
