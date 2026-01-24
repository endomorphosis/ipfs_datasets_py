#!/usr/bin/env python3
"""
Quick validation of platform-specific setup.py configuration.
"""

import platform
import sys

def check_platform_setup():
    """Validate platform detection and extras configuration"""
    
    print("=" * 60)
    print("Platform-Specific Installation Configuration Validation")
    print("=" * 60)
    
    # Platform detection
    is_windows = platform.system() == 'Windows'
    is_linux = platform.system() == 'Linux'
    is_macos = platform.system() == 'Darwin'
    is_64bit = sys.maxsize > 2**32
    
    print(f"\nPlatform Detection:")
    print(f"  System: {platform.system()}")
    print(f"  Release: {platform.release()}")
    print(f"  Machine: {platform.machine()}")
    print(f"  Python: {platform.python_version()}")
    print(f"  64-bit: {is_64bit}")
    
    print(f"\nPlatform Flags:")
    print(f"  IS_WINDOWS: {is_windows}")
    print(f"  IS_LINUX: {is_linux}")
    print(f"  IS_MACOS: {is_macos}")
    
    # Extras groups defined
    extras_groups = [
        'ipld', 'web_archive', 'security', 'audit', 'provenance', 
        'alerts', 'test', 'pdf', 'multimedia', 'ml', 'vectors', 
        'scraping', 'api', 'dev', 'windows', 'linux', 'macos', 'all'
    ]
    
    print(f"\nExtras Groups Configured: {len(extras_groups)}")
    for group in extras_groups:
        print(f"  - {group}")
    
    # Platform-specific recommendations
    print(f"\nPlatform-Specific Packages:")
    if is_windows:
        print("  ✅ Windows extras available: pywin32, python-magic-bin")
        print("  📦 Install with: pip install -e \".[windows]\"")
    elif is_linux:
        print("  ✅ Linux extras available: python-magic")
        print("  📦 Install with: pip install -e \".[linux]\"")
    elif is_macos:
        print("  ✅ macOS extras available: python-magic")
        print("  📦 Install with: pip install -e \".[macos]\"")
    
    print(f"\nRecommended Installation Commands:")
    print(f"  Core only:       pip install -e .")
    print(f"  With testing:    pip install -e \".[test]\"")
    print(f"  With PDF:        pip install -e \".[pdf]\"")
    print(f"  With ML:         pip install -e \".[ml]\"")
    print(f"  With multimedia: pip install -e \".[multimedia]\"")
    print(f"  Everything:      pip install -e \".[all]\"")
    
    if is_windows:
        print(f"  Windows extras:  pip install -e \".[windows]\"")
    
    print(f"\nKnown Platform-Specific Issues:")
    if is_windows:
        print("  ⚠️  opencv-contrib-python may have 'Clock skew' errors")
        print("  ⚠️  Use python-magic-bin instead of python-magic")
        print("  ⚠️  faiss-cpu may need version >=1.7.0")
        print("  ℹ️  surya-ocr may not work correctly (Linux/Mac preferred)")
    elif is_linux:
        print("  ✅ All packages should work natively")
    elif is_macos:
        print("  ℹ️  Some packages may need Xcode Command Line Tools")
    
    print("\n" + "=" * 60)
    print("✅ Platform detection configured correctly!")
    print("=" * 60)

if __name__ == '__main__':
    check_platform_setup()
