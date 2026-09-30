"""Two explicit model profiles, importable together without global aliases.

``legacy_v1`` preserves the ddf6b794 numerical implementation and eight-wide
checkpoint profile. ``current_v2`` uses today's implementation and a 384-wide
profile. Width is a runtime contract, not evidence of semantic qualification.
"""

from importlib import import_module

__all__ = ["legacy_v1", "current_v2"]


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(name)
    module = import_module(f"{__name__}.{name}")
    globals()[name] = module
    return module
