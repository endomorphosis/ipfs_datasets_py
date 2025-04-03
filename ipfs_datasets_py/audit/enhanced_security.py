"""
Enhanced Security and Governance Module

This module extends the audit logging system with advanced security and governance
features, including data classification, access control enforcement, compliance
monitoring, data encryption, and security policy enforcement.
"""

import os
import json
import time
import uuid
import hashlib
import logging
import datetime
import threading
from typing import Dict, List, Any, Optional, Union, Callable, Type, Set, Tuple
from enum import Enum, auto
from dataclasses import dataclass, field, asdict

from ipfs_datasets_py.audit.audit_logger import (
    AuditLogger, AuditEvent, AuditCategory, AuditLevel
)
from ipfs_datasets_py.audit.intrusion import (
    IntrusionDetection, SecurityAlert, SecurityAlertManager
)

# Try to import cryptography module for encryption features
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


class DataClassification(Enum):
    """Classification levels for data sensitivity."""
    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3
    CRITICAL = 4


class AccessDecision(Enum):
    """Possible outcomes of access control decisions."""
    ALLOW = auto()
    DENY = auto()
    ELEVATE = auto()  # Requires additional authentication/authorization
    AUDIT_ONLY = auto()  # Allow but record detailed audit information


@dataclass
class SecurityPolicy:
    """Represents a security policy configuration."""
    policy_id: str
    name: str
    description: str
    enabled: bool = True
    enforcement_level: str = "advisory"  # "advisory", "enforcing", "strict"
    rules: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the policy to a dictionary."""
        return asdict(self)


@dataclass
class AccessControlEntry:
    """Represents an access control entry for a resource."""
    resource_id: str
    resource_type: str
    principal_id: str  # User or role ID
    principal_type: str  # "user" or "role"
    permissions: List[str]
    conditions: Optional[Dict[str, Any]] = None
    expiration: Optional[str] = None  # ISO timestamp for expiration
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the ACE to a dictionary."""
        return asdict(self)


@dataclass
class DataEncryptionConfig:
    """Configuration for data encryption."""
    enabled: bool = False
    key_id: Optional[str] = None
    algorithm: str = "AES-256-GCM"
    key_rotation_days: int = 90
    metadata: Dict[str, Any] = field(default_factory=dict)


