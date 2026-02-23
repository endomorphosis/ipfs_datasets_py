"""
Comprehensive unit tests for authentication.py module.

Tests cover:
    - TokenPayload role and permission checking
    - TokenBlacklist management
    - PasswordHasher (bcrypt hashing)
    - JWTAuthenticator token lifecycle
    - APIKeyAuthenticator
    - AuthenticationMiddleware (async)
    - Permission decorators
    - AuthConfig
"""

import pytest
import jwt
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from fastapi import Request, HTTPException
from starlette.responses import JSONResponse

from ipfs_datasets_py.optimizers.security.authentication import (
    TokenPayload,
    TokenType,
    TokenBlacklist,
    PasswordHasher,
    JWTAuthenticator,
    APIKeyAuthenticator,
    AuthenticationMiddleware,
    AuthConfig,
    AuthenticationError,
    InvalidTokenError,
    InsufficientPermissionsError,
    require_role,
    require_permission,
    get_current_user,
    DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES,
    DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS,
    DEFAULT_ALGORITHM,
    MIN_API_KEY_LENGTH,
)


# ==================== TestTokenPayload ====================

class TestTokenPayload:
    """Test TokenPayload role and permission checking."""
    
    def test_has_role_true(self):
        """Test has_role returns True when role exists."""
        payload = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS,
            roles=["admin", "user"]
        )
        assert payload.has_role("admin") is True
        assert payload.has_role("user") is True
    
    def test_has_role_false(self):
        """Test has_role returns False when role doesn't exist."""
        payload = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS,
            roles=["user"]
        )
        assert payload.has_role("admin") is False
    
    def test_has_role_empty_roles(self):
        """Test has_role with no roles."""
        payload = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS
        )
        assert payload.has_role("admin") is False
    
    def test_has_permission_true(self):
        """Test has_permission returns True when permission exists."""
        payload = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS,
            permissions=["read", "write", "delete"]
        )
        assert payload.has_permission("read") is True
        assert payload.has_permission("write") is True
    
    def test_has_permission_false(self):
        """Test has_permission returns False when permission doesn't exist."""
        payload = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS,
            permissions=["read"]
        )
        assert payload.has_permission("delete") is False
    
    def test_has_permission_empty_permissions(self):
        """Test has_permission with no permissions."""
        payload = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS
        )
        assert payload.has_permission("read") is False
    
    def test_has_any_role_true(self):
        """Test has_any_role returns True when at least one role matches."""
        payload = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS,
            roles=["user", "moderator"]
        )
        assert payload.has_any_role(["admin", "user"]) is True
        assert payload.has_any_role(["moderator", "superuser"]) is True
    
    def test_has_any_role_false(self):
        """Test has_any_role returns False when no roles match."""
        payload = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS,
            roles=["user"]
        )
        assert payload.has_any_role(["admin", "moderator"]) is False
    
    def test_has_any_role_empty(self):
        """Test has_any_role with empty roles list."""
        payload = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS,
            roles=["user"]
        )
        assert payload.has_any_role([]) is False
    
    def test_has_all_roles_true(self):
        """Test has_all_roles returns True when all roles match."""
        payload = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS,
            roles=["admin", "user", "moderator"]
        )
        assert payload.has_all_roles(["admin", "user"]) is True
        assert payload.has_all_roles(["moderator"]) is True
    
    def test_has_all_roles_false(self):
        """Test has_all_roles returns False when not all roles match."""
        payload = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS,
            roles=["user", "moderator"]
        )
        assert payload.has_all_roles(["admin", "user"]) is False
    
    def test_has_all_roles_empty(self):
        """Test has_all_roles with empty required roles."""
        payload = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS,
            roles=["user"]
        )
        assert payload.has_all_roles([]) is True  # All of nothing is True


# ==================== TestTokenBlacklist ====================

