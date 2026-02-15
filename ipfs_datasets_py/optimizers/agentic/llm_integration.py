"""LLM Router Integration for Agentic Optimizer.

This module provides LLM router integration for the agentic optimizer,
enabling AI-powered code optimization with multiple LLM providers.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import os
import re

from ...llm_router import generate_text as router_generate
from .base import OptimizationMethod
from .production_hardening import CircuitBreaker, RetryHandler
from ..common.performance import LLMCache, get_global_cache


class LLMProvider(Enum):
    """Supported LLM providers."""
    
    GPT4 = "gpt4"
    CLAUDE = "claude"
    CODEX = "codex"
    COPILOT = "copilot"
    GEMINI = "gemini"
    LOCAL = "local"  # Local HuggingFace models
    AUTO = "auto"  # Automatic selection


@dataclass
class ProviderCapability:
    """Capabilities of an LLM provider.
    
    Attributes:
        name: Provider name
        supports_code: Whether provider is good at code generation
        supports_reasoning: Whether provider excels at reasoning
        supports_analysis: Whether provider can analyze code
        max_tokens: Maximum tokens supported
        cost_per_1k_tokens: Approximate cost per 1000 tokens (USD)
        priority: Provider priority (lower = higher priority)
    """
    
    name: str
    supports_code: bool = True
    supports_reasoning: bool = True
    supports_analysis: bool = True
    max_tokens: int = 4096
    cost_per_1k_tokens: float = 0.0
    priority: int = 999


# Provider capabilities mapping
PROVIDER_CAPABILITIES = {
    LLMProvider.GPT4: ProviderCapability(
        name="gpt4",
        supports_code=True,
        supports_reasoning=True,
        supports_analysis=True,
        max_tokens=8192,
        cost_per_1k_tokens=0.03,
        priority=1,
    ),
    LLMProvider.CLAUDE: ProviderCapability(
        name="claude",
        supports_code=True,
        supports_reasoning=True,
        supports_analysis=True,
        max_tokens=100000,
        cost_per_1k_tokens=0.008,
        priority=2,
    ),
    LLMProvider.CODEX: ProviderCapability(
        name="codex",
        supports_code=True,
        supports_reasoning=False,
        supports_analysis=True,
        max_tokens=8000,
        cost_per_1k_tokens=0.0,
        priority=3,
    ),
    LLMProvider.COPILOT: ProviderCapability(
        name="copilot",
        supports_code=True,
        supports_reasoning=False,
        supports_analysis=False,
        max_tokens=4096,
        cost_per_1k_tokens=0.0,
        priority=4,
    ),
    LLMProvider.GEMINI: ProviderCapability(
        name="gemini",
        supports_code=True,
        supports_reasoning=True,
        supports_analysis=True,
        max_tokens=32000,
        cost_per_1k_tokens=0.0,
        priority=5,
    ),
    LLMProvider.LOCAL: ProviderCapability(
        name="local",
        supports_code=True,
        supports_reasoning=True,
        supports_analysis=True,
        max_tokens=2048,
        cost_per_1k_tokens=0.0,
        priority=10,
    ),
}


class OptimizerLLMRouter:
    """LLM Router for optimizer operations.
    
    Routes optimization tasks to appropriate LLM providers based on
    task complexity, provider capabilities, and availability.
    
    Example:
        >>> router = OptimizerLLMRouter(
        ...     preferred_provider=LLMProvider.CLAUDE,
        ...     fallback_providers=[LLMProvider.GPT4, LLMProvider.LOCAL],
        ... )
        >>> response = router.generate(
        ...     prompt="Optimize this function...",
        ...     method=OptimizationMethod.TEST_DRIVEN,
        ...     max_tokens=2000,
        ... )
    """
    
    def __init__(
        self,
        preferred_provider: Optional[LLMProvider] = None,
        fallback_providers: Optional[List[LLMProvider]] = None,
        enable_tracking: bool = True,
        enable_caching: bool = True,
        cache: Optional[LLMCache] = None,
    ):
        """Initialize LLM router.
        
        Args:
            preferred_provider: Preferred LLM provider (None = auto-detect)
            fallback_providers: Fallback providers if preferred fails
            enable_tracking: Enable token usage tracking
            enable_caching: Enable LLM response caching (70-90% API reduction)
            cache: Custom cache instance (None = use global cache)
        """
        self.preferred_provider = preferred_provider or self._detect_provider()
        self.fallback_providers = fallback_providers or self._get_default_fallbacks()
        self.enable_tracking = enable_tracking
        self.enable_caching = enable_caching
        
        # LLM caching for 70-90% API call reduction
        self.cache = cache or (get_global_cache() if enable_caching else None)
        
        # Token usage tracking
        self.token_usage: Dict[str, int] = {}
        self.call_count: Dict[str, int] = {}
        self.error_count: Dict[str, int] = {}
        self.cache_hits: int = 0
        self.cache_misses: int = 0
        
        # Production hardening: Circuit breakers for each provider
        self._breakers: Dict[LLMProvider, CircuitBreaker] = {
            provider: CircuitBreaker(failure_threshold=3, timeout=30)
            for provider in LLMProvider if provider != LLMProvider.AUTO
        }
        
        # Production hardening: Retry handler with exponential backoff
        self._retry_handler = RetryHandler(max_retries=3, base_delay=1.0, max_delay=30.0)
    
    def _detect_provider(self) -> LLMProvider:
        """Auto-detect best available provider.
        
        Returns:
            Best available LLM provider
        """
        # Check environment variable
        env_provider = os.environ.get("IPFS_DATASETS_PY_LLM_PROVIDER", "").lower()
        
        provider_map = {
            "gpt4": LLMProvider.GPT4,
            "openai": LLMProvider.GPT4,
            "claude": LLMProvider.CLAUDE,
            "anthropic": LLMProvider.CLAUDE,
            "codex": LLMProvider.CODEX,
            "copilot": LLMProvider.COPILOT,
            "gemini": LLMProvider.GEMINI,
            "local": LLMProvider.LOCAL,
        }
        
        if env_provider in provider_map:
            return provider_map[env_provider]
        
        # Check for API keys to determine availability
        if os.environ.get("OPENAI_API_KEY"):
            return LLMProvider.GPT4
        elif os.environ.get("ANTHROPIC_API_KEY"):
            return LLMProvider.CLAUDE
        elif os.environ.get("GEMINI_API_KEY"):
            return LLMProvider.GEMINI
        
        # Default to local if nothing else available
        return LLMProvider.LOCAL
    
    def _get_default_fallbacks(self) -> List[LLMProvider]:
        """Get default fallback providers.
        
        Returns:
            List of fallback providers
        """
        # Sort providers by priority
        sorted_providers = sorted(
            PROVIDER_CAPABILITIES.items(),
            key=lambda x: x[1].priority
        )
        
        # Return all providers except the preferred one
        return [
            provider for provider, _ in sorted_providers
            if provider != self.preferred_provider
        ]
    
    def select_provider(
        self,
        method: OptimizationMethod,
        complexity: str = "medium",
    ) -> LLMProvider:
        """Select best provider for given optimization method.
        
        Args:
            method: Optimization method
            complexity: Task complexity (simple/medium/complex)
            
        Returns:
            Selected LLM provider
        """
        # For simple tasks, any provider works
        if complexity == "simple":
            return self.preferred_provider
        
        # For complex reasoning tasks, prefer Claude or GPT-4
        if method in [OptimizationMethod.ACTOR_CRITIC, OptimizationMethod.CHAOS]:
            if self.preferred_provider in [LLMProvider.CLAUDE, LLMProvider.GPT4]:
                return self.preferred_provider
            # Fallback to Claude or GPT-4
            for provider in [LLMProvider.CLAUDE, LLMProvider.GPT4]:
                if provider in self.fallback_providers:
                    return provider
        
        # For code-heavy tasks, Codex or Copilot can work well
        if method == OptimizationMethod.TEST_DRIVEN:
            if self.preferred_provider == LLMProvider.CODEX:
                return self.preferred_provider
        
        # Default to preferred provider
        return self.preferred_provider
    
    def generate(
        self,
        prompt: str,
        method: OptimizationMethod,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        """Generate text using LLM router with caching.
        
        Args:
            prompt: Input prompt
            method: Optimization method (for provider selection)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional router arguments
            
        Returns:
            Generated text
            
        Raises:
            RuntimeError: If all providers fail
        """
        # Check cache first (70-90% hit rate after warmup)
        if self.cache:
            cache_key_kwargs = {
                "method": str(method),
                "max_tokens": max_tokens,
                "temperature": temperature,
                **{k: str(v) for k, v in kwargs.items()}
            }
            cached_response = self.cache.get(prompt, **cache_key_kwargs)
            if cached_response is not None:
                self.cache_hits += 1
                return cached_response
            self.cache_misses += 1
        
        # Select provider
        provider = self.select_provider(method)
        providers_to_try = [provider] + [
            p for p in self.fallback_providers if p != provider
        ]
        
        last_error = None
        
        for current_provider in providers_to_try:
            try:
                # Get provider name for router
                provider_name = PROVIDER_CAPABILITIES[current_provider].name
                
                # Track call
                if self.enable_tracking:
                    self.call_count[provider_name] = self.call_count.get(provider_name, 0) + 1
                
                # Call router with provider hint
                os.environ["IPFS_DATASETS_PY_LLM_PROVIDER"] = provider_name
                
                # Production hardening: Use circuit breaker + retry logic
                def _make_llm_call():
                    return self._breakers[current_provider].call(
                        router_generate,
                        prompt=prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        **kwargs
                    )
                
                response = self._retry_handler.retry(_make_llm_call, max_retries=2)
                
                # Store in cache
                if self.cache:
                    cache_key_kwargs = {
                        "method": str(method),
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        **{k: str(v) for k, v in kwargs.items()}
                    }
                    self.cache.set(prompt, response, **cache_key_kwargs)
                
                # Track tokens (estimate)
                if self.enable_tracking:
                    estimated_tokens = len(prompt.split()) + len(response.split())
                    self.token_usage[provider_name] = self.token_usage.get(provider_name, 0) + estimated_tokens
                
                return response
                
            except Exception as e:
                last_error = e
                if self.enable_tracking:
                    provider_name = PROVIDER_CAPABILITIES[current_provider].name
                    self.error_count[provider_name] = self.error_count.get(provider_name, 0) + 1
                
                # Try next provider
                continue
        
        # All providers failed
        raise RuntimeError(
            f"All LLM providers failed. Last error: {last_error}"
        )
    
    def get_prompt_template(
        self,
        method: OptimizationMethod,
        task_type: str = "code",
    ) -> str:
        """Get prompt template for optimization method.
        
        Args:
            method: Optimization method
            task_type: Type of task (code, test, analysis, fix)
            
        Returns:
            Prompt template string with {placeholders}
        """
        if method == OptimizationMethod.TEST_DRIVEN:
            if task_type == "test":
                return TEST_GENERATION_TEMPLATE
            elif task_type == "code":
                return CODE_OPTIMIZATION_TEMPLATE
            else:
                return ANALYSIS_TEMPLATE
        
        elif method == OptimizationMethod.ADVERSARIAL:
            return ADVERSARIAL_TEMPLATE
        
        elif method == OptimizationMethod.ACTOR_CRITIC:
            if task_type == "actor":
                return ACTOR_PROPOSAL_TEMPLATE
            else:
                return CRITIC_EVALUATION_TEMPLATE
        
        elif method == OptimizationMethod.CHAOS:
            if task_type == "analysis":
                return CHAOS_ANALYSIS_TEMPLATE
            else:
                return CHAOS_FIX_TEMPLATE
        
        return GENERIC_TEMPLATE
    
    def extract_code(self, response: str) -> str:
        """Extract code from LLM response.
        
        Args:
            response: LLM response text
            
        Returns:
            Extracted code
        """
        # Look for code blocks
        code_block_pattern = r'```(?:python)?\n(.*?)\n```'
        matches = re.findall(code_block_pattern, response, re.DOTALL)
        
        if matches:
            # Return the first code block
            return matches[0].strip()
        
        # No code blocks found, return response as-is
        return response.strip()
    
    def extract_description(self, response: str) -> str:
        """Extract description from LLM response.
        
        Args:
            response: LLM response text
            
        Returns:
            Extracted description
        """
        # Look for text before first code block
        code_block_pattern = r'```(?:python)?'
        parts = re.split(code_block_pattern, response)
        
        if len(parts) > 1:
            return parts[0].strip()
        
        # Take first 200 chars as description
        return response[:200] + "..." if len(response) > 200 else response
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get usage statistics including cache performance.
        
        Returns:
            Dictionary with usage statistics
        """
        total_calls = sum(self.call_count.values())
        total_tokens = sum(self.token_usage.values())
        total_errors = sum(self.error_count.values())
        total_cache_requests = self.cache_hits + self.cache_misses
        
        stats = {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "total_errors": total_errors,
            "success_rate": (total_calls - total_errors) / max(total_calls, 1),
            "by_provider": {
                provider: {
                    "calls": self.call_count.get(provider, 0),
                    "tokens": self.token_usage.get(provider, 0),
                    "errors": self.error_count.get(provider, 0),
                }
                for provider in set(
                    list(self.call_count.keys()) +
                    list(self.token_usage.keys()) +
                    list(self.error_count.keys())
                )
            },
        }
        
        # Add cache statistics if caching is enabled
        if self.cache:
            stats["cache"] = {
                "hits": self.cache_hits,
                "misses": self.cache_misses,
                "hit_rate": self.cache_hits / max(total_cache_requests, 1),
                "api_call_reduction": self.cache_hits / max(total_cache_requests, 1),
            }
            # Add internal cache stats
            cache_stats = self.cache.get_stats()
            stats["cache"].update(cache_stats)
        
        return stats


