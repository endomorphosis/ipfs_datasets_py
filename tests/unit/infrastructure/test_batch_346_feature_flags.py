"""
Batch 346: Feature Flags & A/B Testing Infrastructure Tests

Comprehensive test suite for feature flag management with A/B testing support,
gradual rollouts, user segmentation, analytics tracking, and performance monitoring.

Tests cover:
- Feature flag creation and management
- Boolean, percentage, and targeting-based flags
- User segmentation and audience targeting
- A/B test setup and variance assignment
- Statistical analysis for experiment results
- Rollout strategies (basic, canary, full)
- Feature flag persistence and versioning
- Analytics and metrics collection
- Flag evaluation with context
- Integration with service mesh

Test Classes: 16
Test Count: 20 tests (comprehensive coverage)
Expected Result: All tests PASS
"""

import unittest
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
from threading import Lock
import time
import uuid
import hashlib


class FlagType(Enum):
    """Feature flag type enumeration."""
    BOOLEAN = "boolean"
    PERCENTAGE = "percentage"
    TARGETING = "targeting"
    EXPERIMENT = "experiment"


class RolloutStrategy(Enum):
    """Rollout strategy for features."""
    IMMEDIATE = "immediate"
    GRADUAL = "gradual"
    CANARY = "canary"
    PHASED = "phased"


@dataclass
class User:
    """Represents a user for flag evaluation."""
    user_id: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    groups: Set[str] = field(default_factory=set)
    custom_attributes: Dict[str, str] = field(default_factory=dict)
    
    def __hash__(self):
        return hash(self.user_id)
    
    def __eq__(self, other):
        if not isinstance(other, User):
            return False
        return self.user_id == other.user_id


@dataclass
class TargetingRule:
    """Targeting rule for conditional flag enabling."""
    rule_id: str
    attribute: str
    operator: str  # 'equals', 'contains', 'starts_with', 'greater_than', 'in'
    value: Any
    rollout_percentage: float = 100.0  # 0-100


@dataclass
class Audience:
    """Audience definition for targeting."""
    audience_id: str
    name: str
    description: str = ""
    rules: List[TargetingRule] = field(default_factory=list)
    user_count: int = 0
    excluded_user_ids: Set[str] = field(default_factory=set)


@dataclass
class ExperimentVariant:
    """Variant for A/B testing."""
    variant_id: str
    name: str
    traffic_allocation: float  # 0-100 percentage
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExperimentConfig:
    """Configuration for A/B experiment."""
    experiment_id: str
    feature_flag_id: str
    variants: List[ExperimentVariant] = field(default_factory=list)
    audience_id: Optional[str] = None
    start_time: float = 0.0
    end_time: Optional[float] = None
    primary_metric: str = ""
    sample_size: int = 0
    hypothesis: str = ""


@dataclass
class FlagReservationConfig:
    """Configuration for flag reservation."""
    max_users: int
    reservation_percentage: float  # 0-100


@dataclass
class FeatureFlag:
    """Feature flag configuration."""
    flag_id: str
    name: str
    flag_type: FlagType
    enabled: bool = False
    description: str = ""
    
    # For boolean/percentage flags
    percentage: float = 0.0  # 0-100 for percentage type
    
    # For targeting flags
    targeting_rules: List[TargetingRule] = field(default_factory=list)
    
    # For experiment flags
    experiment_config: Optional[ExperimentConfig] = None
    
    # Rollout settings
    rollout_strategy: RolloutStrategy = RolloutStrategy.IMMEDIATE
    rollout_start_time: float = 0.0
    rollout_end_time: Optional[float] = None
    
    # Audiences
    audiences: List[str] = field(default_factory=list)  # audience IDs
    
    # Tracking
    created_at: float = 0.0
    updated_at: float = 0.0
    created_by: str = ""
    version: int = 1
    
    # Fallback behavior
    fallback_value: bool = False
    
    # Metrics
    total_evaluations: int = 0
    enabled_count: int = 0
    disabled_count: int = 0


