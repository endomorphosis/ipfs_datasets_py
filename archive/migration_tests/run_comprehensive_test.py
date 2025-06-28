#!/usr/bin/env python3
"""Run comprehensive MCP test and save results to file"""

import subprocess
import sys
import json
from pathlib import Path

def run_comprehensive_test():
    """Run the comprehensive test and capture results"""
    print("🚀 Running comprehensive MCP tools test...")
    
    try:
        # Run the comprehensive test
        result = subprocess.run(
            [str(Path.home() / "ipfs_datasets_py" / ".venv" / "bin" / "python"), 
             "complete_mcp_discovery_test.py"],
            cwd="/home/barberb/ipfs_datasets_py",
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        # Save output to file
        with open('/home/barberb/ipfs_datasets_py/comprehensive_test_output.txt', 'w') as f:
            f.write("STDOUT:\n")
            f.write(result.stdout)
            f.write("\n\nSTDERR:\n")
            f.write(result.stderr)
            f.write(f"\n\nReturn code: {result.returncode}")
        
        print("✅ Comprehensive test completed")
        print(f"📝 Output saved to comprehensive_test_output.txt")
        
        # Try to extract key metrics from output
        if "Success rate:" in result.stdout:
            lines = result.stdout.split('\n')
            for line in lines:
                if "Success rate:" in line:
                    print(f"📊 {line.strip()}")
                elif "Total tools discovered:" in line:
                    print(f"🔧 {line.strip()}")
                elif "Passed:" in line and "Failed:" in line:
                    print(f"✅ {line.strip()}")
        
        return result.returncode == 0
        
    except subprocess.TimeoutExpired:
        print("⏰ Test timed out after 5 minutes")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    success = run_comprehensive_test()
    exit(0 if success else 1)