class EnhancedSecurityManager:
    """
    Enhanced security manager that provides advanced security and governance features.
    
    This class extends the basic audit logging system with data classification,
    access control enforcement, compliance monitoring, data encryption, and
    security policy enforcement.
    """
    
    _instance = None
    
    @classmethod
    def get_instance(cls) -> 'EnhancedSecurityManager':
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self, audit_logger=None, intrusion_detection=None, alert_manager=None):
        """
        Initialize the security manager.
        
        Args:
            audit_logger: AuditLogger instance (optional, will use global instance if None)
            intrusion_detection: IntrusionDetection instance (optional)
            alert_manager: SecurityAlertManager instance (optional)
        """
        self.audit_logger = audit_logger or AuditLogger.get_instance()
        self.intrusion_detection = intrusion_detection or IntrusionDetection()
        self.alert_manager = alert_manager or SecurityAlertManager()
        
        # Initialize security components
        self.data_classifications: Dict[str, DataClassification] = {}
        self.access_control_entries: Dict[str, List[AccessControlEntry]] = {}
        self.security_policies: Dict[str, SecurityPolicy] = {}
        self.encryption_configs: Dict[str, DataEncryptionConfig] = {}
        
        # Threading protection
        self._lock = threading.RLock()
        self.logger = logging.getLogger(__name__)
        
        # Register security alert handler
        self.intrusion_detection.add_alert_handler(self._handle_security_alert)
        
        # Register event listeners
        self.audit_logger.add_event_listener(self._process_audit_event)
    
    def _process_audit_event(self, event: AuditEvent):
        """
        Process audit events for security analysis and policy enforcement.
        
        Args:
            event: The audit event to process
        """
        try:
            # Feed the event to intrusion detection
            self.intrusion_detection.process_events([event])
            
            # Check for policy violations
            self._check_policy_violations(event)
            
        except Exception as e:
            self.logger.error(f"Error processing audit event for security: {str(e)}")
    
    def _handle_security_alert(self, alert: SecurityAlert):
        """
        Handle security alerts from intrusion detection.
        
        Args:
            alert: The security alert to handle
        """
        try:
            # Log the alert
            self.audit_logger.security(
                action="security_alert",
                level=AuditLevel.WARNING if alert.level in ["low", "medium"] else AuditLevel.CRITICAL,
                details={
                    "alert_id": alert.alert_id,
                    "alert_type": alert.type,
                    "alert_level": alert.level,
                    "description": alert.description,
                    "source_events": alert.source_events
                }
            )
            
            # Add to alert manager
            self.alert_manager.add_alert(alert)
            
            # Handle specific alert types
            if alert.level in ["high", "critical"]:
                self._handle_critical_security_alert(alert)
                
        except Exception as e:
            self.logger.error(f"Error handling security alert: {str(e)}")
    
    def _handle_critical_security_alert(self, alert: SecurityAlert):
        """
        Handle critical security alerts with additional response actions.
        
        Args:
            alert: The critical security alert to handle
        """
        try:
            # Log additional details
            self.audit_logger.security(
                action="critical_security_response",
                level=AuditLevel.CRITICAL,
                details={
                    "alert_id": alert.alert_id,
                    "response_actions": ["detailed_logging", "notification"],
                    "timestamp": datetime.datetime.utcnow().isoformat() + 'Z'
                }
            )
            
            # Implement automated response actions based on alert type
            if alert.type == "brute_force_login":
                # Example: Increase logging for the affected user
                affected_user = alert.details.get("user")
                if affected_user:
                    self.set_enhanced_monitoring(affected_user, duration_minutes=60)
            
            elif alert.type == "data_exfiltration":
                # Example: Add extra validation for data access operations
                resource_ids = []
                for event_id in alert.source_events:
                    # In a real implementation, we would retrieve the event and extract resource IDs
                    pass
                
                for resource_id in resource_ids:
                    if resource_id:
                        self.add_temporary_access_restriction(resource_id, duration_minutes=60)
                        
        except Exception as e:
            self.logger.error(f"Error handling critical security alert: {str(e)}")
    
    def set_enhanced_monitoring(self, user_id: str, duration_minutes: int = 60):
        """
        Set enhanced monitoring for a user.
        
        Args:
            user_id: The user to monitor
            duration_minutes: Duration of enhanced monitoring in minutes
        """
        expiration = datetime.datetime.utcnow() + datetime.timedelta(minutes=duration_minutes)
        expiration_str = expiration.isoformat() + 'Z'
        
        self.audit_logger.security(
            action="set_enhanced_monitoring",
            user=user_id,
            details={
                "user_id": user_id,
                "duration_minutes": duration_minutes,
                "expiration": expiration_str,
                "reason": "security_alert_response"
            }
        )
        
        # In a real implementation, we would update a monitoring configuration
    
    def add_temporary_access_restriction(self, resource_id: str, duration_minutes: int = 60):
        """
        Add temporary access restrictions for a resource.
        
        Args:
            resource_id: The resource to restrict
            duration_minutes: Duration of restriction in minutes
        """
        expiration = datetime.datetime.utcnow() + datetime.timedelta(minutes=duration_minutes)
        expiration_str = expiration.isoformat() + 'Z'
        
        self.audit_logger.security(
            action="add_access_restriction",
            resource_id=resource_id,
            details={
                "resource_id": resource_id,
                "duration_minutes": duration_minutes,
                "expiration": expiration_str,
                "reason": "security_alert_response"
            }
        )
        
        # In a real implementation, we would update access control entries
    
    def _check_policy_violations(self, event: AuditEvent):
        """
        Check for security policy violations in an audit event.
        
        Args:
            event: The audit event to check
        """
        violations = []
        
        with self._lock:
            for policy_id, policy in self.security_policies.items():
                if not policy.enabled:
                    continue
                
                for rule in policy.rules:
                    rule_type = rule.get("type")
                    
                    if rule_type == "data_classification":
                        if event.category == AuditCategory.DATA_ACCESS:
                            resource_id = event.resource_id
                            if resource_id and resource_id in self.data_classifications:
                                classification = self.data_classifications[resource_id]
                                min_required = DataClassification[rule.get("min_classification", "PUBLIC")]
                                
                                if classification.value > min_required.value and not self._check_user_clearance(event.user, classification):
                                    violations.append({
                                        "policy_id": policy_id,
                                        "rule_type": rule_type,
                                        "description": f"User {event.user} accessed {classification.name} data without clearance",
                                        "severity": rule.get("severity", "high")
                                    })
                    
                    elif rule_type == "access_time":
                        # Check for access outside allowed time windows
                        if "allowed_hours" in rule:
                            event_time = datetime.datetime.fromisoformat(event.timestamp.rstrip('Z'))
                            hour = event_time.hour
                            allowed_hours = rule["allowed_hours"]
                            
                            if hour < allowed_hours["start"] or hour >= allowed_hours["end"]:
                                violations.append({
                                    "policy_id": policy_id,
                                    "rule_type": rule_type,
                                    "description": f"Access at {hour}:00 outside allowed hours ({allowed_hours['start']}:00-{allowed_hours['end']}:00)",
                                    "severity": rule.get("severity", "medium")
                                })
                    
                    elif rule_type == "data_volume":
                        # Check for excessive data volume operations
                        if event.category in [AuditCategory.DATA_MODIFICATION, AuditCategory.DATA_ACCESS]:
                            if "data_size_bytes" in event.details:
                                try:
                                    size = int(event.details["data_size_bytes"])
                                    threshold = rule.get("threshold_bytes", 100 * 1024 * 1024)  # Default 100MB
                                    
                                    if size > threshold:
                                        violations.append({
                                            "policy_id": policy_id,
                                            "rule_type": rule_type,
                                            "description": f"Data operation size ({size/1024/1024:.2f} MB) exceeds threshold ({threshold/1024/1024:.2f} MB)",
                                            "severity": rule.get("severity", "medium")
                                        })
                                except (ValueError, TypeError):
                                    pass
                    
                    # Additional rule types can be implemented here
        
        # Handle violations
        for violation in violations:
            severity = violation.get("severity", "medium")
            
            # Determine audit level based on severity
            level = AuditLevel.WARNING
            if severity == "high":
                level = AuditLevel.ERROR
            elif severity == "critical":
                level = AuditLevel.CRITICAL
            
            # Log the violation
            self.audit_logger.security(
                action="policy_violation",
                level=level,
                resource_id=event.resource_id,
                resource_type=event.resource_type,
                user=event.user,
                details={
                    "policy_id": violation["policy_id"],
                    "rule_type": violation["rule_type"],
                    "description": violation["description"],
                    "severity": severity,
                    "source_event_id": event.event_id
                }
            )
    
    def _check_user_clearance(self, user_id: str, classification: DataClassification) -> bool:
        """
        Check if a user has clearance for a given data classification.
        
        Args:
            user_id: The user to check
            classification: The data classification to check against
            
        Returns:
            bool: Whether the user has sufficient clearance
        """
        # In a real implementation, this would check against a user clearance database
        # For now, just return a conservative result
        return False
    
    def check_access(self, user_id: str, resource_id: str, operation: str, 
                   context: Optional[Dict[str, Any]] = None) -> AccessDecision:
        """
        Check if a user is allowed to perform an operation on a resource.
        
        This is the main entry point for access control enforcement.
        
        Args:
            user_id: The user requesting access
            resource_id: The resource being accessed
            operation: The operation being performed (e.g., "read", "write")
            context: Additional context for the access decision (optional)
            
        Returns:
            AccessDecision: The access decision
        """
        with self._lock:
            # Check if there are any ACEs for this resource
            if resource_id not in self.access_control_entries:
                # No specific ACEs, fall back to default
                return self._get_default_access_decision(resource_id, operation)
            
            # Find applicable ACEs
            applicable_aces = []
            for ace in self.access_control_entries[resource_id]:
                # Check if this ACE applies to this user
                if ace.principal_type == "user" and ace.principal_id == user_id:
                    applicable_aces.append(ace)
                elif ace.principal_type == "role":
                    # In a real implementation, we would check if the user has this role
                    pass
            
            # Check permissions in applicable ACEs
            for ace in applicable_aces:
                # Check for expired entries
                if ace.expiration:
                    expiration_time = datetime.datetime.fromisoformat(ace.expiration.rstrip('Z'))
                    if datetime.datetime.utcnow() > expiration_time:
                        continue
                
                # Check if the operation is explicitly allowed
                if operation in ace.permissions:
                    # Check conditions if present
                    if ace.conditions and context:
                        if not self._evaluate_conditions(ace.conditions, context):
                            continue
                    
                    # Permission granted
                    return AccessDecision.ALLOW
                
                # Check for special permissions
                if f"{operation}_elevated" in ace.permissions:
                    return AccessDecision.ELEVATE
                
                if f"{operation}_audit" in ace.permissions:
                    return AccessDecision.AUDIT_ONLY
            
            # No applicable ACEs granted permission
            return AccessDecision.DENY
    
    def _get_default_access_decision(self, resource_id: str, operation: str) -> AccessDecision:
        """
        Get the default access decision for a resource without specific ACEs.
        
        Args:
            resource_id: The resource being accessed
            operation: The operation being performed
            
        Returns:
            AccessDecision: The default access decision
        """
        # Check data classification for sensitive resources
        if resource_id in self.data_classifications:
            classification = self.data_classifications[resource_id]
            
            # For sensitive data, default to DENY for write operations
            if classification.value >= DataClassification.CONFIDENTIAL.value and operation in ["write", "update", "delete"]:
                return AccessDecision.DENY
            
            # For RESTRICTED or CRITICAL data, require elevated access for read
            if classification.value >= DataClassification.RESTRICTED.value and operation == "read":
                return AccessDecision.ELEVATE
        
        # Default to ALLOW for read, DENY for write/delete
        if operation == "read":
            return AccessDecision.ALLOW
        else:
            return AccessDecision.DENY
    
    def _evaluate_conditions(self, conditions: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """
        Evaluate access conditions against the provided context.
        
        Args:
            conditions: The conditions to evaluate
            context: The context to evaluate against
            
        Returns:
            bool: Whether the conditions are satisfied
        """
        for key, value in conditions.items():
            if key not in context:
                return False
            
            # Special condition types
            if key == "ip_range" and "client_ip" in context:
                if not self._check_ip_in_range(context["client_ip"], value):
                    return False
            
            elif key == "time_range":
                current_time = datetime.datetime.utcnow().time()
                start_time = datetime.time.fromisoformat(value["start"])
                end_time = datetime.time.fromisoformat(value["end"])
                
                if not (start_time <= current_time <= end_time):
                    return False
            
            # Simple equality for other conditions
            elif context[key] != value:
                return False
        
        # All conditions satisfied
        return True
    
    def _check_ip_in_range(self, ip: str, ip_range: str) -> bool:
        """
        Check if an IP address is within a specified range.
        
        Args:
            ip: The IP address to check
            ip_range: The IP range to check against (CIDR notation)
            
        Returns:
            bool: Whether the IP is in the range
        """
        # In a real implementation, this would use proper IP address parsing
        # For now, just do a simple string comparison
        return ip.startswith(ip_range.split('/')[0].rsplit('.', 1)[0])
    
    def set_data_classification(self, resource_id: str, classification: DataClassification,
                             user_id: Optional[str] = None) -> bool:
        """
        Set the data classification for a resource.
        
        Args:
            resource_id: The resource to classify
            classification: The classification level
            user_id: The user performing the classification (optional)
            
        Returns:
            bool: Whether the classification was successfully set
        """
        try:
            with self._lock:
                old_classification = self.data_classifications.get(resource_id)
                self.data_classifications[resource_id] = classification
            
            # Log the classification change
            self.audit_logger.security(
                action="set_data_classification",
                resource_id=resource_id,
                user=user_id,
                details={
                    "classification": classification.name,
                    "previous_classification": old_classification.name if old_classification else None
                }
            )
            
            return True
        
        except Exception as e:
            self.logger.error(f"Error setting data classification: {str(e)}")
            return False
    
    def get_data_classification(self, resource_id: str) -> Optional[DataClassification]:
        """
        Get the data classification for a resource.
        
        Args:
            resource_id: The resource to check
            
        Returns:
            Optional[DataClassification]: The resource's classification, if set
        """
        with self._lock:
            return self.data_classifications.get(resource_id)
    
    def add_access_control_entry(self, ace: AccessControlEntry, user_id: Optional[str] = None) -> bool:
        """
        Add an access control entry for a resource.
        
        Args:
            ace: The access control entry to add
            user_id: The user adding the entry (optional)
            
        Returns:
            bool: Whether the entry was successfully added
        """
        try:
            with self._lock:
                if ace.resource_id not in self.access_control_entries:
                    self.access_control_entries[ace.resource_id] = []
                
                # Check for existing entry with same principal
                for i, existing_ace in enumerate(self.access_control_entries[ace.resource_id]):
                    if (existing_ace.principal_id == ace.principal_id and 
                        existing_ace.principal_type == ace.principal_type):
                        # Replace existing entry
                        self.access_control_entries[ace.resource_id][i] = ace
                        break
                else:
                    # No existing entry found, add new one
                    self.access_control_entries[ace.resource_id].append(ace)
            
            # Log the ACE addition
            self.audit_logger.security(
                action="add_access_control_entry",
                resource_id=ace.resource_id,
                resource_type=ace.resource_type,
                user=user_id,
                details={
                    "principal_id": ace.principal_id,
                    "principal_type": ace.principal_type,
                    "permissions": ace.permissions,
                    "expiration": ace.expiration
                }
            )
            
            return True
        
        except Exception as e:
            self.logger.error(f"Error adding access control entry: {str(e)}")
            return False
    
    def remove_access_control_entry(self, resource_id: str, principal_id: str, principal_type: str,
                                 user_id: Optional[str] = None) -> bool:
        """
        Remove an access control entry for a resource.
        
        Args:
            resource_id: The resource to modify
            principal_id: The principal ID of the entry to remove
            principal_type: The principal type of the entry to remove
            user_id: The user removing the entry (optional)
            
        Returns:
            bool: Whether the entry was successfully removed
        """
        try:
            removed = False
            
            with self._lock:
                if resource_id not in self.access_control_entries:
                    return False
                
                # Find and remove the matching entry
                filtered_entries = []
                for existing_ace in self.access_control_entries[resource_id]:
                    if (existing_ace.principal_id == principal_id and 
                        existing_ace.principal_type == principal_type):
                        removed = True
                    else:
                        filtered_entries.append(existing_ace)
                
                self.access_control_entries[resource_id] = filtered_entries
                
                # Remove empty resource entries
                if not filtered_entries:
                    del self.access_control_entries[resource_id]
            
            if removed:
                # Log the ACE removal
                self.audit_logger.security(
                    action="remove_access_control_entry",
                    resource_id=resource_id,
                    user=user_id,
                    details={
                        "principal_id": principal_id,
                        "principal_type": principal_type
                    }
                )
            
            return removed
        
        except Exception as e:
            self.logger.error(f"Error removing access control entry: {str(e)}")
            return False
    
    def get_access_control_entries(self, resource_id: str) -> List[AccessControlEntry]:
        """
        Get all access control entries for a resource.
        
        Args:
            resource_id: The resource to query
            
        Returns:
            List[AccessControlEntry]: The resource's access control entries
        """
        with self._lock:
            return self.access_control_entries.get(resource_id, [])[:]
    
    def add_security_policy(self, policy: SecurityPolicy, user_id: Optional[str] = None) -> bool:
        """
        Add a security policy.
        
        Args:
            policy: The security policy to add
            user_id: The user adding the policy (optional)
            
        Returns:
            bool: Whether the policy was successfully added
        """
        try:
            with self._lock:
                self.security_policies[policy.policy_id] = policy
            
            # Log the policy addition
            self.audit_logger.security(
                action="add_security_policy",
                user=user_id,
                details={
                    "policy_id": policy.policy_id,
                    "policy_name": policy.name,
                    "enforcement_level": policy.enforcement_level,
                    "rule_count": len(policy.rules)
                }
            )
            
            return True
        
        except Exception as e:
            self.logger.error(f"Error adding security policy: {str(e)}")
            return False
    
    def remove_security_policy(self, policy_id: str, user_id: Optional[str] = None) -> bool:
        """
        Remove a security policy.
        
        Args:
            policy_id: The ID of the policy to remove
            user_id: The user removing the policy (optional)
            
        Returns:
            bool: Whether the policy was successfully removed
        """
        try:
            with self._lock:
                if policy_id not in self.security_policies:
                    return False
                
                del self.security_policies[policy_id]
            
            # Log the policy removal
            self.audit_logger.security(
                action="remove_security_policy",
                user=user_id,
                details={
                    "policy_id": policy_id
                }
            )
            
            return True
        
        except Exception as e:
            self.logger.error(f"Error removing security policy: {str(e)}")
            return False
    
    def get_security_policy(self, policy_id: str) -> Optional[SecurityPolicy]:
        """
        Get a security policy by ID.
        
        Args:
            policy_id: The ID of the policy to retrieve
            
        Returns:
            Optional[SecurityPolicy]: The security policy, if found
        """
        with self._lock:
            return self.security_policies.get(policy_id)
    
    def list_security_policies(self) -> List[SecurityPolicy]:
        """
        List all security policies.
        
        Returns:
            List[SecurityPolicy]: All active security policies
        """
        with self._lock:
            return list(self.security_policies.values())
    
    def add_encryption_config(self, resource_id: str, config: DataEncryptionConfig,
                           user_id: Optional[str] = None) -> bool:
        """
        Add an encryption configuration for a resource.
        
        Args:
            resource_id: The resource to configure
            config: The encryption configuration
            user_id: The user adding the configuration (optional)
            
        Returns:
            bool: Whether the configuration was successfully added
        """
        try:
            with self._lock:
                self.encryption_configs[resource_id] = config
            
            # Log the configuration addition
            self.audit_logger.security(
                action="add_encryption_config",
                resource_id=resource_id,
                user=user_id,
                details={
                    "encryption_enabled": config.enabled,
                    "algorithm": config.algorithm,
                    "key_rotation_days": config.key_rotation_days
                }
            )
            
            return True
        
        except Exception as e:
            self.logger.error(f"Error adding encryption configuration: {str(e)}")
            return False
    
    def get_encryption_config(self, resource_id: str) -> Optional[DataEncryptionConfig]:
        """
        Get the encryption configuration for a resource.
        
        Args:
            resource_id: The resource to query
            
        Returns:
            Optional[DataEncryptionConfig]: The encryption configuration, if found
        """
        with self._lock:
            return self.encryption_configs.get(resource_id)
    
    def encrypt_sensitive_data(self, data: bytes, resource_id: Optional[str] = None) -> Tuple[bytes, str]:
        """
        Encrypt sensitive data with appropriate configuration.
        
        Args:
            data: The data to encrypt
            resource_id: The associated resource ID (optional)
            
        Returns:
            Tuple[bytes, str]: The encrypted data and the encryption key ID
        """
        if not CRYPTO_AVAILABLE:
            raise ImportError("Cryptography module is not available")
        
        # Get encryption configuration
        config = None
        if resource_id:
            config = self.get_encryption_config(resource_id)
        
        if config and config.enabled:
            key_id = config.key_id
        else:
            # Use default encryption settings
            key_id = self._get_default_encryption_key_id()
        
        # In a real implementation, we would use a key management system
        # For demonstration, we'll generate a key deterministically from the ID
        key = self._get_encryption_key(key_id)
        
        # Encrypt the data
        f = Fernet(key)
        encrypted_data = f.encrypt(data)
        
        return encrypted_data, key_id
    
    def decrypt_sensitive_data(self, encrypted_data: bytes, key_id: str) -> bytes:
        """
        Decrypt sensitive data.
        
        Args:
            encrypted_data: The encrypted data
            key_id: The encryption key ID
            
        Returns:
            bytes: The decrypted data
        """
        if not CRYPTO_AVAILABLE:
            raise ImportError("Cryptography module is not available")
        
        # Get the encryption key
        key = self._get_encryption_key(key_id)
        
        # Decrypt the data
        f = Fernet(key)
        decrypted_data = f.decrypt(encrypted_data)
        
        return decrypted_data
    
    def _get_default_encryption_key_id(self) -> str:
        """
        Get the default encryption key ID.
        
        Returns:
            str: The default key ID
        """
        # In a real implementation, this would retrieve from a configuration
        return "default-encryption-key"
    
    def _get_encryption_key(self, key_id: str) -> bytes:
        """
        Get the encryption key for a given key ID.
        
        In a real implementation, this would retrieve from a secure key store.
        This is a simplified implementation for demonstration purposes only.
        
        Args:
            key_id: The key ID
            
        Returns:
            bytes: The encryption key
        """
        if not CRYPTO_AVAILABLE:
            raise ImportError("Cryptography module is not available")
        
        # WARNING: This is not secure and is only for demonstration purposes!
        # In a real implementation, keys would be securely stored and retrieved.
        salt = b'not-secure-salt'
        password = key_id.encode()
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        
        key = base64.urlsafe_b64encode(kdf.derive(password))
        return key
    

class SecuritySession:
    """
    Context manager for security operations.
    
    This class provides a convenient way to perform security operations within
    a context, ensuring proper auditing and cleanup.
    """
    
    def __init__(self, user_id: str, resource_id: Optional[str] = None,
                action: str = "security_operation",
                security_manager=None):
        """
        Initialize the security session.
        
        Args:
            user_id: The user performing the operation
            resource_id: The resource being operated on (optional)
            action: The action being performed
            security_manager: EnhancedSecurityManager instance (optional)
        """
        self.user_id = user_id
        self.resource_id = resource_id
        self.action = action
        self.security_manager = security_manager or EnhancedSecurityManager.get_instance()
        self.audit_logger = self.security_manager.audit_logger
        self.start_time = None
        self.context = {}
    
    def __enter__(self):
        """Begin the security session."""
        self.start_time = datetime.datetime.now()
        
        # Log session start
        self.audit_logger.security(
            action=f"{self.action}_start",
            user=self.user_id,
            resource_id=self.resource_id,
            details={"session_context": self.context}
        )
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """End the security session."""
        end_time = datetime.datetime.now()
        duration_ms = int((end_time - self.start_time).total_seconds() * 1000)
        
        # Prepare details
        details = {
            "duration_ms": duration_ms,
            "session_context": self.context
        }
        
        # Handle exceptions
        if exc_type is not None:
            # Log session error
            self.audit_logger.security(
                action=f"{self.action}_error",
                level=AuditLevel.ERROR,
                user=self.user_id,
                resource_id=self.resource_id,
                status="failure",
                details={
                    **details,
                    "error_type": exc_type.__name__,
                    "error_message": str(exc_val)
                }
            )
        else:
            # Log session completion
            self.audit_logger.security(
                action=f"{self.action}_complete",
                user=self.user_id,
                resource_id=self.resource_id,
                status="success",
                details=details
            )
        
        # Don't suppress exceptions
        return False
    
    def set_context(self, key: str, value: Any):
        """
        Set a context value for the session.
        
        Args:
            key: Context key
            value: Context value
        """
        self.context[key] = value
    
    def check_access(self, operation: str) -> AccessDecision:
        """
        Check if the session user has access to perform an operation.
        
        Args:
            operation: The operation to check
            
        Returns:
            AccessDecision: The access decision
        """
        return self.security_manager.check_access(
            user_id=self.user_id,
            resource_id=self.resource_id,
            operation=operation,
            context=self.context
        )


def security_operation(user_id_arg: str, resource_id_arg: Optional[str] = None,
                      action: str = "security_operation"):
    """
    Decorator for securing operations with access control and auditing.
    
    Args:
        user_id_arg: Name of the argument containing the user ID
        resource_id_arg: Name of the argument containing the resource ID (optional)
        action: The action being performed
        
    Returns:
        Callable: Decorated function
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Extract user ID and resource ID from arguments
            user_id = kwargs.get(user_id_arg)
            if user_id is None and args:
                # Try to get from function signature
                import inspect
                sig = inspect.signature(func)
                param_names = list(sig.parameters.keys())
                
                for i, param_name in enumerate(param_names):
                    if param_name == user_id_arg and i < len(args):
                        user_id = args[i]
                        break
            
            resource_id = None
            if resource_id_arg:
                resource_id = kwargs.get(resource_id_arg)
                if resource_id is None and args:
                    # Try to get from function signature
                    import inspect
                    sig = inspect.signature(func)
                    param_names = list(sig.parameters.keys())
                    
                    for i, param_name in enumerate(param_names):
                        if param_name == resource_id_arg and i < len(args):
                            resource_id = args[i]
                            break
            
            # Get security manager
            security_manager = EnhancedSecurityManager.get_instance()
            
            # Check access if resource ID is provided
            if resource_id:
                # Determine operation based on function name
                operation = func.__name__.split('_')[0]
                if operation not in ["read", "write", "update", "delete", "create"]:
                    operation = "access"
                
                decision = security_manager.check_access(
                    user_id=user_id,
                    resource_id=resource_id,
                    operation=operation
                )
                
                if decision == AccessDecision.DENY:
                    # Log access denial
                    security_manager.audit_logger.authz(
                        action="access_denied",
                        level=AuditLevel.WARNING,
                        user=user_id,
                        resource_id=resource_id,
                        details={
                            "operation": operation,
                            "function": func.__name__
                        }
                    )
                    
                    # Raise permission error
                    raise PermissionError(f"Access denied for user {user_id} to perform {operation} on {resource_id}")
                
                elif decision == AccessDecision.ELEVATE:
                    # In a real implementation, this would trigger additional authentication
                    # For now, just log and continue
                    security_manager.audit_logger.authz(
                        action="elevated_access",
                        level=AuditLevel.NOTICE,
                        user=user_id,
                        resource_id=resource_id,
                        details={
                            "operation": operation,
                            "function": func.__name__
                        }
                    )
            
            # Create security session
            with SecuritySession(user_id=user_id, resource_id=resource_id, action=action,
                            security_manager=security_manager) as session:
                # Execute the function
                return func(*args, **kwargs)
        
        return wrapper
    
    return decorator


# Get the singleton instance
def get_security_manager() -> EnhancedSecurityManager:
    """Get the global security manager instance."""
    return EnhancedSecurityManager.get_instance()


# Global instance
security_manager = get_security_manager()