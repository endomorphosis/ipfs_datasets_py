# Audit Reporting and Analysis

This guide explains how to use the audit reporting and analysis capabilities in the IPFS Datasets Python project. These features enable you to generate comprehensive reports with security insights, compliance status, and operational metrics based on collected audit events.

## Overview

The audit reporting system builds upon the existing audit logging and visualization capabilities, adding:

1. **Pattern Detection**: Identifies security anomalies, unusual access patterns, and potential compliance issues
2. **Risk Assessment**: Evaluates and scores security risks across various categories
3. **Compliance Analysis**: Evaluates compliance status against common frameworks (GDPR, HIPAA, SOC2)
4. **Report Generation**: Creates comprehensive reports with actionable insights

## Getting Started

### Basic Usage

The simplest way to generate an audit report is using the `generate_comprehensive_audit_report` function:

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger
from ipfs_datasets_py.audit.audit_reporting import generate_comprehensive_audit_report

# Get the audit logger instance
audit_logger = AuditLogger.get_instance()

# Generate a comprehensive HTML report
report_path = generate_comprehensive_audit_report(
    audit_logger=audit_logger,
    report_format='html',
    output_file='./audit_reports/comprehensive_report.html'
)

print(f"Report generated at: {report_path}")
```

### Using the Command Line Tool

You can also use the `generate_audit_report.py` script to create reports from the command line:

```bash
# Generate a comprehensive HTML report
python generate_audit_report.py --type comprehensive --format html

# Generate a security-focused JSON report
python generate_audit_report.py --type security --format json

# Generate a compliance report with a specific output path
python generate_audit_report.py --type compliance --format html --output ./reports/compliance.html
```

## Report Types

The audit reporting system provides four main report types:

### 1. Security Report

Focuses on security-related insights and anomalies:

```python
from ipfs_datasets_py.audit.audit_reporting import setup_audit_reporting

# Set up reporting components
report_generator, _, _ = setup_audit_reporting(audit_logger)

# Generate security report
security_report = report_generator.generate_security_report()

# Export as JSON
report_generator.export_report(
    report=security_report,
    format='json',
    output_file='./security_report.json'
)
```

Security reports include:
- Risk scores across different security categories
- Detected anomalies and potential threats
- Authentication-related issues
- Security recommendations

### 2. Compliance Report

Evaluates compliance status against common frameworks:

```python
# Generate compliance report
compliance_report = report_generator.generate_compliance_report()

# Export as HTML
report_generator.export_report(
    report=compliance_report,
    format='html',
    output_file='./compliance_report.html'
)
```

Compliance reports include:
- Compliance status by framework (GDPR, HIPAA, SOC2)
- Requirement-specific compliance checks
- Top compliance issues to address
- Compliance recommendations

### 3. Operational Report

Focuses on system performance and operational metrics:

```python
# Generate operational report
operational_report = report_generator.generate_operational_report()

# Export as HTML
report_generator.export_report(
    report=operational_report,
    format='html',
    output_file='./operational_report.html'
)
```

Operational reports include:
- Event distribution by category and level
- Performance metrics for operations
- Error rates and slowest operations
- Operational recommendations

### 4. Comprehensive Report

Combines all report types into one complete assessment:

```python
# Generate comprehensive report
comprehensive_report = report_generator.generate_comprehensive_report()

# Export as HTML
report_generator.export_report(
    report=comprehensive_report,
    format='html',
    output_file='./comprehensive_report.html'
)
```

Comprehensive reports include:
- Executive summary with key metrics
- Security assessment
- Compliance status
- Operational metrics
- Top recommendations across all areas

## Advanced Usage

### Pattern Detection

You can use the pattern detection capabilities directly:

```python
from ipfs_datasets_py.audit.audit_visualization import AuditMetricsAggregator
from ipfs_datasets_py.audit.audit_reporting import AuditPatternDetector

# Get metrics aggregator with audit data
metrics = AuditMetricsAggregator()

# Initialize pattern detector
detector = AuditPatternDetector(metrics)

# Detect authentication anomalies
auth_patterns = detector.detect_authentication_patterns()
print(f"Detected {len(auth_patterns)} authentication anomalies")

# Calculate risk scores
risk_scores = detector.calculate_risk_scores()
print(f"Overall risk score: {risk_scores['overall']}")

# Get high-risk anomalies
anomalies = detector.get_anomalies(threshold=0.7)
for anomaly in anomalies:
    print(f"High-risk anomaly: {anomaly['type']} - {anomaly.get('recommendation', '')}")
```

### Compliance Analysis

You can perform detailed compliance analysis:

```python
from ipfs_datasets_py.audit.audit_reporting import AuditComplianceAnalyzer

