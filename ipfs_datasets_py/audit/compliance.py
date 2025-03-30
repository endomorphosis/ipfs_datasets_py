"""
Compliance Reporting for Audit Logs

This module provides tools for generating compliance reports from audit logs,
supporting various regulatory standards and compliance frameworks.
"""

import os
import json
import csv
import datetime
import logging
from enum import Enum, auto
from typing import Dict, List, Any, Optional, Union, Callable, TextIO, Set
from dataclasses import dataclass, field, asdict

from ipfs_datasets_py.audit.audit_logger import AuditEvent, AuditCategory, AuditLevel


class ComplianceStandard(Enum):
    """Supported compliance standards."""
    GDPR = auto()  # General Data Protection Regulation
    HIPAA = auto()  # Health Insurance Portability and Accountability Act
    SOC2 = auto()  # Service Organization Control 2
    PCI_DSS = auto()  # Payment Card Industry Data Security Standard
    CCPA = auto()  # California Consumer Privacy Act
    NIST_800_53 = auto()  # NIST Special Publication 800-53
    ISO_27001 = auto()  # ISO/IEC 27001
    CUSTOM = auto()  # Custom compliance framework


@dataclass
class ComplianceRequirement:
    """A specific compliance requirement that needs to be demonstrated."""
    id: str  # Identifier (e.g., "GDPR-Art30")
    standard: ComplianceStandard
    description: str
    audit_categories: List[AuditCategory]
    actions: List[str]
    min_level: AuditLevel = AuditLevel.INFO
    required_fields: List[str] = field(default_factory=list)
    verification_function: Optional[Callable[[List[AuditEvent]], Dict[str, Any]]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComplianceReport:
    """
    A report demonstrating compliance with a set of requirements.
    
    This class represents a compliance report generated from audit logs,
    showing whether and how compliance requirements are being met.
    """
    report_id: str
    standard: ComplianceStandard
    generated_at: str
    time_period: Dict[str, str]  # {"start": "ISO date", "end": "ISO date"}
    requirements: List[Dict[str, Any]]
    summary: Dict[str, Any]
    compliant: bool
    details: Dict[str, Any] = field(default_factory=dict)
    remediation_suggestions: Dict[str, List[str]] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the report to a dictionary."""
        report_dict = asdict(self)
        report_dict['standard'] = self.standard.name
        return report_dict
    
    def to_json(self, pretty=False) -> str:
        """Serialize the report to JSON."""
        if pretty:
            return json.dumps(self.to_dict(), indent=2)
        return json.dumps(self.to_dict())
    
    def save_json(self, file_path: str, pretty=True) -> None:
        """Save the report to a JSON file."""
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(self.to_json(pretty=pretty))
    
    def save_csv(self, file_path: str) -> None:
        """Save requirements status to a CSV file."""
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Requirement ID', 'Description', 'Status', 'Evidence Count', 'Notes'])
            
            for req in self.requirements:
                writer.writerow([
                    req['id'],
                    req['description'],
                    req['status'],
                    req.get('evidence_count', 0),
                    req.get('notes', '')
                ])
    
    def save_html(self, file_path: str) -> None:
        """Save the report as an HTML document."""
        # Simple HTML template for the report
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Compliance Report - {self.standard.name}</title>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 1200px; margin: 0 auto; padding: 20px; }}
        h1, h2, h3 {{ color: #2c3e50; }}
        .header {{ background-color: #f8f9fa; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
        .summary {{ display: flex; justify-content: space-between; margin-bottom: 20px; }}
        .summary-box {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; flex: 1; margin: 0 10px; }}
        .compliant {{ color: green; }}
        .non-compliant {{ color: red; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #f2f2f2; }}
        tr:hover {{ background-color: #f5f5f5; }}
        .status-compliant {{ color: green; }}
        .status-non-compliant {{ color: red; }}
        .status-partial {{ color: orange; }}
        .remediation {{ background-color: #fff8e1; padding: 15px; border-radius: 5px; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Compliance Report - {self.standard.name}</h1>
        <p><strong>Report ID:</strong> {self.report_id}</p>
        <p><strong>Generated:</strong> {self.generated_at}</p>
        <p><strong>Time Period:</strong> {self.time_period['start']} to {self.time_period['end']}</p>
        <p><strong>Overall Status:</strong> <span class="{'compliant' if self.compliant else 'non-compliant'}">{self.get_status_text(self.compliant)}</span></p>
    </div>
    
    <div class="summary">
        <div class="summary-box">
            <h3>Summary</h3>
            <p><strong>Total Requirements:</strong> {self.summary.get('total_requirements', 0)}</p>
            <p><strong>Compliant:</strong> {self.summary.get('compliant_count', 0)}</p>
            <p><strong>Non-Compliant:</strong> {self.summary.get('non_compliant_count', 0)}</p>
            <p><strong>Partial:</strong> {self.summary.get('partial_count', 0)}</p>
            <p><strong>Compliance Rate:</strong> {self.summary.get('compliance_rate', 0)}%</p>
        </div>
    </div>
    
    <h2>Requirements</h2>
    <table>
        <tr>
            <th>ID</th>
            <th>Description</th>
            <th>Status</th>
            <th>Evidence</th>
            <th>Notes</th>
        </tr>
        {"".join(
            f'''<tr>
                <td>{req['id']}</td>
                <td>{req['description']}</td>
                <td class="status-{req['status'].lower()}">{req['status']}</td>
                <td>{req.get('evidence_count', 0)}</td>
                <td>{req.get('notes', '')}</td>
            </tr>''' 
            for req in self.requirements
        )}
    </table>
    
    {"".join(
        f'''<div class="remediation">
            <h3>Remediation Suggestions for {req_id}</h3>
            <ul>
                {"".join(f'<li>{suggestion}</li>' for suggestion in suggestions)}
            </ul>
        </div>''' 
        for req_id, suggestions in self.remediation_suggestions.items()
    )}
</body>
</html>
"""
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html)
    
    @staticmethod
    def get_status_text(status: bool) -> str:
        """Convert boolean status to text."""
        return "Compliant" if status else "Non-Compliant"


