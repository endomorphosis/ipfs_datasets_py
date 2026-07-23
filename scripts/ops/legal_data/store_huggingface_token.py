#!/usr/bin/env python3
"""Store a Hugging Face token in a usable secret backend.

This helper prefers a responsive system keyring when available, but falls back
to Hugging Face's managed local token store in headless environments where the
desktop secret service cannot be unlocked noninteractively.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, Optional


def _store_with_keyring(
    *,
    token: str,
    service: str,
    account: str,
    timeout_seconds: float,
) -> Dict[str, Any]:
    probe = (
        "import json, keyring; "
        "backend = keyring.get_keyring(); "
        "keyring.set_password(%r, %r, %r); "
        "stored = keyring.get_password(%r, %r); "
        "print(json.dumps({'ok': stored == %r, 'backend': backend.__class__.__module__ + '.' + backend.__class__.__name__}))"
        % (service, account, token, service, account, token)
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "backend": "timeout",
            "error": f"system keyring did not respond within {timeout_seconds:.1f}s",
        }
    except Exception as exc:
        return {
            "ok": False,
            "backend": "error",
            "error": str(exc),
        }

    stdout = str(completed.stdout or "").strip()
    stderr = str(completed.stderr or "").strip()
    if completed.returncode != 0:
        return {
            "ok": False,
            "backend": "error",
            "error": stderr or f"keyring subprocess exited with code {completed.returncode}",
        }
    try:
        payload = json.loads(stdout)
        return {
            "ok": bool(payload.get("ok")),
            "backend": str(payload.get("backend") or ""),
        }
    except Exception:
        return {
            "ok": False,
            "backend": "error",
            "error": stdout or stderr or "failed to parse keyring response",
        }


def _chmod_private(path_str: str) -> Optional[str]:
    path = Path(path_str)
    if not path.exists():
        return None
    try:
        path.chmod(0o600)
    except Exception:
        return None
    return str(path)


def _store_with_hf_local(*, token: str) -> Dict[str, Any]:
    from huggingface_hub import HfFolder, login

    login(token=token, add_to_git_credential=False, new_session=True)

    token_value = HfFolder.get_token()
    token_path = _chmod_private(str(Path.home() / ".cache" / "huggingface" / "token"))
    stored_tokens_path = _chmod_private(str(Path.home() / ".cache" / "huggingface" / "stored_tokens"))

    return {
        "ok": bool(token_value == token),
        "backend": "huggingface_local_store",
        "token_path": token_path,
        "stored_tokens_path": stored_tokens_path,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Store a Hugging Face token in keyring or HF local store.")
    parser.add_argument("--token", help="Hugging Face token. Defaults to HF_TOKEN env var, then interactive prompt.")
    parser.add_argument(
        "--backend",
        choices=["auto", "keyring", "hf-local"],
        default="auto",
        help="Secret backend to use. 'auto' tries keyring first, then falls back to Hugging Face local storage.",
    )
    parser.add_argument(
        "--service",
        default="huggingface_hub",
        help="Service name to use for keyring storage.",
    )
    parser.add_argument(
        "--account",
        default="default",
        help="Account/username label to use for keyring storage.",
    )
    parser.add_argument(
        "--keyring-timeout-seconds",
        type=float,
        default=2.0,
        help="Maximum time to wait for a system keyring round-trip before falling back.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    token = str(args.token or os.getenv("HF_TOKEN") or "").strip()
    if not token:
        token = getpass.getpass("Hugging Face token: ").strip()
    if not token:
        raise SystemExit("No Hugging Face token provided.")

    attempts = []
    result: Optional[Dict[str, Any]] = None

    if args.backend in {"auto", "keyring"}:
        try:
            keyring_result = _store_with_keyring(
                token=token,
                service=str(args.service),
                account=str(args.account),
                timeout_seconds=float(args.keyring_timeout_seconds),
            )
        except Exception as exc:
            keyring_result = {"ok": False, "backend": "error", "error": str(exc)}
        attempts.append({"backend": "keyring", **keyring_result})
        if keyring_result.get("ok"):
            result = {
                "status": "success",
                "backend": "keyring",
                "service": str(args.service),
                "account": str(args.account),
                "keyring_backend": keyring_result.get("backend"),
                "attempts": attempts,
            }

    if result is None and args.backend in {"auto", "hf-local"}:
        hf_result = _store_with_hf_local(token=token)
        attempts.append({"backend": "hf-local", **hf_result})
        if hf_result.get("ok"):
            result = {
                "status": "success",
                "backend": "hf-local",
                "token_path": hf_result.get("token_path"),
                "stored_tokens_path": hf_result.get("stored_tokens_path"),
                "attempts": attempts,
            }

    if result is None:
        result = {
            "status": "error",
            "backend": args.backend,
            "attempts": attempts,
        }

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"status: {result['status']}")
        print(f"backend: {result.get('backend', '')}")
        if result.get("keyring_backend"):
            print(f"keyring_backend: {result['keyring_backend']}")
        if result.get("service"):
            print(f"service: {result['service']}")
        if result.get("account"):
            print(f"account: {result['account']}")
        if result.get("token_path"):
            print(f"token_path: {result['token_path']}")
        if result.get("stored_tokens_path"):
            print(f"stored_tokens_path: {result['stored_tokens_path']}")
        if result.get("attempts"):
            print("attempts:")
            for attempt in result["attempts"]:
                backend = attempt.get("backend", "")
                ok = attempt.get("ok", False)
                detail = attempt.get("error", "") or attempt.get("backend", "")
                print(f"  - {backend}: {'ok' if ok else 'failed'} {detail}".rstrip())

    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
