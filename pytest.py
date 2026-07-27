"""Bootstrap real pytest when hermetic validation clobbers site-packages.

The agent-supervisor validation runtime puts approved site-packages on
``PYTHONPATH`` and sets ``PYTHONNOUSERSITE=1``.  Declared task commands that
assign ``PYTHONPATH=.`` replace that path, so ``python -m pytest`` cannot
import the operator's user-site pytest.

This shim lives at the repository root so ``PYTHONPATH=.`` still finds a
``pytest`` module.  It re-attaches the account user site-packages (via
``pwd``, not the validation child's temporary ``HOME``) and delegates to the
real pytest distribution for both ``python -m pytest`` and ``import pytest``.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


def _account_user_site() -> Path | None:
    """Locate the durable user site-packages, ignoring temporary HOME."""
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates: list[Path] = []
    try:
        import pwd

        uid = os.getuid()
        # Match validation_runtime uid_map handling for unshare -Ur.
        try:
            uid_map = Path("/proc/self/uid_map").read_text(encoding="utf-8")
        except OSError:
            uid_map = ""
        for line in uid_map.splitlines():
            fields = line.split()
            if len(fields) != 3:
                continue
            try:
                inside_start, outside_start, length = (int(f) for f in fields)
            except ValueError:
                continue
            if inside_start <= uid < inside_start + length:
                uid = outside_start + (uid - inside_start)
                break
        account_home = Path(pwd.getpwuid(uid).pw_dir)
        candidates.append(
            account_home / ".local" / "lib" / version / "site-packages"
        )
    except (ImportError, KeyError, OSError):
        pass

    env_home = os.environ.get("HOME")
    if env_home:
        candidates.append(
            Path(env_home) / ".local" / "lib" / version / "site-packages"
        )

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if (resolved / "pytest").is_dir() or (resolved / "pytest.py").is_file():
            return resolved
    return None


def _bootstrap_real_pytest():
    user_site = _account_user_site()
    if user_site is None:
        raise ImportError(
            "pytest shim could not locate user site-packages containing pytest"
        )
    user_site_s = str(user_site)
    # Prefer the real distribution over this shim module.
    while user_site_s in sys.path:
        sys.path.remove(user_site_s)
    sys.path.insert(0, user_site_s)

    shim_file = Path(__file__).resolve()
    for key in list(sys.modules):
        if key != "pytest" and not key.startswith("pytest."):
            continue
        mod = sys.modules.get(key)
        mod_file = getattr(mod, "__file__", None)
        if not mod_file:
            continue
        try:
            if Path(mod_file).resolve() == shim_file:
                del sys.modules[key]
        except OSError:
            sys.modules.pop(key, None)

    # With user site first, the real pytest package wins over this .py file.
    real = importlib.import_module("pytest")
    real_file = getattr(real, "__file__", None) or ""
    try:
        if Path(real_file).resolve() == shim_file:
            raise ImportError(
                "pytest shim failed to load the real pytest package"
            )
    except OSError as exc:
        raise ImportError(
            "pytest shim failed to resolve real pytest location"
        ) from exc
    return real


_real = _bootstrap_real_pytest()

# Ensure both the import name and -m entry point use the real distribution.
sys.modules["pytest"] = _real

if __name__ == "__main__":
    raise SystemExit(_real.console_main())
else:
    # Re-export public API for any binding that kept the shim module object.
    globals().update(
        {
            name: getattr(_real, name)
            for name in dir(_real)
            if name != "__file__"
        }
    )