class ComplianceReporter:
    """
    Base class for generating compliance reports from audit logs.
    
    This class provides the foundation for compliance reporting against
    various regulatory standards and frameworks.
    """
    
    def __init__(self, standard: ComplianceStandard):
        """
        Initialize the compliance reporter.
        
        Args:
            standard: The compliance standard to report against
        """
        self.standard = standard
        self.requirements: List[ComplianceRequirement] = []
        self.logger = logging.getLogger(__name__)
    
    def add_requirement(self, requirement: ComplianceRequirement) -> None:
        """
        Add a compliance requirement to check.
        
        Args:
            requirement: The compliance requirement to add
        """
        self.requirements.append(requirement)
    
    def generate_report(self, events: List[AuditEvent], 
                       start_time: Optional[str] = None,
                       end_time: Optional[str] = None) -> ComplianceReport:
        """
        Generate a compliance report from audit events.
        
        Args:
            events: List of audit events to analyze
            start_time: Start time for the report period (ISO format)
            end_time: End time for the report period (ISO format)
            
        Returns:
            ComplianceReport: The generated compliance report
        """
        # Set default time period if not provided
        if not start_time or not end_time:
            # Default to last 30 days
            end = datetime.datetime.utcnow()
            start = end - datetime.timedelta(days=30)
            end_time = end_time or end.isoformat() + 'Z'
            start_time = start_time or start.isoformat() + 'Z'
        
        # Filter events by time period
        filtered_events = []
        for event in events:
            event_time = event.timestamp.rstrip('Z')
            if start_time <= event_time <= end_time:
                filtered_events.append(event)
        
        # Check each requirement
        requirement_results = []
        remediation_suggestions = {}
        all_compliant = True
        
        for req in self.requirements:
            # Filter events relevant to this requirement
            relevant_events = self._filter_events_for_requirement(filtered_events, req)
            
            # Check if requirement is met
            requirement_status, details = self._check_requirement(req, relevant_events)
            
            # Add to results
            result = {
                'id': req.id,
                'description': req.description,
                'status': requirement_status,
                'evidence_count': len(relevant_events),
                'details': details,
                'notes': details.get('notes', '')
            }
            requirement_results.append(result)
            
            # Update overall compliance status
            if requirement_status == 'Non-Compliant':
                all_compliant = False
                remediation_suggestions[req.id] = self._generate_remediation(req, details)
            elif requirement_status == 'Partial' and all_compliant:
                all_compliant = False
            
        # Generate summary
        compliant_count = sum(1 for r in requirement_results if r['status'] == 'Compliant')
        non_compliant_count = sum(1 for r in requirement_results if r['status'] == 'Non-Compliant')
        partial_count = sum(1 for r in requirement_results if r['status'] == 'Partial')
        total = len(requirement_results)
        
        summary = {
            'total_requirements': total,
            'compliant_count': compliant_count,
            'non_compliant_count': non_compliant_count,
            'partial_count': partial_count,
            'compliance_rate': round((compliant_count / total) * 100, 1) if total else 0
        }
        
        # Create the report
        report = ComplianceReport(
            report_id=f"{self.standard.name}-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            standard=self.standard,
            generated_at=datetime.datetime.utcnow().isoformat() + 'Z',
            time_period={'start': start_time, 'end': end_time},
            requirements=requirement_results,
            summary=summary,
            compliant=all_compliant,
            remediation_suggestions=remediation_suggestions
        )
        
        return report
    
    def _filter_events_for_requirement(self, events: List[AuditEvent], 
                                     requirement: ComplianceRequirement) -> List[AuditEvent]:
        """
        Filter events relevant to a specific compliance requirement.
        
        Args:
            events: List of all audit events
            requirement: The compliance requirement to filter for
            
        Returns:
            List[AuditEvent]: Events relevant to the requirement
        """
        result = []
        
        for event in events:
            # Check level
            if event.level.value < requirement.min_level.value:
                continue
            
            # Check category
            if (requirement.audit_categories and 
                event.category not in requirement.audit_categories):
                continue
            
            # Check action
            if requirement.actions and event.action not in requirement.actions:
                continue
            
            # Check required fields
            if requirement.required_fields:
                missing_fields = False
                for field in requirement.required_fields:
                    # Handle nested fields in details
                    if '.' in field:
                        parts = field.split('.', 1)
                        if parts[0] == 'details':
                            if parts[1] not in event.details:
                                missing_fields = True
                                break
                    elif not hasattr(event, field) or getattr(event, field) is None:
                        missing_fields = True
                        break
                
                if missing_fields:
                    continue
            
            # Event passes all filters
            result.append(event)
        
        return result
    
    def _check_requirement(self, requirement: ComplianceRequirement, 
                         events: List[AuditEvent]) -> tuple:
        """
        Check if a compliance requirement is met.
        
        Args:
            requirement: The compliance requirement to check
            events: Relevant audit events
            
        Returns:
            tuple: (status, details) where status is one of 'Compliant', 
                  'Non-Compliant', or 'Partial'
        """
        # Use custom verification function if provided
        if requirement.verification_function:
            try:
                result = requirement.verification_function(events)
                status = result.get('status', 'Non-Compliant')
                return status, result
            except Exception as e:
                self.logger.error(f"Error in verification function for {requirement.id}: {str(e)}")
                return 'Non-Compliant', {'error': str(e)}
        
        # Default verification based on event presence
        if not events:
            return 'Non-Compliant', {'notes': 'No relevant audit events found'}
        
        # Simple presence check
        return 'Compliant', {'notes': f'Found {len(events)} relevant audit events'}
    
    def _generate_remediation(self, requirement: ComplianceRequirement, 
                            details: Dict[str, Any]) -> List[str]:
        """
        Generate remediation suggestions for a failed requirement.
        
        Args:
            requirement: The failed compliance requirement
            details: Details about the failure
            
        Returns:
            List[str]: Remediation suggestions
        """
        # Default remediation suggestions
        suggestions = [
            f"Ensure proper logging for {', '.join([cat.name for cat in requirement.audit_categories])} events",
            f"Verify that required actions ({', '.join(requirement.actions)}) are being audited",
            f"Check that audit level is at least {requirement.min_level.name}"
        ]
        
        # Add specific suggestions based on requirement
        if requirement.id.startswith('GDPR'):
            suggestions.append("Verify data access controls and consent tracking")
        elif requirement.id.startswith('HIPAA'):
            suggestions.append("Ensure PHI access is properly authenticated and authorized")
        elif requirement.id.startswith('SOC2'):
            suggestions.append("Review system integrity and availability monitoring")
        elif requirement.id.startswith('PCI'):
            suggestions.append("Verify cardholder data protection measures")
        
        return suggestions


