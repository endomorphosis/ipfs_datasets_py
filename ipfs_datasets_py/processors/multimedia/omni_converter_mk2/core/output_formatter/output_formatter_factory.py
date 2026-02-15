"""
Factory module for creating OutputFormatter instances.

This module provides the factory function for creating OutputFormatter instances
following the IoC pattern.
"""
from configs import configs
from logger import logger
from ._output_formatter import OutputFormatter
from ._formatted_output import FormattedOutput
from core.text_normalizer._normalized_content import NormalizedContent


def make_output_formatter() -> 'OutputFormatter':
    """
    Factory function to create an OutputFormatter instance.
    
    Returns:
        An instance of OutputFormatter configured with proper dependencies.
    """
    resources = {
        "normalized_content": NormalizedContent,
        "formatted_output": FormattedOutput,
        "logger": logger,
    }
    return OutputFormatter(resources=resources, configs=configs)