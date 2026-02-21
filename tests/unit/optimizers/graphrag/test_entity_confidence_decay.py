"""
Unit tests for Entity confidence decay over time.

Tests the time-based confidence decay mechanism that reduces entity confidence
for entities that haven't been observed recently.
"""

import time
import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity


class TestEntityConfidenceDecay:
    """Test suite for Entity.apply_confidence_decay()."""

    def test_no_decay_when_last_seen_is_none(self):
        """Entities without last_seen timestamp should not decay."""
        entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.9,
            last_seen=None,
        )
        
        decayed = entity.apply_confidence_decay()
        
        assert decayed.confidence == 0.9
        assert decayed.last_seen is None
        assert decayed.id == entity.id

    def test_no_decay_when_just_observed(self):
        """Entities observed right now should have no decay."""
        current_time = time.time()
        entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.9,
            last_seen=current_time,
        )
        
        decayed = entity.apply_confidence_decay(current_time=current_time)
        
        assert decayed.confidence == pytest.approx(0.9, abs=1e-6)

    def test_decay_after_one_half_life(self):
        """After one half-life period, confidence should be ~50% of original."""
        current_time = time.time()
        half_life_days = 30.0
        # Entity was seen exactly 30 days ago
        past_time = current_time - (half_life_days * 86400)
        
        entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.8,
            last_seen=past_time,
        )
        
        decayed = entity.apply_confidence_decay(
            current_time=current_time,
            half_life_days=half_life_days,
        )
        
        expected = 0.8 * 0.5  # 0.4
        assert decayed.confidence == pytest.approx(expected, abs=0.01)

    def test_decay_after_two_half_lives(self):
        """After two half-lives, confidence should be ~25% of original."""
        current_time = time.time()
        half_life_days = 30.0
        past_time = current_time - (2 * half_life_days * 86400)
        
        entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.8,
            last_seen=past_time,
        )
        
        decayed = entity.apply_confidence_decay(
            current_time=current_time,
            half_life_days=half_life_days,
        )
        
        expected = 0.8 * (0.5 ** 2)  # 0.2
        assert decayed.confidence == pytest.approx(expected, abs=0.01)

    def test_decay_respects_min_confidence_floor(self):
        """Decay should stop at min_confidence floor."""
        current_time = time.time()
        half_life_days = 30.0
        # Very old observation (10 half-lives = 300 days)
        past_time = current_time - (10 * half_life_days * 86400)
        
        entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.9,
            last_seen=past_time,
        )
        
        decayed = entity.apply_confidence_decay(
            current_time=current_time,
            half_life_days=half_life_days,
            min_confidence=0.1,
        )
        
        # After 10 half-lives, natural decay would be 0.9 * (0.5 ** 10) ≈ 0.00088
        # But we enforce min_confidence=0.1
        assert decayed.confidence == pytest.approx(0.1, abs=1e-6)

    def test_decay_with_custom_half_life(self):
        """Different half_life values should produce different decay rates."""
        current_time = time.time()
        days_elapsed = 60.0
        past_time = current_time - (days_elapsed * 86400)
        
        entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.8,
            last_seen=past_time,
        )
        
        # Fast decay (15-day half-life)
        fast_decay = entity.apply_confidence_decay(
            current_time=current_time,
            half_life_days=15.0,
        )
        
        # Slow decay (120-day half-life)
        slow_decay = entity.apply_confidence_decay(
            current_time=current_time,
            half_life_days=120.0,
        )
        
        # Fast decay should reduce confidence more than slow decay
        assert fast_decay.confidence < slow_decay.confidence
        # With 60 days elapsed and 15-day half-life, that's 4 half-lives
        # 0.8 * (0.5 ** 4) = 0.05
        assert fast_decay.confidence == pytest.approx(0.1, abs=0.01)  # hitting floor
        # With 60 days and 120-day half-life, that's 0.5 half-lives
        # 0.8 * (0.5 ** 0.5) ≈ 0.566
        assert slow_decay.confidence == pytest.approx(0.566, abs=0.01)

    def test_decay_preserves_other_fields(self):
        """Decay should only modify confidence, leaving other fields unchanged."""
        current_time = time.time()
        past_time = current_time - (30 * 86400)
        
        entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.9,
            properties={"age": 30, "role": "engineer"},
            source_span=(10, 15),
            last_seen=past_time,
        )
        
        decayed = entity.apply_confidence_decay(current_time=current_time)
        
        assert decayed.id == "e1"
        assert decayed.type == "Person"
        assert decayed.text == "Alice"
        assert decayed.properties == {"age": 30, "role": "engineer"}
        assert decayed.source_span == (10, 15)
        assert decayed.last_seen == past_time  # timestamp preserved
        assert decayed.confidence < 0.9  # only confidence changed

    def test_decay_returns_new_instance(self):
        """apply_confidence_decay should return a new Entity, not modify in place."""
        current_time = time.time()
        past_time = current_time - (30 * 86400)
        
        original = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.9,
            last_seen=past_time,
        )
        
        decayed = original.apply_confidence_decay(current_time=current_time)
        
        # Original should be unchanged
        assert original.confidence == 0.9
        # Decayed should be different
        assert decayed is not original
        assert decayed.confidence < 0.9

    def test_decay_with_negative_elapsed_time(self):
        """If current_time < last_seen (clock skew), treat as no decay."""
        current_time = time.time()
        future_time = current_time + 3600  # 1 hour in the future
        
        entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.9,
            last_seen=future_time,
        )
        
        decayed = entity.apply_confidence_decay(current_time=current_time)
        
        # No decay should occur (max(0, elapsed) protects against negative)
        assert decayed.confidence == pytest.approx(0.9, abs=1e-6)

    def test_serialization_preserves_last_seen(self):
        """Entity.to_dict() and from_dict() should preserve last_seen."""
        current_time = time.time()
        entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.9,
            last_seen=current_time,
        )
        
        serialized = entity.to_dict()
        assert "last_seen" in serialized
        assert serialized["last_seen"] == current_time
        
        deserialized = Entity.from_dict(serialized)
        assert deserialized.last_seen == current_time

    def test_serialization_handles_none_last_seen(self):
        """Entity serialization should handle None last_seen gracefully."""
        entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.9,
            last_seen=None,
        )
        
        serialized = entity.to_dict()
        assert serialized["last_seen"] is None
        
        deserialized = Entity.from_dict(serialized)
        assert deserialized.last_seen is None

    def test_decay_with_very_small_half_life(self):
        """Decay with very short half-life should converge to min_confidence quickly."""
        current_time = time.time()
        past_time = current_time - (7 * 86400)  # 7 days ago
        
        entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.9,
            last_seen=past_time,
        )
        
        decayed = entity.apply_confidence_decay(
            current_time=current_time,
            half_life_days=1.0,  # Very aggressive: 1-day half-life
            min_confidence=0.05,
        )
        
        # After 7 days with 1-day half-life: 0.9 * (0.5 ** 7) ≈ 0.007
        # Should be clamped to 0.05
        assert decayed.confidence == pytest.approx(0.05, abs=1e-6)

    def test_decay_with_zero_confidence_entity(self):
        """Entity with zero confidence should remain at zero after decay."""
        current_time = time.time()
        past_time = current_time - (30 * 86400)
        
        entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.0,
            last_seen=past_time,
        )
        
        decayed = entity.apply_confidence_decay(
            current_time=current_time,
            min_confidence=0.0,
        )
        
        assert decayed.confidence == 0.0

    def test_extracted_entities_have_last_seen_timestamp(self):
        """Entities created by _extract_rule_based should have last_seen set."""
        from ipfs_datasets_py.optimizers.graphrag import (
            OntologyGenerator,
            OntologyGenerationContext,
        )
        
        generator = OntologyGenerator()
        context = OntologyGenerationContext(
            data_source="test.txt",
            data_type="text",
            domain="legal",
            extraction_strategy="rule_based",
        )
        
        text = "The plaintiff Alice Smith filed a lawsuit against Bob Corp."
        
        result = generator._extract_rule_based(text, context)
        
        # At least some entities should be extracted
        assert len(result.entities) > 0
        
        # All should have last_seen timestamps
        for entity in result.entities:
            assert entity.last_seen is not None
            assert isinstance(entity.last_seen, float)
            # Should be recent (within last minute)
            assert time.time() - entity.last_seen < 60

    def test_synthetic_ontology_entities_have_last_seen(self):
        """Synthetic ontology entities should have last_seen set."""
        from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator
        
        generator = OntologyGenerator()
        ontology = generator.generate_synthetic_ontology("legal", n_entities=3)
        
        assert len(ontology["entities"]) == 3
        
        for entity_dict in ontology["entities"]:
            assert "last_seen" in entity_dict
            assert isinstance(entity_dict["last_seen"], float)
            # Should be recent
            assert time.time() - entity_dict["last_seen"] < 60


