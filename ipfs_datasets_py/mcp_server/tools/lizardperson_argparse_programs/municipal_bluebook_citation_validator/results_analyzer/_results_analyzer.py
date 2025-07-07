from pathlib import Path
from typing import Any, Callable


from ipfs_datasets_py.mcp_server.tools.lizardperson_argparse_programs.municipal_bluebook_citation_validator.types_ import DatabaseConnection, Configs

class ResultsAnalyzer:

        def __init__(self, resources: dict[str, Callable]=None, configs: Configs = None) -> None:
            self.resources = resources
            self.configs = configs

            self._sample_size = configs.sample_size

            self._analyze_error_patterns = resources['analyze_error_patterns']
            self._calculate_accuracy_statistics = resources['calculate_accuracy_statistics']
            self._extrapolate_to_full_dataset = resources['extrapolate_to_full_dataset']

        def analyze(self, 
                    error_db: DatabaseConnection, 
                    gnis_counts_by_state: dict[str, int],
                    total_citations: int, 
                    total_errors: int
                    ) -> tuple[dict[str, Any], dict[str, float], dict[str, float]]:
            print("Generating analysis and reports...")
            error_summary: dict[str, Any] = self._analyze_error_patterns(error_db)
            print("Generated error summary. Analyzing error patterns...")
            accuracy_stats: dict[str, float] = self._calculate_accuracy_statistics (total_citations, total_errors)
            print("Analyzed error patterns. Extrapolating results to full dataset...")
            extrapolated_results: dict[str, float] = self._extrapolate_to_full_dataset(accuracy_stats, gnis_counts_by_state)
            print("Extrapolated results to full dataset.")

            error_summary, accuracy_stats, extrapolated_results
