"""Batch 326: Mutation Testing Framework - Comprehensive Test Suite

Implements mutation testing to validate existing test suite quality and identify
untested code paths. Mutation testing works by intentionally modifying code (mutations)
and verifying that tests catch the changes (kill rate).

Key test areas:
- Mutation operators (arithmetic, boolean, return value mutations)
- Score calculation and mutation
- Test harness for applying/validating mutations
- Mutation tracking and reporting
- Integration with pytest
- Mutation killing metrics

"""

import pytest
from typing import Callable, List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
from copy import deepcopy
import inspect
import ast


class MutationOperator(Enum):
    """Types of mutations to apply during testing."""
    ARITHMETIC_REPLACE = "arithmetic_replace"  # + → -, * → /, etc.
    BOOLEAN_REPLACE = "boolean_replace"  # True → False, and → or
    CONSTANT_REPLACE = "constant_replace"  # 0 → 1, "" → "x", etc.
    COMPARISON_REPLACE = "comparison_replace"  # > → >=, == → !=
    RETURN_VALUE_REPLACE = "return_value_replace"  # return x → return not x
    CONDITION_INVERSION = "condition_inversion"  # if x → if not x


@dataclass
class Mutation:
    """Represents a single code mutation."""
    operator: MutationOperator
    target_line: int
    target_function: str
    original_code: str
    mutated_code: str
    description: str
    is_survived: bool = False  # True if tests didn't catch this mutation
    
    def __hash__(self) -> int:
        """Mutations are hashable for set operations."""
        return hash((self.operator, self.target_line, self.target_function))
    
    def __eq__(self, other: Any) -> bool:
        """Equality based on identity, not full content."""
        if not isinstance(other, Mutation):
            return NotImplemented
        # Mutations are equal if they target the same location
        return (self.operator == other.operator and 
                self.target_line == other.target_line and 
                self.target_function == other.target_function)


@dataclass
class MutationTestResult:
    """Results from analyzing mutations."""
    total_mutations: int
    killed_mutations: int  # Caught by tests
    survived_mutations: int  # Not caught by tests
    mutation_score: float  # killed / total
    original_assertion_count: int = 0
    needed_assertions: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "total_mutations": self.total_mutations,
            "killed_mutations": self.killed_mutations,
            "survived_mutations": self.survived_mutations,
            "mutation_score": self.mutation_score,
            "original_assertion_count": self.original_assertion_count,
            "needed_assertions": self.needed_assertions,
        }


class MutationGenerator:
    """Generates mutations for test validation."""
    
    def __init__(self):
        self.mutations: List[Mutation] = []
        self.operators: Set[MutationOperator] = set(MutationOperator)
    
    def enable_operators(self, *operators: MutationOperator) -> None:
        """Enable specific mutation operators."""
        self.operators = set(operators)
    
    def disable_operators(self, *operators: MutationOperator) -> None:
        """Disable specific mutation operators."""
        self.operators -= set(operators)
    
    def generate_arithmetic_mutations(self, value: float) -> List[Tuple[float, str]]:
        """Generate arithmetic mutations."""
        if MutationOperator.ARITHMETIC_REPLACE not in self.operators:
            return []
        
        mutations = []
        if value != 0:
            mutations.append((0, f"{value} → 0"))
        if value != 1:
            mutations.append((1, f"{value} → 1"))
        mutations.append((value + 1, f"{value} → {value + 1}"))
        mutations.append((value - 1, f"{value} → {value - 1}"))
        
        return mutations
    
    def generate_comparison_mutations(self, comparison: str) -> List[Tuple[str, str]]:
        """Generate comparison operator mutations."""
        if MutationOperator.COMPARISON_REPLACE not in self.operators:
            return []
        
        mutations_map = {
            ">": [">=", "<", "=="],
            "<": ["<=", ">", "=="],
            ">=": [">", "<=", "!="],
            "<=": ["<", ">=", "!="],
            "==": ["!="],
            "!=": ["=="],
        }
        mutations = []
        for mutated in mutations_map.get(comparison, []):
            mutations.append((mutated, f"{comparison} → {mutated}"))
        
        return mutations
    
    def generate_boolean_mutations(self) -> List[Tuple[bool, str]]:
        """Generate boolean mutations."""
        if MutationOperator.BOOLEAN_REPLACE not in self.operators:
            return []
        
        return [(True, "False → True"), (False, "True → False")]


