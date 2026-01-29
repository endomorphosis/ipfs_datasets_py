#!/usr/bin/env python3
"""
Script to split master_todo_list.md into separate TODO.md files for each subdirectory.
Worker 10 assignment: Split master_todo_list.md into separate TODO.md files for each subdirectory 
in ipfs_datasets_py except mcp_server.

This is an adhoc tool created on-the-fly by Claude Code to handle a specific task.
"""

import argparse
import os
import re
import random
from pathlib import Path

def assign_workers_to_directories(subdirs, start_worker_id=61):
    """
    Randomly assign workers to directories.
    
    Args:
        subdirs: List of subdirectories to assign workers to
        start_worker_id: Starting worker ID number
        
    Returns:
        dict: Mapping of directory to worker ID
    """
    # Create worker pool starting from start_worker_id
    workers = list(range(start_worker_id, start_worker_id + len(subdirs)))
    
    # Shuffle workers for random assignment
    random.shuffle(workers)
    
    # Assign workers to directories
    assignments = {}
    for i, subdir in enumerate(subdirs):
        assignments[subdir] = workers[i]
    
    return assignments

def update_claude_md_with_assignments(assignments):
    """
    Update CLAUDE.md file with worker assignments.
    
    Args:
        assignments: Dictionary mapping directories to worker IDs
    """
    claude_md_path = Path('/home/kylerose1946/ipfs_datasets_py/CLAUDE.md')
    
    # Read current CLAUDE.md
    with open(claude_md_path, 'r') as f:
        content = f.read()
    
    # Generate worker assignment section
    worker_assignments = []
    for directory, worker_id in sorted(assignments.items()):
        worker_assignments.append(f"- [ ] {worker_id}: Complete TDD tasks for {directory}/ directory")
    
    assignment_section = "\n### Directory-Specific Jobs - Workers 61-75\n" + "\n".join(worker_assignments)
    
    # Find where to insert the assignments (after Priority Jobs section)
    if "### Directory-Specific Jobs" in content:
        # Replace existing section
        pattern = r'### Directory-Specific Jobs - Workers \d+-\d+\n(?:- \[ \] \d+: Complete TDD tasks for .+\n)*'
        content = re.sub(pattern, assignment_section + "\n", content)
    else:
        # Add new section after Priority Jobs
        priority_jobs_end = content.find("### Rules for All Jobs")
        if priority_jobs_end != -1:
            content = content[:priority_jobs_end] + assignment_section + "\n\n" + content[priority_jobs_end:]
    
    # Write updated content
    with open(claude_md_path, 'w') as f:
        f.write(content)
    
    print("Updated CLAUDE.md with worker assignments")

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Split master_todo_list.md into separate TODO.md files for each subdirectory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument('--base-dir', type=str, 
                       default='/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py',
                       help='Base directory containing subdirectories (default: %(default)s)')
    parser.add_argument('--master-todo', type=str,
                       default='/home/kylerose1946/ipfs_datasets_py/master_todo_list.md', 
                       help='Path to master TODO list file (default: %(default)s)')
    parser.add_argument('--claude-md', type=str,
                       default='/home/kylerose1946/ipfs_datasets_py/CLAUDE.md',
                       help='Path to CLAUDE.md file for worker assignments (default: %(default)s)')
    parser.add_argument('--start-worker-id', type=int, default=61,
                       help='Starting worker ID for assignments (default: %(default)s)')
    parser.add_argument('--subdirs', nargs='*',
                       default=['audit', 'config', 'embeddings', 'ipfs_embeddings_py', 'ipld', 'llm', 
                               'logic_integration', 'mcp_tools', 'multimedia', 'optimizers', 'rag', 
                               'search', 'utils', 'vector_stores', 'wikipedia_x'],
                       help='List of subdirectories to process (default: all except mcp_server)')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose output')
    
    return parser.parse_args()

