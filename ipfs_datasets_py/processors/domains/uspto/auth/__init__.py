"""USPTO operator authentication helpers (session login / export).

Secrets are resolved only through opaque references or interactive prompts.
Session material stays under the operator state root with mode 0600 and is
never embedded in receipts or MCP responses.
"""

from .login_session import (
    FORBIDDEN_LOGIN_CAPABILITIES,
    LoginError,
    LoginResult,
    SessionStatus,
    generate_totp,
    load_session_status,
    login_patent_center,
    logout_session,
    resolve_secret_ref,
)

__all__ = [
    "FORBIDDEN_LOGIN_CAPABILITIES",
    "LoginError",
    "LoginResult",
    "SessionStatus",
    "generate_totp",
    "load_session_status",
    "login_patent_center",
    "logout_session",
    "resolve_secret_ref",
]
