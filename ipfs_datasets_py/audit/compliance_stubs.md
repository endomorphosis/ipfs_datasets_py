# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/audit/compliance.py'

Files last updated: 1748635923.4213796

Stub file last updated: 2025-07-07 02:14:36

## ComplianceReport

```python
@dataclass
class ComplianceReport:
    """
    A report demonstrating compliance with a set of requirements.

This class represents a compliance report generated from audit logs,
showing whether and how compliance requirements are being met.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ComplianceReporter

```python
class ComplianceReporter:
    """
    Base class for generating compliance reports from audit logs.

This class provides the foundation for compliance reporting against
various regulatory standards and frameworks.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ComplianceRequirement

```python
@dataclass
class ComplianceRequirement:
    """
    A specific compliance requirement that needs to be demonstrated.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ComplianceStandard

```python
class ComplianceStandard(Enum):
    """
    Supported compliance standards.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## GDPRComplianceReporter

```python
class GDPRComplianceReporter(ComplianceReporter):
    """
    Compliance reporter for GDPR (General Data Protection Regulation).

This class provides predefined compliance requirements specific to GDPR,
focusing on data access, processing, and subject rights.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## HIPAAComplianceReporter

```python
class HIPAAComplianceReporter(ComplianceReporter):
    """
    Compliance reporter for HIPAA (Health Insurance Portability and Accountability Act).

This class provides predefined compliance requirements specific to HIPAA,
focusing on PHI (Protected Health Information) access and security.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SOC2ComplianceReporter

```python
class SOC2ComplianceReporter(ComplianceReporter):
    """
    Compliance reporter for SOC 2 (Service Organization Control 2).

This class provides predefined compliance requirements specific to SOC 2,
covering the five trust services criteria: security, availability,
processing integrity, confidentiality, and privacy.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, standard: ComplianceStandard):
    """
    Initialize the compliance reporter.

Args:
    standard: The compliance standard to report against
    """
```
* **Async:** False
* **Method:** True
* **Class:** ComplianceReporter

## __init__

```python
def __init__(self):
    """
    Initialize the GDPR compliance reporter with predefined requirements.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GDPRComplianceReporter

## __init__

```python
def __init__(self):
    """
    Initialize the HIPAA compliance reporter with predefined requirements.
    """
```
* **Async:** False
* **Method:** True
* **Class:** HIPAAComplianceReporter

## __init__

```python
def __init__(self):
    """
    Initialize the SOC2 compliance reporter with predefined requirements.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SOC2ComplianceReporter

## _check_requirement

```python
def _check_requirement(self, requirement: ComplianceRequirement, events: List[AuditEvent]) -> tuple:
    """
    Check if a compliance requirement is met.

Args:
    requirement: The compliance requirement to check
    events: Relevant audit events

Returns:
    tuple: (status, details) where status is one of 'Compliant',
          'Non-Compliant', or 'Partial'
    """
```
* **Async:** False
* **Method:** True
* **Class:** ComplianceReporter

## _filter_events_for_requirement

```python
def _filter_events_for_requirement(self, events: List[AuditEvent], requirement: ComplianceRequirement) -> List[AuditEvent]:
    """
    Filter events relevant to a specific compliance requirement.

Args:
    events: List of all audit events
    requirement: The compliance requirement to filter for

Returns:
    List[AuditEvent]: Events relevant to the requirement
    """
```
* **Async:** False
* **Method:** True
* **Class:** ComplianceReporter

## _generate_remediation

```python
def _generate_remediation(self, requirement: ComplianceRequirement, details: Dict[str, Any]) -> List[str]:
    """
    Generate remediation suggestions for a failed requirement.

Args:
    requirement: The failed compliance requirement
    details: Details about the failure

Returns:
    List[str]: Remediation suggestions
    """
```
* **Async:** False
* **Method:** True
* **Class:** ComplianceReporter

## add_requirement

```python
def add_requirement(self, requirement: ComplianceRequirement) -> None:
    """
    Add a compliance requirement to check.

Args:
    requirement: The compliance requirement to add
    """
```
* **Async:** False
* **Method:** True
* **Class:** ComplianceReporter

## generate_report

```python
def generate_report(self, events: List[AuditEvent], start_time: Optional[str] = None, end_time: Optional[str] = None) -> ComplianceReport:
    """
    Generate a compliance report from audit events.

Args:
    events: List of audit events to analyze
    start_time: Start time for the report period (ISO format)
    end_time: End time for the report period (ISO format)

Returns:
    ComplianceReport: The generated compliance report
    """
```
* **Async:** False
* **Method:** True
* **Class:** ComplianceReporter

## get_status_text

```python
@staticmethod
def get_status_text(status: bool) -> str:
    """
    Convert boolean status to text.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ComplianceReport

## save_csv

```python
def save_csv(self, file_path: str) -> None:
    """
    Save requirements status to a CSV file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ComplianceReport

## save_html

```python
def save_html(self, file_path: str) -> None:
    """
    Save the report as an HTML document.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ComplianceReport

## save_json

```python
def save_json(self, file_path: str, pretty = True) -> None:
    """
    Save the report to a JSON file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ComplianceReport

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert the report to a dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ComplianceReport

## to_json

```python
def to_json(self, pretty = False) -> str:
    """
    Serialize the report to JSON.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ComplianceReport
