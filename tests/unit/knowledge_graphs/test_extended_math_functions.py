"""
Tests for Cypher extended math functions.

Tests the extended math functions:
- Trigonometric: sin, cos, tan, asin, acos, atan, atan2
- Logarithmic: log, log10, exp
- Constants: pi, e
"""

import pytest
import math
from ipfs_datasets_py.knowledge_graphs.cypher.functions import (
    fn_sin,
    fn_cos,
    fn_tan,
    fn_asin,
    fn_acos,
    fn_atan,
    fn_atan2,
    fn_log,
    fn_log10,
    fn_exp,
    fn_pi,
    fn_e,
    evaluate_function
)


class TestTrigonometricFunctions:
    """Tests for trigonometric functions."""
    
    def test_sin_basic(self):
        """Test sine function."""
        assert fn_sin(0) == 0
        assert abs(fn_sin(math.pi / 2) - 1.0) < 1e-10
        assert abs(fn_sin(math.pi)) < 1e-10
    
    def test_cos_basic(self):
        """Test cosine function."""
        assert fn_cos(0) == 1.0
        assert abs(fn_cos(math.pi / 2)) < 1e-10
        assert abs(fn_cos(math.pi) - (-1.0)) < 1e-10
    
    def test_tan_basic(self):
        """Test tangent function."""
        assert fn_tan(0) == 0
        assert abs(fn_tan(math.pi / 4) - 1.0) < 1e-10
    
    def test_asin_basic(self):
        """Test arc sine function."""
        assert fn_asin(0) == 0
        assert abs(fn_asin(1) - math.pi / 2) < 1e-10
        assert abs(fn_asin(-1) + math.pi / 2) < 1e-10
    
    def test_acos_basic(self):
        """Test arc cosine function."""
        assert abs(fn_acos(1)) < 1e-10
        assert abs(fn_acos(0) - math.pi / 2) < 1e-10
        assert abs(fn_acos(-1) - math.pi) < 1e-10
    
    def test_atan_basic(self):
        """Test arc tangent function."""
        assert fn_atan(0) == 0
        assert abs(fn_atan(1) - math.pi / 4) < 1e-10
    
    def test_atan2_basic(self):
        """Test atan2 function."""
        assert abs(fn_atan2(1, 1) - math.pi / 4) < 1e-10
        assert abs(fn_atan2(1, 0) - math.pi / 2) < 1e-10
        assert abs(fn_atan2(0, 1)) < 1e-10
    
    def test_sin_null(self):
        """Test sin with NULL."""
        assert fn_sin(None) is None
    
    def test_cos_null(self):
        """Test cos with NULL."""
        assert fn_cos(None) is None
    
    def test_tan_null(self):
        """Test tan with NULL."""
        assert fn_tan(None) is None
    
    def test_asin_null(self):
        """Test asin with NULL."""
        assert fn_asin(None) is None
    
    def test_acos_null(self):
        """Test acos with NULL."""
        assert fn_acos(None) is None
    
    def test_atan_null(self):
        """Test atan with NULL."""
        assert fn_atan(None) is None
    
    def test_atan2_null_y(self):
        """Test atan2 with NULL y."""
        assert fn_atan2(None, 1) is None
    
    def test_atan2_null_x(self):
        """Test atan2 with NULL x."""
        assert fn_atan2(1, None) is None
    
    def test_sin_via_registry(self):
        """Test sin via function registry."""
        result = evaluate_function('sin', 0)
        assert result == 0
    
    def test_cos_via_registry(self):
        """Test cos via function registry."""
        result = evaluate_function('cos', 0)
        assert result == 1.0
    
    def test_atan2_via_registry(self):
        """Test atan2 via function registry."""
        result = evaluate_function('atan2', 1, 1)
        assert abs(result - math.pi / 4) < 1e-10


