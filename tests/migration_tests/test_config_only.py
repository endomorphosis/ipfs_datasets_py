#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, '.')

print("Testing config loading...")
print("Current working directory:", os.getcwd())
print("Python path:", sys.path[:3])

try:
    print("Step 1: Import os and toml")
    import toml
    print("✅ toml imported successfully")
    
    print("Step 2: Import config module")
    from ipfs_datasets_py import config as config_module
    print("✅ config module imported successfully")
    
    print("Step 3: Access config class")
    Config = config_module.config
    print("✅ config class accessed successfully")
    
    print("Step 4: Instantiate config")
    config_instance = Config()
    print("✅ Config instantiated successfully")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
