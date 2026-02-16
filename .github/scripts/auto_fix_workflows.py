#!/usr/bin/env python3
"""
Auto-fix common workflow issues based on validator findings
"""
import os
import re
import yaml
from pathlib import Path

def add_timeout_to_jobs(workflow_path):
    """Add timeout-minutes to jobs missing it"""
    with open(workflow_path, 'r') as f:
        content = f.read()
    
    # Check if we need to add timeouts
    if 'timeout-minutes:' in content:
        return False
    
    lines = content.split('\n')
    modified = False
    new_lines = []
    in_job = False
    job_indent = 0
    
    for i, line in enumerate(lines):
        new_lines.append(line)
        
        # Detect job definition
        if re.match(r'^  \w+:$', line) and i > 0 and 'jobs:' in lines[i-1]:
            in_job = True
            job_indent = len(line) - len(line.lstrip())
        
        # Add timeout after runs-on if missing
        if in_job and 'runs-on:' in line:
            # Check if next line has timeout
            if i + 1 < len(lines) and 'timeout-minutes:' not in lines[i+1]:
                indent = ' ' * (job_indent + 2)
                new_lines.append(f'{indent}timeout-minutes: 30')
                modified = True
    
    if modified:
        with open(workflow_path, 'w') as f:
            f.write('\n'.join(new_lines))
    
    return modified

def add_concurrency_control(workflow_path):
    """Add concurrency control if missing"""
    with open(workflow_path, 'r') as f:
        content = f.read()
    
    if 'concurrency:' in content:
        return False
    
    lines = content.split('\n')
    
    # Find where to insert (after 'on:' section)
    insert_index = None
    for i, line in enumerate(lines):
        if line.strip().startswith('on:'):
            # Find end of on: section
            j = i + 1
            while j < len(lines) and (lines[j].startswith('  ') or lines[j].strip() == ''):
                j += 1
            insert_index = j
            break
    
    if insert_index is None:
        return False
    
    # Extract workflow name
    workflow_name = None
    for line in lines[:10]:
        if line.startswith('name:'):
            workflow_name = line.split('name:')[1].strip().strip('"').strip("'")
            break
    
    if not workflow_name:
        return False
    
    concurrency_block = [
        '',
        'concurrency:',
        f'  group: ${{{{ github.workflow }}}}-${{{{ github.ref }}}}',
        '  cancel-in-progress: true',
        ''
    ]
    
    lines[insert_index:insert_index] = concurrency_block
    
    with open(workflow_path, 'w') as f:
        f.write('\n'.join(lines))
    
    return True

def main():
    workflows_dir = Path('.github/workflows')
    
    fixed_count = 0
    timeout_added = 0
    concurrency_added = 0
    
    for workflow_file in workflows_dir.glob('*.yml'):
        if workflow_file.name.startswith('.'):
            continue
        
        print(f"Processing {workflow_file.name}...")
        
        # Add timeouts
        if add_timeout_to_jobs(workflow_file):
            timeout_added += 1
            fixed_count += 1
            print(f"  ✅ Added timeouts")
        
        # Add concurrency
        if add_concurrency_control(workflow_file):
            concurrency_added += 1
            fixed_count += 1
            print(f"  ✅ Added concurrency control")
    
    print(f"\n{'='*60}")
    print(f"Auto-fix Summary:")
    print(f"  Workflows processed: {len(list(workflows_dir.glob('*.yml')))}")
    print(f"  Workflows fixed: {fixed_count}")
    print(f"  Timeouts added: {timeout_added}")
    print(f"  Concurrency added: {concurrency_added}")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()