class GDPRComplianceReporter(ComplianceReporter):
    """
    Compliance reporter for GDPR (General Data Protection Regulation).
    
    This class provides predefined compliance requirements specific to GDPR,
    focusing on data access, processing, and subject rights.
    """
    
    def __init__(self):
        """Initialize the GDPR compliance reporter with predefined requirements."""
        super().__init__(ComplianceStandard.GDPR)
        
        # Add GDPR-specific requirements
        self.add_requirement(ComplianceRequirement(
            id="GDPR-Art30",
            standard=ComplianceStandard.GDPR,
            description="Records of processing activities",
            audit_categories=[AuditCategory.DATA_ACCESS, AuditCategory.DATA_MODIFICATION],
            actions=["read", "write", "update", "delete"],
            min_level=AuditLevel.INFO,
            required_fields=["user", "resource_id", "timestamp"]
        ))
        
        self.add_requirement(ComplianceRequirement(
            id="GDPR-Art32",
            standard=ComplianceStandard.GDPR,
            description="Security of processing",
            audit_categories=[AuditCategory.SECURITY, AuditCategory.AUTHENTICATION],
            actions=["login", "logout", "access_denied", "permission_changed"],
            min_level=AuditLevel.INFO
        ))
        
        self.add_requirement(ComplianceRequirement(
            id="GDPR-Art33",
            standard=ComplianceStandard.GDPR,
            description="Notification of personal data breaches",
            audit_categories=[AuditCategory.SECURITY, AuditCategory.INTRUSION_DETECTION],
            actions=["security_incident", "breach_detected", "unauthorized_access"],
            min_level=AuditLevel.WARNING
        ))
        
        self.add_requirement(ComplianceRequirement(
            id="GDPR-Art15",
            standard=ComplianceStandard.GDPR,
            description="Right of access by the data subject",
            audit_categories=[AuditCategory.DATA_ACCESS],
            actions=["subject_access_request", "data_export"],
            min_level=AuditLevel.INFO
        ))
        
        self.add_requirement(ComplianceRequirement(
            id="GDPR-Art17",
            standard=ComplianceStandard.GDPR,
            description="Right to erasure ('right to be forgotten')",
            audit_categories=[AuditCategory.DATA_MODIFICATION],
            actions=["data_deletion", "right_to_be_forgotten"],
            min_level=AuditLevel.INFO
        ))


