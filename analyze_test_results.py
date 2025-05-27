#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Test results analyzer for MCP server tools.
"""

import os
import sys
import json
import glob
import argparse
from datetime import datetime
from collections import defaultdict

def find_latest_report():
    reports = glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_tools_test_results_*.json"))
    if not reports:
        return None
    # Sort by modification time
    return max(reports, key=os.path.getmtime)

def analyze_report(report_path):
    with open(report_path, "r") as f:
        report = json.load(f)
    
    # Extract summary statistics
    summary = report["summary"]
    total = summary["total"]
    passed = summary["passed"]
    failed = summary["failed"]
    skipped = summary.get("skipped", 0)
    error = summary.get("error", 0)
    duration = summary["duration"]
    
    # Group tests by category
    categories = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 0})
    
    for test_path, tests in report["tests"].items():
        for test in tests:
            # Extract category from test name (e.g., test_web_archive_tools -> web_archive_tools)
            nodeid = test["nodeid"]
            parts = nodeid.split("::", 1)[0].split("/")[-1].replace(".py", "").split("_")
            if len(parts) >= 3 and parts[0] == "test":
                category = "_".join(parts[1:-1]) + "_tools"  # Reconstruct category name
            else:
                category = "other"
            
            # Update category statistics
            categories[category]["total"] += 1
            outcome = test.get("outcome", "error")
            categories[category][outcome] += 1
    
    # Format the report
    report_lines = []
    report_lines.append("MCP TOOLS TEST REPORT")
    report_lines.append("=" * 50)
    report_lines.append(f"Report date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"Report file: {os.path.basename(report_path)}")
    report_lines.append("")
    report_lines.append("SUMMARY")
    report_lines.append("-" * 50)
    report_lines.append(f"Total tests: {total}")
    report_lines.append(f"Passed: {passed} ({passed/total*100:.1f}%)")
    report_lines.append(f"Failed: {failed} ({failed/total*100:.1f}%)")
    report_lines.append(f"Skipped: {skipped} ({skipped/total*100:.1f}%)")
    report_lines.append(f"Error: {error} ({error/total*100:.1f}%)")
    report_lines.append(f"Time elapsed: {duration:.2f}s")
    report_lines.append("")
    report_lines.append("BREAKDOWN BY TOOL CATEGORY")
    report_lines.append("-" * 50)
    
    # Sort categories by name
    for category, stats in sorted(categories.items()):
        cat_total = stats["total"]
        cat_passed = stats["passed"]
        report_lines.append(f"{category}: {cat_passed}/{cat_total} passed ({cat_passed/cat_total*100:.1f}%)")
    
    # List failures
    if failed > 0:
        report_lines.append("")
        report_lines.append("FAILURES")
        report_lines.append("-" * 50)
        
        for test_path, tests in report["tests"].items():
            for test in tests:
                if test.get("outcome") == "failed":
                    report_lines.append(f"- {test['nodeid']}")
                    # Extract short error message
                    error_msg = str(test['call']['longrepr'])
                    error_lines = [line for line in error_msg.split("\n") if line.strip()]
                    if error_lines:
                        report_lines.append(f"  Error: {error_lines[-1].strip()}")
    
    return "\n".join(report_lines)

def main():
    parser = argparse.ArgumentParser(description="Analyze MCP tools test results")
    parser.add_argument("-r", "--report", help="Path to the test report JSON file")
    parser.add_argument("-o", "--output", help="Path to the output analysis file")
    args = parser.parse_args()
    
    report_path = args.report or find_latest_report()
    if not report_path:
        print("No test report found. Run the tests first.")
        return 1
    
    analysis = analyze_report(report_path)
    
    if args.output:
        with open(args.output, "w") as f:
            f.write(analysis)
        print(f"Analysis written to {args.output}")
    else:
        print(analysis)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())