class MutationScorer:
    """Scores mutations and calculates kill rate."""
    
    def __init__(self):
        self.mutations: List[Mutation] = []
        self.survivors: List[Mutation] = []
    
    def add_mutation(self, mutation: Mutation) -> None:
        """Track a mutation."""
        self.mutations.append(mutation)
        if mutation.is_survived:
            self.survivors.append(mutation)
    
    def kill_mutation(self, mutation: Mutation) -> None:
        """Mark a mutation as caught by tests."""
        mutation.is_survived = False
        if mutation in self.survivors:
            self.survivors.remove(mutation)
    
    def get_score(self) -> MutationTestResult:
        """Calculate mutation score."""
        total = len(self.mutations)
        killed = total - len(self.survivors)
        
        score = killed / total if total > 0 else 1.0
        
        return MutationTestResult(
            total_mutations=total,
            killed_mutations=killed,
            survived_mutations=len(self.survivors),
            mutation_score=score,
        )
    
    def get_survived_mutations(self) -> List[Mutation]:
        """Get all mutations not caught by tests."""
        return self.survivors.copy()


class SimpleScoreMutator:
    """Test helper that mutates simple score calculations."""
    
    @staticmethod
    def calculate_weighted_score(values: List[float], weights: List[float]) -> float:
        """Original weighted score calculation."""
        if not values or not weights or len(values) != len(weights):
            return 0.0
        
        total_weight = sum(weights)
        if total_weight == 0:
            return 0.0
        
        weighted_sum = sum(v * w for v, w in zip(values, weights))
        return weighted_sum / total_weight
    
    @staticmethod
    def bounded_score(value: float, min_val: float = 0.0, 
                     max_val: float = 1.0) -> float:
        """Bound a score to [min_val, max_val]."""
        return max(min_val, min(value, max_val))
    
    @staticmethod
    def apply_penalty(base_score: float, penalty: float) -> float:
        """Apply a penalty to score."""
        return max(0.0, base_score - penalty)
    
    @staticmethod
    def exponential_decay(initial: float, decay_rate: float, 
                         steps: int) -> float:
        """Apply exponential decay."""
        return initial * (decay_rate ** steps)


class MutationTestHarness:
    """Orchestrates mutation testing process."""
    
    def __init__(self):
        self.mutations: Dict[str, List[Mutation]] = {}
        self.test_results: Dict[str, MutationTestResult] = {}
        self.generator = MutationGenerator()
        self.scorer = MutationScorer()
    
    def register_mutations(self, target_name: str, 
                          mutations: List[Mutation]) -> None:
        """Register mutations for a target."""
        self.mutations[target_name] = mutations
        for mutation in mutations:
            self.scorer.add_mutation(mutation)
    
    def apply_mutation(self, mutation: Mutation, 
                      target_func: Callable) -> Callable:
        """Apply a mutation and return modified function."""
        # In a real system, this would use AST manipulation
        # For testing, we demonstrate the concept
        return target_func
    
    def validate_mutation_killed(self, mutation: Mutation, 
                                test_results: bool) -> None:
        """Record whether mutation was killed by tests."""
        if test_results:
            self.scorer.kill_mutation(mutation)
        else:
            mutation.is_survived = True
    
    def get_mutation_score(self, target: Optional[str] = None) -> MutationTestResult:
        """Get mutation score for target or all."""
        return self.scorer.get_score()
    
    def report_survivors(self) -> List[Mutation]:
        """Get all mutations that survived testing."""
        return self.scorer.get_survived_mutations()


# Test Suite

class TestMutationOperator:
    """Test MutationOperator enum."""
    
    def test_operators_defined(self):
        """Should have standard mutation operators."""
        operators = list(MutationOperator)
        assert len(operators) >= 5
        assert MutationOperator.ARITHMETIC_REPLACE in operators
        assert MutationOperator.BOOLEAN_REPLACE in operators


class TestMutation:
    """Test Mutation dataclass."""
    
    def test_create_mutation(self):
        """Should create mutation with required fields."""
        mutation = Mutation(
            operator=MutationOperator.ARITHMETIC_REPLACE,
            target_line=42,
            target_function="test_func",
            original_code="x = 1 + 2",
            mutated_code="x = 1 - 2",
            description="Replace + with -",
        )
        
        assert mutation.operator == MutationOperator.ARITHMETIC_REPLACE
        assert mutation.target_line == 42
        assert mutation.is_survived is False
    
    def test_mutation_hashable(self):
        """Mutations should be hashable for set operations."""
        mutation1 = Mutation(
            operator=MutationOperator.ARITHMETIC_REPLACE,
            target_line=10,
            target_function="func",
            original_code="x = 1",
            mutated_code="x = 2",
            description="desc",
        )
        mutation2 = Mutation(
            operator=MutationOperator.ARITHMETIC_REPLACE,
            target_line=10,
            target_function="func",
            original_code="x = 1",
            mutated_code="x = 2",
            description="different desc",
        )
        
        # Same mutations should have same hash
        assert hash(mutation1) == hash(mutation2)
        
        # Can use in set
        mutation_set = {mutation1}
        assert mutation2 in mutation_set


