"""
Intrusion Detection for Audit Logging System

This module provides intrusion detection capabilities that integrate with
the audit logging system to detect and alert on potential security breaches.
"""

import os
import json
import time
import math
import logging
import datetime
import threading
import statistics
from typing import Dict, List, Any, Optional, Union, Callable, Set, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict, Counter

from ipfs_datasets_py.audit.audit_logger import AuditEvent, AuditCategory, AuditLevel


@dataclass
class SecurityAlert:
    """Represents a security alert generated from audit events."""
    alert_id: str
    timestamp: str
    level: str  # 'low', 'medium', 'high', 'critical'
    type: str  # Alert type (e.g., 'brute_force', 'data_exfiltration')
    description: str
    source_events: List[str]  # IDs of events that triggered this alert
    details: Dict[str, Any] = field(default_factory=dict)
    status: str = "new"  # 'new', 'investigating', 'resolved', 'false_positive'
    assigned_to: Optional[str] = None
    resolution: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert the alert to a dictionary."""
        return asdict(self)


class AnomalyDetector:
    """
    Detects anomalies in audit events using statistical methods.

    This class analyzes patterns in audit events to identify unusual
    activity that may indicate security breaches or operational issues.
    """

    def __init__(self, window_size: int = 1000,
                baseline_period_days: int = 7,
                threshold_multiplier: float = 2.0):
        """
        Initialize the anomaly detector.

        Args:
            window_size: Number of events to consider for moving statistics
            baseline_period_days: Days of data to use for establishing baselines
            threshold_multiplier: Multiplier for standard deviation to determine anomalies
        """
        self.window_size = window_size
        self.baseline_period_days = baseline_period_days
        self.threshold_multiplier = threshold_multiplier
        self.baseline_metrics: Dict[str, Any] = {}
        self.current_window: List[AuditEvent] = []
        self.metrics_history: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.RLock()
        self.logger = logging.getLogger(__name__)

    def process_event(self, event: AuditEvent) -> List[Dict[str, Any]]:
        """
        Process a new audit event and check for anomalies.

        Args:
            event: The audit event to process

        Returns:
            List[Dict[str, Any]]: Detected anomalies, if any
        """
        with self._lock:
            # Add event to current window
            self.current_window.append(event)
            if len(self.current_window) > self.window_size:
                self.current_window.pop(0)

            # Update metrics
            self._update_metrics()

            # Check for anomalies
            return self._detect_anomalies()

    def establish_baseline(self, events: List[AuditEvent]) -> None:
        """
        Establish baseline metrics from historical events.

        Args:
            events: Historical audit events to analyze
        """
        with self._lock:
            # Clear existing baseline
            self.baseline_metrics = {}
            self.metrics_history = defaultdict(list)

            # Filter events to baseline period
            cutoff_time = datetime.datetime.now() - datetime.timedelta(days=self.baseline_period_days)
            cutoff_time_str = cutoff_time.isoformat()

            baseline_events = [e for e in events if e.timestamp > cutoff_time_str]

            if not baseline_events:
                self.logger.warning("No events in baseline period")
                return

            # Process events in chronological windows
            for i in range(0, len(baseline_events), self.window_size):
                window = baseline_events[i:i+self.window_size]
                self.current_window = window
                self._update_metrics()

            # Calculate baseline statistics
            for metric, values in self.metrics_history.items():
                if values:
                    self.baseline_metrics[metric] = {
                        'mean': statistics.mean(values),
                        'median': statistics.median(values),
                        'stddev': statistics.stdev(values) if len(values) > 1 else 0,
                        'min': min(values),
                        'max': max(values),
                        'count': len(values)
                    }

            self.logger.info(f"Established baseline from {len(baseline_events)} events")

    def _update_metrics(self) -> None:
        """Update metrics based on current window of events."""
        if not self.current_window:
            return

        # Calculate various metrics
        metrics = {}

        # Event counts by category
        category_counts = Counter(e.category.name for e in self.current_window)
        for category, count in category_counts.items():
            metrics[f"count_category_{category}"] = count

        # Event counts by level
        level_counts = Counter(e.level.name for e in self.current_window)
        for level, count in level_counts.items():
            metrics[f"count_level_{level}"] = count

        # Event counts by action
        action_counts = Counter(e.action for e in self.current_window)
        for action, count in action_counts.items():
            metrics[f"count_action_{action}"] = count

        # Event counts by user
        user_counts = Counter(e.user for e in self.current_window if e.user)
        for user, count in user_counts.items():
            metrics[f"count_user_{user}"] = count

        # Event counts by status
        status_counts = Counter(e.status for e in self.current_window)
        for status, count in status_counts.items():
            metrics[f"count_status_{status}"] = count

        # Event counts by resource type
        resource_type_counts = Counter(e.resource_type for e in self.current_window if e.resource_type)
        for resource_type, count in resource_type_counts.items():
            metrics[f"count_resource_type_{resource_type}"] = count

        # Update metrics history
        for metric, value in metrics.items():
            self.metrics_history[metric].append(value)
            # Keep history bounded
            if len(self.metrics_history[metric]) > 100:
                self.metrics_history[metric].pop(0)

        # Advanced metrics for specific security concerns

        # Failed login rate
        login_events = [e for e in self.current_window if e.category == AuditCategory.AUTHENTICATION and e.action == "login"]
        failed_logins = [e for e in login_events if e.status == "failure"]
        if login_events:
            metrics["rate_failed_logins"] = len(failed_logins) / len(login_events)
            self.metrics_history["rate_failed_logins"].append(metrics["rate_failed_logins"])
            if len(self.metrics_history["rate_failed_logins"]) > 100:
                self.metrics_history["rate_failed_logins"].pop(0)

        # Access denial rate
        access_events = [e for e in self.current_window if e.category == AuditCategory.AUTHORIZATION]
        access_denied = [e for e in access_events if e.status == "failure" or e.action == "access_denied"]
        if access_events:
            metrics["rate_access_denied"] = len(access_denied) / len(access_events)
            self.metrics_history["rate_access_denied"].append(metrics["rate_access_denied"])
            if len(self.metrics_history["rate_access_denied"]) > 100:
                self.metrics_history["rate_access_denied"].pop(0)

        # Data access volume by user
        data_access_by_user = defaultdict(int)
        for event in self.current_window:
            if event.category == AuditCategory.DATA_ACCESS and event.user:
                data_access_by_user[event.user] += 1

        for user, count in data_access_by_user.items():
            metrics[f"data_access_volume_{user}"] = count
            self.metrics_history[f"data_access_volume_{user}"].append(count)
            if len(self.metrics_history[f"data_access_volume_{user}"]) > 100:
                self.metrics_history[f"data_access_volume_{user}"].pop(0)

    def _detect_anomalies(self) -> List[Dict[str, Any]]:
        """
        Detect anomalies in current metrics compared to baseline.

        Returns:
            List[Dict[str, Any]]: Detected anomalies
        """
        if not self.baseline_metrics:
            return []

        anomalies = []

        # Check each metric against its baseline
        for metric, values in self.metrics_history.items():
            if not values or metric not in self.baseline_metrics:
                continue

            current_value = values[-1]
            baseline = self.baseline_metrics[metric]

            # Skip metrics with insufficient history
            if baseline['count'] < 5:
                continue

            # Detect if current value is anomalous
            mean = baseline['mean']
            stddev = baseline['stddev']

            if stddev > 0:
                z_score = abs(current_value - mean) / stddev
                threshold = self.threshold_multiplier

                if z_score > threshold:
                    anomaly = {
                        'metric': metric,
                        'value': current_value,
                        'baseline_mean': mean,
                        'baseline_stddev': stddev,
                        'z_score': z_score,
                        'deviation_percent': abs((current_value - mean) / mean) * 100 if mean != 0 else float('inf'),
                        'timestamp': datetime.datetime.utcnow().isoformat() + 'Z'
                    }

                    # Add anomaly details based on metric type
                    if metric.startswith('count_category_'):
                        category = metric.split('_')[-1]
                        anomaly['type'] = 'category_volume'
                        anomaly['category'] = category
                        anomaly['description'] = f"Unusual volume of {category} events"
                        anomaly['severity'] = self._calculate_severity(z_score)

                    elif metric.startswith('count_level_'):
                        level = metric.split('_')[-1]
                        anomaly['type'] = 'severity_distribution'
                        anomaly['level'] = level
                        anomaly['description'] = f"Unusual number of {level} level events"
                        anomaly['severity'] = self._calculate_severity(z_score)

                    elif metric.startswith('count_action_'):
                        action = metric.split('count_action_')[-1]
                        anomaly['type'] = 'action_frequency'
                        anomaly['action'] = action
                        anomaly['description'] = f"Unusual frequency of {action} actions"
                        anomaly['severity'] = self._calculate_severity(z_score)

                    elif metric.startswith('count_user_'):
                        user = metric.split('count_user_')[-1]
                        anomaly['type'] = 'user_activity'
                        anomaly['user'] = user
                        anomaly['description'] = f"Unusual activity level for user {user}"
                        anomaly['severity'] = self._calculate_severity(z_score)

                    elif metric == 'rate_failed_logins':
                        anomaly['type'] = 'authentication_failure'
                        anomaly['description'] = "Unusual rate of failed login attempts"
                        anomaly['severity'] = self._calculate_severity(z_score, multiplier=1.5)

                    elif metric == 'rate_access_denied':
                        anomaly['type'] = 'authorization_failure'
                        anomaly['description'] = "Unusual rate of access denials"
                        anomaly['severity'] = self._calculate_severity(z_score, multiplier=1.5)

                    elif metric.startswith('data_access_volume_'):
                        user = metric.split('data_access_volume_')[-1]
                        anomaly['type'] = 'data_access_volume'
                        anomaly['user'] = user
                        anomaly['description'] = f"Unusual volume of data access by user {user}"
                        anomaly['severity'] = self._calculate_severity(z_score)

                    else:
                        anomaly['type'] = 'generic'
                        anomaly['description'] = f"Anomaly detected in metric: {metric}"
                        anomaly['severity'] = self._calculate_severity(z_score)

                    anomalies.append(anomaly)

        return anomalies

    def _calculate_severity(self, z_score: float, multiplier: float = 1.0) -> str:
        """
        Calculate severity level based on z-score.

        Args:
            z_score: Standard deviation from mean
            multiplier: Adjustment factor for severity calculation

        Returns:
            str: Severity level ('low', 'medium', 'high', 'critical')
        """
        adjusted_score = z_score * multiplier

        if adjusted_score < 3:
            return 'low'
        elif adjusted_score < 5:
            return 'medium'
        elif adjusted_score < 7:
            return 'high'
        else:
            return 'critical'


class IntrusionDetection:
    """
    Main intrusion detection system that coordinates detection and alerting.

    This class manages different detection methods and generates
    security alerts when potential intrusions are detected.
    """

    def __init__(self):
        """Initialize the intrusion detection system."""
        self.anomaly_detector = AnomalyDetector()
        self.alert_handlers: List[Callable[[SecurityAlert], None]] = []
        self.pattern_detectors: Dict[str, Callable[[List[AuditEvent]], List[Dict[str, Any]]]] = {}
        self.seen_events: Set[str] = set()
        self.recent_alerts: Dict[str, List[SecurityAlert]] = defaultdict(list)
        self._lock = threading.RLock()
        self.logger = logging.getLogger(__name__)

        # Register built-in pattern detectors
        self._register_default_detectors()

    def process_events(self, events: List[AuditEvent]) -> List[SecurityAlert]:
        """
        Process a batch of audit events and detect potential intrusions.

        Args:
            events: List of audit events to process

        Returns:
            List[SecurityAlert]: Security alerts generated
        """
        alerts = []

        with self._lock:
            # Filter out already seen events
            new_events = [e for e in events if e.event_id not in self.seen_events]
            for event in new_events:
                self.seen_events.add(event.event_id)

            if not new_events:
                return alerts

            # Process with anomaly detector
            for event in new_events:
                anomalies = self.anomaly_detector.process_event(event)
                alerts.extend(self._convert_anomalies_to_alerts(anomalies, [event.event_id]))

            # Process with pattern detectors
            for detector_name, detector_func in self.pattern_detectors.items():
                try:
                    patterns = detector_func(new_events)
                    pattern_alerts = self._convert_patterns_to_alerts(patterns, detector_name)
                    alerts.extend(pattern_alerts)
                except Exception as e:
                    self.logger.error(f"Error in pattern detector {detector_name}: {str(e)}")

            # Update recent alerts
            for alert in alerts:
                alert_type = alert.type
                self.recent_alerts[alert_type].append(alert)
                # Keep only recent alerts
                cutoff_time = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
                cutoff_time_str = cutoff_time.isoformat()
                self.recent_alerts[alert_type] = [
                    a for a in self.recent_alerts[alert_type]
                    if a.timestamp > cutoff_time_str
                ]

            # Dispatch alerts
            for alert in alerts:
                self._dispatch_alert(alert)

            return alerts

    def establish_baseline(self, events: List[AuditEvent]) -> None:
        """
        Establish baseline metrics for anomaly detection.

        Args:
            events: Historical audit events to analyze
        """
        self.anomaly_detector.establish_baseline(events)

    def add_alert_handler(self, handler: Callable[[SecurityAlert], None]) -> None:
        """
        Add a handler for processing security alerts.

        Args:
            handler: Function that processes security alerts
        """
        with self._lock:
            self.alert_handlers.append(handler)

    def add_pattern_detector(self, name: str,
                           detector: Callable[[List[AuditEvent]], List[Dict[str, Any]]]) -> None:
        """
        Add a pattern detector for identifying specific intrusion patterns.

        Args:
            name: Name of the detector
            detector: Function that detects patterns in events
        """
        with self._lock:
            self.pattern_detectors[name] = detector

    def _register_default_detectors(self) -> None:
        """Register default pattern detectors."""
        self.add_pattern_detector("brute_force_login", self._detect_brute_force_login)
        self.add_pattern_detector("multiple_access_denials", self._detect_multiple_access_denials)
        self.add_pattern_detector("sensitive_data_access", self._detect_sensitive_data_access)
        self.add_pattern_detector("account_compromise", self._detect_account_compromise)
        self.add_pattern_detector("privilege_escalation", self._detect_privilege_escalation)
        self.add_pattern_detector("data_exfiltration", self._detect_data_exfiltration)
        self.add_pattern_detector("unauthorized_configuration", self._detect_unauthorized_configuration)

    def _convert_anomalies_to_alerts(self, anomalies: List[Dict[str, Any]],
                                  event_ids: List[str]) -> List[SecurityAlert]:
        """
        Convert anomaly detections to security alerts.

        Args:
            anomalies: List of anomaly detections
            event_ids: IDs of events related to the anomalies

        Returns:
            List[SecurityAlert]: Security alerts generated from anomalies
        """
        alerts = []

        for anomaly in anomalies:
            alert_id = f"anomaly-{int(time.time())}-{len(alerts)}"
            alert = SecurityAlert(
                alert_id=alert_id,
                timestamp=anomaly.get('timestamp', datetime.datetime.utcnow().isoformat() + 'Z'),
                level=anomaly.get('severity', 'medium'),
                type=anomaly.get('type', 'anomaly'),
                description=anomaly.get('description', 'Anomalous activity detected'),
                source_events=event_ids,
                details=anomaly
            )
            alerts.append(alert)

        return alerts

    def _convert_patterns_to_alerts(self, patterns: List[Dict[str, Any]],
                                 detector_name: str) -> List[SecurityAlert]:
        """
        Convert pattern detections to security alerts.

        Args:
            patterns: List of pattern detections
            detector_name: Name of the pattern detector

        Returns:
            List[SecurityAlert]: Security alerts generated from patterns
        """
        alerts = []

        for pattern in patterns:
            alert_id = f"{detector_name}-{int(time.time())}-{len(alerts)}"
            alert = SecurityAlert(
                alert_id=alert_id,
                timestamp=pattern.get('timestamp', datetime.datetime.utcnow().isoformat() + 'Z'),
                level=pattern.get('severity', 'medium'),
                type=pattern.get('type', detector_name),
                description=pattern.get('description', f'Pattern detected by {detector_name}'),
                source_events=pattern.get('event_ids', []),
                details=pattern
            )
            alerts.append(alert)

        return alerts

    def _dispatch_alert(self, alert: SecurityAlert) -> None:
        """
        Dispatch a security alert to all registered handlers.

        Args:
            alert: The security alert to dispatch
        """
        for handler in self.alert_handlers:
            try:
                handler(alert)
            except Exception as e:
                self.logger.error(f"Error in alert handler: {str(e)}")

    # Built-in pattern detectors

    def _detect_brute_force_login(self, events: List[AuditEvent]) -> List[Dict[str, Any]]:
        """
        Detect brute force login attempts.

        Args:
            events: List of audit events to analyze

        Returns:
            List[Dict[str, Any]]: Detected patterns
        """
        patterns = []

        # Filter for authentication failures
        auth_failures = [
            e for e in events
            if e.category == AuditCategory.AUTHENTICATION
            and e.action == "login"
            and e.status == "failure"
        ]

        if not auth_failures:
            return patterns

        # Group by user and source IP
        grouped_failures = defaultdict(list)
        for event in auth_failures:
            key = (event.user or "unknown", event.client_ip or "unknown")
            grouped_failures[key].append(event)

        # Check thresholds
        for (user, ip), failures in grouped_failures.items():
            if len(failures) >= 5:  # Threshold for brute force detection
                pattern = {
                    'type': 'brute_force_login',
                    'user': user,
                    'source_ip': ip,
                    'failure_count': len(failures),
                    'event_ids': [e.event_id for e in failures],
                    'description': f"Potential brute force login attempt for user {user} from {ip}",
                    'severity': 'high',
                    'timestamp': datetime.datetime.utcnow().isoformat() + 'Z'
                }
                patterns.append(pattern)

        return patterns

    def _detect_multiple_access_denials(self, events: List[AuditEvent]) -> List[Dict[str, Any]]:
        """
        Detect multiple access denials.

        Args:
            events: List of audit events to analyze

        Returns:
            List[Dict[str, Any]]: Detected patterns
        """
        patterns = []

        # Filter for access denials
        access_denials = [
            e for e in events
            if e.category == AuditCategory.AUTHORIZATION
            and (e.action == "access_denied" or e.status == "failure")
        ]

        if not access_denials:
            return patterns

        # Group by user
        grouped_denials = defaultdict(list)
        for event in access_denials:
            user = event.user or "unknown"
            grouped_denials[user].append(event)

        # Check thresholds
        for user, denials in grouped_denials.items():
            if len(denials) >= 3:  # Threshold for multiple access denials
                # Group by resource type
                resource_types = Counter(e.resource_type for e in denials if e.resource_type)
                most_common_resource = resource_types.most_common(1)[0][0] if resource_types else "unknown"

                pattern = {
                    'type': 'multiple_access_denials',
                    'user': user,
                    'denial_count': len(denials),
                    'resource_types': dict(resource_types),
                    'most_common_resource': most_common_resource,
                    'event_ids': [e.event_id for e in denials],
                    'description': f"Multiple access denials for user {user}, primarily for {most_common_resource} resources",
                    'severity': 'medium',
                    'timestamp': datetime.datetime.utcnow().isoformat() + 'Z'
                }
                patterns.append(pattern)

        return patterns

    def _detect_sensitive_data_access(self, events: List[AuditEvent]) -> List[Dict[str, Any]]:
        """
        Detect unusual access to sensitive data.

        Args:
            events: List of audit events to analyze

        Returns:
            List[Dict[str, Any]]: Detected patterns
        """
        patterns = []

        # Filter for data access events
        data_access = [
            e for e in events
            if e.category == AuditCategory.DATA_ACCESS
            and e.action in ["read", "export", "download"]
        ]

        if not data_access:
            return patterns

        # Identify sensitive resource types (customize based on your data)
        sensitive_types = ["personal_data", "financial", "health", "credentials", "keys", "secrets"]

        sensitive_access = [
            e for e in data_access
            if (e.resource_type and e.resource_type.lower() in sensitive_types) or
               (e.details and "sensitive" in e.details.get("data_classification", "").lower())
        ]

        if not sensitive_access:
            return patterns

        # Group by user
        grouped_access = defaultdict(list)
        for event in sensitive_access:
            user = event.user or "unknown"
            grouped_access[user].append(event)

        # Check for unusual patterns
        for user, access_events in grouped_access.items():
            # Count by resource type
            resource_counts = Counter(e.resource_type for e in access_events if e.resource_type)

            # Look for volume-based anomalies
            if len(access_events) >= 5:  # Threshold for volume-based detection
                pattern = {
                    'type': 'sensitive_data_access',
                    'user': user,
                    'access_count': len(access_events),
                    'resource_types': dict(resource_counts),
                    'event_ids': [e.event_id for e in access_events],
                    'description': f"High volume of sensitive data access by user {user}",
                    'severity': 'medium',
                    'timestamp': datetime.datetime.utcnow().isoformat() + 'Z'
                }
                patterns.append(pattern)

        return patterns

    def _detect_account_compromise(self, events: List[AuditEvent]) -> List[Dict[str, Any]]:
        """
        Detect potential account compromise based on behavioral anomalies.

        Args:
            events: List of audit events to analyze

        Returns:
            List[Dict[str, Any]]: Detected patterns
        """
        patterns = []

        # Group events by user
        user_events = defaultdict(list)
        for event in events:
            if event.user:
                user_events[event.user].append(event)

        for user, user_event_list in user_events.items():
            # Look for indicators of compromise
            indicators = []

            # Unusual authentication patterns
            auth_events = [e for e in user_event_list if e.category == AuditCategory.AUTHENTICATION]
            if auth_events:
                # Check for logins from multiple IPs
                login_ips = set(e.client_ip for e in auth_events if e.client_ip and e.action == "login")
                if len(login_ips) > 2:
                    indicators.append(f"Logins from {len(login_ips)} different IP addresses")

            # Unusual time of access
            event_times = [datetime.datetime.fromisoformat(e.timestamp.rstrip('Z')) for e in user_event_list]
            for time in event_times:
                hour = time.hour
                if hour < 5 or hour > 22:  # Assuming regular business hours
                    indicators.append(f"Activity at unusual hour ({hour}:00)")
                    break

            # Unusual data access patterns
            data_events = [e for e in user_event_list if e.category == AuditCategory.DATA_ACCESS]
            if data_events:
                # Check for high volume of access
                if len(data_events) > 20:
                    indicators.append(f"High volume of data access ({len(data_events)} events)")

                # Check for access to many different resources
                resource_ids = set(e.resource_id for e in data_events if e.resource_id)
                if len(resource_ids) > 15:
                    indicators.append(f"Access to many different resources ({len(resource_ids)} resources)")

            # If multiple indicators are present, generate an alert
            if len(indicators) >= 2:
                pattern = {
                    'type': 'account_compromise',
                    'user': user,
                    'indicators': indicators,
                    'event_count': len(user_event_list),
                    'event_ids': [e.event_id for e in user_event_list],
                    'description': f"Potential account compromise for user {user}: {', '.join(indicators)}",
                    'severity': 'high',
                    'timestamp': datetime.datetime.utcnow().isoformat() + 'Z'
                }
                patterns.append(pattern)

        return patterns

    def _detect_privilege_escalation(self, events: List[AuditEvent]) -> List[Dict[str, Any]]:
        """
        Detect potential privilege escalation.

        Args:
            events: List of audit events to analyze

        Returns:
            List[Dict[str, Any]]: Detected patterns
        """
        patterns = []

        # Look for privilege/permission changes
        permission_events = [
            e for e in events
            if (e.category in [AuditCategory.AUTHORIZATION, AuditCategory.CONFIGURATION, AuditCategory.SECURITY]) and
               (e.action in ["permission_change", "role_change", "privilege_escalation",
                            "sudo", "impersonation", "add_admin"])
        ]

        if not permission_events:
            return patterns

        # Group by user
        for event in permission_events:
            # Extract details about the privilege change
            user = event.user or "unknown"
            target_user = event.details.get("target_user", "unknown")

            pattern = {
                'type': 'privilege_escalation',
                'user': user,
                'target_user': target_user,
                'action': event.action,
                'event_ids': [event.event_id],
                'description': f"Potential privilege escalation by {user} affecting {target_user}",
                'severity': 'high',
                'timestamp': event.timestamp
            }
            patterns.append(pattern)

        return patterns

    def _detect_data_exfiltration(self, events: List[AuditEvent]) -> List[Dict[str, Any]]:
        """
        Detect potential data exfiltration.

        Args:
            events: List of audit events to analyze

        Returns:
            List[Dict[str, Any]]: Detected patterns
        """
        patterns = []

        # Filter for data export/download events
        data_export_events = [
            e for e in events
            if e.category == AuditCategory.DATA_ACCESS and
               e.action in ["export", "download", "extract", "bulk_access"]
        ]

        if not data_export_events:
            return patterns

        # Group by user
        grouped_exports = defaultdict(list)
        for event in data_export_events:
            user = event.user or "unknown"
            grouped_exports[user].append(event)

        # Check thresholds
        for user, exports in grouped_exports.items():
            # Extract volume information when available
            total_volume = 0
            for event in exports:
                if 'data_size_bytes' in event.details:
                    try:
                        total_volume += int(event.details['data_size_bytes'])
                    except (ValueError, TypeError):
                        pass

            # Check for volume-based or count-based thresholds
            volume_threshold = 100 * 1024 * 1024  # 100MB
            count_threshold = 5  # 5 export operations

            if total_volume > volume_threshold or len(exports) >= count_threshold:
                pattern = {
                    'type': 'data_exfiltration',
                    'user': user,
                    'export_count': len(exports),
                    'total_volume_bytes': total_volume,
                    'event_ids': [e.event_id for e in exports],
                    'description': f"Potential data exfiltration by user {user}: {len(exports)} exports, {total_volume / (1024*1024):.2f} MB total",
                    'severity': 'high',
                    'timestamp': datetime.datetime.utcnow().isoformat() + 'Z'
                }
                patterns.append(pattern)

        return patterns

    def _detect_unauthorized_configuration(self, events: List[AuditEvent]) -> List[Dict[str, Any]]:
        """
        Detect unauthorized configuration changes.

        Args:
            events: List of audit events to analyze

        Returns:
            List[Dict[str, Any]]: Detected patterns
        """
        patterns = []

        # Filter for configuration events
        config_events = [
            e for e in events
            if e.category == AuditCategory.CONFIGURATION
        ]

        if not config_events:
            return patterns

        # Check for failed/unauthorized changes
        unauthorized_changes = [
            e for e in config_events
            if e.status == "failure" or
               (e.details and e.details.get("reason") == "unauthorized")
        ]

        if unauthorized_changes:
            # Group by user
            grouped_changes = defaultdict(list)
            for event in unauthorized_changes:
                user = event.user or "unknown"
                grouped_changes[user].append(event)

            # Generate pattern for each user
            for user, changes in grouped_changes.items():
                pattern = {
                    'type': 'unauthorized_configuration',
                    'user': user,
                    'change_count': len(changes),
                    'event_ids': [e.event_id for e in changes],
                    'description': f"Detected {len(changes)} unauthorized configuration change attempts by user {user}",
                    'severity': 'high',
                    'timestamp': datetime.datetime.utcnow().isoformat() + 'Z'
                }
                patterns.append(pattern)

        return patterns


class SecurityAlertManager:
    """
    Manages security alerts generated from audit events.

    This class provides functionality for storing, querying, and
    updating security alerts and coordinating responses.
    """

    def __init__(self, alert_storage_path: Optional[str] = None):
        """
        Initialize the security alert manager.

        Args:
            alert_storage_path: Path to store alerts (optional)
        """
        self.alerts: Dict[str, SecurityAlert] = {}
        self.storage_path = alert_storage_path
        self.notification_handlers: List[Callable[[SecurityAlert], None]] = []
        self._lock = threading.RLock()
        self.logger = logging.getLogger(__name__)

        # Load existing alerts if storage path is provided
        if alert_storage_path:
            self._load_alerts()

    def add_alert(self, alert: SecurityAlert) -> str:
        """
        Add a new security alert.

        Args:
            alert: The security alert to add

        Returns:
            str: The ID of the added alert
        """
        with self._lock:
            self.alerts[alert.alert_id] = alert

            # Save alerts if storage path is provided
            if self.storage_path:
                self._save_alerts()

            # Notify handlers
            self._notify_handlers(alert)

            return alert.alert_id

    def get_alert(self, alert_id: str) -> Optional[SecurityAlert]:
        """
        Get a security alert by ID.

        Args:
            alert_id: ID of the alert to get

        Returns:
            SecurityAlert: The requested alert, or None if not found
        """
        with self._lock:
            return self.alerts.get(alert_id)

    def update_alert(self, alert_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update an existing security alert.

        Args:
            alert_id: ID of the alert to update
            updates: Dictionary of updates to apply

        Returns:
            bool: Whether the update was successful
        """
        with self._lock:
            if alert_id not in self.alerts:
                return False

            alert = self.alerts[alert_id]

            # Apply updates
            for key, value in updates.items():
                if hasattr(alert, key):
                    setattr(alert, key, value)

            # Save alerts if storage path is provided
            if self.storage_path:
                self._save_alerts()

            return True

    def get_alerts(self, filters: Optional[Dict[str, Any]] = None) -> List[SecurityAlert]:
        """
        Get alerts matching specified filters.

        Args:
            filters: Dictionary of filters to apply

        Returns:
            List[SecurityAlert]: Alerts matching the filters
        """
        with self._lock:
            if not filters:
                return list(self.alerts.values())

            result = []
            for alert in self.alerts.values():
                match = True
                for key, value in filters.items():
                    if not hasattr(alert, key) or getattr(alert, key) != value:
                        match = False
                        break

                if match:
                    result.append(alert)

            return result

    def add_notification_handler(self, handler: Callable[[SecurityAlert], None]) -> None:
        """
        Add a handler for alert notifications.

        Args:
            handler: Function that handles alert notifications
        """
        with self._lock:
            self.notification_handlers.append(handler)

    def _notify_handlers(self, alert: SecurityAlert) -> None:
        """
        Notify all handlers of a new alert.

        Args:
            alert: The alert to notify about
        """
        for handler in self.notification_handlers:
            try:
                handler(alert)
            except Exception as e:
                self.logger.error(f"Error in notification handler: {str(e)}")

    def _load_alerts(self) -> None:
        """Load alerts from storage."""
        if not os.path.exists(self.storage_path):
            return

        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                alerts_data = json.load(f)

            self.alerts = {}
            for alert_id, alert_dict in alerts_data.items():
                self.alerts[alert_id] = SecurityAlert(**alert_dict)

            self.logger.info(f"Loaded {len(self.alerts)} alerts from storage")

        except Exception as e:
            self.logger.error(f"Error loading alerts: {str(e)}")

    def _save_alerts(self) -> None:
        """Save alerts to storage."""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

            # Convert alerts to dictionary
            alerts_dict = {alert_id: alert.to_dict() for alert_id, alert in self.alerts.items()}

            # Write to file
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(alerts_dict, f, indent=2)

            self.logger.debug(f"Saved {len(self.alerts)} alerts to storage")

        except Exception as e:
            self.logger.error(f"Error saving alerts: {str(e)}")
