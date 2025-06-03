from pathlib import Path
from typing import Any, Callable


from types_ import DatabaseConnection, Configs

class ResultsAnalyzer:

        def __init__(self, resources: dict[str, Callable]=None, configs: Configs = None) -> None:
            self.resources = resources
            self.configs = configs

            self._analyze_error_patterns = resources['analyze_error_patterns']
            self._calculate_accuracy_statistics = resources['calculate_accuracy_statistics']
            self._extrapolate_to_full_dataset = resources['extrapolate_to_full_dataset']


        def analyze(self, error_db: DatabaseConnection, total_citations: int, total_errors: int):
            print("Generating analysis and reports...")
            error_summary: dict[str, Any] = self._analyze_error_patterns(error_db)
            accuracy_stats: dict[str, float] = self._calculate_accuracy_statistics (total_citations, total_errors)
            extrapolated_results: dict[str, float] = self._extrapolate_to_full_dataset()

            accuracy_stats, gnis_counts_by_state, len(gnis_for_sampled_places)