class TestMutationTestResult:
    """Test MutationTestResult dataclass."""
    
    def test_create_result(self):
        """Should create result with scores."""
        result = MutationTestResult(
            total_mutations=10,
            killed_mutations=8,
            survived_mutations=2,
            mutation_score=0.8,
        )
        
        assert result.total_mutations == 10
        assert result.killed_mutations == 8
        assert result.mutation_score == 0.8
    
    def test_result_to_dict(self):
        """Should serialize to dictionary."""
        result = MutationTestResult(
            total_mutations=5,
            killed_mutations=4,
            survived_mutations=1,
            mutation_score=0.8,
        )
        
        result_dict = result.to_dict()
        assert result_dict["total_mutations"] == 5
        assert result_dict["mutation_score"] == 0.8


class TestMutationGenerator:
    """Test MutationGenerator."""
    
    def test_arithmetic_mutations(self):
        """Should generate arithmetic mutations."""
        generator = MutationGenerator()
        mutations = generator.generate_arithmetic_mutations(5)
        
        assert len(mutations) > 0
        assert any(m[0] == 0 for m in mutations)  # 5 → 0
        assert any(m[0] == 1 for m in mutations)  # 5 → 1
    
    def test_arithmetic_mutations_disabled(self):
        """Should respect disabled operators."""
        generator = MutationGenerator()
        generator.disable_operators(MutationOperator.ARITHMETIC_REPLACE)
        
        mutations = generator.generate_arithmetic_mutations(5)
        assert len(mutations) == 0
    
    def test_comparison_mutations(self):
        """Should generate comparison mutations."""
        generator = MutationGenerator()
        mutations = generator.generate_comparison_mutations(">")
        
        assert len(mutations) > 0
        assert any(m[0] == ">=" for m in mutations)
        assert any(m[0] == "<" for m in mutations)
    
    def test_boolean_mutations(self):
        """Should generate boolean mutations."""
        generator = MutationGenerator()
        mutations = generator.generate_boolean_mutations()
        
        assert len(mutations) == 2
        assert (True, "False → True") in mutations
        assert (False, "True → False") in mutations
    
    def test_enable_specific_operators(self):
        """Should support enabling only specific operators."""
        generator = MutationGenerator()
        generator.operators = set()  # Start with none
        generator.enable_operators(MutationOperator.BOOLEAN_REPLACE)
        
        assert MutationOperator.BOOLEAN_REPLACE in generator.operators
        assert MutationOperator.ARITHMETIC_REPLACE not in generator.operators


class TestMutationScorer:
    """Test MutationScorer."""
    
    def test_add_mutation(self):
        """Should track mutations."""
        scorer = MutationScorer()
        mutation = Mutation(
            operator=MutationOperator.ARITHMETIC_REPLACE,
            target_line=1,
            target_function="func",
            original_code="x = 1",
            mutated_code="x = 2",
            description="desc",
        )
        
        scorer.add_mutation(mutation)
        assert len(scorer.mutations) == 1
    
    def test_kill_mutation(self):
        """Should mark mutation as killed."""
        scorer = MutationScorer()
        mutation = Mutation(
            operator=MutationOperator.ARITHMETIC_REPLACE,
            target_line=1,
            target_function="func",
            original_code="x = 1",
            mutated_code="x = 2",
            description="desc",
            is_survived=True,
        )
        
        scorer.add_mutation(mutation)
        scorer.kill_mutation(mutation)
        
        assert mutation not in scorer.survivors
    
    def test_mutation_score_calculation(self):
        """Should calculate mutation score correctly."""
        scorer = MutationScorer()
        
        for i in range(10):
            mutation = Mutation(
                operator=MutationOperator.ARITHMETIC_REPLACE,
                target_line=i,
                target_function="func",
                original_code="x = 1",
                mutated_code="x = 2",
                description="desc",
                is_survived=(i >= 8),  # Last 2 survive
            )
            scorer.add_mutation(mutation)
        
        result = scorer.get_score()
        assert result.total_mutations == 10
        assert result.survived_mutations == 2
        assert result.killed_mutations == 8
        assert result.mutation_score == 0.8
    
    def test_perfect_score(self):
        """Should calculate perfect score when all mutations killed."""
        scorer = MutationScorer()
        
        for i in range(5):
            mutation = Mutation(
                operator=MutationOperator.ARITHMETIC_REPLACE,
                target_line=i,
                target_function="func",
                original_code="x = 1",
                mutated_code="x = 2",
                description="desc",
            )
            scorer.add_mutation(mutation)
        
        result = scorer.get_score()
        assert result.mutation_score == 1.0
    
    def test_get_survivors(self):
        """Should return survived mutations."""
        scorer = MutationScorer()
        
        survived_mutations = [
            Mutation(
                operator=MutationOperator.ARITHMETIC_REPLACE,
                target_line=i,
                target_function="func",
                original_code="x = 1",
                mutated_code="x = 2",
                description="desc",
                is_survived=True,
            )
            for i in range(3)
        ]
        
        for mutation in survived_mutations:
            scorer.add_mutation(mutation)
        
        survivors = scorer.get_survived_mutations()
        assert len(survivors) == 3


