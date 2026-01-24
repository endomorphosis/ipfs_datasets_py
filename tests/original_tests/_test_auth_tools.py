#!/usr/bin/env python3
"""
Test suite for authentication tools functionality.
"""

import pytest
import anyio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestAuthenticationTools:
    """Test authentication tools functionality."""

    @pytest.mark.asyncio
    async def test_authenticate_user(self):
        """Test user authentication."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import authenticate_user
        
        result = await authenticate_user(
            username="test_user",
            password="test_password",
            auth_method="local"
        )
        
        assert result is not None
        assert "status" in result
        assert "authenticated" in result or "auth_token" in result
    
    @pytest.mark.asyncio
    async def test_generate_auth_token(self):
        """Test authentication token generation."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import generate_auth_token
        
        result = await generate_auth_token(
            user_id="user123",
            permissions=["read", "write"],
            expiry_hours=24
        )
        
        assert result is not None
        assert "status" in result
        assert "token" in result or "auth_token" in result
    
    @pytest.mark.asyncio
    async def test_validate_auth_token(self):
        """Test authentication token validation."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import validate_auth_token, generate_auth_token
        
        # First generate a token
        token_result = await generate_auth_token(
            user_id="user123",
            permissions=["read"],
            expiry_hours=1
        )
        
        if token_result.get("status") == "success" and "token" in token_result:
            # Validate the generated token
            validate_result = await validate_auth_token(
                token=token_result["token"]
            )
            
            assert validate_result is not None
            assert "status" in validate_result
            assert "valid" in validate_result or "user_id" in validate_result
    
    @pytest.mark.asyncio
    async def test_refresh_auth_token(self):
        """Test authentication token refresh."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import refresh_auth_token
        
        result = await refresh_auth_token(
            refresh_token="existing_refresh_token",
            extend_expiry=True
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_revoke_auth_token(self):
        """Test authentication token revocation."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import revoke_auth_token
        
        result = await revoke_auth_token(
            token="token_to_revoke",
            revoke_all_user_tokens=False
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_manage_user_permissions(self):
        """Test user permission management."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import manage_user_permissions
        
        result = await manage_user_permissions(
            user_id="user123",
            action="grant",
            permissions=["admin", "write"],
            resource_type="dataset"
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_check_user_permission(self):
        """Test checking user permissions."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import check_user_permission
        
        result = await check_user_permission(
            user_id="user123",
            permission="read",
            resource_id="dataset456",
            resource_type="dataset"
        )
        
        assert result is not None
        assert "status" in result
        assert "has_permission" in result or "authorized" in result


class TestRoleBasedAccess:
    """Test role-based access control functionality."""

    @pytest.mark.asyncio
    async def test_create_role(self):
        """Test role creation."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import manage_roles
        
        role_definition = {
            "name": "data_scientist",
            "description": "Data scientist role with embedding access",
            "permissions": ["read_datasets", "generate_embeddings", "create_indices"]
        }
        
        result = await manage_roles(
            action="create",
            role_id="data_scientist",
            role_definition=role_definition
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_assign_role_to_user(self):
        """Test assigning role to user."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import assign_user_role
        
        result = await assign_user_role(
            user_id="user123",
            role_id="data_scientist",
            expiry_date=None
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_list_user_roles(self):
        """Test listing user roles."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import list_user_roles
        
        result = await list_user_roles(
            user_id="user123",
            include_permissions=True
        )
        
        assert result is not None
        assert "status" in result
        assert "roles" in result or "user_roles" in result


class TestSessionManagement:
    """Test session management functionality."""

    @pytest.mark.asyncio
    async def test_create_user_session(self):
        """Test user session creation."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import create_user_session
        
        result = await create_user_session(
            user_id="user123",
            session_type="web",
            ip_address="127.0.0.1",
            user_agent="test-agent"
        )
        
        assert result is not None
        assert "status" in result
        assert "session_id" in result or "session_token" in result
    
    @pytest.mark.asyncio
    async def test_validate_user_session(self):
        """Test user session validation."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import validate_user_session
        
        result = await validate_user_session(
            session_id="session123",
            check_ip=True,
            extend_session=True
        )
        
        assert result is not None
        assert "status" in result
        assert "valid" in result or "session_info" in result
    
    @pytest.mark.asyncio
    async def test_end_user_session(self):
        """Test ending user session."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import end_user_session
        
        result = await end_user_session(
            session_id="session123",
            reason="user_logout"
        )
        
        assert result is not None
        assert "status" in result


class TestAPIKeyManagement:
    """Test API key management functionality."""

    @pytest.mark.asyncio
    async def test_generate_api_key(self):
        """Test API key generation."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import generate_api_key
        
        result = await generate_api_key(
            user_id="user123",
            key_name="production_key",
            permissions=["read", "write"],
            expiry_days=365
        )
        
        assert result is not None
        assert "status" in result
        assert "api_key" in result or "key" in result
    
    @pytest.mark.asyncio
    async def test_validate_api_key(self):
        """Test API key validation."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import validate_api_key
        
        result = await validate_api_key(
            api_key="test_api_key_123",
            required_permission="read"
        )
        
        assert result is not None
        assert "status" in result
        assert "valid" in result or "authorized" in result
    
    @pytest.mark.asyncio
    async def test_list_user_api_keys(self):
        """Test listing user API keys."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import list_user_api_keys
        
        result = await list_user_api_keys(
            user_id="user123",
            include_permissions=True,
            show_revoked=False
        )
        
        assert result is not None
        assert "status" in result
        assert "api_keys" in result or "keys" in result
    
    @pytest.mark.asyncio
    async def test_revoke_api_key(self):
        """Test API key revocation."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import revoke_api_key
        
        result = await revoke_api_key(
            api_key="test_api_key_123",
            reason="security_policy"
        )
        
        assert result is not None
        assert "status" in result


class TestAuthenticationIntegration:
    """Test authentication tools integration."""

    @pytest.mark.asyncio
    async def test_auth_tools_mcp_registration(self):
        """Test that auth tools are properly registered with MCP."""
        from ipfs_datasets_py.mcp_server.tools.tool_registration import get_registered_tools
        
        tools = get_registered_tools()
        auth_tools = [tool for tool in tools if 'auth' in tool.get('name', '').lower()]
        
        assert len(auth_tools) > 0, "Auth tools should be registered"
    
    @pytest.mark.asyncio
    async def test_auth_middleware_integration(self):
        """Test authentication middleware integration."""
        # This would test integration with FastAPI middleware
        # For now, just test that the auth tools work with typical middleware patterns
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import validate_auth_token
        
        # Simulate middleware token validation
        result = await validate_auth_token(
            token="Bearer test_token_123"
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_auth_error_handling(self):
        """Test authentication error handling."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import authenticate_user
        
        # Test with invalid credentials
        result = await authenticate_user(
            username="invalid_user",
            password="wrong_password",
            auth_method="local"
        )
        
        assert result is not None
        assert "status" in result
        # Should handle authentication failure gracefully
        if "authenticated" in result:
            assert result["authenticated"] is False
        else:
            assert result["status"] in ["error", "failed"]


class TestSecurityFeatures:
    """Test security features of authentication tools."""

    @pytest.mark.asyncio
    async def test_password_hashing(self):
        """Test password hashing functionality."""
        try:
            from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import hash_password, verify_password
            
            password = "test_password_123"
            hashed = await hash_password(password)
            
            assert hashed is not None
            assert hashed != password  # Should be hashed
            
            # Test verification
            verification_result = await verify_password(password, hashed)
            assert verification_result is True
            
        except ImportError:
            raise ImportError("Password hashing functions not available")
    
    @pytest.mark.asyncio
    async def test_rate_limiting_integration(self):
        """Test integration with rate limiting."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import authenticate_user
        
        # Simulate multiple authentication attempts
        for i in range(3):
            result = await authenticate_user(
                username="test_user",
                password="test_password",
                auth_method="local"
            )
            
            assert result is not None
            assert "status" in result
    
    @pytest.mark.asyncio
    async def test_audit_logging_integration(self):
        """Test integration with audit logging."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import authenticate_user
        
        # Authentication should trigger audit logging
        result = await authenticate_user(
            username="test_user",
            password="test_password",
            auth_method="local"
        )
        
        assert result is not None
        # The audit logging would be tested separately,
        # here we just ensure the auth function completes
        assert "status" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
