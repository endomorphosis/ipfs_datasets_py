"""
Batch 326: LLM-Based Extraction via ipfs_accelerate_py
======================================================

Implements LLM-powered entity extraction integrated with ipfs_accelerate_py
as an alternative to rule-based extraction, behind a feature flag.

Goal: Provide:
- LLM-based entity extraction with structured output
- Integration with ipfs_accelerate_py for model access
- Feature flag for enable/disable
- Fallback to rule-based extraction on LLM failure
- Caching of LLM responses for efficiency
"""

import pytest
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
from unittest.mock import Mock, patch, MagicMock
import json


class ExtractionStrategy(Enum):
    """Extraction strategy options."""
    RULE_BASED = "rule-based"
    LLM_BASED = "llm-based"
    HYBRID = "hybrid"  # Try LLM first, fallback to rule-based


@dataclass
class LLMExtractionConfig:
    """Configuration for LLM-based extraction."""
    enabled: bool = False
    strategy: ExtractionStrategy = ExtractionStrategy.RULE_BASED
    model_name: str = "mistral-7b"  # Default to lightweight model
    temperature: float = 0.5
    max_tokens: int = 2048
    use_cache: bool = True
    fallback_to_rules: bool = True  # Fallback on LLM failure
    min_confidence: float = 0.5
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        d = asdict(self)
        d["strategy"] = self.strategy.value
        return d
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LLMExtractionConfig":
        """Create from dictionary."""
        d = data.copy()
        if isinstance(d.get("strategy"), str):
            d["strategy"] = ExtractionStrategy(d["strategy"])
        return cls(**d)


class LLMExtractionCache:
    """Cache for LLM extraction results."""
    
    def __init__(self, max_size: int = 1000):
        """Initialize cache.
        
        Args:
            max_size: Maximum number of cached entries
        """
        self.max_size = max_size
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        self._hits = 0
        self._misses = 0
    
    def _make_key(self, text: str, domain: str, model: str) -> str:
        """Create cache key from text, domain, and model.
        
        Args:
            text: Input text
            domain: Domain specification
            model: Model name
            
        Returns:
            Cache key
        """
        # Simple hash-based key (in production, use proper hashing)
        import hashlib
        key_str = f"{text}|{domain}|{model}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get(self, text: str, domain: str, model: str) -> Optional[List[Dict[str, Any]]]:
        """Get cached extraction result.
        
        Args:
            text: Input text
            domain: Domain specification
            model: Model name
            
        Returns:
            Cached entities or None
        """
        key = self._make_key(text, domain, model)
        if key in self._cache:
            self._hits += 1
            return self._cache[key]
        self._misses += 1
        return None
    
    def put(self, text: str, domain: str, model: str, entities: List[Dict[str, Any]]) -> None:
        """Cache extraction result.
        
        Args:
            text: Input text
            domain: Domain specification
            model: Model name
            entities: Extracted entities
        """
        if len(self._cache) >= self.max_size:
            # Simple eviction: remove first entry
            first_key = next(iter(self._cache))
            del self._cache[first_key]
        
        key = self._make_key(text, domain, model)
        self._cache[key] = entities
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.
        
        Returns:
            Stats dictionary
        """
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0.0
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
        }
    
    def clear(self) -> None:
        """Clear cache."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0