class HIPAAComplianceReporter(ComplianceReporter):
    """
    Compliance reporter for HIPAA (Health Insurance Portability and Accountability Act).
    
    This class provides predefined compliance requirements specific to HIPAA,
    focusing on PHI (Protected Health Information) access and security.
    """
    
    def __init__(self):
        """Initialize the HIPAA compliance reporter with predefined requirements."""
        super().__init__(ComplianceStandard.HIPAA)
        
        # Add HIPAA-specific requirements
        self.add_requirement(ComplianceRequirement(
            id="HIPAA-164.312.a.1",
            standard=ComplianceStandard.HIPAA,
            description="Access Control - Unique User Identification",
            audit_categories=[AuditCategory.AUTHENTICATION, AuditCategory.AUTHORIZATION],
            actions=["login", "access_granted", "access_denied"],
            min_level=AuditLevel.INFO,
            required_fields=["user", "client_ip", "timestamp"]
        ))
        
        self.add_requirement(ComplianceRequirement(
            id="HIPAA-164.312.b",
            standard=ComplianceStandard.HIPAA,
            description="Audit Controls",
            audit_categories=[AuditCategory.DATA_ACCESS, AuditCategory.DATA_MODIFICATION],
            actions=["read", "write", "update", "delete"],
            min_level=AuditLevel.INFO,
            required_fields=["user", "resource_id", "timestamp"]
        ))
        
        self.add_requirement(ComplianceRequirement(
            id="HIPAA-164.312.c.1",
            standard=ComplianceStandard.HIPAA,
            description="Integrity",
            audit_categories=[AuditCategory.DATA_MODIFICATION, AuditCategory.SECURITY],
            actions=["update", "delete", "checksum_validation"],
            min_level=AuditLevel.INFO
        ))
        
        self.add_requirement(ComplianceRequirement(
            id="HIPAA-164.312.d",
            standard=ComplianceStandard.HIPAA,
            description="Person or Entity Authentication",
            audit_categories=[AuditCategory.AUTHENTICATION],
            actions=["login", "mfa_challenge", "password_change"],
            min_level=AuditLevel.INFO
        ))
        
        self.add_requirement(ComplianceRequirement(
            id="HIPAA-164.312.e.1",
            standard=ComplianceStandard.HIPAA,
            description="Transmission Security",
            audit_categories=[AuditCategory.SECURITY, AuditCategory.DATA_ACCESS],
            actions=["data_export", "data_transfer", "encryption_status"],
            min_level=AuditLevel.INFO
        ))


