"""
J49 — JWT token lifecycle hardening tests
===========================================
Verifies the new revocation API added to AuthenticationManager in enterprise_api.py:

  * revoke_token(token) -> bool
  * is_token_revoked(token) -> bool
  * authenticate() / verify_token() respect the revocation list
"""

import asyncio
import os
import sys
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Stub heavy optional deps before importing enterprise_api
# ---------------------------------------------------------------------------

def _install_stubs():
    """Install sys.modules stubs for uninstalled optional dependencies."""
    stubs = {
        "ipfs_datasets_py.processors": types.ModuleType("ipfs_datasets_py.processors"),
        "ipfs_datasets_py.processors.graphrag": types.ModuleType("ipfs_datasets_py.processors.graphrag"),
        "ipfs_datasets_py.processors.graphrag.complete_advanced_graphrag": types.ModuleType(
            "ipfs_datasets_py.processors.graphrag.complete_advanced_graphrag"
        ),
    }
    # Add minimal class stubs expected by enterprise_api at module level
    rag_mod = stubs["ipfs_datasets_py.processors.graphrag.complete_advanced_graphrag"]
    for cls_name in ("CompleteGraphRAGSystem", "CompleteProcessingConfiguration", "CompleteProcessingResult"):
        setattr(rag_mod, cls_name, type(cls_name, (), {}))

    for key, mod in stubs.items():
        if key not in sys.modules:
            sys.modules[key] = mod

_install_stubs()

# ---------------------------------------------------------------------------
# Import guard — enterprise_api has heavyweight FastAPI / JWT dependencies
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

try:
    from ipfs_datasets_py.mcp_server.enterprise_api import AuthenticationManager
    IMPORT_OK = True
except Exception as _e:
    IMPORT_OK = False
    _IMPORT_ERROR = str(_e)

