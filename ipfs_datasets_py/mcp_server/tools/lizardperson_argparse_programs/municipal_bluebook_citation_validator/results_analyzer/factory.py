

from ._analyze_error_patterns import analyze_error_patterns
from ._results_analyzer import ResultsAnalyzer

from configs import configs

def make_results_analyzer():
    resources = {
        'analyze_error_patterns': analyze_error_patterns,
        'calculate_accuracy_statistics': None,  # Placeholder for actual function
        'extrapolate_to_full_dataset': None,  # Placeholder for actual function
        'load_citations_for_place': None,  # Placeholder for actual function
        'load_documents_for_place': None,  # Placeholder for actual function
    }

    return ResultsAnalyzer(resources=resources, configs=configs)