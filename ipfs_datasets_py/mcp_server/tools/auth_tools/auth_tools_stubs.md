# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/auth_tools/auth_tools.py'

Files last updated: 1751408933.6764565

Stub file last updated: 2025-07-07 01:10:13

## MockAuthService

```python
class MockAuthService:
    """
    Mock authentication service for testing purposes.
    """
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
* **Class:** MockAuthService

## authenticate

```python
async def authenticate(self, username: str, password: str) -> Dict[str, Any]:
    """
    Authenticate user credentials.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MockAuthService

## authenticate_user

```python
async def authenticate_user(username: str, password: str, auth_service = None) -> Dict[str, Any]:
    """
    Authenticate user credentials and return access token.

Args:
    username: Username for authentication
    password: Password for authentication
    auth_service: Optional authentication service
    
Returns:
    Dictionary containing authentication result with token
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## get_user_from_token

```python
async def get_user_from_token(self, token: str) -> Dict[str, Any]:
    """
    Get user information from token.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MockAuthService

## get_user_info

```python
async def get_user_info(token: str, auth_service = None) -> Dict[str, Any]:
    """
    Get current authenticated user information from JWT token.

Args:
    token: JWT access token
    auth_service: Optional authentication service
    
Returns:
    Dictionary containing user information
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## validate_token

```python
async def validate_token(self, token: str, required_permission: Optional[str] = None) -> Dict[str, Any]:
    """
    Validate JWT token and check permissions.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MockAuthService

## validate_token

```python
async def validate_token(token: str, required_permission: Optional[str] = None, action: str = "validate", auth_service = None) -> Dict[str, Any]:
    """
    Validate JWT token and check user permissions.

Args:
    token: JWT access token to validate
    required_permission: Optional permission to check (read, write, delete, manage)
    action: Action to perform (validate, refresh, decode)
    auth_service: Optional authentication service
    
Returns:
    Dictionary containing token validation result
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