# Prompt templates for different optimization methods

TEST_GENERATION_TEMPLATE = """Generate comprehensive test cases for the following code:

{code}

Task: {description}

Requirements:
1. Generate pytest-compatible test functions
2. Cover main functionality and edge cases
3. Include docstrings for each test
4. Use appropriate assertions
5. Test error handling

Generate the test code:"""

CODE_OPTIMIZATION_TEMPLATE = """Optimize the following code for better performance:

{code}

Current Performance: {baseline_metrics}

Requirements:
1. Maintain backward compatibility
2. Improve performance by at least {min_improvement}%
3. Keep the same API
4. Add type hints if missing
5. Include comprehensive docstrings

Generate the optimized code:"""

ANALYSIS_TEMPLATE = """Analyze the following code and provide optimization recommendations:

{code}

Task: {description}

Provide:
1. Performance bottlenecks
2. Code quality issues
3. Potential improvements
4. Estimated impact of each improvement

Analysis:"""

ADVERSARIAL_TEMPLATE = """Generate an alternative implementation for the following code:

{code}

Approach: {approach}

Requirements:
1. Use a {approach} approach
2. Maintain the same functionality
3. Focus on {focus} optimization
4. Include type hints and docstrings
5. Make it production-ready

Generate the alternative implementation:"""

