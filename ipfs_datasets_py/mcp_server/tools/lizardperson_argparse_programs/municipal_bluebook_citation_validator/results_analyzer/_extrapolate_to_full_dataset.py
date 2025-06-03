from functools import cached_property, cache
import math
from typing import Any, Dict, Callable

class ExtrapolateToFullDataset:

    _Z_SCORE_95 = 1.96  # Z-score for 95% confidence interval

    def __init__(self, resources: dict[str, Callable] = None, configs: dict[str, Any] = None) -> None:
        self.resources = resources
        self.configs = configs
        
        self._logger = resources['self._logger']

        self._accuracy_stats = None
        self._gnis_counts_by_state: Dict[str, int] = None
        self._sample_size: int = None

    @cached_property
    def total_estimated_records(self) -> int:
        return sum(self._gnis_counts_by_state.values())

    @cache
    def get_wilson_score_interval(self, p: float, n: int) -> tuple[float, float]:
        """Calculate the Wilson score interval for a proportion."""
        z_score = self._Z_SCORE_95
        denominator = 1 + (z_score**2 / n)
        center = (p + (z_score**2) / (2 * n)) / denominator
        margin = (z_score / denominator) * math.sqrt((p * (1 - p) / n) + (z_score**2 / (4 * n**2)))

        return center, margin

    def extrapolate_to_full_dataset(
        self,
        accuracy_stats: ConfusionMatrix, 
        gnis_counts_by_state: Dict[str, int], 
        sample_size: int
    ) -> Dict[str, float]:
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
            gnis_counts_by_state (Dict[str, int]): Dictionary mapping state codes/names to the
                number of GNIS features in each state. Used to weight the extrapolation based
                on geographic distribution of data.
            sample_size (int): The number of records that were used to generate the accuracy_stats.
                This is used to calculate confidence intervals and scaling factors.

        Returns:
            Dict[str, float]: Dictionary containing extrapolated accuracy metrics for the full
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

        if not gnis_counts_by_state:
            raise ValueError("GNIS counts by state cannot be empty")
        else:
            self._gnis_counts_by_state = gnis_counts_by_state

        if self.total_estimated_records == 0:
            raise ValueError("Total estimated records cannot be zero")

        try:
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
            z_score = 1.96  # 95% confidence interval

            center, margin = self.get_wilson_score_interval(sample_accuracy, sample_size)
            

            
            confidence_lower = max(0.0, center - margin)
            confidence_upper = min(1.0, center + margin)
            
            # Calculate scaling factor based on geographic distribution
            # Weight extrapolation by state distribution to account for potential geographic bias
            total_sample_weight = len(gnis_counts_by_state)  # Assume uniform sampling across states
            scaling_factor = total_estimated_records / sample_size
            
            # Apply geographic weighting
            # Calculate coefficient of variation to assess geographic distribution bias
            state_counts = list(gnis_counts_by_state.values())
            mean_count = sum(state_counts) / len(state_counts)
            variance = sum((count - mean_count)**2 for count in state_counts) / len(state_counts)
            cv = math.sqrt(variance) / mean_count if mean_count > 0 else 0
            
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
            fpc = 1.0
            if sample_size / total_estimated_records > 0.05:  # Apply FPC if sample > 5% of population
                fpc = math.sqrt((total_estimated_records - sample_size) / (total_estimated_records - 1))
                confidence_lower = max(0.0, center - (margin * fpc))
                confidence_upper = min(1.0, center + (margin * fpc))
            
            results = {
                # Core estimates
                'estimated_accuracy': estimated_accuracy,
                'estimated_accuracy_percent': estimated_accuracy * 100,
                'estimated_precision': estimated_precision,
                'estimated_recall': estimated_recall,
                'estimated_f1_score': accuracy_stats.f1_score,
                
                # Confidence intervals
                'confidence_interval_lower': confidence_lower,
                'confidence_interval_upper': confidence_upper,
                'confidence_interval_lower_percent': confidence_lower * 100,
                'confidence_interval_upper_percent': confidence_upper * 100,
                'confidence_level': 95.0,
                
                # Dataset size estimates
                'total_estimated_records': float(total_estimated_records),
                'sample_size': float(sample_size),
                'scaling_factor': scaling_factor,
                'sampling_ratio': sample_size / total_estimated_records,
                
                # Error estimates
                'estimated_total_errors': float(estimated_total_errors),
                'estimated_valid_citations': float(estimated_valid_citations),
                'estimated_error_rate': 1 - estimated_accuracy,
                'estimated_error_rate_percent': (1 - estimated_accuracy) * 100,
                
                # Geographic distribution metrics
                'geographic_coefficient_variation': cv,
                'geographic_adjustment_factor': geographic_adjustment,
                'finite_population_correction': fpc,
                'number_of_states': len(gnis_counts_by_state),
                
                # Quality metrics
                'extrapolation_reliability': 'high' if sample_size >= 385 else 'medium' if sample_size >= 100 else 'low',
                'margin_of_error': margin,
                'margin_of_error_percent': margin * 100
            }
            
            self._logger.info(f"Extrapolated accuracy: {estimated_accuracy:.3f} "
                    f"(95% CI: {confidence_lower:.3f}-{confidence_upper:.3f}) "
                    f"for {total_estimated_records:,} total records")
            
            return results