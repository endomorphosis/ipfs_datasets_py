"""Public CVC5 adapters with shared admission enabled for native execution.

The explicit ``cvc5.compiler`` module remains the frozen compatibility surface.
Importing that submodule does not load these new adapters or change its classes.
"""
from importlib import import_module

__all__ = [
    "SMT_ENCODINGS", "CVC5_BACKEND_ID", "CVC5_BACKEND_VERSION", "CVC5_CAPABILITIES",
    "CVC5_SOFTWARE_VERIFICATION_INTERFACE", "CVC5_SOFTWARE_VERIFICATION_VERSION",
    "CVC5_SV_BACKEND_ID", "CVC5_SV_BACKEND_INTERFACE", "CVC5_SV_BACKEND_VERSION",
    "CVC5Backend", "CVC5Compiler", "CVC5SoftwareVerificationBackend", "compile_request",
]


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module("..smt.admitted", __name__) if name in {
        "CVC5Backend", "CVC5SoftwareVerificationBackend",
    } else import_module(".compiler", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
