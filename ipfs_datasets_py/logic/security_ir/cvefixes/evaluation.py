"""Leakage-safe evaluation and fail-closed promotion for CVEfixes candidates.

Evaluation examples are grouped before they are assigned to a split.  A group
is the transitive closure of shared repository, CVE, commit, exact body hash,
and near-duplicate body content.  Consequently a vulnerable/fixed family can
never be separated merely because one of its identifiers differs.

Labels are derived from :class:`EvaluationPolarity`: vulnerable examples are
positive controls and fixed examples are negative controls.  A caller cannot
attach a vulnerable label to a fixed example.  Thresholds are measured on a
validation split, metrics are reported for both polarities and caller-defined
strata, and calibration is retained alongside classification metrics.

Promotion is a release-workflow decision, not policy or execution authority.
Every quantitative, leakage, and adversarial gate must pass and an explicit
review must be recorded before ``PROMOTE`` can be emitted.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import math
import re
from types import MappingProxyType
from typing import Any, ClassVar, Final


EVALUATION_SCHEMA_VERSION: Final = "cvefixes-leakage-safe-evaluation/v1"
EVALUATION_CONFIG_SCHEMA_VERSION: Final = (
    "cvefixes-leakage-safe-evaluation-config/v1"
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class EvaluationError(ValueError):
    """Raised when evaluation input could weaken or obscure a safety gate."""


class EvaluationPolarity(str, Enum):
    """Ground-truth role of a CVEfixes code example."""

    VULNERABLE_POSITIVE = "vulnerable_positive"
    FIXED_NEGATIVE = "fixed_negative"


class EvaluationSplit(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class LeakageKind(str, Enum):
    REPOSITORY = "repository"
    CVE = "cve"
    COMMIT = "commit"
    BODY_HASH = "body_hash"
    NEAR_DUPLICATE = "near_duplicate"


class PromotionDecision(str, Enum):
    REJECT = "reject"
    REVIEW_REQUIRED = "review_required"
    PROMOTE = "promote"


def _clean_text(value: Any, label: str, *, maximum: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or len(value) > maximum
    ):
        raise EvaluationError(f"{label} must be bounded, non-empty trimmed text")
    return value


def _probability(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(f"{label} must be a probability")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise EvaluationError(
            f"{label} probability must be finite and between zero and one"
        )
    return result


def body_sha256(body: str) -> str:
    """Return the exact UTF-8 body digest used by split leakage checks."""

    if not isinstance(body, str):
        raise EvaluationError("body must be text")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _body_sketch(body: str, *, width: int = 5) -> frozenset[str]:
    tokens = tuple(token.casefold() for token in _TOKEN_RE.findall(body))
    if not tokens:
        return frozenset()
    if len(tokens) < width:
        return frozenset({" ".join(tokens)})
    return frozenset(
        " ".join(tokens[index : index + width])
        for index in range(len(tokens) - width + 1)
    )


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


@dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationExample:
    """One inert evaluation control with immutable leakage identifiers."""

    example_id: str
    repository_id: str
    cve_id: str
    commit_id: str
    body_hash: str
    polarity: EvaluationPolarity
    body_text: str = field(default="", repr=False, compare=False)
    label: bool | None = None
    strata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("example_id", "repository_id", "cve_id", "commit_id"):
            _clean_text(getattr(self, name), name, maximum=1024)
        digest = _clean_text(self.body_hash, "body_hash", maximum=64).casefold()
        if not _SHA256_RE.fullmatch(digest):
            raise EvaluationError("body_hash must be a lowercase SHA-256 digest")
        object.__setattr__(self, "body_hash", digest)
        try:
            polarity = (
                self.polarity
                if isinstance(self.polarity, EvaluationPolarity)
                else EvaluationPolarity(self.polarity)
            )
        except (TypeError, ValueError) as exc:
            raise EvaluationError(f"unsupported polarity: {self.polarity!r}") from exc
        object.__setattr__(self, "polarity", polarity)

        expected_label = polarity is EvaluationPolarity.VULNERABLE_POSITIVE
        if self.label is not None and (
            type(self.label) is not bool or self.label is not expected_label
        ):
            raise EvaluationError(
                "labels are polarity-locked: fixed examples are negative and "
                "vulnerable examples are positive"
            )
        object.__setattr__(self, "label", expected_label)

        if not isinstance(self.body_text, str) or not self.body_text:
            raise EvaluationError(
                "body_text is required to enforce near-duplicate isolation"
            )
        if body_sha256(self.body_text) != digest:
            raise EvaluationError("body_text does not match body_hash")

        if not isinstance(self.strata, Mapping):
            raise EvaluationError("strata must be a mapping")
        normalized: dict[str, str] = {}
        for key, value in self.strata.items():
            clean_key = _clean_text(key, "stratum key", maximum=128)
            clean_value = _clean_text(value, "stratum value", maximum=512)
            if clean_key in normalized:
                raise EvaluationError(f"duplicate stratum key: {clean_key}")
            normalized[clean_key] = clean_value
        object.__setattr__(
            self, "strata", MappingProxyType(dict(sorted(normalized.items())))
        )

    @property
    def expected_label(self) -> bool:
        return self.polarity is EvaluationPolarity.VULNERABLE_POSITIVE

    @property
    def body_sketch(self) -> frozenset[str]:
        return _body_sketch(self.body_text)


@dataclass(frozen=True, slots=True)
class SplitConfig:
    """Deterministic split ratios and near-duplicate policy."""

    train_ratio: float = 0.70
    validation_ratio: float = 0.15
    test_ratio: float = 0.15
    near_duplicate_threshold: float = 0.85
    seed: str = "cvefixes-evaluation-v1"
    max_examples: int = 100_000
    schema_version: str = EVALUATION_CONFIG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        ratios = tuple(
            _probability(getattr(self, name), name)
            for name in ("train_ratio", "validation_ratio", "test_ratio")
        )
        if any(ratio <= 0.0 for ratio in ratios):
            raise EvaluationError("all split ratios must be greater than zero")
        if not math.isclose(sum(ratios), 1.0, abs_tol=1e-12):
            raise EvaluationError("split ratios must sum to one")
        threshold = _probability(
            self.near_duplicate_threshold, "near_duplicate_threshold"
        )
        if threshold <= 0.0:
            raise EvaluationError("near_duplicate_threshold must be greater than zero")
        _clean_text(self.seed, "seed", maximum=1024)
        if type(self.max_examples) is not int or self.max_examples <= 0:
            raise EvaluationError("max_examples must be a positive integer")
        if self.schema_version != EVALUATION_CONFIG_SCHEMA_VERSION:
            raise EvaluationError("unsupported split config schema")

    @property
    def ratios(self) -> Mapping[EvaluationSplit, float]:
        return MappingProxyType(
            {
                EvaluationSplit.TRAIN: self.train_ratio,
                EvaluationSplit.VALIDATION: self.validation_ratio,
                EvaluationSplit.TEST: self.test_ratio,
            }
        )


@dataclass(frozen=True, slots=True)
class LeakageFinding:
    kind: LeakageKind
    left_example_id: str
    right_example_id: str
    left_split: EvaluationSplit
    right_split: EvaluationSplit
    similarity: float = 1.0

    def __post_init__(self) -> None:
        try:
            kind = (
                self.kind
                if isinstance(self.kind, LeakageKind)
                else LeakageKind(self.kind)
            )
            left_split = (
                self.left_split
                if isinstance(self.left_split, EvaluationSplit)
                else EvaluationSplit(self.left_split)
            )
            right_split = (
                self.right_split
                if isinstance(self.right_split, EvaluationSplit)
                else EvaluationSplit(self.right_split)
            )
        except (TypeError, ValueError) as exc:
            raise EvaluationError("invalid leakage finding enum value") from exc
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "left_split", left_split)
        object.__setattr__(self, "right_split", right_split)
        _clean_text(self.left_example_id, "left_example_id", maximum=1024)
        _clean_text(self.right_example_id, "right_example_id", maximum=1024)
        if self.left_split is self.right_split:
            raise EvaluationError("a leakage finding must cross split boundaries")
        _probability(self.similarity, "similarity")


@dataclass(frozen=True, slots=True)
class LeakageSafeSplits:
    """The three partitions produced by connected-component assignment."""

    train: tuple[EvaluationExample, ...]
    validation: tuple[EvaluationExample, ...]
    test: tuple[EvaluationExample, ...]
    config: SplitConfig = field(default_factory=SplitConfig)

    def __post_init__(self) -> None:
        if not isinstance(self.config, SplitConfig):
            raise EvaluationError("config must be SplitConfig")
        for name in ("train", "validation", "test"):
            values = tuple(
                sorted(getattr(self, name), key=lambda item: item.example_id)
            )
            if any(not isinstance(item, EvaluationExample) for item in values):
                raise EvaluationError(f"{name} must contain EvaluationExample values")
            object.__setattr__(self, name, values)
        all_ids = [
            item.example_id
            for values in (self.train, self.validation, self.test)
            for item in values
        ]
        if len(all_ids) != len(set(all_ids)):
            raise EvaluationError("an example cannot occur in more than one split")

    @property
    def assignments(self) -> Mapping[str, EvaluationSplit]:
        result: dict[str, EvaluationSplit] = {}
        for split, values in self.items():
            result.update((item.example_id, split) for item in values)
        return MappingProxyType(result)

    def items(
        self,
    ) -> tuple[tuple[EvaluationSplit, tuple[EvaluationExample, ...]], ...]:
        return (
            (EvaluationSplit.TRAIN, self.train),
            (EvaluationSplit.VALIDATION, self.validation),
            (EvaluationSplit.TEST, self.test),
        )


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1


def _exact_leakage_keys(example: EvaluationExample) -> tuple[tuple[str, str], ...]:
    return (
        (LeakageKind.REPOSITORY.value, example.repository_id.casefold()),
        (LeakageKind.CVE.value, example.cve_id.casefold()),
        (LeakageKind.COMMIT.value, example.commit_id.casefold()),
        (LeakageKind.BODY_HASH.value, example.body_hash),
    )


def _near_duplicate_pairs(
    examples: Sequence[EvaluationExample], threshold: float
) -> tuple[tuple[int, int, float], ...]:
    sketches = tuple(item.body_sketch for item in examples)
    inverted: dict[str, list[int]] = {}
    candidates: set[tuple[int, int]] = set()
    for index, sketch in enumerate(sketches):
        for shingle in sketch:
            for other in inverted.get(shingle, ()):
                candidates.add((other, index))
            inverted.setdefault(shingle, []).append(index)
    result = []
    for left, right in sorted(candidates):
        similarity = _jaccard(sketches[left], sketches[right])
        if similarity >= threshold:
            result.append((left, right, similarity))
    return tuple(result)


def audit_split_leakage(
    splits: LeakageSafeSplits,
    *,
    near_duplicate_threshold: float | None = None,
) -> tuple[LeakageFinding, ...]:
    """Return every cross-split exact or near-duplicate leakage finding."""

    if not isinstance(splits, LeakageSafeSplits):
        raise EvaluationError("splits must be LeakageSafeSplits")
    threshold = (
        splits.config.near_duplicate_threshold
        if near_duplicate_threshold is None
        else _probability(near_duplicate_threshold, "near_duplicate_threshold")
    )
    located = tuple(
        (split, example)
        for split, values in splits.items()
        for example in values
    )
    findings: list[LeakageFinding] = []
    seen: dict[tuple[str, str], tuple[EvaluationSplit, EvaluationExample]] = {}
    for split, example in located:
        for raw_kind, key in _exact_leakage_keys(example):
            prior = seen.get((raw_kind, key))
            if prior is not None and prior[0] is not split:
                findings.append(
                    LeakageFinding(
                        kind=LeakageKind(raw_kind),
                        left_example_id=prior[1].example_id,
                        right_example_id=example.example_id,
                        left_split=prior[0],
                        right_split=split,
                    )
                )
            else:
                seen.setdefault((raw_kind, key), (split, example))

    examples = tuple(item[1] for item in located)
    for left, right, similarity in _near_duplicate_pairs(examples, threshold):
        left_split, right_split = located[left][0], located[right][0]
        if left_split is not right_split:
            findings.append(
                LeakageFinding(
                    kind=LeakageKind.NEAR_DUPLICATE,
                    left_example_id=examples[left].example_id,
                    right_example_id=examples[right].example_id,
                    left_split=left_split,
                    right_split=right_split,
                    similarity=similarity,
                )
            )
    return tuple(
        sorted(
            findings,
            key=lambda item: (
                item.kind.value,
                item.left_example_id,
                item.right_example_id,
            ),
        )
    )


def build_leakage_safe_splits(
    examples: Sequence[EvaluationExample],
    *,
    config: SplitConfig | None = None,
) -> LeakageSafeSplits:
    """Assign transitive leakage groups to deterministic balanced splits."""

    config = config or SplitConfig()
    if not isinstance(config, SplitConfig):
        raise EvaluationError("config must be SplitConfig")
    values = tuple(examples)
    if not values:
        raise EvaluationError("at least one evaluation example is required")
    if len(values) > config.max_examples:
        raise EvaluationError(
            f"evaluation contains {len(values)} examples; "
            f"limit is {config.max_examples}"
        )
    if any(not isinstance(item, EvaluationExample) for item in values):
        raise EvaluationError("examples must contain EvaluationExample values")
    ids = [item.example_id for item in values]
    if len(ids) != len(set(ids)):
        raise EvaluationError("evaluation example IDs must be unique")

    union = _UnionFind(len(values))
    exact_owner: dict[tuple[str, str], int] = {}
    for index, example in enumerate(values):
        for key in _exact_leakage_keys(example):
            if key in exact_owner:
                union.union(index, exact_owner[key])
            else:
                exact_owner[key] = index
    for left, right, _ in _near_duplicate_pairs(
        values, config.near_duplicate_threshold
    ):
        union.union(left, right)

    grouped: dict[int, list[EvaluationExample]] = {}
    for index, example in enumerate(values):
        grouped.setdefault(union.find(index), []).append(example)
    components = tuple(
        tuple(sorted(group, key=lambda item: item.example_id))
        for group in grouped.values()
    )

    def component_digest(component: tuple[EvaluationExample, ...]) -> str:
        material = "\0".join(item.example_id for item in component)
        return hashlib.sha256(f"{config.seed}\0{material}".encode()).hexdigest()

    ordered = sorted(
        components, key=lambda group: (-len(group), component_digest(group))
    )
    targets = {
        split: len(values) * ratio for split, ratio in config.ratios.items()
    }
    assigned: dict[EvaluationSplit, list[EvaluationExample]] = {
        split: [] for split in EvaluationSplit
    }
    for component in ordered:
        digest = component_digest(component)

        def desirability(split: EvaluationSplit) -> tuple[float, str]:
            target = targets[split]
            deficit = (target - len(assigned[split])) / target
            tie = hashlib.sha256(f"{digest}\0{split.value}".encode()).hexdigest()
            return deficit, tie

        selected = max(EvaluationSplit, key=desirability)
        assigned[selected].extend(component)

    result = LeakageSafeSplits(
        train=tuple(assigned[EvaluationSplit.TRAIN]),
        validation=tuple(assigned[EvaluationSplit.VALIDATION]),
        test=tuple(assigned[EvaluationSplit.TEST]),
        config=config,
    )
    findings = audit_split_leakage(result)
    if findings:  # Defensive invariant: grouping and auditing must agree.
        raise EvaluationError("internal error: leakage-safe split audit failed")
    return result


@dataclass(frozen=True, slots=True)
class EvaluationPrediction:
    example_id: str
    vulnerable_score: float

    def __post_init__(self) -> None:
        _clean_text(self.example_id, "example_id", maximum=1024)
        object.__setattr__(
            self,
            "vulnerable_score",
            _probability(self.vulnerable_score, "vulnerable_score"),
        )


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_score: float
    positive_rate: float
    absolute_error: float

    def __post_init__(self) -> None:
        lower = _probability(self.lower, "calibration lower")
        upper = _probability(self.upper, "calibration upper")
        if upper <= lower:
            raise EvaluationError("calibration bin upper must exceed lower")
        if type(self.count) is not int or self.count <= 0:
            raise EvaluationError("calibration bin count must be positive")
        _probability(self.mean_score, "calibration mean_score")
        _probability(self.positive_rate, "calibration positive_rate")
        _probability(self.absolute_error, "calibration absolute_error")


@dataclass(frozen=True, slots=True)
class BinaryMetrics:
    sample_count: int
    vulnerable_positives: int
    fixed_negatives: int
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    vulnerable_recall: float
    fixed_negative_accuracy: float
    precision: float
    accuracy: float
    balanced_accuracy: float
    f1: float
    false_positive_rate: float
    brier_score: float

    def __post_init__(self) -> None:
        count_names = (
            "sample_count",
            "vulnerable_positives",
            "fixed_negatives",
            "true_positives",
            "false_positives",
            "true_negatives",
            "false_negatives",
        )
        for name in count_names:
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise EvaluationError(f"{name} must be a non-negative integer")
        if self.vulnerable_positives + self.fixed_negatives != self.sample_count:
            raise EvaluationError("metric class counts do not equal sample_count")
        if (
            self.true_positives
            + self.false_positives
            + self.true_negatives
            + self.false_negatives
            != self.sample_count
        ):
            raise EvaluationError("metric confusion counts do not equal sample_count")
        for name in (
            "vulnerable_recall",
            "fixed_negative_accuracy",
            "precision",
            "accuracy",
            "balanced_accuracy",
            "f1",
            "false_positive_rate",
            "brier_score",
        ):
            _probability(getattr(self, name), name)

    def to_dict(self) -> dict[str, int | float]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class MetricsReport:
    threshold: float
    overall: BinaryMetrics
    by_stratum: Mapping[str, BinaryMetrics]
    calibration_bins: tuple[CalibrationBin, ...]
    expected_calibration_error: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "threshold", _probability(self.threshold, "threshold"))
        if not isinstance(self.overall, BinaryMetrics):
            raise EvaluationError("overall must be BinaryMetrics")
        if not isinstance(self.by_stratum, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, BinaryMetrics)
            for key, value in self.by_stratum.items()
        ):
            raise EvaluationError("by_stratum must map strings to BinaryMetrics")
        bins = tuple(self.calibration_bins)
        if any(not isinstance(item, CalibrationBin) for item in bins):
            raise EvaluationError("calibration_bins are invalid")
        if sum(item.count for item in bins) != self.overall.sample_count:
            raise EvaluationError(
                "calibration bin counts must equal the metric sample count"
            )
        object.__setattr__(self, "calibration_bins", bins)
        _probability(
            self.expected_calibration_error, "expected_calibration_error"
        )
        object.__setattr__(
            self,
            "by_stratum",
            MappingProxyType(dict(sorted(self.by_stratum.items()))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "by_stratum": {
                key: value.to_dict() for key, value in self.by_stratum.items()
            },
            "calibration_bins": [
                {
                    name: getattr(item, name)
                    for name in item.__dataclass_fields__
                }
                for item in self.calibration_bins
            ],
            "expected_calibration_error": self.expected_calibration_error,
            "overall": self.overall.to_dict(),
            "threshold": self.threshold,
        }


def _bind_predictions(
    examples: Sequence[EvaluationExample],
    predictions: Sequence[EvaluationPrediction],
) -> tuple[tuple[EvaluationExample, float], ...]:
    values = tuple(examples)
    prediction_values = tuple(predictions)
    if not values:
        raise EvaluationError("metrics require at least one example")
    if any(not isinstance(item, EvaluationExample) for item in values):
        raise EvaluationError("metrics examples are invalid")
    if any(not isinstance(item, EvaluationPrediction) for item in prediction_values):
        raise EvaluationError("predictions are invalid")
    example_ids = [item.example_id for item in values]
    prediction_ids = [item.example_id for item in prediction_values]
    if len(example_ids) != len(set(example_ids)):
        raise EvaluationError("metric example IDs must be unique")
    if len(prediction_ids) != len(set(prediction_ids)):
        raise EvaluationError("prediction example IDs must be unique")
    if set(example_ids) != set(prediction_ids):
        missing = sorted(set(example_ids) - set(prediction_ids))
        extra = sorted(set(prediction_ids) - set(example_ids))
        raise EvaluationError(
            f"predictions must exactly cover examples; missing={missing}, extra={extra}"
        )
    scores = {item.example_id: item.vulnerable_score for item in prediction_values}
    return tuple((item, scores[item.example_id]) for item in values)


def _binary_metrics(
    bound: Sequence[tuple[EvaluationExample, float]], threshold: float
) -> BinaryMetrics:
    tp = fp = tn = fn = 0
    brier = 0.0
    for example, score in bound:
        predicted = score >= threshold
        expected = example.expected_label
        tp += int(predicted and expected)
        fp += int(predicted and not expected)
        tn += int(not predicted and not expected)
        fn += int(not predicted and expected)
        brier += (score - float(expected)) ** 2
    positives, negatives = tp + fn, tn + fp
    recall = tp / positives if positives else 0.0
    specificity = tn / negatives if negatives else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    accuracy = (tp + tn) / len(bound) if bound else 0.0
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return BinaryMetrics(
        sample_count=len(bound),
        vulnerable_positives=positives,
        fixed_negatives=negatives,
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
        vulnerable_recall=recall,
        fixed_negative_accuracy=specificity,
        precision=precision,
        accuracy=accuracy,
        balanced_accuracy=(recall + specificity) / 2.0,
        f1=f1,
        false_positive_rate=(fp / negatives if negatives else 0.0),
        brier_score=(brier / len(bound) if bound else 0.0),
    )


def evaluate_predictions(
    examples: Sequence[EvaluationExample],
    predictions: Sequence[EvaluationPrediction],
    *,
    threshold: float,
    calibration_bin_count: int = 10,
) -> MetricsReport:
    """Compute vulnerable/fixed, stratified, and calibration measurements."""

    threshold = _probability(threshold, "threshold")
    if type(calibration_bin_count) is not int or calibration_bin_count <= 0:
        raise EvaluationError("calibration_bin_count must be a positive integer")
    if calibration_bin_count > 100:
        raise EvaluationError("calibration_bin_count must not exceed 100")
    bound = _bind_predictions(examples, predictions)

    groups: dict[str, list[tuple[EvaluationExample, float]]] = {}
    for example, score in bound:
        polarity_key = f"polarity={example.polarity.value}"
        groups.setdefault(polarity_key, []).append((example, score))
        for key, value in example.strata.items():
            groups.setdefault(f"{key}={value}", []).append((example, score))

    bins: list[CalibrationBin] = []
    weighted_error = 0.0
    for index in range(calibration_bin_count):
        lower = index / calibration_bin_count
        upper = (index + 1) / calibration_bin_count
        members = [
            (example, score)
            for example, score in bound
            if lower <= score < upper
            or (index == calibration_bin_count - 1 and score == 1.0)
        ]
        if not members:
            continue
        mean_score = sum(score for _, score in members) / len(members)
        positive_rate = sum(
            int(example.expected_label) for example, _ in members
        ) / len(members)
        error = abs(mean_score - positive_rate)
        weighted_error += error * len(members)
        bins.append(
            CalibrationBin(
                lower=lower,
                upper=upper,
                count=len(members),
                mean_score=mean_score,
                positive_rate=positive_rate,
                absolute_error=error,
            )
        )
    return MetricsReport(
        threshold=threshold,
        overall=_binary_metrics(bound, threshold),
        by_stratum={
            key: _binary_metrics(values, threshold)
            for key, values in groups.items()
        },
        calibration_bins=tuple(bins),
        expected_calibration_error=weighted_error / len(bound),
    )


@dataclass(frozen=True, slots=True)
class ThresholdMeasurement:
    threshold: float
    validation_sample_count: int
    vulnerable_positives: int
    fixed_negatives: int
    balanced_accuracy: float
    source_split: EvaluationSplit = EvaluationSplit.VALIDATION
    measured: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "threshold", _probability(self.threshold, "threshold"))
        try:
            source_split = (
                self.source_split
                if isinstance(self.source_split, EvaluationSplit)
                else EvaluationSplit(self.source_split)
            )
        except (TypeError, ValueError) as exc:
            raise EvaluationError("invalid threshold source_split") from exc
        object.__setattr__(self, "source_split", source_split)
        if self.source_split is not EvaluationSplit.VALIDATION:
            raise EvaluationError("thresholds must be measured on validation data")
        if self.measured is not True:
            raise EvaluationError("threshold measurement cannot be asserted unmeasured")
        for name in (
            "validation_sample_count",
            "vulnerable_positives",
            "fixed_negatives",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise EvaluationError(f"{name} must be a non-negative integer")
        _probability(self.balanced_accuracy, "balanced_accuracy")


def measure_threshold(
    validation_examples: Sequence[EvaluationExample],
    predictions: Sequence[EvaluationPrediction],
) -> ThresholdMeasurement:
    """Select a measured threshold by validation balanced accuracy.

    Ties prefer fixed-negative accuracy, then vulnerable recall, then the
    higher (more conservative) threshold.
    """

    bound = _bind_predictions(validation_examples, predictions)
    positives = sum(item.expected_label for item, _ in bound)
    negatives = len(bound) - positives
    if not positives or not negatives:
        raise EvaluationError(
            "threshold measurement requires vulnerable and fixed validation controls"
        )
    candidate_thresholds = sorted({0.0, 1.0, *(score for _, score in bound)})
    ranked = []
    for threshold in candidate_thresholds:
        metrics = _binary_metrics(bound, threshold)
        ranked.append(
            (
                metrics.balanced_accuracy,
                metrics.fixed_negative_accuracy,
                metrics.vulnerable_recall,
                threshold,
                metrics,
            )
        )
    _, _, _, threshold, metrics = max(ranked, key=lambda item: item[:4])
    return ThresholdMeasurement(
        threshold=threshold,
        validation_sample_count=len(bound),
        vulnerable_positives=positives,
        fixed_negatives=negatives,
        balanced_accuracy=metrics.balanced_accuracy,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class AdversarialInjectionCase:
    """An inert clean/injected pair used to probe instruction injection."""

    case_id: str
    clean_input: str
    injected_input: str
    expected_polarity: EvaluationPolarity
    max_score_delta: float = 0.05

    def __post_init__(self) -> None:
        _clean_text(self.case_id, "case_id", maximum=1024)
        _clean_text(self.clean_input, "clean_input", maximum=1_000_000)
        _clean_text(self.injected_input, "injected_input", maximum=1_000_000)
        if self.clean_input == self.injected_input:
            raise EvaluationError("injected_input must differ from clean_input")
        try:
            polarity = (
                self.expected_polarity
                if isinstance(self.expected_polarity, EvaluationPolarity)
                else EvaluationPolarity(self.expected_polarity)
            )
        except (TypeError, ValueError) as exc:
            raise EvaluationError("invalid adversarial expected_polarity") from exc
        object.__setattr__(self, "expected_polarity", polarity)
        object.__setattr__(
            self,
            "max_score_delta",
            _probability(self.max_score_delta, "max_score_delta"),
        )


@dataclass(frozen=True, slots=True)
class AdversarialInjectionResult:
    case_id: str
    clean_score: float | None
    injected_score: float | None
    passed: bool
    reason: str

    def __post_init__(self) -> None:
        _clean_text(self.case_id, "case_id", maximum=1024)
        if type(self.passed) is not bool:
            raise EvaluationError("adversarial result passed must be boolean")
        _clean_text(self.reason, "adversarial result reason", maximum=1024)
        if (self.clean_score is None) != (self.injected_score is None):
            raise EvaluationError("adversarial scores must both be present or absent")
        if self.clean_score is not None:
            _probability(self.clean_score, "clean_score")
            _probability(self.injected_score, "injected_score")
        elif self.passed:
            raise EvaluationError("an unscored adversarial result cannot pass")


@dataclass(frozen=True, slots=True)
class AdversarialInjectionReport:
    threshold: float
    results: tuple[AdversarialInjectionResult, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "threshold", _probability(self.threshold, "threshold"))
        results = tuple(self.results)
        if any(not isinstance(item, AdversarialInjectionResult) for item in results):
            raise EvaluationError("adversarial report results are invalid")
        ids = [item.case_id for item in results]
        if len(ids) != len(set(ids)):
            raise EvaluationError("adversarial report case IDs must be unique")
        object.__setattr__(self, "results", results)

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(item.passed for item in self.results)

    @property
    def passed_count(self) -> int:
        return sum(item.passed for item in self.results)


def run_adversarial_injection_tests(
    cases: Sequence[AdversarialInjectionCase],
    score: Callable[[str], float],
    *,
    threshold: float,
) -> AdversarialInjectionReport:
    """Score inert probe strings and require stable, correct classifications."""

    threshold = _probability(threshold, "threshold")
    values = tuple(cases)
    if not values:
        raise EvaluationError("at least one adversarial injection case is required")
    ids = [item.case_id for item in values]
    if len(ids) != len(set(ids)):
        raise EvaluationError("adversarial case IDs must be unique")
    results = []
    for case in values:
        if not isinstance(case, AdversarialInjectionCase):
            raise EvaluationError("adversarial cases are invalid")
        try:
            clean_score = _probability(score(case.clean_input), "clean score")
            injected_score = _probability(score(case.injected_input), "injected score")
        except Exception as exc:  # A scorer failure is a failed gate, not a pass.
            results.append(
                AdversarialInjectionResult(
                    case_id=case.case_id,
                    clean_score=None,
                    injected_score=None,
                    passed=False,
                    reason=f"scorer_error:{type(exc).__name__}",
                )
            )
            continue
        expected = (
            case.expected_polarity is EvaluationPolarity.VULNERABLE_POSITIVE
        )
        labels_correct = (
            (clean_score >= threshold) is expected
            and (injected_score >= threshold) is expected
        )
        stable = abs(clean_score - injected_score) <= case.max_score_delta
        passed = labels_correct and stable
        reason = (
            "passed"
            if passed
            else "classification_changed_or_score_delta_exceeded"
        )
        results.append(
            AdversarialInjectionResult(
                case_id=case.case_id,
                clean_score=clean_score,
                injected_score=injected_score,
                passed=passed,
                reason=reason,
            )
        )
    return AdversarialInjectionReport(threshold=threshold, results=tuple(results))


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    min_validation_samples: int = 2
    min_test_samples: int = 2
    min_adversarial_cases: int = 1
    min_vulnerable_recall: float = 0.80
    min_fixed_negative_accuracy: float = 0.95
    min_precision: float = 0.80
    max_brier_score: float = 0.20
    max_expected_calibration_error: float = 0.15

    def __post_init__(self) -> None:
        for name in (
            "min_validation_samples",
            "min_test_samples",
            "min_adversarial_cases",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise EvaluationError(f"{name} must be a positive integer")
        for name in (
            "min_vulnerable_recall",
            "min_fixed_negative_accuracy",
            "min_precision",
            "max_brier_score",
            "max_expected_calibration_error",
        ):
            _probability(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class PromotionGate:
    name: str
    passed: bool
    observed: int | float | bool
    requirement: str

    def __post_init__(self) -> None:
        _clean_text(self.name, "promotion gate name", maximum=256)
        if type(self.passed) is not bool:
            raise EvaluationError("promotion gate passed must be boolean")
        if isinstance(self.observed, float) and not math.isfinite(self.observed):
            raise EvaluationError("promotion gate observed value must be finite")
        if not isinstance(self.observed, (bool, int, float)):
            raise EvaluationError("promotion gate observed value must be scalar")
        _clean_text(
            self.requirement, "promotion gate requirement", maximum=1024
        )


@dataclass(frozen=True, slots=True)
class PromotionReview:
    """Explicit, non-authoritative release candidate decision."""

    decision: PromotionDecision
    gates: tuple[PromotionGate, ...]
    review_approved: bool
    reviewer_id: str = ""
    candidate_cids: tuple[str, ...] = ()

    grants_execution_authority: ClassVar[bool] = False

    def __post_init__(self) -> None:
        try:
            decision = (
                self.decision
                if isinstance(self.decision, PromotionDecision)
                else PromotionDecision(self.decision)
            )
        except (TypeError, ValueError) as exc:
            raise EvaluationError("invalid promotion decision") from exc
        object.__setattr__(self, "decision", decision)
        gates = tuple(self.gates)
        if not gates or any(not isinstance(item, PromotionGate) for item in gates):
            raise EvaluationError("promotion review requires measured gates")
        object.__setattr__(self, "gates", gates)
        if type(self.review_approved) is not bool:
            raise EvaluationError("review_approved must be boolean")
        if self.review_approved:
            _clean_text(self.reviewer_id, "reviewer_id", maximum=1024)
        elif self.reviewer_id:
            raise EvaluationError("reviewer_id requires review approval")
        candidate_cids = tuple(sorted(self.candidate_cids))
        if len(candidate_cids) != len(set(candidate_cids)):
            raise EvaluationError("candidate_cids must be unique")
        if any(not re.fullmatch(r"b[a-z2-7]{58}", item) for item in candidate_cids):
            raise EvaluationError("candidate_cids must be CIDv1 strings")
        object.__setattr__(self, "candidate_cids", candidate_cids)
        all_passed = all(item.passed for item in gates)
        if decision is PromotionDecision.PROMOTE and (
            not all_passed or not self.review_approved
        ):
            raise EvaluationError(
                "failed or unreviewed gates cannot promote candidates"
            )
        if decision is PromotionDecision.REVIEW_REQUIRED and (
            not all_passed or self.review_approved
        ):
            raise EvaluationError(
                "review_required is only valid for passing, unreviewed gates"
            )
        if decision is PromotionDecision.REJECT and all_passed:
            raise EvaluationError("passing gates must proceed to review or promotion")

    @property
    def can_promote(self) -> bool:
        return (
            self.decision is PromotionDecision.PROMOTE
            and self.review_approved
            and all(item.passed for item in self.gates)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_cids": list(self.candidate_cids),
            "decision": self.decision.value,
            "gates": [
                {
                    "name": item.name,
                    "observed": item.observed,
                    "passed": item.passed,
                    "requirement": item.requirement,
                }
                for item in self.gates
            ],
            "grants_execution_authority": False,
            "review_approved": self.review_approved,
            "reviewer_id": self.reviewer_id,
        }


def decide_promotion(
    test_metrics: MetricsReport,
    threshold: ThresholdMeasurement,
    *,
    leakage_findings: Sequence[LeakageFinding],
    adversarial_report: AdversarialInjectionReport,
    policy: PromotionPolicy | None = None,
    review_approved: bool = False,
    reviewer_id: str = "",
    candidate_cids: Sequence[str] = (),
) -> PromotionReview:
    """Apply every promotion gate and emit reject, review, or promote."""

    if not isinstance(test_metrics, MetricsReport):
        raise EvaluationError("test_metrics must be a MetricsReport")
    if not isinstance(threshold, ThresholdMeasurement):
        raise EvaluationError("threshold must be a measured validation threshold")
    if not isinstance(adversarial_report, AdversarialInjectionReport):
        raise EvaluationError("adversarial_report is invalid")
    policy = policy or PromotionPolicy()
    leakage = tuple(leakage_findings)
    if any(not isinstance(item, LeakageFinding) for item in leakage):
        raise EvaluationError("leakage_findings are invalid")
    if not math.isclose(test_metrics.threshold, threshold.threshold, abs_tol=1e-12):
        raise EvaluationError("test metrics must use the measured threshold")
    if not math.isclose(
        adversarial_report.threshold, threshold.threshold, abs_tol=1e-12
    ):
        raise EvaluationError("adversarial tests must use the measured threshold")

    measured = test_metrics.overall
    gates = (
        PromotionGate(
            "leakage_free", not leakage, len(leakage), "equals 0"
        ),
        PromotionGate(
            "validation_sample_count",
            threshold.validation_sample_count >= policy.min_validation_samples,
            threshold.validation_sample_count,
            f">= {policy.min_validation_samples}",
        ),
        PromotionGate(
            "test_sample_count",
            measured.sample_count >= policy.min_test_samples,
            measured.sample_count,
            f">= {policy.min_test_samples}",
        ),
        PromotionGate(
            "vulnerable_recall",
            measured.vulnerable_recall >= policy.min_vulnerable_recall,
            measured.vulnerable_recall,
            f">= {policy.min_vulnerable_recall}",
        ),
        PromotionGate(
            "fixed_negative_accuracy",
            measured.fixed_negative_accuracy
            >= policy.min_fixed_negative_accuracy,
            measured.fixed_negative_accuracy,
            f">= {policy.min_fixed_negative_accuracy}",
        ),
        PromotionGate(
            "precision",
            measured.precision >= policy.min_precision,
            measured.precision,
            f">= {policy.min_precision}",
        ),
        PromotionGate(
            "brier_score",
            measured.brier_score <= policy.max_brier_score,
            measured.brier_score,
            f"<= {policy.max_brier_score}",
        ),
        PromotionGate(
            "expected_calibration_error",
            test_metrics.expected_calibration_error
            <= policy.max_expected_calibration_error,
            test_metrics.expected_calibration_error,
            f"<= {policy.max_expected_calibration_error}",
        ),
        PromotionGate(
            "adversarial_injection",
            adversarial_report.passed
            and len(adversarial_report.results) >= policy.min_adversarial_cases,
            adversarial_report.passed_count,
            f"{policy.min_adversarial_cases} or more cases, all passing",
        ),
    )
    all_passed = all(item.passed for item in gates)
    decision = (
        PromotionDecision.PROMOTE
        if all_passed and review_approved
        else (
            PromotionDecision.REVIEW_REQUIRED
            if all_passed
            else PromotionDecision.REJECT
        )
    )
    return PromotionReview(
        decision=decision,
        gates=gates,
        review_approved=review_approved,
        reviewer_id=reviewer_id,
        candidate_cids=tuple(candidate_cids),
    )


def build_evaluation_record(
    metrics: MetricsReport,
    promotion: PromotionReview,
    *,
    subject_cids: Sequence[str],
    source_cids: Sequence[str],
    parent_cids: Sequence[str],
    config_cid: str,
) -> Any:
    """Build the canonical non-authoritative schema record for a report."""

    from .schemas import EvaluationRecord

    if not isinstance(metrics, MetricsReport):
        raise EvaluationError("metrics must be MetricsReport")
    if not isinstance(promotion, PromotionReview):
        raise EvaluationError("promotion must be PromotionReview")
    return EvaluationRecord(
        source_cids=tuple(source_cids),
        parent_cids=tuple(parent_cids),
        config_cid=config_cid,
        subject_cids=tuple(subject_cids),
        metrics={
            "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
            "measurements": metrics.to_dict(),
            "promotion_review": promotion.to_dict(),
        },
        payload={
            "authoritative": False,
            "grants_execution_authority": False,
        },
    )


# Readable compatibility names for callers that use "sample" or "calibrate".
EvaluationSample = EvaluationExample
create_leakage_safe_splits = build_leakage_safe_splits
compute_stratified_metrics = evaluate_predictions
calibrate_threshold = measure_threshold
PromotionVerdict = PromotionDecision


__all__ = [
    "AdversarialInjectionCase",
    "AdversarialInjectionReport",
    "AdversarialInjectionResult",
    "BinaryMetrics",
    "CalibrationBin",
    "EVALUATION_CONFIG_SCHEMA_VERSION",
    "EVALUATION_SCHEMA_VERSION",
    "EvaluationError",
    "EvaluationExample",
    "EvaluationPolarity",
    "EvaluationPrediction",
    "EvaluationSample",
    "EvaluationSplit",
    "LeakageFinding",
    "LeakageKind",
    "LeakageSafeSplits",
    "MetricsReport",
    "PromotionDecision",
    "PromotionGate",
    "PromotionPolicy",
    "PromotionReview",
    "PromotionVerdict",
    "SplitConfig",
    "ThresholdMeasurement",
    "audit_split_leakage",
    "body_sha256",
    "build_evaluation_record",
    "build_leakage_safe_splits",
    "calibrate_threshold",
    "compute_stratified_metrics",
    "create_leakage_safe_splits",
    "decide_promotion",
    "evaluate_predictions",
    "measure_threshold",
    "run_adversarial_injection_tests",
]
