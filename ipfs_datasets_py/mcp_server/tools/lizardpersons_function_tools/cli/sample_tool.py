#!/usr/bin/env python3
"""Sample CLI tool for testing lizardpersons function tools"""

import sys
import argparse

def main():
    parser = argparse.ArgumentParser(description="Sample CLI tool")
    parser.add_argument("--input", help="Input parameter")
    parser.add_argument("--output", help="Output parameter")
    
    args = parser.parse_args()
    
    print(f"CLI tool executed with input: {args.input}, output: {args.output}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