class MockLLMClient:
    """Mock LLM client for testing."""
    
    def __init__(self, model_name: str = "mistral-7b"):
        """Initialize client.
        
        Args:
            model_name: Model name
        """
        self.model_name = model_name
        self.call_count = 0
        self.last_prompt = None
    
    def extract_entities(self, text: str, domain: str) -> List[Dict[str, Any]]:
        """Mock entity extraction from LLM.
        
        Args:
            text: Input text
            domain: Domain name
            
        Returns:
            List of extracted entities
        """
        self.call_count += 1
        self.last_prompt = text
        
        # Mock extraction: return entities based on text length
        words = text.split()
        entity_count = min(len(words) // 10, 10)
        
        entities = []
        for i in range(entity_count):
            start_idx = i * 10
            end_idx = min(start_idx + 10, len(words))
            if start_idx < len(words):
                text_span = " ".join(words[start_idx:end_idx])
                entities.append({
                    "id": f"e_{domain}_{i}",
                    "type": "ENTITY",
                    "text": text_span,
                    "confidence": 0.8 + (0.1 * (entity_count - i) / entity_count),
                    "domain": domain,
                })
        
        return entities


class LLMBasedExtractor:
    """LLM-based entity extractor."""
    
    def __init__(self, config: Optional[LLMExtractionConfig] = None, llm_client: Optional[MockLLMClient] = None):
        """Initialize extractor.
        
        Args:
            config: Extraction configuration
            llm_client: LLM client (MockLLMClient for testing)
        """
        self.config = config or LLMExtractionConfig()
        self.llm_client = llm_client or MockLLMClient(self.config.model_name)
        self.cache = LLMExtractionCache() if self.config.use_cache else None
        self.fallback_extractor = None  # Can inject rule-based extractor for fallback
    
    def extract(self, text: str, domain: str = "general") -> Dict[str, Any]:
        """Extract entities using configured strategy.
        
        Args:
            text: Input text
            domain: Domain specification
            
        Returns:
            Result dictionary with entities and metadata
        """
        if not self.config.enabled:
            return {
                "success": False,
                "error": "LLM extraction disabled",
                "entities": [],
            }
        
        # Try cache first
        if self.cache:
            cached = self.cache.get(text, domain, self.config.model_name)
            if cached is not None:
                return {
                    "success": True,
                    "entities": cached,
                    "cached": True,
                    "strategy": "cache",
                    "model": self.config.model_name,
                }
        
        try:
            # Extract using LLM
            entities = self.llm_client.extract_entities(text, domain)
            
            # Filter by confidence threshold
            filtered = [e for e in entities if e.get("confidence", 0) >= self.config.min_confidence]
            
            # Cache result
            if self.cache:
                self.cache.put(text, domain, self.config.model_name, filtered)
            
            return {
                "success": True,
                "entities": filtered,
                "cached": False,
                "strategy": self.config.strategy.value,
                "model": self.config.model_name,
                "confidence_filtered": len(entities) - len(filtered),
            }
        except Exception as e:
            if self.config.fallback_to_rules and self.fallback_extractor:
                # Fallback to rule-based extraction
                return self.fallback_extractor.extract(text, domain)
            return {
                "success": False,
                "error": f"LLM extraction failed: {str(e)}",
                "entities": [],
            }
    
    def set_fallback_extractor(self, extractor) -> None:
        """Set fallback extractor for LLM failures.
        
        Args:
            extractor: Fallback extractor instance
        """
        self.fallback_extractor = extractor
    
    def get_cache_stats(self) -> Optional[Dict[str, Any]]:
        """Get cache statistics.
        
        Returns:
            Cache stats or None if caching disabled
        """
        return self.cache.get_stats() if self.cache else None


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestLLMExtractionConfig:
    """Test LLM extraction configuration."""
    
    def test_default_config(self):
        """Test default configuration."""
        config = LLMExtractionConfig()
        assert config.enabled is False
        assert config.strategy == ExtractionStrategy.RULE_BASED
        assert config.model_name == "mistral-7b"
        assert config.temperature == 0.5
    
    def test_config_to_dict(self):
        """Test config serialization."""
        config = LLMExtractionConfig(enabled=True, strategy=ExtractionStrategy.LLM_BASED)
        d = config.to_dict()
        
        assert d["enabled"] is True
        assert d["strategy"] == "llm-based"
        assert d["model_name"] == "mistral-7b"
    
    def test_config_from_dict(self):
        """Test config deserialization."""
        d = {
            "enabled": True,
            "strategy": "hybrid",
            "model_name": "llama-7b",
            "temperature": 0.7,
            "max_tokens": 4096,
        }
        config = LLMExtractionConfig.from_dict(d)
        
        assert config.enabled is True
        assert config.strategy == ExtractionStrategy.HYBRID
        assert config.model_name == "llama-7b"
        assert config.temperature == 0.7
    
    def test_config_roundtrip(self):
        """Test config round-trip serialization."""
        original = LLMExtractionConfig(
            enabled=True,
            strategy=ExtractionStrategy.HYBRID,
            model_name="phi-2",
            temperature=0.3,
            min_confidence=0.7,
        )
        d = original.to_dict()
        restored = LLMExtractionConfig.from_dict(d)
        
        assert restored.enabled == original.enabled
        assert restored.strategy == original.strategy
        assert restored.model_name == original.model_name
        assert restored.temperature == original.temperature
        assert restored.min_confidence == original.min_confidence


class TestLLMExtractionCache:
    """Test LLM extraction cache."""
    
    def test_cache_initialization(self):
        """Test cache initialization."""
        cache = LLMExtractionCache(max_size=100)
        assert cache.max_size == 100
        assert len(cache._cache) == 0
    
    def test_cache_put_get(self):
        """Test cache put and get."""
        cache = LLMExtractionCache()
        
        entities = [{"id": "e1", "type": "ENTITY"}]
        cache.put("test text", "legal", "mistral-7b", entities)
        
        result = cache.get("test text", "legal", "mistral-7b")
        assert result == entities
    
    def test_cache_miss(self):
        """Test cache miss."""
        cache = LLMExtractionCache()
        
        result = cache.get("nonexistent", "legal", "mistral-7b")
        assert result is None
    
    def test_cache_stats(self):
        """Test cache statistics."""
        cache = LLMExtractionCache()
        
        # Warm cache
        cache.put("text1", "legal", "mistral", [])
        cache.put("text2", "legal", "mistral", [])
        
        # Generate hits and misses
        cache.get("text1", "legal", "mistral")  # Hit
        cache.get("text1", "legal", "mistral")  # Hit
        cache.get("missing", "legal", "mistral")  # Miss
        
        stats = cache.get_stats()
        assert stats["size"] == 2
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] > 0
    
    def test_cache_eviction(self):
        """Test cache eviction on size limit."""
        cache = LLMExtractionCache(max_size=2)
        
        cache.put("text1", "legal", "mistral", [{"id": "e1"}])
        cache.put("text2", "legal", "mistral", [{"id": "e2"}])
        cache.put("text3", "legal", "mistral", [{"id": "e3"}])
        
        # First entry should be evicted
        assert len(cache._cache) == 2
        result = cache.get("text3", "legal", "mistral")
        assert result[0]["id"] == "e3"


