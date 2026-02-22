"""Batch-127 feature tests.

Methods under test:
  - ExtractionConfig.threshold_distance(other)
  - ExtractionConfig.is_stricter_than(other)
  - ExtractionConfig.is_looser_than(other)
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(threshold):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
    return ExtractionConfig(confidence_threshold=threshold)


# ---------------------------------------------------------------------------
# ExtractionConfig.threshold_distance
# ---------------------------------------------------------------------------

class TestThresholdDistance:
    def test_equal_configs(self):
        a = _cfg(0.5)
        b = _cfg(0.5)
        assert a.threshold_distance(b) == pytest.approx(0.0)

    def test_a_higher(self):
        a = _cfg(0.8)
        b = _cfg(0.5)
        assert a.threshold_distance(b) == pytest.approx(0.3)

    def test_b_higher(self):
        a = _cfg(0.3)
        b = _cfg(0.7)
        assert a.threshold_distance(b) == pytest.approx(0.4)

    def test_always_positive(self):
        a = _cfg(0.9)
        b = _cfg(0.1)
        assert a.threshold_distance(b) > 0.0
        assert b.threshold_distance(a) > 0.0
        assert a.threshold_distance(b) == b.threshold_distance(a)


# ---------------------------------------------------------------------------
# ExtractionConfig.is_stricter_than
# ---------------------------------------------------------------------------

class TestIsStricterThan:
    def test_true_when_higher_threshold(self):
        a = _cfg(0.8)
        b = _cfg(0.5)
        assert a.is_stricter_than(b) is True

    def test_false_when_equal(self):
        a = _cfg(0.5)
        b = _cfg(0.5)
        assert a.is_stricter_than(b) is False

    def test_false_when_lower_threshold(self):
        a = _cfg(0.3)
        b = _cfg(0.7)
        assert a.is_stricter_than(b) is False


# ---------------------------------------------------------------------------
# ExtractionConfig.is_looser_than
# ---------------------------------------------------------------------------

class TestIsLooserThan:
    def test_true_when_lower_threshold(self):
        a = _cfg(0.3)
        b = _cfg(0.7)
        assert a.is_looser_than(b) is True

    def test_false_when_equal(self):
        a = _cfg(0.5)
        b = _cfg(0.5)
        assert a.is_looser_than(b) is False

    def test_false_when_higher_threshold(self):
        a = _cfg(0.8)
        b = _cfg(0.5)
        assert a.is_looser_than(b) is False

    def test_inverse_of_stricter(self):
        a = _cfg(0.3)
        b = _cfg(0.7)
        assert a.is_looser_than(b) is True
        assert b.is_stricter_than(a) is True
