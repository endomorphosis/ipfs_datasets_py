#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Master test generator for all MCP server tools.
This script runs all the test generators to create a complete test suite.
"""

import os
import sys
import importlib
import subprocess
from pathlib import Path

# List of test generator scripts
TEST_GENERATORS = [
    "test_generator_for_web_archive_tools.py",
    "test_generator_for_security_tools.py",
    "test_generator_for_vector_tools.py",
    "test_generator_for_graph_tools.py",
    "test_generator_for_provenance_tools.py",
    "test_generator_for_ipfs_tools.py",
    "test_generator_for_audit_tools.py",
    "test_generator_for_dataset_tools.py"
]

def run_test_generator(generator_script):
    """Run a test generator script and return its output."""
    print(f"Running {generator_script}...")
    try:
        result = subprocess.run(
            [sys.executable, generator_script],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True,
            text=True,
            check=True
        )
        print(f"  Success: {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  Error: {e}")
        print(f"  Output: {e.stdout}")
        print(f"  Error output: {e.stderr}")
        return False

def update_init_file():
    """Update the __init__.py file in the test directory to import all test modules."""
    test_dir = Path(os.path.dirname(os.path.abspath(__file__))) / "test"
    init_file = test_dir / "__init__.py"

    # Get all test files
    test_files = [f.stem for f in test_dir.glob("test_*.py")]

    # Create imports for __init__.py
    imports = ["# -*- coding: utf-8 -*-", ""]
    imports.append('"""')
    imports.append("Auto-generated test suite for MCP server tools.")
    imports.append('"""')
    imports.append("")

    for test_file in sorted(test_files):
        imports.append(f"from . import {test_file}")

    # Write the __init__.py file
    with open(init_file, "w") as f:
        f.write("\n".join(imports))

    print(f"Updated {init_file} with {len(test_files)} test modules")
    return True

def create_pytest_config():
    """Create a pytest.ini file with appropriate configuration."""
    pytest_ini = Path(os.path.dirname(os.path.abspath(__file__))) / "pytest.ini"

    config = [
        "[pytest]",
        "testpaths = test",
        "python_files = test_*.py",
        "python_classes = Test*",
        "python_functions = test_*",
        "asyncio_mode = auto",
        "filterwarnings =",
        "    ignore::DeprecationWarning",
        "    ignore::UserWarning"
    ]

    with open(pytest_ini, "w") as f:
        f.write("\n".join(config))

    print(f"Created {pytest_ini}")
    return True

def create_comprehensive_test_runner():
    """Create a script to run all tests comprehensively."""
    test_runner = Path(os.path.dirname(os.path.abspath(__file__))) / "run_all_tests.py"

    content = [
        "#!/usr/bin/env python",
        "# -*- coding: utf-8 -*-",
        "",
        '"""',
        "Comprehensive test runner for MCP server tools.",
        '"""',
        "",
        "import os",
        "import sys",
        "import pytest",
        "import json",
        "from datetime import datetime",
        "",
        "def main():",
        "    # Run all tests",
        "    print(\"Running all MCP tools tests...\")",
        "    timestamp = datetime.now().strftime(\"%Y%m%d_%H%M%S\")",
        "    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f\"mcp_tools_test_results_{timestamp}.json\")",
        "    ",
        "    # Run pytest with JSON report",
        "    exit_code = pytest.main([",
        "        \"-v\",",
        "        \"--junitxml=test-results.xml\",",
        "        \"--json-report\",",
        "        f\"--json-report-file={report_path}\",",
        "        \"test/\"",
        "    ])",
        "    ",
        "    # Load and print test summary",
        "    try:",
        "        with open(report_path, \"r\") as f:",
        "            report = json.load(f)",
        "            ",
        "        summary = report[\"summary\"]",
        "        print(\"\\n\" + \"=\" * 50)",
        "        print(\"MCP TOOLS TEST SUMMARY\")",
        "        print(\"=\" * 50)",
        "        print(f\"Total tests: {summary['total']}\")",
        "        print(f\"Passed: {summary['passed']}\")",
        "        print(f\"Failed: {summary['failed']}\")",
        "        print(f\"Skipped: {summary.get('skipped', 0)}\")",
        "        print(f\"Error: {summary.get('error', 0)}\")",
        "        print(f\"Time elapsed: {summary['duration']}s\")",
        "        print(\"=\" * 50)",
        "        ",
        "        # Print failures",
        "        if summary['failed'] > 0:",
        "            print(\"\\nFAILURES:\")",
        "            for test_path, tests in report[\"tests\"].items():",
        "                for test in tests:",
        "                    if test.get(\"outcome\") == \"failed\":",
        "                        print(f\"\\n{test['nodeid']}\")",
        "                        print(f\"  {test['call']['longrepr']}\")",
        "    except Exception as e:",
        "        print(f\"Error reading test report: {e}\")",
        "    ",
        "    return exit_code",
        "",
        "if __name__ == \"__main__\":",
        "    sys.exit(main())"
    ]

    with open(test_runner, "w") as f:
        f.write("\n".join(content))

    # Make the file executable
    os.chmod(test_runner, 0o755)

    print(f"Created {test_runner}")
    return True

