#!/usr/bin/env python3
"""
Quick test of sample states to verify scraping and parquet saving works.

This script tests a representative sample of states (5 states) to quickly verify:
1. Scrapers can process real webpages
2. Data can be saved to parquet files
3. Schema validation works correctly

Use this before running the full test_all_states_with_parquet.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from test_all_states_with_parquet import StateLawsTester


async def test_sample():
    """Test a sample of 5 representative states."""
    print("="*80)
    print("QUICK SAMPLE TEST - 5 Representative States")
    print("="*80)
    
    # Sample states representing different regions and implementations
    sample_states = {
        "CA": "California",      # Large state, detailed implementation
        "NY": "New York",        # Large state, detailed implementation
        "TX": "Texas",           # Large state, detailed implementation
        "IL": "Illinois",        # Medium state
        "WY": "Wyoming"          # Small state
    }
    
    print(f"\nTesting {len(sample_states)} states:")
    for code, name in sample_states.items():
        print(f"  - {code}: {name}")
    
    # Create tester
    tester = StateLawsTester(
        output_dir="~/.ipfs_datasets/state_laws/test_samples_quick"
    )
    
    # Test each sample state
    results = {}
    for state_code, state_name in sample_states.items():
        result = await tester.test_state_scraper(state_code, state_name)
        results[state_code] = result
        tester.results[state_code] = result
    
    # Generate summary
    tester._generate_summary_report()
    
    return tester


if __name__ == "__main__":
    print("\nRunning quick sample test...")
    print("This tests 5 representative states to verify functionality.\n")
    
    tester = asyncio.run(test_sample())
    
    # Check results
    failed = sum(1 for r in tester.results.values() if not r['success'])
    
    if failed == 0:
        print("\n✅ Sample test passed! Ready to run full test.")
        print("\nTo test all 51 states, run:")
        print("  python test_all_states_with_parquet.py")
    else:
        print(f"\n⚠️  {failed} states failed in sample test.")
        print("Please review errors before running full test.")
    
    sys.exit(0 if failed == 0 else 1)