pytestmark = pytest.mark.skipif(not IMPORT_OK, reason=f"enterprise_api not importable: {_IMPORT_ERROR if not IMPORT_OK else ''}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def auth():
    """Fresh AuthenticationManager with a fixed test key."""
    return AuthenticationManager(secret_key="test-secret-key-for-pytest")


# ---------------------------------------------------------------------------
# revoke_token
# ---------------------------------------------------------------------------

class TestRevokeToken:
    def test_revoke_valid_token_returns_true(self, auth):
        token = auth.create_access_token("demo")
        assert auth.revoke_token(token) is True

    def test_revoke_garbage_returns_false(self, auth):
        assert auth.revoke_token("not.a.valid.jwt.at.all") is False

    def test_revoke_empty_string_returns_false(self, auth):
        assert auth.revoke_token("") is False

    def test_revoke_expired_token_returns_true(self, auth):
        """Expired tokens can still be explicitly revoked (exp not enforced)."""
        from datetime import datetime, timedelta
        import jwt as pyjwt
        expired_payload = {
            "sub": "demo",
            "exp": datetime.utcnow() - timedelta(hours=1),
        }
        expired_token = pyjwt.encode(
            expired_payload, auth.secret_key, algorithm=auth.algorithm
        )
        # Should succeed because revoke_token skips expiry verification
        assert auth.revoke_token(expired_token) is True

    def test_revoke_token_with_wrong_key_returns_false(self, auth):
        import jwt as pyjwt
        from datetime import datetime, timedelta
        payload = {"sub": "demo", "exp": datetime.utcnow() + timedelta(hours=1)}
        token_wrong_key = pyjwt.encode(payload, "other-secret", algorithm="HS256")
        # auth uses "test-secret-key-for-pytest" — different key → decode fails
        assert auth.revoke_token(token_wrong_key) is False

    def test_revoke_same_token_twice_is_idempotent(self, auth):
        token = auth.create_access_token("demo")
        assert auth.revoke_token(token) is True
        assert auth.revoke_token(token) is True  # idempotent
        assert auth.is_token_revoked(token) is True

    def test_revoke_does_not_affect_other_tokens(self, auth):
        token_a = auth.create_access_token("demo")
        token_b = auth.create_access_token("admin")
        auth.revoke_token(token_a)
        assert auth.is_token_revoked(token_a) is True
        assert auth.is_token_revoked(token_b) is False


# ---------------------------------------------------------------------------
# is_token_revoked
# ---------------------------------------------------------------------------

class TestIsTokenRevoked:
    def test_fresh_token_not_revoked(self, auth):
        token = auth.create_access_token("demo")
        assert auth.is_token_revoked(token) is False

    def test_after_revoke_returns_true(self, auth):
        token = auth.create_access_token("demo")
        auth.revoke_token(token)
        assert auth.is_token_revoked(token) is True

    def test_arbitrary_string_not_revoked(self, auth):
        # An un-seen string is simply not in the revoked set
        assert auth.is_token_revoked("random-string-never-seen") is False

    def test_revoked_set_starts_empty(self, auth):
        assert len(auth._revoked_tokens) == 0

    def test_revoked_set_grows_after_revoke(self, auth):
        for i in range(5):
            # Use different usernames so each token has a distinct payload
            username = "demo" if i % 2 == 0 else "admin"
            token = auth.create_access_token(username)
            # Add a distinguishing claim so tokens are unique even if issued quickly
            import jwt as pyjwt
            from datetime import datetime, timedelta
            payload = {
                "sub": username,
                "exp": datetime.utcnow() + timedelta(minutes=30),
                "jti": str(i),  # unique per call
            }
            unique_token = pyjwt.encode(payload, auth.secret_key, algorithm=auth.algorithm)
            auth.revoke_token(unique_token)
        assert len(auth._revoked_tokens) == 5


# ---------------------------------------------------------------------------
# verify_token respects revocation
# ---------------------------------------------------------------------------

class TestVerifyTokenRevocation:
    def test_verify_returns_user_data_before_revoke(self, auth):
        token = auth.create_access_token("demo")
        result = auth.verify_token(token)
        assert result is not None
        assert result["username"] == "demo"

    def test_verify_returns_none_after_revoke(self, auth):
        token = auth.create_access_token("demo")
        auth.revoke_token(token)
        assert auth.verify_token(token) is None

    def test_verify_returns_none_for_invalid_token(self, auth):
        assert auth.verify_token("invalid.token.here") is None

    def test_verify_returns_none_for_unknown_user(self, auth):
        """Token for a user not in users_db returns None."""
        import jwt as pyjwt
        from datetime import datetime, timedelta
        payload = {"sub": "ghost_user", "exp": datetime.utcnow() + timedelta(hours=1)}
        token = pyjwt.encode(payload, auth.secret_key, algorithm=auth.algorithm)
        assert auth.verify_token(token) is None


# ---------------------------------------------------------------------------
# authenticate() respects revocation
# ---------------------------------------------------------------------------

class TestAuthenticateRevocation:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_authenticate_valid_token(self, auth):
        token = auth.create_access_token("demo")
        user = self._run(auth.authenticate(token))
        assert user.username == "demo"

    def test_authenticate_revoked_token_raises_401(self, auth):
        from fastapi import HTTPException
        token = auth.create_access_token("demo")
        auth.revoke_token(token)
        with pytest.raises(HTTPException) as exc_info:
            self._run(auth.authenticate(token))
        assert exc_info.value.status_code == 401
        assert "revoked" in exc_info.value.detail.lower()

    def test_authenticate_invalid_token_raises_401(self, auth):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            self._run(auth.authenticate("bad.token"))
        assert exc_info.value.status_code == 401

    def test_authenticate_inactive_user_raises_401(self, auth):
        from fastapi import HTTPException
        # Mark demo as inactive
        auth.users_db["demo"].is_active = False
        token = auth.create_access_token("demo")
        with pytest.raises(HTTPException) as exc_info:
            self._run(auth.authenticate(token))
        assert exc_info.value.status_code == 401
        # Restore
        auth.users_db["demo"].is_active = True

    def test_authenticate_token_without_sub_raises_401(self, auth):
        from fastapi import HTTPException
        import jwt as pyjwt
        from datetime import datetime, timedelta
        payload = {"exp": datetime.utcnow() + timedelta(hours=1)}  # no "sub"
        token = pyjwt.encode(payload, auth.secret_key, algorithm=auth.algorithm)
        with pytest.raises(HTTPException) as exc_info:
            self._run(auth.authenticate(token))
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Full lifecycle scenario
# ---------------------------------------------------------------------------

class TestJWTLifecycleScenario:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_mint_verify_use_revoke_scenario(self, auth):
        """Full lifecycle: mint → verify ok → use → revoke → verify fails."""
        from fastapi import HTTPException

        # 1. Mint
        token = auth.create_access_token("admin")
        assert isinstance(token, str) and len(token) > 10

        # 2. Verify before revoke
        data = auth.verify_token(token)
        assert data["username"] == "admin"
        assert "admin" in data["roles"]

        # 3. Use via authenticate
        user = self._run(auth.authenticate(token))
        assert user.user_id == "admin-user"

        # 4. Revoke
        assert auth.revoke_token(token) is True
        assert auth.is_token_revoked(token) is True

        # 5. Verify after revoke → None
        assert auth.verify_token(token) is None

        # 6. Authenticate after revoke → 401
        with pytest.raises(HTTPException):
            self._run(auth.authenticate(token))

    def test_multiple_tokens_independent_revocation(self, auth):
        """Revoking one token does not affect others."""
        import jwt as pyjwt
        from datetime import datetime, timedelta
        # Use jti claim to ensure tokens are distinct even if issued at the same second
        tokens = []
        for i in range(3):
            payload = {
                "sub": "demo",
                "exp": datetime.utcnow() + timedelta(minutes=30),
                "jti": f"multi-{i}",
            }
            tokens.append(pyjwt.encode(payload, auth.secret_key, algorithm=auth.algorithm))

        # Revoke middle token
        auth.revoke_token(tokens[1])

        # First and last still valid
        assert auth.verify_token(tokens[0]) is not None
        assert auth.verify_token(tokens[2]) is not None
        assert auth.verify_token(tokens[1]) is None

    def test_revocation_store_is_instance_scoped(self):
        """Two AuthenticationManager instances have independent revocation stores."""
        auth1 = AuthenticationManager(secret_key="key1-pytest")
        auth2 = AuthenticationManager(secret_key="key1-pytest")  # same key

        token = auth1.create_access_token("demo")
        auth1.revoke_token(token)

        assert auth1.is_token_revoked(token) is True
        # auth2 has its own store — token not revoked there
        assert auth2.is_token_revoked(token) is False
