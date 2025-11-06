from typing import Callable, Dict, Any
import logging

from ._analyze_error_patterns import analyze_error_patterns
from ._calculate_accuracy_statistics import calculate_accuracy_statistics
from ._extrapolate_to_full_dataset import ExtrapolateToFullDataset
from ._results_analyzer import ResultsAnalyzer

from ..configs import configs

logger = logging.getLogger(__name__)

def _make_extrapolate_to_full_dataset() -> Callable:
    resources = {"logger": logger}
    return ExtrapolateToFullDataset(resources=resources, configs=configs).extrapolate_to_full_dataset


def make_results_analyzer() -> ResultsAnalyzer:
    resources = {
        'analyze_error_patterns': analyze_error_patterns,
        'calculate_accuracy_statistics': calculate_accuracy_statistics,  # Placeholder for actual function
        'extrapolate_to_full_dataset': _make_extrapolate_to_full_dataset(),  # Placeholder for actual function
        'load_citations_for_place': None,  # Placeholder for actual function
        'load_documents_for_place': None,  # Placeholder for actual function
    }

    return ResultsAnalyzer(resources=resources, configs=configs)