def main():
    args = parse_arguments()
    
    # Use command line arguments
    subdirs = args.subdirs
    base_dir = Path(args.base_dir)
    master_todo_path = Path(args.master_todo)
    claude_md_path = Path(args.claude_md)
    
    # Read the master todo list
    with open(master_todo_path, 'r') as f:
        content = f.read()
    
    # Parse the content to extract sections for each subdirectory
    sections = {}
    current_section = None
    current_content = []
    
    for line in content.split('\n'):
        # Check if line starts a new section for a subdirectory
        if line.startswith('- [ ] ') and '/' in line:
            # Extract directory name from the line
            dir_match = re.search(r'- \[ \] ([^/]+)/', line)
            if dir_match:
                dir_name = dir_match.group(1)
                if dir_name in subdirs:
                    # Save previous section if exists
                    if current_section and current_content:
                        sections[current_section] = '\n'.join(current_content)
                    
                    # Start new section
                    current_section = dir_name
                    current_content = [line]
                    continue
        
        # Check if this is a file in a subdirectory we care about
        file_match = re.match(r'- \[ \] ([^/]+)\.py$', line)
        if file_match:
            file_name = file_match.group(1)
            # Check if this file belongs to any of our subdirectories
            for subdir in subdirs:
                subdir_path = base_dir / subdir
                if subdir_path.exists():
                    file_path = subdir_path / f"{file_name}.py"
                    if file_path.exists():
                        if current_section != subdir:
                            # Save previous section if exists
                            if current_section and current_content:
                                sections[current_section] = '\n'.join(current_content)
                            
                            # Start new section
                            current_section = subdir
                            current_content = [line]
                        else:
                            current_content.append(line)
                        break
            continue
        
        # Add line to current section if we're in one
        if current_section and line.strip():
            current_content.append(line)
    
    # Save the last section
    if current_section and current_content:
        sections[current_section] = '\n'.join(current_content)
    
    # Assign workers to directories
    worker_assignments = assign_workers_to_directories(subdirs)
    print("Worker assignments:")
    for directory, worker_id in sorted(worker_assignments.items()):
        print(f"  Worker {worker_id}: {directory}/")
    
    # Update CLAUDE.md with worker assignments
    update_claude_md_with_assignments(worker_assignments)
    
    # Create TODO.md files for each subdirectory
    for subdir in subdirs:
        subdir_path = base_dir / subdir
        if subdir_path.exists():
            todo_path = subdir_path / 'TODO.md'
            
            # Check if TODO.md already exists
            if todo_path.exists():
                print(f"TODO.md already exists in {subdir}/")
                continue
            
            # Get worker assignment for this directory
            assigned_worker = worker_assignments.get(subdir, "TBD")
            
            # Create TODO.md with relevant content
            todo_content = f"""# TODO List for {subdir}/

## Worker Assignment
**Worker {assigned_worker}**: Complete TDD tasks for {subdir}/ directory

## Test-Driven Development Tasks

This file contains TDD tasks extracted from the master todo list.
Each task follows the Red-Green-Refactor cycle:

1. Write function stub with type hints and comprehensive docstring
2. Write test that calls the actual (not-yet-implemented) callable 
3. Write additional test cases for edge cases and error conditions
4. Run all tests to confirm they fail (red phase)
5. Implement the method to make tests pass (green phase)
6. Refactor implementation while keeping tests passing (refactor phase)

## Tasks

"""
            
            # Add specific content for this subdirectory if found
            if subdir in sections:
                todo_content += sections[subdir]
            else:
                todo_content += f"- [ ] Review and analyze all Python files in {subdir}/ directory\n"
                todo_content += f"- [ ] Identify functions and classes that need TDD implementation\n"
                todo_content += f"- [ ] Create comprehensive test suites following TDD methodology\n"
                todo_content += f"- [ ] Implement missing functionality using Red-Green-Refactor cycle\n"
            
            # Write the TODO.md file
            with open(todo_path, 'w') as f:
                f.write(todo_content)
            
            print(f"Created TODO.md for {subdir}/ (assigned to Worker {assigned_worker})")
    
    print("Todo list splitting completed!")

if __name__ == "__main__":
    main()