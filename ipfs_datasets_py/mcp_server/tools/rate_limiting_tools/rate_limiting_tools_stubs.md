# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/rate_limiting_tools/rate_limiting_tools.py'

Files last updated: 1751408933.7664564

Stub file last updated: 2025-07-07 01:10:14

## MockRateLimiter

```python
class MockRateLimiter:
    """
    Mock rate limiter for testing and development.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## RateLimitConfig

```python
@dataclass
class RateLimitConfig:
    """
    Configuration for rate limiting rules.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## RateLimitStrategy

```python
class RateLimitStrategy(Enum):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** MockRateLimiter

## check_rate_limit

```python
def check_rate_limit(self, limit_name: str, identifier: str = "default") -> Dict[str, Any]:
    """
    Check if request is within rate limits.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockRateLimiter

## check_rate_limit

```python
async def check_rate_limit(limit_name: str, identifier: str = "default", request_metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Check if a request is within rate limits.

Args:
    limit_name: Name of the rate limit rule to check
    identifier: Unique identifier for the requester (user ID, IP, etc.)
    request_metadata: Additional metadata about the request

Returns:
    Dict containing rate limit check results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## configure_limit

```python
def configure_limit(self, config: RateLimitConfig) -> Dict[str, Any]:
    """
    Configure a rate limit rule.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockRateLimiter

## configure_rate_limits

```python
async def configure_rate_limits(limits: List[Dict[str, Any]], apply_immediately: bool = True, backup_current: bool = True) -> Dict[str, Any]:
    """
    Configure rate limiting rules for API endpoints and operations.

Args:
    limits: List of rate limit configurations
    apply_immediately: Whether to apply limits immediately
    backup_current: Whether to backup current configuration

Returns:
    Dict containing configuration results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## get_stats

```python
def get_stats(self, limit_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get rate limiting statistics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockRateLimiter

## manage_rate_limits

```python
async def manage_rate_limits(action: str, limit_name: Optional[str] = None, new_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Manage rate limiting configuration and operations.

Args:
    action: Management action to perform
    limit_name: Specific limit to manage (for targeted actions)
    new_config: New configuration data (for update actions)

Returns:
    Dict containing management operation results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## reset_limits

```python
def reset_limits(self, limit_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Reset rate limiting counters.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockRateLimiter
