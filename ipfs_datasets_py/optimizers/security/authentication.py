"""Authentication utilities for optimizer APIs.

This module is intentionally lightweight and dependency-minimal.

It provides:
- JWT access/refresh tokens
- In-memory token blacklist
- bcrypt password hashing
- Simple API key auth (in-memory)
- FastAPI/Starlette middleware + permission decorators

The implementation is designed to be safe-by-default and to satisfy
unit-test expectations without requiring external persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import wraps
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, TypeVar

import bcrypt
import jwt
from fastapi import HTTPException, Request
from jwt import ExpiredSignatureError, InvalidTokenError as PyJWTInvalidTokenError
from starlette.responses import JSONResponse, Response


DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES = 30
DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS = 7
DEFAULT_ALGORITHM = "HS256"

MIN_API_KEY_LENGTH = 32


class AuthenticationError(Exception):
    """Base class for authentication/authorization failures."""


class InvalidTokenError(AuthenticationError):
    """Raised when a token is invalid, expired, or revoked."""


class InsufficientPermissionsError(AuthenticationError):
    """Raised when a user lacks a required role/permission."""


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"
    API_KEY = "api_key"


@dataclass(frozen=True)
class TokenPayload:
    user_id: str
    token_type: TokenType
    roles: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    extra_claims: Dict[str, Any] = field(default_factory=dict)

    def has_role(self, role: str) -> bool:
        return bool(role) and role in (self.roles or [])

    def has_permission(self, permission: str) -> bool:
        return bool(permission) and permission in (self.permissions or [])

    def has_any_role(self, required_roles: Iterable[str]) -> bool:
        required = list(required_roles)
        if not required:
            return False
        roles = set(self.roles or [])
        return any(r in roles for r in required)

    def has_all_roles(self, required_roles: Iterable[str]) -> bool:
        required = list(required_roles)
        if not required:
            return True
        roles = set(self.roles or [])
        return all(r in roles for r in required)


class TokenBlacklist:
    """In-memory blacklist of revoked tokens.

    Note: This is intentionally simple. For production deployments,
    use a shared store (Redis/DB) and a bounded eviction strategy.
    """

    def __init__(self) -> None:
        self._tokens: Dict[str, Optional[datetime]] = {}

    def add(self, token: str, expires_at: Optional[datetime] = None) -> None:
        self._tokens[token] = _ensure_utc(expires_at)

    def is_blacklisted(self, token: str) -> bool:
        expires_at = _ensure_utc(self._tokens.get(token))
        if token not in self._tokens:
            return False
        if expires_at is None:
            return True
        now = _utcnow()
        if expires_at <= now:
            # Expired entries no longer matter.
            self._tokens.pop(token, None)
            return False
        return True

    def cleanup_expired(self) -> None:
        now = _utcnow()
        expired = [
            t
            for t, exp in self._tokens.items()
            if (exp_utc := _ensure_utc(exp)) is not None and exp_utc <= now
        ]
        for token in expired:
            self._tokens.pop(token, None)


class PasswordHasher:
    """bcrypt password hashing helper."""

    def __init__(self, rounds: int = 12) -> None:
        self.rounds = rounds

    def hash_password(self, password: str) -> str:
        if not password:
            raise ValueError("Password cannot be empty")
        salt = bcrypt.gensalt(rounds=self.rounds)
        hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
        return hashed.decode("utf-8")

    def verify_password(self, password: str, hashed_password: str) -> bool:
        if not password or not hashed_password:
            return False
        try:
            return bool(
                bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
            )
        except (ValueError, TypeError):
            return False


@dataclass
class AuthConfig:
    secret_key: str
    algorithm: str = DEFAULT_ALGORITHM
    access_token_expire_minutes: int = DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES
    refresh_token_expire_days: int = DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS

    require_https: bool = True
    enable_token_blacklist: bool = True
    enable_api_keys: bool = True
    allowed_origins: List[str] = field(default_factory=list)


class JWTAuthenticator:
    def __init__(self, config: AuthConfig, blacklist: Optional[TokenBlacklist] = None) -> None:
        self.config = config
        self.blacklist = blacklist or TokenBlacklist()

    def create_access_token(
        self,
        *,
        user_id: str,
        roles: Optional[List[str]] = None,
        permissions: Optional[List[str]] = None,
        extra_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        now = _utcnow()
        expires = now + timedelta(minutes=int(self.config.access_token_expire_minutes))
        claims: Dict[str, Any] = {
            "user_id": user_id,
            "token_type": TokenType.ACCESS.value,
            "roles": roles or [],
            "permissions": permissions or [],
            "iat": now,
            "exp": expires,
        }
        if extra_claims:
            claims.update(extra_claims)
        return jwt.encode(claims, self.config.secret_key, algorithm=self.config.algorithm)

    def create_refresh_token(
        self,
        *,
        user_id: str,
        extra_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        now = _utcnow()
        expires = now + timedelta(days=int(self.config.refresh_token_expire_days))
        claims: Dict[str, Any] = {
            "user_id": user_id,
            "token_type": TokenType.REFRESH.value,
            "iat": now,
            "exp": expires,
        }
        if extra_claims:
            claims.update(extra_claims)
        return jwt.encode(claims, self.config.secret_key, algorithm=self.config.algorithm)

    def verify_token(self, token: str) -> TokenPayload:
        if self.config.enable_token_blacklist and self.blacklist.is_blacklisted(token):
            raise InvalidTokenError("Token has been revoked")

        try:
            claims = jwt.decode(
                token,
                self.config.secret_key,
                algorithms=[self.config.algorithm],
                options={"require": ["exp"]},
            )
        except ExpiredSignatureError as exc:
            raise InvalidTokenError("Token has expired") from exc
        except PyJWTInvalidTokenError as exc:
            raise InvalidTokenError("Invalid token") from exc
        except Exception as exc:
            raise InvalidTokenError("Invalid token") from exc

        token_type = TokenType(claims.get("token_type", TokenType.ACCESS.value))
        issued_at = _claim_to_datetime(claims.get("iat"))
        expires_at = _claim_to_datetime(claims.get("exp"))

        # Preserve any non-standard claims.
        extra_claims = {
            k: v
            for k, v in claims.items()
            if k not in {"user_id", "token_type", "roles", "permissions", "iat", "exp"}
        }

        return TokenPayload(
            user_id=str(claims.get("user_id", "")),
            token_type=token_type,
            roles=list(claims.get("roles") or []),
            permissions=list(claims.get("permissions") or []),
            issued_at=issued_at,
            expires_at=expires_at,
            extra_claims=extra_claims,
        )

    def revoke_token(self, token: str) -> None:
        if not self.config.enable_token_blacklist:
            return
        expires_at: Optional[datetime] = None
        try:
            # Decode without signature verification to extract exp.
            claims = jwt.decode(token, options={"verify_signature": False})
            expires_at = _claim_to_datetime(claims.get("exp"))
        except Exception:
            expires_at = None
        self.blacklist.add(token, expires_at)

    def refresh_access_token(self, refresh_token: str) -> str:
        payload = self.verify_token(refresh_token)
        if payload.token_type != TokenType.REFRESH:
            raise InvalidTokenError("Token is not a refresh token")
        return self.create_access_token(
            user_id=payload.user_id,
            roles=payload.roles,
            permissions=payload.permissions,
        )


class APIKeyAuthenticator:
    """Simple in-memory API key authentication."""

    def __init__(self) -> None:
        self._keys: Dict[str, TokenPayload] = {}

    def generate_api_key(
        self,
        *,
        user_id: str,
        roles: Optional[List[str]] = None,
        permissions: Optional[List[str]] = None,
        extra_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        import secrets

        # Ensure minimum length by generating enough entropy.
        api_key = secrets.token_urlsafe(48)
        while len(api_key) < MIN_API_KEY_LENGTH:
            api_key = secrets.token_urlsafe(48)

        payload = TokenPayload(
            user_id=user_id,
            token_type=TokenType.API_KEY,
            roles=roles or [],
            permissions=permissions or [],
            issued_at=_utcnow(),
            expires_at=None,
            extra_claims=extra_claims or {},
        )
        self._keys[api_key] = payload
        return api_key

    def verify_api_key(self, api_key: str) -> TokenPayload:
        if not api_key or len(api_key) < MIN_API_KEY_LENGTH:
            raise InvalidTokenError("Invalid API key")
        payload = self._keys.get(api_key)
        if payload is None:
            raise InvalidTokenError("Invalid API key")
        return payload

    def revoke_api_key(self, api_key: str) -> None:
        self._keys.pop(api_key, None)


_T = TypeVar("_T")


class AuthenticationMiddleware:
    """FastAPI/Starlette middleware for JWT + API key authentication."""

    def __init__(
        self,
        app: Any,
        *,
        jwt_authenticator: JWTAuthenticator,
        api_key_authenticator: Optional[APIKeyAuthenticator] = None,
        exempt_paths: Optional[List[str]] = None,
    ) -> None:
        self.app = app
        self.jwt_authenticator = jwt_authenticator
        self.api_key_authenticator = api_key_authenticator
        self.exempt_paths = set(exempt_paths or [])

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if getattr(request, "url", None) is not None and request.url.path in self.exempt_paths:
            return await call_next(request)

        # API key takes precedence if present.
        api_key = request.headers.get("X-API-Key")
        if api_key and self.api_key_authenticator is not None:
            try:
                request.state.user = self.api_key_authenticator.verify_api_key(api_key)
                return await call_next(request)
            except AuthenticationError as exc:
                return JSONResponse(status_code=401, content={"detail": str(exc)})

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "Missing credentials"})

        token = auth_header[len("Bearer ") :].strip()
        try:
            request.state.user = self.jwt_authenticator.verify_token(token)
        except AuthenticationError as exc:
            return JSONResponse(status_code=401, content={"detail": str(exc)})

        return await call_next(request)


def get_current_user(request: Request) -> Optional[TokenPayload]:
    state = getattr(request, "state", None)
    if state is None:
        return None
    return getattr(state, "user", None)


def require_role(role: str) -> Callable[[Callable[..., Awaitable[_T]]], Callable[..., Awaitable[_T]]]:
    def decorator(func: Callable[..., Awaitable[_T]]) -> Callable[..., Awaitable[_T]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> _T:
            request = _extract_request(args, kwargs)
            user = get_current_user(request) if request is not None else None
            if user is None or not user.has_role(role):
                raise HTTPException(status_code=403, detail=f"Missing required role: {role}")
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_permission(
    permission: str,
) -> Callable[[Callable[..., Awaitable[_T]]], Callable[..., Awaitable[_T]]]:
    def decorator(func: Callable[..., Awaitable[_T]]) -> Callable[..., Awaitable[_T]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> _T:
            request = _extract_request(args, kwargs)
            user = get_current_user(request) if request is not None else None
            if user is None or not user.has_permission(permission):
                raise HTTPException(
                    status_code=403, detail=f"Missing required permission: {permission}"
                )
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def _extract_request(args: Any, kwargs: Any) -> Optional[Request]:
    # Common FastAPI dependency signature: endpoint(request: Request, ...)
    if "request" in kwargs and isinstance(kwargs["request"], Request):
        return kwargs["request"]
    for arg in args:
        if isinstance(arg, Request):
            return arg
    return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _claim_to_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    # Best effort parse.
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except Exception:
        return None
