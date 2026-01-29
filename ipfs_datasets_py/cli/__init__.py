"""CLI tools for IPFS Datasets Python.

This package contains multiple optional CLI entrypoints. Some depend on
optional third-party tools or modules; avoid failing package import when a
single optional CLI isn't available.
"""

__all__ = [
    "cached_github_cli",
    "discord_cli",
    "email_cli",
    "finance_cli",
    "github_cli_init",
    "scraper_cli",
]


def _try_star_import(module_name: str) -> None:
    try:
        module = __import__(f"{__name__}.{module_name}", fromlist=["*"])
        globals().update({k: getattr(module, k) for k in getattr(module, "__all__", [])})
    except Exception:
        # Optional CLI modules should not prevent importing this package.
        return


# Best-effort imports for convenience; safe if optional deps are missing.
for _mod in __all__:
    _try_star_import(_mod)
