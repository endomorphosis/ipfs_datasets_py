# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/audit/adaptive_security.py'

Files last updated: 1748635923.4113796

Stub file last updated: 2025-07-07 02:14:36

## AdaptiveSecurityManager

```python
class AdaptiveSecurityManager:
    """
    Manages adaptive security responses to detected threats.

This class coordinates automated responses to security alerts based on
configurable rules and integrates with the security and audit systems.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ResponseAction

```python
class ResponseAction(Enum):
    """
    Types of security response actions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ResponseRule

```python
class ResponseRule:
    """
    Rule for determining appropriate security responses to alerts.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## RuleCondition

```python
@dataclass
class RuleCondition:
    """
    Condition for response rule matching.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SecurityResponse

```python
@dataclass
class SecurityResponse:
    """
    Definition of a security response to a threat.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, rule_id: str, name: str, alert_type: str, severity_levels: List[str], actions: List[Dict[str, Any]], conditions: Optional[List[RuleCondition]] = None, description: str = "", enabled: bool = True):
    """
    Initialize a response rule.

Args:
    rule_id: Unique identifier for the rule
    name: Human-readable name
    alert_type: Type of security alert this rule applies to
    severity_levels: List of severity levels this rule applies to (e.g., ["medium", "high"])
    actions: List of actions to take, each with parameters
    conditions: Additional RuleCondition objects that must be met to apply the rule
    description: Human-readable description
    enabled: Whether the rule is enabled
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResponseRule

## __init__

```python
def __init__(self, security_manager = None, alert_manager = None, audit_logger = None, response_storage_path: Optional[str] = None):
    """
    Initialize the adaptive security manager.

Args:
    security_manager: EnhancedSecurityManager instance
    alert_manager: SecurityAlertManager instance
    audit_logger: AuditLogger instance
    response_storage_path: Path to store response history
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _execute_response_action

```python
def _execute_response_action(self, alert: SecurityAlert, action: Dict[str, Any]) -> None:
    """
    Execute a response action.

Args:
    alert: The security alert that triggered the action
    action: The action to execute
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _expire_responses

```python
def _expire_responses(self) -> None:
    """
    Check for and expire timed-out responses.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _handle_audit_response

```python
def _handle_audit_response(self, response: SecurityResponse) -> Dict[str, Any]:
    """
    Handle enhanced audit logging response.

Args:
    response: The security response

Returns:
    Dict[str, Any]: Result of the response
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _handle_encrypt_response

```python
def _handle_encrypt_response(self, response: SecurityResponse) -> Dict[str, Any]:
    """
    Handle encryption enforcement response.

Args:
    response: The security response

Returns:
    Dict[str, Any]: Result of the response
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _handle_escalate_response

```python
def _handle_escalate_response(self, response: SecurityResponse) -> Dict[str, Any]:
    """
    Handle security escalation response.

Args:
    response: The security response

Returns:
    Dict[str, Any]: Result of the response
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _handle_isolate_response

```python
def _handle_isolate_response(self, response: SecurityResponse) -> Dict[str, Any]:
    """
    Handle resource isolation response.

Args:
    response: The security response

Returns:
    Dict[str, Any]: Result of the response
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _handle_lockout_response

```python
def _handle_lockout_response(self, response: SecurityResponse) -> Dict[str, Any]:
    """
    Handle account lockout response.

Args:
    response: The security response

Returns:
    Dict[str, Any]: Result of the response
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _handle_monitor_response

```python
def _handle_monitor_response(self, response: SecurityResponse) -> Dict[str, Any]:
    """
    Handle enhanced monitoring response.

Args:
    response: The security response

Returns:
    Dict[str, Any]: Result of the response
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _handle_notify_response

```python
def _handle_notify_response(self, response: SecurityResponse) -> Dict[str, Any]:
    """
    Handle security notification response.

Args:
    response: The security response

Returns:
    Dict[str, Any]: Result of the response
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _handle_restrict_response

```python
def _handle_restrict_response(self, response: SecurityResponse) -> Dict[str, Any]:
    """
    Handle access restriction response.

Args:
    response: The security response

Returns:
    Dict[str, Any]: Result of the response
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _handle_rollback_response

```python
def _handle_rollback_response(self, response: SecurityResponse) -> Dict[str, Any]:
    """
    Handle rollback response.

