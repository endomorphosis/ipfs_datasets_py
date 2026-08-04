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
from .patent_center_export_client import (
    PatentCenterExportResult,
    export_application_via_patent_center,
)

__all__ = [
    "FORBIDDEN_LOGIN_CAPABILITIES",
    "LoginError",
    "LoginResult",
    "PatentCenterExportResult",
    "SessionStatus",
    "export_application_via_patent_center",
    "generate_totp",
    "load_session_status",
    "login_patent_center",
    "logout_session",
    "resolve_secret_ref",
]
