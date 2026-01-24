#!/usr/bin/env python3
"""
Unified verification runner for US Code and Federal Register scrapers.

This script runs both verification tools and provides a combined summary.
"""
import anyio
import sys
import subprocess
from pathlib import Path
from datetime import datetime


def run_verification(script_name: str) -> tuple[int, str]:
    """Run a verification script and capture output."""
    script_path = Path(__file__).parent / script_name
    
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return 1, f"ERROR: {script_name} timed out after 5 minutes"
    except Exception as e:
        return 1, f"ERROR: Failed to run {script_name}: {e}"


def main():
    """Run all verifications."""
    print("="*80)
    print("LEGAL DATASET TOOLS VERIFICATION SUITE")
    print("="*80)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Run US Code verification
    print("\n" + "="*80)
    print("RUNNING: US Code Scraper Verification")
    print("="*80)
    us_code_exit, us_code_output = run_verification("verify_us_code_scraper.py")
    print(us_code_output)
    
    # Run Federal Register verification
    print("\n" + "="*80)
    print("RUNNING: Federal Register Scraper Verification")
    print("="*80)
    fed_reg_exit, fed_reg_output = run_verification("verify_federal_register_scraper.py")
    print(fed_reg_output)
    
    # Combined summary
    print("\n" + "="*80)
    print("COMBINED VERIFICATION SUMMARY")
    print("="*80)
    
    us_code_status = "✅ PASSED" if us_code_exit == 0 else "❌ FAILED"
    fed_reg_status = "✅ PASSED" if fed_reg_exit == 0 else "❌ FAILED"
    
    print(f"US Code Scraper:       {us_code_status}")
    print(f"Federal Register:      {fed_reg_status}")
    
    overall_exit = 0 if (us_code_exit == 0 and fed_reg_exit == 0) else 1
    overall_status = "✅ ALL TESTS PASSED" if overall_exit == 0 else "❌ SOME TESTS FAILED"
    
    print(f"\nOverall Status:        {overall_status}")
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return overall_exit


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nVerification cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Verification suite failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
