"""
Audit Logging Module for IPFS Datasets

This module provides comprehensive audit logging capabilities for the IPFS Datasets library,
focused on security, compliance, and operational monitoring requirements.

Features:
- Security event tracking (authentication, authorization, access control)
- Data access and modification audit trails
- Operation logs for system-level activities
- Compliance reporting for regulatory requirements
- Integration with existing provenance tracking
- Support for multiple output formats and destinations
- Real-time alerting for security-relevant events
- Adaptive security responses to detected threats
"""

from ipfs_datasets_py.audit.audit_logger import (
    AuditLogger,
    AuditEvent,
    AuditLevel,
    AuditCategory,
    AuditHandler
)
from ipfs_datasets_py.audit.handlers import (
    FileAuditHandler,
    JSONAuditHandler,
    SyslogAuditHandler,
    ElasticsearchAuditHandler,
    AlertingAuditHandler
)
from ipfs_datasets_py.audit.compliance import (
    ComplianceReport,
    ComplianceStandard,
    GDPRComplianceReporter,
    HIPAAComplianceReporter,
    SOC2ComplianceReporter
)
from ipfs_datasets_py.audit.intrusion import (
    IntrusionDetection,
    AnomalyDetector,
    SecurityAlertManager
)
from ipfs_datasets_py.audit.adaptive_security import (
    AdaptiveSecurityManager,
    ResponseAction,
    ResponseRule,
    SecurityResponse,
    RuleCondition
)

__all__ = [
    'AuditLogger',
    'AuditEvent',
    'AuditLevel',
    'AuditCategory',
    'AuditHandler',
    'FileAuditHandler',
    'JSONAuditHandler',
    'SyslogAuditHandler',
    'ElasticsearchAuditHandler',
    'AlertingAuditHandler',
    'ComplianceReport',
    'ComplianceStandard',
    'GDPRComplianceReporter',
    'HIPAAComplianceReporter',
    'SOC2ComplianceReporter',
    'IntrusionDetection',
    'AnomalyDetector',
    'SecurityAlertManager',
    'AdaptiveSecurityManager',
    'ResponseAction',
    'ResponseRule',
    'SecurityResponse',
    'RuleCondition'
]