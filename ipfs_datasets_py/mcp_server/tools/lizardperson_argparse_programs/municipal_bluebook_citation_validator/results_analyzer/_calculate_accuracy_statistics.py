from functools import cached_property
from typing import Any


class ConfusionMatrixStats:

    def __init__(self, 
                    true_positives: int, 
                    true_negatives: int, 
                    predicted_positives: int, 
                    predicted_negatives: int, 
                    total_population: int
                ):
        self.total_citations: int = total_population
        self.total_errors: int = total_population - true_positives - true_negatives
        self.valid_citations: int = true_positives

        if total_population <= 0:
            raise ValueError("Total population must be greater than zero.")

        if true_positives < 0 or true_negatives < 0 or predicted_positives < 0 or predicted_negatives < 0:
            raise ValueError("Counts must be non-negative integers.")

        self._tp: float = float(true_positives)
        self._tn: float = float(true_negatives)
        self._total: float = float(total_population)
        self._predicted_positives: float = float(predicted_positives)
        self._predicted_negatives: float = float(predicted_negatives)
        self._fp = self.false_positives
        self._fn = self.false_negatives

    @property
    def true_positives(self) -> float:
        """Number of false positives."""
        return self._tp

    @property
    def true_negatives(self) -> float:
        """Number of true negatives."""
        return self._tn

    @cached_property
    def false_negatives(self) -> float:  
        """Number of false negatives."""
        return max(0, self._predicted_positives - self._tp) # Predicted invalid but actually valid
    
    @cached_property
    def false_positives(self) -> float:
        """Number of false positives."""
        return max(0, self._predicted_negatives - self._tn) # Predicted valid but actually invalid

    @property
    def total(self) -> float:
        """Total number of citations."""
        return self._total

    # Core metrics
    @cached_property
    def accuracy(self) -> float:
        """Calculate accuracy."""
        return (self._tp + self._tn) / self._total if self._total > 0 else 0.0
    
    @property
    def accuracy_percent(self) -> float:
        """Calculate accuracy as a percentage."""
        return self.accuracy * 100

    @property
    def error_rate(self) -> float:
        """Calculate error rate."""
        return 1 - self.accuracy
    
    @property
    def error_rate_percent(self) -> float:
        """Calculate error rate as a percentage."""
        return self.error_rate * 100

    @cached_property
    def true_positive_rate(self) -> float:
        """Calculate true positive rate (sensitivity, recall)."""
        return self._tp / (self._tp + self.false_negatives) if (self._tp + self.false_negatives) > 0 else 0.0

    @cached_property
    def true_negative_rate(self) -> float:
        """Calculate true negative rate (specificity)."""
        return self._tn / (self._tn + self.false_positives) if (self._tn + self.false_positives) > 0 else 0.0

    @cached_property
    def precision(self) -> float:
        """Calculate precision."""
        return self._tp / (self._tp + self.false_positives) if (self._tp + self.false_positives) > 0 else 0.0

    @cached_property
    def negative_predictive_value(self) -> float:
        """Calculate negative predictive value."""
        return self._tn / (self._tn + self.false_negatives) if (self._tn + self.false_negatives) > 0 else 0.0

    @cached_property
    def false_positive_rate(self) -> float:
        """Calculate false positive rate."""
        return self.false_positives / (self.false_positives + self._tn) if (self.false_positives + self._tn) > 0 else 0.0

    @cached_property
    def false_negative_rate(self) -> float:
        """Calculate false negative rate."""
        return self.false_negatives / (self.false_negatives + self._tp) if (self.false_negatives + self._tp) > 0 else 0.0
    
    @cached_property
    def positive_likelihood_ratio(self) -> float:
        """Calculate positive likelihood ratio."""
        return self.true_positive_rate / self.false_positive_rate if self.false_positive_rate > 0 else float('inf')

    @cached_property
    def negative_likelihood_ratio(self) -> float:
        """Calculate negative likelihood ratio."""
        return self.false_negative_rate / self.true_negative_rate if self.true_negative_rate > 0 else float('inf')

    @cached_property
    def diagnostic_odds_ratio(self) -> float:
        """Calculate diagnostic odds ratio."""
        return self.positive_likelihood_ratio / self.negative_likelihood_ratio if self.negative_likelihood_ratio > 0 else float('inf')

    @cached_property
    def f1_score(self) -> float:
        """Calculate F1 score."""
        return 2 * (self.precision * self.true_positive_rate) / (self.precision + self.true_positive_rate) if (self.precision + self.true_positive_rate) > 0 else 0.0

    @cached_property
    def false_discovery_rate(self) -> float:
        """Calculate false discovery rate."""
        return self.false_positives / (self.false_positives + self._tp) if (self.false_positives + self._tp) > 0 else 0.0

    @cached_property
    def false_omission_rate(self) -> float:
        """Calculate false omission rate."""
        return self.false_negatives / (self.false_negatives + self._tn) if (self.false_negatives + self._tn) > 0 else 0.0

    @cached_property
    def prevalence(self) -> float:
        """Calculate prevalence of the condition."""
        return (self._tp + self.false_negatives) / self._total if self._total > 0 else 0.0

    def to_dict(self) -> dict[str, float]:
        """Convert confusion matrix stats to dictionary with all metrics."""
        return {
            'true_positives': self.true_positives,
            'true_negatives': self.true_negatives,
            'false_positives': self.false_positives,
            'false_negatives': self.false_negatives,
            'total': self.total,
            'accuracy': self.accuracy,
            'accuracy_percent': self.accuracy_percent,
            'error_rate': self.error_rate,
            'error_rate_percent': self.error_rate_percent,
            'true_positive_rate': self.true_positive_rate,
            'true_negative_rate': self.true_negative_rate,
            'precision': self.precision,
            'negative_predictive_value': self.negative_predictive_value,
            'false_positive_rate': self.false_positive_rate,
            'false_negative_rate': self.false_negative_rate,
            'positive_likelihood_ratio': self.positive_likelihood_ratio,
            'negative_likelihood_ratio': self.negative_likelihood_ratio,
            'diagnostic_odds_ratio': self.diagnostic_odds_ratio,
            'f1_score': self.f1_score,
            'false_discovery_rate': self.false_discovery_rate,
            'false_omission_rate': self.false_omission_rate,
            'prevalence': self.prevalence
        }



def calculate_accuracy_statistics(
    total_citations: int,
    total_errors: int,
    predicted_positives: int,
    predicted_negatives: int
) -> dict[str, Any]:
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
    if total_citations == 0:
        return {
            'total_citations': 0,
            'total_errors': 0,
            'accuracy_percent': 0.0,
            'error_rate_percent': 0.0,
            'valid_citations': 0
        }

    valid_citations = total_citations - total_errors

    confusion_matrix = ConfusionMatrixStats(
        true_positives=valid_citations, # Correctly identified as valid
        true_negatives=total_errors, # Correctly identified as having errors
        predicted_positives=predicted_positives,
        predicted_negatives=predicted_negatives,
        total_population=total_citations
    )
    return confusion_matrix.to_dict()