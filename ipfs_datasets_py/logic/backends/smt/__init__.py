"""Lazy public SMT composition with admitted native differential defaults.

Importing explicit compiler or differential submodules remains inert and keeps
their historical implementations intact. The legacy raw subprocess helper is
available only from the explicit differential compatibility module.
"""
from importlib import import_module

__all__ = [
    "AvailabilityProbe", "CVC5_SV_BACKEND_ID", "CVC5_SV_BACKEND_INTERFACE",
    "CVC5_SV_BACKEND_VERSION", "DifferentialClassification", "MalformedSmtSolverOutput",
    "SMT_DIFFERENTIAL_INTERFACE", "SMT_DIFFERENTIAL_SCHEMA_VERSION",
    "SMT_SOFTWARE_VERIFICATION_OUTCOME_VERSION", "SOFTWARE_VERIFICATION_SMT_BACKEND_VERSION",
    "SmtDifferentialError", "SmtDifferentialReport", "SmtDifferentialVerifier",
    "SmtRawSolverOutput", "SmtSoftwareVerificationOutcome", "SmtSolverRunner",
    "SmtSolverVerdict", "SoftwareVerificationSmtBackend", "SoftwareVerificationSmtOutcome",
    "VersionProbe", "Z3_SV_BACKEND_ID", "Z3_SV_BACKEND_INTERFACE", "Z3_SV_BACKEND_VERSION",
    "classify_differential", "compile_obligation", "default_z3_cvc5_verifier",
    "normalize_smtlib_for_solver", "parse_smt_solver_stdout", "run_z3_cvc5_differential",
    "ProofOperationInterrupted", "ProofOperationTimeout", "ProofOperationCancelled",
]


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(".operation_budget", __name__) if name in {
        "ProofOperationInterrupted", "ProofOperationTimeout", "ProofOperationCancelled",
    } else import_module(
        ".admitted_differential" if name in {
            "default_z3_cvc5_verifier", "run_z3_cvc5_differential",
        } else ".differential",
        __name__,
    )
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
