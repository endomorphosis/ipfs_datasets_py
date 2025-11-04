#!/usr/bin/env python3
"""
Generate Copilot instruction from failure analysis JSON.

This script reads a failure analysis JSON file and generates a structured
instruction for GitHub Copilot to implement fixes.
"""

import json
import sys
import argparse


def generate_instruction(analysis_file):
    """Generate Copilot instruction from failure analysis."""
    try:
        with open(analysis_file) as f:
            data = json.load(f)
        
        error_type = data.get('error_type', 'Unknown')
        root_cause = data.get('root_cause', 'Not identified')
        fix_confidence = data.get('fix_confidence', 0)
        recommendations = data.get('recommendations', [])
        
        # Format recommendations
        if recommendations:
            rec_lines = [f'  {i+1}. {rec}' for i, rec in enumerate(recommendations)]
            rec_text = '\n'.join(rec_lines)
        else:
            rec_text = '  No specific recommendations'
        
        instruction = f"""Please analyze and fix the workflow failure detected.

**Error Analysis:**
- Error Type: {error_type}
- Root Cause: {root_cause}
- Fix Confidence: {fix_confidence}%

**Recommended Actions:**
{rec_text}

**Instructions:**
1. Review the error analysis and recommendations above
2. Implement minimal, surgical fixes to address the root cause
3. Ensure all tests pass after your changes
4. Follow existing code patterns and conventions
5. Document any significant changes

Focus on making clean, maintainable changes that directly address the issue."""
        
        print(instruction)
        return 0
        
    except FileNotFoundError:
        print('Please analyze and fix the workflow failure based on the PR description and logs.', file=sys.stderr)
        print('Please analyze and fix the workflow failure based on the PR description and logs.')
        return 1
    except Exception as e:
        print(f'Error generating instruction: {e}', file=sys.stderr)
        print('Please analyze and fix the workflow failure based on the PR description and logs.')
        return 1


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Generate Copilot instruction from failure analysis')
    parser.add_argument('analysis_file', help='Path to failure analysis JSON file')
    
    args = parser.parse_args()
    
    return generate_instruction(args.analysis_file)


if __name__ == '__main__':
    sys.exit(main())
