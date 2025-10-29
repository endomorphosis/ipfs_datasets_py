#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Basic integration test for medicine dashboard improvements.

This test verifies that the medical research scrapers and theorem framework
can be imported and instantiated correctly.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    
    # Test scraper imports
    from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.pubmed_scraper import PubMedScraper
    from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.clinical_trials_scraper import ClinicalTrialsScraper
    
    # Test theorem framework imports
    from ipfs_datasets_py.logic_integration.medical_theorem_framework import (
        MedicalTheorem,
        MedicalTheoremType,
        ConfidenceLevel,
        MedicalTheoremGenerator,
        FuzzyLogicValidator,
        TimeSeriesTheoremValidator
    )
    
    # Test MCP tools imports
    from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import (
        scrape_pubmed_medical_research,
        scrape_clinical_trials,
        scrape_biochemical_research
    )
    
    print("✅ All imports successful!")
    return True


def test_instantiation():
    """Test that classes can be instantiated."""
    print("\nTesting class instantiation...")
    
    from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.pubmed_scraper import PubMedScraper
    from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.clinical_trials_scraper import ClinicalTrialsScraper
    from ipfs_datasets_py.logic_integration.medical_theorem_framework import (
        MedicalTheoremGenerator,
        FuzzyLogicValidator,
        TimeSeriesTheoremValidator
    )
    
    # Instantiate scrapers
    pubmed_scraper = PubMedScraper(email="test@example.com")
    print(f"✅ PubMedScraper instantiated: {type(pubmed_scraper).__name__}")
    
    clinical_trials_scraper = ClinicalTrialsScraper()
    print(f"✅ ClinicalTrialsScraper instantiated: {type(clinical_trials_scraper).__name__}")
    
    # Instantiate theorem framework components
    theorem_generator = MedicalTheoremGenerator()
    print(f"✅ MedicalTheoremGenerator instantiated: {type(theorem_generator).__name__}")
    
    fuzzy_validator = FuzzyLogicValidator()
    print(f"✅ FuzzyLogicValidator instantiated: {type(fuzzy_validator).__name__}")
    
    ts_validator = TimeSeriesTheoremValidator()
    print(f"✅ TimeSeriesTheoremValidator instantiated: {type(ts_validator).__name__}")
    
    return True


def test_enum_values():
    """Test that enums are properly defined."""
    print("\nTesting enum values...")
    
    from ipfs_datasets_py.logic_integration.medical_theorem_framework import (
        MedicalTheoremType,
        ConfidenceLevel
    )
    
    # Test MedicalTheoremType
    theorem_types = [
        MedicalTheoremType.CAUSAL_RELATIONSHIP,
        MedicalTheoremType.RISK_ASSESSMENT,
        MedicalTheoremType.TREATMENT_OUTCOME,
        MedicalTheoremType.POPULATION_EFFECT,
        MedicalTheoremType.TEMPORAL_PROGRESSION,
        MedicalTheoremType.ADVERSE_EVENT
    ]
    print(f"✅ MedicalTheoremType has {len(theorem_types)} types")
    
    # Test ConfidenceLevel
    confidence_levels = [
        ConfidenceLevel.VERY_HIGH,
        ConfidenceLevel.HIGH,
        ConfidenceLevel.MODERATE,
        ConfidenceLevel.LOW,
        ConfidenceLevel.VERY_LOW
    ]
    print(f"✅ ConfidenceLevel has {len(confidence_levels)} levels")
    
    return True


def test_mcp_tool_signatures():
    """Test that MCP tools have correct signatures."""
    print("\nTesting MCP tool signatures...")
    
    from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import (
        scrape_pubmed_medical_research,
        scrape_clinical_trials,
        scrape_biochemical_research,
        generate_medical_theorems_from_trials,
        validate_medical_theorem_fuzzy,
        scrape_population_health_data
    )
    
    import inspect
    
    # Check scrape_pubmed_medical_research
    sig = inspect.signature(scrape_pubmed_medical_research)
    assert 'query' in sig.parameters
    assert 'max_results' in sig.parameters
    print(f"✅ scrape_pubmed_medical_research has correct signature")
    
    # Check scrape_clinical_trials
    sig = inspect.signature(scrape_clinical_trials)
    assert 'query' in sig.parameters
    assert 'condition' in sig.parameters
    print(f"✅ scrape_clinical_trials has correct signature")
    
    # Check generate_medical_theorems_from_trials
    sig = inspect.signature(generate_medical_theorems_from_trials)
    assert 'trial_data' in sig.parameters
    assert 'outcomes_data' in sig.parameters
    print(f"✅ generate_medical_theorems_from_trials has correct signature")
    
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("Medicine Dashboard Integration Tests")
    print("=" * 60)
    
    tests = [
        ("Import Test", test_imports),
        ("Instantiation Test", test_instantiation),
        ("Enum Values Test", test_enum_values),
        ("MCP Tool Signatures Test", test_mcp_tool_signatures)
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"❌ {name} failed: {e}")
            failed += 1
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed == 0:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
