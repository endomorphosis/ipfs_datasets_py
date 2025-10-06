#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, '.')

print("Testing direct config.py import...")

try:
    print("Step 1: Direct import of config.py file")
    sys.path.insert(0, './ipfs_datasets_py/')
    import config as config_direct
    print("✅ Direct config.py import successful")
    
    print("Step 2: Access config class")
    Config = config_direct.config
    print("✅ config class accessed")
    
    print("Step 3: Try to instantiate")
    config_instance = Config()
    print("✅ Config instantiated successfully")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