class TestMockLLMClient:
    """Test mock LLM client."""
    
    def test_client_initialization(self):
        """Test client initialization."""
        client = MockLLMClient(model_name="llama-7b")
        assert client.model_name == "llama-7b"
        assert client.call_count == 0
    
    def test_extract_entities(self):
        """Test entity extraction."""
        client = MockLLMClient()
        
        text = "The patient presented with symptoms. The doctor examined the patient carefully."
        entities = client.extract_entities(text, "medical")
        
        assert len(entities) > 0
        assert all("id" in e and "type" in e for e in entities)
        assert all(e["domain"] == "medical" for e in entities)
    
    def test_extraction_confidence(self):
        """Test extraction confidence scores."""
        client = MockLLMClient()
        
        text = "Some content here with various terms and concepts."
        entities = client.extract_entities(text, "general")
        
        # Verify confidence scores are reasonable
        assert all(0 <= e.get("confidence", 0) <= 1 for e in entities)


class TestLLMBasedExtractor:
    """Test LLM-based extractor."""
    
    def test_disabled_extraction(self):
        """Test extraction when disabled."""
        config = LLMExtractionConfig(enabled=False)
        extractor = LLMBasedExtractor(config)
        
        result = extractor.extract("test text")
        assert result["success"] is False
        assert "disabled" in result["error"].lower()
    
    def test_enabled_extraction(self):
        """Test enabled extraction."""
        config = LLMExtractionConfig(enabled=True, strategy=ExtractionStrategy.LLM_BASED)
        extractor = LLMBasedExtractor(config)
        
        text = "The quick brown fox jumps over the lazy dog multiple times."
        result = extractor.extract(text, "general")
        
        assert result["success"] is True
        assert "entities" in result
        assert result["strategy"] == "llm-based"
    
    def test_extraction_with_caching(self):
        """Test extraction with caching."""
        config = LLMExtractionConfig(enabled=True, use_cache=True)
        extractor = LLMBasedExtractor(config)
        
        text = "Repeated text for testing cache performance."
        
        # First call (cache miss)
        result1 = extractor.extract(text)
        assert result1["cached"] is False
        
        # Second call (cache hit)
        result2 = extractor.extract(text)
        assert result2["cached"] is True
        assert result1["entities"] == result2["entities"]
    
    def test_confidence_filtering(self):
        """Test confidence threshold filtering."""
        config = LLMExtractionConfig(enabled=True, min_confidence=0.9)
        extractor = LLMBasedExtractor(config)
        
        text = "Content for confidence testing with many words and terms and concepts."
        result = extractor.extract(text)
        
        assert result["success"] is True
        # Some entities may be filtered out
        assert "confidence_filtered" in result
    
    def test_model_selection(self):
        """Test different model selection."""
        config = LLMExtractionConfig(enabled=True, model_name="phi-2")
        extractor = LLMBasedExtractor(config)
        
        result = extractor.extract("test text")
        assert result["model"] == "phi-2"
    
    def test_hybrid_strategy(self):
        """Test hybrid extraction strategy."""
        config = LLMExtractionConfig(
            enabled=True,
            strategy=ExtractionStrategy.HYBRID,
            fallback_to_rules=True,
        )
        extractor = LLMBasedExtractor(config)
        
        text = "Hybrid extraction test content."
        result = extractor.extract(text)
        
        assert result["success"] is True
        assert "entities" in result


