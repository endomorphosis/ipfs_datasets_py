# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/audit/audit_reporting.py'

Files last updated: 1748635923.4213796

Stub file last updated: 2025-07-07 02:14:36

## AuditComplianceAnalyzer

```python
class AuditComplianceAnalyzer:
    """
    Analyzes audit data for compliance with various standards and regulations.

This class evaluates audit events against common compliance frameworks
and generates reports on the system's compliance status.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## AuditPatternDetector

```python
class AuditPatternDetector:
    """
    Analyzes audit events to detect patterns, anomalies, and potential security issues.

This class uses statistical methods to identify unusual patterns in audit data,
such as brute force attempts, privilege escalation, data exfiltration patterns,
or unusual system access.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## AuditReportGenerator

```python
class AuditReportGenerator:
    """
    Generates comprehensive audit reports with insights and recommendations.

This class combines data from the metrics aggregator, pattern detector,
and compliance analyzer to create actionable audit reports.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, metrics_aggregator: AuditMetricsAggregator):
    """
    Initialize the pattern detector.

Args:
    metrics_aggregator: The metrics aggregator containing audit data
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditPatternDetector

## __init__

```python
def __init__(self, metrics_aggregator: AuditMetricsAggregator, pattern_detector: Optional[AuditPatternDetector] = None, frameworks: Optional[List[str]] = None):
    """
    Initialize the compliance analyzer.

Args:
    metrics_aggregator: The metrics aggregator containing audit data
    pattern_detector: Optional pattern detector for risk assessment
    frameworks: List of compliance frameworks to analyze against
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditComplianceAnalyzer

## __init__

```python
def __init__(self, metrics_aggregator: AuditMetricsAggregator, visualizer: Optional[AuditVisualizer] = None, pattern_detector: Optional[AuditPatternDetector] = None, compliance_analyzer: Optional[AuditComplianceAnalyzer] = None, output_dir: str = "./audit_reports"):
    """
    Initialize the report generator.

Args:
    metrics_aggregator: The metrics aggregator containing audit data
    visualizer: Optional visualizer for creating charts
    pattern_detector: Optional pattern detector for risk assessment
    compliance_analyzer: Optional compliance analyzer for compliance status
    output_dir: Directory for report output files
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## _generate_compliance_recommendations

```python
def _generate_compliance_recommendations(self) -> List[str]:
    """
    Generate compliance recommendations based on audit data.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## _generate_operational_recommendations

```python
def _generate_operational_recommendations(self) -> List[str]:
    """
    Generate operational recommendations based on audit data.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## _generate_security_recommendations