class TestTokenBlacklist:
    """Test TokenBlacklist functionality."""
    
    def test_add_token(self):
        """Test adding token to blacklist."""
        blacklist = TokenBlacklist()
        blacklist.add("token123")
        assert blacklist.is_blacklisted("token123") is True
    
    def test_add_token_with_expiry(self):
        """Test adding token with expiry time."""
        blacklist = TokenBlacklist()
        expires_at = datetime.utcnow() + timedelta(hours=1)
        blacklist.add("token123", expires_at)
        assert blacklist.is_blacklisted("token123") is True
    
    def test_is_blacklisted_false(self):
        """Test checking non-blacklisted token."""
        blacklist = TokenBlacklist()
        assert blacklist.is_blacklisted("token123") is False
    
    def test_cleanup_expired(self):
        """Test cleaning up expired tokens."""
        blacklist = TokenBlacklist()
        
        # Add expired token
        expired = datetime.utcnow() - timedelta(seconds=1)
        blacklist.add("expired_token", expired)
        
        # Add valid token
        valid = datetime.utcnow() + timedelta(hours=1)
        blacklist.add("valid_token", valid)
        
        # Cleanup
        blacklist.cleanup_expired()
        
        assert blacklist.is_blacklisted("expired_token") is False
        assert blacklist.is_blacklisted("valid_token") is True
    
    def test_cleanup_expired_no_expiry(self):
        """Test cleanup doesn't affect tokens without expiry."""
        blacklist = TokenBlacklist()
        blacklist.add("token_no_expiry")
        blacklist.cleanup_expired()
        assert blacklist.is_blacklisted("token_no_expiry") is True
    
    def test_multiple_tokens(self):
        """Test managing multiple tokens."""
        blacklist = TokenBlacklist()
        tokens = ["token1", "token2", "token3"]
        for token in tokens:
            blacklist.add(token)
        
        for token in tokens:
            assert blacklist.is_blacklisted(token) is True


# ==================== TestPasswordHasher ====================

class TestPasswordHasher:
    """Test PasswordHasher functionality."""
    
    def test_hash_password(self):
        """Test password hashing."""
        hasher = PasswordHasher(rounds=4)  # Use low rounds for speed
        password = "my_secure_password"
        hashed = hasher.hash_password(password)
        
        assert hashed != password
        assert isinstance(hashed, str)
        assert hashed.startswith("$2b$")  # bcrypt format
    
    def test_hash_password_empty(self):
        """Test hashing empty password raises ValueError."""
        hasher = PasswordHasher()
        with pytest.raises(ValueError, match="Password cannot be empty"):
            hasher.hash_password("")
    
    def test_verify_password_correct(self):
        """Test verifying correct password."""
        hasher = PasswordHasher(rounds=4)
        password = "correct_password"
        hashed = hasher.hash_password(password)
        
        assert hasher.verify_password(password, hashed) is True
    
    def test_verify_password_incorrect(self):
        """Test verifying incorrect password."""
        hasher = PasswordHasher(rounds=4)
        password = "correct_password"
        hashed = hasher.hash_password(password)
        
        assert hasher.verify_password("wrong_password", hashed) is False
    
    def test_verify_password_empty_password(self):
        """Test verifying with empty password."""
        hasher = PasswordHasher(rounds=4)
        hashed = hasher.hash_password("password")
        
        assert hasher.verify_password("", hashed) is False
    
    def test_verify_password_empty_hash(self):
        """Test verifying with empty hash."""
        hasher = PasswordHasher()
        assert hasher.verify_password("password", "") is False
    
    def test_verify_password_invalid_hash(self):
        """Test verifying with invalid hash format."""
        hasher = PasswordHasher()
        assert hasher.verify_password("password", "invalid_hash") is False
    
    def test_bcrypt_rounds_configuration(self):
        """Test bcrypt rounds configuration."""
        hasher = PasswordHasher(rounds=10)
        assert hasher.rounds == 10
    
    def test_different_passwords_different_hashes(self):
        """Test different passwords produce different hashes."""
        hasher = PasswordHasher(rounds=4)
        hash1 = hasher.hash_password("password1")
        hash2 = hasher.hash_password("password2")
        
        assert hash1 != hash2
    
    def test_same_password_different_salts(self):
        """Test same password produces different hashes (different salts)."""
        hasher = PasswordHasher(rounds=4)
        password = "same_password"
        hash1 = hasher.hash_password(password)
        hash2 = hasher.hash_password(password)
        
        assert hash1 != hash2  # Different salts
        assert hasher.verify_password(password, hash1)
        assert hasher.verify_password(password, hash2)


# ==================== TestJWTAuthenticator ====================

class TestJWTAuthenticator:
    """Test JWTAuthenticator functionality."""
    
    @pytest.fixture
    def config(self):
        """Create test auth config."""
        return AuthConfig(
            secret_key="test_secret_key",
            algorithm="HS256",
            access_token_expire_minutes=30,
            refresh_token_expire_days=7
        )
    
    @pytest.fixture
    def authenticator(self, config):
        """Create test authenticator."""
        return JWTAuthenticator(config)
    
    def test_create_access_token(self, authenticator):
        """Test creating access token."""
        token = authenticator.create_access_token(
            user_id="user123",
            roles=["admin"],
            permissions=["read", "write"]
        )
        
        assert isinstance(token, str)
        assert len(token) > 0
    
    def test_create_access_token_minimal(self, authenticator):
        """Test creating access token with minimal parameters."""
        token = authenticator.create_access_token(user_id="user123")
        assert isinstance(token, str)
    
    def test_create_access_token_extra_claims(self, authenticator):
        """Test creating access token with extra claims."""
        token = authenticator.create_access_token(
            user_id="user123",
            extra_claims={"custom": "value", "another": 123}
        )
        
        payload = authenticator.verify_token(token)
        # Verify base fields exist
        assert payload.user_id == "user123"
    
    def test_create_refresh_token(self, authenticator):
        """Test creating refresh token."""
        token = authenticator.create_refresh_token(user_id="user123")
        
        assert isinstance(token, str)
        assert len(token) > 0
    
    def test_verify_token_valid(self, authenticator):
        """Test verifying valid access token."""
        token = authenticator.create_access_token(
            user_id="user123",
            roles=["admin", "user"],
            permissions=["read", "write"]
        )
        
        payload = authenticator.verify_token(token)
        
        assert payload.user_id == "user123"
        assert payload.token_type == TokenType.ACCESS
        assert "admin" in payload.roles
        assert "user" in payload.roles
        assert "read" in payload.permissions
        assert "write" in payload.permissions
        assert payload.issued_at is not None
        assert payload.expires_at is not None
    
    def test_verify_token_expired(self, config):
        """Test verifying expired token raises InvalidTokenError."""
        # Create config with very short expiry
        config.access_token_expire_minutes = 0
        authenticator = JWTAuthenticator(config)
        
        # Create token that expires immediately
        now = datetime.utcnow()
        expires = now - timedelta(seconds=1)  # Already expired
        
        claims = {
            "user_id": "user123",
            "token_type": TokenType.ACCESS.value,
            "iat": now,
            "exp": expires,
        }
        
        token = jwt.encode(claims, config.secret_key, algorithm=config.algorithm)
        
        with pytest.raises(InvalidTokenError, match="Token has expired"):
            authenticator.verify_token(token)
    
    def test_verify_token_invalid_signature(self, authenticator):
        """Test verifying token with invalid signature."""
        # Create token with wrong secret
        token = jwt.encode(
            {"user_id": "user123", "exp": datetime.utcnow() + timedelta(hours=1)},
            "wrong_secret",
            algorithm="HS256"
        )
        
        with pytest.raises(InvalidTokenError, match="Invalid token"):
            authenticator.verify_token(token)
    
    def test_verify_token_malformed(self, authenticator):
        """Test verifying malformed token."""
        with pytest.raises(InvalidTokenError, match="Invalid token"):
            authenticator.verify_token("not.a.valid.jwt.token")
    
    def test_verify_token_blacklisted(self, authenticator):
        """Test verifying blacklisted token."""
        token = authenticator.create_access_token(user_id="user123")
        authenticator.revoke_token(token)
        
        with pytest.raises(InvalidTokenError, match="Token has been revoked"):
            authenticator.verify_token(token)
    
    def test_revoke_token(self, authenticator):
        """Test revoking token adds it to blacklist."""
        token = authenticator.create_access_token(user_id="user123")
        
        # Token should be valid before revocation
        payload = authenticator.verify_token(token)
        assert payload.user_id == "user123"
        
        # Revoke token
        authenticator.revoke_token(token)
        
        # Token should be blacklisted after revocation
        assert authenticator.blacklist.is_blacklisted(token) is True
    
    def test_revoke_token_blacklist_disabled(self, config):
        """Test revoking token when blacklist is disabled."""
        config.enable_token_blacklist = False
        authenticator = JWTAuthenticator(config)
        
        token = authenticator.create_access_token(user_id="user123")
        authenticator.revoke_token(token)
        
        # Token should still be valid (not blacklisted)
        payload = authenticator.verify_token(token)
        assert payload.user_id == "user123"
    
    def test_refresh_access_token(self, authenticator):
        """Test refreshing access token from refresh token."""
        refresh_token = authenticator.create_refresh_token(user_id="user123")
        
        # Refresh to get new access token
        new_access_token = authenticator.refresh_access_token(refresh_token)
        
        assert isinstance(new_access_token, str)
        assert new_access_token != refresh_token
        
        # Verify new access token
        payload = authenticator.verify_token(new_access_token)
        assert payload.user_id == "user123"
        assert payload.token_type == TokenType.ACCESS
    
    def test_refresh_access_token_invalid_type(self, authenticator):
        """Test refreshing with non-refresh token raises error."""
        access_token = authenticator.create_access_token(user_id="user123")
        
        with pytest.raises(InvalidTokenError, match="not a refresh token"):
            authenticator.refresh_access_token(access_token)
    
    def test_token_payload_extraction(self, authenticator):
        """Test extracting roles and permissions from token."""
        roles = ["admin", "moderator"]
        permissions = ["read", "write", "delete"]
        
        token = authenticator.create_access_token(
            user_id="user123",
            roles=roles,
            permissions=permissions
        )
        
        payload = authenticator.verify_token(token)
        
        assert payload.roles == roles
        assert payload.permissions == permissions


# ==================== TestAPIKeyAuthenticator ====================

class TestAPIKeyAuthenticator:
    """Test APIKeyAuthenticator functionality."""
    
    @pytest.fixture
    def authenticator(self):
        """Create test API key authenticator."""
        return APIKeyAuthenticator()
    
    def test_generate_api_key(self, authenticator):
        """Test generating API key."""
        api_key = authenticator.generate_api_key(
            user_id="user123",
            roles=["admin"],
            permissions=["read"]
        )
        
        assert isinstance(api_key, str)
        assert len(api_key) >= MIN_API_KEY_LENGTH
    
    def test_generate_api_key_minimal(self, authenticator):
        """Test generating API key with minimal parameters."""
        api_key = authenticator.generate_api_key(user_id="user123")
        assert isinstance(api_key, str)
    
    def test_generate_api_key_unique(self, authenticator):
        """Test generating multiple unique API keys."""
        key1 = authenticator.generate_api_key(user_id="user1")
        key2 = authenticator.generate_api_key(user_id="user2")
        
        assert key1 != key2
    
    def test_verify_api_key_valid(self, authenticator):
        """Test verifying valid API key."""
        api_key = authenticator.generate_api_key(
            user_id="user123",
            roles=["admin"],
            permissions=["read", "write"]
        )
        
        payload = authenticator.verify_api_key(api_key)
        
        assert payload.user_id == "user123"
        assert payload.token_type == TokenType.API_KEY
        assert "admin" in payload.roles
        assert "read" in payload.permissions
        assert payload.issued_at is not None
    
    def test_verify_api_key_invalid(self, authenticator):
        """Test verifying invalid API key raises error."""
        with pytest.raises(InvalidTokenError, match="Invalid API key"):
            authenticator.verify_api_key("invalid_key")
    
    def test_revoke_api_key(self, authenticator):
        """Test revoking API key."""
        api_key = authenticator.generate_api_key(user_id="user123")
        
        # Verify key is valid before revocation
        payload = authenticator.verify_api_key(api_key)
        assert payload.user_id == "user123"
        
        # Revoke key
        authenticator.revoke_api_key(api_key)
        
        # Key should be invalid after revocation
        with pytest.raises(InvalidTokenError, match="Invalid API key"):
            authenticator.verify_api_key(api_key)
    
    def test_revoke_nonexistent_api_key(self, authenticator):
        """Test revoking non-existent API key doesn't raise error."""
        # Should not raise exception
        authenticator.revoke_api_key("nonexistent_key")


# ==================== TestAuthenticationMiddleware ====================

@pytest.mark.asyncio
class TestAuthenticationMiddleware:
    """Test AuthenticationMiddleware functionality."""
    
    @pytest.fixture
    def config(self):
        """Create test auth config."""
        return AuthConfig(
            secret_key="test_secret",
            algorithm="HS256"
        )
    
    @pytest.fixture
    def jwt_auth(self, config):
        """Create JWT authenticator."""
        return JWTAuthenticator(config)
    
    @pytest.fixture
    def api_key_auth(self):
        """Create API key authenticator."""
        return APIKeyAuthenticator()
    
    @pytest.fixture
    def app(self):
        """Create mock FastAPI app."""
        return Mock()
    
    async def test_middleware_with_valid_jwt_token(self, app, jwt_auth):
        """Test middleware with valid JWT Bearer token."""
        middleware = AuthenticationMiddleware(
            app=app,
            jwt_authenticator=jwt_auth
        )
        
        # Create valid token
        token = jwt_auth.create_access_token(user_id="user123", roles=["admin"])
        
        # Mock request with Bearer token
        request = Mock(spec=Request)
        request.url.path = "/api/resource"
        request.headers.get = Mock(return_value=f"Bearer {token}")
        request.state = Mock()
        
        # Mock call_next
        call_next = AsyncMock(return_value=Mock())
        
        # Process request
        response = await middleware.dispatch(request, call_next)
        
        # Verify user was set on request state
        assert hasattr(request.state, 'user')
        assert request.state.user.user_id == "user123"
        
        # Verify call_next was called
        call_next.assert_called_once()
    
    async def test_middleware_with_invalid_token(self, app, jwt_auth):
        """Test middleware with invalid JWT token."""
        middleware = AuthenticationMiddleware(
            app=app,
            jwt_authenticator=jwt_auth
        )
        
        # Mock request with invalid token
        request = Mock(spec=Request)
        request.url.path = "/api/resource"
        request.headers.get = Mock(return_value="Bearer invalid_token")
        
        # Mock call_next
        call_next = AsyncMock()
        
        # Process request
        response = await middleware.dispatch(request, call_next)
        
        # Verify unauthorized response
        assert isinstance(response, JSONResponse)
        assert response.status_code == 401
        
        # Verify call_next was not called
        call_next.assert_not_called()
    
    async def test_middleware_with_expired_token(self, app, config):
        """Test middleware with expired JWT token."""
        # Create authenticator
        jwt_auth = JWTAuthenticator(config)
        middleware = AuthenticationMiddleware(
            app=app,
            jwt_authenticator=jwt_auth
        )
        
        # Create expired token manually
        now = datetime.utcnow()
        expired = now - timedelta(seconds=10)
        
        claims = {
            "user_id": "user123",
            "iat": now - timedelta(minutes=1),
            "exp": expired,
        }
        
        token = jwt.encode(claims, config.secret_key, algorithm=config.algorithm)
        
        # Mock request
        request = Mock(spec=Request)
        request.url.path = "/api/resource"
        request.headers.get = Mock(return_value=f"Bearer {token}")
        
        # Mock call_next
        call_next = AsyncMock()
        
        # Process request
        response = await middleware.dispatch(request, call_next)
        
        # Verify unauthorized response
        assert isinstance(response, JSONResponse)
        assert response.status_code == 401
    
    async def test_middleware_with_valid_api_key(self, app, jwt_auth, api_key_auth):
        """Test middleware with valid API key."""
        middleware = AuthenticationMiddleware(
            app=app,
            jwt_authenticator=jwt_auth,
            api_key_authenticator=api_key_auth
        )
        
        # Generate API key
        api_key = api_key_auth.generate_api_key(user_id="user123")
        
        # Mock request with API key
        request = Mock(spec=Request)
        request.url.path = "/api/resource"
        request.headers.get = Mock(side_effect=lambda x: api_key if x == "X-API-Key" else None)
        request.state = Mock()
        
        # Mock call_next
        call_next = AsyncMock(return_value=Mock())
        
        # Process request
        response = await middleware.dispatch(request, call_next)
        
        # Verify user was set
        assert hasattr(request.state, 'user')
        assert request.state.user.user_id == "user123"
        call_next.assert_called_once()
    
    async def test_middleware_with_exempt_paths(self, app, jwt_auth):
        """Test middleware with exempt paths (no auth required)."""
        middleware = AuthenticationMiddleware(
            app=app,
            jwt_authenticator=jwt_auth,
            exempt_paths=["/health", "/docs"]
        )
        
        # Mock request to exempt path
        request = Mock(spec=Request)
        request.url.path = "/health"
        request.headers.get = Mock(return_value=None)
        
        # Mock call_next
        call_next = AsyncMock(return_value=Mock())
        
        # Process request
        response = await middleware.dispatch(request, call_next)
        
        # Verify call_next was called without authentication
        call_next.assert_called_once()
    
    async def test_middleware_with_missing_credentials(self, app, jwt_auth):
        """Test middleware with missing credentials."""
        middleware = AuthenticationMiddleware(
            app=app,
            jwt_authenticator=jwt_auth
        )
        
        # Mock request without credentials
        request = Mock(spec=Request)
        request.url.path = "/api/resource"
        request.headers.get = Mock(return_value=None)
        
        # Mock call_next
        call_next = AsyncMock()
        
        # Process request
        response = await middleware.dispatch(request, call_next)
        
        # Verify unauthorized response
        assert isinstance(response, JSONResponse)
        assert response.status_code == 401
        call_next.assert_not_called()
    
    async def test_middleware_with_blacklisted_token(self, app, jwt_auth):
        """Test middleware with blacklisted token."""
        middleware = AuthenticationMiddleware(
            app=app,
            jwt_authenticator=jwt_auth
        )
        
        # Create and revoke token
        token = jwt_auth.create_access_token(user_id="user123")
        jwt_auth.revoke_token(token)
        
        # Mock request
        request = Mock(spec=Request)
        request.url.path = "/api/resource"
        request.headers.get = Mock(return_value=f"Bearer {token}")
        
        # Mock call_next
        call_next = AsyncMock()
        
        # Process request
        response = await middleware.dispatch(request, call_next)
        
        # Verify unauthorized response
        assert isinstance(response, JSONResponse)
        assert response.status_code == 401


# ==================== TestPermissionDecorators ====================

@pytest.mark.asyncio
class TestPermissionDecorators:
    """Test permission decorator functions."""
    
    async def test_require_role_with_valid_role(self):
        """Test require_role decorator with user having required role."""
        # Create mock request with user
        request = Mock(spec=Request)
        request.state.user = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS,
            roles=["admin", "user"]
        )
        
        # Create decorated function
        @require_role("admin")
        async def protected_endpoint(request: Request):
            return {"message": "success"}
        
        # Call function
        result = await protected_endpoint(request)
        assert result == {"message": "success"}
    
    async def test_require_role_without_role(self):
        """Test require_role decorator raises HTTPException when role missing."""
        # Create mock request without required role
        request = Mock(spec=Request)
        request.state.user = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS,
            roles=["user"]
        )
        
        # Create decorated function
        @require_role("admin")
        async def protected_endpoint(request: Request):
            return {"message": "success"}
        
        # Call function should raise HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await protected_endpoint(request)
        
        assert exc_info.value.status_code == 403
        assert "admin" in str(exc_info.value.detail)
    
    async def test_require_role_no_user(self):
        """Test require_role decorator when no user in request state."""
        request = Mock(spec=Request)
        request.state = Mock()
        delattr(request.state, 'user')  # Ensure no user attribute
        
        @require_role("admin")
        async def protected_endpoint(request: Request):
            return {"message": "success"}
        
        with pytest.raises(HTTPException) as exc_info:
            await protected_endpoint(request)
        
        assert exc_info.value.status_code == 403
    
    async def test_require_permission_with_valid_permission(self):
        """Test require_permission decorator with user having permission."""
        request = Mock(spec=Request)
        request.state.user = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS,
            permissions=["read", "write"]
        )
        
        @require_permission("read")
        async def protected_endpoint(request: Request):
            return {"message": "success"}
        
        result = await protected_endpoint(request)
        assert result == {"message": "success"}
    
    async def test_require_permission_without_permission(self):
        """Test require_permission decorator raises exception when permission missing."""
        request = Mock(spec=Request)
        request.state.user = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS,
            permissions=["read"]
        )
        
        @require_permission("delete")
        async def protected_endpoint(request: Request):
            return {"message": "success"}
        
        with pytest.raises(HTTPException) as exc_info:
            await protected_endpoint(request)
        
        assert exc_info.value.status_code == 403
        assert "delete" in str(exc_info.value.detail)
    
    async def test_require_permission_no_user(self):
        """Test require_permission decorator when no user in request state."""
        request = Mock(spec=Request)
        request.state = Mock()
        delattr(request.state, 'user')
        
        @require_permission("read")
        async def protected_endpoint(request: Request):
            return {"message": "success"}
        
        with pytest.raises(HTTPException) as exc_info:
            await protected_endpoint(request)
        
        assert exc_info.value.status_code == 403
    
    def test_get_current_user_with_user(self):
        """Test get_current_user returns user from request state."""
        request = Mock(spec=Request)
        user = TokenPayload(
            user_id="user123",
            token_type=TokenType.ACCESS
        )
        request.state.user = user
        
        result = get_current_user(request)
        assert result == user
        assert result.user_id == "user123"
    
    def test_get_current_user_no_user(self):
        """Test get_current_user returns None when no user."""
        request = Mock(spec=Request)
        request.state = Mock()
        delattr(request.state, 'user')
        
        result = get_current_user(request)
        assert result is None


# ==================== TestAuthConfig ====================

class TestAuthConfig:
    """Test AuthConfig configuration."""
    
    def test_default_config_values(self):
        """Test AuthConfig with default values."""
        config = AuthConfig(secret_key="test_secret")
        
        assert config.secret_key == "test_secret"
        assert config.algorithm == DEFAULT_ALGORITHM
        assert config.access_token_expire_minutes == DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES
        assert config.refresh_token_expire_days == DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS
        assert config.require_https is True
        assert config.enable_token_blacklist is True
        assert config.enable_api_keys is True
        assert config.allowed_origins == []
    
    def test_custom_config_values(self):
        """Test AuthConfig with custom values."""
        config = AuthConfig(
            secret_key="custom_secret",
            algorithm="RS256",
            access_token_expire_minutes=60,
            refresh_token_expire_days=30,
            require_https=False,
            enable_token_blacklist=False,
            enable_api_keys=False,
            allowed_origins=["http://localhost:3000"]
        )
        
        assert config.secret_key == "custom_secret"
        assert config.algorithm == "RS256"
        assert config.access_token_expire_minutes == 60
        assert config.refresh_token_expire_days == 30
        assert config.require_https is False
        assert config.enable_token_blacklist is False
        assert config.enable_api_keys is False
        assert config.allowed_origins == ["http://localhost:3000"]
    
    def test_config_with_multiple_origins(self):
        """Test AuthConfig with multiple allowed origins."""
        origins = [
            "http://localhost:3000",
            "https://example.com",
            "https://app.example.com"
        ]
        config = AuthConfig(
            secret_key="test_secret",
            allowed_origins=origins
        )
        
        assert config.allowed_origins == origins
