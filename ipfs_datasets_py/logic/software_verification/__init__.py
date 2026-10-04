"""Lazy source-verification API with admitted default solver execution.

Explicit imports from the historical pipeline module keep that implementation
unchanged for qualified CodebaseIR producers and replay.
"""
from importlib import import_module

__all__ = [
    "PIPELINE_SCHEMA_VERSION", "PIPELINE_VERSION", "SOURCE_TO_VERIFICATION_PIPELINE_INTERFACE",
    "SOURCE_SEMANTICS_PROFILE", "ContractSpec", "ObligationSolveResult", "PipelineError",
    "PipelineResultBindings", "PipelineStatus", "SourceBinding", "SourceToVerificationPipeline",
    "SourceToVerificationResult", "UnsupportedConstructError", "attach_contract_specs",
    "lower_vc_obligation_to_smt", "run_source_to_verification_pipeline",
    "ProofOperationInterrupted", "ProofOperationTimeout", "ProofOperationCancelled",
]


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module("..backends.smt.operation_budget", __name__) if name in {
        "ProofOperationInterrupted", "ProofOperationTimeout", "ProofOperationCancelled",
    } else import_module(
        ".admitted_pipeline" if name in {
            "SourceToVerificationPipeline", "run_source_to_verification_pipeline",
        } else ".pipeline",
        __name__,
    )
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