class SOC2ComplianceReporter(ComplianceReporter):
    """
    Compliance reporter for SOC 2 (Service Organization Control 2).
    
    This class provides predefined compliance requirements specific to SOC 2,
    covering the five trust services criteria: security, availability,
    processing integrity, confidentiality, and privacy.
    """
    
    def __init__(self):
        """Initialize the SOC2 compliance reporter with predefined requirements."""
        super().__init__(ComplianceStandard.SOC2)
        
        # Add SOC2-specific requirements
        self.add_requirement(ComplianceRequirement(
            id="SOC2-CC1.1",
            standard=ComplianceStandard.SOC2,
            description="Common Criteria - Management has defined organizational structure and responsibility",
            audit_categories=[AuditCategory.CONFIGURATION, AuditCategory.AUTHORIZATION],
            actions=["role_assignment", "permission_changed", "policy_update"],
            min_level=AuditLevel.INFO
        ))
        
        self.add_requirement(ComplianceRequirement(
            id="SOC2-CC5.1",
            standard=ComplianceStandard.SOC2,
            description="Common Criteria - Logical access security/cybersecurity",
            audit_categories=[AuditCategory.AUTHENTICATION, AuditCategory.AUTHORIZATION, AuditCategory.SECURITY],
            actions=["login", "logout", "access_denied", "password_change", "mfa_challenge"],
            min_level=AuditLevel.INFO
        ))
        
        self.add_requirement(ComplianceRequirement(
            id="SOC2-CC5.2",
            standard=ComplianceStandard.SOC2,
            description="Common Criteria - System changes are authorized and properly designed and implemented",
            audit_categories=[AuditCategory.CONFIGURATION, AuditCategory.SYSTEM],
            actions=["system_update", "configuration_change", "deployment"],
            min_level=AuditLevel.INFO
        ))
        
        self.add_requirement(ComplianceRequirement(
            id="SOC2-CC6.1",
            standard=ComplianceStandard.SOC2,
            description="Common Criteria - Vulnerabilities are identified and managed",
            audit_categories=[AuditCategory.SECURITY, AuditCategory.INTRUSION_DETECTION],
            actions=["vulnerability_scan", "security_incident", "patch_applied"],
            min_level=AuditLevel.INFO
        ))
        
        self.add_requirement(ComplianceRequirement(
            id="SOC2-A1.1",
            standard=ComplianceStandard.SOC2,
            description="Availability - System availability is planned, supported, and managed",
            audit_categories=[AuditCategory.SYSTEM, AuditCategory.OPERATIONAL],
            actions=["system_startup", "system_shutdown", "service_status_change"],
            min_level=AuditLevel.INFO
        ))
        
        self.add_requirement(ComplianceRequirement(
            id="SOC2-PI1.1",
            standard=ComplianceStandard.SOC2,
            description="Processing Integrity - System processing is complete, valid, accurate, timely, and authorized",
            audit_categories=[AuditCategory.DATA_MODIFICATION, AuditCategory.OPERATIONAL],
            actions=["data_validation", "processing_complete", "error_detected"],
            min_level=AuditLevel.INFO
        ))
        
        self.add_requirement(ComplianceRequirement(
            id="SOC2-C1.1",
            standard=ComplianceStandard.SOC2,
            description="Confidentiality - Confidential information is protected during collection, use, and disposal",
            audit_categories=[AuditCategory.DATA_ACCESS, AuditCategory.SECURITY],
            actions=["data_access", "data_deletion", "encryption_status"],
            min_level=AuditLevel.INFO
        ))
        
        self.add_requirement(ComplianceRequirement(
            id="SOC2-P1.1",
            standard=ComplianceStandard.SOC2,
            description="Privacy - Personal information is collected, used, retained, and disposed of properly",
            audit_categories=[AuditCategory.DATA_ACCESS, AuditCategory.DATA_MODIFICATION],
            actions=["data_collection", "consent_management", "data_deletion"],
            min_level=AuditLevel.INFO
        ))