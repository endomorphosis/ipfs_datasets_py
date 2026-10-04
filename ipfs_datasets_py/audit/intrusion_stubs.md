# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/audit/intrusion.py'

Files last updated: 1748635923.4213796

Stub file last updated: 2025-07-07 02:14:36

## AnomalyDetector

```python
class AnomalyDetector:
    """
    Detects anomalies in audit events using statistical methods.

This class analyzes patterns in audit events to identify unusual
activity that may indicate security breaches or operational issues.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## IntrusionDetection

```python
class IntrusionDetection:
    """
    Main intrusion detection system that coordinates detection and alerting.

This class manages different detection methods and generates
security alerts when potential intrusions are detected.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SecurityAlert

```python
@dataclass
class SecurityAlert:
    """
    Represents a security alert generated from audit events.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SecurityAlertManager

```python
class SecurityAlertManager:
    """
    Manages security alerts generated from audit events.

This class provides functionality for storing, querying, and
updating security alerts and coordinating responses.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, window_size: int = 1000, baseline_period_days: int = 7, threshold_multiplier: float = 2.0):
    """
    Initialize the anomaly detector.

Args:
    window_size: Number of events to consider for moving statistics
    baseline_period_days: Days of data to use for establishing baselines
    threshold_multiplier: Multiplier for standard deviation to determine anomalies
    """
```
* **Async:** False
* **Method:** True
* **Class:** AnomalyDetector

## __init__

```python
def __init__(self):
    """
    Initialize the intrusion detection system.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntrusionDetection

## __init__

```python
def __init__(self, alert_storage_path: Optional[str] = None):
    """
    Initialize the security alert manager.

Args:
    alert_storage_path: Path to store alerts (optional)
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityAlertManager

## _calculate_severity

```python
def _calculate_severity(self, z_score: float, multiplier: float = 1.0) -> str:
    """
    Calculate severity level based on z-score.

Args:
    z_score: Standard deviation from mean
    multiplier: Adjustment factor for severity calculation

Returns:
    str: Severity level ('low', 'medium', 'high', 'critical')
    """
```
* **Async:** False
* **Method:** True
* **Class:** AnomalyDetector

## _convert_anomalies_to_alerts

```python
def _convert_anomalies_to_alerts(self, anomalies: List[Dict[str, Any]], event_ids: List[str]) -> List[SecurityAlert]:
    """
    Convert anomaly detections to security alerts.

Args:
    anomalies: List of anomaly detections
    event_ids: IDs of events related to the anomalies

Returns:
    List[SecurityAlert]: Security alerts generated from anomalies
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntrusionDetection

## _convert_patterns_to_alerts

```python
def _convert_patterns_to_alerts(self, patterns: List[Dict[str, Any]], detector_name: str) -> List[SecurityAlert]:
    """
    Convert pattern detections to security alerts.

Args:
    patterns: List of pattern detections
    detector_name: Name of the pattern detector

Returns:
    List[SecurityAlert]: Security alerts generated from patterns
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntrusionDetection

## _detect_account_compromise

```python
def _detect_account_compromise(self, events: List[AuditEvent]) -> List[Dict[str, Any]]:
    """
    Detect potential account compromise based on behavioral anomalies.

Args:
    events: List of audit events to analyze

Returns:
    List[Dict[str, Any]]: Detected patterns
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntrusionDetection

## _detect_anomalies

```python
def _detect_anomalies(self) -> List[Dict[str, Any]]:
    """
    Detect anomalies in current metrics compared to baseline.

Returns:
    List[Dict[str, Any]]: Detected anomalies
    """
```
* **Async:** False
* **Method:** True
* **Class:** AnomalyDetector

## _detect_brute_force_login

```python
def _detect_brute_force_login(self, events: List[AuditEvent]) -> List[Dict[str, Any]]:
    """
    Detect brute force login attempts.

Args:
    events: List of audit events to analyze

Returns:
    List[Dict[str, Any]]: Detected patterns
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntrusionDetection

## _detect_data_exfiltration

```python
def _detect_data_exfiltration(self, events: List[AuditEvent]) -> List[Dict[str, Any]]:
    """
    Detect potential data exfiltration.

Args:
    events: List of audit events to analyze

Returns:
    List[Dict[str, Any]]: Detected patterns
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntrusionDetection

## _detect_multiple_access_denials

```python
def _detect_multiple_access_denials(self, events: List[AuditEvent]) -> List[Dict[str, Any]]:
    """
    Detect multiple access denials.

Args:
    events: List of audit events to analyze

Returns:
    List[Dict[str, Any]]: Detected patterns
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntrusionDetection

## _detect_privilege_escalation

```python
def _detect_privilege_escalation(self, events: List[AuditEvent]) -> List[Dict[str, Any]]:
    """
    Detect potential privilege escalation.