# Initialize compliance analyzer
analyzer = AuditComplianceAnalyzer(
    metrics_aggregator=metrics,
    frameworks=['gdpr', 'hipaa']  # Analyze specific frameworks
)

# Analyze compliance
compliance_status = analyzer.analyze_compliance()

# Get compliance summary
summary = analyzer.get_compliance_summary()
print(f"Overall compliance: {summary['overall_compliance_percentage']:.1f}%")

# Review top issues
for issue in summary['top_issues']:
    print(f"Compliance issue: {issue['requirement']} - {issue['recommendation']}")
```

## Customizing Reports

You can customize the reporting process in several ways:

### Custom Report Generator

```python
from ipfs_datasets_py.audit.audit_reporting import AuditReportGenerator

# Initialize custom report generator
report_generator = AuditReportGenerator(
    metrics_aggregator=metrics,
    pattern_detector=detector,
    compliance_analyzer=analyzer,
    output_dir="./custom_reports"
)

# Generate reports with the custom generator
report = report_generator.generate_security_report()
```

### HTML Templates

The reporting system uses HTML templates for rendering reports. You can customize these templates by placing your own versions in:

```
ipfs_datasets_py/audit/templates/
```

Available templates:
- `comprehensive_report.html`
- `security_report.html`
- `compliance_report.html`
- `operational_report.html`

## Export Formats

Reports can be exported in the following formats:

- **JSON**: Machine-readable format for further processing or API responses
- **HTML**: User-friendly format with styling and interactive elements
- **PDF**: Formal report format suitable for printing and distribution (requires WeasyPrint)

### PDF Export

To enable PDF export, install WeasyPrint:

```bash
pip install weasyprint
```

Then use the PDF format:

```python
# Export report as PDF
report_generator.export_report(
    report=comprehensive_report,
    format='pdf',
    output_file='./audit_report.pdf'
)
```

## Integration with Other Components

### Integration with Visualization

The reporting system integrates with the audit visualization components to include charts and graphs in HTML reports:

```python
from ipfs_datasets_py.audit.audit_visualization import (
    AuditVisualizer, setup_audit_visualization
)

# Set up visualization
metrics, visualizer, _ = setup_audit_visualization(audit_logger)

# Set up reporting with visualization
report_generator, _, _ = setup_audit_reporting(
    audit_logger=audit_logger,
    metrics_aggregator=metrics,
    visualizer=visualizer
)
```

### Integration with Monitoring Dashboard

You can integrate audit reports into your monitoring dashboard:

```python
from ipfs_datasets_py.admin_dashboard import AdminDashboard

# Initialize dashboard
dashboard = AdminDashboard()

# Add reporting panel
dashboard.add_audit_reporting_panel(report_generator)

# Start dashboard
dashboard.start()
```

## Complete Example

Here's a complete example of using the audit reporting system:

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditEvent, AuditCategory, AuditLevel
from ipfs_datasets_py.audit.audit_visualization import setup_audit_visualization
from ipfs_datasets_py.audit.audit_reporting import setup_audit_reporting

# Get audit logger
audit_logger = AuditLogger.get_instance()

# Set up visualization
metrics, visualizer, _ = setup_audit_visualization(audit_logger)

# Set up reporting
report_generator, detector, analyzer = setup_audit_reporting(
    audit_logger=audit_logger,
    metrics_aggregator=metrics,
    visualizer=visualizer
)

# Generate reports
security_report = report_generator.generate_security_report()
compliance_report = report_generator.generate_compliance_report()
operational_report = report_generator.generate_operational_report()
comprehensive_report = report_generator.generate_comprehensive_report()

# Export reports in different formats
report_generator.export_report(
    report=security_report,
    format='json',
    output_file='./reports/security_report.json'
)

report_generator.export_report(
    report=compliance_report,
    format='html',
    output_file='./reports/compliance_report.html'
)

report_generator.export_report(
    report=comprehensive_report,
    format='html',
    output_file='./reports/comprehensive_report.html'
)
```

## Best Practices

1. **Regular Reports**: Generate reports on a regular schedule (daily, weekly) for ongoing monitoring
2. **Incident Reports**: Create security reports immediately after detecting suspicious activity
3. **Compliance Reviews**: Run compliance reports before audits or regulatory reviews
4. **Report Archiving**: Archive reports for historical comparison and trend analysis
5. **Integration**: Incorporate reports into your security and compliance workflows

## Conclusion

The audit reporting system provides powerful tools for analyzing audit data and generating actionable insights. Whether you're monitoring security, ensuring compliance, or optimizing operations, these reports can help you understand your system's status and make informed decisions.