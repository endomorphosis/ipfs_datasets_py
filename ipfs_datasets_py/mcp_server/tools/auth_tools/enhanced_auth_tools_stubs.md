# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/auth_tools/enhanced_auth_tools.py'

Files last updated: 1751408933.6764565

Stub file last updated: 2025-07-07 01:10:13

## EnhancedAuthenticationTool

```python
class EnhancedAuthenticationTool(EnhancedBaseMCPTool):
    """
    Enhanced tool for user authentication and JWT token management.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## EnhancedTokenValidationTool

```python
class EnhancedTokenValidationTool(EnhancedBaseMCPTool):
    """
    Enhanced tool for validating JWT tokens and checking permissions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## EnhancedUserInfoTool

```python
class EnhancedUserInfoTool(EnhancedBaseMCPTool):
    """
    Enhanced tool for retrieving current user information from JWT token.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## MockAuthService

```python
class MockAuthService:
    """
    Enhanced mock authentication service for development and testing.
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

## __init__

```python
def __init__(self, auth_service = None):
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedAuthenticationTool

## __init__

```python
def __init__(self, auth_service = None):
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedUserInfoTool

## __init__

```python
def __init__(self, auth_service = None):
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedTokenValidationTool

## _execute

```python
async def _execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute user authentication.
    """
```
* **Async:** True
* **Method:** True
* **Class:** EnhancedAuthenticationTool

## _execute

```python
async def _execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute user info retrieval.
    """
```
* **Async:** True
* **Method:** True
* **Class:** EnhancedUserInfoTool

## _execute

```python
async def _execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute token validation.
    """
```
* **Async:** True
* **Method:** True
* **Class:** EnhancedTokenValidationTool

## authenticate

```python
async def authenticate(self, username: str, password: str) -> Dict[str, Any]:
    """
    Authenticate user credentials with rate limiting.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MockAuthService

## decode_token

```python
async def decode_token(self, token: str) -> Dict[str, Any]:
    """
    Decode token and return payload.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MockAuthService

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

## refresh_token

```python
async def refresh_token(self, token: str) -> Dict[str, Any]:
    """
    Refresh an access token.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MockAuthService

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
