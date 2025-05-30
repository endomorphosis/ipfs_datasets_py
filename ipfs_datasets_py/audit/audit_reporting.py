"""
Audit Reporting Module

This module provides comprehensive audit reporting capabilities that go beyond
basic visualizations. It analyzes audit events to generate actionable insights,
risk assessments, and compliance reports.

Key features:
- Security anomaly detection and risk scoring
- Compliance status reporting against common standards
- Operational efficiency metrics and recommendations
- Integration with visualization for comprehensive dashboards
- Pattern detection across multiple event types
- Exportable reports in multiple formats (PDF, HTML, JSON)
"""

import os
import json
import time
import datetime
import logging
import threading
from typing import Dict, List, Any, Optional, Union, Callable, Set, Tuple
from collections import defaultdict, Counter
from pathlib import Path
import uuid

# Try to import optional dependencies
try:
    import pandas as pd
    import numpy as np
    ANALYSIS_LIBS_AVAILABLE = True
except ImportError:
    ANALYSIS_LIBS_AVAILABLE = False

try:
    import matplotlib.pyplot as plt
    import seaborn as sns
    VISUALIZATION_LIBS_AVAILABLE = True
except ImportError:
    VISUALIZATION_LIBS_AVAILABLE = False

try:
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
    INTERACTIVE_LIBS_AVAILABLE = True
except ImportError:
    INTERACTIVE_LIBS_AVAILABLE = False

try:
    from jinja2 import Template
    TEMPLATE_ENGINE_AVAILABLE = True
except ImportError:
    TEMPLATE_ENGINE_AVAILABLE = False

try:
    from weasyprint import HTML
    PDF_EXPORT_AVAILABLE = True
except ImportError:
    PDF_EXPORT_AVAILABLE = False

# Import from audit_logger module
from ipfs_datasets_py.audit.audit_logger import (
    AuditLogger, AuditEvent, AuditLevel, AuditCategory, AuditHandler
)

# Import metrics aggregator for data processing
from ipfs_datasets_py.audit.audit_visualization import (
    AuditMetricsAggregator, AuditVisualizer
)