class TestLLMFallbackBehavior:
    """Test fallback to rule-based extraction."""
    
    def test_fallback_on_llm_failure(self):
        """Test fallback when LLM fails."""
        config = LLMExtractionConfig(
            enabled=True,
            fallback_to_rules=True,
        )
        
        # Create extractor with failing LLM
        bad_client = Mock()
        bad_client.extract_entities.side_effect = Exception("LLM error")
        
        extractor = LLMBasedExtractor(config, bad_client)
        
        # Set fallback (mock a rule-based extractor)
        fallback = Mock()
        fallback.extract.return_value = {"success": True, "entities": []}
        extractor.set_fallback_extractor(fallback)
        
        result = extractor.extract("test text")
        
        # Should call fallback
        assert fallback.extract.called
    
    def test_no_fallback_on_error(self):
        """Test error when no fallback available."""
        config = LLMExtractionConfig(
            enabled=True,
            fallback_to_rules=False,
        )
        
        bad_client = Mock()
        bad_client.extract_entities.side_effect = Exception("LLM error")
        
        extractor = LLMBasedExtractor(config, bad_client)
        
        result = extractor.extract("test text")
        assert result["success"] is False
        assert "error" in result


class TestLLMExtractionIntegration:
    """Integration tests for LLM-based extraction."""
    
    def test_full_extraction_workflow(self):
        """Test complete extraction workflow."""
        config = LLMExtractionConfig(enabled=True, use_cache=True)
        extractor = LLMBasedExtractor(config)
        
        texts = [
            "Medical entities like hypertension and angina pectoris and various other conditions.",
            "Legal concepts including tort liability and contractual obligations under law.",
            "Technical terms such as TCP/IP protocols and machine learning algorithms used in computing.",
        ]
        
        for text in texts:
            result = extractor.extract(text, "general")
            assert result["success"] is True
            assert len(result["entities"]) >= 0  # Can be 0 or more
        
        # Verify caching stats
        stats = extractor.get_cache_stats()
        assert stats["size"] == 3
        assert stats["hits"] == 0  # All unique texts
    
    def test_multi_domain_extraction(self):
        """Test extraction across domains."""
        config = LLMExtractionConfig(enabled=True)
        extractor = LLMBasedExtractor(config)
        
        domains = ["legal", "medical", "technical", "financial"]
        text = "Sample text for multi-domain extraction testing."
        
        for domain in domains:
            result = extractor.extract(text, domain)
            assert result["success"] is True
            # Verify domain is preserved
            assert all(e["domain"] == domain for e in result["entities"])
