#!/usr/bin/env python3
"""Test CLI program for MCP tool testing"""

import sys
import json
import argparse

def main():
    """Main function for test program"""
    parser = argparse.ArgumentParser(description="Test CLI program for MCP tool testing")
    parser.add_argument("--input", default="default", help="Input parameter for testing")
    parser.add_argument("--format", default="json", help="Output format")
    
    args = parser.parse_args()
    
    result = {
        "status": "success",
        "program": "test_program_name",
        "input": args.input,
        "format": args.format,
        "result": f"Processed input: {args.input}"
    }
    
    print(json.dumps(result))
    return 0

if __name__ == "__main__":
    sys.exit(main())