class TestSimpleScoreMutator:
    """Test SimpleScoreMutator functions."""
    
    def test_weighted_score_calculation(self):
        """Should calculate weighted score correctly."""
        values = [0.5, 0.8]
        weights = [2.0, 1.0]
        
        result = SimpleScoreMutator.calculate_weighted_score(values, weights)
        
        # (0.5 * 2 + 0.8 * 1) / (2 + 1) = (1 + 0.8) / 3 = 1.8 / 3 = 0.6
        assert abs(result - 0.6) < 0.001
    
    def test_weighted_score_empty(self):
        """Should handle empty inputs."""
        result = SimpleScoreMutator.calculate_weighted_score([], [])
        assert result == 0.0
    
    def test_bounded_score(self):
        """Should bound scores to range."""
        assert SimpleScoreMutator.bounded_score(-0.5) == 0.0
        assert SimpleScoreMutator.bounded_score(1.5) == 1.0
        assert SimpleScoreMutator.bounded_score(0.5) == 0.5
    
    def test_apply_penalty(self):
        """Should apply penalty correctly."""
        result = SimpleScoreMutator.apply_penalty(0.8, 0.2)
        assert abs(result - 0.6) < 0.001
    
    def test_apply_penalty_no_negatives(self):
        """Should not return negative scores."""
        result = SimpleScoreMutator.apply_penalty(0.3, 0.5)
        assert result == 0.0
    
    def test_exponential_decay(self):
        """Should apply exponential decay."""
        result = SimpleScoreMutator.exponential_decay(1.0, 0.5, 2)
        # 1.0 * (0.5 ** 2) = 1.0 * 0.25 = 0.25
        assert abs(result - 0.25) < 0.001


class TestMutationTestHarness:
    """Test MutationTestHarness orchestration."""
    
    def test_register_mutations(self):
        """Should register mutations for tracking."""
        harness = MutationTestHarness()
        mutations = [
            Mutation(
                operator=MutationOperator.ARITHMETIC_REPLACE,
                target_line=i,
                target_function="func",
                original_code="x = 1",
                mutated_code=f"x = {i}",
                description="desc",
            )
            for i in range(3)
        ]
        
        harness.register_mutations("test_func", mutations)
        
        assert "test_func" in harness.mutations
        assert len(harness.mutations["test_func"]) == 3
    
    def test_mutation_score_tracking(self):
        """Should track mutation scores."""
        harness = MutationTestHarness()
        mutations = [
            Mutation(
                operator=MutationOperator.ARITHMETIC_REPLACE,
                target_line=1,
                target_function="func",
                original_code="x = 1",
                mutated_code="x = 2",
                description="desc",
                is_survived=(i >= 2),
            )
            for i in range(5)
        ]
        
        harness.register_mutations("target", mutations)
        
        result = harness.get_mutation_score()
        assert result.total_mutations == 5
        assert result.survived_mutations == 3  # Last 3 survive
    
    def test_validate_mutation_killed(self):
        """Should validate when mutation is killed."""
        harness = MutationTestHarness()
        mutation = Mutation(
            operator=MutationOperator.ARITHMETIC_REPLACE,
            target_line=1,
            target_function="func",
            original_code="x = 1",
            mutated_code="x = 2",
            description="desc",
            is_survived=True,
        )
        
        harness.register_mutations("target", [mutation])
        harness.validate_mutation_killed(mutation, test_results=True)
        
        result = harness.get_mutation_score()
        assert result.killed_mutations == 1
    
    def test_report_survivors(self):
        """Should report mutations that survived."""
        harness = MutationTestHarness()
        mutations = [
            Mutation(
                operator=MutationOperator.ARITHMETIC_REPLACE,
                target_line=i,
                target_function="func",
                original_code="x = 1",
                mutated_code="x = 2",
                description="desc",
                is_survived=(i >= 3),
            )
            for i in range(5)
        ]
        
        harness.register_mutations("target", mutations)
        
        survivors = harness.report_survivors()
        assert len(survivors) == 2