class TestConfidenceDecayIntegration:
    """Integration tests for confidence decay in real workflows."""

    def test_decay_chain_multiple_applications(self):
        """Applying decay multiple times with same last_seen compounds from original timestamp."""
        current_time = time.time()
        entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.9,
            last_seen=current_time - (15 * 86400),  # 15 days ago
        )
        
        # Apply decay with 30-day half-life at current_time
        # After 15 days: 0.9 * (0.5 ** 0.5) ≈ 0.636
        decayed_1 = entity.apply_confidence_decay(
            current_time=current_time,
            half_life_days=30.0,
        )
        
        assert decayed_1.confidence == pytest.approx(0.636, abs=0.01)
        # Note: decayed_1.last_seen is still the original timestamp
        
        # Simulate another 15 days passing
        future_time = current_time + (15 * 86400)
        
        # Apply decay again
        # Now 30 days have elapsed from original last_seen
        # Decay is calculated from original timestamp: 0.636 * (0.5 ** 1.0) ≈ 0.318
        decayed_2 = decayed_1.apply_confidence_decay(
            current_time=future_time,
            half_life_days=30.0,
        )
        
        # The decay compounds on the already-decayed confidence, but uses original last_seen
        # So it's 0.636 * (0.5 ^ (15 days / 30 days)) = 0.636 * (0.5 ^ 0.5) ≈ 0.45
        # Actually no - decay uses last_seen, which is still 30 days before future_time
        # So it's 0.636 * (0.5 ^ 1.0) = 0.318
        assert decayed_2.confidence == pytest.approx(0.318, abs=0.01)

    def test_decay_does_not_affect_fresh_observations(self):
        """Updating last_seen and re-applying decay should prevent further decay."""
        current_time = time.time()
        old_entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.9,
            last_seen=current_time - (60 * 86400),  # 60 days ago
        )
        
        # Apply decay
        decayed = old_entity.apply_confidence_decay(current_time=current_time)
        assert decayed.confidence < 0.9
        
        # "Re-observe" the entity by updating last_seen
        fresh_entity = decayed.copy_with(last_seen=current_time)
        
        # Apply decay again immediately
        re_decayed = fresh_entity.apply_confidence_decay(current_time=current_time)
        
        # Should have no additional decay
        assert re_decayed.confidence == pytest.approx(fresh_entity.confidence, abs=1e-6)

    def test_batch_decay_application(self):
        """Apply decay to multiple entities at once."""
        current_time = time.time()
        entities = [
            Entity(
                id=f"e{i}",
                type="Person",
                text=f"Person{i}",
                confidence=0.9,
                last_seen=current_time - (i * 10 * 86400),  # 0, 10, 20, 30 days ago
            )
            for i in range(4)
        ]
        
        decayed_entities = [
            e.apply_confidence_decay(current_time=current_time, half_life_days=30.0)
            for e in entities
        ]
        
        # Entity 0 (just observed) should have no decay
        assert decayed_entities[0].confidence == pytest.approx(0.9, abs=1e-6)
        
        # Entity 1 (10 days ago) should have some decay
        assert decayed_entities[1].confidence < 0.9
        assert decayed_entities[1].confidence > decayed_entities[2].confidence
        
        # Entity 3 (30 days = one half-life) should be ~0.45
        assert decayed_entities[3].confidence == pytest.approx(0.45, abs=0.01)
        
        # Confidence should be monotonically decreasing with age
        for i in range(len(decayed_entities) - 1):
            assert decayed_entities[i].confidence >= decayed_entities[i + 1].confidence
