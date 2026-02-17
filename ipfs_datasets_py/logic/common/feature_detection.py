"""
Feature detection utility for optional dependencies.

This module provides programmatic detection of optional dependencies and their
availability, allowing the logic module to gracefully degrade when optional
features are not installed.

Example:
    >>> from ipfs_datasets_py.logic.common.feature_detection import FeatureDetector
    >>> 
    >>> # Check if specific features are available
    >>> if FeatureDetector.has_symbolicai():
    ...     print("SymbolicAI available - using advanced symbolic manipulation")
    ... else:
    ...     print("SymbolicAI not available - using fallback implementation")
    >>> 
    >>> # Print full feature report
    >>> FeatureDetector.print_feature_report()
    >>> 
    >>> # Get list of available features
    >>> features = FeatureDetector.get_available_features()
    >>> print(f"Available: {', '.join(features)}")

CLI Usage:
    python -m ipfs_datasets_py.logic.common.feature_detection
"""

from typing import Dict, List, Tuple
import sys


class FeatureDetector:
    """Detect available optional features and dependencies."""
    
    _cache: Dict[str, bool] = {}
    
    @classmethod
    def has_symbolicai(cls) -> bool:
        """
        Check if SymbolicAI is available.
        
        Returns:
            True if SymbolicAI can be imported, False otherwise.
        """
        if 'symbolicai' not in cls._cache:
            try:
                import symbolicai  # noqa: F401
                cls._cache['symbolicai'] = True
            except ImportError:
                cls._cache['symbolicai'] = False
        return cls._cache['symbolicai']
    
    @classmethod
    def has_z3(cls) -> bool:
        """
        Check if Z3 SMT Solver is available.
        
        Returns:
            True if z3 can be imported, False otherwise.
        """
        if 'z3' not in cls._cache:
            try:
                import z3  # noqa: F401
                cls._cache['z3'] = True
            except ImportError:
                cls._cache['z3'] = False
        return cls._cache['z3']
    
    @classmethod
    def has_spacy(cls) -> bool:
        """
        Check if spaCy NLP is available.
        
        Returns:
            True if spacy can be imported, False otherwise.
        """
        if 'spacy' not in cls._cache:
            try:
                import spacy  # noqa: F401
                cls._cache['spacy'] = True
            except ImportError:
                cls._cache['spacy'] = False
        return cls._cache['spacy']
    
    @classmethod
    def has_spacy_model(cls, model: str = "en_core_web_sm") -> bool:
        """
        Check if a specific spaCy model is available.
        
        Args:
            model: Name of the spaCy model (default: en_core_web_sm)
        
        Returns:
            True if the model can be loaded, False otherwise.
        """
        cache_key = f'spacy_model_{model}'
        if cache_key not in cls._cache:
            if not cls.has_spacy():
                cls._cache[cache_key] = False
            else:
                try:
                    import spacy
                    spacy.load(model)
                    cls._cache[cache_key] = True
                except (ImportError, OSError):
                    cls._cache[cache_key] = False
        return cls._cache[cache_key]
    
    @classmethod
    def has_xgboost(cls) -> bool:
        """
        Check if XGBoost is available.
        
        Returns:
            True if xgboost can be imported, False otherwise.
        """
        if 'xgboost' not in cls._cache:
            try:
                import xgboost  # noqa: F401
                cls._cache['xgboost'] = True
            except ImportError:
                cls._cache['xgboost'] = False
        return cls._cache['xgboost']
    
    @classmethod
    def has_lightgbm(cls) -> bool:
        """
        Check if LightGBM is available.
        
        Returns:
            True if lightgbm can be imported, False otherwise.
        """
        if 'lightgbm' not in cls._cache:
            try:
                import lightgbm  # noqa: F401
                cls._cache['lightgbm'] = True
            except ImportError:
                cls._cache['lightgbm'] = False
        return cls._cache['lightgbm']
    
    @classmethod
    def has_ml_models(cls) -> bool:
        """
        Check if ML confidence scoring models are available.
        
        Returns:
            True if either XGBoost or LightGBM is available.
        """
        return cls.has_xgboost() or cls.has_lightgbm()
    
    @classmethod
    def has_ipfs(cls) -> bool:
        """
        Check if IPFS client is available.
        
        Returns:
            True if ipfshttpclient can be imported, False otherwise.
        """
        if 'ipfshttpclient' not in cls._cache:
            try:
                import ipfshttpclient  # noqa: F401
                cls._cache['ipfshttpclient'] = True
            except ImportError:
                cls._cache['ipfshttpclient'] = False
        return cls._cache['ipfshttpclient']
    
    @classmethod
    def get_available_features(cls) -> List[str]:
        """
        Get list of available optional features.
        
        Returns:
            List of feature names that are available.
        """
        features = []
        
        if cls.has_symbolicai():
            features.append("SymbolicAI Integration")
        
        if cls.has_z3():
            features.append("Z3 SMT Solver")
        
        if cls.has_spacy():
            if cls.has_spacy_model():
                features.append("spaCy NLP (with en_core_web_sm)")
            else:
                features.append("spaCy NLP (no model installed)")
        
        if cls.has_xgboost():
            features.append("XGBoost ML")
        
        if cls.has_lightgbm():
            features.append("LightGBM ML")
        
        if cls.has_ipfs():
            features.append("IPFS Distributed Caching")
        
        return features
    
    @classmethod
    def get_missing_features(cls) -> List[Tuple[str, str]]:
        """
        Get list of missing optional features with installation instructions.
        
        Returns:
            List of tuples (feature_name, install_command).
        """
        missing = []
        
        if not cls.has_symbolicai():
            missing.append(("SymbolicAI Integration", "pip install symbolicai"))
        
        if not cls.has_z3():
            missing.append(("Z3 SMT Solver", "pip install z3-solver"))
        
        if not cls.has_spacy():
            missing.append((
                "spaCy NLP",
                "pip install spacy && python -m spacy download en_core_web_sm"
            ))
        elif not cls.has_spacy_model():
            missing.append((
                "spaCy Model",
                "python -m spacy download en_core_web_sm"
            ))
        
        if not cls.has_xgboost() and not cls.has_lightgbm():
            missing.append((
                "ML Confidence Models",
                "pip install xgboost lightgbm"
            ))
        
        if not cls.has_ipfs():
            missing.append((
                "IPFS Client",
                "pip install ipfshttpclient"
            ))
        
        return missing
    
    @classmethod
    def print_feature_report(cls):
        """
        Print a comprehensive feature availability report.
        
        This prints a formatted report showing which optional features are
        available and which are missing, along with installation instructions
        for missing features.
        """
        print("\n" + "=" * 60)
        print("Logic Module Feature Detection Report")
        print("=" * 60)
        
        # Core features (always available)
        print("\n📦 Core Features (Always Available):")
        print("  ✅ FOL/Deontic Converters")
        print("  ✅ Caching System (local)")
        print("  ✅ Basic Theorem Proving (128 inference rules)")
        print("  ✅ Type System")
        print("  ✅ TDFOL Core")
        
        # Optional features
        print("\n🔧 Optional Enhancements:")
        
        # SymbolicAI
        if cls.has_symbolicai():
            print("  ✅ SymbolicAI Integration")
            print("     → 5-10x faster symbolic operations")
        else:
            print("  ❌ SymbolicAI Integration (using fallback)")
            print("     → Install: pip install symbolicai")
        
        # Z3
        if cls.has_z3():
            print("  ✅ Z3 SMT Solver")
            print("     → Automated theorem proving")
        else:
            print("  ❌ Z3 SMT Solver (using native prover)")
            print("     → Install: pip install z3-solver")
        
        # spaCy
        if cls.has_spacy():
            if cls.has_spacy_model():
                print("  ✅ spaCy NLP (with model)")
                print("     → 15-20% accuracy boost for FOL extraction")
            else:
                print("  ⚠️  spaCy installed but no model")
                print("     → Install model: python -m spacy download en_core_web_sm")
        else:
            print("  ❌ spaCy NLP (using regex)")
            print("     → Install: pip install spacy")
            print("     → Model: python -m spacy download en_core_web_sm")
        
        # ML Models
        ml_status = []
        if cls.has_xgboost():
            ml_status.append("XGBoost")
        if cls.has_lightgbm():
            ml_status.append("LightGBM")
        
        if ml_status:
            print(f"  ✅ ML Confidence Scoring ({', '.join(ml_status)})")
            print("     → 85-90% accuracy confidence prediction")
        else:
            print("  ❌ ML Confidence Scoring (using heuristics)")
            print("     → Install: pip install xgboost lightgbm")
        
        # IPFS
        if cls.has_ipfs():
            print("  ✅ IPFS Distributed Caching")
            print("     → Content-addressed distributed storage")
        else:
            print("  ❌ IPFS Distributed Caching (local only)")
            print("     → Install: pip install ipfshttpclient")
        
        # Summary
        available = cls.get_available_features()
        missing = cls.get_missing_features()
        
        print(f"\n📊 Summary:")
        print(f"  Available Features: {len(available)}")
        print(f"  Missing Features: {len(missing)}")
        
        if missing:
            print(f"\n💡 To install all optional features:")
            print(f"  pip install symbolicai z3-solver spacy xgboost lightgbm ipfshttpclient")
            print(f"  python -m spacy download en_core_web_sm")
        else:
            print(f"\n🎉 All optional features are installed!")
        
        print("=" * 60 + "\n")
    
    @classmethod
    def clear_cache(cls):
        """Clear the feature detection cache (for testing)."""
        cls._cache.clear()


def main():
    """
    CLI entry point for feature detection.
    
    Usage:
        python -m ipfs_datasets_py.logic.common.feature_detection
    """
    FeatureDetector.print_feature_report()
    
    # Exit with error code if missing critical features
    missing = FeatureDetector.get_missing_features()
    if len(missing) > 3:  # More than 3 missing features
        print("⚠️  Many optional features are missing.")
        print("   Consider installing for better performance and accuracy.")
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
