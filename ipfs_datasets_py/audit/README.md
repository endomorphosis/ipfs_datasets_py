# Audit Logging and Reporting System

This directory contains the audit logging and reporting system for the IPFS Datasets Python project.

## Components

### Core Components

- **`audit_logger.py`**: Core audit logging functionality with the `AuditLogger` singleton
- **`audit_visualization.py`**: Metrics collection and visualization tools
- **`audit_reporting.py`**: Comprehensive reporting and analysis capabilities
- **`handlers.py`**: Various handlers for audit events (file, database, alerting)
- **`enhanced_security.py`**: Advanced security features for audit logging
- **`intrusion.py`**: Intrusion detection based on audit events

## Audit Reporting Features

The audit reporting system provides comprehensive analysis of audit data with the following features:

### Pattern Detection
- Authentication anomalies (brute force attempts, unusual login patterns)
- Access control anomalies (unusual resource access, unexpected modifications)
- System health indicators (error rates, critical events)
- Compliance violations and security breaches

### Risk Assessment
- Category-based risk scoring (authentication, access control, system integrity, compliance)
- Anomaly detection with severity rating
- Comprehensive risk trends and early warning indicators
- Weighted overall risk score calculation

### Compliance Analysis
- Framework-based compliance evaluation (GDPR, HIPAA, SOC2)
- Requirement-specific compliance checks
- Compliance status reporting with percentage scores
- Prioritized remediation recommendations

### Report Generation
- Multiple report types (security, compliance, operational, comprehensive)
- Various output formats (JSON, HTML, PDF)
- Executive summaries with actionable insights
- Technical details for specialized analysis

## Usage Examples

### Generating a Report

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger
from ipfs_datasets_py.audit.audit_visualization import setup_audit_visualization
from ipfs_datasets_py.audit.audit_reporting import (
    setup_audit_reporting, generate_comprehensive_audit_report
)

# Get the audit logger instance
audit_logger = AuditLogger.get_instance()

# Set up the visualization system to collect metrics
metrics, visualizer, _ = setup_audit_visualization(audit_logger)

# Generate a comprehensive report
report_path = generate_comprehensive_audit_report(
    audit_logger=audit_logger,
    metrics_aggregator=metrics,
    report_format='html',
    output_file='./audit_reports/comprehensive_report.html'
)

print(f"Report generated at: {report_path}")
```

### Command-Line Report Generation

Use the included `generate_audit_report.py` script to create reports from the command line:

```bash
# Generate a comprehensive HTML report
python generate_audit_report.py --type comprehensive --format html --output ./audit_reports/report.html

# Generate a security-focused JSON report
python generate_audit_report.py --type security --format json

# Generate a compliance report for the last 30 days
python generate_audit_report.py --type compliance --days 30
```

### Custom Analysis

For deeper customization, you can use the reporting components directly:

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger
from ipfs_datasets_py.audit.audit_visualization import AuditMetricsAggregator
from ipfs_datasets_py.audit.audit_reporting import (
    AuditPatternDetector, AuditComplianceAnalyzer, AuditReportGenerator
)

# Get metrics aggregator with collected audit data
metrics = AuditMetricsAggregator()

# Initialize pattern detector for security analysis
pattern_detector = AuditPatternDetector(metrics)
risk_scores = pattern_detector.calculate_risk_scores()
anomalies = pattern_detector.get_anomalies(threshold=0.7)

# Initialize compliance analyzer
compliance_analyzer = AuditComplianceAnalyzer(
    metrics_aggregator=metrics,
    pattern_detector=pattern_detector,
    frameworks=['gdpr', 'hipaa']  # Analyze only these frameworks
)
compliance_status = compliance_analyzer.analyze_compliance()
compliance_summary = compliance_analyzer.get_compliance_summary()

# Initialize report generator for custom reports
report_generator = AuditReportGenerator(
    metrics_aggregator=metrics,
    pattern_detector=pattern_detector,
    compliance_analyzer=compliance_analyzer,
    output_dir="./custom_reports"
)

# Generate a security report with detected anomalies
security_report = report_generator.generate_security_report()

# Export report in desired format
report_path = report_generator.export_report(
    report=security_report,
    format='json',
    output_file='./custom_reports/security_analysis.json'
)
```

## Report Types

The audit reporting system provides four main report types:

1. **Security Report**: Focuses on security anomalies, risk assessment, and security-related recommendations.
2. **Compliance Report**: Evaluates compliance status against various frameworks, highlighting gaps and remediation actions.
3. **Operational Report**: Analyzes system performance, error rates, and operational efficiency.
4. **Comprehensive Report**: Combines all report types into a complete audit assessment with executive summary.

## Output Formats

Reports can be generated in the following formats:

- **JSON**: Machine-readable format for further processing or API responses
- **HTML**: User-friendly format with styling and interactive elements
- **PDF**: Formal report format suitable for printing and distribution (requires WeasyPrint)

## Dependencies

- Required: Core Python libraries (built-in)
- Recommended for visualization: matplotlib, seaborn
- Recommended for HTML reports: jinja2
- Optional for PDF reports: weasyprint

## Configuration

The audit reporting system inherits its configuration from the audit logging system.
For customization, see the documentation in `audit_logger.py`.
