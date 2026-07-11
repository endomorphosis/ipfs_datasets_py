"""Model extraction helpers for exchange security verification."""

from typing import TYPE_CHECKING

from .feature_loop import SecurityIRFeatureLoopProjector
from .log_trace_extractor import LogTraceExtractor
from .openapi_extractor import OpenAPIExtractor
from .python_ast_extractor import PythonASTExtractor
from .source_code_extractor import SourceCodeExtractor
from .typescript_schema import TypeScriptSchemaEmitter
from .ucan_policy_extractor import UCANPolicyExtractor
from .xaman_source_extractor import XamanSourceExtractor

if TYPE_CHECKING:
    from .xaman_runtime_trace_ingestor import XamanRuntimeTraceIngestor

__all__ = [
    'SecurityIRFeatureLoopProjector',
    'LogTraceExtractor',
    'OpenAPIExtractor',
    'PythonASTExtractor',
    'SourceCodeExtractor',
    'TypeScriptSchemaEmitter',
    'UCANPolicyExtractor',
    'XamanRuntimeTraceIngestor',
    'XamanSourceExtractor',
]


def __getattr__(name: str):
    if name == 'XamanRuntimeTraceIngestor':
        from .xaman_runtime_trace_ingestor import XamanRuntimeTraceIngestor

        return XamanRuntimeTraceIngestor
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
