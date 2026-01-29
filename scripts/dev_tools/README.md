# Adhoc Tools Directory

## Overview

This directory contains utility scripts and tools created on-the-fly by Claude Code to handle specific tasks and automation needs within the project. These tools are designed to be lightweight, purpose-built solutions for immediate project requirements.

## Philosophy

Adhoc tools are created when:
- A specific automation task needs to be accomplished quickly
- Manual processes would be time-consuming or error-prone
- A one-time or infrequent operation requires a structured approach
- Project maintenance tasks need standardization

## Tool Standards

All tools in this directory should follow these guidelines:

### 1. Argument Parsing
Every tool should use `argparse` for command-line argument handling:

```python
import argparse

def parse_arguments():
    parser = argparse.ArgumentParser(description="Tool description here")
    parser.add_argument('--input', type=str, help='Input parameter description')
    parser.add_argument('--output', type=str, help='Output parameter description')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose output')
    return parser.parse_args()

def main():
    args = parse_arguments()
    # Tool logic here
    
if __name__ == "__main__":
    main()
```

### 2. Documentation
Each tool should include:
- Clear docstring explaining purpose and usage
- Comments for complex logic
- Help text for all arguments
- Example usage in the docstring

### 3. Error Handling
Tools should handle common error scenarios:
- Missing input files
- Invalid arguments
- Permission issues
- Network failures (if applicable)

### 4. Output
Tools should provide clear feedback:
- Progress indicators for long-running operations
- Success/failure messages
- Verbose mode for debugging

## Current Tools

### split_todo_script.py
**Purpose**: Splits the master_todo_list.md into separate TODO.md files for each subdirectory
**Usage**: `python split_todo_script.py [options]`
**Created for**: Worker 10 assignment to organize massive TODO list

### update_todo_workers.py  
**Purpose**: Updates existing TODO.md files with worker assignments
**Usage**: `python update_todo_workers.py [options]`
**Created for**: Adding worker assignments to TODO files after splitting

### find_documentation.py
**Purpose**: Find all TODO.md and CHANGELOG.md files in a directory tree with modification timestamps
**Usage**: `python find_documentation.py --directory /path/to/search [options]`
**Created for**: Monitoring and tracking TODO and CHANGELOG files across project structure

## Creating New Adhoc Tools

When Claude Code creates new adhoc tools, they should:

1. **Follow naming conventions**: Use descriptive names with underscores
2. **Include creation context**: Document why the tool was created
3. **Be self-contained**: Minimize external dependencies
4. **Include examples**: Show how to use the tool
5. **Handle edge cases**: Consider what could go wrong

### Template for New Tools

```python
#!/usr/bin/env python3
"""
Brief description of what this tool does.

This is an adhoc tool created on-the-fly by Claude Code to handle [specific task].
Created for: [Worker X assignment / specific need]

Usage:
    python tool_name.py --input file.txt --output result.txt
    
Examples:
    # Basic usage
    python tool_name.py --input data.json
    
    # With verbose output
    python tool_name.py --input data.json --verbose
"""

import argparse
import sys
from pathlib import Path

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Tool description",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    # Add arguments here
    parser.add_argument('--input', type=str, required=True,
                       help='Input file or parameter')
    parser.add_argument('--output', type=str,
                       help='Output file or parameter')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose output')
    
    return parser.parse_args()

def main():
    """Main function."""
    args = parse_arguments()
    
    try:
        # Tool logic here
        if args.verbose:
            print("Starting processing...")
            
        # Actual work
        result = do_work(args.input)
        
        if args.output:
            save_result(result, args.output)
        else:
            print(result)
            
        if args.verbose:
            print("Processing completed successfully!")
            
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

def do_work(input_param):
    """Core tool functionality."""
    # Implementation here
    pass

def save_result(result, output_path):
    """Save result to file."""
    # Implementation here
    pass

if __name__ == "__main__":
    main()
```

## Best Practices

1. **Keep it simple**: Adhoc tools should solve one problem well
2. **Make it reusable**: Even though it's adhoc, someone might need it again
3. **Test edge cases**: Consider what happens with empty inputs, missing files, etc.
4. **Log operations**: For tools that modify files, log what was changed
5. **Dry run option**: For destructive operations, provide a preview mode

## Integration with Project Workflow

Adhoc tools complement the main project by:
- Automating repetitive maintenance tasks
- Providing quick solutions for urgent needs
- Facilitating project reorganization and cleanup
- Supporting development workflow improvements

## Maintenance

- Review tools periodically to see if they should become permanent utilities
- Remove tools that are no longer needed
- Update tools when project structure changes
- Document any dependencies or requirements

## Security Considerations

- Never include secrets or credentials in adhoc tools
- Validate all inputs to prevent injection attacks
- Use secure file operations (proper permissions)
- Avoid executing arbitrary code from user input

---

**Note**: These tools are created dynamically by Claude Code to meet immediate project needs. They represent quick, practical solutions rather than polished, long-term software components.