from dataclasses import dataclass
from functools import cached_property, cache
import math


from ipfs_datasets_py.mcp_server.tools.lizardperson_argparse_programs.municipal_bluebook_citation_validator.types_ import Any, Callable, Logger, Configs


class ExtrapolateToFullDataset:

    _Z_SCORE = 1.96  # Z-score for 95% confidence interval

    def __init__(self, 
                 resources: dict[str, Callable] = None, 
                 configs: Configs = None
                 ) -> None:
        self.resources = resources
        self.configs = configs

        self._logger: Logger = resources['self._logger']

        self._gnis_counts_by_state: dict[str, int] = None

    @cached_property
    def total_estimated_records(self) -> int:
        return sum(self._gnis_counts_by_state.values())

    @cache
    def _get_wilson_score_interval(self, p: float, n: int) -> tuple[float, float]:
        """Calculate the Wilson score interval for a proportion."""
        z_score = self._Z_SCORE
        denominator = 1 + (z_score**2 / n)
        center = (p + (z_score**2) / (2 * n)) / denominator
        margin = (z_score / denominator) * math.sqrt((p * (1 - p) / n) + (z_score**2 / (4 * n**2)))

        return center, margin

    @staticmethod
    def _calculate_finite_population_correction(
        sample_size: int, 
        total_estimated_records: int, 
        center: float, 
        margin: float
        ) -> tuple[float, float, float]:
        """
        Calculate finite population correction (fpc) and adjust confidence intervals.

        Args:
            sample_size: Size of the sample
            total_estimated_records: Total number of records in the population
            center: Center point of the confidence interval
            margin: Margin of error

        Returns:
            Tuple of (fpc, confidence_lower, confidence_upper)
        """
        fpc = 1.0
        confidence_lower = max(0.0, center - margin)
        confidence_upper = min(1.0, center + margin)

        if sample_size / total_estimated_records > 0.05:  # Apply FPC if sample > 5% of population
            fpc = math.sqrt((total_estimated_records - sample_size) / (total_estimated_records - 1))
            confidence_lower = max(0.0, center - (margin * fpc))
            confidence_upper = min(1.0, center + (margin * fpc))
            
        return fpc, confidence_lower, confidence_upper

    @staticmethod
    def _apply_geographic_weighting(gnis_counts_by_state: dict[str, int]) -> float:
        """
        Calculate the coefficient of variation (CV) for geographic distribution of GNIS counts by state. The CV is calculated
        as the ratio of the standard deviation to the mean of state counts (e.g. CV = standard_deviation / mean)

        Args:
            self: The instance of the class (note: this parameter should be removed as this is a static method)
            gnis_counts_by_state (dict[str, int]): Dictionary mapping state names/codes to their
                respective GNIS (Geographic Names Information System) counts.

        Returns:
            float: The coefficient of variation (CV) value. A higher CV indicates greater
                geographic distribution bias, while a lower CV suggests more uniform
                distribution across states. Returns 0 if mean_count is 0.
        """
        # Calculate coefficient of variation to assess geographic distribution bias
        state_counts = list(gnis_counts_by_state.values())
        mean_count = sum(state_counts) / len(state_counts)
        variance = sum((count - mean_count)**2 for count in state_counts) / len(state_counts)
        cv = math.sqrt(variance) / mean_count if mean_count > 0 else 0 # Coefficient of Variation
        return cv

    def extrapolate_to_full_dataset(
        self,
        accuracy_stats, 
        gnis_counts_by_state: dict[str, int], 
        sample_size: int
    ) -> dict[str, float]:
        """
        Extrapolate validation accuracy statistics from a sample to estimate performance on a full dataset.

        This function takes accuracy statistics computed on a sample of data and uses the geographic
        distribution of GNIS (Geographic Names Information System) features by state to estimate
        what the accuracy would be across the complete dataset. This is useful for verifying the 
        accuracy of a validation process when only a sample of the data has been validated.

        Args:
            accuracy_stats (ConfusionMatrix): Confusion matrix containing accuracy metrics from
                the validation sample, including true positives, false positives, true negatives,
                and false negatives.
            gnis_counts_by_state (dict[str, int]): Dictionary mapping state codes/names to the
                number of GNIS features in each state. Used to weight the extrapolation based
                on geographic distribution of data.
            sample_size (int): The number of records that were used to generate the accuracy_stats.
                This is used to calculate confidence intervals and scaling factors.

        Returns:
            dict[str, float]: Dictionary containing extrapolated accuracy metrics for the full
                dataset. Includes:
                - 'estimated_accuracy': Overall accuracy estimate
                - 'confidence_interval_lower': Lower bound of confidence interval
                - 'confidence_interval_upper': Upper bound of confidence interval
                - 'estimated_precision': Precision estimate
                - 'estimated_recall': Recall estimate
                - 'total_estimated_records': Total number of records in full dataset

        Raises:
            ValueError: If sample_size is zero or negative, or if accuracy_stats is empty.
            KeyError: If required fields are missing from the confusion matrix.

        Example:
            >>> confusion_matrix = ConfusionMatrix(tp=85, fp=10, tn=90, fn=15)
            >>> state_counts = {'CA': 50000, 'TX': 45000, 'FL': 30000}
            >>> sample_count = 200
            >>> results = extrapolate_to_full_dataset(confusion_matrix, state_counts, sample_count)
            >>> print(f"Estimated accuracy: {results['estimated_accuracy']:.2%}")
        """
        # Input validation
        if sample_size <= 0:
            raise ValueError("Sample size must be positive")

        if not gnis_counts_by_state: # NOTE This should reset the class attribute between runs as well.
            raise ValueError("GNIS counts by state cannot be empty")
        else:
            self._gnis_counts_by_state = gnis_counts_by_state

        if self.total_estimated_records == 0:
            raise ValueError("Total estimated records cannot be zero")

        # Calculate total records in full dataset
        total_estimated_records = sum(gnis_counts_by_state.values())

        # Get sample statistics from confusion matrix
        sample_accuracy = accuracy_stats.accuracy
        sample_precision = accuracy_stats.precision
        sample_recall = accuracy_stats.recall
        sample_total = accuracy_stats.total_population

        # Validate sample statistics
        if sample_total != sample_size:
            self._logger.warning(f"Sample size mismatch: provided {sample_size}, matrix shows {sample_total}")
            sample_size = sample_total

        # Calculate confidence interval for accuracy using Wilson score interval
        # This is more robust than normal approximation for proportions
        center, margin = self._get_wilson_score_interval(sample_accuracy, sample_size)
        confidence_lower = max(0.0, center - margin)
        confidence_upper = min(1.0, center + margin)

        # Calculate scaling factor based on geographic distribution
        # Weight extrapolation by state distribution to account for potential geographic bias
        total_sample_weight = len(gnis_counts_by_state)  # Assume uniform sampling across states
        scaling_factor = total_estimated_records / sample_size

        cv = self._apply_geographic_weighting(cv, scaling_factor)

        # Adjust confidence interval based on geographic variability
        geographic_adjustment = 1 + (cv * 0.1)  # Small adjustment for geographic bias
        confidence_lower = max(0.0, confidence_lower - (cv * 0.05))
        confidence_upper = min(1.0, confidence_upper + (cv * 0.05))

        # Extrapolate other metrics
        estimated_accuracy = sample_accuracy
        estimated_precision = sample_precision
        estimated_recall = sample_recall

        # Calculate estimated error counts for full dataset
        estimated_total_errors = int(total_estimated_records * (1 - sample_accuracy))
        estimated_valid_citations = int(total_estimated_records * sample_accuracy)

        # Calculate finite population correction if sample is large relative to population
        fpc, confidence_lower, confidence_upper = self._calculate_finite_population_correction(
            sample_size, total_estimated_records, center, margin
        )

        @dataclass
        class CoreEstimates:
            """Data class containing core performance estimates for model evaluation.

            Attributes:
                estimated_accuracy (float): The estimated accuracy as a decimal value (0.0 to 1.0).
                estimated_accuracy_percent (float): The estimated accuracy as a percentage (0.0 to 100.0).
                estimated_precision (float): The estimated precision score (0.0 to 1.0).
                estimated_recall (float): The estimated recall score (0.0 to 1.0).
                estimated_f1_score (float): The estimated F1 score, harmonic mean of precision and recall (0.0 to 1.0).
            """
            estimated_accuracy: float
            estimated_accuracy_percent: float
            estimated_precision: float
            estimated_recall: float
            estimated_f1_score: float

        @dataclass
        class ConfidenceIntervals:
            """Data class representing statistical confidence intervals and margin of error calculations.

            Attributes:
                confidence_interval_lower (float): Lower bound of the confidence interval
                confidence_interval_upper (float): Upper bound of the confidence interval
                confidence_interval_lower_percent (float): Lower bound as a percentage
                confidence_interval_upper_percent (float): Upper bound as a percentage
                confidence_level (float): The confidence level used (e.g., 0.95 for 95%)
                margin_of_error (float): Absolute margin of error value
                margin_of_error_percent (float): Margin of error as a percentage
            """
            confidence_interval_lower: float
            confidence_interval_upper: float
            confidence_interval_lower_percent: float
            confidence_interval_upper_percent: float
            confidence_level: float
            margin_of_error: float
            margin_of_error_percent: float

        @dataclass
        class DatasetEstimates:
            """A dataclass containing statistical estimates for extrapolating sample results to a full dataset.

            Attributes:
                total_estimated_records (float): The estimated total number of records in the full dataset
                sample_size (float): The actual number of records in the sample used for analysis
                scaling_factor (float): The multiplier used to scale sample results to full dataset estimates
                sampling_ratio (float): The ratio of sample size to total estimated records (sample_size / total_estimated_records)
            """
            total_estimated_records: float
            sample_size: float
            scaling_factor: float
            sampling_ratio: float

        @dataclass
        class ErrorEstimates:
            """Data class for storing error rate estimates and projections for the full dataset.

            Attributes:
                estimated_total_errors (float): Projected total number of errors in the complete dataset
                estimated_valid_citations (float): Projected number of valid citations in the complete dataset
                estimated_error_rate (float): Estimated error rate as a decimal (0.0 to 1.0)
                estimated_error_rate_percent (float): Estimated error rate as a percentage (0.0 to 100.0)
            """
            estimated_total_errors: float
            estimated_valid_citations: float
            estimated_error_rate: float
            estimated_error_rate_percent: float

        @dataclass
        class GeographicMetrics:
            """Dataclass representing geographic metrics for statistical analysis.

            This class encapsulates key geographic statistical measures used for
            analyzing spatial data distributions and applying geographic corrections
            to statistical calculations.

            Attributes:
                geographic_coefficient_variation (float): The coefficient of variation
                    across geographic regions, measuring relative variability in the data.
                geographic_adjustment_factor (float): A factor used to adjust statistical
                    estimates based on geographic characteristics or biases.
                finite_population_correction (float): Correction factor applied when
                    sampling from a finite population to adjust variance estimates.
                number_of_states (int): The total number of states or geographic units
                    included in the analysis.
            """
            geographic_coefficient_variation: float
            geographic_adjustment_factor: float
            finite_population_correction: float
            number_of_states: int

        @dataclass
        class QualityMetrics:
            """
            A data class that holds quality metrics for dataset extrapolation analysis.

            Attributes:
                extrapolation_reliability (str): A string indicating the reliability level 
                    of extrapolating sample results to the full dataset. Typically contains
                    values like 'high', 'medium', 'low' or descriptive reliability assessments.
            """
            extrapolation_reliability: str

        @dataclass
        class Results:
            """Data class containing comprehensive results from municipal bluebook citation validation analysis.

            This class aggregates all analytical results including statistical estimates,
            confidence intervals, dataset-wide projections, error analysis, geographic
            distribution metrics, and quality assessment metrics.

            Attributes:
                core_estimates (CoreEstimates): Primary statistical estimates and core metrics
                confidence_intervals (ConfidenceIntervals): Statistical confidence intervals for estimates
                dataset_estimates (DatasetEstimates): Extrapolated estimates for the full dataset
                error_estimates (ErrorEstimates): Error analysis and uncertainty quantification
                geographic_metrics (GeographicMetrics): Geographic distribution and spatial analysis metrics
                quality_metrics (QualityMetrics): Data quality assessment and validation metrics
            """
            core_estimates: CoreEstimates
            confidence_intervals: ConfidenceIntervals
            dataset_estimates: DatasetEstimates
            error_estimates: ErrorEstimates
            geographic_metrics: GeographicMetrics
            quality_metrics: QualityMetrics

        results = Results(
            core_estimates=CoreEstimates(
                estimated_accuracy=estimated_accuracy,
                estimated_accuracy_percent=estimated_accuracy * 100,
                estimated_precision=estimated_precision,
                estimated_recall=estimated_recall,
                estimated_f1_score=accuracy_stats.f1_score
            ),
            confidence_intervals=ConfidenceIntervals(
                confidence_interval_lower=confidence_lower,
                confidence_interval_upper=confidence_upper,
                confidence_interval_lower_percent=confidence_lower * 100,
                confidence_interval_upper_percent=confidence_upper * 100,
                confidence_level=95.0,
                margin_of_error=margin,
                margin_of_error_percent=margin * 100
            ),
            dataset_estimates=DatasetEstimates(
                total_estimated_records=float(total_estimated_records),
                sample_size=float(sample_size),
                scaling_factor=scaling_factor,
                sampling_ratio=sample_size / total_estimated_records
            ),
            error_estimates=ErrorEstimates(
                estimated_total_errors=float(estimated_total_errors),
                estimated_valid_citations=float(estimated_valid_citations),
                estimated_error_rate=1 - estimated_accuracy,
                estimated_error_rate_percent=(1 - estimated_accuracy) * 100
            ),
            geographic_metrics=GeographicMetrics(
                geographic_coefficient_variation=cv,
                geographic_adjustment_factor=geographic_adjustment,
                finite_population_correction=fpc,
                number_of_states=len(gnis_counts_by_state)
            ),
            quality_metrics=QualityMetrics(
                extrapolation_reliability='high' if sample_size >= 385 else 'medium' if sample_size >= 100 else 'low'
            )
        )

        self._logger.info(f"Extrapolated accuracy: {estimated_accuracy:.3f} "
                f"(95% CI: {confidence_lower:.3f}-{confidence_upper:.3f}) "
                f"for {total_estimated_records:,} total records")

        return results