Args:
    events: List of audit events to analyze

Returns:
    List[Dict[str, Any]]: Detected patterns
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntrusionDetection

## _detect_sensitive_data_access

```python
def _detect_sensitive_data_access(self, events: List[AuditEvent]) -> List[Dict[str, Any]]:
    """
    Detect unusual access to sensitive data.

Args:
    events: List of audit events to analyze

Returns:
    List[Dict[str, Any]]: Detected patterns
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntrusionDetection

## _detect_unauthorized_configuration

```python
def _detect_unauthorized_configuration(self, events: List[AuditEvent]) -> List[Dict[str, Any]]:
    """
    Detect unauthorized configuration changes.

Args:
    events: List of audit events to analyze

Returns:
    List[Dict[str, Any]]: Detected patterns
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntrusionDetection

## _dispatch_alert

```python
def _dispatch_alert(self, alert: SecurityAlert) -> None:
    """
    Dispatch a security alert to all registered handlers.

Args:
    alert: The security alert to dispatch
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntrusionDetection

## _load_alerts

```python
def _load_alerts(self) -> None:
    """
    Load alerts from storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityAlertManager

## _notify_handlers

```python
def _notify_handlers(self, alert: SecurityAlert) -> None:
    """
    Notify all handlers of a new alert.

Args:
    alert: The alert to notify about
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityAlertManager

## _register_default_detectors

```python
def _register_default_detectors(self) -> None:
    """
    Register default pattern detectors.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntrusionDetection

## _save_alerts

```python
def _save_alerts(self) -> None:
    """
    Save alerts to storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityAlertManager

## _update_metrics

```python
def _update_metrics(self) -> None:
    """
    Update metrics based on current window of events.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AnomalyDetector

## add_alert

```python
def add_alert(self, alert: SecurityAlert) -> str:
    """
    Add a new security alert.

Args:
    alert: The security alert to add

Returns:
    str: The ID of the added alert
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityAlertManager

## add_alert_handler

```python
def add_alert_handler(self, handler: Callable[[SecurityAlert], None]) -> None:
    """
    Add a handler for processing security alerts.

Args:
    handler: Function that processes security alerts
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntrusionDetection

## add_notification_handler

```python
def add_notification_handler(self, handler: Callable[[SecurityAlert], None]) -> None:
    """
    Add a handler for alert notifications.

Args:
    handler: Function that handles alert notifications
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityAlertManager

## add_pattern_detector

```python
def add_pattern_detector(self, name: str, detector: Callable[[List[AuditEvent]], List[Dict[str, Any]]]) -> None:
    """
    Add a pattern detector for identifying specific intrusion patterns.

Args:
    name: Name of the detector
    detector: Function that detects patterns in events
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntrusionDetection

## establish_baseline

```python
def establish_baseline(self, events: List[AuditEvent]) -> None:
    """
    Establish baseline metrics from historical events.

Args:
    events: Historical audit events to analyze
    """
```
* **Async:** False
* **Method:** True
* **Class:** AnomalyDetector

## establish_baseline

```python
def establish_baseline(self, events: List[AuditEvent]) -> None:
    """
    Establish baseline metrics for anomaly detection.

Args:
    events: Historical audit events to analyze
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntrusionDetection

## get_alert

```python
def get_alert(self, alert_id: str) -> Optional[SecurityAlert]:
    """
    Get a security alert by ID.

Args:
    alert_id: ID of the alert to get

Returns:
    SecurityAlert: The requested alert, or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityAlertManager

## get_alerts

```python
def get_alerts(self, filters: Optional[Dict[str, Any]] = None) -> List[SecurityAlert]:
    """
    Get alerts matching specified filters.

Args:
    filters: Dictionary of filters to apply

Returns:
    List[SecurityAlert]: Alerts matching the filters
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityAlertManager

## process_event

```python
def process_event(self, event: AuditEvent) -> List[Dict[str, Any]]:
    """
    Process a new audit event and check for anomalies.

Args:
    event: The audit event to process

Returns:
    List[Dict[str, Any]]: Detected anomalies, if any
    """
```
* **Async:** False
* **Method:** True
* **Class:** AnomalyDetector

## process_events

```python
def process_events(self, events: List[AuditEvent]) -> List[SecurityAlert]:
    """
    Process a batch of audit events and detect potential intrusions.

Args:
    events: List of audit events to process

Returns:
    List[SecurityAlert]: Security alerts generated
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntrusionDetection

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert the alert to a dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityAlert

## update_alert

```python
def update_alert(self, alert_id: str, updates: Dict[str, Any]) -> bool:
    """
    Update an existing security alert.

Args:
    alert_id: ID of the alert to update
    updates: Dictionary of updates to apply

Returns:
    bool: Whether the update was successful
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityAlertManager
