# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardperson_argparse_programs/municipal_bluebook_citation_validator/results_analyzer/_extrapolate_to_full_dataset.py'

Files last updated: 1751408933.7264564

Stub file last updated: 2025-07-07 01:10:14

## ConfidenceIntervals

```python
@dataclass
class ConfidenceIntervals:
    """
    Data class representing statistical confidence intervals and margin of error calculations.

Attributes:
    confidence_interval_lower (float): Lower bound of the confidence interval
    confidence_interval_upper (float): Upper bound of the confidence interval
    confidence_interval_lower_percent (float): Lower bound as a percentage
    confidence_interval_upper_percent (float): Upper bound as a percentage
    confidence_level (float): The confidence level used (e.g., 0.95 for 95%)
    margin_of_error (float): Absolute margin of error value
    margin_of_error_percent (float): Margin of error as a percentage
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## CoreEstimates

```python
@dataclass
class CoreEstimates:
    """
    Data class containing core performance estimates for model evaluation.

Attributes:
    estimated_accuracy (float): The estimated accuracy as a decimal value (0.0 to 1.0).
    estimated_accuracy_percent (float): The estimated accuracy as a percentage (0.0 to 100.0).
    estimated_precision (float): The estimated precision score (0.0 to 1.0).
    estimated_recall (float): The estimated recall score (0.0 to 1.0).
    estimated_f1_score (float): The estimated F1 score, harmonic mean of precision and recall (0.0 to 1.0).
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DatasetEstimates

```python
@dataclass
class DatasetEstimates:
    """
    A dataclass containing statistical estimates for extrapolating sample results to a full dataset.

Attributes:
    total_estimated_records (float): The estimated total number of records in the full dataset
    sample_size (float): The actual number of records in the sample used for analysis
    scaling_factor (float): The multiplier used to scale sample results to full dataset estimates
    sampling_ratio (float): The ratio of sample size to total estimated records (sample_size / total_estimated_records)
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ErrorEstimates

```python
@dataclass
class ErrorEstimates:
    """
    Data class for storing error rate estimates and projections for the full dataset.

Attributes:
    estimated_total_errors (float): Projected total number of errors in the complete dataset
    estimated_valid_citations (float): Projected number of valid citations in the complete dataset
    estimated_error_rate (float): Estimated error rate as a decimal (0.0 to 1.0)
    estimated_error_rate_percent (float): Estimated error rate as a percentage (0.0 to 100.0)
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ExtrapolateToFullDataset

```python
class ExtrapolateToFullDataset:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## GeographicMetrics

```python
@dataclass
class GeographicMetrics:
    """
    Dataclass representing geographic metrics for statistical analysis.

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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## QualityMetrics

```python
@dataclass
class QualityMetrics:
    """
    A data class that holds quality metrics for dataset extrapolation analysis.

Attributes:
    extrapolation_reliability (str): A string indicating the reliability level 
        of extrapolating sample results to the full dataset. Typically contains
        values like 'high', 'medium', 'low' or descriptive reliability assessments.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## Results

```python
@dataclass
class Results:
    """
    Data class containing comprehensive results from municipal bluebook citation validation analysis.

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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: dict[str, Callable] = None, configs: Configs = None) -> None:
```
* **Async:** False
* **Method:** True
* **Class:** ExtrapolateToFullDataset

## _apply_geographic_weighting

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** ExtrapolateToFullDataset

## _calculate_finite_population_correction

```python
@staticmethod
def _calculate_finite_population_correction(sample_size: int, total_estimated_records: int, center: float, margin: float) -> tuple[float, float, float]:
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
```
* **Async:** False
* **Method:** True
* **Class:** ExtrapolateToFullDataset

## _get_wilson_score_interval

```python
@cache
def _get_wilson_score_interval(self, p: float, n: int) -> tuple[float, float]:
    """
    Calculate the Wilson score interval for a proportion.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExtrapolateToFullDataset

## extrapolate_to_full_dataset

```python
def extrapolate_to_full_dataset(self, accuracy_stats, gnis_counts_by_state: dict[str, int], sample_size: int) -> dict[str, float]:
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
```
* **Async:** False
* **Method:** True
* **Class:** ExtrapolateToFullDataset

## total_estimated_records

```python
@cached_property
def total_estimated_records(self) -> int:
```
* **Async:** False
* **Method:** True
* **Class:** ExtrapolateToFullDataset
