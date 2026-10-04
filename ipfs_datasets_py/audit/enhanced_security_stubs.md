# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/audit/enhanced_security.py'

Files last updated: 1748635923.4213796

Stub file last updated: 2025-07-07 02:14:36

## AccessControlEntry

```python
@dataclass
class AccessControlEntry:
    """
    Represents an access control entry for a resource.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## AccessDecision

```python
class AccessDecision(Enum):
    """
    Possible outcomes of access control decisions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DataClassification

```python
class DataClassification(Enum):
    """
    Classification levels for data sensitivity.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DataEncryptionConfig

```python
@dataclass
class DataEncryptionConfig:
    """
    Configuration for data encryption.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## EnhancedSecurityManager

```python
class EnhancedSecurityManager:
    """
    Enhanced security manager that provides advanced security and governance features.

This class extends the basic audit logging system with data classification,
access control enforcement, compliance monitoring, data encryption, and
security policy enforcement.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SecurityPolicy

```python
@dataclass
class SecurityPolicy:
    """
    Represents a security policy configuration.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SecuritySession

```python
class SecuritySession:
    """
    Context manager for security operations.

This class provides a convenient way to perform security operations within
a context, ensuring proper auditing and cleanup.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __enter__

```python
def __enter__(self):
    """
    Begin the security session.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecuritySession

## __exit__

```python
def __exit__(self, exc_type, exc_val, exc_tb):
    """
    End the security session.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecuritySession

## __init__

```python
def __init__(self, audit_logger = None, intrusion_detection = None, alert_manager = None):
    """
    Initialize the security manager.

Args:
    audit_logger: AuditLogger instance (optional, will use global instance if None)
    intrusion_detection: IntrusionDetection instance (optional)
    alert_manager: SecurityAlertManager instance (optional)
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## __init__

```python
def __init__(self, user_id: str, resource_id: Optional[str] = None, action: str = "security_operation", security_manager = None):
    """
    Initialize the security session.

Args:
    user_id: The user performing the operation
    resource_id: The resource being operated on (optional)
    action: The action being performed
    security_manager: EnhancedSecurityManager instance (optional)
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecuritySession

## _check_ip_in_range

```python
def _check_ip_in_range(self, ip: str, ip_range: str) -> bool:
    """
    Check if an IP address is within a specified range.

Args:
    ip: The IP address to check
    ip_range: The IP range to check against (CIDR notation)

Returns:
    bool: Whether the IP is in the range
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## _check_policy_violations

```python
def _check_policy_violations(self, event: AuditEvent):
    """
    Check for security policy violations in an audit event.

Args:
    event: The audit event to check
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## _check_user_clearance

```python
def _check_user_clearance(self, user_id: str, classification: DataClassification) -> bool:
    """
    Check if a user has clearance for a given data classification.

Args:
    user_id: The user to check
    classification: The data classification to check against

Returns:
    bool: Whether the user has sufficient clearance
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## _evaluate_conditions

```python
def _evaluate_conditions(self, conditions: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """
    Evaluate access conditions against the provided context.

Args:
    conditions: The conditions to evaluate
    context: The context to evaluate against

Returns:
    bool: Whether the conditions are satisfied
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## _get_default_access_decision

```python
def _get_default_access_decision(self, resource_id: str, operation: str) -> AccessDecision:
    """
    Get the default access decision for a resource without specific ACEs.

Args:
    resource_id: The resource being accessed
    operation: The operation being performed

Returns:
    AccessDecision: The default access decision
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## _get_default_encryption_key_id

```python
def _get_default_encryption_key_id(self) -> str:
    """
    Get the default encryption key ID.

Returns:
    str: The default key ID
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## _get_encryption_key

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## _handle_critical_security_alert

```python
def _handle_critical_security_alert(self, alert: SecurityAlert):
    """
    Handle critical security alerts with additional response actions.

Args:
    alert: The critical security alert to handle
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## _handle_security_alert

```python
def _handle_security_alert(self, alert: SecurityAlert):
    """
    Handle security alerts from intrusion detection.

Args:
    alert: The security alert to handle
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## _process_audit_event

```python
def _process_audit_event(self, event: AuditEvent):
    """
    Process audit events for security analysis and policy enforcement.

Args:
    event: The audit event to process
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## add_access_control_entry

```python
def add_access_control_entry(self, ace: AccessControlEntry, user_id: Optional[str] = None) -> bool:
    """
    Add an access control entry for a resource.

Args:
    ace: The access control entry to add
    user_id: The user adding the entry (optional)

Returns:
    bool: Whether the entry was successfully added
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## add_encryption_config

```python
def add_encryption_config(self, resource_id: str, config: DataEncryptionConfig, user_id: Optional[str] = None) -> bool:
    """
    Add an encryption configuration for a resource.

Args:
    resource_id: The resource to configure
    config: The encryption configuration
    user_id: The user adding the configuration (optional)

Returns:
    bool: Whether the configuration was successfully added
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## add_security_policy

```python
def add_security_policy(self, policy: SecurityPolicy, user_id: Optional[str] = None) -> bool:
    """
    Add a security policy.

Args:
    policy: The security policy to add
    user_id: The user adding the policy (optional)

Returns:
    bool: Whether the policy was successfully added
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## add_temporary_access_restriction

```python
def add_temporary_access_restriction(self, resource_id: str, duration_minutes: int = 60):
    """
    Add temporary access restrictions for a resource.