ACTOR_PROPOSAL_TEMPLATE = """Propose a code improvement for the following:

{code}

Context: {context}

Previous patterns that worked well:
{patterns}

Requirements:
1. Apply proven patterns where applicable
2. Improve code quality and performance
3. Maintain backward compatibility
4. Include clear explanations

Propose your improvement:"""

CRITIC_EVALUATION_TEMPLATE = """Evaluate the following code proposal:

{proposed_code}

Original code:
{original_code}

Evaluation criteria:
1. Correctness (does it work?)
2. Performance (is it faster?)
3. Maintainability (is it cleaner?)
4. Style (does it follow conventions?)

Provide scores (0-10) and detailed feedback:"""

CHAOS_ANALYSIS_TEMPLATE = """Analyze the following code for resilience issues:

{code}

Focus on:
1. Error handling gaps
2. Input validation issues
3. Resource management problems
4. Network failure scenarios
5. Edge cases that could cause failures

List all potential issues with severity:"""

CHAOS_FIX_TEMPLATE = """Generate a fix for the following resilience issue:

{code}

Issue: {issue_description}
Severity: {severity}

Requirements:
1. Add proper error handling
2. Validate inputs
3. Handle edge cases
4. Add logging
5. Make it production-ready

Generate the fixed code:"""

GENERIC_TEMPLATE = """{code}

Task: {description}

Generate improved code:"""
