#!/usr/bin/env python3
"""
Generate Comprehensive Audit Reports

This script generates audit reports based on collected audit events,
with options for different report types, formats, and output locations.

Usage:
    python generate_audit_report.py [options]

Options:
    --type TYPE         Report type: security, compliance, operational, or comprehensive (default)
    --format FORMAT     Output format: json, html, or pdf (requires WeasyPrint)
    --output FILE       Output file path (default: ./audit_reports/[type]_report_[timestamp].[format])
    --days DAYS         Number of days of audit data to include (default: 7)
    --include-graphics  Include visualization graphics in the report
    --help              Show this help message
"""

import os
import sys
import argparse
import datetime
from pathlib import Path

# Add parent directory to path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

try:
    from ipfs_datasets_py.audit.audit_logger import AuditLogger
    from ipfs_datasets_py.audit.audit_visualization import (
        AuditMetricsAggregator, AuditVisualizer, setup_audit_visualization
    )
    from ipfs_datasets_py.audit.audit_reporting import (
        AuditReportGenerator, setup_audit_reporting, generate_comprehensive_audit_report
    )
    MODULES_AVAILABLE = True
except ImportError as e:
    print(f"Required modules not available: {e}")
    MODULES_AVAILABLE = False
    sys.exit(1)

# Check visualization libraries
try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    import seaborn as sns
    VISUALIZATION_AVAILABLE = True
except ImportError:
    VISUALIZATION_AVAILABLE = False

# Check template engine for HTML reports
try:
    from jinja2 import Template
    TEMPLATE_ENGINE_AVAILABLE = True
except ImportError:
    TEMPLATE_ENGINE_AVAILABLE = False

# Check PDF export capability
try:
    from weasyprint import HTML
    PDF_EXPORT_AVAILABLE = True
except ImportError:
    PDF_EXPORT_AVAILABLE = False


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Generate audit reports")

    parser.add_argument(
        "--type",
        choices=["security", "compliance", "operational", "comprehensive"],
        default="comprehensive",
        help="Type of report to generate (default: comprehensive)"
    )

    parser.add_argument(
        "--format",
        choices=["json", "html", "pdf"],
        default="html",
        help="Output format (default: html)"
    )

    parser.add_argument(
        "--output",
        type=str,
        help="Output file path (default: ./audit_reports/[type]_report_[timestamp].[format])"
    )

    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days of audit data to include (default: 7)"
    )

    parser.add_argument(
        "--include-graphics",
        action="store_true",
        help="Include visualization graphics in the report"
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    # Check format requirements
    if args.format == "html" and not TEMPLATE_ENGINE_AVAILABLE:
        print("ERROR: HTML format requires Jinja2 template engine.")
        print("Install it with: pip install jinja2")
        sys.exit(1)

    if args.format == "pdf" and not PDF_EXPORT_AVAILABLE:
        print("ERROR: PDF format requires WeasyPrint.")
        print("Install it with: pip install weasyprint")
        sys.exit(1)

    if args.include_graphics and not VISUALIZATION_AVAILABLE:
        print("WARNING: Visualization libraries not available. Graphics will not be included.")
        print("Install them with: pip install matplotlib seaborn")
        args.include_graphics = False

    # Generate default output path if not provided
    if args.output is None:
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = os.path.join(os.path.dirname(__file__), "audit_reports")
        os.makedirs(output_dir, exist_ok=True)
        args.output = os.path.join(
            output_dir,
            f"{args.type}_report_{timestamp}.{args.format}"
        )

    # Get audit logger
    audit_logger = AuditLogger.get_instance()

    # Set up visualization components
    metrics, visualizer, _ = setup_audit_visualization(audit_logger)

    # Set up reporting components
    report_generator, pattern_detector, compliance_analyzer = setup_audit_reporting(
        audit_logger=audit_logger,
        metrics_aggregator=metrics,
        visualizer=visualizer,
        output_dir=os.path.dirname(args.output)
    )

    # Generate report based on type
    print(f"Generating {args.type} report in {args.format} format...")

    try:
        if args.type == "security":
            report = report_generator.generate_security_report()
        elif args.type == "compliance":
            report = report_generator.generate_compliance_report()
        elif args.type == "operational":
            report = report_generator.generate_operational_report()
        else:  # comprehensive is default
            report = report_generator.generate_comprehensive_report()

        # Export report
        output_path = report_generator.export_report(
            report=report,
            format=args.format,
            output_file=args.output
        )

        print(f"Report successfully generated at: {output_path}")

    except Exception as e:
        print(f"Error generating report: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