class TestLogarithmicFunctions:
    """Tests for logarithmic and exponential functions."""
    
    def test_log_basic(self):
        """Test natural logarithm."""
        assert abs(fn_log(math.e) - 1.0) < 1e-10
        assert abs(fn_log(1)) < 1e-10
        assert abs(fn_log(math.e ** 2) - 2.0) < 1e-10
    
    def test_log10_basic(self):
        """Test base-10 logarithm."""
        assert fn_log10(1) == 0
        assert fn_log10(10) == 1.0
        assert fn_log10(100) == 2.0
        assert fn_log10(1000) == 3.0
    
    def test_exp_basic(self):
        """Test exponential function."""
        assert fn_exp(0) == 1.0
        assert abs(fn_exp(1) - math.e) < 1e-10
        assert abs(fn_exp(2) - math.e ** 2) < 1e-10
    
    def test_log_null(self):
        """Test log with NULL."""
        assert fn_log(None) is None
    
    def test_log10_null(self):
        """Test log10 with NULL."""
        assert fn_log10(None) is None
    
    def test_exp_null(self):
        """Test exp with NULL."""
        assert fn_exp(None) is None
    
    def test_log_via_registry(self):
        """Test log via function registry."""
        result = evaluate_function('log', math.e)
        assert abs(result - 1.0) < 1e-10
    
    def test_log10_via_registry(self):
        """Test log10 via function registry."""
        result = evaluate_function('log10', 100)
        assert result == 2.0
    
    def test_exp_via_registry(self):
        """Test exp via function registry."""
        result = evaluate_function('exp', 0)
        assert result == 1.0


class TestMathConstants:
    """Tests for mathematical constants."""
    
    def test_pi_value(self):
        """Test pi constant."""
        assert fn_pi() == math.pi
        assert abs(fn_pi() - 3.141592653589793) < 1e-10
    
    def test_e_value(self):
        """Test e constant."""
        assert fn_e() == math.e
        assert abs(fn_e() - 2.718281828459045) < 1e-10
    
    def test_pi_via_registry(self):
        """Test pi via function registry."""
        result = evaluate_function('pi')
        assert result == math.pi
    
    def test_e_via_registry(self):
        """Test e via function registry."""
        result = evaluate_function('e')
        assert result == math.e


class TestExtendedMathIntegration:
    """Integration tests for extended math functions."""
    
    def test_pythagorean_identity(self):
        """Test sin²(x) + cos²(x) = 1."""
        x = math.pi / 3
        sin_x = fn_sin(x)
        cos_x = fn_cos(x)
        assert abs(sin_x ** 2 + cos_x ** 2 - 1.0) < 1e-10
    
    def test_exp_log_inverse(self):
        """Test that exp and log are inverses."""
        x = 5.0
        assert abs(fn_log(fn_exp(x)) - x) < 1e-10
        assert abs(fn_exp(fn_log(x)) - x) < 1e-10
    
    def test_log10_relationship(self):
        """Test log10(x) = log(x) / log(10)."""
        x = 42.0
        log10_x = fn_log10(x)
        log_x = fn_log(x)
        log_10 = fn_log(10)
        assert abs(log10_x - (log_x / log_10)) < 1e-10
    
    def test_atan2_quadrants(self):
        """Test atan2 in all quadrants."""
        # First quadrant
        assert fn_atan2(1, 1) > 0
        # Second quadrant
        assert fn_atan2(1, -1) > math.pi / 2
        # Third quadrant
        assert fn_atan2(-1, -1) < 0
        # Fourth quadrant
        assert fn_atan2(-1, 1) < 0
    
    def test_trig_with_pi(self):
        """Test trigonometric functions with pi constant."""
        pi = fn_pi()
        assert abs(fn_sin(pi)) < 1e-10
        assert abs(fn_cos(pi) - (-1.0)) < 1e-10
        assert abs(fn_tan(pi)) < 1e-10
    
    def test_exp_with_e(self):
        """Test exp with e constant."""
        e = fn_e()
        assert abs(fn_exp(1) - e) < 1e-10
        assert abs(fn_log(e) - 1.0) < 1e-10


class TestEdgeCases:
    """Test edge cases for extended math functions."""
    
    def test_asin_bounds(self):
        """Test asin at boundary values."""
        assert fn_asin(-1) is not None
        assert fn_asin(1) is not None
        
        # Out of bounds should raise ValueError
        with pytest.raises(ValueError):
            fn_asin(2)
        with pytest.raises(ValueError):
            fn_asin(-2)
    
    def test_acos_bounds(self):
        """Test acos at boundary values."""
        assert fn_acos(-1) is not None
        assert fn_acos(1) is not None
        
        # Out of bounds should raise ValueError
        with pytest.raises(ValueError):
            fn_acos(2)
        with pytest.raises(ValueError):
            fn_acos(-2)
    
    def test_log_negative(self):
        """Test log with negative input."""
        with pytest.raises(ValueError):
            fn_log(-1)
    
    def test_log10_negative(self):
        """Test log10 with negative input."""
        with pytest.raises(ValueError):
            fn_log10(-1)
    
    def test_log_zero(self):
        """Test log with zero."""
        with pytest.raises(ValueError):
            fn_log(0)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
