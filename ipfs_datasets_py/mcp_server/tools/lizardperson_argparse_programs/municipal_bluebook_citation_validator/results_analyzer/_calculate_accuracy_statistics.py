from dataclasses import dataclass

@dataclass
class ConfusionMatrix:
    """
    Dataclass representing a confusion matrix with comprehensive metrics.

    Attributes:
        true_positives: Correctly predicted positive cases (TP)
        true_negatives: Correctly predicted negative cases (TN)
        false_positives: Incorrectly predicted positive cases (FP)
        false_negatives: Incorrectly predicted negative cases (FN)

    Properties:
        total_population: Total number of cases evaluated
        accuracy: Overall accuracy (TP + TN) / Total
        precision: TP / (TP + FP)
        recall: TP / (TP + FN), also known as sensitivity
        specificity: TN / (TN + FP)
        f1_score: Harmonic mean of precision and recall
        false_positive_rate: FP / (FP + TN)
        false_negative_rate: FN / (FN + TP)
    
    Methods:
        to_dict(): Convert confusion matrix to dictionary with all metrics
    """
    true_positives: int = 0
    true_negatives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def total_population(self) -> int:
        """Total number of cases evaluated."""
        return self.true_positives + self.true_negatives + self.false_positives + self.false_negatives

    @property
    def accuracy(self) -> float:
        """Overall accuracy: (TP + TN) / Total"""
        if self.total_population == 0:
            return 0.0
        return (self.true_positives + self.true_negatives) / self.total_population

    @property
    def precision(self) -> float:
        """Precision: TP / (TP + FP)"""
        denominator = self.true_positives + self.false_positives
        return self.true_positives / denominator if denominator > 0 else 0.0

    @property
    def recall(self) -> float:
        """Recall/Sensitivity: TP / (TP + FN)"""
        denominator = self.true_positives + self.false_negatives
        return self.true_positives / denominator if denominator > 0 else 0.0
    
    @property
    def specificity(self) -> float:
        """Specificity: TN / (TN + FP)"""
        denominator = self.true_negatives + self.false_positives
        return self.true_negatives / denominator if denominator > 0 else 0.0

    @property
    def f1_score(self) -> float:
        """F1 Score: 2 * (precision * recall) / (precision + recall)"""
        denominator = self.precision + self.recall
        return 2 * (self.precision * self.recall) / denominator if denominator > 0 else 0.0

    @property
    def false_positive_rate(self) -> float:
        """False Positive Rate: FP / (FP + TN)"""
        denominator = self.false_positives + self.true_negatives
        return self.false_positives / denominator if denominator > 0 else 0.0

    @property
    def false_negative_rate(self) -> float:
        """False Negative Rate: FN / (FN + TP)"""
        denominator = self.false_negatives + self.true_positives
        return self.false_negatives / denominator if denominator > 0 else 0.0

    def to_dict(self) -> dict[str, float]:
        """Convert confusion matrix to dictionary with all metrics."""
        return {
            'true_positives': float(self.true_positives),
            'true_negatives': float(self.true_negatives),
            'false_positives': float(self.false_positives),
            'false_negatives': float(self.false_negatives),
            'total_population': float(self.total_population),
            'accuracy': self.accuracy,
            'accuracy_percent': self.accuracy * 100,
            'precision': self.precision,
            'recall': self.recall,
            'sensitivity': self.recall,
            'specificity': self.specificity,
            'f1_score': self.f1_score,
            'false_positive_rate': self.false_positive_rate,
            'false_negative_rate': self.false_negative_rate,
            'error_rate': 1 - self.accuracy,
            'error_rate_percent': (1 - self.accuracy) * 100
        }


def calculate_accuracy_statistics(
    total_citations: int,
    total_errors: int,
    predicted_positives: int,
    predicted_negatives: int
) -> ConfusionMatrix:
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
    confusion_matrix = ConfusionMatrix(
        true_positives=total_citations,
        true_negatives=total_errors,
        predicted_positives=predicted_positives,
        predicted_negatives=predicted_negatives
    )
    return confusion_matrix.to_dict()