class AuditPatternDetector:
    """
    Analyzes audit events to detect patterns, anomalies, and potential security issues.

    This class uses statistical methods to identify unusual patterns in audit data,
    such as brute force attempts, privilege escalation, data exfiltration patterns,
    or unusual system access.
    """

    def __init__(self, metrics_aggregator: AuditMetricsAggregator):
        """
        Initialize the pattern detector.

        Args:
            metrics_aggregator: The metrics aggregator containing audit data
        """
        self.metrics = metrics_aggregator
        self._lock = threading.RLock()
        self.patterns = []
        self.anomalies = []
        self.risk_scores = {}

    def detect_authentication_patterns(self) -> List[Dict[str, Any]]:
        """
        Detect patterns in authentication events.

        Returns:
            List of detected patterns with details
        """
        patterns = []
        with self._lock:
            # Process login failures
            for user, failures in self.metrics.detailed['login_failures'].items():
                successes = self.metrics.detailed['login_failures'].get(user, 0)

                # Detect potential brute force patterns (high failure rate)
                if failures > 5 and (successes == 0 or failures / (successes + failures) > 0.7):
                    patterns.append({
                        'type': 'brute_force_suspected',
                        'user': user,
                        'failures': failures,
                        'successes': successes,
                        'failure_rate': failures / (successes + failures) if successes > 0 else 1.0,
                        'severity': 'high',
                        'recommendation': 'Investigate potential brute force attempt'
                    })

                # Detect unusual login times
                # This would need time-based analysis which we could implement
                # with the time series data in the metrics aggregator

            # Add additional patterns here

        return patterns

    def detect_access_patterns(self) -> List[Dict[str, Any]]:
        """
        Detect patterns in resource access events.

        Returns:
            List of detected patterns with details
        """
        patterns = []
        with self._lock:
            # Detect unusual access patterns
            for resource_id, user_accesses in self.metrics.detailed['resource_access'].items():
                # Check for unusual spikes in access
                for user, count in user_accesses.items():
                    # Calculate Z-score if we have enough data
                    if len(user_accesses) > 5:
                        values = list(user_accesses.values())
                        if ANALYSIS_LIBS_AVAILABLE:
                            mean = np.mean(values)
                            std = np.std(values) if np.std(values) > 0 else 1
                            z_score = (count - mean) / std

                            if z_score > 2:  # More than 2 standard deviations
                                patterns.append({
                                    'type': 'unusual_access_frequency',
                                    'resource_id': resource_id,
                                    'user': user,
                                    'access_count': count,
                                    'z_score': z_score,
                                    'severity': 'medium' if z_score < 3 else 'high',
                                    'recommendation': 'Review access patterns for this resource'
                                })

                # Check for modifications without proper read access first
                for user, mod_count in self.metrics.detailed['resource_modifications'].get(resource_id, {}).items():
                    read_count = user_accesses.get(user, 0)
                    if mod_count > 0 and read_count == 0:
                        patterns.append({
                            'type': 'modification_without_read',
                            'resource_id': resource_id,
                            'user': user,
                            'modification_count': mod_count,
                            'severity': 'high',
                            'recommendation': 'Investigate how resource was modified without read access'
                        })

            # Add additional patterns here

        return patterns

    def detect_system_patterns(self) -> List[Dict[str, Any]]:
        """
        Detect patterns in system events.

        Returns:
            List of detected patterns with details
        """
        patterns = []
        with self._lock:
            # Look for configuration changes followed by errors
            # This would require temporal analysis of the time series data

            # Look for system restarts or critical errors
            error_count = self.metrics.totals['by_level'].get(str(AuditLevel.ERROR), 0)
            critical_count = self.metrics.totals['by_level'].get(str(AuditLevel.CRITICAL), 0)

            if critical_count > 0:
                patterns.append({
                    'type': 'critical_errors',
                    'count': critical_count,
                    'severity': 'high',
                    'recommendation': 'Review critical system errors immediately'
                })

            if error_count > 10:
                patterns.append({
                    'type': 'high_error_rate',
                    'count': error_count,
                    'severity': 'medium',
                    'recommendation': 'Investigate system errors'
                })

            # Add additional patterns here

        return patterns

    def detect_compliance_patterns(self) -> List[Dict[str, Any]]:
        """
        Detect patterns related to compliance requirements.

        Returns:
            List of detected patterns with details
        """
        patterns = []
        with self._lock:
            # Check for compliance violations
            for requirement_id, violations in self.metrics.detailed['compliance_violations'].items():
                if violations > 0:
                    patterns.append({
                        'type': 'compliance_violation',
                        'requirement_id': requirement_id,
                        'violations': violations,
                        'severity': 'high',
                        'recommendation': f'Address compliance requirement {requirement_id}'
                    })

            # Check for sensitive data access
            for sensitivity, access_types in self.metrics.detailed['data_access_by_sensitivity'].items():
                if sensitivity in ['high', 'restricted', 'confidential']:
                    total = sum(access_types.values())
                    if total > 0:
                        patterns.append({
                            'type': 'sensitive_data_access',
                            'sensitivity': sensitivity,
                            'access_count': total,
                            'severity': 'medium',
                            'recommendation': f'Review access to {sensitivity} data'
                        })

            # Add additional patterns here

        return patterns

    def calculate_risk_scores(self) -> Dict[str, float]:
        """
        Calculate risk scores based on detected patterns.

        Returns:
            Dictionary of risk categories and their scores (0-1)
        """
        # Detect all patterns
        auth_patterns = self.detect_authentication_patterns()
        access_patterns = self.detect_access_patterns()
        system_patterns = self.detect_system_patterns()
        compliance_patterns = self.detect_compliance_patterns()

        # Store all detected patterns
        self.patterns = auth_patterns + access_patterns + system_patterns + compliance_patterns

        # Calculate risk scores (simplified)
        risk_scores = {
            'authentication': 0.0,
            'access_control': 0.0,
            'system_integrity': 0.0,
            'compliance': 0.0,
            'overall': 0.0
        }

        # Authentication risk
        auth_high = sum(1 for p in auth_patterns if p['severity'] == 'high')
        auth_med = sum(1 for p in auth_patterns if p['severity'] == 'medium')
        if auth_patterns:
            risk_scores['authentication'] = min(1.0, (auth_high * 0.3 + auth_med * 0.1) / len(auth_patterns) + 0.1)

        # Access control risk
        access_high = sum(1 for p in access_patterns if p['severity'] == 'high')
        access_med = sum(1 for p in access_patterns if p['severity'] == 'medium')
        if access_patterns:
            risk_scores['access_control'] = min(1.0, (access_high * 0.3 + access_med * 0.1) / len(access_patterns) + 0.1)

        # System integrity risk
        system_high = sum(1 for p in system_patterns if p['severity'] == 'high')
        system_med = sum(1 for p in system_patterns if p['severity'] == 'medium')
        if system_patterns:
            risk_scores['system_integrity'] = min(1.0, (system_high * 0.3 + system_med * 0.1) / len(system_patterns) + 0.1)

        # Compliance risk
        compliance_high = sum(1 for p in compliance_patterns if p['severity'] == 'high')
        compliance_med = sum(1 for p in compliance_patterns if p['severity'] == 'medium')
        if compliance_patterns:
            risk_scores['compliance'] = min(1.0, (compliance_high * 0.3 + compliance_med * 0.1) / len(compliance_patterns) + 0.1)

        # Overall risk (weighted average)
        weights = {
            'authentication': 0.25,
            'access_control': 0.25,
            'system_integrity': 0.25,
            'compliance': 0.25
        }

        risk_scores['overall'] = sum(risk_scores[k] * weights[k] for k in weights)

        # Store and return
        self.risk_scores = risk_scores
        return risk_scores

    def get_anomalies(self, threshold: float = 0.7) -> List[Dict[str, Any]]:
        """
        Get detected anomalies above a specific risk threshold.

        Args:
            threshold: Risk threshold for filtering anomalies (0-1)

        Returns:
            List of anomalies with details
        """
        # Calculate risk scores if not already done
        if not self.risk_scores:
            self.calculate_risk_scores()

        # Filter high-risk patterns
        anomalies = [
            pattern for pattern in self.patterns
            if pattern['severity'] == 'high' or
               (pattern['severity'] == 'medium' and self.risk_scores.get('overall', 0) >= threshold)
        ]

        # Store and return
        self.anomalies = anomalies
        return anomalies