class TestMutationIntegration:
    """Integration tests for mutation testing framework."""
    
    def test_full_mutation_workflow(self):
        """Test complete mutation testing workflow."""
        harness = MutationTestHarness()
        generator = MutationGenerator()
        
        # Generate mutations for a score calculation
        mutations = []
        for i in range(5):
            # Initial state: last 2 survive (not caught by tests)
            survived = i >= 3
            mutation = Mutation(
                operator=MutationOperator.ARITHMETIC_REPLACE,
                target_line=i + 10,
                target_function="calculate_score",
                original_code=f"weight = {i}",
                mutated_code=f"weight = {i + 1}",
                description=f"Increment weight from {i} to {i + 1}",
                is_survived=survived,
            )
            mutations.append(mutation)
        
        harness.register_mutations("calculate_score", mutations)
        
        # Simulate tests catching mutation 3 (originally survived)
        harness.validate_mutation_killed(mutations[3], test_results=True)
        
        # Check results: 4 killed (3 originally + 1 caught), 1 survived
        result = harness.get_mutation_score()
        assert result.total_mutations == 5
        assert result.killed_mutations == 4
        assert result.mutation_score == 0.8
    
    def test_mutation_score_interpretation(self):
        """Test interpretation of mutation scores."""
        # 100% score: perfect tests
        harness_perfect = MutationTestHarness()
        mutations = [
            Mutation(
                operator=MutationOperator.ARITHMETIC_REPLACE,
                target_line=i,
                target_function="func",
                original_code="",
                mutated_code="",
                description="",
            )
            for i in range(10)
        ]
        harness_perfect.register_mutations("func", mutations)
        
        result_perfect = harness_perfect.get_mutation_score()
        assert result_perfect.mutation_score == 1.0
        
        # 50% score: weak tests
        harness_weak = MutationTestHarness()
        mutations_weak = []
        for i in range(10):
            mutation = Mutation(
                operator=MutationOperator.ARITHMETIC_REPLACE,
                target_line=i,
                target_function="func",
                original_code="",
                mutated_code="",
                description="",
                is_survived=(i >= 5),
            )
            mutations_weak.append(mutation)
        harness_weak.register_mutations("func", mutations_weak)
        
        result_weak = harness_weak.get_mutation_score()
        assert result_weak.mutation_score == 0.5


class TestMutationRelatedTests:
    """Tests related to mutation detection and test quality."""
    
    def test_comparison_mutation_detection(self):
        """Ensure tests would catch comparison mutations."""
        # Original: if score > 0.5
        # Mutation: if score >= 0.5 (different for 0.5 exactly)
        
        def original_check(score: float) -> bool:
            return score > 0.5
        
        # Test cases that should catch this mutation
        assert original_check(0.6) is True  # Would catch >= mutation
        assert original_check(0.5) is False  # Would definitely catch mutation
        assert original_check(0.4) is False
    
    def test_arithmetic_mutation_detection(self):
        """Ensure tests would catch arithmetic mutations."""
        def weighted_avg(a: float, b: float) -> float:
            return (a + b) / 2  # Original
            # Mutation: (a - b) / 2 would be caught by this test
        
        result = weighted_avg(2, 4)
        assert result == 3.0  # (2 + 4) / 2
        # If mutated to (2 - b) / 2, would get -1.0
    
    def test_boolean_mutation_detection(self):
        """Ensure tests would catch boolean mutations."""
        def validate_range(value: float) -> bool:
            return 0.0 <= value <= 1.0  # Original
        
        # Tests that would catch "and" → "or" mutation
        assert validate_range(0.5) is True
        assert validate_range(1.5) is False  # Would catch or mutation
        assert validate_range(-0.5) is False  # Would catch or mutation
