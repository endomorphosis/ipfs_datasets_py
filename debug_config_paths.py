#!/usr/bin/env python3
"""
Debug config path resolution
"""
import sys
import os
sys.path.insert(0, '.')

print("Debugging config path resolution...")

# Import config module directly
sys.path.insert(0, './ipfs_datasets_py/')
import config as config_module

print("Creating config class...")
Config = config_module.config

print("Check current working directory:", os.getcwd())
print("Checking available config files...")

# Check all the paths the findConfig method would check
import os
test_paths = [
    './config.toml',
    '../config.toml', 
    '../config/config.toml',
    './config/config.toml'
]

this_dir = os.path.dirname(os.path.realpath('./ipfs_datasets_py/config.py'))
print(f"this_dir would be: {this_dir}")

for path in test_paths:
    this_path = os.path.realpath(os.path.join(this_dir, path))
    exists = os.path.exists(this_path)
    print(f"Path: {path} -> {this_path} -> exists: {exists}")

# Check specific config file locations
print("\nChecking specific config locations:")
print(f"./config/config.toml exists: {os.path.exists('./config/config.toml')}")
print(f"./config/config.toml realpath: {os.path.realpath('./config/config.toml')}")

# Test the findConfig method
try:
    dummy_config = Config.__new__(Config)  # Create without calling __init__
    found_path = dummy_config.findConfig()
    print(f"findConfig() would return: {found_path}")
except Exception as e:
    print(f"findConfig() failed: {e}")

print("\nNow testing actual instantiation...")
try:
    config_instance = Config()
    print("✅ Config instantiated successfully!")
except SystemExit as e:
    print(f"❌ Config instantiation called exit({e.code})")
except Exception as e:
    print(f"❌ Config instantiation failed: {e}")
    import traceback
    traceback.print_exc()