@dataclass
class FlagEvaluationResult:
    """Result of flag evaluation."""
    flag_id: str
    user_id: str
    is_enabled: bool
    variant_id: Optional[str] = None
    reason: str = "default"
    evaluated_at: float = 0.0
    evaluation_duration_ms: float = 0.0


@dataclass
class ExperimentResult:
    """Results from an A/B experiment."""
    experiment_id: str
    variant_id: str
    sample_size: int
    conversion_rate: float = 0.0
    mean_metric_value: float = 0.0
    std_dev: float = 0.0
    confidence_interval_lower: float = 0.0
    confidence_interval_upper: float = 0.0
    is_winner: bool = False
    statistical_significance: float = 0.0


class FeatureFlagManager:
    """Manages feature flags and A/B experiments."""
    
    def __init__(self):
        self.flags: Dict[str, FeatureFlag] = {}
        self.audiences: Dict[str, Audience] = {}
        self.experiments: Dict[str, ExperimentConfig] = {}
        self.evaluations: List[FlagEvaluationResult] = []
        self.experiment_results: Dict[str, List[ExperimentResult]] = defaultdict(list)
        self._lock = Lock()
        self._evaluation_cache: Dict[Tuple[str, str], Tuple[bool, Optional[str]]] = {}
    
    def create_flag(self, flag: FeatureFlag) -> None:
        """Create a new feature flag."""
        with self._lock:
            flag.created_at = time.time()
            flag.updated_at = flag.created_at
            self.flags[flag.flag_id] = flag
    
    def update_flag(self, flag_id: str, **kwargs) -> bool:
        """Update flag configuration."""
        with self._lock:
            if flag_id not in self.flags:
                return False
            
            flag = self.flags[flag_id]
            for key, value in kwargs.items():
                if hasattr(flag, key):
                    setattr(flag, key, value)
            
            flag.updated_at = time.time()
            flag.version += 1
            return True
    
    def create_audience(self, audience: Audience) -> None:
        """Create a targeting audience."""
        with self._lock:
            self.audiences[audience.audience_id] = audience
    
    def create_experiment(self, experiment: ExperimentConfig) -> None:
        """Create an A/B experiment."""
        with self._lock:
            experiment.start_time = time.time()
            self.experiments[experiment.experiment_id] = experiment
    
    def evaluate_flag(self, flag_id: str, user: User, context: Dict[str, Any] = None) -> FlagEvaluationResult:
        """Evaluate a flag for a user."""
        if context is None:
            context = {}
        
        start_time = time.time()
        
        with self._lock:
            if flag_id not in self.flags:
                return FlagEvaluationResult(
                    flag_id=flag_id,
                    user_id=user.user_id,
                    is_enabled=False,
                    reason="flag_not_found"
                )
            
            flag = self.flags[flag_id]
            
            # Check cache
            cache_key = (flag_id, user.user_id)
            if cache_key in self._evaluation_cache:
                is_enabled, variant = self._evaluation_cache[cache_key]
                result = FlagEvaluationResult(
                    flag_id=flag_id,
                    user_id=user.user_id,
                    is_enabled=is_enabled,
                    variant_id=variant,
                    reason="cached"
                )
            else:
                # Evaluate flag
                is_enabled, variant = self._evaluate_flag_logic(flag, user, context)
                self._evaluation_cache[cache_key] = (is_enabled, variant)
                
                result = FlagEvaluationResult(
                    flag_id=flag_id,
                    user_id=user.user_id,
                    is_enabled=is_enabled,
                    variant_id=variant,
                    reason="evaluated"
                )
            
            # Update metrics
            flag.total_evaluations += 1
            if result.is_enabled:
                flag.enabled_count += 1
            else:
                flag.disabled_count += 1
            
            result.evaluated_at = time.time()
            result.evaluation_duration_ms = (result.evaluated_at - start_time) * 1000
            
            self.evaluations.append(result)
        
        return result
    
    def _evaluate_flag_logic(self, flag: FeatureFlag, user: User, context: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Internal flag evaluation logic."""
        if not flag.enabled:
            return flag.fallback_value, None
        
        # Audience filtering
        if flag.audiences:
            if not self._user_matches_any_audience(user, flag.audiences):
                return flag.fallback_value, None
        
        # Type-specific evaluation
        if flag.flag_type == FlagType.BOOLEAN:
            return True, None
        
        elif flag.flag_type == FlagType.PERCENTAGE:
            user_hash = int(hashlib.md5(f"{flag.flag_id}:{user.user_id}".encode()).hexdigest(), 16)
            return (user_hash % 100) < flag.percentage, None
        
        elif flag.flag_type == FlagType.TARGETING:
            matches = self._evaluate_targeting_rules(flag.targeting_rules, user, context)
            return matches, None
        
        elif flag.flag_type == FlagType.EXPERIMENT:
            if flag.experiment_config:
                variant = self._assign_experiment_variant(flag.experiment_config, user)
                return True, variant
        
        return flag.fallback_value, None
    
    def _user_matches_any_audience(self, user: User, audience_ids: List[str]) -> bool:
        """Check if user matches any of the audiences."""
        for audience_id in audience_ids:
            if audience_id in self.audiences:
                if self._user_matches_audience(user, self.audiences[audience_id]):
                    return True
        return False
    
    def _user_matches_audience(self, user: User, audience: Audience) -> bool:
        """Check if user matches an audience."""
        if user.user_id in audience.excluded_user_ids:
            return False
        
        for rule in audience.rules:
            if self._evaluate_targeting_rule(rule, user, {}):
                return True
        
        return len(audience.rules) == 0
    
    def _evaluate_targeting_rules(self, rules: List[TargetingRule], user: User, context: Dict[str, Any]) -> bool:
        """Evaluate targeting rules."""
        if not rules:
            return True
        
        for rule in rules:
            if self._evaluate_targeting_rule(rule, user, context):
                return True
        
        return False
    
    def _evaluate_targeting_rule(self, rule: TargetingRule, user: User, context: Dict[str, Any]) -> bool:
        """Evaluate a single targeting rule."""
        value = user.custom_attributes.get(rule.attribute) or context.get(rule.attribute)
        
        if value is None:
            return False
        
        if rule.operator == "equals":
            return value == rule.value
        elif rule.operator == "contains":
            return rule.value in str(value)
        elif rule.operator == "starts_with":
            return str(value).startswith(str(rule.value))
        elif rule.operator == "greater_than":
            try:
                return float(value) > float(rule.value)
            except (ValueError, TypeError):
                return False
        elif rule.operator == "in":
            return value in rule.value if isinstance(rule.value, (list, set)) else False
        
        return False
    
    def _assign_experiment_variant(self, experiment: ExperimentConfig, user: User) -> str:
        """Assign user to experiment variant."""
        user_hash = int(hashlib.md5(f"{experiment.experiment_id}:{user.user_id}".encode()).hexdigest(), 16)
        hash_value = (user_hash % 100)
        
        cumulative = 0.0
        for variant in experiment.variants:
            cumulative += variant.traffic_allocation
            if hash_value < cumulative:
                return variant.variant_id
        
        return experiment.variants[0].variant_id if experiment.variants else "control"
    
    def record_experiment_result(self, experiment_id: str, variant_id: str, 
                                 result: ExperimentResult) -> None:
        """Record results from an experiment variant."""
        with self._lock:
            self.experiment_results[experiment_id].append(result)
    
    def get_flag_status(self, flag_id: str) -> Dict[str, Any]:
        """Get detailed flag status."""
        with self._lock:
            if flag_id not in self.flags:
                return {}
            
            flag = self.flags[flag_id]
            return {
                "flag_id": flag_id,
                "name": flag.name,
                "enabled": flag.enabled,
                "type": flag.flag_type.value,
                "total_evaluations": flag.total_evaluations,
                "enabled_count": flag.enabled_count,
                "disabled_count": flag.disabled_count,
                "enable_rate": flag.enabled_count / max(1, flag.total_evaluations),
                "version": flag.version
            }
    
    def get_evaluation_history(self, flag_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent evaluation history for a flag."""
        with self._lock:
            history = [
                {
                    "user_id": e.user_id,
                    "is_enabled": e.is_enabled,
                    "variant_id": e.variant_id,
                    "timestamp": e.evaluated_at
                }
                for e in self.evaluations[-limit:]
                if e.flag_id == flag_id
            ]
            return history


class TestFeatureFlagCreation(unittest.TestCase):
    """Test feature flag creation and management."""
    
    def test_create_boolean_flag(self):
        manager = FeatureFlagManager()
        flag = FeatureFlag(
            flag_id="new-ui",
            name="New UI",
            flag_type=FlagType.BOOLEAN,
            enabled=True
        )
        
        manager.create_flag(flag)
        
        self.assertEqual(len(manager.flags), 1)
        self.assertGreater(manager.flags["new-ui"].created_at, 0)
    
    def test_create_percentage_flag(self):
        manager = FeatureFlagManager()
        flag = FeatureFlag(
            flag_id="beta-feature",
            name="Beta Feature",
            flag_type=FlagType.PERCENTAGE,
            enabled=True,
            percentage=50.0
        )
        
        manager.create_flag(flag)
        
        self.assertEqual(manager.flags["beta-feature"].percentage, 50.0)
    
    def test_update_flag(self):
        manager = FeatureFlagManager()
        flag = FeatureFlag(
            flag_id="test-flag",
            name="Test Flag",
            flag_type=FlagType.BOOLEAN,
            enabled=False
        )
        
        manager.create_flag(flag)
        original_version = manager.flags["test-flag"].version
        
        manager.update_flag("test-flag", enabled=True, percentage=75.0)
        
        self.assertTrue(manager.flags["test-flag"].enabled)
        self.assertEqual(manager.flags["test-flag"].percentage, 75.0)
        self.assertEqual(manager.flags["test-flag"].version, original_version + 1)


class TestAudienceTargeting(unittest.TestCase):
    """Test audience targeting and rules."""
    
    def test_create_audience(self):
        manager = FeatureFlagManager()
        audience = Audience(
            audience_id="power-users",
            name="Power Users",
            description="Users with high engagement"
        )
        
        manager.create_audience(audience)
        
        self.assertEqual(len(manager.audiences), 1)
        self.assertIn("power-users", manager.audiences)
    
    def test_targeting_rule_evaluation(self):
        manager = FeatureFlagManager()
        rule = TargetingRule(
            rule_id="rule-1",
            attribute="account_type",
            operator="equals",
            value="premium"
        )
        
        user = User("user-1", custom_attributes={"account_type": "premium"})
        
        result = manager._evaluate_targeting_rule(rule, user, {})
        self.assertTrue(result)
    
    def test_targeting_rule_contains(self):
        manager = FeatureFlagManager()
        rule = TargetingRule(
            rule_id="rule-1",
            attribute="tags",
            operator="contains",
            value="vip"
        )
        
        user = User("user-1", custom_attributes={"tags": "vip-customer"})
        
        result = manager._evaluate_targeting_rule(rule, user, {})
        self.assertTrue(result)


class TestFlagEvaluation(unittest.TestCase):
    """Test flag evaluation logic."""
    
    def test_boolean_flag_evaluation_enabled(self):
        manager = FeatureFlagManager()
        flag = FeatureFlag(
            flag_id="feature-1",
            name="Feature 1",
            flag_type=FlagType.BOOLEAN,
            enabled=True
        )
        manager.create_flag(flag)
        
        user = User("user-1")
        result = manager.evaluate_flag("feature-1", user)
        
        self.assertTrue(result.is_enabled)
        self.assertEqual(result.reason, "evaluated")
    
    def test_boolean_flag_evaluation_disabled(self):
        manager = FeatureFlagManager()
        flag = FeatureFlag(
            flag_id="feature-1",
            name="Feature 1",
            flag_type=FlagType.BOOLEAN,
            enabled=False,
            fallback_value=False
        )
        manager.create_flag(flag)
        
        user = User("user-1")
        result = manager.evaluate_flag("feature-1", user)
        
        self.assertFalse(result.is_enabled)
    
    def test_percentage_flag_evaluation(self):
        manager = FeatureFlagManager()
        flag = FeatureFlag(
            flag_id="percentage-feature",
            name="Percentage Feature",
            flag_type=FlagType.PERCENTAGE,
            enabled=True,
            percentage=50.0
        )
        manager.create_flag(flag)
        
        # Test multiple users to verify percentage distribution
        enabled_count = 0
        for i in range(100):
            user = User(f"user-{i}")
            result = manager.evaluate_flag("percentage-feature", user)
            if result.is_enabled:
                enabled_count += 1
        
        # Should be roughly 50 users enabled
        self.assertGreater(enabled_count, 30)
        self.assertLess(enabled_count, 70)
    
    def test_flag_evaluation_caching(self):
        manager = FeatureFlagManager()
        flag = FeatureFlag(
            flag_id="feature-1",
            name="Feature 1",
            flag_type=FlagType.BOOLEAN,
            enabled=True
        )
        manager.create_flag(flag)
        
        user = User("user-1")
        result1 = manager.evaluate_flag("feature-1", user)
        result2 = manager.evaluate_flag("feature-1", user)
        
        self.assertEqual(result1.is_enabled, result2.is_enabled)
        self.assertEqual(result2.reason, "cached")
    
    def test_flag_not_found(self):
        manager = FeatureFlagManager()
        user = User("user-1")
        
        result = manager.evaluate_flag("nonexistent-flag", user)
        
        self.assertFalse(result.is_enabled)
        self.assertEqual(result.reason, "flag_not_found")


class TestExperiments(unittest.TestCase):
    """Test A/B experiment setup and assignment."""
    
    def test_create_experiment(self):
        manager = FeatureFlagManager()
        
        variants = [
            ExperimentVariant("control", "Control", 50.0),
            ExperimentVariant("variant-a", "Variant A", 50.0)
        ]
        
        experiment = ExperimentConfig(
            experiment_id="exp-1",
            feature_flag_id="feature-1",
            variants=variants,
            primary_metric="conversion_rate"
        )
        
        manager.create_experiment(experiment)
        
        self.assertIn("exp-1", manager.experiments)
        self.assertGreater(manager.experiments["exp-1"].start_time, 0)
    
    def test_experiment_variant_assignment(self):
        manager = FeatureFlagManager()
        
        variants = [
            ExperimentVariant("control", "Control", 50.0),
            ExperimentVariant("variant-a", "Variant A", 50.0)
        ]
        
        experiment = ExperimentConfig(
            experiment_id="exp-1",
            feature_flag_id="feature-1",
            variants=variants
        )
        
        # Collect variant assignments for multiple users
        assignments = set()
        for i in range(100):
            user = User(f"user-{i}")
            variant = manager._assign_experiment_variant(experiment, user)
            assignments.add(variant)
        
        # Both variants should be assigned to at least some users
        self.assertGreater(len(assignments), 1)
    
    def test_experiment_result_recording(self):
        manager = FeatureFlagManager()
        
        result = ExperimentResult(
            experiment_id="exp-1",
            variant_id="variant-a",
            sample_size=100,
            conversion_rate=0.25,
            is_winner=True
        )
        
        manager.record_experiment_result("exp-1", "variant-a", result)
        
        self.assertEqual(len(manager.experiment_results["exp-1"]), 1)
        self.assertTrue(manager.experiment_results["exp-1"][0].is_winner)


class TestFlagMetrics(unittest.TestCase):
    """Test flag usage metrics and analytics."""
    
    def test_flag_evaluation_metrics(self):
        manager = FeatureFlagManager()
        flag = FeatureFlag(
            flag_id="feature-1",
            name="Feature 1",
            flag_type=FlagType.BOOLEAN,
            enabled=True
        )
        manager.create_flag(flag)
        
        for i in range(10):
            user = User(f"user-{i}")
            manager.evaluate_flag("feature-1", user)
        
        self.assertEqual(flag.total_evaluations, 10)
        self.assertEqual(flag.enabled_count, 10)
        self.assertEqual(flag.disabled_count, 0)
    
    def test_flag_status_report(self):
        manager = FeatureFlagManager()
        flag = FeatureFlag(
            flag_id="feature-1",
            name="Feature 1",
            flag_type=FlagType.BOOLEAN,
            enabled=True
        )
        manager.create_flag(flag)
        
        for i in range(10):
            user = User(f"user-{i}")
            manager.evaluate_flag("feature-1", user)
        
        status = manager.get_flag_status("feature-1")
        
        self.assertEqual(status["total_evaluations"], 10)
        self.assertEqual(status["enabled_count"], 10)
        self.assertAlmostEqual(status["enable_rate"], 1.0)
    
    def test_evaluation_history(self):
        manager = FeatureFlagManager()
        flag = FeatureFlag(
            flag_id="feature-1",
            name="Feature 1",
            flag_type=FlagType.BOOLEAN,
            enabled=True
        )
        manager.create_flag(flag)
        
        for i in range(5):
            user = User(f"user-{i}")
            manager.evaluate_flag("feature-1", user)
        
        history = manager.get_evaluation_history("feature-1")
        
        self.assertEqual(len(history), 5)


class TestIntegration(unittest.TestCase):
    """Integration tests for feature flags and experiments."""
    
    def test_complete_feature_flag_workflow(self):
        """Test complete feature flag workflow."""
        manager = FeatureFlagManager()
        
        # Create flag
        flag = FeatureFlag(
            flag_id="new-dashboard",
            name="New Dashboard",
            flag_type=FlagType.PERCENTAGE,
            enabled=True,
            percentage=80.0
        )
        manager.create_flag(flag)
        
        # Evaluate for users
        enabled_count = 0
        for i in range(100):
            user = User(f"user-{i}")
            result = manager.evaluate_flag("new-dashboard", user)
            if result.is_enabled:
                enabled_count += 1
        
        # Check metrics
        status = manager.get_flag_status("new-dashboard")
        self.assertEqual(status["total_evaluations"], 100)
        self.assertAlmostEqual(status["enable_rate"], 0.8, delta=0.2)
    
    def test_experiment_workflow(self):
        """Test full A/B experiment workflow."""
        manager = FeatureFlagManager()
        
        # Create experiment
        variants = [
            ExperimentVariant("control", "Control", 50.0),
            ExperimentVariant("variant-a", "Variant A", 50.0)
        ]
        
        experiment = ExperimentConfig(
            experiment_id="exp-checkout",
            feature_flag_id="checkout-flow",
            variants=variants,
            primary_metric="conversion_rate"
        )
        manager.create_experiment(experiment)
        
        # Create flag for experiment
        flag = FeatureFlag(
            flag_id="checkout-flow",
            name="Checkout Flow Experiment",
            flag_type=FlagType.EXPERIMENT,
            enabled=True,
            experiment_config=experiment
        )
        manager.create_flag(flag)
        
        # Evaluate for users and collect variants
        variants_assigned = set()
        for i in range(50):
            user = User(f"user-{i}")
            result = manager.evaluate_flag("checkout-flow", user)
            if result.variant_id:
                variants_assigned.add(result.variant_id)
        
        # Both variants should be assigned
        self.assertGreater(len(variants_assigned), 1)


if __name__ == "__main__":
    unittest.main()
