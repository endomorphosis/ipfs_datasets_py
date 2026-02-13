"""Tests for automated prompt engineering using genetic algorithms."""

import time
from unittest.mock import Mock

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.prompt_engineer import (
    PromptEngineer,
    SelectionMethod,
    CrossoverMethod,
    MutationMethod,
    EvolutionResult
)


class TestPromptEngineer:
    """Test suite for PromptEngineer class."""
    
    def test_initialization(self):
        """
        GIVEN default parameters
        WHEN PromptEngineer is initialized
        THEN all parameters are set correctly
        """
        engineer = PromptEngineer()
        
        assert engineer.population_size == 20
        assert engineer.num_generations == 10
        assert engineer.selection_method == SelectionMethod.TOURNAMENT
        assert engineer.crossover_method == CrossoverMethod.TWO_POINT
        assert engineer.mutation_method == MutationMethod.WORD_SUBSTITUTION
        assert engineer.mutation_rate == 0.15
        assert engineer.elite_size == 2
        assert engineer.tournament_size == 3
        assert engineer.convergence_threshold == 0.01
    
    def test_custom_initialization(self):
        """
        GIVEN custom parameters
        WHEN PromptEngineer is initialized
        THEN custom parameters are used
        """
        engineer = PromptEngineer(
            population_size=30,
            num_generations=15,
            selection_method=SelectionMethod.ROULETTE_WHEEL,
            crossover_method=CrossoverMethod.UNIFORM,
            mutation_method=MutationMethod.PHRASE_INSERTION,
            mutation_rate=0.25,
            elite_size=3,
            tournament_size=5,
            convergence_threshold=0.02
        )
        
        assert engineer.population_size == 30
        assert engineer.num_generations == 15
        assert engineer.selection_method == SelectionMethod.ROULETTE_WHEEL
        assert engineer.crossover_method == CrossoverMethod.UNIFORM
        assert engineer.mutation_method == MutationMethod.PHRASE_INSERTION
        assert engineer.mutation_rate == 0.25
        assert engineer.elite_size == 3
        assert engineer.tournament_size == 5
        assert engineer.convergence_threshold == 0.02
    
    def test_initialize_population(self):
        """
        GIVEN seed prompts
        WHEN population is initialized
        THEN population has correct size and contains seeds
        """
        engineer = PromptEngineer(population_size=10)
        seeds = ["Extract logic from text", "Identify formal statements"]
        
        population = engineer._initialize_population(seeds)
        
        assert len(population) == 10
        assert all(seed in population for seed in seeds)
        assert len(set(population)) == len(population)  # All unique
    
    def test_evaluate_fitness_basic(self):
        """
        GIVEN a prompt and fitness function
        WHEN fitness is evaluated
        THEN score is between 0 and 1
        """
        engineer = PromptEngineer()
        
        def fitness_func(prompt: str) -> float:
            return 0.7
        
        fitness = engineer._evaluate_fitness("Test prompt", fitness_func, None)
        
        assert 0.0 <= fitness <= 1.0
    
    def test_evaluate_fitness_with_domain(self):
        """
        GIVEN a prompt with domain keywords
        WHEN fitness is evaluated with domain
        THEN domain bonus is applied
        """
        engineer = PromptEngineer()
        
        def fitness_func(prompt: str) -> float:
            return 0.5
        
        # Prompt with legal keywords
        legal_prompt = "Extract legal statute from law document"
        fitness_legal = engineer._evaluate_fitness(legal_prompt, fitness_func, "legal")
        
        # Prompt without legal keywords
        general_prompt = "Extract information from text"
        fitness_general = engineer._evaluate_fitness(general_prompt, fitness_func, "legal")
        
        # Legal prompt should have higher fitness due to domain bonus
        assert fitness_legal > fitness_general
    
    def test_calculate_diversity(self):
        """
        GIVEN a population of prompts
        WHEN diversity is calculated
        THEN diversity score reflects variation
        """
        engineer = PromptEngineer()
        
        # High diversity population
        diverse_pop = [
            "Extract logic from text",
            "Identify formal statements in document",
            "Find logical reasoning patterns"
        ]
        diversity_high = engineer._calculate_diversity(diverse_pop)
        
        # Low diversity population
        similar_pop = [
            "Extract logic from text",
            "Extract logic from text data",
            "Extract logic from text document"
        ]
        diversity_low = engineer._calculate_diversity(similar_pop)
        
        assert diversity_high > diversity_low
        assert 0.0 <= diversity_high <= 1.0
        assert 0.0 <= diversity_low <= 1.0
    
    def test_check_convergence_not_converged(self):
        """
        GIVEN evolution history with improving fitness
        WHEN convergence is checked
        THEN evolution has not converged
        """
        engineer = PromptEngineer(convergence_threshold=0.01)
        
        history = [
            {"best_fitness": 0.5},
            {"best_fitness": 0.6},
            {"best_fitness": 0.7}
        ]
        
        converged = engineer._check_convergence(history, 0.01)
        
        assert not converged
    
    def test_check_convergence_converged(self):
        """
        GIVEN evolution history with plateau
        WHEN convergence is checked
        THEN evolution has converged
        """
        engineer = PromptEngineer(convergence_threshold=0.01)
        
        history = [
            {"best_fitness": 0.70},
            {"best_fitness": 0.702},
            {"best_fitness": 0.703}
        ]
        
        converged = engineer._check_convergence(history, 0.01)
        
        assert converged
    
    def test_select_parent_tournament(self):
        """
        GIVEN population with fitness scores
        WHEN tournament selection is used
        THEN high-fitness prompts are more likely selected
        """
        engineer = PromptEngineer(
            selection_method=SelectionMethod.TOURNAMENT,
            tournament_size=3
        )
        
        population = ["prompt1", "prompt2", "prompt3", "prompt4", "prompt5"]
        fitness_scores = {
            "prompt1": 0.9,
            "prompt2": 0.1,
            "prompt3": 0.3,
            "prompt4": 0.5,
            "prompt5": 0.2
        }
        
        # Run multiple selections
        selections = [engineer._select_parent(population, fitness_scores) for _ in range(10)]
        
        # Should mostly select high-fitness prompts
        assert "prompt1" in selections
    
    def test_select_parent_roulette(self):
        """
        GIVEN population with fitness scores
        WHEN roulette wheel selection is used
        THEN selection is fitness-proportional
        """
        engineer = PromptEngineer(selection_method=SelectionMethod.ROULETTE_WHEEL)
        
        population = ["prompt1", "prompt2", "prompt3"]
        fitness_scores = {
            "prompt1": 0.6,
            "prompt2": 0.3,
            "prompt3": 0.1
        }
        
        # Run multiple selections
        selections = [engineer._select_parent(population, fitness_scores) for _ in range(20)]
        
        # All prompts should be selected at some point
        assert len(set(selections)) > 1
    
    def test_crossover_single_point(self):
        """
        GIVEN two parent prompts
        WHEN single-point crossover is applied
        THEN offspring contains parts from both parents
        """
        engineer = PromptEngineer(crossover_method=CrossoverMethod.SINGLE_POINT)
        
        parent1 = "Extract logic from text document"
        parent2 = "Identify formal statements in passage"
        
        offspring = engineer._crossover(parent1, parent2)
        
        # Offspring should have words from both parents
        offspring_words = set(offspring.split())
        parent1_words = set(parent1.split())
        parent2_words = set(parent2.split())
        
        assert len(offspring_words & parent1_words) > 0
        assert len(offspring_words & parent2_words) > 0
    
    def test_crossover_two_point(self):
        """
        GIVEN two parent prompts
        WHEN two-point crossover is applied
        THEN offspring is mix of both parents
        """
        engineer = PromptEngineer(crossover_method=CrossoverMethod.TWO_POINT)
        
        parent1 = "Extract logic from text document carefully"
        parent2 = "Identify formal statements in passage precisely"
        
        offspring = engineer._crossover(parent1, parent2)
        
        # Should produce valid offspring
        assert isinstance(offspring, str)
        assert len(offspring) > 0
    
    def test_crossover_uniform(self):
        """
        GIVEN two parent prompts
        WHEN uniform crossover is applied
        THEN each word randomly selected from parents
        """
        engineer = PromptEngineer(crossover_method=CrossoverMethod.UNIFORM)
        
        parent1 = "Extract logic from document"
        parent2 = "Identify statements in text"
        
        offspring = engineer._crossover(parent1, parent2)
        
        assert isinstance(offspring, str)
        assert len(offspring) > 0
    
    def test_mutate_word_substitution(self):
        """
        GIVEN a prompt
        WHEN word substitution mutation is applied
        THEN some words may be replaced with synonyms
        """
        engineer = PromptEngineer(mutation_method=MutationMethod.WORD_SUBSTITUTION)
        
        original = "extract logic from text"
        mutated = engineer._mutate(original)
        
        assert isinstance(mutated, str)
        assert len(mutated) > 0
        # May or may not be different (depends on random)
    
    def test_mutate_phrase_insertion(self):
        """
        GIVEN a prompt
        WHEN phrase insertion mutation is applied
        THEN a phrase may be inserted
        """
        engineer = PromptEngineer(mutation_method=MutationMethod.PHRASE_INSERTION)
        
        original = "extract logic from text"
        mutated = engineer._mutate(original)
        
        assert isinstance(mutated, str)
        # May be longer (phrase inserted)
        assert len(mutated.split()) >= len(original.split())
    
    def test_mutate_phrase_deletion(self):
        """
        GIVEN a prompt
        WHEN phrase deletion mutation is applied
        THEN some words may be removed
        """
        engineer = PromptEngineer(mutation_method=MutationMethod.PHRASE_DELETION)
        
        original = "extract logic carefully from the text document"
        mutated = engineer._mutate(original)
        
        assert isinstance(mutated, str)
        assert len(mutated) > 0
    
    def test_mutate_structure_modification(self):
        """
        GIVEN a prompt
        WHEN structure modification mutation is applied
        THEN word order may change
        """
        engineer = PromptEngineer(mutation_method=MutationMethod.STRUCTURE_MODIFICATION)
        
        original = "extract logic from text document"
        mutated = engineer._mutate(original)
        
        assert isinstance(mutated, str)
        assert len(mutated.split()) == len(original.split())
    
    def test_evolve_prompts_basic(self):
        """
        GIVEN initial prompts and fitness function
        WHEN prompts are evolved
        THEN evolution produces improved prompts
        """
        engineer = PromptEngineer(
            population_size=10,
            num_generations=5,
            mutation_rate=0.2
        )
        
        def fitness_func(prompt: str) -> float:
            # Simple fitness: longer prompts score higher
            return min(len(prompt) / 100.0, 1.0)
        
        initial_prompts = ["Extract logic", "Find statements"]
        
        result = engineer.evolve_prompts(initial_prompts, fitness_func)
        
        assert isinstance(result, EvolutionResult)
        assert result.best_prompt is not None
        assert 0.0 <= result.best_fitness <= 1.0
        assert len(result.population) == engineer.population_size
        assert result.generations_run > 0
        assert len(result.history) == result.generations_run
    
    def test_evolve_prompts_with_domain(self):
        """
        GIVEN initial prompts and domain
        WHEN prompts are evolved for domain
        THEN domain-specific optimization occurs
        """
        engineer = PromptEngineer(population_size=8, num_generations=3)
        
        def fitness_func(prompt: str) -> float:
            return 0.5
        
        initial_prompts = ["Extract legal information", "Find legal rules"]
        
        result = engineer.evolve_prompts(initial_prompts, fitness_func, domain="legal")
        
        assert result.best_prompt is not None
        assert result.generations_run > 0
    
    def test_evolve_prompts_convergence(self):
        """
        GIVEN fitness function that quickly plateaus
        WHEN prompts are evolved
        THEN evolution detects convergence
        """
        engineer = PromptEngineer(
            population_size=6,
            num_generations=20,
            convergence_threshold=0.001
        )
        
        def fitness_func(prompt: str) -> float:
            # Constant fitness - immediate convergence
            return 0.7
        
        initial_prompts = ["Prompt A", "Prompt B"]
        
        result = engineer.evolve_prompts(initial_prompts, fitness_func)
        
        # Should converge before max generations
        assert result.converged or result.generations_run < engineer.num_generations
    
    def test_create_next_generation(self):
        """
        GIVEN current population
        WHEN next generation is created
        THEN elite prompts are preserved
        """
        engineer = PromptEngineer(population_size=10, elite_size=2)
        
        population = [f"prompt_{i}" for i in range(10)]
        fitness_scores = {f"prompt_{i}": 0.1 * i for i in range(10)}
        
        next_gen = engineer._create_next_generation(population, fitness_scores)
        
        assert len(next_gen) == engineer.population_size
        # Best prompts should be preserved
        assert "prompt_9" in next_gen  # Highest fitness
        assert "prompt_8" in next_gen  # Second highest
    
    def test_get_population_statistics(self):
        """
        GIVEN a population
        WHEN statistics are requested
        THEN comprehensive stats are returned
        """
        engineer = PromptEngineer()
        
        population = [
            "Short prompt",
            "This is a longer prompt with more words",
            "Medium length prompt here"
        ]
        
        stats = engineer.get_population_statistics(population)
        
        assert stats["size"] == 3
        assert stats["avg_length"] > 0
        assert stats["min_length"] > 0
        assert stats["max_length"] > 0
        assert 0.0 <= stats["diversity"] <= 1.0
        assert stats["unique_words"] > 0
    
    def test_evolution_history_tracking(self):
        """
        GIVEN evolution process
        WHEN evolution runs
        THEN history is tracked for each generation
        """
        engineer = PromptEngineer(population_size=6, num_generations=4)
        
        def fitness_func(prompt: str) -> float:
            return 0.6
        
        initial_prompts = ["Prompt 1", "Prompt 2"]
        
        result = engineer.evolve_prompts(initial_prompts, fitness_func)
        
        assert len(result.history) == result.generations_run
        for gen_stat in result.history:
            assert "generation" in gen_stat
            assert "best_fitness" in gen_stat
            assert "avg_fitness" in gen_stat
            assert "diversity" in gen_stat
            assert "best_prompt" in gen_stat
    
    def test_evolution_time_tracking(self):
        """
        GIVEN evolution process
        WHEN evolution completes
        THEN total time is tracked
        """
        engineer = PromptEngineer(population_size=5, num_generations=2)
        
        def fitness_func(prompt: str) -> float:
            time.sleep(0.01)  # Small delay
            return 0.5
        
        initial_prompts = ["Test prompt"]
        
        result = engineer.evolve_prompts(initial_prompts, fitness_func)
        
        assert result.total_time > 0.0
    
    def test_elite_preservation(self):
        """
        GIVEN evolution with elite_size > 0
        WHEN next generation is created
        THEN best prompts are always preserved
        """
        engineer = PromptEngineer(elite_size=3)
        
        population = [f"prompt_{i}" for i in range(10)]
        fitness_scores = {f"prompt_{i}": float(i) / 10 for i in range(10)}
        
        next_gen = engineer._create_next_generation(population, fitness_scores)
        
        # Top 3 should be in next generation
        assert "prompt_9" in next_gen
        assert "prompt_8" in next_gen
        assert "prompt_7" in next_gen
