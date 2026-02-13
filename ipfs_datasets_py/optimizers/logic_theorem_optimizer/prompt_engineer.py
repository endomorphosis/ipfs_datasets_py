"""Automated Prompt Engineering using Genetic Algorithms.

This module implements genetic algorithms for automatically evolving and optimizing
prompts for logic extraction. It uses population-based search with selection,
crossover, and mutation operators to discover high-quality prompts.

Key features:
- Genetic algorithm for prompt evolution
- Multiple selection strategies (tournament, roulette wheel)
- Advanced crossover operators (single-point, two-point, uniform)
- Context-aware mutation operators
- Multi-criteria fitness evaluation
- Convergence detection
- Elite preservation
- Generation history tracking

Integration:
- Works with LogicExtractor and PromptOptimizer
- Learns from extraction success rates
- Adapts to different domains and formalisms
"""

from __future__ import annotations

import logging
import random
import hashlib
from typing import Any, Dict, List, Optional, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
import time

logger = logging.getLogger(__name__)


class SelectionMethod(Enum):
    """Methods for selecting parents for crossover."""
    TOURNAMENT = "tournament"  # k-way tournament selection
    ROULETTE_WHEEL = "roulette_wheel"  # Fitness-proportional selection


class CrossoverMethod(Enum):
    """Methods for combining parent prompts."""
    SINGLE_POINT = "single_point"  # Cut at one point
    TWO_POINT = "two_point"  # Cut at two points
    UNIFORM = "uniform"  # Random selection from each parent


class MutationMethod(Enum):
    """Methods for mutating prompts."""
    WORD_SUBSTITUTION = "word_substitution"  # Replace words with synonyms
    PHRASE_INSERTION = "phrase_insertion"  # Insert common phrases
    PHRASE_DELETION = "phrase_deletion"  # Remove phrases
    STRUCTURE_MODIFICATION = "structure_modification"  # Change structure


@dataclass
class EvolutionResult:
    """Result of prompt evolution.
    
    Attributes:
        best_prompt: The best prompt found
        best_fitness: Fitness score of best prompt
        population: Final population of prompts
        generations_run: Number of generations executed
        converged: Whether evolution converged
        history: Evolution history by generation
        total_time: Total evolution time
    """
    best_prompt: str
    best_fitness: float
    population: List[str]
    generations_run: int
    converged: bool
    history: List[Dict[str, Any]] = field(default_factory=list)
    total_time: float = 0.0


