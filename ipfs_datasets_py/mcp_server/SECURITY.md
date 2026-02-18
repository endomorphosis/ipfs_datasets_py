# MCP Server Security Guide

**Last Updated:** 2026-02-18  
**Status:** Phase 1 Security Fixes In Progress

---

## Required Environment Variables

### SECRET_KEY (CRITICAL)

**Required for:** JWT token signing, session security  
**Status:** 🔴 REQUIRED - Server will not start without this

```bash
# Generate a strong random secret key
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

# Or set it manually (minimum 32 characters recommended)
export SECRET_KEY="your-very-strong-secret-key-at-least-32-chars"
```

**Why this is critical:**
- Without a SECRET_KEY, JWT tokens can be forged
- Session hijacking is possible
- Production deployment is insecure

**Changes made (2026-02-18):**
- ✅ Removed hardcoded default "your-secret-key-change-in-production"
- ✅ Server now fails fast if SECRET_KEY not set
- ✅ Clear error message guides users to set the variable

**Files updated:**
- `fastapi_config.py:35` - Removed default value
- `fastapi_service.py:95` - Added validation with helpful error message

---

## Security Fixes Applied

### S1: Hardcoded Secrets ✅ FIXED (2026-02-18)

**Issue:** Hardcoded SECRET_KEY in 2 files allowed JWT token forgery  
**Severity:** 🔴 CRITICAL  
**Status:** ✅ Fixed

**Before:**
```python
secret_key: str = Field(default="your-secret-key-change-in-production", env="SECRET_KEY")
```

**After:**
```python
secret_key: str = Field(env="SECRET_KEY")  # No default - MUST be set
```

### S3: Hallucinated Library Import ✅ FIXED (2026-02-18)

**Issue:** Import of non-existent `mcp.client` library caused startup crashes  
**Severity:** 🔴 CRITICAL  
**Status:** ✅ Fixed

**Before:**
```python
from mcp.client import MCPClient  # This library doesn't exist!
```

**After:**
```python
# Disabled until proper MCP client library is available
logger.warning("ipfs_kit MCP proxy registration is currently disabled...")
```

---

## Security Issues Remaining

### S2: Bare Exception Handlers 🔴 TODO

**Issue:** 14+ files with bare `except:` clauses masking failures  
**Severity:** 🔴 CRITICAL  
**Status:** ⏳ In Progress

**Affected Files:**
- `tools/email_tools/email_analyze.py`
- `tools/discord_tools/discord_analyze.py`
- `tools/media_tools/ffmpeg_edit.py`
- ... (11+ more)

**Example Fix:**
```python
# BAD - catches everything
try:
    risky_operation()
except:
    return None

# GOOD - specific exceptions
try:
    risky_operation()
except (ValueError, KeyError) as e:
    logger.error(f"Operation failed: {e}", exc_info=True)
    raise ToolExecutionError(f"Failed: {e}") from e
```

### S4: Unsafe Subprocess Calls 🔴 TODO

**Issue:** Command injection vulnerability in CLI tool wrappers  
**Severity:** 🔴 CRITICAL  
**Status:** ⏳ Planned

**Affected Files:**
- `tools/lizardpersons_function_tools/meta_tools/use_cli_program_as_tool.py`
- `tools/development_tools/linting_tools.py`

**Required Fix:**
```python
# BAD - shell=True allows injection
subprocess.run(user_input, shell=True)

# GOOD - sanitized and safe
import shlex
subprocess.run(shlex.split(user_input), shell=False, timeout=30)
```

### S5: Error Data Exposure 🟡 TODO

**Issue:** Sensitive data leaked in error reports  
**Severity:** 🟡 HIGH  
**Status:** ⏳ Planned

**Location:** `server.py:629-633`

**Required Fix:**
```python
# Sanitize kwargs before reporting
safe_context = {
    "tool": tool_name,
    "kwargs_keys": list(kwargs.keys())  # Only key names, not values
}
```

---

## Security Testing

### Manual Verification

1. **Test SECRET_KEY requirement:**
```bash
# Should fail
python -m ipfs_datasets_py.mcp_server

# Should work
export SECRET_KEY="test-key-at-least-32-characters-long"
python -m ipfs_datasets_py.mcp_server
```

2. **Test server startup:**
```bash
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
python ipfs_datasets_py/mcp_server/server.py
# Should start without ImportError
```

### Automated Testing (TODO)

Create `tests/mcp/test_security.py`:
- Test SECRET_KEY requirement
- Test exception handling
- Test subprocess sanitization
- Test error report sanitization
- Test for command injection vulnerabilities

### Security Scanning

Run Bandit security scanner:
```bash
pip install bandit
bandit -r ipfs_datasets_py/mcp_server/ -f json -o security_report.json
```

**Target:** 0 HIGH/CRITICAL issues

---

## Production Deployment Checklist

Before deploying to production, ensure:

- [x] SECRET_KEY set via environment variable (minimum 32 characters)
- [ ] All bare exception handlers fixed (S2)
- [ ] Subprocess calls sanitized (S4)
- [ ] Error reporting sanitized (S5)
- [ ] Security test suite passing
- [ ] Bandit scan: 0 HIGH/CRITICAL issues
- [ ] Manual security review complete

**CRITICAL:** Do not deploy to production until all items are checked.

---

## Security Contacts

**Report security vulnerabilities:**
- Open a private security advisory on GitHub
- Email: [security contact if available]
- Tag: `security`, `vulnerability`

**Response Time:**
- Critical vulnerabilities: 24-48 hours
- High severity: 1 week
- Medium/Low: Next release cycle

---

## References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [Bandit Security Scanner](https://bandit.readthedocs.io/)

---

**Document Status:** In Progress  
**Last Security Audit:** 2026-02-18  
**Next Audit:** After Phase 1 complete
