# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardperson_argparse_programs/municipal_bluebook_citation_validator/results_analyzer/_calculate_accuracy_statistics.py'

Files last updated: 1751408933.7264564

Stub file last updated: 2025-07-07 01:10:14

## ConfusionMatrixStats

```python
class ConfusionMatrixStats:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, true_positives: int, true_negatives: int, predicted_positives: int, predicted_negatives: int, total_population: int):
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## accuracy

```python
@cached_property
def accuracy(self) -> float:
    """
    Calculate accuracy.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## accuracy_percent

```python
@property
def accuracy_percent(self) -> float:
    """
    Calculate accuracy as a percentage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## calculate_accuracy_statistics

```python
def calculate_accuracy_statistics(total_citations: int, total_errors: int, predicted_positives: int, predicted_negatives: int) -> dict[str, Any]:
    """
    Calculate accuracy percentages for the sample.

Args:
    total_citations (int): Total number of citations checked.
    total_errors (int): Total number of errors found.
    predicted_positives (int): Total number of citations that were predicted as valid.
    predicted_negatives (int): Total number of citations that were predicted as invalid.

Returns:
    A confusion matrix statistics dictionary with all metrics.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## diagnostic_odds_ratio

```python
@cached_property
def diagnostic_odds_ratio(self) -> float:
    """
    Calculate diagnostic odds ratio.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## error_rate

```python
@property
def error_rate(self) -> float:
    """
    Calculate error rate.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## error_rate_percent

```python
@property
def error_rate_percent(self) -> float:
    """
    Calculate error rate as a percentage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## f1_score

```python
@cached_property
def f1_score(self) -> float:
    """
    Calculate F1 score.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## false_discovery_rate

```python
@cached_property
def false_discovery_rate(self) -> float:
    """
    Calculate false discovery rate.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## false_negative_rate

```python
@cached_property
def false_negative_rate(self) -> float:
    """
    Calculate false negative rate.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## false_negatives

```python
@cached_property
def false_negatives(self) -> float:
    """
    Number of false negatives.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## false_omission_rate

```python
@cached_property
def false_omission_rate(self) -> float:
    """
    Calculate false omission rate.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## false_positive_rate

```python
@cached_property
def false_positive_rate(self) -> float:
    """
    Calculate false positive rate.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## false_positives

```python
@cached_property
def false_positives(self) -> float:
    """
    Number of false positives.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## negative_likelihood_ratio

```python
@cached_property
def negative_likelihood_ratio(self) -> float:
    """
    Calculate negative likelihood ratio.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## negative_predictive_value

```python
@cached_property
def negative_predictive_value(self) -> float:
    """
    Calculate negative predictive value.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## positive_likelihood_ratio

```python
@cached_property
def positive_likelihood_ratio(self) -> float:
    """
    Calculate positive likelihood ratio.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## precision

```python
@cached_property
def precision(self) -> float:
    """
    Calculate precision.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## prevalence

```python
@cached_property
def prevalence(self) -> float:
    """
    Calculate prevalence of the condition.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## to_dict

```python
def to_dict(self) -> dict[str, float]:
    """
    Convert confusion matrix stats to dictionary with all metrics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## total

```python
@property
def total(self) -> float:
    """
    Total number of citations.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## true_negative_rate

```python
@cached_property
def true_negative_rate(self) -> float:
    """
    Calculate true negative rate (specificity).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## true_negatives

```python
@property
def true_negatives(self) -> float:
    """
    Number of true negatives.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## true_positive_rate

```python
@cached_property
def true_positive_rate(self) -> float:
    """
    Calculate true positive rate (sensitivity, recall).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats

## true_positives

```python
@property
def true_positives(self) -> float:
    """
    Number of false positives.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ConfusionMatrixStats