class PromptEngineer:
    """Automated prompt engineering using genetic algorithms.
    
    This class implements a genetic algorithm for evolving prompts. It maintains
    a population of prompts and evolves them over generations using selection,
    crossover, and mutation operators.
    
    Attributes:
        population_size: Number of prompts in population
        num_generations: Maximum number of generations
        selection_method: Method for parent selection
        crossover_method: Method for combining parents
        mutation_method: Method for mutating offspring
        mutation_rate: Probability of mutation
        elite_size: Number of top prompts to preserve
        tournament_size: Size for tournament selection
        convergence_threshold: Threshold for convergence detection
    """
    
    def __init__(
        self,
        population_size: int = 20,
        num_generations: int = 10,
        selection_method: SelectionMethod = SelectionMethod.TOURNAMENT,
        crossover_method: CrossoverMethod = CrossoverMethod.TWO_POINT,
        mutation_method: MutationMethod = MutationMethod.WORD_SUBSTITUTION,
        mutation_rate: float = 0.15,
        elite_size: int = 2,
        tournament_size: int = 3,
        convergence_threshold: float = 0.01
    ):
        """Initialize prompt engineer.
        
        Args:
            population_size: Number of prompts in population
            num_generations: Maximum generations to evolve
            selection_method: Parent selection strategy
            crossover_method: Crossover strategy
            mutation_method: Mutation strategy
            mutation_rate: Probability of mutation (0.0-1.0)
            elite_size: Number of best prompts to preserve
            tournament_size: Size for tournament selection
            convergence_threshold: Threshold for detecting convergence
        """
        self.population_size = population_size
        self.num_generations = num_generations
        self.selection_method = selection_method
        self.crossover_method = crossover_method
        self.mutation_method = mutation_method
        self.mutation_rate = mutation_rate
        self.elite_size = elite_size
        self.tournament_size = tournament_size
        self.convergence_threshold = convergence_threshold
        
        # Word substitution vocabulary
        self.synonyms = {
            "extract": ["identify", "find", "detect", "discover", "locate"],
            "logic": ["reasoning", "logical statements", "formal logic", "rules"],
            "text": ["document", "content", "passage", "material"],
            "identify": ["extract", "find", "detect", "discover"],
            "analyze": ["examine", "evaluate", "assess", "investigate"],
            "statement": ["proposition", "assertion", "claim", "declaration"]
        }
        
        # Common phrases for insertion
        self.phrases = [
            "Please ",
            "carefully ",
            "precisely ",
            "from the following ",
            "in the given ",
            "that appear in ",
            "based on ",
            "using formal notation"
        ]
        
    def evolve_prompts(
        self,
        initial_prompts: List[str],
        fitness_function: Callable[[str], float],
        domain: Optional[str] = None,
        convergence_threshold: Optional[float] = None
    ) -> EvolutionResult:
        """Evolve prompts using genetic algorithm.
        
        Args:
            initial_prompts: Seed prompts to start evolution
            fitness_function: Function to evaluate prompt quality (returns 0.0-1.0)
            domain: Optional domain for domain-specific evolution
            convergence_threshold: Override default convergence threshold
        
        Returns:
            EvolutionResult with best prompt and evolution history
        """
        start_time = time.time()
        threshold = convergence_threshold or self.convergence_threshold
        
        # Initialize population
        population = self._initialize_population(initial_prompts)
        history = []
        
        best_prompt = None
        best_fitness = -1.0
        generations_without_improvement = 0
        
        for generation in range(self.num_generations):
            # Evaluate fitness
            fitness_scores = {
                prompt: self._evaluate_fitness(prompt, fitness_function, domain)
                for prompt in population
            }
            
            # Track best
            gen_best_prompt = max(fitness_scores, key=fitness_scores.get)
            gen_best_fitness = fitness_scores[gen_best_prompt]
            
            if gen_best_fitness > best_fitness:
                best_fitness = gen_best_fitness
                best_prompt = gen_best_prompt
                generations_without_improvement = 0
            else:
                generations_without_improvement += 1
            
            # Record generation statistics
            fitnesses = list(fitness_scores.values())
            gen_stats = {
                "generation": generation,
                "best_fitness": gen_best_fitness,
                "avg_fitness": sum(fitnesses) / len(fitnesses),
                "min_fitness": min(fitnesses),
                "max_fitness": max(fitnesses),
                "diversity": self._calculate_diversity(population),
                "best_prompt": gen_best_prompt
            }
            history.append(gen_stats)
            
            logger.info(
                f"Generation {generation}: best={gen_best_fitness:.3f}, "
                f"avg={gen_stats['avg_fitness']:.3f}, "
                f"diversity={gen_stats['diversity']:.3f}"
            )
            
            # Check convergence
            converged = False
            if self._check_convergence(history, threshold):
                logger.info(f"Converged at generation {generation}")
                converged = True
                break
            
            # Check diversity collapse
            if gen_stats["diversity"] < 0.1:
                logger.warning(f"Diversity collapsed at generation {generation}")
                converged = True
                break
            
            # Create next generation
            population = self._create_next_generation(population, fitness_scores)
        
        total_time = time.time() - start_time
        
        return EvolutionResult(
            best_prompt=best_prompt,
            best_fitness=best_fitness,
            population=population,
            generations_run=len(history),
            converged=converged,
            history=history,
            total_time=total_time
        )
    
    def _initialize_population(self, seeds: List[str]) -> List[str]:
        """Initialize population from seed prompts.
        
        Args:
            seeds: Initial seed prompts
        
        Returns:
            List of prompts (population)
        """
        population = list(seeds)
        
        # Generate variants to fill population
        while len(population) < self.population_size:
            # Randomly select a seed and mutate it
            seed = random.choice(seeds)
            variant = self._mutate(seed)
            if variant not in population:
                population.append(variant)
        
        return population[:self.population_size]
    
    def _evaluate_fitness(
        self,
        prompt: str,
        fitness_function: Callable[[str], float],
        domain: Optional[str]
    ) -> float:
        """Evaluate fitness of a prompt.
        
        Args:
            prompt: Prompt to evaluate
            fitness_function: Function to compute base fitness
            domain: Optional domain for domain-specific scoring
        
        Returns:
            Fitness score (0.0-1.0)
        """
        # Base fitness from provided function
        base_fitness = fitness_function(prompt)
        
        # Diversity bonus (encourage novelty)
        diversity_score = len(set(prompt.split())) / max(len(prompt.split()), 1)
        
        # Complexity penalty (prefer simpler prompts)
        complexity_penalty = min(len(prompt) / 200.0, 1.0)  # Penalty for >200 chars
        
        # Domain-specific bonus
        domain_bonus = 0.0
        if domain:
            domain_keywords = {
                "legal": ["law", "legal", "statute", "regulation", "contract"],
                "medical": ["medical", "clinical", "patient", "diagnosis", "treatment"],
                "scientific": ["research", "experiment", "hypothesis", "data", "analysis"]
            }
            if domain in domain_keywords:
                keywords = domain_keywords[domain]
                matches = sum(1 for kw in keywords if kw in prompt.lower())
                domain_bonus = min(matches / len(keywords), 0.2)
        
        # Weighted combination
        fitness = (
            0.5 * base_fitness +
            0.2 * diversity_score +
            0.2 * (1.0 - complexity_penalty) +
            0.1 * domain_bonus
        )
        
        return max(0.0, min(1.0, fitness))
    
    def _calculate_diversity(self, population: List[str]) -> float:
        """Calculate population diversity.
        
        Args:
            population: List of prompts
        
        Returns:
            Diversity score (0.0-1.0)
        """
        if len(population) < 2:
            return 0.0
        
        # Calculate pairwise differences
        differences = []
        for i in range(len(population)):
            for j in range(i + 1, len(population)):
                # Simple character-level difference
                p1, p2 = population[i], population[j]
                diff = sum(c1 != c2 for c1, c2 in zip(p1, p2))
                diff += abs(len(p1) - len(p2))
                max_len = max(len(p1), len(p2))
                if max_len > 0:
                    differences.append(diff / max_len)
        
        return sum(differences) / len(differences) if differences else 0.0
    
    def _check_convergence(
        self,
        history: List[Dict[str, Any]],
        threshold: float
    ) -> bool:
        """Check if evolution has converged.
        
        Args:
            history: Evolution history
            threshold: Convergence threshold
        
        Returns:
            True if converged
        """
        if len(history) < 3:
            return False
        
        # Check fitness plateau
        recent_best = [h["best_fitness"] for h in history[-3:]]
        fitness_change = max(recent_best) - min(recent_best)
        
        return fitness_change < threshold
    
    def _create_next_generation(
        self,
        population: List[str],
        fitness_scores: Dict[str, float]
    ) -> List[str]:
        """Create next generation using selection, crossover, and mutation.
        
        Args:
            population: Current population
            fitness_scores: Fitness score for each prompt
        
        Returns:
            Next generation population
        """
        next_gen = []
        
        # Elitism: preserve best prompts
        sorted_pop = sorted(population, key=lambda p: fitness_scores[p], reverse=True)
        next_gen.extend(sorted_pop[:self.elite_size])
        
        # Generate offspring
        while len(next_gen) < self.population_size:
            # Selection
            parent1 = self._select_parent(population, fitness_scores)
            parent2 = self._select_parent(population, fitness_scores)
            
            # Crossover
            offspring = self._crossover(parent1, parent2)
            
            # Mutation
            if random.random() < self.mutation_rate:
                offspring = self._mutate(offspring)
            
            # Add to next generation if unique
            if offspring not in next_gen:
                next_gen.append(offspring)
        
        return next_gen[:self.population_size]
    
    def _select_parent(
        self,
        population: List[str],
        fitness_scores: Dict[str, float]
    ) -> str:
        """Select a parent for reproduction.
        
        Args:
            population: Current population
            fitness_scores: Fitness scores
        
        Returns:
            Selected parent prompt
        """
        if self.selection_method == SelectionMethod.TOURNAMENT:
            # Tournament selection
            tournament = random.sample(population, min(self.tournament_size, len(population)))
            return max(tournament, key=lambda p: fitness_scores[p])
        
        elif self.selection_method == SelectionMethod.ROULETTE_WHEEL:
            # Roulette wheel (fitness-proportional) selection
            total_fitness = sum(fitness_scores.values())
            if total_fitness == 0:
                return random.choice(population)
            
            pick = random.uniform(0, total_fitness)
            current = 0
            for prompt in population:
                current += fitness_scores[prompt]
                if current >= pick:
                    return prompt
            return population[-1]  # Fallback
        
        return random.choice(population)
    
    def _crossover(self, parent1: str, parent2: str) -> str:
        """Perform crossover between two parents.
        
        Args:
            parent1: First parent prompt
            parent2: Second parent prompt
        
        Returns:
            Offspring prompt
        """
        words1 = parent1.split()
        words2 = parent2.split()
        
        if not words1 or not words2:
            return parent1 if words1 else parent2
        
        if self.crossover_method == CrossoverMethod.SINGLE_POINT:
            # Single-point crossover
            point = random.randint(1, min(len(words1), len(words2)) - 1)
            offspring = words1[:point] + words2[point:]
        
        elif self.crossover_method == CrossoverMethod.TWO_POINT:
            # Two-point crossover
            min_len = min(len(words1), len(words2))
            if min_len < 3:
                return parent1
            point1 = random.randint(1, min_len - 2)
            point2 = random.randint(point1 + 1, min_len - 1)
            offspring = words1[:point1] + words2[point1:point2] + words1[point2:]
        
        elif self.crossover_method == CrossoverMethod.UNIFORM:
            # Uniform crossover
            offspring = []
            for i in range(max(len(words1), len(words2))):
                if i < len(words1) and i < len(words2):
                    offspring.append(words1[i] if random.random() < 0.5 else words2[i])
                elif i < len(words1):
                    offspring.append(words1[i])
                else:
                    offspring.append(words2[i])
        else:
            offspring = words1
        
        return " ".join(offspring)
    
    def _mutate(self, prompt: str) -> str:
        """Mutate a prompt.
        
        Args:
            prompt: Prompt to mutate
        
        Returns:
            Mutated prompt
        """
        words = prompt.split()
        if not words:
            return prompt
        
        if self.mutation_method == MutationMethod.WORD_SUBSTITUTION:
            # Substitute a word with a synonym
            for i, word in enumerate(words):
                word_lower = word.lower().strip('.,!?;:')
                if word_lower in self.synonyms and random.random() < 0.3:
                    replacement = random.choice(self.synonyms[word_lower])
                    # Preserve case
                    if word[0].isupper():
                        replacement = replacement.capitalize()
                    words[i] = replacement
                    break
        
        elif self.mutation_method == MutationMethod.PHRASE_INSERTION:
            # Insert a common phrase
            if len(words) > 1:
                position = random.randint(0, len(words) - 1)
                phrase = random.choice(self.phrases)
                words.insert(position, phrase.strip())
        
        elif self.mutation_method == MutationMethod.PHRASE_DELETION:
            # Delete a phrase
            if len(words) > 3:
                # Delete 1-2 words
                delete_count = random.randint(1, min(2, len(words) - 2))
                position = random.randint(0, len(words) - delete_count)
                words = words[:position] + words[position + delete_count:]
        
        elif self.mutation_method == MutationMethod.STRUCTURE_MODIFICATION:
            # Swap two words
            if len(words) > 2:
                i, j = random.sample(range(len(words)), 2)
                words[i], words[j] = words[j], words[i]
        
        return " ".join(words)
    
    def get_population_statistics(self, population: List[str]) -> Dict[str, Any]:
        """Get statistics about current population.
        
        Args:
            population: List of prompts
        
        Returns:
            Dictionary of statistics
        """
        return {
            "size": len(population),
            "avg_length": sum(len(p) for p in population) / len(population),
            "min_length": min(len(p) for p in population),
            "max_length": max(len(p) for p in population),
            "diversity": self._calculate_diversity(population),
            "unique_words": len(set(word for p in population for word in p.split()))
        }
