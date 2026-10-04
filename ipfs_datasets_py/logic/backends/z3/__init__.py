"""Public Z3 adapters with shared admission enabled for native execution.

The explicit ``z3.compiler`` module remains the frozen compatibility surface.
Importing that submodule does not load these new adapters or change its classes.
"""
from importlib import import_module

__all__ = [
    "SMT_ENCODINGS", "Z3_BACKEND_ID", "Z3_BACKEND_VERSION", "Z3_CAPABILITIES",
    "Z3_SOFTWARE_VERIFICATION_INTERFACE", "Z3_SOFTWARE_VERIFICATION_VERSION",
    "Z3_SV_BACKEND_ID", "Z3_SV_BACKEND_INTERFACE", "Z3_SV_BACKEND_VERSION",
    "Z3Backend", "Z3Compiler", "Z3SoftwareVerificationBackend", "compile_request",
]


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module("..smt.admitted", __name__) if name in {
        "Z3Backend", "Z3SoftwareVerificationBackend",
    } else import_module(".compiler", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
