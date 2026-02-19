"""Dashboard Tools Module for MCP Server."""

from .js_error_reporter import JavaScriptErrorReporter, get_js_error_reporter

# TDFOL performance dashboard tools
try:
    from . import tdfol_performance_tool
    __all__ = [
        'JavaScriptErrorReporter',
        'get_js_error_reporter',
        'tdfol_performance_tool'
    ]
except ImportError:
    __all__ = ['JavaScriptErrorReporter', 'get_js_error_reporter']