```python
def _generate_security_recommendations(self) -> List[str]:
    """
    Generate security recommendations based on audit data.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## _generic_compliance_check

```python
def _generic_compliance_check(self, framework_id: str, requirement_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Perform a generic compliance check based on audit events.

Args:
    framework_id: ID of the compliance framework
    requirement_id: ID of the specific requirement

Returns:
    Tuple of (compliance_status, details)
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditComplianceAnalyzer

## _get_critical_findings

```python
def _get_critical_findings(self) -> List[Dict[str, Any]]:
    """
    Get critical findings across all report types.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## _get_error_rates

```python
def _get_error_rates(self) -> Dict[str, Any]:
    """
    Get error rates by category and action.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## _get_key_metrics

```python
def _get_key_metrics(self) -> Dict[str, Any]:
    """
    Get key metrics for executive summary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## _get_resource_usage

```python
def _get_resource_usage(self) -> Dict[str, Any]:
    """
    Get resource usage metrics (placeholder).
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## _get_risk_factors

```python
def _get_risk_factors(self) -> List[Dict[str, Any]]:
    """
    Get the factors contributing to the risk score.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## _get_risk_trends

```python
def _get_risk_trends(self) -> Dict[str, Any]:
    """
    Get trends in risk factors over time.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## _get_slowest_operations

```python
def _get_slowest_operations(self, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Get the slowest operations by average duration.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## _get_top_compliance_issues

```python
def _get_top_compliance_issues(self, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Get the top compliance issues to address.

Args:
    limit: Maximum number of issues to return

Returns:
    List of top compliance issues
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditComplianceAnalyzer

## _get_top_recommendations

```python
def _get_top_recommendations(self) -> List[Dict[str, Any]]:
    """
    Get top recommendations across all report types.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## _get_top_resources

```python
def _get_top_resources(self, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Get the most accessed resources by access count.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## _get_top_security_events

```python
def _get_top_security_events(self, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Get the top security-related events.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## _get_top_users

```python
def _get_top_users(self, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Get the most active users by event count.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## analyze_compliance

```python
def analyze_compliance(self) -> Dict[str, Any]:
    """
    Analyze audit data for compliance with selected frameworks.

Returns:
    Compliance status report for each framework
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditComplianceAnalyzer

## calculate_risk_scores

```python
def calculate_risk_scores(self) -> Dict[str, float]:
    """
    Calculate risk scores based on detected patterns.

Returns:
    Dictionary of risk categories and their scores (0-1)
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditPatternDetector

## check_gdpr_data_access_logging

```python
def check_gdpr_data_access_logging(self) -> Tuple[bool, Dict[str, Any]]:
    """
    Check GDPR data access logging compliance.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditComplianceAnalyzer

## check_hipaa_audit_controls

```python
def check_hipaa_audit_controls(self) -> Tuple[bool, Dict[str, Any]]:
    """
    Check HIPAA audit controls compliance.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditComplianceAnalyzer

## check_soc2_monitoring

```python
def check_soc2_monitoring(self) -> Tuple[bool, Dict[str, Any]]:
    """
    Check SOC2 monitoring compliance.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditComplianceAnalyzer

## detect_access_patterns

```python
def detect_access_patterns(self) -> List[Dict[str, Any]]:
    """
    Detect patterns in resource access events.

Returns:
    List of detected patterns with details
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditPatternDetector

## detect_authentication_patterns

```python
def detect_authentication_patterns(self) -> List[Dict[str, Any]]:
    """
    Detect patterns in authentication events.

Returns:
    List of detected patterns with details
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditPatternDetector

## detect_compliance_patterns

```python
def detect_compliance_patterns(self) -> List[Dict[str, Any]]:
    """
    Detect patterns related to compliance requirements.

Returns:
    List of detected patterns with details
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditPatternDetector

## detect_system_patterns

```python
def detect_system_patterns(self) -> List[Dict[str, Any]]:
    """
    Detect patterns in system events.

Returns:
    List of detected patterns with details
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditPatternDetector

## export_report

```python
def export_report(self, report: Dict[str, Any], format: str = "json", output_file: Optional[str] = None) -> str:
    """
    Export a report in the specified format.

Args:
    report: The report data structure to export
    format: Format to export ('json', 'html', 'pdf')
    output_file: Optional output file path

Returns:
    Path to the exported report file
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## generate_compliance_report

```python
def generate_compliance_report(self) -> Dict[str, Any]:
    """
    Generate a compliance-focused audit report.

Returns:
    Compliance report data structure
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## generate_comprehensive_audit_report

```python
def generate_comprehensive_audit_report(output_file: Optional[str] = None, audit_logger: Optional[AuditLogger] = None, metrics_aggregator: Optional[AuditMetricsAggregator] = None, report_format: str = "html", include_security: bool = True, include_compliance: bool = True, include_operational: bool = True) -> str:
    """
    Generate a comprehensive audit report with security, compliance, and operational insights.

Args:
    output_file: Path for the output report file
    audit_logger: The audit logger instance (will use global instance if None)
    metrics_aggregator: Optional existing metrics aggregator
    report_format: Format for the report ('json', 'html', 'pdf')
    include_security: Whether to include security analysis
    include_compliance: Whether to include compliance analysis
    include_operational: Whether to include operational analysis

Returns:
    Path to the generated report file
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## generate_comprehensive_report

```python
def generate_comprehensive_report(self) -> Dict[str, Any]:
    """
    Generate a comprehensive audit report combining security, compliance, and operations.

Returns:
    Comprehensive report data structure
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## generate_operational_report

```python
def generate_operational_report(self) -> Dict[str, Any]:
    """
    Generate an operations-focused audit report.

Returns:
    Operational report data structure
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## generate_security_report

```python
def generate_security_report(self) -> Dict[str, Any]:
    """
    Generate a security-focused audit report.

Returns:
    Security report data structure
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditReportGenerator

## get_anomalies

```python
def get_anomalies(self, threshold: float = 0.7) -> List[Dict[str, Any]]:
    """
    Get detected anomalies above a specific risk threshold.

Args:
    threshold: Risk threshold for filtering anomalies (0-1)

Returns:
    List of anomalies with details
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditPatternDetector

## get_compliance_summary

```python
def get_compliance_summary(self) -> Dict[str, Any]:
    """
    Get a summary of compliance status across all frameworks.

Returns:
    Summary of compliance status
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditComplianceAnalyzer

## setup_audit_reporting

```python
def setup_audit_reporting(audit_logger: AuditLogger, metrics_aggregator: Optional[AuditMetricsAggregator] = None, visualizer: Optional[AuditVisualizer] = None, output_dir: str = "./audit_reports") -> Tuple[AuditReportGenerator, AuditPatternDetector, AuditComplianceAnalyzer]:
    """
    Set up the audit reporting system with metrics, pattern detection, and compliance analysis.

Args:
    audit_logger: The audit logger instance
    metrics_aggregator: Optional existing metrics aggregator
    visualizer: Optional existing visualizer
    output_dir: Directory for report output files

Returns:
    Tuple of (report_generator, pattern_detector, compliance_analyzer)
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