class AuditComplianceAnalyzer:
    """
    Analyzes audit data for compliance with various standards and regulations.

    This class evaluates audit events against common compliance frameworks
    and generates reports on the system's compliance status.
    """

    # Common compliance frameworks
    COMPLIANCE_FRAMEWORKS = {
        'gdpr': {
            'name': 'General Data Protection Regulation',
            'requirements': {
                'data_access_logging': 'All data access must be logged',
                'breach_notification': 'Security breaches must be detected and reported',
                'consent_tracking': 'User consent for data processing must be tracked',
                'data_minimization': 'Only necessary data should be processed',
                'accountability': 'Evidence of compliance must be maintained'
            }
        },
        'hipaa': {
            'name': 'Health Insurance Portability and Accountability Act',
            'requirements': {
                'access_controls': 'Implement technical policies and procedures for electronic PHI access',
                'audit_controls': 'Implement hardware, software, and procedural mechanisms to record and examine activity',
                'integrity_controls': 'Implement policies and procedures to protect electronic PHI from improper alteration or destruction',
                'authentication': 'Implement procedures to verify that a person seeking access is the claimed identity',
                'transmission_security': 'Implement technical security measures to guard against unauthorized access during transmission'
            }
        },
        'soc2': {
            'name': 'Service Organization Control 2',
            'requirements': {
                'access_control': 'Access to data and systems should be restricted and monitored',
                'change_management': 'Changes to systems should be authorized and logged',
                'incident_response': 'Security incidents should be detected, reported, and addressed',
                'risk_management': 'Risks should be identified and mitigated',
                'monitoring': 'Systems should be monitored for security and availability'
            }
        }
    }

    def __init__(self,
                 metrics_aggregator: AuditMetricsAggregator,
                 pattern_detector: Optional[AuditPatternDetector] = None,
                 frameworks: Optional[List[str]] = None):
        """
        Initialize the compliance analyzer.

        Args:
            metrics_aggregator: The metrics aggregator containing audit data
            pattern_detector: Optional pattern detector for risk assessment
            frameworks: List of compliance frameworks to analyze against
        """
        self.metrics = metrics_aggregator
        self.pattern_detector = pattern_detector
        self.frameworks = frameworks or ['gdpr', 'hipaa', 'soc2']
        self._lock = threading.RLock()
        self.compliance_status = {}

    def analyze_compliance(self) -> Dict[str, Any]:
        """
        Analyze audit data for compliance with selected frameworks.

        Returns:
            Compliance status report for each framework
        """
        compliance_status = {}

        with self._lock:
            # Analyze each selected framework
            for framework_id in self.frameworks:
                if framework_id not in self.COMPLIANCE_FRAMEWORKS:
                    continue

                framework = self.COMPLIANCE_FRAMEWORKS[framework_id]
                requirements = framework['requirements']

                # Initialize compliance status for this framework
                status = {
                    'name': framework['name'],
                    'requirements': {},
                    'compliant_count': 0,
                    'total_requirements': len(requirements),
                    'compliance_percentage': 0.0
                }

                # Check each requirement
                for req_id, req_description in requirements.items():
                    # Call the appropriate method to check this requirement
                    method_name = f"check_{framework_id}_{req_id}"
                    if hasattr(self, method_name) and callable(getattr(self, method_name)):
                        compliant, details = getattr(self, method_name)()
                    else:
                        # Default to a generic check if specific method doesn't exist
                        compliant, details = self._generic_compliance_check(framework_id, req_id)

                    status['requirements'][req_id] = {
                        'description': req_description,
                        'compliant': compliant,
                        'details': details
                    }

                    if compliant:
                        status['compliant_count'] += 1

                # Calculate overall compliance percentage
                if status['total_requirements'] > 0:
                    status['compliance_percentage'] = (
                        status['compliant_count'] / status['total_requirements'] * 100
                    )

                compliance_status[framework_id] = status

            # Store results
            self.compliance_status = compliance_status
            return compliance_status

    def _generic_compliance_check(self, framework_id: str, requirement_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Perform a generic compliance check based on audit events.

        Args:
            framework_id: ID of the compliance framework
            requirement_id: ID of the specific requirement

        Returns:
            Tuple of (compliance_status, details)
        """
        # Get relevant events for this requirement
        category_map = {
            'data_access_logging': AuditCategory.DATA_ACCESS,
            'access_controls': AuditCategory.AUTHENTICATION,
            'access_control': AuditCategory.AUTHENTICATION,
            'audit_controls': AuditCategory.SYSTEM,
            'monitoring': AuditCategory.SYSTEM,
            'change_management': AuditCategory.CONFIGURATION,
            'transmission_security': AuditCategory.SECURITY,
            'incident_response': AuditCategory.SECURITY,
            'authentication': AuditCategory.AUTHENTICATION,
            'integrity_controls': AuditCategory.DATA_MODIFICATION,
            'risk_management': AuditCategory.SECURITY,
        }

        # Map the requirement to a relevant audit category
        relevant_category = category_map.get(requirement_id)

        # Check for existence of relevant audit events
        if relevant_category:
            category_count = self.metrics.totals['by_category'].get(str(relevant_category), 0)
            has_relevant_events = category_count > 0

            # Check for any compliance violations related to this requirement
            violations = self.metrics.detailed['compliance_violations'].get(f"{framework_id}_{requirement_id}", 0)

            details = {
                'relevant_events': category_count,
                'violations': violations,
                'missing_controls': [],
                'recommendation': ""
            }

            if violations > 0:
                compliant = False
                details['recommendation'] = f"Address {violations} compliance violations related to {requirement_id}"
            elif not has_relevant_events:
                compliant = False
                details['missing_controls'].append(f"No {relevant_category.name.lower()} events logged")
                details['recommendation'] = f"Implement {requirement_id} controls and ensure they are logged"
            else:
                compliant = True
                details['recommendation'] = "Continue monitoring for compliance"

            return compliant, details
        else:
            # Generic fallback if we can't map to a specific category
            return False, {
                'relevant_events': 0,
                'violations': 0,
                'missing_controls': ["Unable to automatically verify this requirement"],
                'recommendation': f"Manually verify compliance with {requirement_id}"
            }

    # Specific compliance check methods
    def check_gdpr_data_access_logging(self) -> Tuple[bool, Dict[str, Any]]:
        """Check GDPR data access logging compliance."""
        data_access_events = self.metrics.totals['by_category'].get(str(AuditCategory.DATA_ACCESS), 0)
        data_mod_events = self.metrics.totals['by_category'].get(str(AuditCategory.DATA_MODIFICATION), 0)

        # Check if we have sufficient logging of data access
        has_access_logging = data_access_events > 0
        has_user_info = any(user for user in self.metrics.totals['by_user'])
        has_resource_info = any(resource for resource in self.metrics.totals['by_resource_type'])

        details = {
            'access_events_count': data_access_events,
            'modification_events_count': data_mod_events,
            'user_information_present': has_user_info,
            'resource_information_present': has_resource_info,
            'missing_controls': [],
            'recommendation': ""
        }

        compliant = True

        if not has_access_logging:
            compliant = False
            details['missing_controls'].append("No data access events logged")
            details['recommendation'] = "Implement comprehensive data access logging"
        elif not has_user_info:
            compliant = False
            details['missing_controls'].append("User information missing from logs")
            details['recommendation'] = "Include user identity in all data access logs"
        elif not has_resource_info:
            compliant = False
            details['missing_controls'].append("Resource information missing from logs")
            details['recommendation'] = "Include resource type and ID in all data access logs"
        else:
            details['recommendation'] = "Continue monitoring data access events"

        return compliant, details

    def check_hipaa_audit_controls(self) -> Tuple[bool, Dict[str, Any]]:
        """Check HIPAA audit controls compliance."""
        # Check for comprehensive audit logging across categories
        categories = self.metrics.totals['by_category']
        has_auth_events = int(categories.get(str(AuditCategory.AUTHENTICATION), 0)) > 0
        has_access_events = int(categories.get(str(AuditCategory.DATA_ACCESS), 0)) > 0
        has_mod_events = int(categories.get(str(AuditCategory.DATA_MODIFICATION), 0)) > 0
        has_security_events = int(categories.get(str(AuditCategory.SECURITY), 0)) > 0

        details = {
            'authentication_logging': has_auth_events,
            'access_logging': has_access_events,
            'modification_logging': has_mod_events,
            'security_logging': has_security_events,
            'missing_controls': [],
            'recommendation': ""
        }

        compliant = True

        if not has_auth_events:
            compliant = False
            details['missing_controls'].append("No authentication events logged")

        if not has_access_events:
            compliant = False
            details['missing_controls'].append("No data access events logged")

        if not has_mod_events:
            compliant = False
            details['missing_controls'].append("No data modification events logged")

        if not has_security_events:
            compliant = False
            details['missing_controls'].append("No security-related events logged")

        if not compliant:
            details['recommendation'] = "Implement comprehensive audit logging across all required categories"
        else:
            details['recommendation'] = "Continue monitoring audit controls effectiveness"

        return compliant, details

    def check_soc2_monitoring(self) -> Tuple[bool, Dict[str, Any]]:
        """Check SOC2 monitoring compliance."""
        # Check for evidence of system monitoring
        system_events = self.metrics.totals['by_category'].get(str(AuditCategory.SYSTEM), 0)
        security_events = self.metrics.totals['by_category'].get(str(AuditCategory.SECURITY), 0)
        operational_events = self.metrics.totals['by_category'].get(str(AuditCategory.OPERATIONAL), 0)

        # Check for critical events monitoring
        has_error_events = self.metrics.totals['by_level'].get(str(AuditLevel.ERROR), 0) > 0
        has_critical_events = self.metrics.totals['by_level'].get(str(AuditLevel.CRITICAL), 0) > 0

        details = {
            'system_events_count': system_events,
            'security_events_count': security_events,
            'operational_events_count': operational_events,
            'error_monitoring': has_error_events,
            'critical_event_monitoring': has_critical_events,
            'missing_controls': [],
            'recommendation': ""
        }

        compliant = True

        if system_events == 0:
            compliant = False
            details['missing_controls'].append("No system monitoring events logged")

        if security_events == 0:
            compliant = False
            details['missing_controls'].append("No security monitoring events logged")

        if not has_error_events and not has_critical_events:
            compliant = False
            details['missing_controls'].append("No evidence of error or critical event monitoring")

        if not compliant:
            details['recommendation'] = "Enhance system monitoring to cover all required areas"
        else:
            details['recommendation'] = "Continue comprehensive system monitoring"

        return compliant, details

    def get_compliance_summary(self) -> Dict[str, Any]:
        """
        Get a summary of compliance status across all frameworks.

        Returns:
            Summary of compliance status
        """
        if not self.compliance_status:
            self.analyze_compliance()

        # Calculate overall compliance metrics
        total_requirements = 0
        total_compliant = 0

        for framework_id, status in self.compliance_status.items():
            total_requirements += status['total_requirements']
            total_compliant += status['compliant_count']

        overall_percentage = (
            total_compliant / total_requirements * 100 if total_requirements > 0 else 0
        )

        # Generate summary
        summary = {
            'overall_compliance_percentage': overall_percentage,
            'frameworks_analyzed': len(self.compliance_status),
            'total_requirements': total_requirements,
            'compliant_requirements': total_compliant,
            'non_compliant_requirements': total_requirements - total_compliant,
            'framework_scores': {
                framework_id: {
                    'name': status['name'],
                    'compliance_percentage': status['compliance_percentage'],
                    'compliant_count': status['compliant_count'],
                    'total_requirements': status['total_requirements']
                }
                for framework_id, status in self.compliance_status.items()
            },
            'top_issues': self._get_top_compliance_issues(3)
        }

        return summary

    def _get_top_compliance_issues(self, limit: int = 3) -> List[Dict[str, Any]]:
        """
        Get the top compliance issues to address.

        Args:
            limit: Maximum number of issues to return

        Returns:
            List of top compliance issues
        """
        issues = []

        for framework_id, status in self.compliance_status.items():
            for req_id, details in status['requirements'].items():
                if not details['compliant']:
                    issues.append({
                        'framework': status['name'],
                        'requirement': details['description'],
                        'details': details['details'],
                        'recommendation': details['details'].get('recommendation', '')
                    })

        # Sort issues by recommendation importance (simplified)
        issues.sort(key=lambda x: 'Implement' in x['recommendation'], reverse=True)

        return issues[:limit]


class AuditReportGenerator:
    """
    Generates comprehensive audit reports with insights and recommendations.

    This class combines data from the metrics aggregator, pattern detector,
    and compliance analyzer to create actionable audit reports.
    """

    def __init__(self,
                 metrics_aggregator: AuditMetricsAggregator,
                 visualizer: Optional[AuditVisualizer] = None,
                 pattern_detector: Optional[AuditPatternDetector] = None,
                 compliance_analyzer: Optional[AuditComplianceAnalyzer] = None,
                 output_dir: str = "./audit_reports"):
        """
        Initialize the report generator.

        Args:
            metrics_aggregator: The metrics aggregator containing audit data
            visualizer: Optional visualizer for creating charts
            pattern_detector: Optional pattern detector for risk assessment
            compliance_analyzer: Optional compliance analyzer for compliance status
            output_dir: Directory for report output files
        """
        self.metrics = metrics_aggregator
        self.visualizer = visualizer
        self.output_dir = output_dir

        # Create pattern detector if not provided
        if pattern_detector is None:
            self.pattern_detector = AuditPatternDetector(metrics_aggregator)
        else:
            self.pattern_detector = pattern_detector

        # Create compliance analyzer if not provided
        if compliance_analyzer is None:
            self.compliance_analyzer = AuditComplianceAnalyzer(
                metrics_aggregator, self.pattern_detector
            )
        else:
            self.compliance_analyzer = compliance_analyzer

        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

    def generate_security_report(self) -> Dict[str, Any]:
        """
        Generate a security-focused audit report.

        Returns:
            Security report data structure
        """
        # Detect patterns and calculate risk scores
        risk_scores = self.pattern_detector.calculate_risk_scores()
        anomalies = self.pattern_detector.get_anomalies()

        # Get metrics summary
        metrics_summary = self.metrics.get_metrics_summary()

        # Count security-related events
        security_events = self.metrics.totals['by_category'].get(str(AuditCategory.SECURITY), 0)
        auth_events = self.metrics.totals['by_category'].get(str(AuditCategory.AUTHENTICATION), 0)
        auth_failures = sum(self.metrics.detailed['login_failures'].values())

        # Generate security report
        report = {
            'report_type': 'security',
            'timestamp': datetime.datetime.now().isoformat(),
            'report_id': str(uuid.uuid4()),
            'summary': {
                'total_events': metrics_summary['total_events'],
                'security_events': security_events,
                'authentication_events': auth_events,
                'authentication_failures': auth_failures,
                'critical_events': self.metrics.totals['critical_events'],
                'overall_risk_score': risk_scores['overall'],
                'risk_scores': risk_scores,
                'anomalies_detected': len(anomalies)
            },
            'risk_assessment': {
                'scores': risk_scores,
                'factors': self._get_risk_factors(),
                'trends': self._get_risk_trends()
            },
            'anomalies': anomalies,
            'top_security_events': self._get_top_security_events(),
            'recommendations': self._generate_security_recommendations()
        }

        return report

    def generate_compliance_report(self) -> Dict[str, Any]:
        """
        Generate a compliance-focused audit report.

        Returns:
            Compliance report data structure
        """
        # Analyze compliance status
        compliance_status = self.compliance_analyzer.analyze_compliance()
        compliance_summary = self.compliance_analyzer.get_compliance_summary()

        # Generate compliance report
        report = {
            'report_type': 'compliance',
            'timestamp': datetime.datetime.now().isoformat(),
            'report_id': str(uuid.uuid4()),
            'summary': {
                'overall_compliance_percentage': compliance_summary['overall_compliance_percentage'],
                'frameworks_analyzed': compliance_summary['frameworks_analyzed'],
                'compliant_requirements': compliance_summary['compliant_requirements'],
                'non_compliant_requirements': compliance_summary['non_compliant_requirements']
            },
            'frameworks': {
                framework_id: {
                    'name': status['name'],
                    'compliance_percentage': status['compliance_percentage'],
                    'compliant_count': status['compliant_count'],
                    'total_requirements': status['total_requirements'],
                    'requirements': status['requirements']
                }
                for framework_id, status in compliance_status.items()
            },
            'top_issues': compliance_summary['top_issues'],
            'recommendations': self._generate_compliance_recommendations()
        }

        return report

    def generate_operational_report(self) -> Dict[str, Any]:
        """
        Generate an operations-focused audit report.

        Returns:
            Operational report data structure
        """
        # Get metrics summary
        metrics_summary = self.metrics.get_metrics_summary()

        # Analyze performance metrics
        performance = {
            'operation_durations': {
                action: {
                    'avg': self.metrics.detailed['avg_duration'].get(action, 0),
                    'max': self.metrics.detailed['max_duration'].get(action, 0),
                    'p95': self.metrics.detailed['p95_duration'].get(action, 0)
                }
                for action in self.metrics.detailed['avg_duration']
            },
            'slowest_operations': self._get_slowest_operations(5),
            'error_rates': self._get_error_rates()
        }

        # Generate operational report
        report = {
            'report_type': 'operational',
            'timestamp': datetime.datetime.now().isoformat(),
            'report_id': str(uuid.uuid4()),
            'summary': {
                'total_events': metrics_summary['total_events'],
                'event_distribution': {
                    'by_category': metrics_summary['by_category'],
                    'by_level': metrics_summary['by_level'],
                    'by_status': metrics_summary['by_status']
                },
                'error_percentage': metrics_summary.get('error_percentage', 0)
            },
            'performance_metrics': performance,
            'resource_usage': self._get_resource_usage(),
            'top_users': self._get_top_users(5),
            'top_resources': self._get_top_resources(5),
            'recommendations': self._generate_operational_recommendations()
        }

        return report

    def generate_comprehensive_report(self) -> Dict[str, Any]:
        """
        Generate a comprehensive audit report combining security, compliance, and operations.

        Returns:
            Comprehensive report data structure
        """
        # Generate component reports
        security_report = self.generate_security_report()
        compliance_report = self.generate_compliance_report()
        operational_report = self.generate_operational_report()

        # Combine into comprehensive report
        report = {
            'report_type': 'comprehensive',
            'timestamp': datetime.datetime.now().isoformat(),
            'report_id': str(uuid.uuid4()),
            'executive_summary': {
                'total_events': self.metrics.totals['total_events'],
                'overall_risk_score': security_report['summary']['overall_risk_score'],
                'overall_compliance_percentage': compliance_report['summary']['overall_compliance_percentage'],
                'error_percentage': operational_report['summary']['error_percentage'],
                'critical_findings': self._get_critical_findings(),
                'key_metrics': self._get_key_metrics()
            },
            'security': security_report,
            'compliance': compliance_report,
            'operations': operational_report,
            'top_recommendations': self._get_top_recommendations()
        }

        return report

    def export_report(self,
                      report: Dict[str, Any],
                      format: str = 'json',
                      output_file: Optional[str] = None) -> str:
        """
        Export a report in the specified format.

        Args:
            report: The report data structure to export
            format: Format to export ('json', 'html', 'pdf')
            output_file: Optional output file path

        Returns:
            Path to the exported report file
        """
        # Generate default output filename if not provided
        if output_file is None:
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = os.path.join(
                self.output_dir,
                f"{report['report_type']}_report_{timestamp}.{format}"
            )

        # Export in requested format
        if format == 'json':
            with open(output_file, 'w') as f:
                json.dump(report, f, indent=2)

        elif format == 'html':
            if not TEMPLATE_ENGINE_AVAILABLE:
                raise ImportError("Jinja2 is required for HTML export")

            # Load appropriate template based on report type
            template_path = os.path.join(
                os.path.dirname(__file__),
                f"templates/{report['report_type']}_report.html"
            )

            # If template doesn't exist, use a generic one
            if not os.path.exists(template_path):
                template_path = os.path.join(
                    os.path.dirname(__file__),
                    "templates/generic_report.html"
                )

            # If still no template, use an inline one
            if not os.path.exists(template_path):
                template_str = """
                <!DOCTYPE html>
                <html>
                <head>
                    <title>{{ report.report_type|title }} Audit Report</title>
                    <style>
                        body { font-family: Arial, sans-serif; margin: 40px; }
                        h1 { color: #2c3e50; }
                        h2 { color: #3498db; }
                        table { border-collapse: collapse; width: 100%; }
                        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                        th { background-color: #f2f2f2; }
                        tr:nth-child(even) { background-color: #f9f9f9; }
                        .risk-high { color: #e74c3c; }
                        .risk-medium { color: #f39c12; }
                        .risk-low { color: #27ae60; }
                    </style>
                </head>
                <body>
                    <h1>{{ report.report_type|title }} Audit Report</h1>
                    <p>Generated: {{ report.timestamp }}</p>

                    <h2>Summary</h2>
                    <table>
                        {% for key, value in report.summary.items() %}
                        <tr>
                            <th>{{ key|replace('_', ' ')|title }}</th>
                            <td>{{ value }}</td>
                        </tr>
                        {% endfor %}
                    </table>

                    {% if report.recommendations %}
                    <h2>Recommendations</h2>
                    <ul>
                        {% for rec in report.recommendations %}
                        <li>{{ rec }}</li>
                        {% endfor %}
                    </ul>
                    {% endif %}

                    <!-- Add more sections based on report type -->
                </body>
                </html>
                """

                # Render with inline template
                template = Template(template_str)
                html_content = template.render(report=report)
            else:
                # Load template from file
                with open(template_path, 'r') as f:
                    template = Template(f.read())

                # Render report
                html_content = template.render(report=report)

            # Write HTML file
            with open(output_file, 'w') as f:
                f.write(html_content)

        elif format == 'pdf':
            if not PDF_EXPORT_AVAILABLE:
                raise ImportError("WeasyPrint is required for PDF export")

            # First export as HTML
            html_path = output_file.replace('.pdf', '.html')
            self.export_report(report, 'html', html_path)

            # Convert HTML to PDF
            pdf = HTML(filename=html_path).write_pdf()

            # Write PDF file
            with open(output_file, 'wb') as f:
                f.write(pdf)

            # Remove temporary HTML file
            os.remove(html_path)

        else:
            raise ValueError(f"Unsupported export format: {format}")

        return output_file

    # Helper methods for report generation
    def _get_risk_factors(self) -> List[Dict[str, Any]]:
        """Get the factors contributing to the risk score."""
        # This would be implementation-specific based on your risk calculation
        factors = []

        # Check login failures
        auth_failures = sum(self.metrics.detailed['login_failures'].values())
        if auth_failures > 0:
            factors.append({
                'factor': 'authentication_failures',
                'value': auth_failures,
                'impact': 'high' if auth_failures > 10 else 'medium' if auth_failures > 5 else 'low',
                'description': f"{auth_failures} failed authentication attempts detected"
            })

        # Check critical events
        critical_events = self.metrics.totals['critical_events']
        if critical_events > 0:
            factors.append({
                'factor': 'critical_events',
                'value': critical_events,
                'impact': 'high',
                'description': f"{critical_events} critical severity events detected"
            })

        # Check security events
        security_events = self.metrics.totals['by_category'].get(str(AuditCategory.SECURITY), 0)
        if security_events > 0:
            factors.append({
                'factor': 'security_events',
                'value': security_events,
                'impact': 'medium',
                'description': f"{security_events} security-related events detected"
            })

        # Check sensitive data access
        sensitive_access = 0
        for sensitivity, access_types in self.metrics.detailed['data_access_by_sensitivity'].items():
            if sensitivity in ['high', 'restricted', 'confidential']:
                sensitive_access += sum(access_types.values())

        if sensitive_access > 0:
            factors.append({
                'factor': 'sensitive_data_access',
                'value': sensitive_access,
                'impact': 'high' if sensitive_access > 20 else 'medium',
                'description': f"{sensitive_access} accesses to sensitive data detected"
            })

        return factors

    def _get_risk_trends(self) -> Dict[str, Any]:
        """Get trends in risk factors over time."""
        # This would require historical data which is not available in the current implementation
        # But we can return a placeholder structure
        return {
            'trend_available': False,
            'message': "Risk trends require historical data across multiple reports"
        }

    def _get_top_security_events(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get the top security-related events."""
        # Filter security and authentication events
        security_events = []

        # Get all events from time series data that are security-related
        security_category = str(AuditCategory.SECURITY)
        auth_category = str(AuditCategory.AUTHENTICATION)

        # This is a simplified version since we don't have actual event objects
        # In a real implementation, you would use the actual events stored in the metrics

        # Add security events
        for action, count in self.metrics.totals['by_category_action'].get(security_category, {}).items():
            security_events.append({
                'category': 'SECURITY',
                'action': action,
                'count': count,
                'level': 'ERROR',  # Assumed severity
                'description': f"Security event: {action}"
            })

        # Add auth failure events
        for user, failures in self.metrics.detailed['login_failures'].items():
            if failures > 0:
                security_events.append({
                    'category': 'AUTHENTICATION',
                    'action': 'login_failure',
                    'count': failures,
                    'level': 'WARNING',
                    'user': user,
                    'description': f"{failures} failed login attempts for user {user}"
                })

        # Sort by count (descending) and return top events
        security_events.sort(key=lambda x: x['count'], reverse=True)
        return security_events[:limit]

    def _generate_security_recommendations(self) -> List[str]:
        """Generate security recommendations based on audit data."""
        recommendations = []

        # Get risk scores and anomalies
        risk_scores = self.pattern_detector.risk_scores
        anomalies = self.pattern_detector.anomalies

        # Add recommendations based on risk scores
        if risk_scores.get('authentication', 0) > 0.5:
            recommendations.append(
                "Enhance authentication security with multi-factor authentication and account lockout policies"
            )

        if risk_scores.get('access_control', 0) > 0.5:
            recommendations.append(
                "Review access control policies and implement least privilege principle"
            )

        if risk_scores.get('system_integrity', 0) > 0.5:
            recommendations.append(
                "Strengthen system integrity controls and monitoring"
            )

        # Add recommendations based on anomalies
        for anomaly in anomalies:
            if 'recommendation' in anomaly:
                recommendations.append(anomaly['recommendation'])

        # Check for other security indicators
        auth_failures = sum(self.metrics.detailed['login_failures'].values())
        if auth_failures > 10:
            recommendations.append(
                "Investigate brute force attempts and implement IP-based rate limiting"
            )

        # Add general recommendations if list is empty
        if not recommendations:
            recommendations.append(
                "Maintain current security controls and monitoring"
            )

        return recommendations

    def _generate_compliance_recommendations(self) -> List[str]:
        """Generate compliance recommendations based on audit data."""
        recommendations = []

        # Get compliance status
        compliance_summary = self.compliance_analyzer.get_compliance_summary()

        # Add recommendations based on compliance issues
        for issue in compliance_summary['top_issues']:
            if 'recommendation' in issue:
                recommendations.append(issue['recommendation'])

        # Check compliance percentage
        overall_percentage = compliance_summary['overall_compliance_percentage']
        if overall_percentage < 50:
            recommendations.append(
                "Develop a comprehensive compliance program addressing major gaps"
            )
        elif overall_percentage < 80:
            recommendations.append(
                "Focus on addressing specific compliance requirements with the lowest scores"
            )
        else:
            recommendations.append(
                "Continue monitoring compliance controls and address remaining minor issues"
            )

        return recommendations

    def _get_slowest_operations(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get the slowest operations by average duration."""
        operations = [
            {
                'action': action,
                'avg_duration': duration,
                'max_duration': self.metrics.detailed['max_duration'].get(action, 0),
                'p95_duration': self.metrics.detailed['p95_duration'].get(action, 0)
            }
            for action, duration in self.metrics.detailed['avg_duration'].items()
        ]

        # Sort by average duration (descending)
        operations.sort(key=lambda x: x['avg_duration'], reverse=True)
        return operations[:limit]

    def _get_error_rates(self) -> Dict[str, Any]:
        """Get error rates by category and action."""
        error_rates = {}

        # Calculate error rates by category
        for category, actions in self.metrics.detailed['error_counts'].items():
            category_total = sum(self.metrics.totals['by_category_action'].get(category, {}).values())
            category_errors = sum(actions.values())

            if category_total > 0:
                error_rate = category_errors / category_total
            else:
                error_rate = 0

            error_rates[category] = {
                'total_events': category_total,
                'error_events': category_errors,
                'error_rate': error_rate,
                'actions': {}
            }

            # Calculate error rates by action within this category
            for action, error_count in actions.items():
                action_total = self.metrics.totals['by_category_action'].get(category, {}).get(action, 0)

                if action_total > 0:
                    action_error_rate = error_count / action_total
                else:
                    action_error_rate = 0

                error_rates[category]['actions'][action] = {
                    'total_events': action_total,
                    'error_events': error_count,
                    'error_rate': action_error_rate
                }

        return error_rates

    def _get_resource_usage(self) -> Dict[str, Any]:
        """Get resource usage metrics (placeholder)."""
        # This would require system metrics which are not available in this implementation
        return {
            'data_available': False,
            'message': "Resource usage metrics require system monitoring integration"
        }

    def _get_top_users(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get the most active users by event count."""
        users = [
            {'user': user, 'event_count': count}
            for user, count in self.metrics.totals['by_user'].items()
            if user  # Skip empty user
        ]

        # Sort by event count (descending)
        users.sort(key=lambda x: x['event_count'], reverse=True)
        return users[:limit]

    def _get_top_resources(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get the most accessed resources by access count."""
        resources = []

        # Combine access and modification counts
        for resource_id, user_accesses in self.metrics.detailed['resource_access'].items():
            access_count = sum(user_accesses.values())
            mod_count = sum(self.metrics.detailed['resource_modifications'].get(resource_id, {}).values())

            resources.append({
                'resource_id': resource_id,
                'access_count': access_count,
                'modification_count': mod_count,
                'total_operations': access_count + mod_count
            })

        # Sort by total operations (descending)
        resources.sort(key=lambda x: x['total_operations'], reverse=True)
        return resources[:limit]

    def _generate_operational_recommendations(self) -> List[str]:
        """Generate operational recommendations based on audit data."""
        recommendations = []

        # Check error percentage
        metrics_summary = self.metrics.get_metrics_summary()
        error_percentage = metrics_summary.get('error_percentage', 0)

        if error_percentage > 10:
            recommendations.append(
                "Investigate and address high error rate in operations"
            )

        # Check slow operations
        slow_ops = self._get_slowest_operations(3)
        if slow_ops and slow_ops[0]['avg_duration'] > 1000:  # >1s
            recommendations.append(
                f"Optimize slow operation: {slow_ops[0]['action']} (avg: {slow_ops[0]['avg_duration']}ms)"
            )

        # Check resource type distribution
        resource_types = self.metrics.totals['by_resource_type']
        total_resources = sum(resource_types.values())

        if 'dataset' in resource_types and resource_types['dataset'] / total_resources > 0.8:
            recommendations.append(
                "Consider optimizing dataset access patterns to reduce load"
            )

        # Add general recommendations if list is empty
        if not recommendations:
            recommendations.append(
                "Current operational metrics indicate good performance"
            )

        return recommendations

    def _get_critical_findings(self) -> List[Dict[str, Any]]:
        """Get critical findings across all report types."""
        findings = []

        # Add high-risk anomalies
        for anomaly in self.pattern_detector.anomalies:
            if anomaly.get('severity') == 'high':
                findings.append({
                    'type': 'security',
                    'finding': anomaly['type'],
                    'details': anomaly.get('recommendation', ''),
                    'severity': 'high'
                })

        # Add compliance issues
        compliance_summary = self.compliance_analyzer.get_compliance_summary()
        for issue in compliance_summary['top_issues']:
            findings.append({
                'type': 'compliance',
                'finding': f"Non-compliance with {issue['framework']} requirement",
                'details': issue['requirement'],
                'severity': 'high'
            })

        # Add operational issues
        metrics_summary = self.metrics.get_metrics_summary()
        if metrics_summary.get('error_percentage', 0) > 20:
            findings.append({
                'type': 'operational',
                'finding': 'High error rate in operations',
                'details': f"Error rate: {metrics_summary.get('error_percentage')}%",
                'severity': 'high'
            })

        return findings

    def _get_key_metrics(self) -> Dict[str, Any]:
        """Get key metrics for executive summary."""
        metrics_summary = self.metrics.get_metrics_summary()

        return {
            'total_events': metrics_summary['total_events'],
            'event_distribution': {
                'by_category': dict(sorted(
                    metrics_summary['by_category'].items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:5]),
                'by_level': metrics_summary['by_level']
            },
            'error_percentage': metrics_summary.get('error_percentage', 0),
            'security_metrics': {
                'authentication_failures': sum(self.metrics.detailed['login_failures'].values()),
                'security_events': self.metrics.totals['by_category'].get(str(AuditCategory.SECURITY), 0),
                'critical_events': self.metrics.totals['critical_events']
            },
            'compliance_status': {
                'overall_percentage': self.compliance_analyzer.get_compliance_summary()['overall_compliance_percentage']
            }
        }

    def _get_top_recommendations(self) -> List[Dict[str, Any]]:
        """Get top recommendations across all report types."""
        recommendations = []

        # Add security recommendations
        for rec in self._generate_security_recommendations()[:2]:
            recommendations.append({
                'category': 'security',
                'recommendation': rec
            })

        # Add compliance recommendations
        for rec in self._generate_compliance_recommendations()[:2]:
            recommendations.append({
                'category': 'compliance',
                'recommendation': rec
            })

        # Add operational recommendations
        for rec in self._generate_operational_recommendations()[:2]:
            recommendations.append({
                'category': 'operational',
                'recommendation': rec
            })

        return recommendations


def setup_audit_reporting(
    audit_logger: AuditLogger,
    metrics_aggregator: Optional[AuditMetricsAggregator] = None,
    visualizer: Optional[AuditVisualizer] = None,
    output_dir: str = "./audit_reports"
) -> Tuple[AuditReportGenerator, AuditPatternDetector, AuditComplianceAnalyzer]:
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
    # Get metrics aggregator from existing or by setting up a new one
    if metrics_aggregator is None:
        from ipfs_datasets_py.audit.audit_visualization import (
            AuditMetricsAggregator, MetricsCollectionHandler, setup_audit_visualization
        )

        metrics_aggregator, visualizer, _ = setup_audit_visualization(audit_logger)

    # Initialize pattern detector
    pattern_detector = AuditPatternDetector(metrics_aggregator)

    # Initialize compliance analyzer
    compliance_analyzer = AuditComplianceAnalyzer(metrics_aggregator, pattern_detector)

    # Initialize report generator
    report_generator = AuditReportGenerator(
        metrics_aggregator=metrics_aggregator,
        visualizer=visualizer,
        pattern_detector=pattern_detector,
        compliance_analyzer=compliance_analyzer,
        output_dir=output_dir
    )

    return report_generator, pattern_detector, compliance_analyzer


def generate_comprehensive_audit_report(
    output_file: Optional[str] = None,
    audit_logger: Optional[AuditLogger] = None,
    metrics_aggregator: Optional[AuditMetricsAggregator] = None,
    report_format: str = 'html',
    include_security: bool = True,
    include_compliance: bool = True,
    include_operational: bool = True
) -> str:
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
    # Get audit logger instance if not provided
    if audit_logger is None:
        audit_logger = AuditLogger.get_instance()

    # Set up reporting components
    report_generator, _, _ = setup_audit_reporting(
        audit_logger=audit_logger,
        metrics_aggregator=metrics_aggregator
    )

    # Generate report based on included sections
    if include_security and include_compliance and include_operational:
        report = report_generator.generate_comprehensive_report()
    elif include_security:
        report = report_generator.generate_security_report()
    elif include_compliance:
        report = report_generator.generate_compliance_report()
    elif include_operational:
        report = report_generator.generate_operational_report()
    else:
        # Default to comprehensive if nothing specified
        report = report_generator.generate_comprehensive_report()

    # Export report in requested format
    report_path = report_generator.export_report(
        report=report,
        format=report_format,
        output_file=output_file
    )

    return report_path