Args:
    resource_id: The resource to restrict
    duration_minutes: Duration of restriction in minutes
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## check_access

```python
def check_access(self, user_id: str, resource_id: str, operation: str, context: Optional[Dict[str, Any]] = None) -> AccessDecision:
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## check_access

```python
def check_access(self, operation: str) -> AccessDecision:
    """
    Check if the session user has access to perform an operation.

Args:
    operation: The operation to check

Returns:
    AccessDecision: The access decision
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecuritySession

## decorator

```python
def decorator(func):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## decrypt_sensitive_data

```python
def decrypt_sensitive_data(self, encrypted_data: bytes, key_id: str) -> bytes:
    """
    Decrypt sensitive data.

Args:
    encrypted_data: The encrypted data
    key_id: The encryption key ID

Returns:
    bytes: The decrypted data
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## encrypt_sensitive_data

```python
def encrypt_sensitive_data(self, data: bytes, resource_id: Optional[str] = None) -> Tuple[bytes, str]:
    """
    Encrypt sensitive data with appropriate configuration.

Args:
    data: The data to encrypt
    resource_id: The associated resource ID (optional)

Returns:
    Tuple[bytes, str]: The encrypted data and the encryption key ID
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## get_access_control_entries

```python
def get_access_control_entries(self, resource_id: str) -> List[AccessControlEntry]:
    """
    Get all access control entries for a resource.

Args:
    resource_id: The resource to query

Returns:
    List[AccessControlEntry]: The resource's access control entries
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## get_data_classification

```python
def get_data_classification(self, resource_id: str) -> Optional[DataClassification]:
    """
    Get the data classification for a resource.

Args:
    resource_id: The resource to check

Returns:
    Optional[DataClassification]: The resource's classification, if set
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## get_encryption_config

```python
def get_encryption_config(self, resource_id: str) -> Optional[DataEncryptionConfig]:
    """
    Get the encryption configuration for a resource.

Args:
    resource_id: The resource to query

Returns:
    Optional[DataEncryptionConfig]: The encryption configuration, if found
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## get_instance

```python
@classmethod
def get_instance(cls) -> "EnhancedSecurityManager":
    """
    Get the singleton instance.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## get_security_manager

```python
def get_security_manager() -> EnhancedSecurityManager:
    """
    Get the global security manager instance.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_security_policy

```python
def get_security_policy(self, policy_id: str) -> Optional[SecurityPolicy]:
    """
    Get a security policy by ID.

Args:
    policy_id: The ID of the policy to retrieve

Returns:
    Optional[SecurityPolicy]: The security policy, if found
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## list_security_policies

```python
def list_security_policies(self) -> List[SecurityPolicy]:
    """
    List all security policies.

Returns:
    List[SecurityPolicy]: All active security policies
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## remove_access_control_entry

```python
def remove_access_control_entry(self, resource_id: str, principal_id: str, principal_type: str, user_id: Optional[str] = None) -> bool:
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## remove_security_policy

```python
def remove_security_policy(self, policy_id: str, user_id: Optional[str] = None) -> bool:
    """
    Remove a security policy.

Args:
    policy_id: The ID of the policy to remove
    user_id: The user removing the policy (optional)

Returns:
    bool: Whether the policy was successfully removed
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## security_operation

```python
def security_operation(user_id_arg: str, resource_id_arg: Optional[str] = None, action: str = "security_operation"):
    """
    Decorator for securing operations with access control and auditing.

Args:
    user_id_arg: Name of the argument containing the user ID
    resource_id_arg: Name of the argument containing the resource ID (optional)
    action: The action being performed

Returns:
    Callable: Decorated function
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## set_context

```python
def set_context(self, key: str, value: Any):
    """
    Set a context value for the session.

Args:
    key: Context key
    value: Context value
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecuritySession

## set_data_classification

```python
def set_data_classification(self, resource_id: str, classification: DataClassification, user_id: Optional[str] = None) -> bool:
    """
    Set the data classification for a resource.

Args:
    resource_id: The resource to classify
    classification: The classification level
    user_id: The user performing the classification (optional)

Returns:
    bool: Whether the classification was successfully set
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## set_enhanced_monitoring

```python
def set_enhanced_monitoring(self, user_id: str, duration_minutes: int = 60):
    """
    Set enhanced monitoring for a user.

Args:
    user_id: The user to monitor
    duration_minutes: Duration of enhanced monitoring in minutes
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedSecurityManager

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert the policy to a dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityPolicy

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert the ACE to a dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AccessControlEntry

## wrapper

```python
def wrapper(*args, **kwargs):
```
* **Async:** False
* **Method:** False
* **Class:** N/A