def create_test_report_analyzer():
    """Create a script to analyze test results and generate a report."""
    report_analyzer = Path(os.path.dirname(os.path.abspath(__file__))) / "analyze_test_results.py"

    content = [
        "#!/usr/bin/env python",
        "# -*- coding: utf-8 -*-",
        "",
        '"""',
        "Test results analyzer for MCP server tools.",
        '"""',
        "",
        "import os",
        "import sys",
        "import json",
        "import glob",
        "import argparse",
        "from datetime import datetime",
        "from collections import defaultdict",
        "",
        "def find_latest_report():",
        "    reports = glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), \"mcp_tools_test_results_*.json\"))",
        "    if not reports:",
        "        return None",
        "    # Sort by modification time",
        "    return max(reports, key=os.path.getmtime)",
        "",
        "def analyze_report(report_path):",
        "    with open(report_path, \"r\") as f:",
        "        report = json.load(f)",
        "    ",
        "    # Extract summary statistics",
        "    summary = report[\"summary\"]",
        "    total = summary[\"total\"]",
        "    passed = summary[\"passed\"]",
        "    failed = summary[\"failed\"]",
        "    skipped = summary.get(\"skipped\", 0)",
        "    error = summary.get(\"error\", 0)",
        "    duration = summary[\"duration\"]",
        "    ",
        "    # Group tests by category",
        "    categories = defaultdict(lambda: {\"total\": 0, \"passed\": 0, \"failed\": 0, \"skipped\": 0, \"error\": 0})",
        "    ",
        "    for test_path, tests in report[\"tests\"].items():",
        "        for test in tests:",
        "            # Extract category from test name (e.g., test_web_archive_tools -> web_archive_tools)",
        "            nodeid = test[\"nodeid\"]",
        "            parts = nodeid.split(\"::\", 1)[0].split(\"/\")[-1].replace(\".py\", \"\").split(\"_\")",
        "            if len(parts) >= 3 and parts[0] == \"test\":",
        "                category = \"_\".join(parts[1:-1]) + \"_tools\"  # Reconstruct category name",
        "            else:",
        "                category = \"other\"",
        "            ",
        "            # Update category statistics",
        "            categories[category][\"total\"] += 1",
        "            outcome = test.get(\"outcome\", \"error\")",
        "            categories[category][outcome] += 1",
        "    ",
        "    # Format the report",
        "    report_lines = []",
        "    report_lines.append(\"MCP TOOLS TEST REPORT\")",
        "    report_lines.append(\"=\" * 50)",
        "    report_lines.append(f\"Report date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\")",
        "    report_lines.append(f\"Report file: {os.path.basename(report_path)}\")",
        "    report_lines.append(\"\")",
        "    report_lines.append(\"SUMMARY\")",
        "    report_lines.append(\"-\" * 50)",
        "    report_lines.append(f\"Total tests: {total}\")",
        "    report_lines.append(f\"Passed: {passed} ({passed/total*100:.1f}%)\")",
        "    report_lines.append(f\"Failed: {failed} ({failed/total*100:.1f}%)\")",
        "    report_lines.append(f\"Skipped: {skipped} ({skipped/total*100:.1f}%)\")",
        "    report_lines.append(f\"Error: {error} ({error/total*100:.1f}%)\")",
        "    report_lines.append(f\"Time elapsed: {duration:.2f}s\")",
        "    report_lines.append(\"\")",
        "    report_lines.append(\"BREAKDOWN BY TOOL CATEGORY\")",
        "    report_lines.append(\"-\" * 50)",
        "    ",
        "    # Sort categories by name",
        "    for category, stats in sorted(categories.items()):",
        "        cat_total = stats[\"total\"]",
        "        cat_passed = stats[\"passed\"]",
        "        report_lines.append(f\"{category}: {cat_passed}/{cat_total} passed ({cat_passed/cat_total*100:.1f}%)\")",
        "    ",
        "    # List failures",
        "    if failed > 0:",
        "        report_lines.append(\"\")",
        "        report_lines.append(\"FAILURES\")",
        "        report_lines.append(\"-\" * 50)",
        "        ",
        "        for test_path, tests in report[\"tests\"].items():",
        "            for test in tests:",
        "                if test.get(\"outcome\") == \"failed\":",
        "                    report_lines.append(f\"- {test['nodeid']}\")",
        "                    # Extract short error message",
        "                    error_msg = str(test['call']['longrepr'])",
        "                    error_lines = [line for line in error_msg.split(\"\\n\") if line.strip()]",
        "                    if error_lines:",
        "                        report_lines.append(f\"  Error: {error_lines[-1].strip()}\")",
        "    ",
        "    return \"\\n\".join(report_lines)",
        "",
        "def main():",
        "    parser = argparse.ArgumentParser(description=\"Analyze MCP tools test results\")",
        "    parser.add_argument(\"-r\", \"--report\", help=\"Path to the test report JSON file\")",
        "    parser.add_argument(\"-o\", \"--output\", help=\"Path to the output analysis file\")",
        "    args = parser.parse_args()",
        "    ",
        "    report_path = args.report or find_latest_report()",
        "    if not report_path:",
        "        print(\"No test report found. Run the tests first.\")",
        "        return 1",
        "    ",
        "    analysis = analyze_report(report_path)",
        "    ",
        "    if args.output:",
        "        with open(args.output, \"w\") as f:",
        "            f.write(analysis)",
        "        print(f\"Analysis written to {args.output}\")",
        "    else:",
        "        print(analysis)",
        "    ",
        "    return 0",
        "",
        "if __name__ == \"__main__\":",
        "    sys.exit(main())"
    ]

    with open(report_analyzer, "w") as f:
        f.write("\n".join(content))

    # Make the file executable
    os.chmod(report_analyzer, 0o755)

    print(f"Created {report_analyzer}")
    return True

def main():
    """Run all test generators and create supporting files."""
    print("=== MCP TOOLS TEST GENERATOR ===")

    # Create test directory if it doesn't exist
    test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
    os.makedirs(test_dir, exist_ok=True)

    # Run all test generators
    successes = 0
    for generator in TEST_GENERATORS:
        if run_test_generator(generator):
            successes += 1

    print(f"\nCompleted {successes}/{len(TEST_GENERATORS)} test generators")

    # Update the __init__.py file
    update_init_file()

    # Create pytest.ini
    create_pytest_config()

    # Create comprehensive test runner
    create_comprehensive_test_runner()

    # Create test report analyzer
    create_test_report_analyzer()

    print("\nTest suite generation complete!")
    print("To run all tests, use: python run_all_tests.py")
    print("To analyze test results, use: python analyze_test_results.py")

if __name__ == "__main__":
    main()
