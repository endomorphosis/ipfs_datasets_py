"""
Machine learning domain processors for classification and analysis tasks.
"""

# Try to import ML modules, make them optional for missing dependencies
try:
    from .classify_with_llm import *
except ImportError as e:
    import warnings
    warnings.warn(f"LLM classifier unavailable due to missing dependencies: {e}")

__all__ = ['ClassifyWithLLM', 'LLMClassifier']