Args:
    response: The security response

Returns:
    Dict[str, Any]: Result of the response
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _handle_security_alert

```python
def _handle_security_alert(self, alert: SecurityAlert) -> None:
    """
    Handle a security alert by applying appropriate response rules.

Args:
    alert: The security alert to handle
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _handle_snapshot_response

```python
def _handle_snapshot_response(self, response: SecurityResponse) -> Dict[str, Any]:
    """
    Handle security snapshot response.

Args:
    response: The security response

Returns:
    Dict[str, Any]: Result of the response
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _handle_throttle_response

```python
def _handle_throttle_response(self, response: SecurityResponse) -> Dict[str, Any]:
    """
    Handle rate limiting response.

Args:
    response: The security response

Returns:
    Dict[str, Any]: Result of the response
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _load_responses

```python
def _load_responses(self) -> None:
    """
    Load responses from storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _maintenance_loop

```python
def _maintenance_loop(self) -> None:
    """
    Background thread for maintenance tasks like expiring responses.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _register_default_handlers

```python
def _register_default_handlers(self) -> None:
    """
    Register default response handlers.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _register_default_rules

```python
def _register_default_rules(self) -> None:
    """
    Register default response rules.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## _save_responses

```python
def _save_responses(self) -> None:
    """
    Save responses to storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## add_response

```python
def add_response(self, response: SecurityResponse) -> None:
    """
    Add a security response manually.

Args:
    response: The security response to add
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## add_rule

```python
def add_rule(self, rule: ResponseRule) -> None:
    """
    Add a response rule.

Args:
    rule: The rule to add
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## cancel_response

```python
def cancel_response(self, response_id: str) -> bool:
    """
    Cancel an active security response.

Args:
    response_id: ID of the response to cancel

Returns:
    bool: Whether the cancellation was successful
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## check_expired_responses

```python
def check_expired_responses(self) -> int:
    """
    Check for expired responses and update their status.

Returns:
    int: Number of expired responses
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## evaluate

```python
def evaluate(self, alert: Any) -> bool:
    """
    Evaluate the condition against an alert.

Args:
    alert: The alert to evaluate against

Returns:
    bool: Whether the condition is met
    """
```
* **Async:** False
* **Method:** True
* **Class:** RuleCondition

## get_actions_for_alert

```python
def get_actions_for_alert(self, alert: SecurityAlert) -> List[Dict[str, Any]]:
    """
    Get the actions to take for the given alert.

Args:
    alert: Security alert to respond to

Returns:
    List[Dict[str, Any]]: Actions to take
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResponseRule

## get_active_responses

```python
def get_active_responses(self, target_id: Optional[str] = None, action_type: Optional[ResponseAction] = None) -> List[SecurityResponse]:
    """
    Get active security responses, optionally filtered.

Args:
    target_id: Filter by target ID
    action_type: Filter by action type

Returns:
    List[SecurityResponse]: Matching active responses
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## get_instance

```python
@classmethod
def get_instance(cls) -> "AdaptiveSecurityManager":
    """
    Get the singleton instance.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## is_expired

```python
def is_expired(self) -> bool:
    """
    Check if the response has expired.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityResponse

## matches_alert

```python
def matches_alert(self, alert: SecurityAlert) -> bool:
    """
    Check if this rule applies to the given alert.

Args:
    alert: Security alert to check

Returns:
    bool: Whether the rule applies
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResponseRule

## process_pending_alerts

```python
def process_pending_alerts(self) -> int:
    """
    Process all pending security alerts.

Returns:
    int: Number of alerts processed
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## register_response_handler

```python
def register_response_handler(self, action_type: ResponseAction, handler: Callable[[SecurityResponse], Dict[str, Any]]) -> None:
    """
    Register a handler for a response action.

Args:
    action_type: The action type to handle
    handler: The handler function
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveSecurityManager

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityResponse
