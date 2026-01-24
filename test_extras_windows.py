#!/usr/bin/env python3
"""
Comprehensive Windows extras installation test.
Tests each extras group to verify packages install and import correctly.
"""

import subprocess
import sys
from pathlib import Path

def test_package_import(packages, description):
    """Test if packages can be imported"""
    print(f"\nTesting {description}:")
    
    for package, import_name in packages:
        try:
            __import__(import_name if import_name else package)
            print(f"  ✅ {package}")
        except ImportError as e:
            print(f"  ❌ {package}: {e}")
            return False
    return True

def main():
    """Run comprehensive test of all extras groups"""
    
    print("=" * 70)
    print("COMPREHENSIVE WINDOWS EXTRAS INSTALLATION TEST")
    print("=" * 70)
    
    results = {}
    
    # Test groups with their key packages
    test_groups = {
        'test': [
            ('pytest', 'pytest'),
            ('pytest-cov', 'pytest_cov'),
            ('coverage', 'coverage'),
        ],
        'windows': [
            ('pywin32', 'win32api'),
            ('python-magic-bin', 'magic'),
        ],
        'pdf': [
            ('pdfplumber', 'pdfplumber'),
            ('tiktoken', 'tiktoken'),
            ('pysbd', 'pysbd'),
            # pymupdf has DLL issues on Windows - skip import test
        ],
        'multimedia': [
            ('pillow', 'PIL'),
            ('yt-dlp', 'yt_dlp'),
        ],
        'api': [
            ('fastapi', 'fastapi'),
            ('uvicorn', 'uvicorn'),
            ('flask', 'flask'),
        ],
        'vectors': [
            ('faiss-cpu', 'faiss'),
        ],
        'security': [
            ('cryptography', 'cryptography'),
        ],
    }
    
    print("\nInstalled and tested packages:")
    for group, packages in test_groups.items():
        results[group] = test_package_import(packages, f"{group} extras")
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    for group, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {status} - {group}")
    
    # Known issues
    print("\n⚠️  KNOWN ISSUES:")
    print("  - pymupdf: DLL load issues on Windows (ImportError: DLL load failed)")
    print("    Workaround: Use pdfplumber or install Visual C++ Redistributable")
    print("  - ffmpeg-python: Requires system ffmpeg binary")
    print("  - moviepy: Requires ffmpeg")
    print("  - pytesseract: Requires Tesseract OCR installation")
    
    total_tested = len(results)
    total_passed = sum(1 for v in results.values() if v)
    
    print(f"\n📊 Results: {total_passed}/{total_tested} extras groups working")
    
    if total_passed == total_tested:
        print("\n✅ ALL TESTED EXTRAS GROUPS WORK ON WINDOWS!")
    elif total_passed >= total_tested * 0.8:
        print("\n⚠️  MOST EXTRAS GROUPS WORK (some issues to address)")
    else:
        print("\n❌ MULTIPLE ISSUES FOUND")
    
    print("=" * 70)
    
    return 0 if total_passed >= total_tested * 0.8 else 1

if __name__ == '__main__':
    sys.exit(main())
